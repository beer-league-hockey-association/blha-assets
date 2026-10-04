#!/usr/bin/env python3
"""Offline checks for the season rollover tool."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import rollover  # noqa: E402

INFO = json.loads((HERE.parent / "tests" / "fixtures" / "league_info_2026_test.json").read_text())
BEFORE = datetime(2026, 9, 1, tzinfo=timezone.utc)
ET = ZoneInfo("America/New_York")


def standings(played=0):
    return [{"wins": played, "losses": 0, "ties": 0} for _ in range(12)]


def levels(info=INFO, rows=None, now=BEFORE):
    return {f.text: f.level for f in rollover.check_league(info, standings() if rows is None else rows, now)}


class CheckTests(unittest.TestCase):
    def test_matching_league_has_no_failures(self):
        self.assertNotIn("FAIL", levels().values())

    def test_wrong_playoff_size_fails(self):
        info = json.loads(json.dumps(INFO))
        info["playoffs"]["numPlayoffTeams"] = 4
        self.assertIn("FAIL", levels(info).values())

    def test_wrong_team_count_fails(self):
        info = json.loads(json.dumps(INFO))
        info["teamInfo"].pop(next(iter(info["teamInfo"])))
        self.assertIn("FAIL", levels(info).values())

    def test_started_or_played_league_only_warns(self):
        got = levels(rows=standings(5), now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        self.assertNotIn("FAIL", got.values())
        self.assertGreaterEqual(list(got.values()).count("WARN"), 2)


class PrizeTests(unittest.TestCase):
    def test_running_prize_countdown_blocks_rollover(self):
        end = datetime(2027, 4, 5, tzinfo=timezone.utc)
        state = {"anchors": {"season_end_final": end.isoformat()}}
        self.assertIn("Roll over after", rollover.pending_prizes(state, end + timedelta(days=10)))
        self.assertIsNone(rollover.pending_prizes(state, end + timedelta(days=31)))
        self.assertIsNone(rollover.pending_prizes({}, end))


class EventTests(unittest.TestCase):
    def test_past_disabled_and_undated_events_are_listed(self):
        events = {"events": [
            {"id": "a", "enabled": True, "starts_at": "2026-01-01T20:00:00"},
            {"id": "b", "enabled": False, "starts_at": "2030-01-01T20:00:00"},
            {"id": "c", "enabled": True, "starts_at": "2030-01-01T20:00:00"},
            {"id": "d", "enabled": True},
        ]}
        got = rollover.events_needing_dates(events, BEFORE.replace(year=2027), ET)
        self.assertEqual([g.split(":")[0] for g in got], ["a", "b", "d"])


class ConfigTests(unittest.TestCase):
    def test_write_config_changes_only_league_id_and_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "league.yaml"
            p.write_text('# note\nleague_id: old123\nseason_label: "2026-27 TEST"\ntimezone: America/New_York\n')
            self.assertTrue(rollover.write_config(p, "new456", "2027-28"))
            self.assertEqual(p.read_text(), '# note\nleague_id: new456\nseason_label: "2027-28"\ntimezone: America/New_York\n')
            self.assertFalse(rollover.write_config(p, "new456", "2027-28"))

    def test_state_list_never_includes_carryover_state(self):
        joined = " ".join(rollover.SEASON_STATE)
        for keep in ("wire", "health", "minors"):
            self.assertNotIn(keep, joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
