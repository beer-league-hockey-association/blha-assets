#!/usr/bin/env python3
"""Offline checks for the season calendar, weekly report, live scoreboard and playoffs.

Uses a trimmed copy of the real Fantrax test league (2026-27) so week
boundaries match what Fantrax actually publishes: weeks end at the first
Monday game (for example Mon Oct 5, 6:59 PM ET), not at midnight.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

AUTOMATION = Path(__file__).resolve().parents[1]
for sub in ("", "competition", "playoffs", "scheduler"):
    sys.path.insert(0, str(AUTOMATION / sub))

import desk  # noqa: E402
import discord_webhook  # noqa: E402
import playoff  # noqa: E402
import render  # noqa: E402
import scheduler  # noqa: E402
import scoreboard  # noqa: E402
from blha import season  # noqa: E402
from blha.fantrax import games_counted, normalize_standings, schedule_for  # noqa: E402
from blha.schedule import job_active, load_schedule  # noqa: E402

ET = ZoneInfo("America/New_York")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
INFO = json.loads((FIXTURES / "league_info_2026_test.json").read_text())
RAW_STANDINGS = json.loads((FIXTURES / "standings_week0.json").read_text())
COMP = {"report_time": "08:00", "playoff_race_start_week": 16, "bubble_depth": 3}


def et(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


def standings_after(weeks: int) -> list[dict]:
    raw = copy.deepcopy(RAW_STANDINGS)
    for i, row in enumerate(raw):
        wins = weeks // 2 + (1 if i % 2 and weeks % 2 else 0)
        row["points"] = f"{wins}-{weeks - wins}-0"
    return normalize_standings(raw)


def end_of(week: int) -> datetime:
    return season.period(INFO, week).end


def morning_of_end(week: int, hour: int = 8) -> datetime:
    local = end_of(week).astimezone(ET)
    return datetime(local.year, local.month, local.day, hour, 0, tzinfo=ET).astimezone(timezone.utc)


def items(plan: desk.ReportPlan) -> list[tuple[str, int]]:
    return [(p.item, p.week) for p in plan.posts]


class SeasonCalendarTests(unittest.TestCase):
    def test_fantrax_offsets_parse(self) -> None:
        self.assertEqual(season.parse_dt("2026-10-05T18:59:59.0-0400"), et(2026, 10, 5, 18, 59).replace(second=59))

    def test_week_is_final_at_six_am_on_its_last_day(self) -> None:
        p1 = season.period(INFO, 1)
        self.assertEqual(season.final_at(p1, ET), et(2026, 10, 5, 6))
        self.assertFalse(season.is_final(p1, et(2026, 10, 5, 5, 59), ET))
        self.assertTrue(season.is_final(p1, et(2026, 10, 5, 8), ET))

    def test_phases(self) -> None:
        self.assertEqual(season.phase(INFO, et(2026, 9, 28, 12)), season.PRESEASON)
        self.assertEqual(season.phase(INFO, et(2026, 10, 2, 12)), season.REGULAR)
        self.assertEqual(season.phase(INFO, et(2027, 3, 10, 12)), season.PLAYOFFS)
        self.assertEqual(season.phase(INFO, et(2027, 4, 10, 12)), season.OFFSEASON)

    def test_playoffs_begin_when_week_23_starts(self) -> None:
        self.assertEqual(season.phase_started_at(INFO, et(2027, 3, 10, 12)), season.period(INFO, 23).start)

    def test_upcoming_week(self) -> None:
        self.assertEqual(season.upcoming_period(INFO, et(2026, 9, 29, 8), ET).number, 1)
        self.assertEqual(season.upcoming_period(INFO, et(2026, 10, 2, 12), ET).number, 1)
        self.assertEqual(season.upcoming_period(INFO, et(2026, 10, 5, 8), ET).number, 2)

    def test_league_schedule_has_six_matchups_per_week(self) -> None:
        self.assertEqual(len(schedule_for(INFO, 1)), 6)


class WeeklyReportTests(unittest.TestCase):
    def plan(self, now: datetime, counted: int, state: dict) -> desk.ReportPlan:
        return desk.plan_report(INFO, standings_after(counted), state, now, ET, COMP)

    def test_quiet_mid_week(self) -> None:
        self.assertEqual(items(self.plan(et(2026, 10, 2, 12), 0, {"preview_week": 1})), [])

    def test_nothing_before_report_time(self) -> None:
        self.assertEqual(items(self.plan(et(2026, 10, 5, 7, 30), 1, {"preview_week": 1})), [])

    def test_monday_report_in_order(self) -> None:
        plan = self.plan(et(2026, 10, 5, 8), 1, {"preview_week": 1})
        self.assertEqual(items(plan), [("recap", 1), ("awards", 1), ("rankings", 1), ("standings", 1),
                                       ("preview", 2), ("games", 2)])

    def test_standings_wait_for_fantrax_then_go_out_in_evening(self) -> None:
        morning = self.plan(et(2026, 10, 5, 8), 0, {"preview_week": 1})
        self.assertEqual(items(morning), [("recap", 1), ("awards", 1), ("rankings", 1), ("preview", 2), ("games", 2)])
        self.assertTrue(any("standings wait" in n for n in morning.notes))
        state = {"recap_week": 1, "preview_week": 2}
        self.assertEqual(items(self.plan(et(2026, 10, 5, 20), 1, state)), [("standings", 1)])

    def test_standings_posted_after_grace_even_if_fantrax_never_counts(self) -> None:
        state = {"recap_week": 1, "preview_week": 2}
        late = end_of(1) + desk.STANDINGS_GRACE + timedelta(minutes=1)
        self.assertEqual(items(self.plan(late, 0, state)), [("standings", 1)])

    def test_nothing_repeats_once_posted(self) -> None:
        state = {"recap_week": 1, "standings_week": 1, "preview_week": 2}
        self.assertEqual(items(self.plan(et(2026, 10, 5, 20), 1, state)), [])

    def test_no_playoff_race_before_week_16(self) -> None:
        state = {k: 13 for k in ("recap_week", "standings_week", "race_week")} | {"preview_week": 14}
        self.assertNotIn("race", [i for i, _ in items(self.plan(morning_of_end(14), 14, state))])

    def test_playoff_race_starts_with_week_16(self) -> None:
        state = {k: 14 for k in ("recap_week", "standings_week", "race_week")} | {"preview_week": 15}
        plan = self.plan(morning_of_end(15), 15, state)
        self.assertEqual(items(plan), [("recap", 15), ("awards", 15), ("rankings", 15), ("standings", 15),
                                       ("race", 15), ("preview", 16), ("games", 16)])

    def test_last_week_gets_final_standings_and_no_race_or_preview(self) -> None:
        state = {k: 21 for k in ("recap_week", "standings_week", "race_week")} | {"preview_week": 22}
        plan = self.plan(morning_of_end(22), 22, state)
        self.assertEqual(items(plan), [("recap", 22), ("awards", 22), ("rankings", 22), ("standings", 22)])

    def test_week_21_still_gets_a_race_update(self) -> None:
        state = {k: 20 for k in ("recap_week", "standings_week", "race_week")} | {"preview_week": 21}
        self.assertIn(("race", 21), items(self.plan(morning_of_end(21), 21, state)))

    def test_preseason_previews_week_one_on_opening_day(self) -> None:
        self.assertEqual(items(self.plan(et(2026, 9, 29, 8), 0, {})), [("preview", 1), ("games", 1)])

    def test_playoffs_do_not_trigger_regular_season_posts(self) -> None:
        state = {k: 22 for k in ("recap_week", "standings_week", "race_week", "preview_week")}
        self.assertEqual(items(self.plan(morning_of_end(23), 22, state)), [])

    def test_preview_records_include_uncounted_week(self) -> None:
        rows = standings_after(0)
        a, b = rows[0]["teamId"], rows[1]["teamId"]
        scores = [{"away": {"teamId": a, "score": 120.5}, "home": {"teamId": b, "score": 99.0}}]
        records = desk.records_with_week(rows, scores)
        self.assertEqual(records[a]["record"], "1-0-0")
        self.assertEqual(records[b]["record"], "0-1-0")


class RenderTests(unittest.TestCase):
    ctx = render.Context("Dynasty Hockey Test League", "2026-27 TEST", 0xFFB81C)

    def test_final_standings_title(self) -> None:
        body = render.standings(self.ctx, standings_after(22), after_week=22, playoff_cut=6, final=True)
        self.assertEqual(body["embeds"][0]["title"], "BLHA Final Regular-Season Standings")
        self.assertIn("Playoff Cut", body["embeds"][0]["fields"][5]["name"])

    def test_race_shows_cut_plus_bubble(self) -> None:
        body = render.playoff_race(self.ctx, standings_after(15), after_week=15, weeks_left=7,
                                   playoff_cut=6, bubble_depth=3)
        embed = body["embeds"][0]
        self.assertEqual(len(embed["fields"]), 9)
        self.assertIn("7 weeks left", embed["description"])

    def test_preview_without_ranks_when_fantrax_not_ready(self) -> None:
        p = season.period(INFO, 2)
        pairs = schedule_for(INFO, 2)
        body = render.preview(self.ctx, p, pairs, {}, ranks_shown=False)
        self.assertNotIn("#", body["embeds"][0]["fields"][0]["value"])

    def test_competition_desk_identity_and_no_mentions(self) -> None:
        body = render.recap(self.ctx, season.period(INFO, 1), [])
        self.assertEqual(body["username"], "BLHA Competition Desk")
        self.assertEqual(body["allowed_mentions"], {"parse": []})


class LiveScoreboardTests(unittest.TestCase):
    def test_opens_current_week(self) -> None:
        self.assertEqual(scoreboard.plan_scoreboard(INFO, {}, et(2026, 10, 2, 12), ET), [("open", 1)])

    def test_updates_same_week(self) -> None:
        state = {"week": 1, "message_id": "m1", "final": False}
        self.assertEqual(scoreboard.plan_scoreboard(INFO, state, et(2026, 10, 2, 12), ET), [("update", 1)])

    def test_marks_final_monday_morning_and_waits_for_next_week(self) -> None:
        state = {"week": 1, "message_id": "m1", "final": False}
        self.assertEqual(scoreboard.plan_scoreboard(INFO, state, et(2026, 10, 5, 8), ET), [("finalize", 1)])
        done = {"week": 1, "message_id": "m1", "final": True}
        self.assertEqual(scoreboard.plan_scoreboard(INFO, done, et(2026, 10, 5, 12), ET), [])

    def test_new_week_opens_new_message(self) -> None:
        done = {"week": 1, "message_id": "m1", "final": True}
        self.assertEqual(scoreboard.plan_scoreboard(INFO, done, et(2026, 10, 5, 19, 30), ET), [("open", 2)])

    def test_missed_final_is_caught_up_before_opening(self) -> None:
        state = {"week": 1, "message_id": "m1", "final": False}
        actions = scoreboard.plan_scoreboard(INFO, state, et(2026, 10, 5, 19, 30), ET)
        self.assertEqual(actions, [("finalize", 1), ("open", 2)])

    def test_offseason_does_nothing(self) -> None:
        state = {"week": 25, "message_id": "m", "final": True}
        self.assertEqual(scoreboard.plan_scoreboard(INFO, state, et(2027, 5, 1, 12), ET), [])

    def test_fingerprint_ignores_render_time(self) -> None:
        rows = [{"away": {"teamId": "a", "score": 1.0, "gamesPlayed": 1},
                 "home": {"teamId": "b", "score": 2.0, "gamesPlayed": 1}}]
        self.assertEqual(scoreboard.fingerprint(1, rows, False), scoreboard.fingerprint(1, copy.deepcopy(rows), False))
        self.assertNotEqual(scoreboard.fingerprint(1, rows, False), scoreboard.fingerprint(1, rows, True))


class PlayoffSeedTests(unittest.TestCase):
    def test_seeds_wait_until_week_22_is_counted(self) -> None:
        self.assertFalse(playoff.seeds_ready(INFO, standings_after(21)))
        self.assertTrue(playoff.seeds_ready(INFO, standings_after(22)))

    def test_games_counted_uses_fewest_games(self) -> None:
        rows = standings_after(5)
        rows[0]["wins"] -= 1
        self.assertEqual(games_counted(rows), 4)


class DiscordEditTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TEST_HOOK"] = "https://discord.example.invalid/api/webhooks/123/abc"

    def tearDown(self) -> None:
        os.environ.pop("TEST_HOOK", None)

    def test_message_url(self) -> None:
        self.assertEqual(
            discord_webhook.message_url("https://discord.com/api/webhooks/1/tok", "99"),
            "https://discord.com/api/webhooks/1/tok/messages/99",
        )

    @patch("discord_webhook.requests.patch")
    def test_edit_existing_message(self, patch_: Mock) -> None:
        patch_.return_value = Mock(status_code=200, text="", headers={})
        ok, _, mid, how = discord_webhook.upsert_discord_message("TEST_HOOK", {"embeds": [], "username": "x"}, "55")
        self.assertEqual((ok, mid, how), (True, "55", "edited"))
        sent = patch_.call_args.kwargs["json"]
        self.assertNotIn("username", sent)

    @patch("discord_webhook.requests.post")
    @patch("discord_webhook.requests.patch")
    def test_deleted_message_is_reposted(self, patch_: Mock, post: Mock) -> None:
        patch_.return_value = Mock(status_code=404, text="Unknown Message", headers={})
        created = Mock(status_code=200, text="", headers={})
        created.json.return_value = {"id": "77"}
        post.return_value = created
        ok, _, mid, how = discord_webhook.upsert_discord_message("TEST_HOOK", {"embeds": []}, "55")
        self.assertEqual((ok, mid, how), (True, "77", "posted"))


class SchedulerSeasonTests(unittest.TestCase):
    def test_phase_gating(self) -> None:
        job = {"id": "scoreboard", "phases": ["regular", "playoffs"]}
        self.assertTrue(job_active(job, "regular")[0])
        self.assertFalse(job_active(job, "offseason")[0])
        self.assertTrue(job_active(job, None)[0])  # Fantrax unreachable: do not block
        self.assertTrue(job_active({"id": "wire"}, "offseason")[0])

    def test_schedule_phases_are_valid(self) -> None:
        jobs = {j["id"]: j for j in load_schedule()["jobs"]}
        self.assertEqual(jobs["playoffs"]["phases"], ["playoffs"])
        self.assertNotIn("phases", jobs["wire-engine"])

    def test_failed_daily_run_is_retried(self) -> None:
        job = {"id": "desk", "workflow": "x.yml", "daily_at": ["08:00"], "retry_failures": 2}
        now = et(2026, 10, 5, 8, 20)
        failed = {"created_at": et(2026, 10, 5, 8, 1).isoformat(), "display_title": "x — live",
                  "event": "workflow_dispatch", "conclusion": "failure"}
        self.assertTrue(scheduler.decide(job, [failed], now, ET, timedelta(minutes=5)).due)
        three = [dict(failed, created_at=et(2026, 10, 5, 8, m).isoformat()) for m in (1, 16, 31)]
        self.assertFalse(scheduler.decide(job, three, et(2026, 10, 5, 8, 45), ET, timedelta(minutes=5)).due)

    def test_successful_daily_run_is_not_retried(self) -> None:
        job = {"id": "desk", "workflow": "x.yml", "daily_at": ["08:00"], "retry_failures": 2}
        ok = {"created_at": et(2026, 10, 5, 8, 1).isoformat(), "display_title": "x — live",
              "event": "workflow_dispatch", "conclusion": "success"}
        self.assertFalse(scheduler.decide(job, [ok], et(2026, 10, 5, 8, 20), ET, timedelta(minutes=5)).due)


if __name__ == "__main__":
    unittest.main()
