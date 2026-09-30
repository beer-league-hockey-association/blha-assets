#!/usr/bin/env python3
"""BLHA Phase 2D.4 — Fantrax playoff-race view.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.

Modes:
- preview: print the current race view; no Discord delivery/state change
- test: send a clearly labeled test embed; do not alter state
- baseline: record the current race fingerprint; send nothing
- live: post only when the playoff-race snapshot materially changes

This first version deliberately reports the current playoff picture, bubble,
and cut-line gap. It does not invent clinching/elimination scenarios from
incomplete schedule or tiebreaker data. Those scenarios can be added once the
league's remaining-matchup and tiebreak semantics are proven.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

BASE = "https://www.fantrax.com/fxea/general"
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "playoff_race_config.yaml"
STATE_PATH = ROOT / "state" / "playoff_race.json"
AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fantrax_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Fantrax-Playoff-Race/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def get_json(session: requests.Session, league_id: str, endpoint: str) -> Any:
    response = session.get(
        f"{BASE}/{endpoint}",
        params={"leagueId": league_id},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def parse_record(value: Any) -> tuple[int, int, int]:
    text = str(value or "0-0-0").strip()
    parts = text.split("-")
    if len(parts) != 3:
        return 0, 0, 0
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return 0, 0, 0


def fmt_gb(value: float) -> str:
    if abs(value) < 0.0001:
        return "—"
    return f"{value:.2f}"


def normalize_rows(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("getStandings did not return a list")

    rows: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue

        record = str(row.get("points") or "0-0-0")
        wins, losses, ties = parse_record(record)

        try:
            rank = int(row.get("rank") or 0)
        except (TypeError, ValueError):
            rank = 0

        try:
            games_back = float(row.get("gamesBack") or 0.0)
        except (TypeError, ValueError):
            games_back = 0.0

        try:
            points_for = float(row.get("totalPointsFor") or 0.0)
        except (TypeError, ValueError):
            points_for = 0.0

        rows.append(
            {
                "rank": rank,
                "teamName": str(row.get("teamName") or "Unknown Team"),
                "teamId": str(row.get("teamId") or ""),
                "record": record,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "gamesBack": games_back,
                "pointsFor": points_for,
            }
        )

    rows.sort(
        key=lambda row: (
            row["rank"] if row["rank"] > 0 else 999,
            row["teamName"].lower(),
        )
    )
    return rows


def fingerprint(rows: list[dict], playoff_cut: int, bubble_depth: int) -> str:
    tracked = rows[: playoff_cut + bubble_depth]
    canonical = {
        "playoff_cut": playoff_cut,
        "bubble_depth": bubble_depth,
        "teams": [
            {
                "rank": row["rank"],
                "teamId": row["teamId"],
                "teamName": row["teamName"],
                "record": row["record"],
                "gamesBack": row["gamesBack"],
            }
            for row in tracked
        ],
    }
    text = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def console_table(rows: list[dict], playoff_cut: int, bubble_depth: int) -> str:
    limit = min(len(rows), playoff_cut + bubble_depth)
    lines = ["RK  TEAM                     REC        GB"] 
    lines.append("--  -----------------------  ---------  ------")
    for index, row in enumerate(rows[:limit], start=1):
        rank = row["rank"] or index
        name = row["teamName"][:23]
        lines.append(
            f"{rank:>2}  {name:<23}  {row['record']:<9}  "
            f"{fmt_gb(row['gamesBack']):>6}"
        )
        if rank == playoff_cut and rank < limit:
            lines.append("    -------- PLAYOFF CUT --------")
    return "\n".join(lines)


def team_value(row: dict) -> str:
    return (
        f"**Record:** {row['record']} • "
        f"**PF:** {row['pointsFor']:.2f} • "
        f"**GB:** {fmt_gb(row['gamesBack'])}"
    )


def race_fields(
    rows: list[dict],
    playoff_cut: int,
    bubble_depth: int,
) -> list[dict]:
    """Use the same clean vertical field format as standings/scoreboard."""
    fields: list[dict] = []
    limit = min(len(rows), playoff_cut + bubble_depth)

    for index, row in enumerate(rows[:limit], start=1):
        rank = row["rank"] or index
        title = f"{rank}. {row['teamName']}"
        if rank == playoff_cut:
            title += " — Playoff Cut"

        fields.append(
            {
                "name": title,
                "value": team_value(row),
                "inline": False,
            }
        )

    return fields


def color_value(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def build_payload(
    info: dict,
    rows: list[dict],
    cfg: dict,
    *,
    test: bool,
) -> dict:
    playoff_cut = int(cfg.get("playoff_cut", 6))
    bubble_depth = int(cfg.get("bubble_depth", 3))

    title = "BLHA Playoff Race"
    if test:
        title = "[TEST] " + title

    league_name = str(
        info.get("leagueName") or "Beer League Hockey Association"
    )
    season_label = str(cfg.get("season_label") or "")

    description = f"**{league_name}**"
    if season_label:
        description += f" • {season_label}"

    description += (
        f"\n\n*Playoff race pulled directly from Fantrax. "
        f"The top {playoff_cut} teams currently occupy playoff positions; "
        f"the next {bubble_depth} teams are tracked on the bubble.*"
    )

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "fields": race_fields(
                    rows,
                    playoff_cut,
                    bubble_depth,
                ),
                "color": color_value(cfg.get("color", "0xFFB81C")),
                "footer": {
                    "text": (
                        f"{cfg.get('channel_label', 'PLAYOFF RACE')} • "
                        "FANTRAX READ-ONLY DATA"
                    )
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def deliver(secret_name: str, body: dict) -> tuple[bool, str]:
    url = os.getenv(secret_name, "").strip()
    if not url:
        return False, f"missing secret {secret_name}"

    try:
        response = requests.post(
            url,
            params={"wait": "true"},
            json=body,
            timeout=25,
        )
    except Exception as exc:
        return False, f"request failed: {exc}"

    if response.status_code not in (200, 204):
        return (
            False,
            f"Discord returned {response.status_code}: "
            f"{response.text[:250]}",
        )

    return True, "delivered"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("preview", "test", "baseline", "live"),
        default="preview",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from playoff_race_config.yaml")
        return 1

    playoff_cut = int(cfg.get("playoff_cut", 6))
    bubble_depth = int(cfg.get("bubble_depth", 3))

    try:
        session = fantrax_session()
        info = get_json(session, league_id, "getLeagueInfo")
        rows = normalize_rows(get_json(session, league_id, "getStandings"))
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    if not isinstance(info, dict):
        print("ERROR: getLeagueInfo did not return a dict")
        return 1

    if len(rows) < playoff_cut:
        print(
            f"ERROR: Fantrax returned only {len(rows)} teams; "
            f"{playoff_cut} playoff positions are required."
        )
        return 1

    current_hash = fingerprint(rows, playoff_cut, bubble_depth)
    state = load_state()
    previous_hash = str(state.get("fingerprint") or "")

    print(
        "BLHA FANTRAX PLAYOFF RACE — "
        f"mode={args.mode.upper()} teams={len(rows)}"
    )
    print(console_table(rows, playoff_cut, bubble_depth))
    print(
        f"fingerprint={current_hash[:12]} "
        f"previous={(previous_hash or 'none')[:12]}"
    )

    if args.mode == "preview":
        print(
            "RESULT: preview only; no Discord message sent and no state changed."
        )
        return 0

    if args.mode == "baseline":
        save_state(
            {
                "fingerprint": current_hash,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "playoff_cut": playoff_cut,
                "bubble_depth": bubble_depth,
            }
        )
        print("RESULT: playoff-race baseline recorded; 0 Discord messages sent.")
        return 0

    if (
        args.mode == "live"
        and previous_hash == current_hash
        and not args.force
    ):
        print("RESULT: playoff race unchanged; 0 Discord messages sent.")
        return 0

    secret = str(
        cfg.get("webhook_secret") or "BLHA_WEBHOOK_PLAYOFF_RACE"
    )

    ok, detail = deliver(
        secret,
        build_payload(info, rows, cfg, test=args.mode == "test"),
    )
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    if args.mode == "live":
        save_state(
            {
                "fingerprint": current_hash,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "playoff_cut": playoff_cut,
                "bubble_depth": bubble_depth,
            }
        )

    print(
        f"RESULT: Discord playoff-race message {detail}; "
        f"state_updated={args.mode == 'live'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
