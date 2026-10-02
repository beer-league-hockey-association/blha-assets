#!/usr/bin/env python3
"""Offline checks for which runs the health monitor treats as production."""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
