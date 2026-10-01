#!/usr/bin/env python3
"""Fantrax roster ownership enrichment for BLHA The Wire.

The public getTeamRosters endpoint returns rosterItems with Fantrax player IDs,
not player names. Resolve those IDs through getPlayerIds?sport=NHL, then attach
BLHA fantasy-team ownership to injury candidates by normalized player name.

Fantrax's getPlayerIds wire shape is slightly unusual: the root object itself is
commonly keyed by the ID used by rosterItems, while each value may also contain
a separate ``fantraxId``. Keep every available ID as an alias for the same
player name so roster joins do not depend on one undocumented ID flavor.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

FANTRAX_BASE = "https://www.fantrax.com/fxea/general"


def normalize_player_name(value: str) -> str:
    raw = str(value or "").strip()

    # getPlayerIds commonly returns "Last, First" while injury sources use
    # "First Last". Normalize the display order before stripping punctuation.
    if raw.count(",") == 1:
        last, first = (part.strip() for part in raw.split(",", 1))
        if last and first:
            raw = f"{first} {last}"

    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _player_container(payload: Any) -> Any:
    """Return the actual player collection from known getPlayerIds shapes."""
    if not isinstance(payload, dict):
        return payload

    if "playerIds" in payload:
        return payload["playerIds"]
    if "players" in payload:
        return payload["players"]
    data = payload.get("data")
    if isinstance(data, dict):
        if "playerIds" in data:
            return data["playerIds"]
        if "players" in data:
            return data["players"]
    return payload


def _roster_container(payload: Any) -> Any:
    """Return the team-roster collection from known getTeamRosters shapes."""
    if not isinstance(payload, dict):
        return None
    if "rosters" in payload:
        return payload["rosters"]
    if "teams" in payload:
        return payload["teams"]
    data = payload.get("data")
    if isinstance(data, dict):
        if "rosters" in data:
            return data["rosters"]
        if "teams" in data:
            return data["teams"]
    return None


def _iter_roster_teams(payload: Any):
    """Yield (team_id, team_object) for object- or array-shaped roster data."""
    roster_block = _roster_container(payload)
    if isinstance(roster_block, dict):
        yield from roster_block.items()
    elif isinstance(roster_block, list):
        for raw_team in roster_block:
            if not isinstance(raw_team, dict):
                continue
            team_id = str(
                raw_team.get("teamId")
                or raw_team.get("team_id")
                or raw_team.get("id")
                or ""
            ).strip()
            yield team_id, raw_team


def player_name_index(payload: Any) -> dict[str, str]:
    """Return every known Fantrax player-ID alias -> player name."""
    index: dict[str, str] = {}
    players = _player_container(payload)

    if isinstance(players, list):
        iterable = [("", raw) for raw in players]
    elif isinstance(players, dict):
        iterable = list(players.items())
    else:
        return index

    for outer_id, raw in iterable:
        # Older/alternate shape: {playerId: "Player Name"}.
        if isinstance(raw, str):
            if str(outer_id).strip() and raw.strip():
                index[str(outer_id).strip()] = raw.strip()
            continue
        if not isinstance(raw, dict):
            continue

        name = str(
            raw.get("name")
            or raw.get("playerName")
            or raw.get("fullName")
            or ""
        ).strip()
        if not name:
            continue

        aliases = {
            str(outer_id or "").strip(),
            str(raw.get("fantraxId") or "").strip(),
            str(raw.get("id") or "").strip(),
            str(raw.get("playerId") or "").strip(),
            str(raw.get("player_id") or "").strip(),
        }
        for alias in aliases:
            if alias:
                index[alias] = name

    return index


def _team_items(raw_team: Any) -> list:
    if not isinstance(raw_team, dict):
        return []
    items = raw_team.get("rosterItems")
    if isinstance(items, list):
        return items
    for key in ("players", "roster", "rows"):
        candidate = raw_team.get(key)
        if isinstance(candidate, list):
            return candidate
    return []


def _roster_player_ids(rosters: Any) -> set[str]:
    ids: set[str] = set()
    for _team_id, raw_team in _iter_roster_teams(rosters):
        for row in _team_items(raw_team):
            if not isinstance(row, dict):
                continue
            player_id = str(
                row.get("id")
                or row.get("fantraxId")
                or row.get("playerId")
                or row.get("player_id")
                or ""
            ).strip()
            if player_id:
                ids.add(player_id)
    return ids


def ownership_from_payloads(rosters: Any, players: Any) -> dict[str, str]:
    """Build normalized player name -> BLHA team name from Fantrax payloads."""
    names_by_id = player_name_index(players)
    ownership: dict[str, str] = {}

    for team_id, raw_team in _iter_roster_teams(rosters):
        if not isinstance(raw_team, dict):
            continue
        owner = str(
            raw_team.get("teamName")
            or raw_team.get("team_name")
            or raw_team.get("name")
            or team_id
            or ""
        ).strip()
        if not owner:
            continue

        for row in _team_items(raw_team):
            if not isinstance(row, dict):
                continue
            player_id = str(
                row.get("id")
                or row.get("fantraxId")
                or row.get("playerId")
                or row.get("player_id")
                or ""
            ).strip()
            player_name = str(
                row.get("name")
                or row.get("playerName")
                or row.get("fullName")
                or names_by_id.get(player_id, "")
            ).strip()
            key = normalize_player_name(player_name)
            if key:
                ownership[key] = owner

    return ownership


def fantrax_ownership(league_id: str, period: str = "current") -> dict[str, str]:
    if not league_id:
        return {}

    period = str(period or "current").strip() or "current"

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Wire-Fantrax-Enrichment/1.3",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    try:
        # Fantrax expects a scoring period for getTeamRosters. "current" keeps
        # this automatic as the NHL season advances instead of hard-coding 1.
        roster_response = session.get(
            f"{FANTRAX_BASE}/getTeamRosters",
            params={"leagueId": league_id, "period": period},
            timeout=20,
        )
        roster_response.raise_for_status()
        rosters = roster_response.json()

        player_response = session.get(
            f"{FANTRAX_BASE}/getPlayerIds",
            params={"sport": "NHL"},
            timeout=20,
        )
        player_response.raise_for_status()
        players = player_response.json()
    except Exception as exc:
        print(f"ROSTER ENRICHMENT WARNING: Fantrax read failed: {exc}")
        return {}

    ownership = ownership_from_payloads(rosters, players)
    if not ownership:
        roster_block = _roster_container(rosters)
        roster_type = type(roster_block).__name__
        roster_teams = len(roster_block) if isinstance(roster_block, (dict, list)) else 0
        roster_ids = _roster_player_ids(rosters)
        player_index = player_name_index(players)
        overlap = len(roster_ids.intersection(player_index))
        player_container = _player_container(players)
        raw_player_count = len(player_container) if isinstance(player_container, (dict, list)) else 0
        print(
            "ROSTER ENRICHMENT WARNING: 0 rostered player names resolved "
            f"(period={period}, rosters_type={roster_type}, roster_teams={roster_teams}, "
            f"roster_ids={len(roster_ids)}, player_records={raw_player_count}, "
            f"player_id_aliases={len(player_index)}, id_overlap={overlap})"
        )
        return {}

    print(
        f"ROSTER ENRICHMENT: loaded {len(ownership)} rostered player names "
        f"for period={period}"
    )
    return ownership


def enrich_injury_ownership(candidates: list[dict], config: dict) -> None:
    fantrax_cfg = config.get("fantrax") if isinstance(config.get("fantrax"), dict) else {}
    if not fantrax_cfg.get("roster_enrichment", False):
        return

    injuries = [
        candidate
        for candidate in candidates
        if candidate.get("channel") == "injury-report" and candidate.get("player")
    ]
    if not injuries:
        return

    ownership = fantrax_ownership(
        str(fantrax_cfg.get("league_id") or "").strip(),
        str(fantrax_cfg.get("period") or "current").strip(),
    )
    if not ownership:
        return

    matched = 0
    for candidate in injuries:
        owner = ownership.get(normalize_player_name(candidate.get("player", "")), "")
        if owner:
            candidate["fantasy_owner"] = owner
            matched += 1

    print(f"ROSTER ENRICHMENT: matched {matched}/{len(injuries)} injury items to BLHA rosters")
