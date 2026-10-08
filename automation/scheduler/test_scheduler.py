#!/usr/bin/env python3
"""Offline regression checks for the BLHA Scheduler's due-time logic."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import scheduler

ET = ZoneInfo("America/New_York")
TOL = timedelta(minutes=5)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def run(created: datetime, title: str = "BLHA Job — live", event: str = "workflow_dispatch",
        conclusion: str | None = "success") -> dict:
    return {
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "display_title": title,
        "event": event,
        "conclusion": conclusion,
    }


class IntervalJobTests(unittest.TestCase):
    job = {"id": "wire", "workflow": "blha-wire-engine.yml", "every_minutes": 15}
    now = utc("2026-10-02T15:00:00")

    def test_never_run_is_due(self) -> None:
        self.assertTrue(scheduler.decide(self.job, [], self.now, ET, TOL).due)

    def test_recent_live_run_waits(self) -> None:
        runs = [run(self.now - timedelta(minutes=5))]
        self.assertFalse(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_tolerance_keeps_fifteen_minute_cadence(self) -> None:
        # A tick that lands 14 minutes after the last run must still start it,
        # otherwise jitter would halve the cadence.
        runs = [run(self.now - timedelta(minutes=14))]
        self.assertTrue(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_manual_preview_run_does_not_count(self) -> None:
        runs = [run(self.now - timedelta(minutes=2), title="BLHA Wire Engine — shadow")]
        self.assertTrue(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_cancelled_live_run_does_not_count(self) -> None:
        runs = [run(self.now - timedelta(minutes=2), conclusion="cancelled")]
        self.assertTrue(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_in_progress_live_run_counts(self) -> None:
        runs = [run(self.now - timedelta(minutes=1), conclusion=None)]
        self.assertFalse(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_failed_live_run_counts(self) -> None:
        # Failures are reported by the health monitor, not retried every tick.
        runs = [run(self.now - timedelta(minutes=3), conclusion="failure")]
        self.assertFalse(scheduler.decide(self.job, runs, self.now, ET, TOL).due)

    def test_legacy_cron_run_counts(self) -> None:
        runs = [run(self.now - timedelta(minutes=3), title="BLHA Wire Engine", event="schedule")]
        self.assertFalse(scheduler.decide(self.job, runs, self.now, ET, TOL).due)


class DailyJobTests(unittest.TestCase):
    job = {"id": "standings", "workflow": "blha-fantrax-standings.yml", "daily_at": ["07:30"]}

    def test_due_after_slot_when_not_yet_run(self) -> None:
        now = datetime(2026, 10, 2, 9, 0, tzinfo=ET).astimezone(timezone.utc)
        yesterday = datetime(2026, 10, 1, 7, 31, tzinfo=ET).astimezone(timezone.utc)
        self.assertTrue(scheduler.decide(self.job, [run(yesterday)], now, ET, TOL).due)

    def test_waits_after_slot_already_ran(self) -> None:
        now = datetime(2026, 10, 2, 9, 0, tzinfo=ET).astimezone(timezone.utc)
        today = datetime(2026, 10, 2, 7, 32, tzinfo=ET).astimezone(timezone.utc)
        self.assertFalse(scheduler.decide(self.job, [run(today)], now, ET, TOL).due)

    def test_before_todays_slot_uses_yesterdays(self) -> None:
        now = datetime(2026, 10, 2, 6, 0, tzinfo=ET).astimezone(timezone.utc)
        yesterday = datetime(2026, 10, 1, 7, 31, tzinfo=ET).astimezone(timezone.utc)
        self.assertFalse(scheduler.decide(self.job, [run(yesterday)], now, ET, TOL).due)

    def test_late_scheduler_catches_up_once(self) -> None:
        # Scheduler was down from 07:00 to 11:00; standings runs once at 11:00.
        now = datetime(2026, 10, 2, 11, 0, tzinfo=ET).astimezone(timezone.utc)
        yesterday = datetime(2026, 10, 1, 7, 31, tzinfo=ET).astimezone(timezone.utc)
        self.assertTrue(scheduler.decide(self.job, [run(yesterday)], now, ET, TOL).due)
        after = [run(now), run(yesterday)]
        later = now + timedelta(minutes=15)
        self.assertFalse(scheduler.decide(self.job, after, later, ET, TOL).due)

    def test_two_slots_per_day(self) -> None:
        job = {"id": "scoreboard", "workflow": "x.yml", "daily_at": ["02:30", "19:15"]}
        morning_run = datetime(2026, 10, 2, 2, 31, tzinfo=ET).astimezone(timezone.utc)
        at_noon = datetime(2026, 10, 2, 12, 0, tzinfo=ET).astimezone(timezone.utc)
        evening = datetime(2026, 10, 2, 19, 20, tzinfo=ET).astimezone(timezone.utc)
        self.assertFalse(scheduler.decide(job, [run(morning_run)], at_noon, ET, TOL).due)
        self.assertTrue(scheduler.decide(job, [run(morning_run)], evening, ET, TOL).due)

    def test_slot_is_local_time_across_dst(self) -> None:
        # 07:30 Eastern is 11:30 UTC in October and 12:30 UTC in January.
        oct_slot = scheduler.most_recent_slot(utc("2026-10-02T13:00:00"), ["07:30"], ET)
        jan_slot = scheduler.most_recent_slot(utc("2027-01-15T13:00:00"), ["07:30"], ET)
        self.assertEqual(oct_slot, utc("2026-10-02T11:30:00"))
        self.assertEqual(jan_slot, utc("2027-01-15T12:30:00"))


class ConfigTests(unittest.TestCase):
    def test_every_job_has_valid_timing_and_workflow(self) -> None:
        cfg = scheduler.load_config()
        now = utc("2026-10-02T15:00:00")
        tz = ZoneInfo(cfg["timezone"])
        seen = set()
        for job in cfg["jobs"]:
            self.assertTrue((scheduler.ROOT.parents[1] / ".github" / "workflows" / job["workflow"]).exists(),
                            f"missing workflow file for {job['id']}")
            self.assertNotIn(job["workflow"], seen)
            seen.add(job["workflow"])
            scheduler.decide(job, [], now, tz, TOL)

    def test_faster_pace_must_be_valid(self) -> None:
        import tempfile
        from pathlib import Path

        from blha.schedule import load_schedule

        bad = [
            "jobs:\n  - id: x\n    workflow: x.yml\n    daily_at: ['08:00']\n    faster: {when: trade-deadline-day, every_minutes: 15}\n",
            "jobs:\n  - id: x\n    workflow: x.yml\n    every_minutes: 30\n    faster: {when: no-such-condition, every_minutes: 15}\n",
            "jobs:\n  - id: x\n    workflow: x.yml\n    every_minutes: 30\n    faster: {when: trade-deadline-day, every_minutes: 45}\n",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for i, text in enumerate(bad):
                path = Path(tmp) / f"s{i}.yaml"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_schedule(path)

    def test_faster_job_uses_its_short_interval_only_while_the_condition_holds(self) -> None:
        from unittest.mock import patch

        from blha import schedule

        job = {"id": "x", "workflow": "x.yml", "every_minutes": 30,
               "faster": {"when": "trade-deadline-day", "every_minutes": 15}}
        now = utc("2027-02-21T20:00:00")
        runs = [run(now - timedelta(minutes=12))]
        with patch.dict(schedule.CONDITIONS, {"trade-deadline-day": (lambda n: now, "")}):
            fast, _ = schedule.paced(job, now)
        with patch.dict(schedule.CONDITIONS, {"trade-deadline-day": (lambda n: None, "")}):
            slow, _ = schedule.paced(job, now)
        self.assertTrue(scheduler.decide(fast, runs, now, ET, TOL).due)
        self.assertFalse(scheduler.decide(slow, runs, now, ET, TOL).due)


if __name__ == "__main__":
    unittest.main()
