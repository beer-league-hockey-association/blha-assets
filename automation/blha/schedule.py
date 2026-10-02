"""Shared reading of automation/scheduler/schedule.yaml.

Used by the scheduler (to decide what to start) and by the health monitor (to
know which workflows are expected to be running right now).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import season
from .fantrax import Fantrax
from .league import AUTOMATION_ROOT, load_league

SCHEDULE_PATH = AUTOMATION_ROOT / "scheduler" / "schedule.yaml"


def load_schedule(path: Path = SCHEDULE_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("jobs"), list) or not data["jobs"]:
        raise ValueError("schedule.yaml must define a non-empty jobs list")
    for job in data["jobs"]:
        for name in job.get("phases") or []:
            if name not in season.PHASES:
                raise ValueError(f"job {job.get('id')}: unknown phase {name!r}")
    return data


def current_season(now: datetime | None = None) -> tuple[str | None, str, datetime | None]:
    """Return (phase, description, phase_started_at).

    phase is None if Fantrax could not be read, in which case callers should
    not gate anything on the season.
    """
    now = now or datetime.now(timezone.utc)
    try:
        cfg = load_league()
        info = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Scheduler/2.0").league_info()
    except Exception as exc:  # network or config problem: do not gate on phase
        return None, f"unknown (could not read Fantrax: {exc})", None
    return season.phase(info, now), season.describe(info, now), season.phase_started_at(info, now)


def current_phase(now: datetime | None = None) -> tuple[str | None, str]:
    phase, text, _ = current_season(now)
    return phase, text


def job_active(job: dict[str, Any], phase: str | None) -> tuple[bool, str]:
    """Whether a job should run in the current season phase."""
    allowed = job.get("phases")
    if not allowed:
        return True, ""
    if phase is None:
        return True, "season phase unknown; running anyway"
    if phase in allowed:
        return True, ""
    return False, f"not active in {phase} (runs in {', '.join(allowed)})"
