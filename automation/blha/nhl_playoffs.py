"""The NHL playoff window: the scheduler condition ``when: nhl-playoffs``.

The BLHA Playoff Pool (automation/playoff_pool/) runs only around the NHL
playoffs, which fall in the BLHA Offseason, so the Fantrax season phases can't
gate it. The window is read from the NHL's own season dates instead:

  opens   OPENS_BEFORE days before the NHL regular season's last day (local
          midnight), so the pool can post its boxes as soon as the playoff
          field is set and owners have until the first puck drop to pick
  closes  LINGER days after the NHL's last scheduled playoff date (the latest
          possible Stanley Cup Final game), so the morning after the Final
          the pool can post its result

Source: ``GET https://api-web.nhle.com/v1/schedule/{YYYY-MM-DD}``. Besides
``gameWeek`` (read by blha/nhl.py), the response carries the season's dates
as top-level ``regularSeasonEndDate`` and ``playoffEndDate`` (YYYY-MM-DD).

UNVERIFIED: those two field names are the NHL's publicly seen ones; they have
not been checked against a live response from this repository (the build
environment cannot reach the NHL API). If they are missing the window can't
be worked out and ``window_start`` raises, so the scheduler runs the job
anyway rather than silently skipping it (blha/schedule.py job_active), and the
job itself does nothing until the playoff field is set.

Outside CALENDAR (late March to late July) no NHL request is made at all.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

SCHEDULE_URL = "https://api-web.nhle.com/v1/schedule/{date}"
OPENS_BEFORE = timedelta(days=5)
LINGER = timedelta(days=2)
CALENDAR = ((3, 20), (7, 20))  # (month, day) bounds; the NHL playoffs always fall inside
DEFAULT_TZ = "America/New_York"


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def in_calendar(day: date) -> bool:
    (m1, d1), (m2, d2) = CALENDAR
    return date(day.year, m1, d1) <= day <= date(day.year, m2, d2)


def season_dates(raw: Any) -> tuple[date | None, date | None]:
    """(regularSeasonEndDate, playoffEndDate) from a schedule response."""
    if not isinstance(raw, dict):
        return None, None
    return _date(raw.get("regularSeasonEndDate")), _date(raw.get("playoffEndDate"))


def window(raw: Any, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    """(opens, closes) in UTC for the season in ``raw``, or None if its dates are missing."""
    regular_end, playoff_end = season_dates(raw)
    if regular_end is None or playoff_end is None or playoff_end < regular_end:
        return None
    opens = datetime.combine(regular_end - OPENS_BEFORE, time(0), tzinfo=tz)
    closes = datetime.combine(playoff_end + LINGER, time(0), tzinfo=tz) + timedelta(days=1)
    return opens.astimezone(timezone.utc), closes.astimezone(timezone.utc)


def http_get_json(url: str) -> Any:
    import requests

    response = requests.get(url, headers={"User-Agent": "BLHA-Scheduler/2.0"}, timeout=20)
    response.raise_for_status()
    return response.json()


def _league_tz() -> ZoneInfo:
    try:
        from .league import load_league, timezone_of

        return timezone_of(load_league())
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def window_start(
    now: datetime | None = None,
    tz: ZoneInfo | None = None,
    get: Callable[[str], Any] | None = None,
) -> datetime | None:
    """When the current NHL playoff window opened, or None outside it.

    Raises ValueError when the NHL schedule has no season dates (see above).
    """
    now = now or datetime.now(timezone.utc)
    tz = tz or _league_tz()
    today = now.astimezone(tz).date()
    if not in_calendar(today):
        return None
    raw = (get or http_get_json)(SCHEDULE_URL.format(date=today.isoformat()))
    found = window(raw, tz)
    if found is None:
        raise ValueError("the NHL schedule has no regularSeasonEndDate/playoffEndDate")
    opens, closes = found
    return opens if opens <= now < closes else None
