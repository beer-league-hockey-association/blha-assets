"""Load bot/config.yaml into typed settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .rules import Franchise, Settings

PICKEM_ROLES = ("owner", "co_owner")


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
    co_owner_role_id: int | None = None
    pickem_channel_id: int | None = None
    suggestions_forum_id: int | None = None
    scheduled_for_vote_tag_id: int | None = None
    pickem_players: tuple[str, ...] = PICKEM_ROLES
    problems: list[str] = field(default_factory=list)

    @property
    def member_role_ids(self) -> set[int]:
        """Franchise Owner and Co-Owner roles: who may use /myteam and /tradecheck."""
        return {r for r in (self.owner_role_id, self.co_owner_role_id) if r}

    @property
    def pickem_role_ids(self) -> set[int]:
        """Roles that play Pick'em (pickem.players in config.yaml)."""
        ids = {"owner": self.owner_role_id, "co_owner": self.co_owner_role_id}
        return {ids[k] for k in self.pickem_players if ids.get(k)}


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
        team_id = str(row.get("fantrax_team_id") or "").strip()
        if not team_id:
            problems.append(f"{name} has no fantrax_team_id yet, so /myteam and /tradecheck can't find its Fantrax team.")
        franchises.append(Franchise(name, role, bool(row.get("commissioner")), fantrax_team_id=team_id))
    if len({f.name for f in franchises}) != len(franchises):
        problems.append("Two franchises share a name.")
    if sum(f.commissioner for f in franchises) != 1:
        problems.append("Exactly one franchise must be marked commissioner: true.")
    team_ids = [f.fantrax_team_id for f in franchises if f.fantrax_team_id]
    if len(set(team_ids)) != len(team_ids):
        problems.append("Two franchises share a fantrax_team_id.")

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

    pickem = raw.get("pickem") or {}
    players = [str(p).strip() for p in (pickem.get("players") or PICKEM_ROLES)]
    for p in players:
        if p not in PICKEM_ROLES:
            problems.append(f"pickem.players has {p!r}; use owner and/or co_owner.")

    discord_ids = raw.get("discord") or {}
    for key, value in discord_ids.items():
        text = str(value or "").strip()
        if text and not text.isdigit():
            problems.append(f"discord.{key} must be a Discord ID (digits only, in quotes), not {text!r}.")
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
        co_owner_role_id=_id(discord_ids.get("co_owner_role_id")),
        pickem_channel_id=_id(discord_ids.get("pickem_channel_id")),
        suggestions_forum_id=_id(discord_ids.get("suggestions_forum_id")),
        scheduled_for_vote_tag_id=_id(discord_ids.get("scheduled_for_vote_tag_id")),
        pickem_players=tuple(p for p in players if p in PICKEM_ROLES),
        problems=problems,
    )
    for attr, key in (("guild_id", "guild_id"), ("voting_channel_id", "voting_channel_id"),
                      ("rulings_log_channel_id", "rulings_log_channel_id"),
                      ("commissioner_role_id", "commissioner_role_id"),
                      ("owner_role_id", "franchise_owner_role_id")):
        if getattr(cfg, attr) is None:
            problems.append(f"discord.{key} is not set.")
    if cfg.co_owner_role_id is None:
        problems.append("discord.co_owner_role_id is not set, so Co-Owners can't use /myteam, /tradecheck or Pick'em.")
    if cfg.pickem_channel_id is None:
        problems.append("discord.pickem_channel_id is not set, so Pick'em is off.")
    elif not cfg.pickem_role_ids:
        problems.append("Pick'em has no player roles: set the roles named in pickem.players.")
    if cfg.suggestions_forum_id is None:
        problems.append("discord.suggestions_forum_id is not set, so /proposal from-thread is off.")
        if cfg.scheduled_for_vote_tag_id is not None:
            problems.append("discord.scheduled_for_vote_tag_id needs discord.suggestions_forum_id too.")
    return cfg
