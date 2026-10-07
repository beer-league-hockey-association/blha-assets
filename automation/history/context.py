"""LeagueHistory: the archive, history.yaml and league.yaml read together.

Lifetime records are kept per franchise, not per Fantrax team id: a team id
listed under a franchise's ``team_ids`` in history.yaml (or a team whose
Fantrax name matches a franchise name) belongs to that franchise, so records
survive a league renewal that hands out new team ids. Teams that are not in
history.yaml yet count under their own Fantrax team id and current name.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from blha.league import load_league
from history.records import Records
from history.store import Archive, parse_asset, parse_pick

ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def natural(text: str) -> list[Any]:
    """Sort key that puts "Test 2" before "Test 10"."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(text).lower())]


def initials(name: str) -> str:
    """Monogram letters: first letter of each word, whole numbers kept ("Test 10" -> "T10")."""
    words = [w for w in re.split(r"[\s-]+", name) if w[:1].isalnum()]
    return "".join(w if w.isdigit() else w[0] for w in words[:3]).upper()[:4] or "?"


def ordinal(n: int) -> str:
    return ORDINAL.get(n, f"{n}th")


def display_name(fantrax_name: str) -> str:
    """'McDavid, Connor' -> 'Connor McDavid'."""
    if fantrax_name.count(",") == 1:
        last, first = (part.strip() for part in fantrax_name.split(",", 1))
        return f"{first} {last}".strip()
    return fantrax_name


class LeagueHistory:
    def __init__(self, archive: Archive | Path | str | None = None, records: Records | None = None,
                 league: dict[str, Any] | None = None) -> None:
        self.archive = archive if isinstance(archive, Archive) else Archive(archive)
        self.records = records if records is not None else Records.load()
        if league is None:
            try:
                league = load_league()
            except Exception:
                league = {}
        self.league = league
        self.tz = ZoneInfo(str(league.get("timezone") or "America/New_York"))
        self.seasons = self.archive.seasons()
        self.team_names = self.archive.team_names()
        self.players = self.archive.players()
        self._events: list[dict[str, Any]] | None = None

    # --- franchises ---------------------------------------------------------------
    def franchise(self, team_id: str) -> str:
        """Franchise key for a Fantrax team id (the team id itself when not in history.yaml)."""
        team_id = str(team_id or "")
        return self.records.franchise_for(team_id, self.team_names.get(team_id)) or team_id

    def name(self, key: str) -> str:
        return self.records.name(key) or self.team_names.get(str(key)) or str(key or "Unknown team")

    def franchise_keys(self) -> list[str]:
        """Every franchise in history.yaml plus every archived team not mapped to one."""
        keys = list(self.records.franchises)
        extra = []
        for team_id in self.current_team_ids() or self.team_names:
            key = self.franchise(team_id)
            if key not in keys and key not in extra:
                extra.append(key)
        return keys + sorted(extra, key=lambda k: natural(self.name(k)))

    def current_team_ids(self) -> list[str]:
        latest = self.archive.latest_season()
        return list((self.archive.meta(latest).get("teams") or {}).keys()) if latest is not None else []

    def same(self, a: str, b: str) -> bool:
        return self.franchise(a) == self.franchise(b)

    # --- players and assets ---------------------------------------------------------
    def player_name(self, pid: str) -> str:
        row = self.players.get(str(pid)) or {}
        return display_name(str(row.get("name") or f"Player {pid}"))

    def player(self, pid: str) -> str:
        row = self.players.get(str(pid)) or {}
        bits = [b for b in (row.get("position"), row.get("team")) if b and b != "(N/A)"]
        return self.player_name(pid) + (f" ({', '.join(bits)})" if bits else "")

    def pick(self, key: str) -> str:
        parsed = parse_pick(key)
        if not parsed:
            return f"Pick {key}"
        year, rnd, original = parsed
        return f"{year} {ordinal(rnd)} round pick ({self.name(self.franchise(original))})"

    def asset(self, asset: str) -> str:
        kind, value = parse_asset(asset)
        return self.player(value) if kind == "player" else self.pick(value)

    # --- events ---------------------------------------------------------------------
    def events(self) -> list[dict[str, Any]]:
        if self._events is None:
            self._events = self.archive.events()
        return self._events

    def trades(self) -> list[dict[str, Any]]:
        return [e for e in self.events() if e.get("type") == "trade"]

    def date(self, iso: str | None) -> str:
        if not iso:
            return "unknown date"
        try:
            when = datetime.fromisoformat(str(iso))
        except ValueError:
            return str(iso)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        local = when.astimezone(self.tz)
        return f"{local.strftime('%b')} {local.day}, {local.year}"

    def event_date(self, event: dict[str, Any]) -> str:
        """Events are found by the daily run, so the date is when it was seen (it happened since the run before)."""
        if event.get("date"):
            try:
                d = datetime.fromisoformat(str(event["date"]))
                return f"{d.strftime('%b')} {d.day}, {d.year}"
            except ValueError:
                pass
        return self.date(event.get("at"))

    def describe(self, event: dict[str, Any]) -> str:
        kind = event.get("type")
        if kind == "trade":
            sides = "; ".join(
                f"{self.name(self.franchise(t))} received {', '.join(self.asset(a) for a in event['received'].get(t, [])) or 'nothing'}"
                for t in event.get("teams", []))
            note = " (one-sided: possibly a drop and a claim between two daily runs)" if event.get("one_sided") else ""
            return f"Trade: {sides}{note}"
        team = self.name(self.franchise(event.get("team", "")))
        player = self.player(event.get("player", ""))
        if kind == "add":
            return f"{team} added {player}"
        if kind == "drop":
            return f"{team} dropped {player}"
        if kind == "status":
            return f"{team} moved {player} from {event.get('from')} to {event.get('to')}"
        return f"{kind}: {event}"

    # --- rosters and drafts ---------------------------------------------------------
    def current_owner(self, pid: str) -> tuple[str, str] | None:
        """(franchise key, status) of a player on a roster in the latest counted season."""
        latest = self.archive.latest_season()
        if latest is None:
            return None
        for team_id, roster in self.archive.rosters(latest).items():
            if str(pid) in roster:
                return self.franchise(team_id), roster[str(pid)]
        return None

    def drafts(self) -> dict[int, dict[str, Any]]:
        """Saved drafts of counted seasons, keyed by the year each draft was held."""
        out = {}
        for season in self.seasons:
            d = self.archive.draft(season)
            if d:
                out[int(d.get("year") or season)] = {**d, "season": season}
        return out

    def pick_selection(self, key: str) -> dict[str, Any] | None:
        """The draft selection a pick (year|round|original) became, if that draft is saved."""
        parsed = parse_pick(key)
        if not parsed:
            return None
        year, rnd, original = parsed
        draft = self.drafts().get(year)
        if not draft:
            return None
        return slot_pick(draft, rnd, original)


def is_snake(draft: dict[str, Any]) -> bool:
    """True when round 2 runs in reverse order (startup snake); False for a linear annual draft."""
    order = [str(t) for t in draft.get("order") or []]
    second = [p for p in draft.get("picks") or [] if p.get("round") == 2]
    if len(order) < 2 or not second:
        return False
    by_slot = {int(p["in_round"]): str(p.get("team")) for p in second}
    linear = sum(by_slot.get(i + 1) == t for i, t in enumerate(order))
    reverse = sum(by_slot.get(i + 1) == t for i, t in enumerate(reversed(order)))
    return reverse > linear


def slot_pick(draft: dict[str, Any], rnd: int, original: str) -> dict[str, Any] | None:
    """The pick made with ``original``'s slot in round ``rnd``, using the round-1 draft order.

    Assumes Fantrax's draftOrder lists original owners (unverified for drafts
    with traded picks).
    """
    order = [str(t) for t in draft.get("order") or []]
    if original not in order:
        return None
    position = order.index(original) + 1
    if is_snake(draft) and rnd % 2 == 0:
        position = len(order) - position + 1
    for pick in draft.get("picks") or []:
        if pick.get("round") == rnd and pick.get("in_round") == position:
            return pick
    return None
