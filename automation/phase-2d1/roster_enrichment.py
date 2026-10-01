#!/usr/bin/env python3
"""Fantrax roster ownership enrichment for BLHA The Wire.

The public getTeamRosters endpoint returns rosterItems with Fantrax player IDs,
not player names. Resolve those IDs through getPlayerIds?sport=NHL, then attach
BLHA fantasy-team ownership to injury candidates by normalized player name.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

FANTRAX_BASE = "https://www.fantrax.com/fxea/general"


def normalize_player_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def player_name_index(payload: Any) -> dict[str, str]:
    """Return Fantrax player ID -> player name from getPlayerIds."""
    index: dict[str, str] = {}
    if not isinstance(payload, dict):
        return index

    for outer_id, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        player_id = str(raw.get("fantraxId") or raw.get("id") or outer_id or "").strip()
        name = str(raw.get("name") or raw.get("playerName") or "").strip()
        if player_id and name:
            index[player_id] = name
    return index


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
                or ""
            ).strip()
            player_name = str(
                row.get("name")
                or row.get("playerName")
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
            "User-Agent": "BLHA-Wire-Fantrax-Enrichment/1.1",
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
        player_count = len(players) if isinstance(players, dict) else 0
        print(
            "ROSTER ENRICHMENT WARNING: 0 rostered player names resolved "
            f"(rosters_type={roster_type}, player_id_records={player_count})"
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
