#!/usr/bin/env python3
"""BLHA automation-health runner.

Adds production-noise filters around the core health monitor:
- first-schedule startup grace for newly created workflows;
- repeated-run confirmation before a Wire flood-guard event becomes an alert;
- root-cause suppression of the Wire flood guard while the Wire schedule is stale;
- automatic suppression of League Office schedule alerts while every event is disabled.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import health as core


_original_collect_issues = core.collect_issues
ROOT = Path(__file__).resolve().parents[1]
LEAGUE_OFFICE_EVENTS = ROOT / "phase-2d2" / "events.yaml"


def github_session() -> tuple[Any, str, str] | None:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repository or not token:
        return None

    session = core.requests.Session()
    session.headers.update(core.github_headers(token))
    return session, repository, api_base


def apply_startup_grace(
    cfg: dict[str, Any],
    issues: dict[str, dict[str, Any]],
    connection: tuple[Any, str, str] | None,
) -> None:
    settings = cfg.get("settings") or {}
    grace_minutes = int(settings.get("no_run_grace_minutes") or 0)
    if grace_minutes <= 0 or connection is None:
        return

    no_run_ids = {
        str(item.get("id") or "workflow"): item
        for item in (cfg.get("workflows") or [])
        if isinstance(item, dict)
        and f"no-run:{str(item.get('id') or 'workflow')}" in issues
    }
    if not no_run_ids:
        return

    session, repository, api_base = connection
    current = core.now_utc()

    for workflow_id, item in no_run_ids.items():
        workflow_file = str(item.get("file") or "").strip()
        if not workflow_file:
            continue
        try:
            metadata = core.api_get(
                session,
                api_base,
                f"/repos/{repository}/actions/workflows/{workflow_file}",
            )
            created_at = core.parse_dt(
                str(metadata.get("created_at") or "")
                if isinstance(metadata, dict)
                else ""
            )
        except Exception as exc:
            print(
                f"STARTUP-GRACE CHECK WARNING [{workflow_id}]: "
                f"could not read workflow metadata: {exc}"
            )
            continue

        if created_at is None:
            continue

        age_minutes = int((current - created_at).total_seconds() // 60)
        if age_minutes < grace_minutes:
            issues.pop(f"no-run:{workflow_id}", None)
            print(
                f"STARTUP GRACE [{workflow_id}]: no scheduled run yet; "
                f"workflow age={age_minutes}m grace={grace_minutes}m"
            )


def apply_wire_rate_guard_confirmation(
    cfg: dict[str, Any],
    issues: dict[str, dict[str, Any]],
    connection: tuple[Any, str, str] | None,
) -> None:
    """Suppress a one-off Wire rate-guard event."""
    if "wire-rate-guard" not in issues or connection is None:
        return

    settings = cfg.get("settings") or {}
    threshold = int(settings.get("wire_rate_guard_consecutive_runs") or 1)
    if threshold <= 1:
        return

    wire_item = next(
        (
            item
            for item in (cfg.get("workflows") or [])
            if isinstance(item, dict) and item.get("id") == "wire-engine"
        ),
        None,
    )
    if not wire_item:
        return

    workflow_file = str(wire_item.get("file") or "").strip()
    if not workflow_file:
        return

    session, repository, api_base = connection
    try:
        runs = core.scheduled_runs(
            session,
            api_base,
            repository,
            workflow_file,
            per_page=max(10, threshold + 2),
        )
    except Exception as exc:
        print(f"RATE-GUARD CONFIRMATION WARNING: could not read Wire runs: {exc}")
        return

    completed = [
        row
        for row in runs
        if row.get("status") == "completed" and row.get("id")
    ][:threshold]
    if len(completed) < threshold:
        issues.pop("wire-rate-guard", None)
        print(
            f"RATE-GUARD INFO: only {len(completed)} completed scheduled Wire run(s) "
            f"available; need {threshold} consecutive runs before alerting"
        )
        return

    guard_hits = 0
    for row in completed:
        try:
            log_text = core.download_run_log(
                session,
                api_base,
                repository,
                int(row["id"]),
            )
        except Exception as exc:
            print(f"RATE-GUARD CONFIRMATION WARNING: could not inspect run log: {exc}")
            return
        if "RATE-GUARD SUPPRESSED" in log_text:
            guard_hits += 1

    if guard_hits < threshold:
        issues.pop("wire-rate-guard", None)
        print(
            f"RATE-GUARD INFO: latest Wire run hit the guard, but only "
            f"{guard_hits}/{threshold} consecutive run(s) did; treating as a "
            "one-off protected news burst"
        )


def apply_wire_root_cause_suppression(issues: dict[str, dict[str, Any]]) -> None:
    """Prefer the stale Wire schedule as the actionable root cause.

    A delayed GitHub schedule can leave a backlog of stories for the next Wire
    execution. That catch-up run can legitimately hit the production flood
    guard, so reporting both conditions at once creates two alerts for one
    operational problem. While the schedule itself is stale, retain the stale
    alert and defer rate-guard evaluation until scheduled execution recovers.
    """
    if "stale:wire-engine" not in issues or "wire-rate-guard" not in issues:
        return

    issues.pop("wire-rate-guard", None)
    print(
        "WIRE RATE-GUARD SECONDARY: suppressed while the Wire schedule is stale; "
        "the rate guard will be evaluated again after scheduled execution recovers."
    )


def apply_dormant_league_office(issues: dict[str, dict[str, Any]]) -> None:
    """Do not page on League Office scheduling while every event is disabled.

    Monitoring automatically resumes as soon as any event in events.yaml is enabled.
    """
    try:
        config = core.yaml.safe_load(LEAGUE_OFFICE_EVENTS.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"LEAGUE-OFFICE DORMANCY WARNING: could not read events config: {exc}")
        return

    events = [item for item in (config.get("events") or []) if isinstance(item, dict)]
    if any(bool(item.get("enabled")) for item in events):
        return

    removed = 0
    for key in list(issues):
        data = issues.get(key) or {}
        if key.endswith(":league-office") or data.get("workflow") == "BLHA League Office Automation":
            issues.pop(key, None)
            removed += 1
    print(
        "LEAGUE OFFICE DORMANT: all configured events are disabled; "
        f"suppressed {removed} health issue(s). Monitoring resumes automatically when an event is enabled."
    )


def collect_issues_with_safety_filters(
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    issues = _original_collect_issues(cfg)
    connection = github_session()
    apply_startup_grace(cfg, issues, connection)
    apply_wire_rate_guard_confirmation(cfg, issues, connection)
    apply_wire_root_cause_suppression(issues)
    apply_dormant_league_office(issues)
    return issues


core.collect_issues = collect_issues_with_safety_filters

if __name__ == "__main__":
    sys.exit(core.main())
