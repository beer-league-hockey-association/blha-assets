"""The pool's 10 boxes, built once when the NHL playoff field is set.

  Boxes 1-8   skaters from the 16 playoff teams with at least ``min_games``
              regular-season games, ranked by points per game and split into
              tiers of ``players_per_box`` (box 1 = the top tier)
  Box 9       Dark Horses: the next ``players_per_box`` skaters after skipping
              ``dark_horse_gap`` more below box 8 (a mid-tier list)
  Box 10      Goalies: each playoff team's likely starter (most regular-season
              games started), most starts first

A player traded away from a playoff team still shows in that club's stats, so
the current roster (``/roster/{team}/current``) filters them out. When a
roster can't be read the filter is skipped for that team (logged).

Every owner picks one player from each box, so there is no draft order and
nobody gains anything from pick position. Once posted, the boxes never change.
Each player has an option number within his box (1, 2, 3...), which owners can
use when they DM their picks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .nhl_feed import number, text

SKATER = "skater"
GOALIE = "goalie"
BOX_COUNT = 10
SELECT_MAX = 25  # Discord select menus hold at most 25 options
MAX_PER_BOX = 10  # keeps the boxes post inside Discord's 6,000-character message limit


@dataclass
class Settings:
    webhook: str = "BLHA_WEBHOOK_GAME_DAY"
    players_per_box: int = 8
    min_games: int = 20
    skater_boxes: int = 8
    dark_horse_gap: int = 8
    standings_time: str = "07:30"
    entries_via: str = "dm"  # dm: owners DM the Commissioner; bot: /pool pick in the League Bot

    @classmethod
    def from_cfg(cls, raw: Any) -> "Settings":
        raw = raw if isinstance(raw, dict) else {}
        s = cls()
        for key in ("webhook", "standings_time", "entries_via"):
            if raw.get(key):
                setattr(s, key, str(raw[key]).strip())
        for key in ("players_per_box", "min_games", "dark_horse_gap"):
            if raw.get(key) is not None:
                setattr(s, key, int(raw[key]))
        if not 2 <= s.players_per_box <= MAX_PER_BOX:
            raise ValueError(f"playoff_pool.players_per_box must be 2 to {MAX_PER_BOX}")
        if s.min_games < 0 or s.dark_horse_gap < 0:
            raise ValueError("playoff_pool.min_games and dark_horse_gap can't be negative")
        if s.entries_via not in ("dm", "bot"):
            raise ValueError("playoff_pool.entries_via must be dm or bot")
        return s


@dataclass
class Player:
    id: int
    name: str
    team: str
    pos: str
    gp: int = 0
    pts: int = 0
    ppg: float = 0.0
    gs: int = 0
    sv_pct: float = 0.0

    @property
    def goalie(self) -> bool:
        return self.pos == "G"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.team})"

    @property
    def stat(self) -> str:
        if self.goalie:
            return f"{self.gs} starts"
        return f"{self.ppg:.2f} pts/gm"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.goalie:
            d.pop("pts")
            d.pop("ppg")
        else:
            d.pop("gs")
            d.pop("sv_pct")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Player":
        return cls(int(d["id"]), str(d["name"]), str(d.get("team") or ""), str(d.get("pos") or ""),
                   int(d.get("gp") or 0), int(d.get("pts") or 0), float(d.get("ppg") or 0),
                   int(d.get("gs") or 0), float(d.get("sv_pct") or 0))


def norm(name: str) -> str:
    plain = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]+", "", plain.lower().replace("-", " ")).strip()


@dataclass
class Box:
    number: int
    title: str
    kind: str
    players: list[Player]

    def find(self, ref: Any) -> Player | None:
        """A player in this box by option number (1-99), NHL player id, or name."""
        if isinstance(ref, bool) or ref is None:
            return None
        raw = str(ref).strip().lstrip("#")
        if raw.isdigit():
            value = int(raw)
            if value < 100:
                return self.players[value - 1] if 1 <= value <= len(self.players) else None
            return next((p for p in self.players if p.id == value), None)
        wanted = norm(raw)
        if not wanted:
            return None
        exact = [p for p in self.players if norm(p.name) == wanted]
        if len(exact) == 1:
            return exact[0]
        last = [p for p in self.players if norm(p.name).split(" ")[-1] == wanted]
        return last[0] if len(last) == 1 else None

    def option(self, player_id: int) -> int:
        """1-based option number of a player in this box (0 if not here)."""
        return next((i for i, p in enumerate(self.players, 1) if p.id == player_id), 0)

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "title": self.title, "kind": self.kind,
                "players": [p.as_dict() for p in self.players]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Box":
        return cls(int(d["number"]), str(d["title"]), str(d["kind"]),
                   [Player.from_dict(p) for p in d.get("players") or []])


@dataclass
class Boxes:
    year: int
    season: str
    built_at: str
    teams: list[str]
    boxes: list[Box]
    deadline: datetime | None = None
    rules: dict[str, Any] = field(default_factory=dict)

    def box(self, number: int) -> Box | None:
        return next((b for b in self.boxes if b.number == number), None)

    def player(self, player_id: int) -> Player | None:
        for b in self.boxes:
            for p in b.players:
                if p.id == player_id:
                    return p
        return None

    def player_ids(self) -> set[int]:
        return {p.id for b in self.boxes for p in b.players}

    def locked(self, now: datetime) -> bool:
        """Picks lock at the first puck drop. Unknown deadline = still open."""
        return self.deadline is not None and now >= self.deadline

    def as_dict(self) -> dict[str, Any]:
        return {"year": self.year, "season": self.season, "built_at": self.built_at, "teams": self.teams,
                "deadline": self.deadline.isoformat() if self.deadline else None, "rules": self.rules,
                "boxes": [b.as_dict() for b in self.boxes]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Boxes":
        deadline = d.get("deadline")
        return cls(int(d["year"]), str(d.get("season") or ""), str(d.get("built_at") or ""),
                   [str(t) for t in d.get("teams") or []], [Box.from_dict(b) for b in d.get("boxes") or []],
                   datetime.fromisoformat(deadline) if deadline else None, dict(d.get("rules") or {}))


# --- Building ----------------------------------------------------------------------

def _name(row: dict[str, Any]) -> str:
    return f"{text(row.get('firstName'))} {text(row.get('lastName'))}".strip()


def skaters_of(raw: Any, team: str) -> list[Player]:
    """Regular-season skaters from /club-stats/{team}/{season}/2."""
    out = []
    for row in (raw.get("skaters") if isinstance(raw, dict) else None) or []:
        if not isinstance(row, dict) or not row.get("playerId"):
            continue
        gp = int(number(row.get("gamesPlayed")))
        pts = int(number(row.get("points")) or number(row.get("goals")) + number(row.get("assists")))
        out.append(Player(int(row["playerId"]), _name(row), team, text(row.get("positionCode")).upper() or "F",
                          gp=gp, pts=pts, ppg=round(pts / gp, 3) if gp else 0.0))
    return out


def goalies_of(raw: Any, team: str) -> list[Player]:
    out = []
    for row in (raw.get("goalies") if isinstance(raw, dict) else None) or []:
        if not isinstance(row, dict) or not row.get("playerId"):
            continue
        sv = number(row.get("savePercentage") if row.get("savePercentage") is not None else row.get("savePctg"))
        out.append(Player(int(row["playerId"]), _name(row), team, "G", gp=int(number(row.get("gamesPlayed"))),
                          gs=int(number(row.get("gamesStarted"))), sv_pct=round(sv, 3)))
    return out


def roster_ids(raw: Any) -> set[int] | None:
    """Player ids on /roster/{team}/current, or None if it couldn't be read."""
    if not isinstance(raw, dict):
        return None
    ids = {int(p["id"]) for group in ("forwards", "defensemen", "goalies")
           for p in raw.get(group) or [] if isinstance(p, dict) and str(p.get("id") or "").isdigit()}
    return ids or None


def build(
    year: int,
    season: str,
    teams: list[str],
    club_stats: dict[str, Any],
    rosters: dict[str, Any],
    settings: Settings,
    now: datetime,
    log: list[str] | None = None,
) -> Boxes:
    """The 10 boxes from each playoff team's regular-season stats.

    ``rosters`` maps team -> /roster/{team}/current (or None to skip that
    team's filter). Raises ValueError when there are too few eligible players.
    """
    log = log if log is not None else []
    skaters: dict[int, Player] = {}
    goalies: list[Player] = []
    for team in teams:
        on_roster = roster_ids(rosters.get(team))
        if on_roster is None:
            log.append(f"{team}: current roster unavailable; traded-away players not filtered")
        for p in skaters_of(club_stats.get(team), team):
            if on_roster is not None and p.id not in on_roster:
                continue
            if p.gp < settings.min_games:
                continue
            if p.id not in skaters or p.gp > skaters[p.id].gp:
                skaters[p.id] = p
        team_goalies = [g for g in goalies_of(club_stats.get(team), team)
                        if on_roster is None or g.id in on_roster]
        team_goalies.sort(key=lambda g: (-g.gs, -g.gp, -g.sv_pct, g.name))
        if team_goalies:
            goalies.append(team_goalies[0])
        else:
            log.append(f"{team}: no goalie found")

    ranked = sorted(skaters.values(), key=lambda p: (-(p.pts / p.gp if p.gp else 0), -p.pts, -p.gp, p.name, p.id))
    per = settings.players_per_box
    dark_start = settings.skater_boxes * per + settings.dark_horse_gap
    needed = dark_start + per
    if len(ranked) < needed:
        raise ValueError(f"only {len(ranked)} eligible skaters; the boxes need {needed}")
    boxes = [Box(i + 1, f"Box {i + 1}", SKATER, ranked[i * per:(i + 1) * per]) for i in range(settings.skater_boxes)]
    boxes.append(Box(settings.skater_boxes + 1, f"Box {settings.skater_boxes + 1}: Dark Horses", SKATER,
                     ranked[dark_start:dark_start + per]))
    goalies.sort(key=lambda g: (-g.gs, -g.sv_pct, g.name, g.id))
    if len(goalies) < 2:
        raise ValueError(f"only {len(goalies)} goalies found")
    boxes.append(Box(settings.skater_boxes + 2, f"Box {settings.skater_boxes + 2}: Goalies", GOALIE,
                     goalies[:SELECT_MAX]))
    rules = {"players_per_box": per, "min_games": settings.min_games, "dark_horse_ranks":
             [dark_start + 1, dark_start + per], "eligible_skaters": len(ranked)}
    return Boxes(year, season, now.isoformat(), sorted(teams), boxes, None, rules)
