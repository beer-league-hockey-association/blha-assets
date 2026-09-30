#!/usr/bin/env python3
"""BLHA Phase 2D.3 — read-only Fantrax data-path probe.

This does not modify Fantrax, Discord, or repository state. It only checks
whether the league-scoped Fantrax beta endpoints are reachable from GitHub
Actions with the supplied league ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

BASE = "https://www.fantrax.com/fxea/general"
ENDPOINTS = (
    "getLeagueInfo",
    "getStandings",
    "getTeamRosters",
    "getDraftPicks",
)


def describe_json(data: Any) -> str:
    if isinstance(data, dict):
        keys = list(data.keys())[:12]
        return f"dict keys={keys}"
    if isinstance(data, list):
        return f"list items={len(data)}"
    return type(data).__name__


def probe(session: requests.Session, league_id: str, endpoint: str) -> tuple[str, str]:
    url = f"{BASE}/{endpoint}"
    try:
        response = session.get(url, params={"leagueId": league_id}, timeout=25)
    except Exception as exc:
        return "ERROR", f"request failed: {exc}"

    content_type = response.headers.get("content-type", "").lower()
    body_preview = response.text[:180].replace("\n", " ").replace("\r", " ")

    if response.status_code != 200:
        return "BLOCKED", f"HTTP {response.status_code}; body={body_preview!r}"

    try:
        data = response.json()
    except Exception:
        if "text/html" in content_type or "<html" in response.text[:500].lower():
            return "AUTH_REQUIRED", "received HTML instead of JSON (likely login/auth gate)"
        return "UNKNOWN", f"HTTP 200 but response was not JSON; body={body_preview!r}"

    # Common auth/error shapes should not be treated as successful data access.
    if isinstance(data, dict):
        text = json.dumps(data)[:1200].lower()
        auth_markers = (
            "not logged in",
            "login required",
            "unauthorized",
            "not authorized",
            "access denied",
            "permission",
        )
        if any(marker in text for marker in auth_markers):
            return "AUTH_REQUIRED", describe_json(data)

    return "PASS", describe_json(data)


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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0 Safari/537.36 BLHA-ReadOnly-Probe/1.0"
            ),
            "Accept": "application/json,text/plain,*/*",
        }
    )

    # Optional only. Do not require or print this value.
    cookie = os.getenv("FANTRAX_COOKIE", "").strip()
    if cookie:
        session.headers["Cookie"] = cookie
        auth_mode = "cookie-present"
    else:
        auth_mode = "anonymous"

    print("BLHA FANTRAX DATA-PATH PROBE")
    print(f"league_id={league_id}")
    print(f"auth_mode={auth_mode}")
    print("read_only=true\n")

    results: list[tuple[str, str, str]] = []
    for endpoint in ENDPOINTS:
        status, detail = probe(session, league_id, endpoint)
        results.append((endpoint, status, detail))
        print(f"{status:13} {endpoint}: {detail}")

    passes = sum(1 for _, status, _ in results if status == "PASS")
    auth_required = sum(1 for _, status, _ in results if status == "AUTH_REQUIRED")
    blocked = sum(1 for _, status, _ in results if status == "BLOCKED")
    errors = sum(1 for _, status, _ in results if status in {"ERROR", "UNKNOWN"})

    print(
        f"\nSUMMARY pass={passes} auth_required={auth_required} "
        f"blocked={blocked} errors={errors} total={len(results)}"
    )

    if passes == len(ENDPOINTS):
        print("RESULT: Fantrax read-only data path is fully available.")
    elif passes > 0:
        print("RESULT: Fantrax data path is partially available; inspect endpoint results before building ingestion.")
    elif auth_required or blocked:
        print("RESULT: Anonymous access is insufficient. Do not add credentials yet; review this probe first.")
    else:
        print("RESULT: Probe was inconclusive; inspect the endpoint details above.")

    # Diagnostic probe should finish successfully so the log is easy to inspect.
    return 0


if __name__ == "__main__":
    sys.exit(main())
