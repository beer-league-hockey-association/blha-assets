"""Fantasy points a player has produced since a trade, scored the BLHA way from NHL game logs.

Scoring values come from the Constitution source (tools/constitution_source.py,
Article VIII), so they can never drift from the rules:

  skaters  Goal +5.00, Assist +2.95, Shot on Goal +0.55, Block +0.35, Hit +0.20,
           Penalty Minute -0.54
  goalies  Game Started +6.50, Save +0.49, Goal Against -5.00, Goalie Goal +5.00,
           Goalie Assist +2.95

Data (read-only, NHL public API, https://github.com/Zmalski/NHL-API-Reference):

  GET https://api-web.nhle.com/v1/player/{nhlId}/game-log/{season}/{gameType}
      season like 20262027, gameType 2 (regular season). Each ``gameLog`` row
      has gameId and gameDate; skaters goals, assists, shots, pim; goalies
      gamesStarted, shotsAgainst, goalsAgainst, goals, assists.
  GET https://api-web.nhle.com/v1/gamecenter/{gameId}/boxscore
      ``playerByGameStats.{awayTeam,homeTeam}.{forwards,defense,goalies}``
      rows with playerId, hits and blockedShots. Read only for the games a
      skater's game-log row has no hits/blockedShots (the game log does not
      carry them).

UNVERIFIED: the NHL-API-Reference lists these endpoints but not their fields,
and this repository cannot reach the NHL API from its build environment. The
field names above are the API's public ones (the same game log and landing
fields minors.py and history/retro.py read); the parser is tolerant, a missing
number counts as 0, and a boxscore that can't be read leaves that game's hits
and blocks out (the post says how many games).

Only NHL regular-season games count (Fantrax scores no NHL playoff games), and
every game counts no matter which BLHA team rosters the player afterwards.
Players are matched to NHL ids by name, narrowed by NHL team and position with
the Wire's normalizers (automation/wire/roster.py); an ambiguous name is left
unmatched rather than guessed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

AUTOMATION = Path(__file__).resolve().parents[1]
for folder in (AUTOMATION, AUTOMATION / "commissioner", AUTOMATION / "wire", AUTOMATION.parent / "tools"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import constitution_source as cs  # noqa: E402  (tools/constitution_source.py)
import roster  # noqa: E402  (wire/roster.py)

NHL = "https://api-web.nhle.com/v1"
SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
REGULAR_SEASON = 2

SKATER_STATS = {"Goal": "goals", "Assist": "assists", "Shot on Goal": "shots", "Block": "blockedShots",
                "Hit": "hits", "Penalty Minute": "pim"}
GOALIE_STATS = {"Game Started": "gamesStarted", "Save": "saves", "Goal Against": "goalsAgainst",
                "Goalie Goal": "goals", "Goalie Assist": "assists"}
BOX_ONLY = ("hits", "blockedShots")


def _values(table: list[tuple[str, str]], stats: dict[str, str]) -> dict[str, float]:
    out = {}
    for label, value in table:
        if label not in stats:
            raise ValueError(f"constitution_source has a scoring category this module doesn't know: {label}")
        out[stats[label]] = float(value.replace("−", "-"))
    missing = set(stats) - {label for label, _ in table}
    if missing:
        raise ValueError(f"constitution_source is missing scoring categories: {sorted(missing)}")
    return out


SKATER = _values(cs.SKATERS, SKATER_STATS)
GOALIE = _values(cs.GOALIES, GOALIE_STATS)


def _n(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def game_points(row: dict[str, Any], goalie: bool) -> float:
    """BLHA fantasy points for one game-log row (with hits/blockedShots already merged in for skaters)."""
    if goalie:
        saves = row.get("saves")
        saves = _n(row, "saves") if saves is not None else max(_n(row, "shotsAgainst") - _n(row, "goalsAgainst"), 0.0)
        return (GOALIE["gamesStarted"] * _n(row, "gamesStarted") + GOALIE["saves"] * saves
                + GOALIE["goalsAgainst"] * _n(row, "goalsAgainst") + GOALIE["goals"] * _n(row, "goals")
                + GOALIE["assists"] * _n(row, "assists"))
    return sum(points * _n(row, stat) for stat, points in SKATER.items())


def nhl_season(day: date) -> int:
    """The NHL season a date falls in, as the API writes it (2027-01-15 -> 20262027). Seasons turn over July 1."""
    start = day.year if day.month >= 7 else day.year - 1
    return start * 10000 + start + 1


def seasons_between(first: date, last: date) -> list[int]:
    a, b = nhl_season(first) // 10000, nhl_season(last) // 10000
    return [y * 10000 + y + 1 for y in range(a, b + 1)]


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def box_rows(raw: Any) -> dict[str, dict[str, Any]]:
    """playerId -> boxscore row, for every player in a /gamecenter/{id}/boxscore answer."""
    out: dict[str, dict[str, Any]] = {}
    stats = raw.get("playerByGameStats") if isinstance(raw, dict) else None
    for side in ("awayTeam", "homeTeam"):
        team = (stats or {}).get(side) or {}
        for group in ("forwards", "defense", "goalies"):
            for row in team.get(group) or []:
                if isinstance(row, dict) and row.get("playerId") is not None:
                    out[str(row["playerId"])] = row
    return out


@dataclass
class Production:
    """One player's BLHA points from NHL games after the trade."""
    nhl_id: int | None
    points: float = 0.0
    games: int = 0
    goalie: bool = False
    missing_box: int = 0          # skater games whose hits/blocks couldn't be read
    error: str = ""               # set when the NHL data couldn't be read at all
    by_game: list[tuple[str, float]] = field(default_factory=list)


def _pos(code: Any) -> str:
    """NHL positionCode (C, L, R, D, G) -> a Fantrax-style position for roster.position_group."""
    text = str(code or "").upper()
    return {"L": "LW", "R": "RW"}.get(text, text)


class NhlStats:
    """NHL reads with one shared getter (tests pass a fake) and a per-run boxscore cache."""

    def __init__(self, get: Callable[..., Any] | None = None) -> None:
        if get is None:
            import requests

            import minors  # automation/commissioner/minors.py: rate-limited NHL reads with retries

            session = requests.Session()
            session.headers["User-Agent"] = "BLHA-Trade-Desk/1.0"
            get = lambda url, **params: minors._get(session, url, **params)  # noqa: E731
        self.get = get
        self.boxes: dict[str, dict[str, dict[str, Any]]] = {}

    def find_id(self, name: str, team: str = "", position: str = "") -> int | None:
        """NHL player id for a Fantrax player ("Last, First", NHL team, position), or None if unsure."""
        wanted = roster.normalize_player_name(name)
        if not wanted:
            return None
        if name.count(",") == 1:  # Fantrax writes "Last, First"
            last, first = (part.strip() for part in name.split(",", 1))
            name = f"{first} {last}"
        hits = self.get(SEARCH, culture="en-us", limit=20, q=name) or []
        same = [h for h in hits if isinstance(h, dict) and h.get("playerId")
                and roster.normalize_player_name(str(h.get("name") or "")) == wanted]
        code, group = roster.normalize_team(team), roster.position_group(position)
        if code and len(same) > 1:
            same = [h for h in same if code in (roster.normalize_team(h.get("teamAbbrev")),
                                                roster.normalize_team(h.get("lastTeamAbbrev")))] or same
        if group and len(same) > 1:
            same = [h for h in same if roster.position_group(_pos(h.get("positionCode"))) == group] or same
        if len(same) != 1:
            return None
        try:
            return int(same[0]["playerId"])
        except (TypeError, ValueError):
            return None

    def game_log(self, nhl_id: int, season_id: int) -> list[dict[str, Any]]:
        raw = self.get(f"{NHL}/player/{nhl_id}/game-log/{season_id}/{REGULAR_SEASON}") or {}
        rows = raw.get("gameLog") if isinstance(raw, dict) else None
        return [r for r in rows or [] if isinstance(r, dict)]

    def box_row(self, game_id: Any, nhl_id: int) -> dict[str, Any] | None:
        key = str(game_id)
        if key not in self.boxes:
            try:
                self.boxes[key] = box_rows(self.get(f"{NHL}/gamecenter/{key}/boxscore") or {})
            except Exception as exc:  # noqa: BLE001 - one missing boxscore only loses that game's hits/blocks
                print(f"NHL WARNING: boxscore {key} could not be read ({exc.__class__.__name__})")
                self.boxes[key] = {}
        return self.boxes[key].get(str(nhl_id))

    def production(self, nhl_id: int | None, goalie: bool, after: date, through: date) -> Production:
        """Points from NHL regular-season games played after ``after`` (the trade date) through ``through``."""
        out = Production(nhl_id, goalie=goalie)
        if nhl_id is None:
            out.error = "not matched to an NHL player"
            return out
        try:
            rows = [r for sid in seasons_between(after, through) for r in self.game_log(nhl_id, sid)]
        except Exception as exc:  # noqa: BLE001 - reported per player
            out.error = f"NHL game log unavailable ({exc.__class__.__name__})"
            return out
        for row in rows:
            day = _day(row.get("gameDate"))
            if day is None or not (after < day <= through):
                continue
            row = dict(row)
            goalie_row = goalie or "shotsAgainst" in row or "goalsAgainst" in row
            if goalie_row and row.get("gamesStarted") is None:
                box = self.box_row(row.get("gameId"), nhl_id) or {}
                row["gamesStarted"] = 1 if box.get("starter") else 0
            if not goalie_row and any(row.get(k) is None for k in BOX_ONLY):
                box = self.box_row(row.get("gameId"), nhl_id)
                if box is None:
                    out.missing_box += 1
                else:
                    for k in BOX_ONLY:
                        if row.get(k) is None:
                            row[k] = box.get(k)
            pts = game_points(row, goalie_row)
            out.goalie = out.goalie or goalie_row
            out.points += pts
            out.games += 1
            out.by_game.append((str(row.get("gameDate"))[:10], round(pts, 2)))
        out.points = round(out.points, 2)
        return out
