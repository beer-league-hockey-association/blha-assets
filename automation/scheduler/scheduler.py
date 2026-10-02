#!/usr/bin/env python3
"""BLHA Scheduler: start each automation workflow in live mode when it is due.

GitHub's built-in cron is best-effort and, for this repository, regularly runs
hours late or skips runs entirely. This dispatcher replaces the individual
per-workflow cron entries with one catch-up scheduler:

- An external timer (cron-job.org) starts this workflow every 15 minutes.
- GitHub cron also starts it as a backup.
- Each start reads schedule.yaml, looks at each workflow's recent runs, and
  dispatches the workflows that are due with ``mode=live``.

Because due-ness is computed from the last live run rather than from the
current minute, a missed or delayed start never causes a job to be skipped;
the job simply runs at the next check. Running the scheduler twice in a row is
harmless because the second pass sees the runs the first pass started.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "schedule.yaml"

# Runs that ended this way did no work, so they do not count as the job having
# run. Failed runs DO count: retrying a failing job every 15 minutes would only
# create noise, and the health monitor already reports failures.
IGNORED_CONCLUSIONS = {"cancelled", "skipped"}

LIVE_SUFFIX = "— live"


@dataclass
class Decision:
    job_id: str
    workflow: str
    due: bool
    reason: str


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def is_live_run(run: dict[str, Any]) -> bool:
    """True for runs that did real live work (scheduled or dispatched live).

    Every BLHA workflow sets a run-name ending in "— <mode>", so live runs can
    be told apart from manual preview/test runs without reading their logs.
    """
    if run.get("conclusion") in IGNORED_CONCLUSIONS:
        return False
    if run.get("event") == "schedule":
        return True
    title = str(run.get("display_title") or run.get("name") or "").strip()
    return title.endswith(LIVE_SUFFIX)


def last_live_run_time(runs: Iterable[dict[str, Any]]) -> datetime | None:
    times = [
        parse_dt(run.get("created_at"))
        for run in runs
        if is_live_run(run)
    ]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def most_recent_slot(now: datetime, slots: list[str], tz: ZoneInfo) -> datetime:
    """Return the latest daily slot at or before ``now`` (as UTC)."""
    local_now = now.astimezone(tz)
    candidates: list[datetime] = []
    for day_offset in (0, -1):
        day = (local_now + timedelta(days=day_offset)).date()
        for raw in slots:
            hour, minute = (int(part) for part in str(raw).split(":", 1))
            local = datetime.combine(day, time(hour, minute), tzinfo=tz)
            if local <= local_now:
                candidates.append(local)
    if not candidates:
        raise ValueError(f"no usable daily slot in {slots!r}")
    return max(candidates).astimezone(timezone.utc)


def decide(
    job: dict[str, Any],
    runs: list[dict[str, Any]],
    now: datetime,
    tz: ZoneInfo,
    tolerance: timedelta,
) -> Decision:
    job_id = str(job.get("id") or job.get("workflow"))
    workflow = str(job["workflow"])
    last = last_live_run_time(runs)
    last_text = last.strftime("%Y-%m-%d %H:%M UTC") if last else "never"

    if job.get("every_minutes"):
        interval = timedelta(minutes=int(job["every_minutes"]))
        threshold = max(interval - tolerance, interval / 2)
        if last is None:
            return Decision(job_id, workflow, True, "no previous live run")
        age = now - last
        age_min = int(age.total_seconds() // 60)
        if age >= threshold:
            return Decision(job_id, workflow, True, f"last live run {age_min}m ago ({last_text})")
        return Decision(job_id, workflow, False, f"last live run {age_min}m ago")

    if job.get("daily_at"):
        slot = most_recent_slot(now, list(job["daily_at"]), tz)
        slot_text = slot.astimezone(tz).strftime("%a %H:%M %Z")
        if last is None or last < slot:
            return Decision(job_id, workflow, True, f"slot {slot_text} not yet run (last {last_text})")
        return Decision(job_id, workflow, False, f"slot {slot_text} already ran")

    raise ValueError(f"job {job_id} needs every_minutes or daily_at")


class GitHub:
    def __init__(self, token: str, repository: str, api_base: str) -> None:
        self.repository = repository
        self.api_base = api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BLHA-Scheduler/1.0",
        })

    def recent_runs(self, workflow: str, per_page: int = 40) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.api_base}/repos/{self.repository}/actions/workflows/{workflow}/runs",
            params={"per_page": per_page},
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json().get("workflow_runs", [])
        return [row for row in rows if isinstance(row, dict)]

    def dispatch_live(self, workflow: str, ref: str) -> None:
        response = self.session.post(
            f"{self.api_base}/repos/{self.repository}/actions/workflows/{workflow}/dispatches",
            json={"ref": ref, "inputs": {"mode": "live"}},
            timeout=30,
        )
        if response.status_code != 204:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")


def load_config() -> dict[str, Any]:
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("jobs"), list) or not data["jobs"]:
        raise ValueError("schedule.yaml must define a non-empty jobs list")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report what is due without starting anything.")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com")
    ref = os.getenv("GITHUB_REF_NAME", "main").strip() or "main"
    if not token or not repository:
        print("ERROR: GITHUB_TOKEN and GITHUB_REPOSITORY are required")
        return 1

    cfg = load_config()
    tz = ZoneInfo(str(cfg.get("timezone") or "America/New_York"))
    tolerance = timedelta(minutes=int(cfg.get("interval_tolerance_minutes", 5)))
    now = datetime.now(timezone.utc)
    gh = GitHub(token, repository, api_base)

    print(f"BLHA SCHEDULER now={now.astimezone(tz).strftime('%Y-%m-%d %H:%M %Z')} dry_run={args.dry_run} ref={ref}")
    started = errors = 0
    for job in cfg["jobs"]:
        try:
            decision = decide(job, gh.recent_runs(str(job["workflow"])), now, tz, tolerance)
        except Exception as exc:
            print(f"ERROR   {job.get('id')}: could not evaluate: {exc}")
            errors += 1
            continue

        if not decision.due:
            print(f"WAIT    {decision.job_id}: {decision.reason}")
            continue
        if args.dry_run:
            print(f"DUE     {decision.job_id}: {decision.reason} (dry run, not started)")
            continue
        try:
            gh.dispatch_live(decision.workflow, ref)
            print(f"STARTED {decision.job_id}: {decision.reason}")
            started += 1
        except Exception as exc:
            print(f"ERROR   {decision.job_id}: dispatch failed: {exc}")
            errors += 1

    print(f"SUMMARY started={started} errors={errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
