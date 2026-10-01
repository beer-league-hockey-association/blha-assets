#!/usr/bin/env python3
"""Safety wrapper for BLHA playoff automation.

The playoff workflow runs on an hourly schedule year-round, but live Discord
posts must remain completely silent until Fantrax reaches the first playoff
scoring period and a final regular-season seed baseline has been recorded.
Manual preview/test/baseline modes are passed through unchanged.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import requests

import playoff as core


def arg_value(flag: str) -> str | None:
    try:
        index = sys.argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def live_preflight() -> int | None:
    """Return an exit code when live execution should stop before core.main."""
    mode = arg_value("--mode") or "preview"
    if mode != "live":
        return None

    cfg = core.load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from playoff_config.yaml")
        return 1

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Fantrax-Playoffs/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    try:
        info = core.get_json(session, "getLeagueInfo", league_id)
        playoffs = info.get("playoffs") or {}
        first = int(playoffs.get("firstPlayoffPeriod") or 0)
        cutoff = int(playoffs.get("numPlayoffTeams") or 6)
        detected = core.current_period(info, datetime.now(timezone.utc))
    except Exception as exc:
        print(f"ERROR: playoff live preflight Fantrax read failed: {exc}")
        return 1

    if detected is None or detected < first:
        print(
            "RESULT: playoffs have not started; 0 Discord messages sent and "
            "no playoff state changed."
        )
        return 0

    state = core.load_state()
    seeds = state.get("seeds")
    baseline_ready = (
        isinstance(seeds, dict)
        and len(seeds) >= cutoff
        and bool(state.get("recorded_at"))
    )

    if not baseline_ready:
        print(
            "RESULT: playoff window reached but no final regular-season seed "
            "baseline exists; run baseline after the regular season before "
            "live playoff posts are allowed."
        )
        return 0

    return None


def main() -> int:
    stopped = live_preflight()
    if stopped is not None:
        return stopped
    return core.main()


if __name__ == "__main__":
    sys.exit(main())
