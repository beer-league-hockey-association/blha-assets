#!/usr/bin/env python3
"""BLHA Phase 2D.3E — completed Fantrax scoring-period recap to Discord.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.
Scheduled live runs post each completed scoring period once.
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
AUTOMATION_ROOT = ROOT.parent
if str(AUTOMATION_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_ROOT))

from discord_webhook import post_discord_webhook

CONFIG_PATH = ROOT / "weekly_recap_config.yaml"
STATE_PATH = ROOT / "state" / "weekly_recap.json"
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


def fantrax_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "BLHA-Fantrax-Weekly-Recap/1.0",
        "Accept": "application/json,text/plain,*/*",
    })
    return s


def get_json(s: requests.Session, league_id: str, endpoint: str, **params: Any) -> Any:
    response = s.get(
        f"{BASE}/{endpoint}",
        params={"leagueId": league_id, **params},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def period_by_number(info: dict, number: int) -> dict | None:
    for period in info.get("scoringPeriods") or []:
        if isinstance(period, dict) and int(period.get("number") or 0) == number:
            return period
    return None


def latest_completed_period(info: dict) -> dict | None:
    now = datetime.now(timezone.utc)
    completed: list[dict] = []
    for period in info.get("scoringPeriods") or []:
        if not isinstance(period, dict):
            continue
        try:
            number = int(period.get("number") or 0)
            end = parse_dt(period["endDate"])
        except Exception:
            continue
        if number > 0 and end < now:
            completed.append(period)
    if not completed:
        return None
    return max(completed, key=lambda p: int(p.get("number") or 0))


def current_or_first_period(info: dict) -> dict | None:
    periods = [p for p in info.get("scoringPeriods") or [] if isinstance(p, dict)]
    if not periods:
        return None
    now = datetime.now(timezone.utc)
    for period in periods:
        try:
            if parse_dt(period["startDate"]) <= now <= parse_dt(period["endDate"]):
                return period
        except Exception:
            continue
    return min(periods, key=lambda p: int(p.get("number") or 9999))


def normalize_team(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "teamName": str(raw.get("teamName") or "Unknown Team"),
        "teamId": str(raw.get("teamId") or ""),
        "score": float(raw.get("score") or 0.0),
        "gamesPlayed": float(raw.get("gamesPlayed") or 0.0),
    }


def normalize_matchups(raw: Any) -> list[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("matchups"), list):
        raise ValueError("getMatchupScores did not return a matchup list")
    rows: list[dict] = []
    for matchup in raw["matchups"]:
        if not isinstance(matchup, dict):
            continue
        rows.append({
            "away": normalize_team(matchup.get("away")),
            "home": normalize_team(matchup.get("home")),
        })
    return rows


def fmt_score(value: float) -> str:
    return f"{value:.2f}"


def fmt_gp(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def recap_fingerprint(period: int, rows: list[dict]) -> str:
    canonical = {
        "period": period,
        "matchups": [
            {
                "away": [r["away"]["teamId"], r["away"]["score"], r["away"]["gamesPlayed"]],
                "home": [r["home"]["teamId"], r["home"]["score"], r["home"]["gamesPlayed"]],
            }
            for r in rows
        ],
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def console_table(rows: list[dict]) -> str:
    lines = ["AWAY                     SCORE   HOME                     SCORE   MARGIN"]
    lines.append("-----------------------  ------  -----------------------  ------  ------")
    for row in rows:
        away = row["away"]
        home = row["home"]
        margin = abs(away["score"] - home["score"])
        lines.append(
            f"{away['teamName'][:23]:<23}  {fmt_score(away['score']):>6}  "
            f"{home['teamName'][:23]:<23}  {fmt_score(home['score']):>6}  {margin:>6.2f}"
        )
    return "\n".join(lines)


def matchup_fields(rows: list[dict]) -> list[dict]:
    fields: list[dict] = []
    for index, row in enumerate(rows, start=1):
        away = row["away"]
        home = row["home"]
        away_score = fmt_score(away["score"])
        home_score = fmt_score(home["score"])
        margin = abs(away["score"] - home["score"])

        if away["score"] > home["score"]:
            away_score_text = f"**{away_score} pts**"
            home_score_text = f"{home_score} pts"
            result = f"Result: **{away['teamName']}** wins by {margin:.2f} pts"
        elif home["score"] > away["score"]:
            away_score_text = f"{away_score} pts"
            home_score_text = f"**{home_score} pts**"
            result = f"Result: **{home['teamName']}** wins by {margin:.2f} pts"
        else:
            away_score_text = f"{away_score} pts"
            home_score_text = f"{home_score} pts"
            result = "Result: Tie"

        fields.append({
            "name": f"Matchup {index}",
            "value": (
                f"**{away['teamName']}** *(Away)* — {away_score_text} • `{fmt_gp(away['gamesPlayed'])} GP`\n"
                f"**{home['teamName']}** *(Home)* — {home_score_text} • `{fmt_gp(home['gamesPlayed'])} GP`\n"
                f"{result}"
            ),
            "inline": False,
        })
    return fields


def summary_fields(rows: list[dict]) -> list[dict]:
    teams = [row[side] for row in rows for side in ("away", "home")]
    if not teams or max(t["score"] for t in teams) <= 0:
        return []

    high = max(teams, key=lambda t: t["score"])
    margins = [
        (abs(row["away"]["score"] - row["home"]["score"]), row)
        for row in rows
    ]
    closest_margin, closest = min(margins, key=lambda item: item[0])
    largest_margin, largest = max(margins, key=lambda item: item[0])

    def pairing(row: dict) -> str:
        return f"{row['away']['teamName']} vs. {row['home']['teamName']}"

    return [
        {
            "name": "High Score",
            "value": f"**{high['teamName']}** — {fmt_score(high['score'])} pts",
            "inline": False,
        },
        {
            "name": "Closest Matchup",
            "value": f"{pairing(closest)} — {closest_margin:.2f}-point margin",
            "inline": False,
        },
        {
            "name": "Largest Margin",
            "value": f"{pairing(largest)} — {largest_margin:.2f}-point margin",
            "inline": False,
        },
    ]


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


def build_payload(info: dict, rows: list[dict], cfg: dict, period: int, period_info: dict | None, *, test: bool) -> dict:
    title = f"BLHA Week {period} Recap"
    if test:
        title = "[TEST] " + title

    description = f"**{info.get('leagueName') or 'Beer League Hockey Association'}**"
    if cfg.get("season_label"):
        description += f" • {cfg['season_label']}"
    window = period_window(period_info)
    if window:
        description += f"\n**Scoring Period:** {window}"
    description += "\n\n*Completed matchup results pulled directly from Fantrax.*"

    fields = matchup_fields(rows) + summary_fields(rows)

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": title,
            "description": description,
            "fields": fields,
            "color": color_value(cfg.get("color", "0xFFB81C")),
            "footer": {"text": f"{cfg.get('channel_label','WEEKLY RECAP')} • FANTRAX READ-ONLY DATA"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }


def deliver(secret_name: str, payload: dict) -> tuple[bool, str]:
    return post_discord_webhook(secret_name, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "baseline", "live"), default="preview")
    parser.add_argument("--period", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from weekly_recap_config.yaml")
        return 1

    try:
        s = fantrax_session()
        info = get_json(s, league_id, "getLeagueInfo")
        if not isinstance(info, dict):
            raise ValueError("getLeagueInfo did not return a dict")

        if args.period is not None:
            period_info = period_by_number(info, args.period)
        elif args.mode in {"live", "baseline"}:
            period_info = latest_completed_period(info)
        else:
            period_info = latest_completed_period(info) or current_or_first_period(info)

        if not period_info:
            print("RESULT: no completed scoring period is available yet; 0 Discord messages sent.")
            return 0

        period = int(period_info.get("number") or 0)
        raw = get_json(s, league_id, "getMatchupScores", period=period)
        rows = normalize_matchups(raw)
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    if not rows:
        print("ERROR: Fantrax returned zero matchups")
        return 1

    fp = recap_fingerprint(period, rows)
    state = load_state()
    last_period = int(state.get("last_recapped_period") or 0)

    print(f"BLHA FANTRAX WEEKLY RECAP — mode={args.mode.upper()} period={period} matchups={len(rows)}")
    print(console_table(rows))
    print(f"fingerprint={fp[:12]} last_recapped_period={last_period}")

    if args.mode == "preview":
        print("RESULT: preview only; no Discord message sent and no state changed.")
        return 0

    if args.mode == "baseline":
        save_state({
            "last_recapped_period": period,
            "fingerprint": fp,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        print("RESULT: recap baseline recorded; 0 Discord messages sent.")
        return 0

    if args.mode == "live" and period <= last_period and not args.force:
        print("RESULT: latest completed period already recapped; 0 Discord messages sent.")
        return 0

    secret = str(cfg.get("webhook_secret") or "BLHA_WEBHOOK_WEEKLY_RECAP")
    ok, detail = deliver(
        secret,
        build_payload(info, rows, cfg, period, period_info, test=args.mode == "test"),
    )
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    if args.mode == "live":
        save_state({
            "last_recapped_period": period,
            "fingerprint": fp,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"RESULT: Discord weekly recap {detail}; state_updated={args.mode == 'live'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
