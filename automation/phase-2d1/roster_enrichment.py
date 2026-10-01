#!/usr/bin/env python3
"""Fantrax roster ownership enrichment for BLHA The Wire.

The public getTeamRosters endpoint returns rosterItems with Fantrax player IDs,
not player names. Resolve those IDs through getPlayerIds?sport=NHL, then attach
BLHA fantasy-team ownership to injury candidates by normalized player name.

Fantrax's getPlayerIds wire shape is slightly unusual: the root object itself is
commonly keyed by the ID used by rosterItems, while each value may also contain
a separate ``fantraxId``.  Keep every available ID as an alias for the same
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


def _roster_player_ids(rosters: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(rosters, dict):
        return ids
    roster_block = rosters.get("rosters")
    if not isinstance(roster_block, dict):
        return ids
    for raw_team in roster_block.values():
        if not isinstance(raw_team, dict):
            continue
        items = raw_team.get("rosterItems")
        if not isinstance(items, list):
            for key in ("players", "roster", "rows"):
                candidate = raw_team.get(key)
                if isinstance(candidate, list):
                    items = candidate
                    break
        if not isinstance(items, list):
            continue
        for row in items:
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
    if not isinstance(rosters, dict):
        return {}
    roster_block = rosters.get("rosters")
    if not isinstance(roster_block, dict):
        return {}

    names_by_id = player_name_index(players)
    ownership: dict[str, str] = {}

    for team_id, raw_team in roster_block.items():
        if not isinstance(raw_team, dict):
            continue
        owner = str(
            raw_team.get("teamName")
            or raw_team.get("name")
            or team_id
            or ""
        ).strip()
        if not owner:
            continue

        items = raw_team.get("rosterItems")
        if not isinstance(items, list):
            # Tolerate older/alternate payload shapes without making them the
            # primary assumption.
            for key in ("players", "roster", "rows"):
                candidate = raw_team.get(key)
                if isinstance(candidate, list):
                    items = candidate
                    break
        if not isinstance(items, list):
            continue

        for row in items:
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


def fantrax_ownership(league_id: str) -> dict[str, str]:
    if not league_id:
        return {}

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Wire-Fantrax-Enrichment/1.2",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    try:
        roster_response = session.get(
            f"{FANTRAX_BASE}/getTeamRosters",
            params={"leagueId": league_id},
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
        roster_type = type(rosters.get("rosters") if isinstance(rosters, dict) else None).__name__
        roster_ids = _roster_player_ids(rosters)
        player_index = player_name_index(players)
        overlap = len(roster_ids.intersection(player_index))
        raw_player_count = len(_player_container(players)) if isinstance(_player_container(players), (dict, list)) else 0
        print(
            "ROSTER ENRICHMENT WARNING: 0 rostered player names resolved "
            f"(rosters_type={roster_type}, roster_ids={len(roster_ids)}, "
            f"player_records={raw_player_count}, player_id_aliases={len(player_index)}, "
            f"id_overlap={overlap})"
        )
        return {}

    print(f"ROSTER ENRICHMENT: loaded {len(ownership)} rostered player names")
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

    ownership = fantrax_ownership(str(fantrax_cfg.get("league_id") or "").strip())
    if not ownership:
        return

    matched = 0
    for candidate in injuries:
        owner = ownership.get(normalize_player_name(candidate.get("player", "")), "")
        if owner:
            candidate["fantasy_owner"] = owner
            matched += 1

    print(f"ROSTER ENRICHMENT: matched {matched}/{len(injuries)} injury items to BLHA rosters")
