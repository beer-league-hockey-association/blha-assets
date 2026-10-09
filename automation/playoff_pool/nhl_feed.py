"""Read-only NHL API client for the Playoff Pool (api-web.nhle.com/v1).

Endpoints (from the public reference https://github.com/Zmalski/NHL-API-Reference):

  /playoff-bracket/{year}                    the bracket: round, series letter,
                                             top/bottom seed team and wins
  /club-stats/{team}/{season}/2              a club's regular-season skater and
                                             goalie totals
  /roster/{team}/current                     a club's current roster
  /schedule/{YYYY-MM-DD}                     seven days of games (gameType 3 =
                                             playoffs) plus the season's dates
  /gamecenter/{game-id}/boxscore             one game's player stats, including
                                             hits and blocked shots

The reference lists paths and parameters but not response fields. The fields
read here are the ones the NHL's public responses are known to use; they have
NOT been checked against a live response from this repository (the build
environment cannot reach the NHL API). Every parser is tolerant: a missing
field reads as empty or zero instead of failing. Tests use the synthetic
fixture automation/tests/fixtures/nhl_playoffs_synthetic.json.

Game logs (/player/{id}/game-log/{season}/3) are not used: they have no hits
or blocked shots, which BLHA scores.
"""

from __future__ import annotations

import time
from typing import Any, Callable

API = "https://api-web.nhle.com/v1"
USER_AGENT = "BLHA-Playoff-Pool/1.0 (+https://github.com/beer-league-hockey-association/blha-assets)"
MIN_GAP = 0.4  # seconds between requests; the NHL API answers 429 when hit too fast
ATTEMPTS = 4


def season_id(year: int) -> str:
    """The NHL season string for the playoffs of ``year``: 2027 -> "20262027"."""
    return f"{year - 1}{year}"


def bracket_url(year: int) -> str:
    return f"{API}/playoff-bracket/{year}"


def club_stats_url(team: str, season: str) -> str:
    return f"{API}/club-stats/{team}/{season}/2"


def roster_url(team: str) -> str:
    return f"{API}/roster/{team}/current"


def schedule_url(day: str) -> str:
    return f"{API}/schedule/{day}"


def boxscore_url(game_id: str | int) -> str:
    return f"{API}/gamecenter/{game_id}/boxscore"


class Feed:
    """``get(url)`` returns parsed JSON, or None for a 404. Tests pass their own ``get``."""

    def __init__(self, get: Callable[[str], Any] | None = None) -> None:
        self._get = get or self._http_get
        self._session: Any = None
        self._last = 0.0
        self.calls = 0

    def _http_get(self, url: str) -> Any:
        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = USER_AGENT
        last: Exception | None = None
        for attempt in range(ATTEMPTS):
            wait = MIN_GAP - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self._session.get(url, timeout=20)
                if response.status_code == 404:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    last = RuntimeError(f"HTTP {response.status_code}")
                    time.sleep(min(2 ** (attempt + 1), 20))
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # network error: retry, then report
                last = exc
                time.sleep(1)
        raise RuntimeError(f"NHL request failed: {url} ({last})")

    def get(self, url: str) -> Any:
        self.calls += 1
        return self._get(url)

    def bracket(self, year: int) -> Any:
        return self.get(bracket_url(year))

    def club_stats(self, team: str, season: str) -> Any:
        return self.get(club_stats_url(team, season))

    def roster(self, team: str) -> Any:
        return self.get(roster_url(team))

    def schedule(self, day: str) -> Any:
        return self.get(schedule_url(day))

    def boxscore(self, game_id: str | int) -> Any:
        return self.get(boxscore_url(game_id))


def text(value: Any) -> str:
    """NHL names come as plain strings or {"default": "..."}."""
    if isinstance(value, dict):
        value = value.get("default")
    return str(value or "").strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
