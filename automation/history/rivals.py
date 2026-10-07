"""Lifetime head-to-head records and rivalries from the archive's final weekly results.

Every finished matchup in every counted season adds a game to both franchises'
records (regular season and playoffs; weeks where nothing was played are
skipped). Rivals come from two places:

  declared  pairs listed under ``rivals:`` in automation/league.yaml
  earned    each franchise's opponent with the most games played against it;
            ties go to the closest record (smallest gap between wins and
            losses), then the most recent meeting, then name
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from history.context import LeagueHistory
from history.store import Archive


@dataclass
class Record:
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    playoff_games: int = 0
    last: tuple[int, int] | None = None   # (season, period) of the latest meeting

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def text(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ties}"

    @property
    def gap(self) -> int:
        return abs(self.wins - self.losses)

    def add(self, mine: float, theirs: float, playoff: bool, when: tuple[int, int]) -> None:
        if mine > theirs:
            self.wins += 1
        elif mine < theirs:
            self.losses += 1
        else:
            self.ties += 1
        self.points_for += mine
        self.points_against += theirs
        self.playoff_games += int(playoff)
        if self.last is None or when > self.last:
            self.last = when


class HeadToHead:
    def __init__(self, hist: LeagueHistory) -> None:
        self.hist = hist
        self.pairs: dict[tuple[str, str], Record] = {}
        for season in hist.seasons:
            for key, week in sorted(hist.archive.results(season).items(), key=lambda kv: int(kv[0])):
                if not isinstance(week, dict) or not week.get("played", True):
                    continue
                for m in week.get("matchups") or []:
                    a, b = hist.franchise(m["away"]["team"]), hist.franchise(m["home"]["team"])
                    if not a or not b or a == b:
                        continue
                    when = (season, int(week.get("period") or key))
                    playoff = bool(week.get("playoff"))
                    sa, sb = float(m["away"]["score"]), float(m["home"]["score"])
                    self.pairs.setdefault((a, b), Record()).add(sa, sb, playoff, when)
                    self.pairs.setdefault((b, a), Record()).add(sb, sa, playoff, when)

    def record(self, a: str, b: str) -> Record:
        return self.pairs.get((a, b), Record())

    def opponents(self, a: str) -> dict[str, Record]:
        return {b: r for (x, b), r in self.pairs.items() if x == a}

    def franchises(self) -> list[str]:
        keys = self.hist.franchise_keys()
        for a, _ in self.pairs:
            if a not in keys:
                keys.append(a)
        return keys

    def lifetime(self, a: str) -> Record:
        total = Record()
        for r in self.opponents(a).values():
            total.wins += r.wins
            total.losses += r.losses
            total.ties += r.ties
            total.points_for += r.points_for
            total.points_against += r.points_against
            total.playoff_games += r.playoff_games
        return total

    def earned_rival(self, a: str) -> str | None:
        opponents = [(b, r) for b, r in self.opponents(a).items() if r.games]
        if not opponents:
            return None
        opponents.sort(key=lambda br: (-br[1].games, br[1].gap, tuple(-x for x in (br[1].last or (0, 0))),
                                       self.hist.name(br[0]).lower()))
        return opponents[0][0]

    def matrix(self) -> tuple[list[str], list[list[Record | None]]]:
        keys = self.franchises()
        return keys, [[None if a == b else self.record(a, b) for b in keys] for a in keys]


def declared_rivals(hist: LeagueHistory) -> list[tuple[str, str]]:
    """Pairs from league.yaml ``rivals:`` as franchise keys. Entries may be franchise keys, team ids or names."""
    out = []
    for pair in hist.league.get("rivals") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        keys = []
        for item in pair:
            text = str(item)
            key = hist.records.resolve(text)
            if key is None:
                by_name = {v.lower(): k for k, v in hist.team_names.items()}
                team_id = text if text in hist.team_names else by_name.get(text.lower())
                key = hist.franchise(team_id) if team_id else None
            keys.append(key)
        if all(keys) and keys[0] != keys[1]:
            out.append((keys[0], keys[1]))
    return out


def is_declared(hist: LeagueHistory, a: str, b: str) -> bool:
    return any({a, b} == {x, y} for x, y in declared_rivals(hist))


def rivalry_note(team_a_id: str, team_b_id: str, archive: Archive | LeagueHistory | Path | str | None = None,
                 **kwargs: Any) -> str:
    """One line about this pairing for the weekly preview, from team A's side.

    "Rivals: lifetime 3-2-1"            declared in league.yaml rivals:
    "Rivals (most played): lifetime …"  either team's earned rival is the other
    "Lifetime 3-2-1"                    they have met before
    "First meeting"                     they never have

    ``archive`` may be an Archive, a LeagueHistory, an archive folder, or None
    for the default archive/. Extra keyword arguments go to LeagueHistory
    (records=, league=).
    """
    hist = archive if isinstance(archive, LeagueHistory) else LeagueHistory(archive, **kwargs)
    h2h = HeadToHead(hist)
    a, b = hist.franchise(team_a_id), hist.franchise(team_b_id)
    record = h2h.record(a, b)
    if is_declared(hist, a, b):
        return f"Rivals: lifetime {record.text}"
    if record.games and (h2h.earned_rival(a) == b or h2h.earned_rival(b) == a):
        return f"Rivals (most played): lifetime {record.text}"
    return f"Lifetime {record.text}" if record.games else "First meeting"
