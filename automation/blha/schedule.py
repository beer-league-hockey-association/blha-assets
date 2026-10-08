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
        if job.get("when") and job["when"] not in CONDITIONS:
            raise ValueError(f"job {job.get('id')}: unknown condition {job['when']!r}")
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


def _league_ops():
    import sys

    folder = AUTOMATION_ROOT / "league-office"
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    import league_ops  # noqa: PLC0415

    return league_ops


def league_office_window(now: datetime | None = None) -> datetime | None:
    """When the open League Office reminder window began (None if closed)."""
    ops = _league_ops()
    return ops.upcoming_window_start(ops.load_config(), now)


def draft_window(now: datetime | None = None) -> datetime | None:
    """When the Draft Center window opened (None if no draft is near).

    Opens a day before the earliest countdown post (30 days ahead by default)
    and closes a day after the draft finishes, using Fantrax's draft date.
    """
    from datetime import timedelta

    from . import draft as dr

    now = now or datetime.now(timezone.utc)
    cfg = load_league()
    dc = cfg.get("draft_center") or {}
    offsets = [str(o) for o in (dc.get("countdown") or ["30d"])]
    days = max((int(o[:-1]) for o in offsets if o.endswith("d")), default=30)
    info = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Scheduler/2.0").get("getDraftResults")
    draft = dr.parse_results(info)
    return dr.window_start(draft, now, timedelta(days=days + 1), timedelta(hours=float(dc.get("linger_hours") or 24)))


def nhl_playoffs_window(now: datetime | None = None) -> datetime | None:
    """When the NHL playoff window opened (None outside it); see blha/nhl_playoffs.py.

    Opens 5 days before the NHL regular season's last day and closes 2 days
    after the NHL's last scheduled playoff date.
    """
    from . import nhl_playoffs

    return nhl_playoffs.window_start(now)


# condition name -> (function returning when it became true or None, reason when off)
CONDITIONS = {
    "league-office-events": (league_office_window, "no enabled League Office event is coming up"),
    "draft-window": (draft_window, "no Fantrax draft within the next 31 days"),
    "nhl-playoffs": (nhl_playoffs_window, "outside the NHL playoff window"),
}


def condition_started_at(job: dict[str, Any], now: datetime | None = None) -> datetime | None:
    entry = CONDITIONS.get(str(job.get("when") or ""))
    if not entry:
        return None
    try:
        return entry[0](now)
    except Exception:
        return None


def job_active(job: dict[str, Any], phase: str | None, now: datetime | None = None) -> tuple[bool, str]:
    """Whether a job should run now (season phase and any extra condition)."""
    allowed = job.get("phases")
    if allowed and phase is not None and phase not in allowed:
        return False, f"not active in {phase} (runs in {', '.join(allowed)})"

    condition = job.get("when")
    if condition:
        check, reason = CONDITIONS.get(condition, (None, ""))
        if check is None:
            return True, f"unknown condition {condition!r}; running anyway"
        try:
            if check(now) is None:
                return False, reason
        except Exception as exc:
            return True, f"condition {condition!r} failed ({exc}); running anyway"

    if allowed and phase is None:
        return True, "season phase unknown; running anyway"
    return True, ""
