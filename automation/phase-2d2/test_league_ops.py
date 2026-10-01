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


if __name__ == "__main__":
    unittest.main()
