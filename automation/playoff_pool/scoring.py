"""Pool scoring: BLHA fantasy scoring (Constitution Article VIII) on NHL playoff games.

  Skaters  goal +5, assist +2.95, shot on goal +0.55, block +0.35, hit +0.20,
           penalty minute -0.54
  Goalies  game started +6.5, save +0.49, goal against -5, goal +5, assist +2.95

Points are kept in hundredths (integers) so totals and ties are exact.

Stats come from each playoff game's boxscore (``/v1/gamecenter/{id}/boxscore``):
``playerByGameStats.{awayTeam,homeTeam}.{forwards,defense,goalies}``. Skater
rows carry ``goals``, ``assists``, ``sog`` (older responses: ``shots``),
``blockedShots``, ``hits`` and ``pim``. Goalie rows carry ``saves`` (older:
``saveShotsAgainst`` as "28/30"), ``goalsAgainst`` and ``starter``; goals and
assists when present. If no goalie of a team is marked ``starter``, the one
with the most ice time is credited with the start. Only games whose
``gameState`` is OFF or FINAL count. UNVERIFIED shape; see nhl_feed.py.

Standings: total points, then the tiebreakers most points from the goalie
(box 10) and the earliest entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .nhl_feed import number

SKATER_POINTS = {"g": 500, "a": 295, "sog": 55, "blk": 35, "hit": 20, "pim": -54}
GOALIE_POINTS = {"gs": 650, "sv": 49, "ga": -500, "g": 500, "a": 295}
FINAL_STATES = {"OFF", "FINAL"}


def fmt(hundredths: int) -> str:
    sign = "-" if hundredths < 0 else ""
    value = abs(int(hundredths))
    return f"{sign}{value // 100}.{value % 100:02d}"


def _int(value: Any) -> int:
    return int(round(number(value)))


def _toi(value: Any) -> int:
    """'59:12' -> seconds."""
    try:
        minutes, seconds = str(value or "0:0").split(":", 1)
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


def _saves(row: dict[str, Any]) -> int:
    if row.get("saves") is not None:
        return _int(row.get("saves"))
    pair = str(row.get("saveShotsAgainst") or "")
    if "/" in pair:
        return _int(pair.split("/", 1)[0])
    return max(_int(row.get("shotsAgainst")) - _int(row.get("goalsAgainst")), 0)


def parse_boxscore(raw: Any) -> tuple[str, dict[int, dict[str, int]]]:
    """(gameState, player id -> stat line) for one game."""
    if not isinstance(raw, dict):
        return "", {}
    lines: dict[int, dict[str, int]] = {}
    stats = raw.get("playerByGameStats") or {}
    for side in ("awayTeam", "homeTeam"):
        team = stats.get(side) or {}
        for group in ("forwards", "defense", "defensemen"):
            for row in team.get(group) or []:
                if not isinstance(row, dict) or not row.get("playerId"):
                    continue
                lines[int(row["playerId"])] = {
                    "g": _int(row.get("goals")), "a": _int(row.get("assists")),
                    "sog": _int(row.get("sog") if row.get("sog") is not None else row.get("shots")),
                    "blk": _int(row.get("blockedShots")), "hit": _int(row.get("hits")),
                    "pim": _int(row.get("pim") if row.get("pim") is not None else row.get("penaltyMinutes")),
                }
        goalies = [r for r in team.get("goalies") or [] if isinstance(r, dict) and r.get("playerId")]
        marked = any("starter" in r for r in goalies)
        most_ice = max(goalies, key=lambda r: _toi(r.get("toi")), default=None)
        for row in goalies:
            started = bool(row.get("starter")) if marked else row is most_ice and _toi(row.get("toi")) > 0
            lines[int(row["playerId"])] = {
                "gs": int(started), "sv": _saves(row), "ga": _int(row.get("goalsAgainst")),
                "g": _int(row.get("goals")), "a": _int(row.get("assists")),
            }
    return str(raw.get("gameState") or "").upper(), lines


def line_points(line: dict[str, int], goalie: bool) -> int:
    table = GOALIE_POINTS if goalie else SKATER_POINTS
    return sum(weight * int(line.get(key) or 0) for key, weight in table.items())


def player_points(games: dict[str, Any], goalies: set[int]) -> dict[int, int]:
    """Player id -> playoff points so far, from the cached game lines."""
    out: dict[int, int] = {}
    for game in games.values():
        if not game.get("final"):
            continue
        for pid, line in (game.get("lines") or {}).items():
            pid = int(pid)
            out[pid] = out.get(pid, 0) + line_points(line, pid in goalies)
    return out


# --- Standings ---------------------------------------------------------------------

@dataclass
class Row:
    owner: str
    total: int
    goalie: int
    entered: datetime | None
    order: int
    picks: dict[int, int] = field(default_factory=dict)      # box -> player id
    points: dict[int, int] = field(default_factory=dict)     # box -> points
    best_box: int = 0
    out: int = 0                                              # picks whose team is eliminated


def standings(entries: list[Any], goalie_box: int, totals: dict[int, int], teams: dict[int, str],
              eliminated: set[str]) -> list[Row]:
    """Rows best first. ``entries`` have owner, picks (box -> id), entered, order."""
    rows = []
    for e in entries:
        points = {box: totals.get(pid, 0) for box, pid in e.picks.items()}
        best = max(sorted(points), key=lambda b: points[b], default=0)
        rows.append(Row(e.owner, sum(points.values()), points.get(goalie_box, 0), e.entered, e.order,
                        dict(e.picks), points, best,
                        sum(1 for pid in e.picks.values() if teams.get(pid) in eliminated)))
    # Entries without an entry time rank after timed ones, then by file order.
    return sorted(rows, key=lambda r: (-r.total, -r.goalie,
                                       r.entered.timestamp() if r.entered else float("inf"), r.order))


def tie_note(rows: list[Row], index: int) -> str:
    """Why row ``index`` is ahead of the next row when their totals are equal."""
    if index + 1 >= len(rows) or rows[index].total != rows[index + 1].total:
        return ""
    if rows[index].goalie != rows[index + 1].goalie:
        return "ahead on goalie points"
    return "ahead on earlier entry"
