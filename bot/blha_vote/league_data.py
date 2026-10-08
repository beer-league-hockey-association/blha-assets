"""Cached, read-only data for the bot's league commands.

Every method here blocks (Fantrax, the NHL API, the League Ledger CSV, the
events file, the Playoff Pool boxes), so the Discord layer calls them with
``asyncio.to_thread``.
Results are cached for a few minutes (rosters, scores) up to half a day
(Fantrax's player list), so busy commands don't hammer Fantrax or the NHL.
Nothing here writes to Fantrax.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .shared import minors, picktrades

USER_AGENT = "BLHA-LeagueBot/1.0"

# Seconds each kind of data is reused before it is read again.
TTL = {
    "info": 30 * 60,        # league calendar and schedule rarely change
    "rosters": 5 * 60,
    "picks": 10 * 60,
    "players": 12 * 3600,   # getPlayerIds is large and changes slowly
    "scores": 3 * 60,
    "clearance": 10 * 60,
    "clearance_error": 60,
    "events": 60,
    "nhl_search": 6 * 3600,
    "pool_boxes": 10 * 60,  # boxes.json gains its deadline once the NHL publishes it
}


class TTLCache:
    """Thread-safe cache of loaded values, each kept for its own lifetime."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_entries: int = 500) -> None:
        self.clock = clock
        self.max_entries = max_entries
        self._data: dict[Any, tuple[float, float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any, ttl: float, load: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit and self.clock() - hit[0] < hit[1]:
                return hit[2]
        value = load()  # outside the lock: a slow load doesn't block other keys
        self.put(key, ttl, value)
        return value

    def put(self, key: Any, ttl: float, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max_entries:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (self.clock(), ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


@dataclass(frozen=True)
class Clearance:
    """The League Ledger's Pick Clearance tab: status is ok, unset or error."""
    status: str
    table: dict[str, dict[str, Any]] | None = None


class LeagueData:
    """Fantrax league data, the Pick Clearance CSV and the League Calendar, cached."""

    def __init__(self, client: Any = None, *, league_id: str | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 events_loader: Callable[[], dict[str, Any]] | None = None,
                 clearance_loader: Callable[[], Any] | None = None,
                 pool_loader: Callable[[], Any] | None = None) -> None:
        self._client = client
        self._league_id = league_id
        self.cache = TTLCache(clock)
        self._events_loader = events_loader
        self._clearance_loader = clearance_loader
        self._pool_loader = pool_loader
        self._client_lock = threading.Lock()

    @property
    def league_id(self) -> str:
        if self._league_id is None:
            from blha.league import load_league
            self._league_id = str(load_league()["league_id"])
        return self._league_id

    @property
    def client(self) -> Any:
        with self._client_lock:
            if self._client is None:
                from blha.fantrax import Fantrax
                self._client = Fantrax(self.league_id, user_agent=USER_AGENT)
            return self._client

    def league_info(self) -> dict[str, Any]:
        return self.cache.get("info", TTL["info"], self.client.league_info)

    def rosters(self) -> dict[str, Any]:
        """getTeamRosters for today (statuses ACTIVE, RESERVE, MINORS, IR)."""
        return self.cache.get("rosters", TTL["rosters"], self.client.rosters)

    def draft_picks(self) -> dict[str, Any]:
        return self.cache.get("picks", TTL["picks"], self.client.draft_picks)

    def player_ids(self) -> dict[str, Any]:
        return self.cache.get("players", TTL["players"], self.client.player_ids)

    def matchup_scores(self, period: int) -> list[dict[str, Any]]:
        return self.cache.get(("scores", period), TTL["scores"], lambda: self.client.matchup_scores(period))

    def events(self) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            if self._events_loader:
                return self._events_loader()
            from .deadlines import load as load_events
            return load_events()
        return self.cache.get("events", TTL["events"], load)

    def clearance(self) -> Clearance:
        """Paid-through Seasons from BLHA_LEDGER_CLEARANCE_CSV (picktrades.py's parser)."""
        pt = picktrades()
        if self._clearance_loader is None and not os.environ.get(pt.CLEARANCE_ENV, "").strip():
            return Clearance("unset")

        def load() -> Clearance:
            table = (self._clearance_loader or pt.load_clearance)()
            return Clearance("ok", table) if table is not None else Clearance("error")

        result = self.cache.get("clearance", TTL["clearance"], load)
        if result.status == "error":  # retry a failed read sooner
            self.cache.put("clearance", TTL["clearance_error"], result)
        return result

    def pool_boxes(self) -> Any:
        """The Playoff Pool boxes the automation posted (pool.load_boxes), or None before they exist.

        Read from the public automation-state branch (pool.boxes_url). A failed
        read raises and is not cached, so the next command tries again.
        """
        from . import pool

        def load() -> Any:
            if self._pool_loader is not None:
                raw = self._pool_loader()
            else:
                import requests

                response = requests.get(pool.boxes_url(), headers={"User-Agent": USER_AGENT}, timeout=15)
                if response.status_code == 404:
                    raw = None
                else:
                    response.raise_for_status()
                    raw = response.json()
            return pool.load_boxes(raw)

        return self.cache.get("pool_boxes", TTL["pool_boxes"], load)


class NHLLookup:
    """NHL player search and landing pages through minors.py's rate-limited client."""

    def __init__(self, session: Any = None, clock: Callable[[], float] = time.monotonic) -> None:
        import requests

        self.m = minors()
        self.session = session or requests.Session()
        if hasattr(self.session, "headers"):
            self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.cache = TTLCache(clock)
        self._lock = threading.Lock()  # minors._get's pacing is not thread-safe

    def _get(self, url: str, **params: Any) -> Any:
        with self._lock:
            return self.m._get(self.session, url, **params)

    def search(self, query: str) -> list[dict[str, Any]]:
        key = ("search", self.m.norm(query))
        return self.cache.get(key, TTL["nhl_search"],
                              lambda: self._get(self.m.SEARCH, culture="en-us", limit=20, q=query) or [])

    def landing(self, player_id: int) -> dict[str, Any]:
        """Bio and career totals, reused for minors.py's CACHE_HOURS like the nightly watch."""
        return self.cache.get(("landing", int(player_id)), self.m.CACHE_HOURS * 3600,
                              lambda: self._get(f"{self.m.NHL}/player/{int(player_id)}/landing") or {})
