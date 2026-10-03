#!/usr/bin/env python3
"""Offline checks for the Commissioner Desk timing and delivery logic."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import desk  # noqa: E402
import endreport  # noqa: E402
from blha import season  # noqa: E402

ET = ZoneInfo("America/New_York")
INFO = json.loads((HERE.parent / "tests" / "fixtures" / "league_info_2026_test.json").read_text())
DATA = desk.load_tasks()
SETTINGS = DATA["settings"]
CATCHUP = timedelta(hours=36)


def anchors():
    return desk.anchors_from(INFO, ET, SETTINGS)


def statuses(now, sent=None):
    return {d.task_id: d.status for d in desk.plan(DATA["tasks"], anchors(), sent or {}, now, CATCHUP)}


def _raw(played, same_record=False):
    rows = []
    for i in range(1, 13):
        rec = f"{played - i}-{i}-0" if not same_record or i not in (6, 7) else f"{played - 6}-6-0"
        rows.append({"rank": i, "teamId": f"t{i}", "teamName": f"Team {i}", "points": rec,
                     "totalPointsFor": 1000.0 - i, "gamesBack": 0, "winPercentage": 0.5})
    return rows


FINAL_STANDINGS = _raw(23)  # 22 games each: W + L = 22
IN_PROGRESS = _raw(15)


class AnchorTests(unittest.TestCase):
    def test_anchor_values_match_fantrax_calendar(self):
        a = anchors()
        weeks = {p.number: p for p in season.periods(INFO)}
        self.assertEqual(a["first_week_start"], weeks[1].start)
        # Trade-deadline week is 20 of 22; final at 6 AM ET on the Monday that closes it.
        self.assertEqual(a["trade_deadline_final"], season.final_at(weeks[20], ET))
        self.assertEqual(a["last_regular_final"], season.final_at(weeks[22], ET))
        self.assertEqual(a["playoff_start:1"], weeks[23].start)
        self.assertEqual(a["playoff_start:3"], weeks[25].start)
        self.assertEqual(a["season_end_final"], season.final_at(weeks[25], ET))

    def test_every_task_anchor_exists(self):
        a = anchors()
        for task in DATA["tasks"]:
            self.assertIn(task["anchor"], a, task["id"])


class OffsetTests(unittest.TestCase):
    def test_parse_offsets(self):
        self.assertEqual(desk.parse_offset("2h"), timedelta(hours=2))
        self.assertEqual(desk.parse_offset("-6h"), timedelta(hours=-6))
        self.assertEqual(desk.parse_offset("14d"), timedelta(days=14))
        self.assertEqual(desk.parse_offset("start"), timedelta(0))
        with self.assertRaises(ValueError):
            desk.parse_offset("3w")


class PlanTests(unittest.TestCase):
    def test_wrapup_is_due_the_morning_after_week_22_and_only_once(self):
        trigger = anchors()["last_regular_final"] + timedelta(hours=2)
        self.assertEqual(statuses(trigger - timedelta(minutes=1))["wrapup"], "early")
        self.assertEqual(statuses(trigger + timedelta(minutes=1))["wrapup"], "send")
        sent = {desk.state_key("wrapup", trigger): "x"}
        self.assertEqual(statuses(trigger + timedelta(minutes=1), sent)["wrapup"], "sent")

    def test_late_reminder_is_still_posted_as_overdue(self):
        trigger = anchors()["last_regular_final"] + timedelta(hours=2)
        self.assertEqual(statuses(trigger + CATCHUP + timedelta(minutes=1))["wrapup"], "overdue")
        self.assertEqual(statuses(trigger + timedelta(days=6))["wrapup"], "overdue")

    def test_countdown_expires_when_its_event_starts(self):
        start = anchors()["playoff_start:1"]
        self.assertEqual(statuses(start - timedelta(hours=1))["consolation-r1"], "send")
        self.assertEqual(statuses(start + timedelta(minutes=1))["consolation-r1"], "expired")
        # With a late scheduler it is still posted, as overdue, until the event starts.
        trigger = start - timedelta(hours=6)
        self.assertEqual(statuses(trigger + CATCHUP + timedelta(hours=1))["consolation-r1"], "expired")

    def test_reminder_expires_after_its_overdue_window(self):
        trigger = anchors()["last_regular_final"] + timedelta(hours=2)
        self.assertEqual(statuses(trigger + timedelta(days=8))["wrapup"], "expired")
        # The close-out list is needed for 30 days.
        end = anchors()["season_end_final"] + timedelta(hours=2)
        self.assertEqual(statuses(end + timedelta(days=20))["closeout"], "overdue")

    def test_countdown_before_playoff_round(self):
        start = anchors()["playoff_start:1"]
        self.assertEqual(statuses(start - timedelta(hours=7))["consolation-r1"], "early")
        self.assertEqual(statuses(start - timedelta(hours=5))["consolation-r1"], "send")

    def test_prize_countdown_runs_for_thirty_days(self):
        end = anchors()["season_end_final"]
        self.assertEqual(statuses(end + timedelta(days=14, hours=1))["prizes-day-14"], "send")
        self.assertEqual(statuses(end + timedelta(days=29, hours=1))["prizes-day-29"], "send")
        # Nothing is left to say after day 30.
        self.assertTrue(all(s not in ("send", "overdue") for s in statuses(end + timedelta(days=32)).values()))

    def test_nothing_due_midseason(self):
        now = season.period(INFO, 10).start + timedelta(days=2)
        self.assertTrue(all(s not in ("send", "overdue") for s in statuses(now).values()))

    def test_missing_anchor_is_reported_not_crashed(self):
        out = desk.plan(DATA["tasks"], {}, {}, datetime.now(timezone.utc), CATCHUP)
        self.assertTrue(all(d.status == "no-anchor" for d in out))


class PayloadTests(unittest.TestCase):
    def test_payload_lists_every_item_and_never_mentions_by_default(self):
        task = next(t for t in DATA["tasks"] if t["id"] == "wrapup")
        payload = desk.build_payload(task, anchors()["last_regular_final"], {"color": "0xFFB81C"})
        text = payload["embeds"][0]["description"]
        for item in task["items"]:
            self.assertIn(item, text)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("content", payload)
        self.assertLessEqual(len(text), 4000)

    def test_optional_ping_only_mentions_that_user(self):
        task = DATA["tasks"][0]
        cfg = {"commissioner_desk": {"ping_user_id": "123456789012345678"}}
        payload = desk.build_payload(task, None, cfg)
        self.assertEqual(payload["allowed_mentions"], {"users": ["123456789012345678"]})
        self.assertEqual(payload["content"], "<@123456789012345678>")


class RunTests(unittest.TestCase):
    def _run(self, now, mode="live", post_ok=True, baselined=True, final_standings=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "commissioner.json"
        if baselined:
            state.write_text(json.dumps({"baselined": "2026-01-01T00:00:00+00:00", "sent": {}}))
        posts = []

        def fake_post(secret, payload):
            posts.append(payload)
            return post_ok, "delivered" if post_ok else "boom"

        class FakeFantrax:
            def __init__(self, *a, **k):
                pass

            def league_info(self):
                return INFO

            def standings(self):
                return FINAL_STANDINGS if final_standings else IN_PROGRESS

        with patch.object(desk, "STATE_PATH", state), patch.object(desk, "Fantrax", FakeFantrax), \
                patch.object(desk, "post_discord_webhook", fake_post):
            code = desk.run(mode, now)
            code2 = desk.run(mode, now)  # a second pass must not repeat anything
        return code, code2, posts, state

    def test_live_posts_once_and_records_state(self):
        now = anchors()["last_regular_final"] + timedelta(hours=3)
        code, code2, posts, state = self._run(now)
        self.assertEqual((code, code2), (0, 0))
        self.assertEqual(len(posts), 2)  # the wrap-up checklist and the data report
        self.assertIn("seed the playoffs", posts[0]["embeds"][0]["title"])
        saved = json.loads(state.read_text())
        self.assertEqual(len(saved["sent"]), 2)
        self.assertIn("season_end_final", saved["anchors"])

    def test_preview_posts_nothing_and_saves_nothing(self):
        now = anchors()["last_regular_final"] + timedelta(hours=3)
        code, _, posts, state = self._run(now, mode="preview")
        self.assertEqual(code, 0)
        self.assertEqual(posts, [])
        self.assertEqual(json.loads(state.read_text()), {"baselined": "2026-01-01T00:00:00+00:00", "sent": {}})

    def test_overdue_reminder_is_labelled(self):
        now = anchors()["last_regular_final"] + timedelta(hours=2) + timedelta(days=3)
        _, _, posts, _ = self._run(now)
        titles = [p["embeds"][0]["title"] for p in posts]
        self.assertEqual(len(titles), 2)
        self.assertTrue(all(t.startswith("OVERDUE: ") for t in titles))
        self.assertIn("Was due", posts[0]["embeds"][0]["description"])

    def test_first_live_run_does_not_flood_with_old_reminders(self):
        # Enabled in the middle of the test season: weeks of past reminders exist.
        now = anchors()["last_regular_final"] + timedelta(days=3)
        code, code2, posts, state = self._run(now, baselined=False)
        self.assertEqual((code, code2, posts), (0, 0, []))
        saved = json.loads(state.read_text())
        self.assertIn("baselined", saved)
        self.assertTrue(all(v == "baseline" for v in saved["sent"].values()))

    def test_first_live_run_still_posts_what_is_on_time(self):
        now = anchors()["last_regular_final"] + timedelta(hours=3)
        _, _, posts, _ = self._run(now, baselined=False)
        self.assertEqual(len(posts), 2)
        self.assertFalse(posts[0]["embeds"][0]["title"].startswith("OVERDUE"))

    def test_failed_delivery_is_retried_next_run(self):
        now = anchors()["last_regular_final"] + timedelta(hours=3)
        code, _, posts, state = self._run(now, post_ok=False)
        self.assertEqual(code, 1)
        self.assertEqual(len(posts), 4)  # both messages tried on both passes, never recorded as sent
        self.assertEqual(json.loads(state.read_text())["sent"], {})


class EndReportTests(unittest.TestCase):
    def test_report_lists_field_bracket_consolation_and_trophy(self):
        from blha.fantrax import normalize_standings
        text = endreport.render(endreport.build_report(normalize_standings(FINAL_STANDINGS)))
        self.assertIn("Presidents' Trophy", text)
        self.assertIn("Round 1: Team 3 v Team 6 and Team 4 v Team 5", text)
        self.assertIn("Round 1: Team 9 v Team 12 and Team 10 v Team 11", text)
        self.assertIn("Potential Points", text)
        self.assertNotIn("Ties to check", text)
        self.assertNotIn("•", text)

    def test_boundary_tie_and_equal_points_are_flagged(self):
        from blha.fantrax import normalize_standings
        rows = normalize_standings(_raw(23, same_record=True))
        text = endreport.render(endreport.build_report(rows))
        self.assertIn("Ties to check", text)
        self.assertIn("last playoff spot", text)
        for r in rows:
            if r["rank"] in (6, 7):
                r["pointsFor"] = 500.0
        text = endreport.render(endreport.build_report(rows))
        self.assertIn("head-to-head", text)

    def test_report_waits_until_fantrax_counted_every_week(self):
        now = anchors()["last_regular_final"] + timedelta(hours=3)
        code, _, posts, state = self._run_wait(now)
        titles = [p["embeds"][0]["title"] for p in posts]
        self.assertFalse(any("End-of-season report" in t for t in titles))
        self.assertEqual(code, 0)
        self.assertFalse(any("endreport" in k for k in json.loads(state.read_text())["sent"]))

    _run_wait = lambda self, now: RunTests._run(self, now, final_standings=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
