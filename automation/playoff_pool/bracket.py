"""The NHL playoff bracket: who is in, who is out, and who won the Cup.

Reads ``/v1/playoff-bracket/{year}``: ``{"series": [...]}`` where each series
has ``playoffRound`` (1-4), ``seriesLetter``, ``topSeedTeam`` and
``bottomSeedTeam`` (each with ``id`` and ``abbrev``), ``topSeedWins``,
``bottomSeedWins`` and, once decided, ``winningTeamId`` / ``losingTeamId``.
A series whose teams are not known yet has no team (or no abbrev) on that
side. UNVERIFIED shape; see nhl_feed.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .nhl_feed import text

WINS_NEEDED = 4
FIELD_SIZE = 16
FINAL_ROUND = 4


@dataclass(frozen=True)
class Series:
    round: int
    letter: str
    top: str          # team abbreviation, "" if not known yet
    bottom: str
    top_wins: int
    bottom_wins: int
    winner: str       # "" until decided
    loser: str
    names: tuple[tuple[str, str], ...] = ()  # (abbrev, display name) for both teams

    @property
    def decided(self) -> bool:
        return bool(self.winner)


def _team(raw: Any) -> tuple[str, str, str]:
    """(id, abbrev, display name) of a bracket team."""
    if not isinstance(raw, dict):
        return "", "", ""
    abbrev = text(raw.get("abbrev")).upper()
    name = text(raw.get("name")) or text(raw.get("commonName")) or abbrev
    return str(raw.get("id") or ""), abbrev, name


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse(raw: Any) -> list[Series]:
    rows = raw.get("series") if isinstance(raw, dict) else None
    out: list[Series] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        top_id, top, top_name = _team(row.get("topSeedTeam"))
        bottom_id, bottom, bottom_name = _team(row.get("bottomSeedTeam"))
        top_wins, bottom_wins = _int(row.get("topSeedWins")), _int(row.get("bottomSeedWins"))
        winner = loser = ""
        won = str(row.get("winningTeamId") or "")
        if won and top and bottom and won in (top_id, bottom_id):
            winner, loser = (top, bottom) if won == top_id else (bottom, top)
        elif top and bottom and max(top_wins, bottom_wins) >= WINS_NEEDED:
            winner, loser = (top, bottom) if top_wins > bottom_wins else (bottom, top)
        out.append(Series(_int(row.get("playoffRound")), str(row.get("seriesLetter") or "").upper(),
                          top, bottom, top_wins, bottom_wins, winner, loser,
                          tuple((a, n) for a, n in ((top, top_name), (bottom, bottom_name)) if a)))
    return sorted(out, key=lambda s: (s.round, s.letter))


def field(series: list[Series]) -> list[str]:
    """The playoff teams, from the first round (16 once the field is set)."""
    teams = {t for s in series if s.round == 1 for t in (s.top, s.bottom) if t}
    return sorted(teams)


def field_set(series: list[Series]) -> bool:
    return len(field(series)) == FIELD_SIZE


def eliminated(series: list[Series]) -> set[str]:
    return {s.loser for s in series if s.loser}


def champion(series: list[Series]) -> str:
    """The Stanley Cup winner, "" until the Final is decided."""
    final = [s for s in series if s.round == FINAL_ROUND and s.decided]
    return final[0].winner if final else ""


def team_name(series: list[Series], abbrev: str) -> str:
    for s in series:
        for a, name in s.names:
            if a == abbrev and name:
                return name
    return abbrev
