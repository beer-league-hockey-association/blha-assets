"""/deadlines: the next dates on the League Calendar (automation/league-office/events.yaml).

Events are read the way the League Office automation reads them
(league_ops.parse_event_time): only events with ``enabled: true`` and a
``starts_at`` count, and times without an offset are New York wall-clock
time. Private Commissioner Desk reminders are never shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import embeds as E
from .shared import league_ops

PRIVATE_CHANNELS = {"commissioner-desk"}
NOT_PUBLISHED = "The League Calendar hasn't been published yet."
FOOTER = "BLHA LEAGUE OFFICE • LEAGUE CALENDAR"


@dataclass(frozen=True)
class Deadline:
    id: str
    title: str
    at: datetime
    description: str = ""


def load() -> dict[str, Any]:
    """events.yaml (blocking file read; call from a thread)."""
    return league_ops().load_config()


def events(config: dict[str, Any], *, include_private: bool = False) -> list[Deadline]:
    """Every enabled, dated event, soonest first."""
    settings = config.get("settings") or {}
    tz = ZoneInfo(settings.get("timezone", "America/New_York"))
    default_channel = settings.get("default_channel", "league-calendar")
    out = []
    for event in config.get("events") or []:
        if not isinstance(event, dict) or not event.get("enabled"):
            continue
        if not include_private and event.get("channel", default_channel) in PRIVATE_CHANNELS:
            continue
        try:
            at = league_ops().parse_event_time(event.get("starts_at"), tz)
        except (TypeError, ValueError):
            continue  # a broken date is reported by the League Office run, not here
        if at is None:
            continue
        out.append(Deadline(str(event.get("id") or ""), str(event.get("title") or "League date"), at,
                            str(event.get("description") or "").strip()))
    out.sort(key=lambda d: d.at)
    return out


def upcoming(config: dict[str, Any], now: datetime, limit: int = 3) -> list[Deadline]:
    return [d for d in events(config) if d.at > now][:limit]


def event_time(config: dict[str, Any], event_id: str) -> datetime | None:
    """A dated event's time whether or not it is enabled (e.g. when trading reopens)."""
    settings = config.get("settings") or {}
    tz = ZoneInfo(settings.get("timezone", "America/New_York"))
    for event in config.get("events") or []:
        if isinstance(event, dict) and event.get("id") == event_id:
            try:
                return league_ops().parse_event_time(event.get("starts_at"), tz)
            except (TypeError, ValueError):
                return None
    return None


def lines(found: list[Deadline]) -> str:
    """Compact list for other embeds (e.g. /myteam)."""
    if not found:
        return NOT_PUBLISHED
    return "\n".join(f"**{d.title}** — {E.when(d.at)}" for d in found)


def embed(found: list[Deadline]) -> dict[str, Any]:
    if not found:
        return E.card("UPCOMING DEADLINES", NOT_PUBLISHED + " Dates are set by formula in Article V and published "
                      "on the League Calendar each Season (5.5).", [], FOOTER)
    fields = []
    for d in found:
        value = E.when(d.at)
        if d.description:
            value += f"\n{d.description}"
        fields.append((d.title.upper(), value))
    lead = f"The next {len(found)} League Calendar dates." if len(found) > 1 else "The next League Calendar date."
    return E.card("UPCOMING DEADLINES", lead + " Times show in your own time zone.", fields, FOOTER)
