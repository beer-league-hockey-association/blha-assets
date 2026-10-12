"""Schedule edge for the Monday matchup preview: projected games per franchise.

For every NHL game night in a Fantrax week, each franchise's active lineup is
filled from its rostered players whose NHL team plays that night:

  - slots: 3 C, 3 LW, 3 RW, 3 F (any forward), 6 D, 2 G (Constitution 6.2);
  - who counts: players on the ACTIVE or RESERVE part of the roster. MINORS
    and IR players are left out;
  - positions: the player's Fantrax positions (getPlayerIds, comma-separated
    when he has more than one) plus his roster slot;
  - skater slots are filled as fully as possible: a maximum matching, so a
    multi-position player goes wherever he lets the most players start;
  - goalies: up to 2 a night, one per NHL game (two goalies from the same NHL
    team cannot both start), and the week's total is capped at the credited
    goalie starts: 4 per calendar week, 8 for a two-week period (9.2, 9.3).

Projected games = the filled slots summed over the week. Light-night games =
the same count on light nights only (nights when few NHL teams play, as in the
NHL games grid). This is the most a manager could start with the current
roster; it says nothing about how good the players are.

A player whose NHL team is missing, or does not play anywhere in the fetched
schedule, adds nothing. All inputs are read-only.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from blha import nhl

_WIRE = str(Path(__file__).resolve().parents[1] / "wire")
if _WIRE not in sys.path:
    sys.path.append(_WIRE)

from roster import normalize_team  # noqa: E402  (wire/roster.py: NHL team code aliases)

SKATER_SLOTS = (("C", 3), ("LW", 3), ("RW", 3), ("F", 3), ("D", 6))
GOALIE_SLOTS = 2
FORWARDS = {"C", "LW", "RW", "F"}
KNOWN = FORWARDS | {"D", "G"}
LINEUP = ("ACTIVE", "RESERVE")


def positions_of(*values: Any) -> frozenset[str]:
    found: set[str] = set()
    for value in values:
        for part in re.split(r"[,/ ]+", str(value or "").upper()):
            if part in KNOWN:
                found.add(part)
    return frozenset(found)


@dataclass(frozen=True)
class RosterPlayer:
    player_id: str
    nhl_team: str
    positions: frozenset[str]

    @property
    def goalie(self) -> bool:
        return "G" in self.positions

    def skater_slots(self) -> set[str]:
        slots = {p for p in self.positions if p in ("C", "LW", "RW", "D")}
        if self.positions & FORWARDS:
            slots.add("F")
        return slots


def lineup_players(rosters: Any, players: Any) -> dict[str, list[RosterPlayer]] | None:
    """teamId -> players who can be in a lineup this week; None when every roster is empty."""
    block = rosters.get("rosters") if isinstance(rosters, dict) else None
    if not isinstance(block, dict) or not block:
        return None
    directory: dict[str, dict[str, Any]] = {}
    for key, raw in (players or {}).items() if isinstance(players, dict) else []:
        if isinstance(raw, dict):
            directory[str(key)] = raw
            if raw.get("fantraxId"):
                directory[str(raw["fantraxId"])] = raw
    teams: dict[str, list[RosterPlayer]] = {}
    any_items = False
    for team_id, team in block.items():
        if not isinstance(team, dict):
            continue
        squad: list[RosterPlayer] = []
        for item in team.get("rosterItems") or []:
            if not isinstance(item, dict):
                continue
            any_items = True
            if str(item.get("status") or "").upper() not in LINEUP:
                continue
            player_id = str(item.get("id") or "")
            info = directory.get(player_id) or {}
            positions = positions_of(info.get("position"), item.get("position"))
            team_code = normalize_team(info.get("team"))
            if positions and team_code:
                squad.append(RosterPlayer(player_id, team_code, positions))
        teams[str(team_id)] = squad
    return teams if any_items else None


def max_skaters(eligible: list[set[str]], slots: tuple[tuple[str, int], ...] = SKATER_SLOTS) -> int:
    """Most skaters that can start at once (maximum bipartite matching).

    ``eligible`` lists, per player, the slot types he may fill. Augmenting
    paths move an already-placed multi-position player to another of his
    slots when that frees a spot, so the result is the true maximum.
    """
    seats = [slot for slot, count in slots for _ in range(count)]
    holder = [-1] * len(seats)

    def place(player: int, tried: set[int]) -> bool:
        for seat, slot in enumerate(seats):
            if seat in tried or slot not in eligible[player]:
                continue
            tried.add(seat)
            if holder[seat] == -1 or place(holder[seat], tried):
                holder[seat] = player
                return True
        return False

    # Fewest options first: the result is the same, the search is shorter.
    order = sorted(range(len(eligible)), key=lambda i: len(eligible[i]))
    return sum(1 for player in order if eligible[player] and place(player, set()))


def nights_in_period(games: list[nhl.Game], start: datetime, end: datetime, tz: ZoneInfo) -> dict[date, set[str]]:
    """Local night -> NHL teams playing a regular-season game in the period."""
    nights: dict[date, set[str]] = {}
    for game in nhl.regular_season(games):
        if nhl.in_period(game, start, end, tz):
            nights.setdefault(game.night, set()).update(normalize_team(t) for t in game.teams)
    return dict(sorted(nights.items()))


@dataclass(frozen=True)
class Projection:
    games: int
    light_games: int
    skater_games: int
    goalie_games: int


def project(
    squad: list[RosterPlayer],
    nights: dict[date, set[str]],
    light_nights: set[date],
    goalie_cap: int,
) -> Projection:
    skaters = goalies = light_skaters = light_goalies = 0
    for night, playing in nights.items():
        tonight = [p for p in squad if p.nhl_team in playing]
        filled = max_skaters([p.skater_slots() for p in tonight if not p.goalie])
        in_net = min(GOALIE_SLOTS, len({p.nhl_team for p in tonight if p.goalie}))
        skaters += filled
        goalies += in_net
        if night in light_nights:
            light_skaters += filled
            light_goalies += in_net
    goalie_games = min(goalies, goalie_cap)
    return Projection(
        games=skaters + goalie_games,
        light_games=light_skaters + min(light_goalies, goalie_cap),
        skater_games=skaters,
        goalie_games=goalie_games,
    )


def projections(
    teams: dict[str, list[RosterPlayer]],
    games: list[nhl.Game],
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    *,
    goalie_cap: int,
    light_max: int = nhl.LIGHT_NIGHT_MAX_TEAMS,
) -> dict[str, Projection]:
    """teamId -> Projection for the period start..end (empty when no NHL games)."""
    nights = nights_in_period(games, start, end, tz)
    if not nights:
        return {}
    light = {night for night, playing in nights.items() if len(playing) <= light_max}
    return {team_id: project(squad, nights, light, goalie_cap) for team_id, squad in teams.items()}
