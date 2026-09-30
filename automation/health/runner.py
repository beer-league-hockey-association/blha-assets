#!/usr/bin/env python3
"""BLHA automation-health runner.

Adds first-schedule startup grace around the core health monitor so a newly
created GitHub Actions workflow is not reported as down before GitHub has had a
reasonable opportunity to fire its first scheduled run.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import health as core


_original_collect_issues = core.collect_issues


def collect_issues_with_startup_grace(
    cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    issues = _original_collect_issues(cfg)
    settings = cfg.get("settings") or {}
    grace_minutes = int(settings.get("no_run_grace_minutes") or 0)
    if grace_minutes <= 0:
        return issues

    no_run_ids = {
        str(item.get("id") or "workflow"): item
        for item in (cfg.get("workflows") or [])
        if isinstance(item, dict)
        and f"no-run:{str(item.get('id') or 'workflow')}" in issues
    }
    if not no_run_ids:
        return issues

    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repository or not token:
        return issues

    session = core.requests.Session()
    session.headers.update(core.github_headers(token))
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

    return issues


core.collect_issues = collect_issues_with_startup_grace

if __name__ == "__main__":
    sys.exit(core.main())
