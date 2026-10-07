#!/usr/bin/env python3
"""BLHA Lineup Alerts: a daily nudge when a starter has no NHL game today.

Once a day (about 3:00 PM ET, regular season and playoffs) this checks each
opted-in owner's Fantrax lineup for today. When a player in the ACTIVE lineup
has no NHL regular-season game today while one of that franchise's RESERVE
players at an eligible position does play (and his game has not started yet),
the owner gets one short message in #lineup-alerts that mentions them.
Lineups are the manager's job (9.1); this is only a reminder. Players lock
about one minute before their own game (5.3).

Who gets alerts: only owners listed under ``owners`` in automation/league.yaml,
the same opt-in the Wire uses for injury pings. Nobody else is mentioned.

Position eligibility, kept simple:
  - a C, LW or RW slot takes a reserve listed at that position;
  - an F (utility forward) slot takes any forward: C, LW, RW or F;
  - D only for D, G only for G.
  A reserve's positions are his Fantrax roster position plus the position(s)
  in getPlayerIds (comma-separated when Fantrax lists more than one).

Data (all read-only):
  - getTeamRosters without a period = today's daily lineup (ACTIVE, RESERVE,
    MINORS, IR). MINORS and IR players are ignored.
  - getPlayerIds = each player's name, position and NHL team.
  - NHL schedule API = today's games (automation/blha/nhl.py).
  A player whose NHL team is missing, or does not appear anywhere in the
  NHL's 7-day schedule, is skipped rather than guessed at.

Each franchise gets at most one alert per day (state/lineup_alerts.json).

Modes:
  preview  print the alerts; no Discord, no state change
  test     post [TEST] alerts without notifying anyone; no state change
  live     post alerts for opted-in owners and record them
  --all-teams (preview/test only) also covers franchises with no opted-in
  owner, without a mention.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
for folder in (AUTOMATION, AUTOMATION / "competition", AUTOMATION / "wire"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import render  # noqa: E402  (competition/render.py)
import roster  # noqa: E402  (wire/roster.py: NHL team code aliases)
from blha import nhl  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook  # noqa: E402

STATE_PATH = ROOT / "state" / "lineup_alerts.json"
DEFAULT_WEBHOOK = "BLHA_WEBHOOK_LINEUP_ALERTS"
FORWARDS = {"C", "LW", "RW", "F"}
LINEUP = ("ACTIVE", "RESERVE")


@dataclass
class Entry:
    player_id: str
    name: str
    slot: str             # Fantrax roster position (the lineup slot when ACTIVE)
    positions: set[str]
    nhl_team: str
    game: nhl.Game | None = None


@dataclass
class TeamAlert:
    team_id: str
    team_name: str
    idle: list[Entry] = field(default_factory=list)   # ACTIVE, no game today
    bench: list[Entry] = field(default_factory=list)  # RESERVE, eligible, plays today


def positions_of(*values: Any) -> set[str]:
    found: set[str] = set()
    for value in values:
        for part in re.split(r"[,/ ]+", str(value or "").upper()):
            if part:
                found.add(part)
    return found


def can_fill(slot: str, positions: set[str]) -> bool:
    """Whether a reserve with these positions can take this lineup slot."""
    slot = slot.upper()
    if slot == "F":
        return bool(positions & FORWARDS)
    return slot in positions


def display_name(name: str) -> str:
    """Fantrax lists names as "Last, First"; show "First Last"."""
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(",", 1))
        return f"{first} {last}"
    return name


def player_directory(players: dict[str, Any]) -> dict[str, dict[str, Any]]:
    directory: dict[str, dict[str, Any]] = {}
    for key, raw in (players or {}).items():
        if isinstance(raw, dict):
            directory[str(key)] = raw
            if raw.get("fantraxId"):
                directory[str(raw["fantraxId"])] = raw
    return directory


def todays_games(games: list[nhl.Game], today: date) -> tuple[dict[str, nhl.Game], set[str]]:
    """(team -> today's game, every team code in the fetched schedule)."""
    playing = {roster.normalize_team(team): game for team, game in nhl.games_on(games, today).items()}
    known = {roster.normalize_team(team) for g in nhl.regular_season(games) for team in g.teams}
    return playing, known


def find_alerts(
    rosters: dict[str, Any],
    players: dict[str, Any],
    playing: dict[str, nhl.Game],
    known_teams: set[str],
    now: datetime,
) -> list[TeamAlert]:
    directory = player_directory(players)
    block = rosters.get("rosters") if isinstance(rosters, dict) else None
    alerts: list[TeamAlert] = []
    for team_id, team in (block or {}).items():
        if not isinstance(team, dict):
            continue
        idle: list[Entry] = []
        bench: list[Entry] = []
        for item in team.get("rosterItems") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            if status not in LINEUP:
                continue
            player_id = str(item.get("id") or "")
            info = directory.get(player_id) or {}
            nhl_team = roster.normalize_team(info.get("team"))
            if nhl_team not in known_teams:
                continue  # unknown or unmatched NHL team: never guess
            game = playing.get(nhl_team)
            entry = Entry(
                player_id=player_id,
                name=display_name(str(info.get("name") or player_id)),
                slot=str(item.get("position") or "").upper(),
                positions=positions_of(item.get("position"), info.get("position")),
                nhl_team=nhl_team,
                game=game,
            )
            if status == "ACTIVE" and game is None:
                idle.append(entry)
            elif status == "RESERVE" and game is not None and (game.start is None or game.start > now):
                bench.append(entry)
        options = [b for b in bench if any(can_fill(i.slot, b.positions) for i in idle)]
        stuck = [i for i in idle if any(can_fill(i.slot, b.positions) for b in options)]
        if stuck and options:
            alerts.append(TeamAlert(str(team_id), str(team.get("teamName") or team_id), stuck, options))
    return alerts


# --- Owners (opt-in) ----------------------------------------------------------

def owner_ids(league: dict[str, Any]) -> dict[str, str]:
    """league.yaml ``owners``: lowercased team name/ID -> Discord user ID."""
    owners: dict[str, str] = {}
    for key, value in (league.get("owners") or {}).items():
        user = str(value or "").strip()
        if re.fullmatch(r"\d{15,21}", user):
            owners[str(key).strip().lower()] = user
    return owners


def owner_for(alert: TeamAlert, owners: dict[str, str]) -> str:
    return owners.get(alert.team_id.lower()) or owners.get(alert.team_name.lower()) or ""


# --- Discord ------------------------------------------------------------------

def _slot_label(positions: set[str]) -> str:
    order = ["C", "LW", "RW", "F", "D", "G"]
    return "/".join(p for p in order if p in positions) or "?"


def alert_payload(ctx: render.Context, alert: TeamAlert, user_id: str, *, notify: bool) -> dict[str, Any]:
    idle = "\n".join(f"{e.slot} — {e.name} ({e.nhl_team})" for e in alert.idle)
    bench = "\n".join(
        f"{_slot_label(e.positions)} — {e.name} ({e.nhl_team}"
        + (f", <t:{int(e.game.start.timestamp())}:t>" if e.game and e.game.start else "")
        + ")"
        for e in alert.bench
    )
    fields = [
        {"name": "In your lineup, no game today", "value": render._clip(idle), "inline": False},
        {"name": "On your bench, playing today", "value": render._clip(bench), "inline": False},
    ]
    note = (
        "*A starter has no NHL game today while an eligible bench player does. "
        "Players lock about one minute before their own game (5.3).*"
    )
    payload = render._payload(ctx, f"Lineup Alert — {alert.team_name}", f"{render._header(ctx)}\n\n{note}", fields,
                              "LINEUP ALERT", source="FANTRAX + NHL SCHEDULE DATA")
    if user_id:
        payload["content"] = f"<@{user_id}>"
        payload["allowed_mentions"] = {"parse": [], "users": [user_id] if notify else []}
    return payload


# --- Run ----------------------------------------------------------------------

def alerted_today(state: dict[str, Any], today: date) -> set[str]:
    if state.get("date") != today.isoformat():
        return set()
    return {str(t) for t in state.get("alerted") or []}


def run(
    mode: str,
    all_teams: bool = False,
    *,
    now: datetime | None = None,
    league: dict[str, Any] | None = None,
    fx: Any = None,
    nhl_get: Any = None,
) -> int:
    cfg = league or load_league()
    tz: ZoneInfo = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(tz).date()
    settings = cfg.get("lineup_alerts") or {}
    secret = str(settings.get("webhook") or DEFAULT_WEBHOOK)
    owners = owner_ids(cfg)
    include_all = all_teams and mode != "live"
    print(f"BLHA LINEUP ALERTS mode={mode.upper()} date={today} opted_in_owners={len(owners)} all_teams={include_all}")

    if not owners and not include_all:
        print("RESULT: no owners have opted in (league.yaml owners); nothing to check")
        return 0

    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Lineup-Alerts/2.0")
    rosters = fx.rosters()
    players = fx.player_ids()
    games = nhl.fetch_schedule(today, today, tz, nhl_get)
    playing, known = todays_games(games, today)
    print(f"FANTRAX daily lineup period={rosters.get('period')} NHL teams playing today={len(playing)}")
    if not known:
        print("NOTE    the NHL schedule has no regular-season games in the next 7 days; nothing to check")
        return 0

    ctx = render.Context(
        league_name=str(fx.league_info().get("leagueName") or ""),
        season_label=str(cfg.get("season_label") or ""),
        color=color_value(cfg.get("color")),
        test=(mode == "test"),
    )
    state = load_json(STATE_PATH, {}) if mode == "live" else {}
    done = alerted_today(state, today)

    errors = sent = 0
    for alert in find_alerts(rosters, players, playing, known, now):
        user = owner_for(alert, owners)
        label = f"{alert.team_name}: {len(alert.idle)} idle, {len(alert.bench)} bench option(s)"
        if not user and not include_all:
            print(f"SKIP    {label} (owner has not opted in)")
            continue
        if alert.team_id in done:
            print(f"SKIP    {label} (already alerted today)")
            continue
        payload = alert_payload(ctx, alert, user, notify=(mode == "live"))
        if mode == "preview":
            print(f"PREVIEW {label}:\n{json.dumps(payload, indent=2)}")
            continue
        ok, detail, _ = send_discord_webhook(secret, payload)
        if not ok:
            print(f"ERROR   {label}: {detail}")
            errors += 1
            continue
        sent += 1
        print(f"POSTED  {label}")
        if mode == "live":
            done.add(alert.team_id)
            save_json(STATE_PATH, {"date": today.isoformat(), "alerted": sorted(done), "updated_at": now.isoformat()})

    print(f"SUMMARY sent={sent} errors={errors}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--all-teams", action="store_true",
                        help="Preview/test: include franchises with no opted-in owner (never mentioned)")
    args = parser.parse_args()
    try:
        return run(args.mode, args.all_teams)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
