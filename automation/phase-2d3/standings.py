#!/usr/bin/env python3
"""BLHA Phase 2D.3B — Fantrax standings to Discord.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.
Modes:
- preview: print current standings only
- test: send a clearly labeled test embed; do not alter state
- baseline: record current standings fingerprint; send nothing
- live: post only when standings changed from persisted state
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
CONFIG_PATH = ROOT / "standings_config.yaml"
STATE_PATH = ROOT / "state" / "standings.json"
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
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "BLHA-Fantrax-Standings/1.0",
        "Accept": "application/json,text/plain,*/*",
    })
    return s


def get_json(s: requests.Session, league_id: str, endpoint: str) -> Any:
    response = s.get(f"{BASE}/{endpoint}", params={"leagueId": league_id}, timeout=25)
    response.raise_for_status()
    return response.json()


def normalize_rows(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("getStandings did not return a list")
    rows: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        rows.append({
            "rank": int(row.get("rank") or 0),
            "teamName": str(row.get("teamName") or "Unknown Team"),
            "teamId": str(row.get("teamId") or ""),
            "points": str(row.get("points") or "0-0-0"),
            "totalPointsFor": float(row.get("totalPointsFor") or 0.0),
            "gamesBack": float(row.get("gamesBack") or 0.0),
            "winPercentage": float(row.get("winPercentage") or 0.0),
        })
    rows.sort(key=lambda r: (r["rank"] if r["rank"] > 0 else 999, r["teamName"].lower()))
    return rows


def fingerprint(rows: list[dict]) -> str:
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fmt_pf(value: float) -> str:
    return f"{value:.2f}"


def fmt_gb(value: float) -> str:
    if abs(value) < 0.0001:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def table(rows: list[dict], playoff_cut: int) -> str:
    """Compact console-only table for GitHub Actions logs."""
    lines = ["RK  TEAM                     REC        PF       GB"]
    lines.append("--  -----------------------  ---------  -------  ----")
    for index, row in enumerate(rows, start=1):
        rank = row["rank"] or index
        name = row["teamName"][:23]
        rec = row["points"][:9]
        pf = fmt_pf(row["totalPointsFor"])
        gb = fmt_gb(row["gamesBack"])
        lines.append(f"{rank:>2}  {name:<23}  {rec:<9}  {pf:>7}  {gb:>4}")
        if rank == playoff_cut and rank < len(rows):
            lines.append("    -------- PLAYOFF CUT --------")
    return "\n".join(lines)


def discord_standing_fields(rows: list[dict], playoff_cut: int) -> list[dict]:
    """Use the same clean vertical field style as the BLHA scoreboard."""
    fields: list[dict] = []
    for index, row in enumerate(rows, start=1):
        rank = row["rank"] or index
        title = f"{rank}. {row['teamName']}"
        if rank == playoff_cut:
            title += " — Playoff Cut"

        value = (
            f"**Record:** {row['points']} • "
            f"**PF:** {fmt_pf(row['totalPointsFor'])} • "
            f"**GB:** {fmt_gb(row['gamesBack'])}"
        )
        fields.append({
            "name": title,
            "value": value,
            "inline": False,
        })
    return fields


def color_value(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def payload(info: dict, rows: list[dict], cfg: dict, *, test: bool = False) -> dict:
    league_name = str(info.get("leagueName") or "Beer League Hockey Association")
    season_label = str(cfg.get("season_label") or "")
    playoff_cut = int(cfg.get("playoff_cut", 6))
    title = "BLHA League Standings"
    if test:
        title = "[TEST] " + title

    description = f"**{league_name}**"
    if season_label:
        description += f" • {season_label}"
    description += (
        f"\n\n*Standings pulled directly from Fantrax. "
        f"The top {playoff_cut} teams currently occupy playoff positions.*"
    )

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": title,
            "description": description,
            "fields": discord_standing_fields(rows, playoff_cut),
            "color": color_value(cfg.get("color", "0xFFB81C")),
            "footer": {"text": f"{cfg.get('channel_label','STANDINGS')} • FANTRAX READ-ONLY DATA"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }


def deliver(secret_name: str, body: dict) -> tuple[bool, str]:
    url = os.getenv(secret_name, "").strip()
    if not url:
        return False, f"missing secret {secret_name}"
    try:
        response = requests.post(url, params={"wait": "true"}, json=body, timeout=25)
    except Exception as exc:
        return False, f"request failed: {exc}"
    if response.status_code not in (200, 204):
        return False, f"Discord returned {response.status_code}: {response.text[:250]}"
    return True, "delivered"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "baseline", "live"), default="preview")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from standings_config.yaml")
        return 1

    try:
        s = session()
        info = get_json(s, league_id, "getLeagueInfo")
        rows = normalize_rows(get_json(s, league_id, "getStandings"))
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    if not rows:
        print("ERROR: Fantrax returned zero standings rows")
        return 1

    current_hash = fingerprint(rows)
    state = load_state()
    previous_hash = state.get("fingerprint")

    print(f"BLHA FANTRAX STANDINGS — mode={args.mode.upper()} teams={len(rows)}")
    print(table(rows, int(cfg.get("playoff_cut", 6))))
    print(f"fingerprint={current_hash[:12]} previous={(previous_hash or 'none')[:12]}")

    if args.mode == "preview":
        print("RESULT: preview only; no Discord message sent and no state changed.")
        return 0

    if args.mode == "baseline":
        save_state({
            "fingerprint": current_hash,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "team_count": len(rows),
        })
        print("RESULT: baseline recorded; 0 Discord messages sent.")
        return 0

    secret = str(cfg.get("webhook_secret") or "BLHA_WEBHOOK_STANDINGS")

    if args.mode == "live" and previous_hash == current_hash and not args.force:
        print("RESULT: standings unchanged; 0 Discord messages sent.")
        return 0

    ok, detail = deliver(secret, payload(info if isinstance(info, dict) else {}, rows, cfg, test=args.mode == "test"))
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    if args.mode == "live":
        save_state({
            "fingerprint": current_hash,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "team_count": len(rows),
        })

    print(f"RESULT: Discord standings message {detail}; state_updated={args.mode == 'live'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
