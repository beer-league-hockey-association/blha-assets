"""Read-only Fantrax client and normalizers shared by BLHA automations.

Uses Fantrax's public league endpoints. Nothing here writes to Fantrax.
"""

from __future__ import annotations

from typing import Any

import requests

BASE = "https://www.fantrax.com/fxea/general"


class FantraxError(RuntimeError):
    """Fantrax answered HTTP 200 but the body was an error object."""


def raise_if_error(endpoint: str, body: Any) -> Any:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        raise FantraxError(f"{endpoint}: {body['error']}")
    return body


class Fantrax:
    def __init__(self, league_id: str, *, user_agent: str = "BLHA-Automation/2.0", timeout: int = 30) -> None:
        self.league_id = league_id
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json,text/plain,*/*",
        })

    def get(self, endpoint: str, **params: Any) -> Any:
        query = {"leagueId": self.league_id, **params}
        response = self.session.get(f"{BASE}/{endpoint}", params=query, timeout=self.timeout)
        response.raise_for_status()
        return raise_if_error(endpoint, response.json())

    def league_info(self) -> dict[str, Any]:
        info = self.get("getLeagueInfo")
        if not isinstance(info, dict):
            raise ValueError("getLeagueInfo did not return an object")
        return info

    def standings(self) -> list[dict[str, Any]]:
        return normalize_standings(self.get("getStandings"))

    def matchup_scores(self, period: int) -> list[dict[str, Any]]:
        return normalize_scores(self.get("getMatchupScores", period=period))

    def rosters(self, period: int | None = None) -> dict[str, Any]:
        """Team rosters; with ``period`` returns that week's lineup and statuses."""
        raw = self.get("getTeamRosters", **({"period": period} if period is not None else {}))
        return raw if isinstance(raw, dict) else {}

    def draft_picks(self) -> Any:
        """Current and future draft pick ownership (read-only)."""
        return self.get("getDraftPicks")

    def draft_results(self) -> Any:
        """Draft results. Endpoint shape is unverified; see tools/fantrax_probe.py."""
        return self.get("getDraftResults")

    def adp(self, **filters: Any) -> Any:
        """Average draft position data."""
        return self.get("getAdp", **filters)

    def player_ids(self) -> dict[str, Any]:
        response = self.session.get(f"{BASE}/getPlayerIds", params={"sport": "NHL"}, timeout=self.timeout)
        response.raise_for_status()
        raw = response.json()
        return raw if isinstance(raw, dict) else {}


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def parse_record(value: Any) -> tuple[int, int, int]:
    parts = str(value or "0-0-0").strip().split("-")
    if len(parts) != 3:
        return 0, 0, 0
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return 0, 0, 0


def normalize_standings(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("getStandings did not return a list")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            continue
        try:
            rank = int(row.get("rank") or 0)
        except (TypeError, ValueError):
            rank = 0
        record = str(row.get("points") or "0-0-0")
        wins, losses, ties = parse_record(record)
        rows.append({
            "rank": rank,
            "teamId": str(row.get("teamId") or ""),
            "teamName": str(row.get("teamName") or "Unknown Team"),
            "record": record,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "pointsFor": _float(row.get("totalPointsFor")),
            "gamesBack": _float(row.get("gamesBack")),
            "winPercentage": _float(row.get("winPercentage")),
        })
    rows.sort(key=lambda r: (r["rank"] if r["rank"] > 0 else 999, r["teamName"].lower()))
    for index, row in enumerate(rows, start=1):
        row["rank"] = row["rank"] or index
    return rows


def games_counted(rows: list[dict[str, Any]]) -> int | None:
    """Matchups reflected in Fantrax standings (fewest W+L+T across teams).

    In head-to-head every team plays once per week, so this equals the number
    of weeks Fantrax has finished processing.
    """
    if not rows:
        return None
    return min(row["wins"] + row["losses"] + row["ties"] for row in rows)


def normalize_scores(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("getMatchupScores did not return an object")
    if isinstance(raw.get("pageError"), dict):
        raise RuntimeError(f"getMatchupScores pageError: {raw['pageError']}")
    matchups = raw.get("matchups")
    if not isinstance(matchups, list):
        return []

    def team(value: Any) -> dict[str, Any]:
        value = value if isinstance(value, dict) else {}
        return {
            "teamId": str(value.get("teamId") or ""),
            "teamName": str(value.get("teamName") or "Unknown Team"),
            "score": _float(value.get("score")),
            "gamesPlayed": _float(value.get("gamesPlayed")),
        }

    return [
        {"away": team(m.get("away")), "home": team(m.get("home"))}
        for m in matchups
        if isinstance(m, dict)
    ]


def schedule_for(info: dict[str, Any], period: int) -> list[dict[str, Any]]:
    """Matchup pairings for a week from getLeagueInfo's season schedule."""
    for block in info.get("matchups") or []:
        if not isinstance(block, dict) or int(block.get("period") or 0) != period:
            continue
        pairs = []
        for row in block.get("matchupList") or []:
            if not isinstance(row, dict):
                continue
            away = row.get("away") or {}
            home = row.get("home") or {}
            pairs.append({
                "away": {"teamId": str(away.get("id") or ""), "teamName": str(away.get("name") or "TBD")},
                "home": {"teamId": str(home.get("id") or ""), "teamName": str(home.get("name") or "TBD")},
            })
        return pairs
    return []
