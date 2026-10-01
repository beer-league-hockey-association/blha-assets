#!/usr/bin/env python3
"""BLHA weekly matchup preview automation.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.
The scheduled live mode posts exactly once at the start of each regular-season
scoring period, then remains silent until Fantrax advances to the next period.
"""

from __future__ import annotations

import argparse
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

CONFIG_PATH = ROOT / "matchup_preview_config.yaml"
STATE_PATH = ROOT / "state" / "matchup_preview.json"
AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)


def load_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fantrax_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Fantrax-Matchup-Preview/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def get_json(
    session: requests.Session,
    league_id: str,
    endpoint: str,
    **params: Any,
) -> Any:
    response = session.get(
        f"{BASE}/{endpoint}",
        params={"leagueId": league_id, **params},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def parse_dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def period_rows(info: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in (info.get("scoringPeriods") or []) if isinstance(row, dict)]
    rows.sort(key=lambda row: int(row.get("number") or 0))
    return rows


def find_period(
    info: dict[str, Any],
    requested: int | None,
) -> tuple[int | None, dict[str, Any] | None, bool]:
    rows = period_rows(info)
    if requested is not None:
        row = next(
            (row for row in rows if int(row.get("number") or 0) == requested),
            None,
        )
        return requested, row, bool(row)

    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            start = parse_dt(row.get("startDate"))
            end = parse_dt(row.get("endDate"))
        except Exception:
            continue
        if start <= now <= end:
            return int(row.get("number") or 0), row, True

    return None, None, False


def normalize_standings(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("getStandings did not return a list")

    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            continue
        team_id = str(row.get("teamId") or "")
        if not team_id:
            continue
        try:
            rank = int(row.get("rank") or index)
        except (TypeError, ValueError):
            rank = index
        result[team_id] = {
            "rank": rank,
            "record": str(row.get("points") or "0-0-0"),
            "teamName": str(row.get("teamName") or "Unknown Team"),
        }
    return result


def normalize_team(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "teamId": str(raw.get("teamId") or ""),
        "teamName": str(raw.get("teamName") or "Unknown Team"),
    }


def normalize_matchups(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("getMatchupScores did not return a dict")
    matchups = raw.get("matchups")
    if not isinstance(matchups, list):
        raise ValueError("getMatchupScores.matchups was not a list")

    result: list[dict[str, Any]] = []
    for row in matchups:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "away": normalize_team(row.get("away")),
                "home": normalize_team(row.get("home")),
            }
        )
    return result


def team_line(team: dict[str, Any], standings: dict[str, dict[str, Any]]) -> str:
    meta = standings.get(team.get("teamId", ""), {})
    rank = meta.get("rank")
    record = str(meta.get("record") or "0-0-0")
    rank_text = f"#{rank}" if rank else "Unranked"
    return f"**{team.get('teamName', 'Unknown Team')}** — {rank_text} • {record}"


def matchup_fields(
    matchups: list[dict[str, Any]],
    standings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for index, matchup in enumerate(matchups, start=1):
        fields.append(
            {
                "name": f"Matchup {index}",
                "value": (
                    f"{team_line(matchup['away'], standings)}\n"
                    "vs\n"
                    f"{team_line(matchup['home'], standings)}"
                ),
                "inline": False,
            }
        )
    return fields


def color_value(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def period_window(period_info: dict[str, Any] | None) -> str:
    if not period_info:
        return ""
    try:
        start = parse_dt(period_info.get("startDate"))
        end = parse_dt(period_info.get("endDate"))
        return f"<t:{int(start.timestamp())}:D> – <t:{int(end.timestamp())}:D>"
    except Exception:
        return ""


def build_payload(
    info: dict[str, Any],
    cfg: dict[str, Any],
    period: int,
    period_info: dict[str, Any] | None,
    matchups: list[dict[str, Any]],
    standings: dict[str, dict[str, Any]],
    *,
    test: bool,
) -> dict[str, Any]:
    league_name = str(info.get("leagueName") or "Beer League Hockey Association")
    season_label = str(cfg.get("season_label") or "")
    title = f"BLHA Week {period} Matchup Preview"
    if test:
        title = "[TEST] " + title

    description = f"**{league_name}**"
    if season_label:
        description += f" • {season_label}"
    window = period_window(period_info)
    if window:
        description += f"\n**Scoring Period:** {window}"
    description += (
        "\n\n*Weekly matchups with each team's current Fantrax standing and record. "
        "The scoreboard will track scoring once the period is underway.*"
    )

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "fields": matchup_fields(matchups, standings),
                "color": color_value(cfg.get("color", "0xFFB81C")),
                "footer": {
                    "text": f"{cfg.get('channel_label', 'SCOREBOARD')} • FANTRAX READ-ONLY DATA"
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def deliver(secret_name: str, body: dict[str, Any]) -> tuple[bool, str]:
    return post_discord_webhook(secret_name, body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("preview", "test", "live"),
        default="preview",
    )
    parser.add_argument("--period", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from matchup_preview_config.yaml")
        return 1

    try:
        session = fantrax_session()
        info = get_json(session, league_id, "getLeagueInfo")
        if not isinstance(info, dict):
            raise ValueError("getLeagueInfo did not return a dict")
        period, period_info, active = find_period(info, args.period)
        if period is None or period_info is None:
            print("RESULT: no active scoring period; 0 Discord messages sent.")
            return 0

        playoffs = info.get("playoffs") if isinstance(info.get("playoffs"), dict) else {}
        last_regular = int(playoffs.get("lastRegularSeasonPeriod") or 0)
        if args.period is None and last_regular and period > last_regular:
            print(
                f"RESULT: period {period} is outside the regular season; "
                "0 Discord messages sent."
            )
            return 0

        standings = normalize_standings(get_json(session, league_id, "getStandings"))
        matchups = normalize_matchups(
            get_json(session, league_id, "getMatchupScores", period=period)
        )
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    if not matchups:
        print(f"RESULT: Fantrax returned zero matchups for period {period}; no post sent.")
        return 0

    print(
        f"BLHA MATCHUP PREVIEW mode={args.mode.upper()} period={period} "
        f"active={active} matchups={len(matchups)}"
    )
    for index, matchup in enumerate(matchups, start=1):
        print(
            f"{index}. {team_line(matchup['away'], standings)} vs "
            f"{team_line(matchup['home'], standings)}"
        )

    body = build_payload(
        info,
        cfg,
        period,
        period_info,
        matchups,
        standings,
        test=args.mode == "test",
    )

    if args.mode == "preview":
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print("RESULT: preview only; no Discord message sent and no state changed.")
        return 0

    if args.mode == "live" and args.period is None and not active:
        print("RESULT: scoring period is not active; 0 Discord messages sent.")
        return 0

    state = load_state()
    previous_period = state.get("last_posted_period")
    if args.mode == "live" and previous_period == period and not args.force:
        print(f"RESULT: matchup preview for period {period} already posted; 0 Discord messages sent.")
        return 0

    secret_name = str(cfg.get("webhook_secret") or "BLHA_WEBHOOK_SCOREBOARD")
    ok, detail = deliver(secret_name, body)
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    state_updated = False
    if args.mode == "live":
        save_state(
            {
                "last_posted_period": period,
                "last_posted_at": datetime.now(timezone.utc).isoformat(),
                "matchup_count": len(matchups),
            }
        )
        state_updated = True

    print(
        f"RESULT: Discord matchup preview {detail}; "
        f"state_updated={state_updated}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
