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


class NhlPlayoffWindowTests(unittest.TestCase):
    """when: nhl-playoffs, from the NHL schedule's season dates (synthetic shape, see nhl_playoffs.py)."""

    SEASON = {"regularSeasonEndDate": "2027-04-15", "playoffEndDate": "2027-06-24", "gameWeek": []}

    def start(self, now: datetime, raw: dict | None = None) -> datetime | None:
        from blha import nhl_playoffs

        calls: list[str] = []

        def get(url: str) -> dict:
            calls.append(url)
            return raw if raw is not None else self.SEASON

        result = nhl_playoffs.window_start(now, ET, get)
        self.calls = calls
        return result

    def test_opens_five_days_before_the_regular_season_ends(self) -> None:
        opens = datetime(2027, 4, 10, 0, 0, tzinfo=ET).astimezone(timezone.utc)
        self.assertIsNone(self.start(opens - timedelta(minutes=1)))
        self.assertEqual(self.start(opens), opens)
        self.assertEqual(self.start(datetime(2027, 5, 20, 7, 45, tzinfo=ET).astimezone(timezone.utc)), opens)
        self.assertTrue(self.calls[0].endswith("/v1/schedule/2027-05-20"))

    def test_closes_two_days_after_the_last_scheduled_playoff_date(self) -> None:
        last_morning = datetime(2027, 6, 26, 19, 45, tzinfo=ET).astimezone(timezone.utc)
        self.assertIsNotNone(self.start(last_morning))
        self.assertIsNone(self.start(datetime(2027, 6, 27, 0, 0, tzinfo=ET).astimezone(timezone.utc)))

    def test_no_nhl_request_outside_the_spring(self) -> None:
        for when in (utc("2026-10-02T15:00:00"), utc("2027-01-15T12:00:00"), utc("2027-08-01T12:00:00")):
            self.assertIsNone(self.start(when))
            self.assertEqual(self.calls, [], when)

    def test_missing_season_dates_raise_so_the_job_runs_anyway(self) -> None:
        with self.assertRaises(ValueError):
            self.start(utc("2027-04-20T12:00:00"), raw={"gameWeek": []})

    def test_pool_job_is_gated_by_the_condition(self) -> None:
        from unittest.mock import patch

        from blha import schedule

        job = next(j for j in scheduler.load_config()["jobs"] if j["id"] == "playoff-pool")
        now = utc("2027-04-20T12:00:00")
        with patch.dict(schedule.CONDITIONS, {"nhl-playoffs": (lambda now=None: None, "outside the NHL playoff window")}):
            self.assertEqual(schedule.job_active(job, "offseason", now), (False, "outside the NHL playoff window"))
        with patch.dict(schedule.CONDITIONS, {"nhl-playoffs": (lambda now=None: now, "")}):
            self.assertTrue(schedule.job_active(job, "offseason", now)[0])

        def broken(now=None):
            raise ValueError("no season dates")

        with patch.dict(schedule.CONDITIONS, {"nhl-playoffs": (broken, "")}):
            active, why = schedule.job_active(job, "offseason", now)
            self.assertTrue(active)
            self.assertIn("running anyway", why)


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


if __name__ == "__main__":
    unittest.main()
