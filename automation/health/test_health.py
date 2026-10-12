#!/usr/bin/env python3
"""Offline checks for which runs the health monitor treats as production."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import health


class ProductionRunFilterTests(unittest.TestCase):
    def test_scheduler_live_dispatch_counts(self) -> None:
        row = {"event": "workflow_dispatch", "display_title": "BLHA Wire Engine — live"}
        self.assertTrue(health.is_automatic_live_run(row))

    def test_manual_preview_does_not_count(self) -> None:
        for mode in ("shadow", "preview", "test", "dry-run", "baseline"):
            row = {"event": "workflow_dispatch", "display_title": f"BLHA Fantrax Standings — {mode}"}
            self.assertFalse(health.is_automatic_live_run(row), mode)

    def test_github_cron_run_counts(self) -> None:
        self.assertTrue(health.is_automatic_live_run({"event": "schedule", "display_title": "BLHA Scheduler — live"}))

    def test_push_runs_do_not_count(self) -> None:
        self.assertFalse(health.is_automatic_live_run({"event": "push", "display_title": "anything — live"}))


class CollectIssuesTests(unittest.TestCase):
    NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    CFG = {"workflows": [{"id": "wire", "name": "Wire", "file": "blha-wire-engine.yml", "max_age_minutes": 60},
                         {"id": "scoreboard", "name": "Scoreboard", "file": "blha-fantrax-scoreboard.yml",
                          "max_age_minutes": 90}]}
    SCHEDULE = {"jobs": [{"workflow": "blha-wire-engine.yml"},
                         {"workflow": "blha-fantrax-scoreboard.yml", "phases": ["regular", "playoffs"]}]}

    def _run(self, runs, phase="regular"):
        def run(minutes_ago, conclusion):
            t = (self.NOW - timedelta(minutes=minutes_ago)).isoformat()
            return {"status": "completed", "conclusion": conclusion, "run_started_at": t,
                    "created_at": t, "html_url": "u", "event": "workflow_dispatch"}
        rows = [run(m, c) for m, c in runs]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}), \
                patch.object(health, "now_utc", lambda: self.NOW), \
                patch.object(health, "current_season", lambda now: (phase, str(phase), None)), \
                patch.object(health, "load_schedule", lambda: self.SCHEDULE), \
                patch.object(health, "scheduled_runs", lambda *a: rows), \
                patch.object(health, "inspect_wire_logs", lambda *a, **k: {}):
            return health.collect_issues(self.CFG)

    def test_single_cancelled_run_is_not_a_failure(self) -> None:
        issues = self._run([(5, "cancelled"), (20, "success")])
        self.assertFalse([k for k in issues if k.startswith("failed:")])

    def test_two_cancelled_runs_in_a_row_alert(self) -> None:
        issues = self._run([(5, "cancelled"), (20, "cancelled")])
        self.assertIn("failed:wire", issues)

    def test_unknown_phase_skips_phase_gated_jobs(self) -> None:
        issues = self._run([(500, "success")], phase=None)
        self.assertNotIn("stale:scoreboard", issues)
        self.assertIn("stale:wire", issues)


class PlayoffPoolGateTests(unittest.TestCase):
    """The Playoff Pool is checked only inside the NHL playoff window, like the scheduler runs it."""

    NOW = datetime(2027, 5, 1, 12, 0, tzinfo=timezone.utc)
    CFG = {"workflows": [{"id": "playoff-pool", "name": "Pool", "file": "blha-playoff-pool.yml",
                          "max_age_minutes": 900}]}
    SCHEDULE = {"jobs": [{"workflow": "blha-playoff-pool.yml", "daily_at": ["07:45"], "when": "nhl-playoffs"}]}

    def _run(self, opened):
        from blha import schedule

        stale = (self.NOW - timedelta(hours=20)).isoformat()
        rows = [{"status": "completed", "conclusion": "success", "run_started_at": stale, "created_at": stale,
                 "html_url": "u", "event": "workflow_dispatch"}]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}), \
                patch.object(health, "now_utc", lambda: self.NOW), \
                patch.object(health, "current_season", lambda now: ("offseason", "offseason", None)), \
                patch.object(health, "load_schedule", lambda: self.SCHEDULE), \
                patch.object(health, "scheduled_runs", lambda *a: rows), \
                patch.dict(schedule.CONDITIONS, {"nhl-playoffs": (lambda now=None: opened, "outside")}):
            return health.collect_issues(self.CFG)

    def test_outside_the_window_is_not_checked(self) -> None:
        self.assertEqual(self._run(None), {})

    def test_inside_the_window_a_missed_run_alerts(self) -> None:
        self.assertIn("stale:playoff-pool", self._run(self.NOW - timedelta(days=10)))

    def test_window_just_opened_gets_a_grace_period(self) -> None:
        self.assertEqual(self._run(self.NOW - timedelta(hours=2)), {})


if __name__ == "__main__":
    unittest.main()
