#!/usr/bin/env python3
"""BLHA Competition Desk: the weekly report.

On the morning a fantasy week ends (normally Monday, at report_time in
league.yaml), posts in order:

1. Weekly recap of the week that just finished, with each team's all-play
   record for the week and the season (📰│weekly-recap)
2. Weekly Awards for that week (📰│weekly-recap)
3. Power Rankings after that week (📰│weekly-recap)
4. League standings after that week
5. Playoff race (from playoff_race_start_week through the last regular week)
6. Matchup preview for the week that starts that evening, with each
   matchup's projected games (schedule edge, edge.py) when rosters are filled
   (scoreboard channel)
7. NHL games grid for that week, for planning daily lineups (scoreboard channel)
8. The Wooden Spoon for the last-place franchise, once, with the final
   regular-season standings (📰│weekly-recap; competition.wooden_spoon)

Also in 📰│weekly-recap, right after the power rankings:

- Monthly Awards (monthly.py; competition.monthly_awards), the morning the
  first week ending in a new month is reported, for the month before; the
  season's last month goes out with the final regular-season week.
- Bounty claims (bounties.py; competition.bounties), each announced once per
  Season. Team bounties are checked when a week is final; the hat-trick bounty
  is checked every run against the NHL scores of nights not checked yet, so a
  claim goes out the morning after.

All-play, awards, power rankings (with the Luck Index), monthly awards and
team bounties are computed from Fantrax matchup scores (see weekly.py); the
games grid reads the NHL schedule API (blha/nhl.py).

Standings and the playoff race wait until Fantrax has counted the finished
week in its standings. If Fantrax is not ready at 8:00 AM, those two go out
at the next check (8:00 PM). Nothing is ever posted twice for the same week.

Modes:
  preview  print what would be posted; no Discord, no state change
  test     send clearly labeled [TEST] posts; no state change
  live     post what is due and record it
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
if str(ROOT.parent / "wire") not in sys.path:
    sys.path.append(str(ROOT.parent / "wire"))  # after ours, so wire never shadows a desk module

import bounties  # noqa: E402
import edge  # noqa: E402
import monthly  # noqa: E402
import render  # noqa: E402
import roster  # noqa: E402  (wire/roster.py: match NHL scorers to BLHA rosters)
import weekly  # noqa: E402
from blha import nhl, season  # noqa: E402
from blha.fantrax import Fantrax, games_counted, schedule_for  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook  # noqa: E402

STATE_PATH = ROOT / "state" / "competition.json"
ITEMS = ("recap", "awards", "rankings", "monthly", "bounties", "standings", "race", "preview", "games", "spoon")
STATE_KEYS = {
    "recap": "recap_week",
    "awards": "awards_week",
    "rankings": "rankings_week",
    "monthly": "monthly_week",    # last week of the latest month posted
    "bounties": "bounties_week",  # last final week checked for team bounties
    "standings": "standings_week",
    "race": "race_week",
    "preview": "preview_week",
    "games": "games_week",
    "spoon": "spoon_week",
}
# Items added after the report went live go out with an older sibling. Until an
# item has its own state, it counts as posted up to the week its sibling last
# posted, so deploying mid-week never posts an old week's awards or grid.
SIBLING = {"awards": "recap", "rankings": "recap", "games": "preview", "spoon": "standings"}
# Previous weeks' power rankings kept in state (for the week-over-week change).
RANKS_KEPT = 4
# If Fantrax still has not counted a week this long after it officially
# closes, post the standings anyway rather than waiting forever.
STANDINGS_GRACE = timedelta(hours=2)


@dataclass
class Plan:
    item: str
    week: int


@dataclass
class ReportPlan:
    posts: list[Plan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def posted_week(state: dict[str, Any], item: str) -> int:
    """Last week this item was posted (see SIBLING for newer items)."""
    key = STATE_KEYS[item]
    if key not in state and item in SIBLING:
        key = STATE_KEYS[SIBLING[item]]
    return int(state.get(key) or 0)


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Give newer items their own state key, copied from their sibling."""
    state = dict(state)
    for item, sibling in SIBLING.items():
        if STATE_KEYS[item] not in state and STATE_KEYS[sibling] in state:
            state[STATE_KEYS[item]] = state[STATE_KEYS[sibling]]
    return state


def migrate_monthly(state: dict[str, Any], info: dict[str, Any], tz: ZoneInfo, comp: dict[str, Any]) -> None:
    """State saved before Monthly Awards existed: months already reported count as posted."""
    if comp.get("monthly_awards") and "monthly_week" not in state:
        last_regular, _, _ = season.playoff_settings(info)
        groups = monthly.month_groups(info, tz, last_regular)
        state["monthly_week"] = monthly.posted_baseline(groups, int(state.get("recap_week") or 0))


def bounties_due(
    info: dict[str, Any],
    state: dict[str, Any],
    now: datetime,
    tz: ZoneInfo,
    comp: dict[str, Any],
    done_week: int,
) -> bool:
    """Whether an open bounty has something new to check: a newly final week
    (team bounties) or a finished NHL night (the hat-trick bounty)."""
    configured, _ = bounties.load_bounties(comp)
    saved = bounty_state(state)
    still_open = [b for b in configured if b.id not in saved["claimed"]]
    if done_week and int(state.get("bounties_week") or 0) < done_week and any(
            b.type in bounties.TEAM_TYPES for b in still_open):
        return True
    if any(b.type == bounties.PLAYER_HAT_TRICK for b in still_open):
        last_regular, _, _ = season.playoff_settings(info)
        return bool(bounties.nights_to_check(info, tz, now, last_regular, saved["hat_trick_through"], limit=1))
    return False


def bounty_state(state: dict[str, Any]) -> dict[str, Any]:
    """The saved bounty state: {"claimed": {id: claim}, "hat_trick_through": "YYYY-MM-DD" | None}."""
    raw = state.get("bounties") if isinstance(state.get("bounties"), dict) else {}
    claimed = raw.get("claimed") if isinstance(raw.get("claimed"), dict) else {}
    through = raw.get("hat_trick_through")
    return {"claimed": claimed, "hat_trick_through": str(through) if through else None}


def _report_time(comp: dict[str, Any]) -> time:
    hour, minute = (int(x) for x in str(comp.get("report_time") or "08:00").split(":", 1))
    return time(hour, minute)


def plan_report(
    info: dict[str, Any],
    standings_rows: list[dict[str, Any]],
    state: dict[str, Any],
    now: datetime,
    tz: ZoneInfo,
    comp: dict[str, Any],
) -> ReportPlan:
    plan = ReportPlan()
    if now.astimezone(tz).time() < _report_time(comp):
        plan.notes.append(f"before report time {comp.get('report_time', '08:00')}")
        return plan

    last_regular, _, _ = season.playoff_settings(info)
    race_start = int(comp.get("playoff_race_start_week") or 16)
    done = season.latest_final(info, now, tz, through=last_regular)

    if done:
        week = done.number
        counted = games_counted(standings_rows)
        standings_ready = (counted is not None and counted >= week) or now >= done.end + STANDINGS_GRACE

        for item in ("recap", "awards", "rankings"):
            if posted_week(state, item) < week:
                plan.posts.append(Plan(item, week))

        if comp.get("monthly_awards"):
            groups = monthly.month_groups(info, tz, last_regular)
            if "monthly_week" in state:
                posted = int(state.get("monthly_week") or 0)
            else:
                posted = monthly.posted_baseline(groups, int(state.get("recap_week") or 0))
            due = monthly.due_groups(groups, week, posted)
            if not state:  # --force: repost the latest month only
                due = due[-1:]
            plan.posts.extend(Plan("monthly", g.last_week) for g in due)

        if bounties_due(info, state, now, tz, comp, week):
            plan.posts.append(Plan("bounties", week))

        if int(state.get("standings_week") or 0) < week:
            if standings_ready:
                plan.posts.append(Plan("standings", week))
            else:
                plan.notes.append(f"standings wait: Fantrax has counted {counted} of {week} weeks")

        spoon_on = comp.get("wooden_spoon", True) is not False
        if spoon_on and week == last_regular and posted_week(state, "spoon") < week:
            if standings_ready:
                plan.posts.append(Plan("spoon", week))
            else:
                plan.notes.append("Wooden Spoon waits for the final standings")

        next_week = week + 1
        if race_start <= next_week <= last_regular and int(state.get("race_week") or 0) < week:
            if standings_ready:
                plan.posts.append(Plan("race", week))
            else:
                plan.notes.append("playoff race waits for standings")
    elif bounties_due(info, state, now, tz, comp, 0):
        plan.posts.append(Plan("bounties", 0))  # Week 1 not final yet: hat-trick check only

    upcoming = season.upcoming_period(info, now, tz)
    if upcoming and upcoming.number <= last_regular:
        for item in ("preview", "games"):
            if posted_week(state, item) < upcoming.number:
                plan.posts.append(Plan(item, upcoming.number))

    if not plan.posts and not plan.notes:
        plan.notes.append("nothing due")
    return plan


def records_with_week(
    standings_rows: list[dict[str, Any]],
    scores: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fantrax records plus a finished week Fantrax has not counted yet."""
    records = {r["teamId"]: [r["wins"], r["losses"], r["ties"]] for r in standings_rows}
    for row in scores:
        away, home = row["away"], row["home"]
        for team in (away, home):
            records.setdefault(team["teamId"], [0, 0, 0])
        if away["score"] > home["score"]:
            records[away["teamId"]][0] += 1
            records[home["teamId"]][1] += 1
        elif home["score"] > away["score"]:
            records[home["teamId"]][0] += 1
            records[away["teamId"]][1] += 1
        else:
            records[away["teamId"]][2] += 1
            records[home["teamId"]][2] += 1
    return {tid: {"record": f"{w}-{l}-{t}"} for tid, (w, l, t) in records.items()}


def remember_ranks(state: dict[str, Any], week: int, ranks: dict[str, int]) -> None:
    """Keep the posted power rankings so next week can show each team's change."""
    saved = {k: v for k, v in (state.get("power_ranks") or {}).items() if isinstance(v, dict)}
    saved[str(week)] = ranks
    keep = sorted(saved, key=int)[-RANKS_KEPT:]
    state["power_ranks"] = {k: saved[k] for k in keep}


class Desk:
    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        test: bool = False,
        fx: Any = None,
        saved_state: dict[str, Any] | None = None,
        nhl_get: Any = None,
    ) -> None:
        self.cfg = cfg
        self.comp = cfg.get("competition") or {}
        self.tz = timezone_of(cfg)
        self.fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Competition-Desk/2.0")
        self.info = self.fx.league_info()
        self.rows = self.fx.standings()
        self.last_regular, self.first_playoff, self.playoff_cut = season.playoff_settings(self.info)
        self.ctx = render.Context(
            league_name=str(self.info.get("leagueName") or ""),
            season_label=str(cfg.get("season_label") or ""),
            color=color_value(cfg.get("color")),
            test=test,
        )
        self._scores: dict[int, list[dict]] = {}
        # Read-only copy of saved state: last week's power rankings.
        self.saved_state = saved_state if saved_state is not None else load_json(STATE_PATH, {})
        self.nhl_get = nhl_get
        self.ranks: dict[int, dict[str, int]] = {}
        # Set by run(): "preview", "test" or "live", and in live mode the state
        # being written (bounty claims are read from it).
        self.mode = "preview"
        self.live_state: dict[str, Any] | None = None
        self.bounty_update: dict[str, Any] | None = None
        self.notes: list[str] = []
        self._nhl: dict[tuple, list] = {}
        self._rosters: dict[str, Any] | None = None
        self._players: dict[str, Any] | None = None

    def scores(self, week: int) -> list[dict]:
        if week not in self._scores:
            self._scores[week] = self.fx.matchup_scores(week)
        return self._scores[week]

    def season_weeks(self, through: int) -> dict[int, list[dict]]:
        """Matchup scores for every week from 1 through ``through``."""
        return {w: self.scores(w) for w in range(1, through + 1) if season.period(self.info, w)}

    def previous_ranks(self, week: int) -> dict[str, int]:
        """Power rankings after the week before: as posted, else recomputed."""
        if week <= 1:
            return {}
        saved = (self.saved_state.get("power_ranks") or {}).get(str(week - 1))
        if isinstance(saved, dict) and saved:
            return {str(k): int(v) for k, v in saved.items()}
        return weekly.ranks_of(weekly.power_rankings(self.season_weeks(week - 1)))

    def webhook(self, item: str) -> str:
        hooks = self.comp.get("webhooks") or {}
        key = {"race": "playoff_race"}.get(item, item)
        fallback = {"awards": "recap", "rankings": "recap", "games": "preview",
                    "monthly": "recap", "bounties": "recap"}.get(item, "")
        return str(hooks.get(key) or hooks.get(fallback) or "")

    # --- Shared reads (each fetched once per run) ---------------------------------

    def nhl_schedule(self, p: season.Period) -> list[nhl.Game]:
        first, last = p.start.astimezone(self.tz).date(), p.end.astimezone(self.tz).date()
        if (first, last) not in self._nhl:
            self._nhl[(first, last)] = nhl.fetch_schedule(first, last, self.tz, self.nhl_get)
        return self._nhl[(first, last)]

    def roster_data(self) -> dict[str, Any]:
        if self._rosters is None:
            self._rosters = self.fx.rosters()
        return self._rosters

    def player_directory(self) -> dict[str, Any]:
        if self._players is None:
            self._players = self.fx.player_ids()
        return self._players

    def rosters_empty(self) -> bool:
        block = self.roster_data().get("rosters")
        if not isinstance(block, dict):
            raise ValueError("getTeamRosters has no rosters object")
        return not any((team or {}).get("rosterItems") for team in block.values() if isinstance(team, dict))

    # --- Schedule edge (matchup preview) ------------------------------------------

    def goalie_cap(self, p: season.Period) -> int:
        return season.goalie_start_cap(p, int(self.comp.get("goalie_starts_per_week") or season.GOALIE_STARTS_PER_WEEK))

    def light_max(self) -> int:
        return int(self.comp.get("light_night_max_teams") or nhl.LIGHT_NIGHT_MAX_TEAMS)

    def schedule_edge(self, p: season.Period) -> dict[str, edge.Projection] | None:
        """teamId -> projected games for the week, or None to leave the line out.

        Never raises: an empty roster, a Fantrax error or an NHL schedule error
        only drops the projection from the preview.
        """
        try:
            if self.rosters_empty():
                self.notes.append("schedule edge left out: every BLHA roster is empty")
                return None
            squads = edge.lineup_players(self.roster_data(), self.player_directory())
            if not squads:
                self.notes.append("schedule edge left out: no lineup players found")
                return None
            found = edge.projections(squads, self.nhl_schedule(p), p.start, p.end, self.tz,
                                     goalie_cap=self.goalie_cap(p), light_max=self.light_max())
            if not found:
                self.notes.append("schedule edge left out: no NHL regular-season games this week")
            return found or None
        except Exception as exc:
            self.notes.append(f"schedule edge left out: {exc}")
            return None

    # --- Monthly awards -------------------------------------------------------------

    def monthly_post(self, week: int) -> dict[str, Any] | None:
        """Awards for the month containing ``week``, through that week."""
        groups = monthly.month_groups(self.info, self.tz, self.last_regular)
        group = monthly.group_for(groups, week)
        if group is None:
            return None  # playoff weeks have no monthly awards
        numbers = [w for w in group.weeks if w <= week]
        result = monthly.monthly_awards({w: self.scores(w) for w in numbers},
                                        monthly.multi_week_periods(self.info, numbers))
        first, last = season.period(self.info, numbers[0]), season.period(self.info, numbers[-1])
        span = season.Period(0, first.start, last.end)
        return render.monthly_awards(self.ctx, group, span, result, month_to_date=week < group.last_week)

    # --- Bounties -------------------------------------------------------------------

    def hat_trick_check(self, bounty: bounties.Bounty, now: datetime, through: str | None) -> bounties.HatTrickCheck:
        nights = bounties.nights_to_check(self.info, self.tz, now, self.last_regular, through)
        if not nights:
            return bounties.HatTrickCheck()
        try:
            if self.rosters_empty():
                # Nobody is rostered, so nobody can be credited for these nights.
                return bounties.HatTrickCheck(checked_through=nights[-1])
            index = roster.build_index(self.roster_data(), self.player_directory())
        except Exception as exc:
            self.notes.append(f"hat-trick check skipped, Fantrax rosters unavailable: {exc}")
            return bounties.HatTrickCheck()

        def owner_of(name: str, team: str) -> tuple[str, str] | None:
            player = index.match(name, team)
            return (player.owner_id, player.owner_name) if player else None

        get = self.nhl_get or nhl.http_get_json
        check = bounties.find_hat_trick(bounty, nights, lambda night: get(nhl.SCORE_URL.format(date=night.isoformat())),
                                        owner_of)
        self.notes.extend(f"hat-trick check: {note}" for note in check.notes)
        return check

    def bounty_post(self, week: int, now: datetime) -> dict[str, Any] | None:
        """Live: new claims only (None when nothing new). Preview/test: the
        Bounty Board, every claim so far plus where the open bounties stand."""
        self.bounty_update = None
        configured, errors = bounties.load_bounties(self.comp)
        self.notes.extend(f"bounty config: {e}" for e in errors)
        if not configured:
            return None
        state = self.live_state if self.live_state is not None else self.saved_state
        saved = bounty_state(state)
        claimed = {k: c for k, c in ((k, bounties.Claim.from_dict(v)) for k, v in saved["claimed"].items()) if c}
        still_open = [b for b in configured if b.id not in claimed]

        week = min(week, self.last_regular)
        checked_week = int(state.get("bounties_week") or 0)
        numbers = list(range(1, week + 1))
        long_weeks = monthly.multi_week_periods(self.info, numbers)
        fresh: dict[str, bounties.Claim] = {}
        if self.mode != "live" or week > checked_week:
            fresh = bounties.team_claims([b for b in still_open if b.type in bounties.TEAM_TYPES],
                                         self.season_weeks(week), long_weeks)

        through = saved["hat_trick_through"]
        hat = next((b for b in still_open if b.type == bounties.PLAYER_HAT_TRICK), None)
        if hat:
            check = self.hat_trick_check(hat, now, through)
            if check.checked_through:
                through = check.checked_through.isoformat()
            if check.claim:
                fresh[hat.id] = check.claim
        for claim in fresh.values():
            claim.claimed_at = now.isoformat()

        everything = {**claimed, **fresh}
        self.bounty_update = {"claimed": {k: c.to_dict() for k, c in everything.items()}, "hat_trick_through": through}
        shown = fresh if self.mode == "live" else everything
        pairs = [(b, shown[b.id]) for b in configured if b.id in shown]
        if self.mode == "live" and not pairs:
            return None
        # Read lazily: a daily hat-trick check with nothing new never re-reads every week.
        weeks = self.season_weeks(week) if week >= 1 else {}
        open_now = [(b, bounties.progress(b, weeks, long_weeks)) for b in configured if b.id not in everything]
        return render.bounties(self.ctx, pairs, open_now,
                               nhl_data=any(b.type == bounties.PLAYER_HAT_TRICK for b, _ in pairs))

    def games_grid(self, p: season.Period) -> dict[str, Any] | None:
        games = self.nhl_schedule(p)
        if not games:
            raise ValueError("the NHL schedule API returned no games at all; its response shape may have changed")
        grid = nhl.week_grid(
            games, p.start, p.end, self.tz,
            light_max=int(self.comp.get("light_night_max_teams") or nhl.LIGHT_NIGHT_MAX_TEAMS),
            heavy_min=int(self.comp.get("heavy_night_min_teams") or nhl.HEAVY_NIGHT_MIN_TEAMS),
        )
        if not grid.total_games:
            return None  # e.g. a preseason test week: no regular-season games
        return render.games_grid(self.ctx, p, grid)

    def build(self, item: str, week: int, now: datetime) -> dict[str, Any] | None:
        """The Discord payload, or None when there is nothing to post."""
        if item == "bounties":
            return self.bounty_post(week, now)  # week 0: before Week 1 is final
        p = season.period(self.info, week)
        if p is None:
            raise ValueError(f"Fantrax has no week {week}")
        if item == "recap":
            rows = self.scores(week)
            return render.recap(self.ctx, p, rows,
                                all_play_week=weekly.all_play(rows),
                                all_play_season=weekly.season_all_play(self.season_weeks(week)))
        if item == "awards":
            return render.awards(self.ctx, p, weekly.weekly_awards(self.scores(week)))
        if item == "rankings":
            previous = self.previous_ranks(week)
            rows = weekly.power_rankings(self.season_weeks(week), previous)
            self.ranks[week] = weekly.ranks_of(rows)
            return render.power_rankings(self.ctx, week, rows, has_previous=bool(previous))
        if item == "standings":
            return render.standings(self.ctx, self.rows, after_week=week, playoff_cut=self.playoff_cut,
                                    final=week >= self.last_regular)
        if item == "race":
            return render.playoff_race(self.ctx, self.rows, after_week=week,
                                       weeks_left=max(0, self.last_regular - week),
                                       playoff_cut=self.playoff_cut,
                                       bubble_depth=int(self.comp.get("bubble_depth") or 3))
        if item == "spoon":
            if not self.rows:
                return None
            last = max(self.rows, key=lambda r: r["rank"])
            return render.wooden_spoon(self.ctx, last, owner_mention(self.cfg, last))
        if item == "preview":
            pairs = schedule_for(self.info, week) or [
                {"away": r["away"], "home": r["home"]} for r in self.scores(week)
            ]
            counted = games_counted(self.rows) or 0
            needed = week - 1
            if counted >= needed or needed < 1:
                records = {r["teamId"]: {"record": r["record"], "rank": r["rank"]} for r in self.rows}
                ranks_shown = True
            else:
                records = records_with_week(self.rows, self.scores(needed))
                ranks_shown = False
            return render.preview(self.ctx, p, pairs, records, ranks_shown=ranks_shown,
                                  projections=self.schedule_edge(p), goalie_cap=self.goalie_cap(p),
                                  light_max=self.light_max())
        if item == "games":
            return self.games_grid(p)
        if item == "monthly":
            return self.monthly_post(week)
        raise ValueError(f"unknown item {item}")

    def default_week(self, item: str, now: datetime) -> int:
        """Best week to show for manual preview/test runs."""
        done = season.latest_final(self.info, now, self.tz, through=self.last_regular)
        active = season.active_period(self.info, now) or season.upcoming_period(self.info, now, self.tz)
        if item in ("preview", "games"):
            up = season.upcoming_period(self.info, now, self.tz) or active
            return up.number if up else 1
        if item == "monthly" and done:
            # The latest month whose awards are due; else this month to date.
            groups = monthly.month_groups(self.info, self.tz, self.last_regular)
            ready = [g for g in groups if g.report_week <= done.number]
            return ready[-1].last_week if ready else done.number
        if done:
            return done.number
        return active.number if active else 1


def owner_mention(cfg: dict[str, Any], row: dict[str, Any]) -> str:
    """Discord user ID of the franchise's owner if listed under owners (opt-in), else ""."""
    owners = {str(k).strip().lower(): str(v).strip() for k, v in (cfg.get("owners") or {}).items()}
    user = owners.get(str(row.get("teamId") or "").lower()) or owners.get(str(row.get("teamName") or "").lower()) or ""
    return user if user.isdigit() and 15 <= len(user) <= 21 else ""


def record_post(state: dict[str, Any], desk: Desk, post: Plan, now: datetime) -> None:
    key = STATE_KEYS[post.item]
    state[key] = max(int(state.get(key) or 0), post.week)
    if post.item == "rankings" and post.week in desk.ranks:
        remember_ranks(state, post.week, desk.ranks[post.week])
    if post.item == "bounties" and desk.bounty_update is not None:
        state["bounties"] = desk.bounty_update
    state["updated_at"] = now.isoformat()
    save_json(STATE_PATH, state)


def run(
    mode: str,
    items: list[str],
    week_override: int | None,
    force: bool,
    *,
    desk: Desk | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    desk = desk or Desk(load_league(), test=(mode == "test"))
    print(
        f"BLHA COMPETITION DESK mode={mode.upper()} "
        f"now={now.astimezone(desk.tz).strftime('%a %Y-%m-%d %H:%M %Z')} "
        f"season={season.describe(desk.info, now)} counted_weeks={games_counted(desk.rows)}"
    )

    desk.mode = mode
    if mode == "live":
        state = migrate_state(load_json(STATE_PATH, {}))
        migrate_monthly(state, desk.info, desk.tz, desk.comp)
        desk.live_state = state
        planning_state = {} if force else state
        plan = plan_report(desk.info, desk.rows, planning_state, now, desk.tz, desk.comp)
        posts = [p for p in plan.posts if p.item in items]
        for note in plan.notes:
            print(f"NOTE    {note}")
    else:
        state = {}
        posts = [Plan(item, week_override or desk.default_week(item, now)) for item in items]

    errors = 0
    for post in posts:
        label = f"{post.item} week {post.week}"
        try:
            payload = desk.build(post.item, post.week, now)
        except Exception as exc:
            print(f"ERROR   {label}: could not build: {exc}")
            errors += 1
            continue
        finally:
            for note in desk.notes:
                print(f"NOTE    {label}: {note}")
            desk.notes.clear()

        if payload is None:
            print(f"SKIPPED {label}: nothing to post (no scores yet, or no NHL regular-season games)")
            if mode == "live":
                record_post(state, desk, post, now)
            continue

        if mode == "preview":
            print(f"PREVIEW {label}:\n{json.dumps(payload, indent=2)}")
            continue

        ok, detail, _ = send_discord_webhook(desk.webhook(post.item), payload)
        if not ok:
            print(f"ERROR   {label}: {detail}")
            errors += 1
            continue
        print(f"POSTED  {label}")
        if mode == "live":
            record_post(state, desk, post, now)

    if not posts:
        print("RESULT: nothing to post")
    print(f"SUMMARY posts={len(posts)} errors={errors}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--item", choices=("all",) + ITEMS, default="all")
    parser.add_argument("--week", type=int, help="Week to render in preview/test mode")
    parser.add_argument("--force", action="store_true", help="Live: repost items already posted for their week")
    args = parser.parse_args()
    items = list(ITEMS) if args.item == "all" else [args.item]
    try:
        return run(args.mode, items, args.week, args.force)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
