#!/usr/bin/env python3
"""BLHA Phase 2D.3C — Fantrax weekly scoreboard to Discord.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.
Modes:
- preview: print current scoreboard only
- test: send a clearly labeled test embed; do not alter state
- baseline: record current scoreboard fingerprint; send nothing
- live: post only when the scoreboard changed from persisted state

The fingerprint intentionally ignores category-level stat detail so the channel
tracks actual matchup score/GP changes instead of every underlying stat update.
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
CONFIG_PATH = ROOT / "scoreboard_config.yaml"
STATE_PATH = ROOT / "state" / "scoreboard.json"
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
        "User-Agent": "BLHA-Fantrax-Scoreboard/1.0",
        "Accept": "application/json,text/plain,*/*",
    })
    return s


def get_json(s: requests.Session, league_id: str, endpoint: str, **params: Any) -> Any:
    query = {"leagueId": league_id, **params}
    response = s.get(f"{BASE}/{endpoint}", params=query, timeout=25)
    response.raise_for_status()
    return response.json()


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def current_period(info: dict, requested: int | None = None) -> tuple[int, dict | None]:
    periods = info.get("scoringPeriods") or []
    if requested is not None:
        row = next((p for p in periods if int(p.get("number") or 0) == requested), None)
        return requested, row

    now = datetime.now(timezone.utc)
    for period in periods:
        try:
            start = parse_dt(period["startDate"]).astimezone(timezone.utc)
            end = parse_dt(period["endDate"]).astimezone(timezone.utc)
        except Exception:
            continue
        if start <= now <= end:
            return int(period.get("number") or 0), period

    valid = [p for p in periods if int(p.get("number") or 0) > 0]
    if valid:
        first = valid[0]
        last = valid[-1]
        try:
            if now < parse_dt(first["startDate"]).astimezone(timezone.utc):
                return int(first["number"]), first
        except Exception:
            pass
        return int(last["number"]), last

    raise ValueError("Fantrax returned no usable scoring periods")


def normalize_team(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "teamName": str(raw.get("teamName") or "Unknown Team"),
        "teamId": str(raw.get("teamId") or ""),
        "score": float(raw.get("score") or 0.0),
        "gamesPlayed": float(raw.get("gamesPlayed") or 0.0),
    }


def normalize_matchups(raw: Any) -> list[dict]:
    if not isinstance(raw, dict):
        raise ValueError("getMatchupScores did not return a dict")
    matchups = raw.get("matchups")
    if not isinstance(matchups, list):
        raise ValueError("getMatchupScores.matchups was not a list")

    rows: list[dict] = []
    for matchup in matchups:
        if not isinstance(matchup, dict):
            continue
        rows.append({
            "away": normalize_team(matchup.get("away")),
            "home": normalize_team(matchup.get("home")),
        })
    return rows


def canonical_for_fingerprint(period: int, rows: list[dict]) -> dict:
    return {
        "period": period,
        "matchups": [
            {
                "away": {
                    "teamId": row["away"]["teamId"],
                    "score": row["away"]["score"],
                    "gamesPlayed": row["away"]["gamesPlayed"],
                },
                "home": {
                    "teamId": row["home"]["teamId"],
                    "score": row["home"]["score"],
                    "gamesPlayed": row["home"]["gamesPlayed"],
                },
            }
            for row in rows
        ],
    }


def fingerprint(period: int, rows: list[dict]) -> str:
    canonical = json.dumps(
        canonical_for_fingerprint(period, rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fmt_score(value: float) -> str:
    return f"{value:.2f}"


def fmt_gp(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def scoreboard_table(rows: list[dict]) -> str:
    """Compact console-only table for GitHub Actions logs."""
    lines = ["AWAY                     SCORE   GP   HOME                     SCORE   GP"]
    lines.append("-----------------------  ------  ---  -----------------------  ------  ---")
    for row in rows:
        away = row["away"]
        home = row["home"]
        lines.append(
            f"{away['teamName'][:23]:<23}  {fmt_score(away['score']):>6}  {fmt_gp(away['gamesPlayed']):>3}  "
            f"{home['teamName'][:23]:<23}  {fmt_score(home['score']):>6}  {fmt_gp(home['gamesPlayed']):>3}"
        )
    return "\n".join(lines)


def discord_matchup_fields(rows: list[dict]) -> list[dict]:
    """Use vertical embed fields so Discord never wraps a wide ASCII table badly."""
    fields: list[dict] = []
    for index, row in enumerate(rows, start=1):
        away = row["away"]
        home = row["home"]
        away_score = fmt_score(away["score"])
        home_score = fmt_score(home["score"])

        if away["score"] > home["score"]:
            away_score_text = f"**{away_score} pts**"
            home_score_text = f"{home_score} pts"
        elif home["score"] > away["score"]:
            away_score_text = f"{away_score} pts"
            home_score_text = f"**{home_score} pts**"
        else:
            away_score_text = f"{away_score} pts"
            home_score_text = f"{home_score} pts"

        fields.append({
            "name": f"Matchup {index}",
            "value": (
                f"✈️ **{away['teamName']}** — {away_score_text} • `{fmt_gp(away['gamesPlayed'])} GP`\n"
                f"🏠 **{home['teamName']}** — {home_score_text} • `{fmt_gp(home['gamesPlayed'])} GP`"
            ),
            "inline": False,
        })
    return fields


def color_value(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def period_window(period_info: dict | None) -> str:
    if not period_info:
        return ""
    try:
        start = parse_dt(period_info["startDate"])
        end = parse_dt(period_info["endDate"])
        return f"<t:{int(start.timestamp())}:D> – <t:{int(end.timestamp())}:D>"
    except Exception:
        return ""


def payload(info: dict, rows: list[dict], cfg: dict, period: int, period_info: dict | None, *, test: bool = False) -> dict:
    league_name = str(info.get("leagueName") or "Beer League Hockey Association")
    season_label = str(cfg.get("season_label") or "")
    title = f"BLHA Week {period} Scoreboard"
    if test:
        title = "[TEST] " + title

    description = f"**{league_name}**"
    if season_label:
        description += f" • {season_label}"
    window = period_window(period_info)
    if window:
        description += f"\n**Scoring Period:** {window}"
    description += "\n\n*Scores and games played pulled directly from Fantrax. The leading score is bolded.*"

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": title,
            "description": description,
            "fields": discord_matchup_fields(rows),
            "color": color_value(cfg.get("color", "0xFFB81C")),
            "footer": {"text": f"{cfg.get('channel_label','📊 SCOREBOARD')} • FANTRAX READ-ONLY DATA"},
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
    parser.add_argument("--period", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from scoreboard_config.yaml")
        return 1

    try:
        s = session()
        info = get_json(s, league_id, "getLeagueInfo")
        if not isinstance(info, dict):
            raise ValueError("getLeagueInfo did not return a dict")
        period, period_info = current_period(info, args.period)
        raw_scores = get_json(s, league_id, "getMatchupScores", period=period)
        rows = normalize_matchups(raw_scores)
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    if not rows:
        print("ERROR: Fantrax returned zero matchups")
        return 1

    current_hash = fingerprint(period, rows)
    state = load_state()
    previous_hash = state.get("fingerprint")

    print(f"BLHA FANTRAX SCOREBOARD — mode={args.mode.upper()} period={period} matchups={len(rows)}")
    print(scoreboard_table(rows))
    print(f"fingerprint={current_hash[:12]} previous={(previous_hash or 'none')[:12]}")

    if args.mode == "preview":
        print("RESULT: preview only; no Discord message sent and no state changed.")
        return 0

    if args.mode == "baseline":
        save_state({
            "fingerprint": current_hash,
            "period": period,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "matchup_count": len(rows),
        })
        print("RESULT: baseline recorded; 0 Discord messages sent.")
        return 0

    secret = str(cfg.get("webhook_secret") or "BLHA_WEBHOOK_SCOREBOARD")

    if args.mode == "live" and previous_hash == current_hash and not args.force:
        print("RESULT: scoreboard unchanged; 0 Discord messages sent.")
        return 0

    ok, detail = deliver(
        secret,
        payload(info, rows, cfg, period, period_info, test=args.mode == "test"),
    )
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    if args.mode == "live":
        save_state({
            "fingerprint": current_hash,
            "period": period,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "matchup_count": len(rows),
        })

    print(f"RESULT: Discord scoreboard message {detail}; state_updated={args.mode == 'live'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
