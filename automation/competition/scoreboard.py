#!/usr/bin/env python3
"""BLHA live scoreboard: one Discord message per week, edited as scores change.

- When a week starts, a new scoreboard message is posted.
- Each check edits that same message if any score or games-played changed.
  Edits do not notify members, so the channel stays quiet but current.
- When the week's games are done (6 AM on the day it ends), the message gets
  one last edit marking it Final, and it stays in the channel as the record.

Modes:
  preview  print the current scoreboard payload; no Discord, no state change
  test     post a [TEST] scoreboard as a new message; no state change
  live     open / update / finalize the live message and record its id
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import render  # noqa: E402
from blha import season  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook, upsert_discord_message  # noqa: E402

STATE_PATH = ROOT / "state" / "scoreboard.json"


def fingerprint(week: int, rows: list[dict], final: bool) -> str:
    canonical = {
        "week": week,
        "final": final,
        "rows": [
            [r["away"]["teamId"], r["away"]["score"], r["away"]["gamesPlayed"],
             r["home"]["teamId"], r["home"]["score"], r["home"]["gamesPlayed"]]
            for r in rows
        ],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def plan_scoreboard(info: dict[str, Any], state: dict[str, Any], now: datetime, tz: ZoneInfo) -> list[tuple[str, int]]:
    """Return ordered actions: ("finalize"|"open"|"update", week)."""
    actions: list[tuple[str, int]] = []
    tracked = int(state.get("week") or 0)
    if tracked and not state.get("final"):
        p = season.period(info, tracked)
        if p and season.is_final(p, now, tz):
            actions.append(("finalize", tracked))

    current = season.active_period(info, now)
    if current and not season.is_final(current, now, tz):
        if tracked != current.number:
            actions.append(("open", current.number))
        elif not state.get("final"):
            actions.append(("update", current.number))
    return actions


def run(mode: str, week_override: int | None) -> int:
    cfg = load_league()
    tz = timezone_of(cfg)
    now = datetime.now(timezone.utc)
    secret = str((cfg.get("competition") or {}).get("webhooks", {}).get("scoreboard") or "BLHA_WEBHOOK_SCOREBOARD")
    fx = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Scoreboard/2.0")
    info = fx.league_info()
    _, first_playoff, _ = season.playoff_settings(info)
    ctx = render.Context(
        league_name=str(info.get("leagueName") or ""),
        season_label=str(cfg.get("season_label") or ""),
        color=color_value(cfg.get("color")),
        test=(mode == "test"),
    )
    print(f"BLHA SCOREBOARD mode={mode.upper()} season={season.describe(info, now)}")

    def payload_for(week: int, final: bool) -> tuple[dict, str]:
        p = season.period(info, week)
        if p is None:
            raise ValueError(f"Fantrax has no week {week}")
        rows = fx.matchup_scores(week)
        body = render.scoreboard(ctx, p, rows, final=final, playoffs=week >= first_playoff)
        return body, fingerprint(week, rows, final)

    if mode in ("preview", "test"):
        current = season.active_period(info, now) or season.latest_final(info, now, tz)
        week = week_override or (current.number if current else 1)
        p = season.period(info, week)
        final = bool(p and season.is_final(p, now, tz))
        body, _ = payload_for(week, final)
        if mode == "preview":
            print(json.dumps(body, indent=2))
            return 0
        ok, detail, _ = send_discord_webhook(secret, body)
        print(f"{'POSTED' if ok else 'ERROR'} test scoreboard week {week}: {detail}")
        return 0 if ok else 1

    state = load_json(STATE_PATH, {})
    actions = plan_scoreboard(info, state, now, tz)
    if not actions:
        print("RESULT: no active week to track; nothing to do")
        return 0

    errors = 0
    for action, week in actions:
        final = action == "finalize"
        body, fp = payload_for(week, final)
        if action == "update" and fp == state.get("fingerprint"):
            print(f"UNCHANGED week {week}")
            continue
        message_id = None if action == "open" else state.get("message_id")
        ok, detail, new_id, how = upsert_discord_message(secret, body, message_id)
        if not ok:
            print(f"ERROR   {action} week {week}: {detail}")
            errors += 1
            break
        state = {
            "week": week,
            "message_id": new_id,
            "fingerprint": fp,
            "final": final,
            "updated_at": now.isoformat(),
        }
        save_json(STATE_PATH, state)
        print(f"{how.upper():8} week {week} ({action})")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--week", type=int, help="Week to render in preview/test mode")
    args = parser.parse_args()
    try:
        return run(args.mode, args.week)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
