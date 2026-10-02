#!/usr/bin/env python3
"""Offline regression checks for BLHA League Office time handling."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import league_ops


class LeagueOfficeTimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("America/New_York")

    def test_winter_local_time_uses_est(self) -> None:
        dt = league_ops.parse_event_time("2027-01-15T20:00:00", self.tz)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.utcoffset().total_seconds(), -5 * 3600)

    def test_summer_local_time_uses_edt(self) -> None:
        dt = league_ops.parse_event_time("2027-07-15T20:00:00", self.tz)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.utcoffset().total_seconds(), -4 * 3600)

    def test_explicit_offset_remains_supported(self) -> None:
        dt = league_ops.parse_event_time("2027-01-15T20:00:00-05:00", self.tz)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 20)
        self.assertEqual(dt.utcoffset().total_seconds(), -5 * 3600)

    def test_reminder_never_posts_before_trigger(self) -> None:
        trigger = datetime(2027, 1, 15, 20, 0, tzinfo=self.tz)
        now = trigger - timedelta(minutes=1)
        self.assertFalse(league_ops.due(now, trigger, timedelta(hours=24)))

    def test_delayed_run_catches_up_within_window(self) -> None:
        trigger = datetime(2027, 1, 15, 20, 0, tzinfo=self.tz)
        now = trigger + timedelta(hours=4)
        self.assertTrue(league_ops.due(now, trigger, timedelta(hours=24)))

    def test_stale_reminder_expires_after_catchup_window(self) -> None:
        trigger = datetime(2027, 1, 15, 20, 0, tzinfo=self.tz)
        now = trigger + timedelta(hours=25)
        self.assertFalse(league_ops.due(now, trigger, timedelta(hours=24)))

    def test_late_start_payload_does_not_claim_future_time(self) -> None:
        starts = datetime(2027, 1, 15, 20, 0, tzinfo=self.tz)
        now = starts + timedelta(hours=2)
        event = {"title": "BLHA Test", "description": "", "priority": "normal"}
        channel = {"label": "LEAGUE CALENDAR", "color": 0xC68F15}
        payload = league_ops.build_payload(
            event,
            channel,
            "1h",
            starts,
            reference_time=now,
        )
        self.assertIn("has reached its scheduled time", payload["embeds"][0]["description"])


class ReminderPileUpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("America/New_York")
        self.starts = datetime(2027, 1, 15, 20, 0, tzinfo=self.tz)
        self.event = {
            "id": "trade-deadline",
            "title": "BLHA Trade Deadline",
            "reminders": ["1d", "3h", "1h", "start"],
            "announcement_reminders": ["1d", "1h"],
        }

    def plan(self, now: datetime, sent: dict | None = None) -> list:
        return league_ops.plan_event(self.event, self.starts, now, sent or {}, [], "league-calendar",
                                     timedelta(hours=24))

    def test_on_time_run_sends_just_that_reminder(self) -> None:
        actions = self.plan(self.starts - timedelta(hours=3) + timedelta(minutes=5),
                            {"trade-deadline::1d::league-calendar": "x", "trade-deadline::1d::league-announcements": "x"})
        self.assertEqual(actions, [("league-calendar", "3h", "send")])

    def test_late_run_sends_only_latest_and_skips_older(self) -> None:
        sent = {"trade-deadline::1d::league-calendar": "x", "trade-deadline::1d::league-announcements": "x"}
        actions = self.plan(self.starts + timedelta(minutes=10), sent)
        calendar = [(r, a) for c, r, a in actions if c == "league-calendar"]
        self.assertEqual(calendar, [("3h", "skip"), ("1h", "skip"), ("start", "send")])
        announcements = [(r, a) for c, r, a in actions if c == "league-announcements"]
        self.assertEqual(announcements, [("1h", "send")])

    def test_already_sent_reminders_are_not_repeated(self) -> None:
        sent = {f"trade-deadline::{r}::league-calendar": "x" for r in ("1d", "3h", "1h", "start")}
        sent.update({f"trade-deadline::{r}::league-announcements": "x" for r in ("1d", "1h")})
        self.assertEqual(self.plan(self.starts + timedelta(hours=1), sent), [])


class UpcomingWindowTests(unittest.TestCase):
    def config(self, starts_at: str | None, enabled: bool = True) -> dict:
        return {
            "settings": {"timezone": "America/New_York", "catchup_window_hours": 24,
                         "default_reminders": ["7d", "1d", "start"]},
            "events": [{"id": "e", "title": "E", "enabled": enabled, "starts_at": starts_at}],
        }

    def test_disabled_or_undated_events_keep_league_office_off(self) -> None:
        now = datetime(2027, 1, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertFalse(league_ops.has_upcoming_events(self.config("2027-01-05T20:00:00", enabled=False), now))
        self.assertFalse(league_ops.has_upcoming_events(self.config(None), now))

    def test_window_opens_an_hour_before_first_reminder(self) -> None:
        tz = ZoneInfo("America/New_York")
        cfg = self.config("2027-01-15T20:00:00")
        first_reminder = datetime(2027, 1, 8, 20, 0, tzinfo=tz)
        self.assertFalse(league_ops.has_upcoming_events(cfg, first_reminder - timedelta(hours=2)))
        self.assertTrue(league_ops.has_upcoming_events(cfg, first_reminder - timedelta(minutes=30)))
        self.assertEqual(league_ops.upcoming_window_start(cfg, first_reminder), first_reminder - timedelta(hours=1))

    def test_window_closes_after_catchup(self) -> None:
        tz = ZoneInfo("America/New_York")
        cfg = self.config("2027-01-15T20:00:00")
        self.assertTrue(league_ops.has_upcoming_events(cfg, datetime(2027, 1, 16, 19, 0, tzinfo=tz)))
        self.assertFalse(league_ops.has_upcoming_events(cfg, datetime(2027, 1, 16, 21, 0, tzinfo=tz)))


if __name__ == "__main__":
    unittest.main()
