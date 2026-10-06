#!/usr/bin/env python3
"""BLHA Starting Goalies: one live message per game day in #game-day.

During the regular season and playoffs the scheduler runs this several times
a day (automation/scheduler/schedule.yaml). The first run of the day posts a
"Starting Goalies" message listing every NHL game tonight with each team's
expected starter and how firm that report is:

  Confirmed    the team or a beat reporter has said so
  Likely       expected, not yet announced
  Unconfirmed  no report yet

Later runs edit that same message (edits are silent, nobody is notified) as
reports firm up, until the last game of the night starts. Goalies on a BLHA
roster are tagged with their BLHA team, and a short list at the bottom shows
rostered goalies whose NHL team plays tonight but who are not the listed
starter. Goalie starts count against the weekly cap, so this helps with
daily lineups (9.1). It is information only: Fantrax decides what counts.

Data (all read-only):
  - Daily Faceoff's starting goalies page for the day
    (https://www.dailyfaceoff.com/starting-goalies/YYYY-MM-DD). The page
    carries its data as JSON in the Next.js ``__NEXT_DATA__`` script; the
    shape was captured on 2026-10-06 (tests/fixtures). robots.txt allows it.
  - Fantrax getTeamRosters + getPlayerIds, for the BLHA tags (wire/roster.py
    matching: a name is only tagged when it identifies one player).

Modes:
  preview  print the message; no Discord, no state change
  test     post a new [TEST] message; no state change
  live     post or edit today's message and record it
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
for folder in (AUTOMATION, AUTOMATION / "competition", AUTOMATION / "wire"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import render  # noqa: E402  (competition/render.py)
import roster  # noqa: E402  (wire/roster.py)
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook, upsert_discord_message  # noqa: E402

STATE_PATH = ROOT / "state" / "starting_goalies.json"
DEFAULT_WEBHOOK = "BLHA_WEBHOOK_GAME_DAY"
DEFAULT_POST_FROM = "11:00"
PAGE_URL = "https://www.dailyfaceoff.com/starting-goalies/{day}"
USER_AGENT = "Mozilla/5.0 (compatible; BLHA-Starting-Goalies/1.0; +https://github.com/beer-league-hockey-association/blha-assets)"
SOURCE = "DAILY FACEOFF DATA"

# Daily Faceoff team slugs -> Fantrax NHL team codes (wire/roster.py uses the same codes).
TEAM_CODES = {
    "anaheim-ducks": "ANA", "boston-bruins": "BOS", "buffalo-sabres": "BUF", "calgary-flames": "CGY",
    "carolina-hurricanes": "CAR", "chicago-blackhawks": "CHI", "colorado-avalanche": "COL",
    "columbus-blue-jackets": "CBJ", "dallas-stars": "DAL", "detroit-red-wings": "DET",
    "edmonton-oilers": "EDM", "florida-panthers": "FLA", "los-angeles-kings": "LAK",
    "minnesota-wild": "MIN", "montreal-canadiens": "MTL", "nashville-predators": "NSH",
    "new-jersey-devils": "NJD", "new-york-islanders": "NYI", "new-york-rangers": "NYR",
    "ottawa-senators": "OTT", "philadelphia-flyers": "PHI", "pittsburgh-penguins": "PIT",
    "san-jose-sharks": "SJS", "seattle-kraken": "SEA", "st-louis-blues": "STL",
    "tampa-bay-lightning": "TBL", "toronto-maple-leafs": "TOR", "utah-mammoth": "UTA",
    "utah-hockey-club": "UTA", "vancouver-canucks": "VAN", "vegas-golden-knights": "VGK",
    "washington-capitals": "WSH", "winnipeg-jets": "WPG",
}
STATUSES = ("Confirmed", "Likely", "Unconfirmed")


@dataclass
class Start:
    team: str          # Fantrax NHL team code ("" if the slug is unknown)
    team_name: str
    goalie: str        # "" when Daily Faceoff lists nobody yet
    status: str        # one of STATUSES
    owner: str = ""    # BLHA team that rosters this goalie


@dataclass
class Game:
    start: datetime | None
    away: Start
    home: Start

    @property
    def label(self) -> str:
        return f"{self.away.team or self.away.team_name} at {self.home.team or self.home.team_name}"


# --- Daily Faceoff --------------------------------------------------------------

def _status(value: Any) -> str:
    text = str(value or "").strip().title()
    return text if text in ("Confirmed", "Likely") else "Unconfirmed"


def _team_code(slug: Any, name: Any) -> str:
    slug_text = str(slug or "").strip().lower()
    if slug_text in TEAM_CODES:
        return TEAM_CODES[slug_text]
    guess = re.sub(r"[^a-z]+", "-", str(name or "").lower()).strip("-")
    return TEAM_CODES.get(guess, "")


def _when(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_page(html: str, day: date) -> list[Game]:
    """Games for ``day`` from the page's __NEXT_DATA__ JSON.

    Returns [] when the page is for another day (Daily Faceoff falls back to
    the current day for dates it has nothing for). Raises ValueError when the
    page no longer has the expected structure, so a site change is noticed.
    """
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError("Daily Faceoff page has no __NEXT_DATA__ script (site layout changed?)")
    props = (json.loads(match.group(1)).get("props") or {}).get("pageProps") or {}
    rows = props.get("data")
    if not isinstance(rows, list):
        raise ValueError("Daily Faceoff __NEXT_DATA__ has no pageProps.data list (site layout changed?)")
    if str(props.get("date") or "") != day.isoformat():
        return []
    games: list[Game] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sides = {}
        for side in ("away", "home"):
            sides[side] = Start(
                team=_team_code(row.get(f"{side}TeamSlug"), row.get(f"{side}TeamName")),
                team_name=str(row.get(f"{side}TeamName") or ""),
                goalie=str(row.get(f"{side}GoalieName") or "").strip(),
                status=_status(row.get(f"{side}NewsStrengthName")),
            )
        games.append(Game(_when(row.get("dateGmt")), sides["away"], sides["home"]))
    games.sort(key=lambda g: (g.start or datetime.max.replace(tzinfo=timezone.utc), g.label))
    return games


def http_get(url: str) -> str:
    import requests

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response.text


def fetch(day: date, get: Callable[[str], str] | None = None) -> list[Game]:
    return parse_page((get or http_get)(PAGE_URL.format(day=day.isoformat())), day)


# --- BLHA rosters ---------------------------------------------------------------

def tag_owners(games: list[Game], index: roster.RosterIndex | None) -> int:
    """Set Start.owner for rostered goalies. Returns how many were tagged."""
    if index is None:
        return 0
    tagged = 0
    for game in games:
        for side in (game.away, game.home):
            if not side.goalie:
                continue
            player = index.match(side.goalie, side.team, "G")
            if player and player.group == "G":
                side.owner = player.owner_name
                tagged += 1
    return tagged


def not_starting(games: list[Game], index: roster.RosterIndex | None, now: datetime) -> list[str]:
    """Rostered goalies whose NHL team plays tonight but who are not the listed starter.

    Only for games that have not started, and only when the listed starter is
    Confirmed or Likely (an unconfirmed guess is not worth flagging).
    """
    if index is None:
        return []
    starters: dict[str, Start] = {}
    for game in games:
        if game.start is not None and game.start <= now:
            continue
        for side in (game.away, game.home):
            if side.team and side.goalie and side.status in ("Confirmed", "Likely"):
                starters[side.team] = side
    lines: list[str] = []
    for players in index.by_name.values():
        for p in players:
            if p.group != "G" or not p.owner_id or p.team not in starters:
                continue
            starter = starters[p.team]
            if roster.normalize_player_name(p.name) == roster.normalize_player_name(starter.goalie):
                continue
            lines.append(f"**{p.owner_name}** — {roster.display_name(p)} ({p.team}): "
                         f"{starter.goalie} is {starter.status.lower()} to start")
    return sorted(lines)


def load_index(fx: Any) -> roster.RosterIndex | None:
    try:
        rosters = fx.rosters()
        players = fx.player_ids()
    except Exception as exc:
        print(f"ROSTER TAGS WARNING: Fantrax read failed, posting without BLHA tags: {exc}")
        return None
    index = roster.build_index(rosters, players)
    print(f"ROSTER TAGS: {len(index.rostered_names)} rostered players indexed")
    return index


# --- Discord --------------------------------------------------------------------

def _line(side: Start) -> str:
    who = side.goalie or "No report yet"
    text = f"**{side.team or side.team_name}** {who} — {side.status}"
    if side.owner:
        text += f" • *{side.owner}*"
    return text


def summary(games: list[Game]) -> tuple[int, int]:
    total = 2 * len(games)
    confirmed = sum(side.status == "Confirmed" for g in games for side in (g.away, g.home))
    return confirmed, total


def payload(ctx: render.Context, games: list[Game], day: date, benched: list[str], now: datetime) -> dict[str, Any]:
    confirmed, total = summary(games)
    url = PAGE_URL.format(day=day.isoformat())
    fields = []
    for game in games:
        when = f"<t:{int(game.start.timestamp())}:t>" if game.start else "Time TBA"
        if game.start is not None and game.start <= now:
            when += " • under way"
        fields.append({"name": game.label, "value": render._clip(f"{when}\n{_line(game.away)}\n{_line(game.home)}"),
                       "inline": False})
    if benched:
        fields.append({"name": "BLHA GOALIES NOT STARTING TONIGHT", "value": render._clip("\n".join(benched)),
                       "inline": False})
    description = (
        f"{render._header(ctx)}\n\n"
        f"**{confirmed} of {total} starters confirmed** • updated <t:{int(now.timestamp())}:R>\n"
        "*Confirmed: announced by the team or a beat reporter. Likely: expected, not announced. "
        "Unconfirmed: no report yet. This message updates until the last game starts. "
        f"Goalies on a BLHA roster show their BLHA team.* Source: [Daily Faceoff]({url})"
    )
    title = f"Starting Goalies — {day.strftime('%A, %B')} {day.day}"
    return render._payload(ctx, title, description, fields, "STARTING GOALIES", source=SOURCE)


def fingerprint(games: list[Game], benched: list[str]) -> str:
    rows = [[g.label, g.start.isoformat() if g.start else "",
             [(s.goalie, s.status, s.owner) for s in (g.away, g.home)]] for g in games]
    return hashlib.sha256(json.dumps([rows, benched]).encode()).hexdigest()[:16]


# --- Run ------------------------------------------------------------------------

def _post_from(settings: dict[str, Any]) -> time:
    text = str(settings.get("post_from") or DEFAULT_POST_FROM)
    hour, minute = (int(part) for part in text.split(":", 1))
    return time(hour, minute)


def run(
    mode: str,
    *,
    now: datetime | None = None,
    league: dict[str, Any] | None = None,
    fx: Any = None,
    get: Callable[[str], str] | None = None,
) -> int:
    cfg = league or load_league()
    tz: ZoneInfo = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    day = local.date()
    settings = cfg.get("starting_goalies") or {}
    secret = str(settings.get("webhook") or DEFAULT_WEBHOOK)
    print(f"BLHA STARTING GOALIES mode={mode.upper()} date={day} local_time={local:%H:%M}")

    if mode == "live" and local.time() < _post_from(settings):
        print(f"RESULT: before {_post_from(settings):%H:%M}; nothing to post yet")
        return 0

    games = fetch(day, get)
    if not games:
        print("RESULT: Daily Faceoff lists no NHL games today; nothing to post")
        return 0
    upcoming = [g for g in games if g.start is None or g.start > now]
    print(f"DAILY FACEOFF games={len(games)} not_started={len(upcoming)} confirmed={summary(games)[0]}/{summary(games)[1]}")

    state = load_json(STATE_PATH, {}) if mode == "live" else {}
    if state.get("date") != day.isoformat():
        state = {}
    if mode == "live" and not upcoming:
        print("RESULT: every game has started; today's message is final")
        return 0

    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Starting-Goalies/1.0")
    index = load_index(fx)
    tagged = tag_owners(games, index)
    benched = not_starting(games, index, now)
    print(f"BLHA TAGS starters_on_blha_rosters={tagged} rostered_not_starting={len(benched)}")
    try:
        league_name = str(fx.league_info().get("leagueName") or "")
    except Exception:
        league_name = ""
    ctx = render.Context(
        league_name=league_name,
        season_label=str(cfg.get("season_label") or ""),
        color=color_value(cfg.get("color")),
        test=(mode == "test"),
    )
    body = payload(ctx, games, day, benched, now)

    if mode == "preview":
        print(json.dumps(body, indent=2))
        return 0
    if mode == "test":
        ok, detail, _ = send_discord_webhook(secret, body)
        print(f"{'POSTED' if ok else 'ERROR'} test message: {detail}")
        return 0 if ok else 1

    fp = fingerprint(games, benched)
    if state.get("message_id") and fp == state.get("fingerprint"):
        print("UNCHANGED no new goalie reports since the last update")
        return 0
    ok, detail, new_id, how = upsert_discord_message(secret, body, state.get("message_id"))
    if not ok:
        print(f"ERROR   {detail}")
        return 1
    save_json(STATE_PATH, {"date": day.isoformat(), "message_id": new_id, "fingerprint": fp,
                           "updated_at": now.isoformat()})
    print(f"{how.upper():8} starting goalies for {day}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()
    try:
        return run(args.mode)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
