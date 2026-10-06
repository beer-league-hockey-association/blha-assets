"""Load bot/config.yaml into typed settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .rules import Franchise, Settings


def _id(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


@dataclass
class BotConfig:
    guild_id: int | None
    voting_channel_id: int | None
    rulings_log_channel_id: int | None
    commissioner_role_id: int | None
    assistant_role_id: int | None
    owner_role_id: int | None
    franchises: list[Franchise]
    settings: Settings
    timezone: ZoneInfo
    publish_ballots: bool = True
    remind_hours: float = 24.0
    problems: list[str] = field(default_factory=list)


def _date(value: Any, tz: ZoneInfo) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        # A bare date means the end of that day, league time.
        if len(text) == 10:
            dt = dt.replace(hour=23, minute=59, second=59)
        dt = dt.replace(tzinfo=tz)
    return dt


def load(path: str | Path) -> BotConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    tz = ZoneInfo(str(raw.get("timezone") or "America/New_York"))
    problems: list[str] = []

    franchises = []
    for row in raw.get("franchises") or []:
        role = _id(row.get("role_id"))
        name = str(row.get("name") or "").strip()
        if not name:
            problems.append("A franchise has no name.")
            continue
        if role is None:
            problems.append(f"{name} has no role_id yet.")
            role = -len(franchises) - 1  # placeholder that no member can hold
        franchises.append(Franchise(name, role, bool(row.get("commissioner"))))
    if len({f.name for f in franchises}) != len(franchises):
        problems.append("Two franchises share a name.")
    if sum(f.commissioner for f in franchises) != 1:
        problems.append("Exactly one franchise must be marked commissioner: true.")

    deadlines = {}
    for season, value in (raw.get("dues_deadlines") or {}).items():
        dt = _date(value, tz)
        if dt:
            deadlines[int(season)] = dt

    votes = raw.get("votes") or {}
    settings = Settings(
        threshold=int(votes.get("threshold", 8)),
        notice_days=int(votes.get("notice_days", 7)),
        window_days=int(votes.get("window_days", 7)),
        amendment_votes_from=_date(votes.get("amendment_votes_from"), tz),
        dues_deadlines=deadlines,
    )
    discord_ids = raw.get("discord") or {}
    cfg = BotConfig(
        guild_id=_id(discord_ids.get("guild_id")),
        voting_channel_id=_id(discord_ids.get("voting_channel_id")),
        rulings_log_channel_id=_id(discord_ids.get("rulings_log_channel_id")),
        commissioner_role_id=_id(discord_ids.get("commissioner_role_id")),
        assistant_role_id=_id(discord_ids.get("assistant_commissioner_role_id")),
        owner_role_id=_id(discord_ids.get("franchise_owner_role_id")),
        franchises=franchises,
        settings=settings,
        timezone=tz,
        publish_ballots=bool(votes.get("publish_ballots", True)),
        remind_hours=float(votes.get("remind_hours_before_close", 24)),
        problems=problems,
    )
    for attr, key in (("guild_id", "guild_id"), ("voting_channel_id", "voting_channel_id"),
                      ("rulings_log_channel_id", "rulings_log_channel_id"),
                      ("commissioner_role_id", "commissioner_role_id"),
                      ("owner_role_id", "franchise_owner_role_id")):
        if getattr(cfg, attr) is None:
            problems.append(f"discord.{key} is not set.")
    return cfg
