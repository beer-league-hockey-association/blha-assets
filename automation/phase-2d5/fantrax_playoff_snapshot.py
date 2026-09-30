#!/usr/bin/env python3
"""BLHA Phase 2D.5A — inspect Fantrax playoff/bracket data.

Read-only. Does not modify Fantrax, Discord, or repository state.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

GENERAL_BASE = "https://www.fantrax.com/fxea/general"
PRIVATE_BASE = "https://www.fantrax.com/fxpa/req"


def compact(value: Any, max_chars: int = 5000) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def keys_of(value: Any) -> list[str]:
    return list(value.keys()) if isinstance(value, dict) else []


def get_league_info(session: requests.Session, league_id: str) -> dict[str, Any]:
    response = session.get(
        f"{GENERAL_BASE}/getLeagueInfo",
        params={"leagueId": league_id},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("getLeagueInfo did not return a dict")
    return data


def get_playoff_view(session: requests.Session, league_id: str) -> Any:
    payload = {
        "msgs": [
            {
                "method": "getStandings",
                "data": {
                    "leagueId": league_id,
                    "view": "PLAYOFFS",
                },
            }
        ],
        "uiv": 3,
        "refUrl": f"https://www.fantrax.com/fantasy/league/{league_id}/standings",
        "dt": 0,
        "at": 0,
        "tz": "Etc/UTC",
    }

    response = session.post(
        PRIVATE_BASE,
        params={"leagueId": league_id},
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()

    if not isinstance(body, dict):
        raise ValueError("Fantrax fxpa response did not return a dict")

    responses = body.get("responses")
    if not isinstance(responses, list) or not responses:
        raise ValueError(f"Fantrax fxpa response has no responses: {compact(body)}")

    first = responses[0]
    if not isinstance(first, dict):
        return first

    errors = first.get("errors")
    if errors:
        raise RuntimeError(f"Fantrax playoff view returned errors: {compact(errors)}")

    return first


def describe(name: str, value: Any, max_chars: int = 5000) -> None:
    print(f"\n=== {name} ===")
    print(f"type={type(value).__name__}")
    if isinstance(value, dict):
        print(f"keys={keys_of(value)}")
        for idx, (key, item) in enumerate(value.items(), start=1):
            if idx > 30:
                break
            print(f"item_{idx}_key={key!r}")
            print(f"item_{idx}_type={type(item).__name__}")
            if isinstance(item, dict):
                print(f"item_{idx}_keys={keys_of(item)}")
            elif isinstance(item, list):
                print(f"item_{idx}_count={len(item)}")
                if item:
                    print(f"item_{idx}_first_type={type(item[0]).__name__}")
                    print(f"item_{idx}_first_keys={keys_of(item[0])}")
            print(f"item_{idx}_sample={compact(item, max_chars=1600)}")
    elif isinstance(value, list):
        print(f"items={len(value)}")
        for idx, item in enumerate(value[:20], start=1):
            print(f"item_{idx}_type={type(item).__name__}")
            print(f"item_{idx}_keys={keys_of(item)}")
            print(f"item_{idx}_sample={compact(item, max_chars=1600)}")
    else:
        print(f"sample={compact(value, max_chars=max_chars)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True)
    args = parser.parse_args()

    league_id = args.league_id.strip()
    if not league_id:
        print("ERROR: league ID is empty")
        return 1

    session = requests.Session()
    session.headers.update({
        "User-Agent": "BLHA-Fantrax-Playoff-Snapshot/1.0",
        "Accept": "application/json,text/plain,*/*",
    })

    print("BLHA FANTRAX PLAYOFF SCHEMA SNAPSHOT")
    print(f"league_id={league_id}")
    print("read_only=true")

    try:
        info = get_league_info(session, league_id)
    except Exception as exc:
        print(f"ERROR: getLeagueInfo failed: {exc}")
        return 1

    print(f"leagueName={info.get('leagueName')!r}")
    print(f"seasonYear={info.get('seasonYear')!r}")
    print(f"startDate={info.get('startDate')!r}")
    print(f"endDate={info.get('endDate')!r}")

    # This is the first place to look for explicit playoff configuration.
    describe("PLAYOFFS FROM getLeagueInfo", info.get("playoffs"))

    # Keep matchup/scoring-period context available because the bracket may be
    # represented as playoff periods inside the normal matchup structure.
    describe("MATCHUPS", info.get("matchups"), max_chars=3500)
    describe("SCORING PERIODS", info.get("scoringPeriods"), max_chars=3000)

    try:
        playoff_view = get_playoff_view(session, league_id)
        describe("FXPA getStandings VIEW=PLAYOFFS", playoff_view, max_chars=6000)
        playoff_view_status = "available"
    except Exception as exc:
        print(f"\nWARNING: PLAYOFFS view probe failed: {exc}")
        playoff_view_status = "failed"

    print(
        "\nRESULT: playoff schema probe complete; "
        f"fxpa_playoff_view={playoff_view_status}; "
        "no Fantrax data was modified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
