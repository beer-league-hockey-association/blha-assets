#!/usr/bin/env python3
"""BLHA Competition Desk: the weekly report.

On the morning a fantasy week ends (normally Monday, at report_time in
league.yaml), posts in order:

1. Weekly recap of the week that just finished
2. League standings after that week
3. Playoff race (from playoff_race_start_week through the last regular week)
4. Matchup preview for the week that starts that evening

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

import render  # noqa: E402
from blha import season  # noqa: E402
from blha.fantrax import Fantrax, games_counted, schedule_for  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook  # noqa: E402

STATE_PATH = ROOT / "state" / "competition.json"
ITEMS = ("recap", "standings", "race", "preview")
STATE_KEYS = {"recap": "recap_week", "standings": "standings_week", "race": "race_week", "preview": "preview_week"}
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

        if int(state.get("recap_week") or 0) < week:
            plan.posts.append(Plan("recap", week))

        if int(state.get("standings_week") or 0) < week:
            if standings_ready:
                plan.posts.append(Plan("standings", week))
            else:
                plan.notes.append(f"standings wait: Fantrax has counted {counted} of {week} weeks")

        next_week = week + 1
        if race_start <= next_week <= last_regular and int(state.get("race_week") or 0) < week:
            if standings_ready:
                plan.posts.append(Plan("race", week))
            else:
                plan.notes.append("playoff race waits for standings")

    upcoming = season.upcoming_period(info, now, tz)
    if upcoming and upcoming.number <= last_regular and int(state.get("preview_week") or 0) < upcoming.number:
        plan.posts.append(Plan("preview", upcoming.number))

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


class Desk:
    def __init__(self, cfg: dict[str, Any], *, test: bool = False) -> None:
        self.cfg = cfg
        self.comp = cfg.get("competition") or {}
        self.tz = timezone_of(cfg)
        self.fx = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Competition-Desk/2.0")
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

    def scores(self, week: int) -> list[dict]:
        if week not in self._scores:
            self._scores[week] = self.fx.matchup_scores(week)
        return self._scores[week]

    def webhook(self, item: str) -> str:
        hooks = self.comp.get("webhooks") or {}
        key = {"race": "playoff_race"}.get(item, item)
        return str(hooks.get(key) or "")

    def build(self, item: str, week: int, now: datetime) -> dict[str, Any]:
        p = season.period(self.info, week)
        if p is None:
            raise ValueError(f"Fantrax has no week {week}")
        if item == "recap":
            return render.recap(self.ctx, p, self.scores(week))
        if item == "standings":
            return render.standings(self.ctx, self.rows, after_week=week, playoff_cut=self.playoff_cut,
                                    final=week >= self.last_regular)
        if item == "race":
            return render.playoff_race(self.ctx, self.rows, after_week=week,
                                       weeks_left=max(0, self.last_regular - week),
                                       playoff_cut=self.playoff_cut,
                                       bubble_depth=int(self.comp.get("bubble_depth") or 3))
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
            return render.preview(self.ctx, p, pairs, records, ranks_shown=ranks_shown)
        raise ValueError(f"unknown item {item}")

    def default_week(self, item: str, now: datetime) -> int:
        """Best week to show for manual preview/test runs."""
        done = season.latest_final(self.info, now, self.tz, through=self.last_regular)
        active = season.active_period(self.info, now) or season.upcoming_period(self.info, now, self.tz)
        if item == "preview":
            up = season.upcoming_period(self.info, now, self.tz) or active
            return up.number if up else 1
        if done:
            return done.number
        return active.number if active else 1


def run(mode: str, items: list[str], week_override: int | None, force: bool) -> int:
    cfg = load_league()
    now = datetime.now(timezone.utc)
    desk = Desk(cfg, test=(mode == "test"))
    print(
        f"BLHA COMPETITION DESK mode={mode.upper()} "
        f"now={now.astimezone(desk.tz).strftime('%a %Y-%m-%d %H:%M %Z')} "
        f"season={season.describe(desk.info, now)} counted_weeks={games_counted(desk.rows)}"
    )

    if mode == "live":
        state = load_json(STATE_PATH, {})
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
            state[STATE_KEYS[post.item]] = max(int(state.get(STATE_KEYS[post.item]) or 0), post.week)
            state["updated_at"] = now.isoformat()
            save_json(STATE_PATH, state)

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
