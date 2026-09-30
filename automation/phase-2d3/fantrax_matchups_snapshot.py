#!/usr/bin/env python3
"""BLHA Phase 2D.3C — inspect Fantrax matchup/schedule data shape.

Read-only. Does not modify Fantrax, Discord, or repository state.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

BASE = "https://www.fantrax.com/fxea/general"


def compact(value: Any, max_chars: int = 2200) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def keys_of(value: Any) -> list[str]:
    return list(value.keys()) if isinstance(value, dict) else []


def get_info(league_id: str) -> dict:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "BLHA-Fantrax-Matchup-Snapshot/1.0",
        "Accept": "application/json,text/plain,*/*",
    })
    response = s.get(f"{BASE}/getLeagueInfo", params={"leagueId": league_id}, timeout=25)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("getLeagueInfo did not return a dict")
    return data


def describe_block(name: str, block: Any, max_items: int = 12) -> None:
    print(f"\n=== {name} ===")
    print(f"type={type(block).__name__}")
    if isinstance(block, dict):
        print(f"keys={list(block.keys())[:30]}")
        for idx, (key, value) in enumerate(block.items()):
            if idx >= max_items:
                break
            print(f"item_{idx+1}_key={key!r}")
            print(f"item_{idx+1}_type={type(value).__name__}")
            if isinstance(value, dict):
                print(f"item_{idx+1}_keys={keys_of(value)}")
            elif isinstance(value, list):
                print(f"item_{idx+1}_count={len(value)}")
                if value:
                    print(f"item_{idx+1}_first_type={type(value[0]).__name__}")
                    print(f"item_{idx+1}_first_keys={keys_of(value[0])}")
            print(f"item_{idx+1}_sample={compact(value)}")
    elif isinstance(block, list):
        print(f"items={len(block)}")
        for idx, value in enumerate(block[:max_items], start=1):
            print(f"item_{idx}_type={type(value).__name__}")
            print(f"item_{idx}_keys={keys_of(value)}")
            print(f"item_{idx}_sample={compact(value)}")
    else:
        print(f"sample={compact(block)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True)
    args = parser.parse_args()

    league_id = args.league_id.strip()
    if not league_id:
        print("ERROR: league ID is empty")
        return 1

    print("BLHA FANTRAX MATCHUP SCHEMA SNAPSHOT")
    print(f"league_id={league_id}")
    print("read_only=true")

    try:
        info = get_info(league_id)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"leagueName={info.get('leagueName')!r}")
    print(f"startDate={info.get('startDate')!r}")
    print(f"endDate={info.get('endDate')!r}")
    print(f"seasonYear={info.get('seasonYear')!r}")

    describe_block("MATCHUPS", info.get("matchups"))
    describe_block("SCORING PERIODS", info.get("scoringPeriods"), max_items=8)
    describe_block("ROSTER PERIODS", info.get("rosterPeriods"), max_items=8)
    describe_block("TEAM INFO", info.get("teamInfo"), max_items=4)

    print("\nRESULT: matchup schema snapshot complete; no Fantrax data was modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
