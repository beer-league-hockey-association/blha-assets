"""The BLHA season calendar, derived entirely from Fantrax's own week dates.

Fantrax weeks do not end at midnight. Each week ends when the first NHL game
of the following Monday starts (for example Mon 6:59 PM), and the next week
begins at that moment. So by Monday morning every game of the outgoing week
has been played, even though Fantrax still lists the week as open until the
evening. ``final_at`` captures that: a week is treated as final from 6:00 AM
local time on the day it ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

PRESEASON = "preseason"
REGULAR = "regular"
PLAYOFFS = "playoffs"
OFFSEASON = "offseason"
PHASES = (PRESEASON, REGULAR, PLAYOFFS, OFFSEASON)

FINAL_HOUR = 6


@dataclass(frozen=True)
class Period:
    number: int
    start: datetime  # aware, UTC
    end: datetime    # aware, UTC

    def contains(self, now: datetime) -> bool:
        return self.start <= now <= self.end


def parse_dt(value: Any) -> datetime | None:
    """Parse Fantrax timestamps such as 2026-10-05T18:59:59.0-0400."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def periods(info: dict[str, Any]) -> list[Period]:
    result: list[Period] = []
    for row in info.get("scoringPeriods") or []:
        if not isinstance(row, dict):
            continue
        start, end = parse_dt(row.get("startDate")), parse_dt(row.get("endDate"))
        try:
            number = int(row.get("number"))
        except (TypeError, ValueError):
            continue
        if start and end:
            result.append(Period(number, start, end))
    result.sort(key=lambda p: p.number)
    return result


def period(info: dict[str, Any], number: int) -> Period | None:
    return next((p for p in periods(info) if p.number == number), None)


def playoff_settings(info: dict[str, Any]) -> tuple[int, int, int]:
    """Return (last_regular_week, first_playoff_week, playoff_team_count)."""
    cfg = info.get("playoffs") if isinstance(info.get("playoffs"), dict) else {}
    weeks = periods(info)
    last_week = weeks[-1].number if weeks else 0
    last_regular = int(cfg.get("lastRegularSeasonPeriod") or last_week)
    first_playoff = int(cfg.get("firstPlayoffPeriod") or last_regular + 1)
    teams = int(cfg.get("numPlayoffTeams") or 6)
    return last_regular, first_playoff, teams


def final_at(p: Period, tz: ZoneInfo) -> datetime:
    """When a week's games are all complete (6 AM local on its end day)."""
    local_end = p.end.astimezone(tz)
    morning = datetime.combine(local_end.date(), time(FINAL_HOUR), tzinfo=tz)
    return min(p.end, morning.astimezone(timezone.utc))


def is_final(p: Period, now: datetime, tz: ZoneInfo) -> bool:
    return now >= final_at(p, tz)


def active_period(info: dict[str, Any], now: datetime) -> Period | None:
    return next((p for p in periods(info) if p.contains(now)), None)


def latest_final(info: dict[str, Any], now: datetime, tz: ZoneInfo, *, through: int | None = None) -> Period | None:
    candidates = [p for p in periods(info) if is_final(p, now, tz) and (through is None or p.number <= through)]
    return candidates[-1] if candidates else None


def upcoming_period(info: dict[str, Any], now: datetime, tz: ZoneInfo) -> Period | None:
    """The week that is in progress or starts later today (local).

    A week whose games are all finished (see final_at) is skipped, so on
    Monday morning this returns the week that starts Monday evening.
    """
    today = now.astimezone(tz).date()
    for p in periods(info):
        if p.end <= now or is_final(p, now, tz):
            continue
        if p.start <= now or p.start.astimezone(tz).date() <= today:
            return p
        return None
    return None


def phase(info: dict[str, Any], now: datetime) -> str:
    weeks = periods(info)
    if not weeks:
        return OFFSEASON
    last_regular, _, _ = playoff_settings(info)
    for p in weeks:
        if now <= p.end:
            if now < p.start and p is weeks[0]:
                return PRESEASON
            return REGULAR if p.number <= last_regular else PLAYOFFS
    return OFFSEASON


def phase_started_at(info: dict[str, Any], now: datetime) -> datetime | None:
    """When the current phase began (None for preseason or unknown)."""
    weeks = periods(info)
    current = phase(info, now)
    if not weeks or current == PRESEASON:
        return None
    if current == OFFSEASON:
        return weeks[-1].end
    last_regular, first_playoff, _ = playoff_settings(info)
    target = weeks[0].number if current == REGULAR else first_playoff
    match = next((p for p in weeks if p.number == target), None)
    return match.start if match else None


def describe(info: dict[str, Any], now: datetime) -> str:
    current = active_period(info, now)
    week = f" week {current.number}" if current else ""
    return f"{phase(info, now)}{week}"
