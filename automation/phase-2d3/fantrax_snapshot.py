#!/usr/bin/env python3
"""BLHA Phase 2D.3A — inspect Fantrax league data shapes before Discord automation.

Read-only. Does not modify Fantrax, Discord, or repository state.
Prints enough structure and samples to design stable standings/roster/draft ingestion.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

BASE = "https://www.fantrax.com/fxea/general"


def get_json(session: requests.Session, league_id: str, endpoint: str) -> Any:
    response = session.get(
        f"{BASE}/{endpoint}", params={"leagueId": league_id}, timeout=25
    )
    response.raise_for_status()
    return response.json()


def keys_of(value: Any) -> list[str]:
    if isinstance(value, dict):
        return list(value.keys())
    return []


def compact(value: Any, max_chars: int = 1200) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def inspect_league_info(info: Any) -> None:
    print("\n=== LEAGUE INFO ===")
    print(f"top_level_type={type(info).__name__}")
    print(f"top_level_keys={keys_of(info)}")
    if isinstance(info, dict):
        for key in ("leagueName", "scoringSystem", "draftType", "endDate"):
            if key in info:
                print(f"{key}={info[key]!r}")
        team_info = info.get("teamInfo")
        print(f"teamInfo_type={type(team_info).__name__}")
        if isinstance(team_info, dict):
            print(f"teamInfo_keys={list(team_info.keys())[:20]}")
            if team_info:
                first_key = next(iter(team_info))
                print(f"teamInfo_sample_key={first_key!r}")
                print(f"teamInfo_sample={compact(team_info[first_key])}")
        elif isinstance(team_info, list):
            print(f"teamInfo_items={len(team_info)}")
            if team_info:
                print(f"teamInfo_sample_keys={keys_of(team_info[0])}")
                print(f"teamInfo_sample={compact(team_info[0])}")


def inspect_standings(standings: Any) -> None:
    print("\n=== STANDINGS ===")
    print(f"type={type(standings).__name__}")
    if isinstance(standings, list):
        print(f"items={len(standings)}")
        if standings:
            print(f"row_keys={keys_of(standings[0])}")
        for idx, row in enumerate(standings[:12], start=1):
            print(f"row_{idx}={compact(row, 900)}")
    else:
        print(f"keys={keys_of(standings)}")
        print(f"sample={compact(standings)}")


def inspect_rosters(rosters: Any) -> None:
    print("\n=== TEAM ROSTERS ===")
    print(f"type={type(rosters).__name__}")
    print(f"top_level_keys={keys_of(rosters)}")
    if not isinstance(rosters, dict):
        print(f"sample={compact(rosters)}")
        return

    if "period" in rosters:
        print(f"period={rosters['period']!r}")
    roster_block = rosters.get("rosters")
    print(f"rosters_type={type(roster_block).__name__}")

    if isinstance(roster_block, dict):
        print(f"team_count={len(roster_block)}")
        for team_key, players in list(roster_block.items())[:3]:
            print(f"team_key={team_key!r} players_type={type(players).__name__}")
            if isinstance(players, list):
                print(f"player_count={len(players)}")
                if players:
                    print(f"player_keys={keys_of(players[0])}")
                    print(f"player_sample={compact(players[0])}")
            else:
                print(f"team_roster_sample={compact(players)}")
    elif isinstance(roster_block, list):
        print(f"team_count={len(roster_block)}")
        if roster_block:
            print(f"team_roster_keys={keys_of(roster_block[0])}")
            print(f"team_roster_sample={compact(roster_block[0])}")


def inspect_draft_picks(picks: Any) -> None:
    print("\n=== DRAFT PICKS ===")
    print(f"type={type(picks).__name__}")
    print(f"top_level_keys={keys_of(picks)}")
    if isinstance(picks, dict):
        for key in ("futureDraftPicks", "currentDraftPicks"):
            block = picks.get(key)
            print(f"{key}_type={type(block).__name__}")
            if isinstance(block, list):
                print(f"{key}_items={len(block)}")
                if block:
                    print(f"{key}_sample_keys={keys_of(block[0])}")
                    print(f"{key}_sample={compact(block[0])}")
            elif isinstance(block, dict):
                print(f"{key}_keys={list(block.keys())[:20]}")
                if block:
                    first_key = next(iter(block))
                    print(f"{key}_sample_key={first_key!r}")
                    print(f"{key}_sample={compact(block[first_key])}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True)
    args = parser.parse_args()

    league_id = args.league_id.strip()
    if not league_id:
        print("ERROR: league ID is empty")
        return 1

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Fantrax-ReadOnly-Snapshot/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    print("BLHA FANTRAX SCHEMA SNAPSHOT")
    print(f"league_id={league_id}")
    print("read_only=true")

    try:
        info = get_json(session, league_id, "getLeagueInfo")
        standings = get_json(session, league_id, "getStandings")
        rosters = get_json(session, league_id, "getTeamRosters")
        picks = get_json(session, league_id, "getDraftPicks")
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    inspect_league_info(info)
    inspect_standings(standings)
    inspect_rosters(rosters)
    inspect_draft_picks(picks)

    print("\nRESULT: schema snapshot complete; no Fantrax data was modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
