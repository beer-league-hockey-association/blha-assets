"""NHL schedule reader (read-only) for lineup planning.

Endpoint: ``GET https://api-web.nhle.com/v1/schedule/{YYYY-MM-DD}`` returns
``{"gameWeek": [{"date": "YYYY-MM-DD", "games": [...]}, ...]}`` for the seven
days starting at that date. Each game has ``homeTeam.abbrev``,
``awayTeam.abbrev``, ``startTimeUTC`` and ``gameType`` (1 preseason,
2 regular season, 3 playoffs). Only regular-season games (2) count.

UNVERIFIED: this shape is the NHL's publicly documented one. It has not been
checked against a live response from this repository (the build environment
cannot reach the NHL API). The parser is tolerant: a game missing a team or a
date is skipped, and ``abbrev`` may be a plain string or {"default": "TOR"}.
Tests use the synthetic fixture tests/fixtures/nhl_schedule_synthetic.json.

A game's night is its start time converted to league time (Eastern), falling
back to the gameWeek ``date`` when the start time is missing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .season import parse_dt

SCHEDULE_URL = "https://api-web.nhle.com/v1/schedule/{date}"
REGULAR_SEASON = 2
LIGHT_NIGHT_MAX_TEAMS = 8
HEAVY_NIGHT_MIN_TEAMS = 20
MAX_FETCHES = 6  # a 14-day Fantrax period needs 2-3; this is only a safety stop


@dataclass(frozen=True)
class Game:
    game_id: str
    night: date            # local (league time zone) date
    start: datetime | None  # aware, UTC
    away: str
    home: str
    game_type: int

    @property
    def teams(self) -> tuple[str, str]:
        return self.away, self.home


def _abbrev(team: Any) -> str:
    value = team.get("abbrev") if isinstance(team, dict) else None
    if isinstance(value, dict):
        value = value.get("default")
    return str(value or "").strip().upper()


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def schedule_dates(raw: Any) -> list[date]:
    days = raw.get("gameWeek") if isinstance(raw, dict) else None
    return sorted(d for d in (_date(day.get("date")) for day in days or [] if isinstance(day, dict)) if d)


def parse_schedule(raw: Any, tz: ZoneInfo) -> list[Game]:
    games: list[Game] = []
    days = raw.get("gameWeek") if isinstance(raw, dict) else None
    for day in days if isinstance(days, list) else []:
        if not isinstance(day, dict):
            continue
        day_date = _date(day.get("date"))
        for item in day.get("games") or []:
            if not isinstance(item, dict):
                continue
            start = parse_dt(item.get("startTimeUTC"))
            night = start.astimezone(tz).date() if start else day_date
            away, home = _abbrev(item.get("awayTeam")), _abbrev(item.get("homeTeam"))
            if not (away and home and night):
                continue
            try:
                game_type = int(item.get("gameType") or 0)
            except (TypeError, ValueError):
                game_type = 0
            game_id = str(item.get("id") or f"{night.isoformat()}-{away}-{home}")
            games.append(Game(game_id, night, start, away, home, game_type))
    return games


def http_get_json(url: str) -> Any:
    import requests

    response = requests.get(url, headers={"User-Agent": "BLHA-Automation/2.0"}, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_schedule(
    first: date,
    last: date,
    tz: ZoneInfo,
    get: Callable[[str], Any] | None = None,
) -> list[Game]:
    """Every NHL game from ``first`` through ``last`` (local dates), any type."""
    get = get or http_get_json
    found: dict[str, Game] = {}
    day = first
    for _ in range(MAX_FETCHES):
        if day > last:
            break
        raw = get(SCHEDULE_URL.format(date=day.isoformat()))
        for game in parse_schedule(raw, tz):
            found[game.game_id] = game
        dates = schedule_dates(raw)
        day = max(day + timedelta(days=1), (dates[-1] + timedelta(days=1)) if dates else day + timedelta(days=7))
    return sorted(found.values(), key=lambda g: (g.night, g.start.isoformat() if g.start else "", g.away))


def regular_season(games: list[Game]) -> list[Game]:
    return [g for g in games if g.game_type == REGULAR_SEASON]


def in_period(game: Game, start: datetime, end: datetime, tz: ZoneInfo) -> bool:
    """Whether a game belongs to the Fantrax period running start..end (UTC).

    Fantrax periods begin and end at the first NHL game of a day, so the start
    time decides. Without a start time, the local dates decide (the end day's
    games belong to the next period).
    """
    if game.start is not None:
        return start <= game.start <= end
    return start.astimezone(tz).date() <= game.night < end.astimezone(tz).date()


def games_on(games: list[Game], night: date) -> dict[str, Game]:
    """Regular-season games on one local night, keyed by team abbreviation."""
    playing: dict[str, Game] = {}
    for game in regular_season(games):
        if game.night == night:
            for team in game.teams:
                playing.setdefault(team, game)
    return playing


# --- Weekly games grid --------------------------------------------------------

@dataclass
class WeekGrid:
    games_by_team: dict[str, int]
    back_to_backs: dict[str, list[tuple[date, date]]]
    nights: list[tuple[date, int]]  # (night, teams playing), nights with games only
    light_max: int = LIGHT_NIGHT_MAX_TEAMS
    heavy_min: int = HEAVY_NIGHT_MIN_TEAMS
    total_games: int = 0

    def by_count(self) -> list[tuple[int, list[str]]]:
        groups: dict[int, list[str]] = defaultdict(list)
        for team, count in self.games_by_team.items():
            groups[count].append(team)
        return [(count, sorted(groups[count])) for count in sorted(groups, reverse=True)]

    @property
    def light_nights(self) -> list[tuple[date, int]]:
        return [(night, teams) for night, teams in self.nights if teams <= self.light_max]

    @property
    def heavy_nights(self) -> list[tuple[date, int]]:
        return [(night, teams) for night, teams in self.nights if teams >= self.heavy_min]


def week_grid(
    games: list[Game],
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    *,
    light_max: int = LIGHT_NIGHT_MAX_TEAMS,
    heavy_min: int = HEAVY_NIGHT_MIN_TEAMS,
) -> WeekGrid:
    """Games per team, back-to-backs and light/heavy nights for one period.

    Teams that appear anywhere in the fetched schedule but have no game in the
    period are listed with 0 games.
    """
    season_games = regular_season(games)
    week = [g for g in season_games if in_period(g, start, end, tz)]
    counts: dict[str, int] = {team: 0 for g in season_games for team in g.teams}
    nights_by_team: dict[str, set[date]] = defaultdict(set)
    teams_by_night: dict[date, set[str]] = defaultdict(set)
    for game in week:
        for team in game.teams:
            counts[team] = counts.get(team, 0) + 1
            nights_by_team[team].add(game.night)
            teams_by_night[game.night].add(team)

    b2b: dict[str, list[tuple[date, date]]] = {}
    for team, nights in nights_by_team.items():
        ordered = sorted(nights)
        pairs = [(a, b) for a, b in zip(ordered, ordered[1:]) if (b - a).days == 1]
        if pairs:
            b2b[team] = pairs

    return WeekGrid(
        games_by_team=counts,
        back_to_backs=dict(sorted(b2b.items())),
        nights=[(night, len(teams)) for night, teams in sorted(teams_by_night.items())],
        light_max=light_max,
        heavy_min=heavy_min,
        total_games=len(week),
    )


# --- Final scores and goal scorers ------------------------------------------------
#
# Endpoint: ``GET https://api-web.nhle.com/v1/score/{YYYY-MM-DD}`` returns
# ``{"games": [...]}`` for one date. Each game has ``id``, ``gameType``,
# ``gameState`` (FUT, PRE, LIVE, CRIT, FINAL, OFF), ``startTimeUTC``,
# ``awayTeam.abbrev``, ``homeTeam.abbrev`` and ``goals``: one entry per goal in
# order, with ``playerId``, ``firstName.default``, ``lastName.default``
# (or ``name.default``), ``teamAbbrev`` and ``periodDescriptor.periodType``
# (REG, OT or SO; shootout goals are not real goals and are skipped).
#
# UNVERIFIED: like the schedule, this is the NHL's publicly documented shape and
# has not been checked against a live response from this repository. The parser
# is tolerant: a goal without a player is skipped, and ``teamAbbrev`` or a name
# may be a plain string or {"default": ...}.

SCORE_URL = "https://api-web.nhle.com/v1/score/{date}"
FINISHED_STATES = {"FINAL", "OFF"}
IN_PROGRESS_STATES = {"LIVE", "CRIT"}


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("default")
    return str(value or "").strip()


@dataclass(frozen=True)
class Goal:
    player_id: str
    name: str   # "First Last"
    team: str   # the scorer's NHL team


@dataclass(frozen=True)
class ScoredGame:
    game_id: str
    game_type: int
    state: str
    start: datetime | None
    away: str
    home: str
    goals: tuple[Goal, ...]

    @property
    def finished(self) -> bool:
        return self.state in FINISHED_STATES

    def opponent(self, team: str) -> str:
        return self.home if team == self.away else self.away


def parse_scores(raw: Any) -> list[ScoredGame]:
    """Games from one /v1/score/{date} response, goals in scoring order.

    Raises ValueError when the response has no ``games`` list (an error body
    or an API change), so it is not mistaken for a night without games.
    """
    items = raw.get("games") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("NHL score response has no games list (API changed?)")
    games: list[ScoredGame] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        away, home = _abbrev(item.get("awayTeam")), _abbrev(item.get("homeTeam"))
        try:
            game_type = int(item.get("gameType") or 0)
        except (TypeError, ValueError):
            game_type = 0
        goals: list[Goal] = []
        for goal in item.get("goals") or []:
            if not isinstance(goal, dict) or not goal.get("playerId"):
                continue
            period = goal.get("periodDescriptor") if isinstance(goal.get("periodDescriptor"), dict) else {}
            if str(period.get("periodType") or "").upper() == "SO":
                continue
            name = " ".join(x for x in (_text(goal.get("firstName")), _text(goal.get("lastName"))) if x)
            team = _text(goal.get("teamAbbrev")).upper()
            goals.append(Goal(str(goal["playerId"]), name or _text(goal.get("name")), team))
        games.append(ScoredGame(
            game_id=str(item.get("id") or f"{away}-{home}"),
            game_type=game_type,
            state=str(item.get("gameState") or "").upper(),
            start=parse_dt(item.get("startTimeUTC")),
            away=away,
            home=home,
            goals=tuple(goals),
        ))
    return games


@dataclass(frozen=True)
class MultiGoal:
    game: ScoredGame
    goal: Goal       # the scorer
    goals: int       # his goals in the game
    order: int       # 0-based position of his ``threshold``-th goal in the game's goals


def multi_goal_games(game: ScoredGame, threshold: int = 3) -> list[MultiGoal]:
    """Players with at least ``threshold`` goals in one game (a hat trick at 3)."""
    counts: dict[str, int] = {}
    reached: dict[str, int] = {}
    first: dict[str, Goal] = {}
    for index, goal in enumerate(game.goals):
        counts[goal.player_id] = counts.get(goal.player_id, 0) + 1
        first.setdefault(goal.player_id, goal)
        if counts[goal.player_id] == threshold:
            reached[goal.player_id] = index
    return [MultiGoal(game, first[pid], counts[pid], order) for pid, order in sorted(reached.items(), key=lambda x: x[1])]
