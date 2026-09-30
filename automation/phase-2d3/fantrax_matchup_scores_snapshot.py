#!/usr/bin/env python3
"""BLHA Phase 2D.3D — inspect Fantrax matchup-score data shape.

Read-only. Does not modify Fantrax, Discord, or repository state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

import requests

BASE = "https://www.fantrax.com/fxea/general"


def compact(value: Any, max_chars: int = 3200) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...<truncated>"


def keys_of(value: Any) -> list[str]:
    return list(value.keys()) if isinstance(value, dict) else []


def get_json(session: requests.Session, league_id: str, endpoint: str, **params: Any) -> Any:
    query = {"leagueId": league_id, **params}
    response = session.get(f"{BASE}/{endpoint}", params=query, timeout=25)
    response.raise_for_status()
    return response.json()


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def choose_period(info: dict, requested: int | None) -> int:
    periods = info.get("scoringPeriods")
    if requested is not None:
        return requested
    if not isinstance(periods, list) or not periods:
        return 1

    now = datetime.now(timezone.utc)
    for period in periods:
        if not isinstance(period, dict):
            continue
        try:
            start = parse_dt(str(period.get("startDate"))).astimezone(timezone.utc)
            end = parse_dt(str(period.get("endDate"))).astimezone(timezone.utc)
            if start <= now <= end:
                return int(period.get("number") or 1)
        except Exception:
            continue

    # Before/after season: choose the closest valid period boundary rather than
    # relying on Fantrax's behavior when period is omitted.
    sortable: list[tuple[datetime, int]] = []
    for period in periods:
        if not isinstance(period, dict):
            continue
        try:
            sortable.append((parse_dt(str(period.get("startDate"))).astimezone(timezone.utc), int(period.get("number") or 1)))
        except Exception:
            continue
    if not sortable:
        return 1
    future = [item for item in sortable if item[0] > now]
    if future:
        return min(future)[1]
    return max(sortable)[1]


def describe(data: Any) -> None:
    print("\n=== MATCHUP SCORES ===")
    print(f"type={type(data).__name__}")
    if isinstance(data, dict):
        print(f"keys={list(data.keys())[:40]}")
        for idx, (key, value) in enumerate(data.items(), start=1):
            if idx > 20:
                break
            print(f"item_{idx}_key={key!r}")
            print(f"item_{idx}_type={type(value).__name__}")
            if isinstance(value, dict):
                print(f"item_{idx}_keys={keys_of(value)}")
            elif isinstance(value, list):
                print(f"item_{idx}_count={len(value)}")
                if value:
                    print(f"item_{idx}_first_type={type(value[0]).__name__}")
                    print(f"item_{idx}_first_keys={keys_of(value[0])}")
            print(f"item_{idx}_sample={compact(value)}")
    elif isinstance(data, list):
        print(f"items={len(data)}")
        for idx, value in enumerate(data[:20], start=1):
            print(f"item_{idx}_type={type(value).__name__}")
            print(f"item_{idx}_keys={keys_of(value)}")
            print(f"item_{idx}_sample={compact(value)}")
    else:
        print(f"sample={compact(data)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league-id", required=True)
    parser.add_argument("--period", type=int)
    args = parser.parse_args()

    league_id = args.league_id.strip()
    if not league_id:
        print("ERROR: league ID is empty")
        return 1

    session = requests.Session()
    session.headers.update({
        "User-Agent": "BLHA-Fantrax-Matchup-Score-Snapshot/1.0",
        "Accept": "application/json,text/plain,*/*",
    })

    print("BLHA FANTRAX MATCHUP SCORE SNAPSHOT")
    print(f"league_id={league_id}")
    print("read_only=true")

    try:
        info = get_json(session, league_id, "getLeagueInfo")
        if not isinstance(info, dict):
            raise ValueError("getLeagueInfo did not return a dict")
        period = choose_period(info, args.period)
        scores = get_json(session, league_id, "getMatchupScores", period=period)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"leagueName={info.get('leagueName')!r}")
    print(f"period={period}")
    describe(scores)
    print("\nRESULT: matchup-score snapshot complete; no Fantrax data was modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
