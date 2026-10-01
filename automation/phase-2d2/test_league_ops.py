#!/usr/bin/env python3
"""Offline regression checks for BLHA League Office time handling."""

from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
