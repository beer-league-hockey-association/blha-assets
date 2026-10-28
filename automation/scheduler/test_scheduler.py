#!/usr/bin/env python3
"""Offline regression checks for the BLHA Scheduler's due-time logic."""

from __future__ import annotations

import unittest
from pathlib import Path
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



# --- GitHub hiccups ----------------------------------------------------------

import contextlib
import io
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from blha import github_api


class _FlakyHandler(BaseHTTPRequestHandler):
    """Answers each request from the server's script: a status code, or "drop"."""

    def _answer(self) -> None:
        self.server.hits[self.command] = self.server.hits.get(self.command, 0) + 1
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        step = self.server.script.pop(0) if self.server.script else 200
        if step == "drop":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        body = b'{"workflow_runs": []}'
        self.send_response(step)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args) -> None:
        pass


class RetrySessionTests(unittest.TestCase):
    def serve(self, script: list) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FlakyHandler)
        server.script, server.hits = list(script), {}
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        return f"http://127.0.0.1:{server.server_address[1]}/runs"

    def session(self) -> requests.Session:
        s = github_api.add_retries(requests.Session(), backoff_factor=0)
        s.trust_env = False  # talk to the local server directly, not through a proxy
        return s

    def test_read_retries_a_bad_gateway(self) -> None:
        url = self.serve([502, 200])
        self.assertEqual(self.session().get(url, timeout=5).status_code, 200)
        self.assertEqual(self.server.hits["GET"], 2)

    def test_read_retries_a_dropped_connection(self) -> None:
        url = self.serve(["drop", 200])
        self.assertEqual(self.session().get(url, timeout=5).status_code, 200)
        self.assertEqual(self.server.hits["GET"], 2)

    def test_read_gives_up_after_three_retries(self) -> None:
        url = self.serve([500, 500, 500, 500, 200])
        response = self.session().get(url, timeout=5)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.server.hits["GET"], 4)
        with self.assertRaises(requests.HTTPError) as caught:
            response.raise_for_status()
        self.assertTrue(github_api.is_transient(caught.exception))

    def test_a_write_that_reached_github_is_never_repeated(self) -> None:
        url = self.serve([500, 204])
        self.assertEqual(self.session().post(url, json={}, timeout=5).status_code, 500)
        self.assertEqual(self.server.hits["POST"], 1)

    def test_real_problems_are_not_transient(self) -> None:
        for status in (401, 403, 404, 422):
            self.assertFalse(github_api.is_transient(scheduler.DispatchError(status, "")), status)
        for status in (429, 500, 502, 503, 504):
            self.assertTrue(github_api.is_transient(scheduler.DispatchError(status, "")), status)
        self.assertTrue(github_api.is_transient(requests.ConnectionError("Remote end closed connection")))
        self.assertTrue(github_api.is_transient(requests.Timeout()))
        self.assertFalse(github_api.is_transient(ValueError("bad schedule")))


class _FakeGitHub:
    """Stands in for the GitHub client: reads and dispatches follow a per-workflow plan."""

    reads: dict = {}
    dispatches: dict = {}
    started: list = []

    def __init__(self, *args) -> None:
        pass

    def recent_runs(self, workflow: str, per_page: int = 40) -> list:
        outcome = self.reads.get(workflow)
        if isinstance(outcome, BaseException):
            raise outcome
        return []  # never run, so every job is due

    def dispatch_live(self, workflow: str, ref: str) -> None:
        outcome = self.dispatches.get(workflow)
        if isinstance(outcome, BaseException):
            raise outcome
        self.started.append(workflow)


class SchedulerRunTests(unittest.TestCase):
    JOBS = {"timezone": "America/New_York", "jobs": [
        {"id": "wire", "workflow": "wire.yml", "every_minutes": 15},
        {"id": "desk", "workflow": "desk.yml", "every_minutes": 15},
    ]}

    def run_scheduler(self, reads: dict | None = None, dispatches: dict | None = None) -> tuple[int, str]:
        _FakeGitHub.reads, _FakeGitHub.dispatches, _FakeGitHub.started = reads or {}, dispatches or {}, []
        out = io.StringIO()
        with patch.object(scheduler, "GitHub", _FakeGitHub), \
             patch.object(scheduler, "load_config", lambda: self.JOBS), \
             patch.object(scheduler, "current_phase", lambda now: ("regular", "test")), \
             patch.object(scheduler, "job_active", lambda job, phase, now: (True, "")), \
             patch.object(scheduler, "paced", lambda job, now: (job, "")), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r"}), \
             patch.object(sys, "argv", ["scheduler.py"]), \
             contextlib.redirect_stdout(out):
            code = scheduler.main()
        return code, out.getvalue()

    def test_clean_run(self) -> None:
        code, log = self.run_scheduler()
        self.assertEqual(code, 0)
        self.assertEqual(_FakeGitHub.started, ["wire.yml", "desk.yml"])

    def test_a_start_github_fumbles_is_left_for_the_next_run(self) -> None:
        # The Oct 11 and Oct 14, 2026 failures: one dispatch got HTTP 500.
        code, log = self.run_scheduler(dispatches={"desk.yml": scheduler.DispatchError(500, "Failed to run workflow dispatch")})
        self.assertEqual(code, 0)
        self.assertIn("RETRY   desk: not started (HTTP 500)", log)
        self.assertEqual(_FakeGitHub.started, ["wire.yml"])

    def test_a_read_github_fumbles_is_left_for_the_next_run(self) -> None:
        # The Oct 12 and Oct 13, 2026 failures: a 502 and a dropped connection on one read.
        for exc in (requests.HTTPError(response=type("R", (), {"status_code": 502})()),
                    requests.ConnectionError("Remote end closed connection without response")):
            code, log = self.run_scheduler(reads={"wire.yml": exc})
            self.assertEqual(code, 0, log)
            self.assertIn("RETRY   wire: GitHub didn't answer", log)
            self.assertEqual(_FakeGitHub.started, ["desk.yml"])

    def test_a_real_problem_still_fails_the_run(self) -> None:
        code, log = self.run_scheduler(dispatches={"desk.yml": scheduler.DispatchError(403, "Resource not accessible")})
        self.assertEqual(code, 1)
        self.assertIn("ERROR   desk: dispatch failed: HTTP 403", log)

    def test_github_down_for_the_whole_run_fails_it(self) -> None:
        down = requests.ConnectionError("down")
        code, log = self.run_scheduler(reads={"wire.yml": down, "desk.yml": down})
        self.assertEqual(code, 1)
        self.assertIn("GitHub didn't answer any read this run", log)

if __name__ == "__main__":
    unittest.main()


class PauseTests(unittest.TestCase):
    def setUp(self) -> None:
        from blha import schedule as sched
        self.sched = sched
        self.cfg = {"timezone": "America/New_York", "paused_until": "2027-05-01",
                    "jobs": [{"id": "wire", "workflow": "w.yml", "every_minutes": 15},
                             {"id": "guard", "workflow": "g.yml", "daily_at": ["06:15"], "runs_while_paused": True}]}

    def test_jobs_are_held_until_midnight_eastern(self) -> None:
        wire, guard = self.cfg["jobs"]
        before = utc("2027-05-01T03:59:00Z")  # 23:59 EDT on April 30
        after = utc("2027-05-01T04:00:00Z")   # 00:00 EDT on May 1
        self.assertIn("paused until 2027-05-01", self.sched.job_paused(wire, self.cfg, before))
        self.assertIsNone(self.sched.job_paused(wire, self.cfg, after))

    def test_runs_while_paused_job_is_never_held(self) -> None:
        guard = self.cfg["jobs"][1]
        self.assertIsNone(self.sched.job_paused(guard, self.cfg, utc("2026-11-01T12:00:00Z")))

    def test_no_pause_line_means_no_pause(self) -> None:
        cfg = {k: v for k, v in self.cfg.items() if k != "paused_until"}
        self.assertIsNone(self.sched.paused(cfg, utc("2026-11-01T12:00:00Z")))
        self.assertIsNone(self.sched.pause_end(cfg))

    def test_bad_date_is_rejected(self) -> None:
        import tempfile, yaml
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.yaml"
            path.write_text(yaml.safe_dump({**self.cfg, "paused_until": "May 2027"}))
            with self.assertRaises(ValueError):
                self.sched.load_schedule(path)

    def test_live_schedule_keeps_the_dormancy_guard_running(self) -> None:
        cfg = self.sched.load_schedule()
        running = [j["id"] for j in cfg["jobs"] if self.sched.job_paused(j, cfg, utc("2026-11-01T12:00:00Z")) is None]
        self.assertEqual(running, ["dormancy-guard"])
