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
    """Probe the website's PLAYOFFS view.

    This endpoint may require an authenticated Fantrax session even when
    getLeagueInfo/getStandings are anonymously readable. Treat pageError as an
    actual failure instead of a successful schema response.
    """
    payload = {
        "msgs": [
            {
                "method": "getStandings",
                "data": {
                    "leagueId": league_id,
                    "view": "PLAYOFFS",
                },
            }
        ]
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

    page_error = body.get("pageError")
    if isinstance(page_error, dict):
        code = page_error.get("code") or "UNKNOWN_PAGE_ERROR"
        raise RuntimeError(
            f"Fantrax PLAYOFFS view returned pageError {code}: "
            f"{compact(page_error)}"
        )

    responses = body.get("responses")
    if not isinstance(responses, list) or not responses:
        raise ValueError(
            f"Fantrax fxpa response has no responses: {compact(body)}"
        )

    first = responses[0]
    if not isinstance(first, dict):
        return first

    errors = first.get("errors")
    if errors:
        raise RuntimeError(
            f"Fantrax playoff view returned errors: {compact(errors)}"
        )

    return first


def print_playoff_matchups(info: dict[str, Any]) -> None:
    """Print only playoff-period pairings from the public league-info feed."""
    print("\n=== PLAYOFF MATCHUPS FROM getLeagueInfo ===")

    playoffs = info.get("playoffs")
    if not isinstance(playoffs, dict):
        print("playoff_config_missing=true")
        return

    first = playoffs.get("firstPlayoffPeriod")
    last_regular = playoffs.get("lastRegularSeasonPeriod")
    print(f"lastRegularSeasonPeriod={last_regular!r}")
    print(f"firstPlayoffPeriod={first!r}")

    matchups = info.get("matchups")
    if not isinstance(matchups, list):
        print("matchups_missing=true")
        return

    found = False
    for block in matchups:
        if not isinstance(block, dict):
            continue
        period = block.get("period")
        if not isinstance(period, int) or not isinstance(first, int) or period < first:
            continue

        found = True
        print(f"period={period}")
        matchup_list = block.get("matchupList")
        if not isinstance(matchup_list, list):
            print("  matchupList_missing=true")
            continue

        for matchup in matchup_list:
            if not isinstance(matchup, dict):
                continue
            away = matchup.get("away") or {}
            home = matchup.get("home") or {}
            if not isinstance(away, dict):
                away = {}
            if not isinstance(home, dict):
                home = {}
            print(
                "  "
                f"away={away.get('name')!r} [{away.get('id')}] "
                f"vs home={home.get('name')!r} [{home.get('id')}]"
            )

    if not found:
        print("no_playoff_period_matchups_found=true")


def get_matchup_scores(
    session: requests.Session,
    league_id: str,
    period: int,
) -> Any:
    response = session.get(
        f"{GENERAL_BASE}/getMatchupScores",
        params={"leagueId": league_id, "period": period},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and isinstance(data.get("pageError"), dict):
        raise RuntimeError(
            f"getMatchupScores returned pageError: "
            f"{compact(data['pageError'])}"
        )

    return data

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
        "User-Agent": "BLHA-Fantrax-Playoff-Snapshot/1.1",
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

    describe("PLAYOFFS FROM getLeagueInfo", info.get("playoffs"))
    print_playoff_matchups(info)

    playoffs = info.get("playoffs") if isinstance(info.get("playoffs"), dict) else {}
    first = playoffs.get("firstPlayoffPeriod")
    scoring_periods = info.get("scoringPeriods")
    max_period = None
    if isinstance(scoring_periods, list):
        nums = []
        for p in scoring_periods:
            if isinstance(p, dict):
                try:
                    nums.append(int(p.get("number")))
                except (TypeError, ValueError):
                    pass
        if nums:
            max_period = max(nums)

    playoff_nums = []
    if isinstance(first, int):
        last_period = max_period if max_period is not None else first + 2
        playoff_nums = list(range(first, last_period + 1))

    print(f"playoff_periods={playoff_nums}")

    for period in playoff_nums:
        try:
            scores = get_matchup_scores(session, league_id, period)
            describe(
                f"MATCHUP SCORES PERIOD {period}",
                scores,
                max_chars=4500,
            )
        except Exception as exc:
            print(
                f"\nWARNING: getMatchupScores period {period} failed: {exc}"
            )

    try:
        playoff_view = get_playoff_view(session, league_id)
        describe(
            "FXPA getStandings VIEW=PLAYOFFS",
            playoff_view,
            max_chars=6000,
        )
        playoff_view_status = "available"
    except Exception as exc:
        print(f"\nWARNING: PLAYOFFS view probe failed: {exc}")
        playoff_view_status = "unavailable"

    print(
        "\nRESULT: playoff schema probe complete; "
        f"fxpa_playoff_view={playoff_view_status}; "
        "getLeagueInfo_playoff_config=available; "
        "no Fantrax data was modified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
