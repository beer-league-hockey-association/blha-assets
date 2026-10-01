#!/usr/bin/env python3
"""BLHA read-only Fantrax league-transaction schema probe.

This script does not modify Fantrax, Discord, or repository state. It tests
Fantrax's transaction-history request shape from GitHub Actions so we can decide
whether a public BLHA league transaction feed is reliable enough to automate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

REQ_URL = "https://www.fantrax.com/fxpa/req"


def describe(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict keys={list(value.keys())[:20]}"
    if isinstance(value, list):
        return f"list items={len(value)}"
    return type(value).__name__


def compact(value: Any, limit: int = 1800) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def request_history(
    session: requests.Session,
    league_id: str,
    *,
    view: str | None,
) -> tuple[str, str, Any | None]:
    data: dict[str, Any] = {
        "leagueId": league_id,
        "maxResultsPerPage": "100",
        "pageNumber": "1",
        "executedOnly": True,
        "includeDeleted": False,
    }
    if view:
        data["view"] = view

    payload = {
        "msgs": [
            {
                "method": "getTransactionDetailsHistory",
                "data": data,
            }
        ]
    }

    try:
        response = session.post(
            REQ_URL,
            params={"leagueId": league_id},
            json=payload,
            timeout=30,
        )
    except Exception as exc:
        return "ERROR", f"request failed: {exc}", None

    preview = response.text[:300].replace("\n", " ").replace("\r", " ")
    if response.status_code != 200:
        return "BLOCKED", f"HTTP {response.status_code}; body={preview!r}", None

    try:
        body = response.json()
    except Exception:
        if "<html" in response.text[:500].lower():
            return "AUTH_REQUIRED", "received HTML instead of JSON", None
        return "UNKNOWN", f"HTTP 200 non-JSON body={preview!r}", None

    lowered = compact(body, 4000).lower()
    auth_markers = (
        "not logged in",
        "login required",
        "unauthorized",
        "not authorized",
        "access denied",
        "permission denied",
    )
    if any(marker in lowered for marker in auth_markers):
        return "AUTH_REQUIRED", describe(body), body

    return "PASS", describe(body), body


def extract_result(body: Any) -> Any:
    """Return the first useful nested result without assuming Fantrax schema."""
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict):
            for key in ("data", "result", "response"):
                if key in first:
                    return first[key]
        return first
    if isinstance(body, dict):
        for key in ("responses", "msgs", "data", "result"):
            value = body.get(key)
            if value:
                return value
    return body


def print_probe(label: str, status: str, detail: str, body: Any | None) -> None:
    print(f"{status:13} {label}: {detail}")
    if status != "PASS" or body is None:
        return
    useful = extract_result(body)
    print(f"  result_shape={describe(useful)}")
    print(f"  sample={compact(useful)}")


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
                "Chrome/136.0 Safari/537.36 BLHA-Transaction-Probe/1.0"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
        }
    )

    cookie = os.getenv("FANTRAX_COOKIE", "").strip()
    if cookie:
        session.headers["Cookie"] = cookie
        auth_mode = "cookie-present"
    else:
        auth_mode = "anonymous"

    print("BLHA FANTRAX LEAGUE-TRANSACTION PROBE")
    print(f"league_id={league_id}")
    print(f"auth_mode={auth_mode}")
    print("read_only=true")
    print("writes_to_fantrax=false")
    print("writes_to_discord=false\n")

    probes = (
        ("ALL EXECUTED TRANSACTIONS", None),
        ("CLAIMS / ADDS / DROPS", "CLAIM_DROP"),
        ("TRADES", "TRADE"),
    )

    results: list[str] = []
    for label, view in probes:
        status, detail, body = request_history(session, league_id, view=view)
        results.append(status)
        print_probe(label, status, detail, body)
        print()

    passes = results.count("PASS")
    if passes == len(results):
        print("RESULT: transaction history is anonymously readable; inspect schema samples before building Discord ingestion.")
    elif passes:
        print("RESULT: transaction history is partially readable; inspect per-view results before building ingestion.")
    elif any(status == "AUTH_REQUIRED" for status in results):
        print("RESULT: transaction history appears authentication-gated. Do not add credentials yet; review the probe output first.")
    else:
        print("RESULT: transaction-history probe was inconclusive; inspect the request results above.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
