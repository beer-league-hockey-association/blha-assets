"""Tag Wire stories with the BLHA team that rosters the player.

How matching works:
- Fantrax's getTeamRosters gives player IDs per BLHA team; getPlayerIds gives
  every NHL player's name ("Last, First"), NHL team and position.
- Several real players share a name (two Sebastian Ahos, two Elias
  Petterssons on the same NHL team, two Jack Hugheses). A story is only
  tagged when the player can be identified unambiguously:
    * Injury report entries carry the player's NHL team and position, so
      those are used to pick the right player.
    * Headlines are scanned for full names of rostered players. If another
      NHL player shares that name, the headline is not tagged.
- Wrong tags are worse than missing tags, so anything ambiguous is skipped.

Owner pings (opt-in) are configured in automation/league.yaml under
``owners`` and ``wire_pings``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Common alternate NHL team codes -> Fantrax's codes.
TEAM_ALIASES = {
    "NJ": "NJD", "TB": "TBL", "LA": "LAK", "SJ": "SJS", "VEG": "VGK", "LV": "VGK",
    "WAS": "WSH", "MON": "MTL", "CLB": "CBJ", "CLS": "CBJ", "NAS": "NSH", "UTAH": "UTA",
    "UHC": "UTA", "WIN": "WPG", "CAL": "CGY", "NYIS": "NYI",
}
FORWARD = {"C", "LW", "RW", "F"}


def normalize_player_name(value: str) -> str:
    raw = str(value or "").strip()
    if raw.count(",") == 1:
        last, first = (part.strip() for part in raw.split(",", 1))
        if last and first:
            raw = f"{first} {last}"
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_team(code: Any) -> str:
    text = str(code or "").strip().upper()
    return TEAM_ALIASES.get(text, text)


def position_group(position: Any) -> str:
    text = str(position or "").upper()
    first = text.split(",")[0].strip()
    if first in FORWARD:
        return "F"
    if first in ("D", "G"):
        return first
    return ""


@dataclass
class Player:
    player_id: str
    name: str
    team: str
    group: str
    owner_id: str = ""
    owner_name: str = ""


@dataclass
class RosterIndex:
    by_name: dict[str, list[Player]] = field(default_factory=dict)
    rostered_names: set[str] = field(default_factory=set)
    _pattern: re.Pattern | None = None

    @property
    def empty(self) -> bool:
        return not self.rostered_names

    def match(self, name: str, team: str = "", position: str = "") -> Player | None:
        """Identify one player by name, narrowed by NHL team and position.

        Returns the rostered player, or None if not rostered or ambiguous.
        """
        candidates = list(self.by_name.get(normalize_player_name(name), []))
        if not candidates:
            return None
        team_code, group = normalize_team(team), position_group(position)
        if team_code and len(candidates) > 1:
            by_team = [p for p in candidates if p.team == team_code]
            candidates = by_team or candidates
        if group and len(candidates) > 1:
            by_pos = [p for p in candidates if p.group == group]
            candidates = by_pos or candidates
        if len(candidates) != 1:
            return None
        player = candidates[0]
        return player if player.owner_id else None

    def scan(self, text: str) -> list[Player]:
        """Rostered players named in a headline (unambiguous names only)."""
        if self.empty:
            return []
        if self._pattern is None:
            names = sorted(self.rostered_names, key=len, reverse=True)
            self._pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
        found: list[Player] = []
        seen: set[str] = set()
        for match in self._pattern.finditer(normalize_player_name(text)):
            key = match.group(1)
            if key in seen:
                continue
            seen.add(key)
            candidates = self.by_name.get(key, [])
            if len(candidates) == 1 and candidates[0].owner_id:
                found.append(candidates[0])
        return found


def build_index(rosters: dict[str, Any], players: dict[str, Any]) -> RosterIndex:
    """Join getTeamRosters with getPlayerIds into a name index."""
    owners: dict[str, tuple[str, str]] = {}
    block = rosters.get("rosters") if isinstance(rosters, dict) else None
    if isinstance(block, dict):
        for team_id, team in block.items():
            if not isinstance(team, dict):
                continue
            team_name = str(team.get("teamName") or team_id)
            for item in team.get("rosterItems") or []:
                if isinstance(item, dict) and item.get("id"):
                    owners[str(item["id"])] = (str(team_id), team_name)

    index = RosterIndex()
    for outer_id, raw in (players or {}).items():
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        ids = {str(outer_id), str(raw.get("fantraxId") or "")} - {""}
        owner_id, owner_name = next((owners[i] for i in ids if i in owners), ("", ""))
        player = Player(
            player_id=str(raw.get("fantraxId") or outer_id),
            name=str(raw["name"]),
            team=normalize_team(raw.get("team")),
            group=position_group(raw.get("position")),
            owner_id=owner_id,
            owner_name=owner_name,
        )
        key = normalize_player_name(player.name)
        if not key:
            continue
        index.by_name.setdefault(key, []).append(player)
        if owner_id:
            index.rostered_names.add(key)
    return index


def display_name(player: Player) -> str:
    """Fantrax lists names as "Last, First"; show "First Last"."""
    if player.name.count(",") == 1:
        last, first = (part.strip() for part in player.name.split(",", 1))
        return f"{first} {last}"
    return player.name


def tag_candidates(candidates: list[dict], index: RosterIndex) -> int:
    """Attach BLHA roster info to candidates in place. Returns tagged count."""
    tagged = 0
    for candidate in candidates:
        if candidate.get("player"):
            player = index.match(candidate["player"], candidate.get("team", ""), candidate.get("position", ""))
            matches = [player] if player else []
            show_player = False
        else:
            matches = index.scan(candidate.get("title", ""))
            show_player = True
        if not matches:
            continue
        candidate["owners"] = [
            {"team_id": p.owner_id, "team_name": p.owner_name, "player": display_name(p)}
            for p in matches
        ]
        if len(matches) == 1 and not show_player:
            candidate["fantasy_owner"] = matches[0].owner_name
        else:
            candidate["fantasy_owner"] = " • ".join(
                f"{p.owner_name} ({display_name(p)})" for p in matches
            )
        tagged += 1
    return tagged


def owner_mentions(candidate: dict, league: dict[str, Any]) -> list[str]:
    """Discord user IDs to ping for this story (opt-in owners only)."""
    pings = league.get("wire_pings") or {}
    if candidate.get("channel") != "injury-report" or not pings.get("injuries"):
        return []
    owners_cfg = {str(k).strip().lower(): str(v).strip() for k, v in (league.get("owners") or {}).items()}
    ids: list[str] = []
    for owner in candidate.get("owners") or []:
        user = owners_cfg.get(owner["team_id"].lower()) or owners_cfg.get(owner["team_name"].lower())
        if user and re.fullmatch(r"\d{15,21}", user) and user not in ids:
            ids.append(user)
    return ids


def load_index(league: dict[str, Any]) -> RosterIndex | None:
    """Fetch rosters and the player directory from Fantrax (None on failure)."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from blha.fantrax import Fantrax

    fx = Fantrax(str(league.get("league_id") or ""), user_agent="BLHA-Wire-Roster/2.0", timeout=20)
    try:
        rosters = fx.rosters()
    except Exception as exc:
        print(f"ROSTER TAGS WARNING: Fantrax roster read failed: {exc}")
        return None
    block = rosters.get("rosters") if isinstance(rosters, dict) else {}
    if isinstance(block, dict) and block and not any(
        (team or {}).get("rosterItems") for team in block.values() if isinstance(team, dict)
    ):
        print(f"ROSTER TAGS: all {len(block)} BLHA rosters are empty; tags start once players are rostered")
        return None
    try:
        players = fx.player_ids()
    except Exception as exc:
        print(f"ROSTER TAGS WARNING: Fantrax player directory read failed: {exc}")
        return None
    index = build_index(rosters, players)
    print(f"ROSTER TAGS: {len(index.rostered_names)} rostered players indexed")
    return index
