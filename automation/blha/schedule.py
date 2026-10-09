"""Shared reading of automation/scheduler/schedule.yaml.

Used by the scheduler (to decide what to start) and by the health monitor (to
know which workflows are expected to be running right now).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from . import season
from .fantrax import Fantrax
from .league import AUTOMATION_ROOT, load_league, timezone_of

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
        faster = job.get("faster")
        if faster is not None:
            if not job.get("every_minutes"):
                raise ValueError(f"job {job.get('id')}: faster needs every_minutes on the job")
            if not isinstance(faster, dict) or faster.get("when") not in CONDITIONS:
                raise ValueError(f"job {job.get('id')}: faster needs a known 'when' condition")
            if not 0 < int(faster.get("every_minutes") or 0) < int(job["every_minutes"]):
                raise ValueError(f"job {job.get('id')}: faster every_minutes must be shorter than the job's")
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


DEADLINE_DAY_LINGER = timedelta(hours=1)


def deadline_day_window(deadline: datetime | None, now: datetime, tz: Any) -> datetime | None:
    """Midnight (local) of trade-deadline day while that day's window is open, else None.

    The window runs from 00:00 on deadline day until an hour after the
    deadline, so the Trade Desk's last edit (the final tally) also runs at the
    faster pace.
    """
    if deadline is None:
        return None
    day = deadline.astimezone(tz).date()
    opened = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    return opened if opened <= now <= deadline + DEADLINE_DAY_LINGER else None


def trade_deadline_day(now: datetime | None = None) -> datetime | None:
    """When trade-deadline day began (None on any other day). Deadline from season.trade_deadline."""
    now = now or datetime.now(timezone.utc)
    cfg = load_league()
    tz = timezone_of(cfg)
    info = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Scheduler/2.0").league_info()
    return deadline_day_window(season.trade_deadline(info, tz), now, tz)


# condition name -> (function returning when it became true or None, reason when off)
CONDITIONS = {
    "league-office-events": (league_office_window, "no enabled League Office event is coming up"),
    "draft-window": (draft_window, "no Fantrax draft within the next 31 days"),
    "trade-deadline-day": (trade_deadline_day, "not trade-deadline day"),
}


def paced(job: dict[str, Any], now: datetime | None = None) -> tuple[dict[str, Any], str]:
    """The job with its faster interval while its ``faster.when`` condition holds.

    For example the Trade Desk runs every 30 minutes, and every 15 on
    trade-deadline day. If the condition can't be checked (Fantrax down), the
    normal interval is used.
    """
    faster = job.get("faster")
    if not isinstance(faster, dict):
        return job, ""
    check, _ = CONDITIONS.get(str(faster.get("when")), (None, ""))
    if check is None:
        return job, ""
    try:
        on = check(now) is not None
    except Exception as exc:
        return job, f"could not check {faster.get('when')} ({exc}); normal pace"
    if not on:
        return job, ""
    return {**job, "every_minutes": int(faster["every_minutes"])}, f"{faster.get('when')}: every {faster['every_minutes']} minutes"


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
