#!/usr/bin/env python3
"""BLHA automation health monitor.

Checks scheduled production workflows for failures and missed schedules, inspects
The Wire logs for delivery problems, flood-guard activity, and persistent source
errors, and posts only state changes to a private commissioner-facing Discord
webhook.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent
AUTOMATION_ROOT = ROOT.parent
if str(AUTOMATION_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_ROOT))

from discord_webhook import post_discord_webhook
from blha.schedule import condition_started_at, current_season, job_active, load_schedule

CONFIG_PATH = ROOT / "health_config.yaml"
STATE_PATH = ROOT / "state" / "health.json"
AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png?v=3"
)

BAD_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}

SOURCE_ERROR_RE = re.compile(r"SOURCE ERROR \[([^\]]+)\]:\s*(.+)")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def load_config() -> dict[str, Any]:
    value = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError("health_config.yaml must contain a mapping")
    return value


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"active_issues": {}}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("active_issues"), dict):
            return value
    except Exception:
        pass
    return {"active_issues": {}}


def save_state(issues: dict[str, dict[str, Any]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"active_issues": issues}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "BLHA-Automation-Health/1.0",
    }


def api_get(session: requests.Session, api_base: str, path: str, **params: Any) -> Any:
    response = session.get(f"{api_base}{path}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def is_automatic_live_run(row: dict[str, Any]) -> bool:
    """True for production runs: GitHub cron runs or BLHA Scheduler live dispatches.

    The BLHA Scheduler starts workflows through workflow_dispatch with
    mode=live, and every BLHA workflow's run-name ends in "— <mode>". Manual
    preview/test/shadow runs are therefore excluded without reading logs.
    """
    if row.get("event") == "schedule":
        return True
    if row.get("event") != "workflow_dispatch":
        return False
    title = str(row.get("display_title") or "").strip()
    return title.endswith("— live")


def scheduled_runs(
    session: requests.Session,
    api_base: str,
    repository: str,
    workflow_file: str,
    *,
    per_page: int = 40,
) -> list[dict[str, Any]]:
    """Return recent production (automatic live) runs, newest first."""
    raw = api_get(
        session,
        api_base,
        f"/repos/{repository}/actions/workflows/{workflow_file}/runs",
        per_page=per_page,
    )
    rows = raw.get("workflow_runs", []) if isinstance(raw, dict) else []
    return [row for row in rows if isinstance(row, dict) and is_automatic_live_run(row)]


def download_run_log(
    session: requests.Session,
    api_base: str,
    repository: str,
    run_id: int,
) -> str:
    response = session.get(
        f"{api_base}/repos/{repository}/actions/runs/{run_id}/logs",
        timeout=45,
    )
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        chunks: list[str] = []
        for name in archive.namelist():
            if not name.lower().endswith(".txt"):
                continue
            chunks.append(archive.read(name).decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def issue(
    issue_id: str,
    workflow: str,
    summary: str,
    detail: str,
    url: str = "",
) -> tuple[str, dict[str, Any]]:
    return issue_id, {
        "workflow": workflow,
        "summary": summary,
        "detail": detail,
        "url": url,
    }


def inspect_wire_logs(
    session: requests.Session,
    api_base: str,
    repository: str,
    runs: list[dict[str, Any]],
    threshold: int,
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    completed = [r for r in runs if r.get("status") == "completed" and r.get("id")]
    if not completed:
        return found

    latest = completed[0]
    latest_url = str(latest.get("html_url") or "")
    try:
        latest_log = download_run_log(
            session,
            api_base,
            repository,
            int(latest["id"]),
        )
    except Exception as exc:
        key, value = issue(
            "wire-log-read",
            "BLHA Wire Engine",
            "Health monitor could not inspect the latest Wire log",
            str(exc),
            latest_url,
        )
        found[key] = value
        return found

    if "DELIVERY ERROR" in latest_log or "NOT POSTED" in latest_log:
        key, value = issue(
            "wire-delivery",
            "BLHA Wire Engine",
            "Discord delivery problem detected",
            "The latest Wire run logged DELIVERY ERROR or NOT POSTED.",
            latest_url,
        )
        found[key] = value

    if "RATE-GUARD SUPPRESSED" in latest_log:
        key, value = issue(
            "wire-rate-guard",
            "BLHA Wire Engine",
            "Wire roundup overflowed",
            "The latest Wire run had more overflow stories than fit in a roundup post, so some were not shown. Review the feed burst; a parser change can expose a large backlog.",
            latest_url,
        )
        found[key] = value

    recent = completed[: max(1, threshold)]
    if len(recent) < threshold:
        return found

    errors_per_run: list[dict[str, str]] = []
    for row in recent:
        try:
            text = download_run_log(session, api_base, repository, int(row["id"]))
        except Exception:
            errors_per_run.append({})
            continue
        errors: dict[str, str] = {}
        for match in SOURCE_ERROR_RE.finditer(text):
            errors[match.group(1).strip()] = match.group(2).strip()[:300]
        errors_per_run.append(errors)

    if not errors_per_run or any(not errors for errors in errors_per_run):
        return found

    persistent_sources = set(errors_per_run[0])
    for errors in errors_per_run[1:]:
        persistent_sources &= set(errors)

    for source in sorted(persistent_sources):
        detail = errors_per_run[0].get(source, "Repeated source fetch error")
        key, value = issue(
            f"wire-source:{source.lower()}",
            "BLHA Wire Engine",
            f"Persistent source failure: {source}",
            f"The source failed in {threshold} consecutive Wire runs. Latest error: {detail}",
            latest_url,
        )
        found[key] = value

    return found


def collect_issues(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    api_base = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repository:
        raise RuntimeError("GITHUB_REPOSITORY is missing")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing")

    session = requests.Session()
    session.headers.update(github_headers(token))
    current = now_utc()
    issues: dict[str, dict[str, Any]] = {}

    settings = cfg.get("settings") or {}
    source_threshold = int(settings.get("wire_persistent_source_runs") or 3)

    # Workflows the scheduler is not running in this part of the season
    # (for example the scoreboard in the offseason) are not expected to be fresh.
    phase, phase_text, phase_started = current_season(current)
    print(f"HEALTH season={phase_text}")
    try:
        jobs_by_file = {str(job["workflow"]): job for job in load_schedule()["jobs"]}
    except Exception as exc:
        print(f"HEALTH WARNING: could not read schedule.yaml: {exc}")
        jobs_by_file = {}

    for item in cfg.get("workflows") or []:
        if not isinstance(item, dict):
            continue
        workflow_id = str(item.get("id") or "workflow")
        name = str(item.get("name") or workflow_id)
        workflow_file = str(item.get("file") or "").strip()
        max_age = int(item.get("max_age_minutes") or 0)
        if not workflow_file or max_age <= 0:
            continue
        job = jobs_by_file.get(workflow_file, {})
        active, why = job_active(job, phase, current)
        if not active:
            print(f"HEALTH SKIP [{workflow_id}]: {why}")
            continue
        # A job that just switched on (new season phase, or a League Office
        # event window opening) gets max_age to complete its first run.
        if job.get("phases") and phase_started and (current - phase_started).total_seconds() < max_age * 60:
            print(f"HEALTH SKIP [{workflow_id}]: {phase} began recently; allowing first run")
            continue
        opened = condition_started_at(job, current) if job.get("when") else None
        if opened and (current - opened).total_seconds() < max_age * 60:
            print(f"HEALTH SKIP [{workflow_id}]: just became active; allowing first run")
            continue

        try:
            runs = scheduled_runs(session, api_base, repository, workflow_file)
        except Exception as exc:
            key, value = issue(
                f"api:{workflow_id}",
                name,
                "Could not read workflow status from GitHub",
                str(exc),
            )
            issues[key] = value
            continue

        if not runs:
            key, value = issue(
                f"no-run:{workflow_id}",
                name,
                "No live run found",
                f"GitHub returned no live run for {workflow_file}.",
            )
            issues[key] = value
            continue

        newest = runs[0]
        newest_time = parse_dt(str(newest.get("run_started_at") or newest.get("created_at") or ""))
        newest_url = str(newest.get("html_url") or "")
        if newest_time is None:
            key, value = issue(
                f"bad-time:{workflow_id}",
                name,
                "Latest live run has no usable timestamp",
                workflow_file,
                newest_url,
            )
            issues[key] = value
        else:
            age_minutes = int((current - newest_time).total_seconds() // 60)
            if age_minutes > max_age:
                key, value = issue(
                    f"stale:{workflow_id}",
                    name,
                    "Workflow appears stale",
                    f"Latest live run started {age_minutes} minutes ago; alert threshold is {max_age} minutes.",
                    newest_url,
                )
                issues[key] = value

        completed = [r for r in runs if r.get("status") == "completed"]
        if completed:
            last_completed = completed[0]
            conclusion = str(last_completed.get("conclusion") or "").lower()
            if conclusion in BAD_CONCLUSIONS:
                key, value = issue(
                    f"failed:{workflow_id}",
                    name,
                    f"Latest completed live run ended with {conclusion}",
                    "Open the workflow run and review the failed step/log output.",
                    str(last_completed.get("html_url") or ""),
                )
                issues[key] = value

        if bool(item.get("inspect_wire_logs")):
            issues.update(
                inspect_wire_logs(
                    session,
                    api_base,
                    repository,
                    runs,
                    source_threshold,
                )
            )

    connection = (session, repository, api_base)
    apply_startup_grace(cfg, issues, connection)
    apply_wire_rate_guard_confirmation(cfg, issues, connection)
    apply_wire_root_cause_suppression(issues)
    return issues



# --- Noise filters ------------------------------------------------------------
# Applied after the raw checks so one operational problem produces one alert.


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
    current = now_utc()

    for workflow_id, item in no_run_ids.items():
        workflow_file = str(item.get("file") or "").strip()
        if not workflow_file:
            continue
        try:
            metadata = api_get(
                session,
                api_base,
                f"/repos/{repository}/actions/workflows/{workflow_file}",
            )
            created_at = parse_dt(
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
        runs = scheduled_runs(
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
            log_text = download_run_log(
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


def field_for_issue(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("detail") or "Review the automation."
    url = str(data.get("url") or "")
    if url:
        value += f"\n[Open workflow run]({url})"
    return {
        "name": f"{data.get('workflow', 'Automation')} — {data.get('summary', 'Issue')}",
        "value": str(value)[:1024],
        "inline": False,
    }


def discord_payload(
    cfg: dict[str, Any],
    new_issues: dict[str, dict[str, Any]],
    recovered: dict[str, dict[str, Any]],
    *,
    test: bool = False,
) -> dict[str, Any]:
    settings = cfg.get("settings") or {}
    username = str(settings.get("username") or "BLHA Systems Desk")

    if test:
        title = "[TEST] BLHA Automation Health"
        description = (
            "Controlled webhook test for the private BLHA automation-health feed. "
            "No health state is changed by this test."
        )
        color = int(str(settings.get("test_color", "0xFFB81C")), 0)
        fields = [
            {
                "name": "Status",
                "value": "Webhook delivery is functioning.",
                "inline": False,
            }
        ]
    else:
        fields: list[dict[str, Any]] = []
        if new_issues:
            fields.append(
                {
                    "name": "NEW ISSUES",
                    "value": f"{len(new_issues)} automation health issue(s) require attention.",
                    "inline": False,
                }
            )
            fields.extend(field_for_issue(data) for data in new_issues.values())
        if recovered:
            names = "\n".join(
                f"• {data.get('workflow', 'Automation')} — {data.get('summary', 'Issue')}"
                for data in recovered.values()
            )
            fields.append(
                {
                    "name": "RECOVERED",
                    "value": names[:1024],
                    "inline": False,
                }
            )

        if new_issues:
            title = "BLHA Automation Alert"
            description = "The automation monitor detected a new production issue."
            color = int(str(settings.get("alert_color", "0xC73E3A")), 0)
        else:
            title = "BLHA Automation Recovery"
            description = "Previously reported automation issue(s) have cleared."
            color = int(str(settings.get("recovery_color", "0x2E7D32")), 0)

    return {
        "username": username,
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "fields": fields[:25],
                "color": color,
                "footer": {"text": "AUTOMATION HEALTH • COMMISSIONER OPERATIONS"},
                "timestamp": now_utc().isoformat(),
            }
        ],
    }


def deliver(cfg: dict[str, Any], body: dict[str, Any]) -> tuple[bool, str]:
    settings = cfg.get("settings") or {}
    secret_name = str(settings.get("webhook_secret") or "BLHA_WEBHOOK_AUTOMATION_HEALTH")
    return post_discord_webhook(secret_name, body)


def print_issues(issues: dict[str, dict[str, Any]]) -> None:
    if not issues:
        print("HEALTH: no current production issues detected")
        return
    print(f"HEALTH: {len(issues)} current issue(s)")
    for key, data in sorted(issues.items()):
        print(
            f"- {key}: {data.get('workflow')} — {data.get('summary')} :: "
            f"{data.get('detail')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"ERROR: could not load health config: {exc}")
        return 1

    if args.mode == "test":
        ok, detail = deliver(cfg, discord_payload(cfg, {}, {}, test=True))
        if not ok:
            print(f"DELIVERY ERROR: {detail}")
            return 1
        print("RESULT: automation-health test message delivered; state_updated=False")
        return 0

    try:
        current = collect_issues(cfg)
    except Exception as exc:
        print(f"ERROR: automation health collection failed: {exc}")
        return 1

    print_issues(current)
    if args.mode == "preview":
        print("RESULT: preview only; no Discord message sent and no state changed.")
        return 0

    state = load_state()
    previous = state.get("active_issues") or {}
    new_issues = {key: value for key, value in current.items() if key not in previous}
    recovered = {key: value for key, value in previous.items() if key not in current}

    if not new_issues and not recovered:
        print("RESULT: health state unchanged; 0 Discord messages sent.")
        return 0

    body = discord_payload(cfg, new_issues, recovered)
    ok, detail = deliver(cfg, body)
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    save_state(current)
    print(
        f"RESULT: automation-health message {detail}; "
        f"new={len(new_issues)} recovered={len(recovered)} state_updated=True"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
