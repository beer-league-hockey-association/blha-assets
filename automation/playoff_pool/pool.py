#!/usr/bin/env python3
"""BLHA Playoff Pool: a free NHL playoff box pool for the owners, in 🏒│game-day.

Just for fun: no money and no effect on the fantasy league. The prize is the
Pool Shark role for the next season and a line in the league history
(automation/history/history.yaml, seasons.<year>.pool_shark).

The scheduler runs this at 07:45 and 19:45 only inside the NHL playoff window
(``when: nhl-playoffs`` in automation/scheduler/schedule.yaml). Each live run
does whatever is due, once:

  1. Boxes. When the NHL playoff bracket has all 16 teams, build the 10 boxes
     (boxes.py) from regular-season club stats, post them with the entry
     instructions and the pick deadline (the first puck drop of the playoffs),
     and save them to state/boxes.json, which the League Bot reads. If the
     NHL hasn't published the first game's time yet, a later run adds it to
     the same post (a silent edit).
  2. Standings. After the deadline, read every finished playoff game's
     boxscore (cached in state; the last two nights are re-read to pick up
     NHL scoring changes), score the picks in entries.yaml the BLHA way and
     post the standings once a morning (from standings_time), only when
     something changed.
  3. Final. When the Stanley Cup Final is decided and every game is final,
     post the final standings naming the Pool Shark, once.

Entries come only from automation/playoff_pool/entries.yaml (entries.py):
filled in by the Commissioner from DMs, or exported by the League Bot's
/pool export once it is live.

Modes:
  preview  print what would be posted; no Discord, no state change
  test     post [TEST] copies of the boxes (and standings, after the
           deadline); no state change
  live     do what is due and save state

``--year`` (preview and test only) runs against a past NHL playoffs, for
example ``--year 2025``, so the whole pool can be checked out of season.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
if str(AUTOMATION) not in sys.path:
    sys.path.insert(0, str(AUTOMATION))

from blha import nhl  # noqa: E402
from blha import nhl_playoffs  # noqa: E402
from blha.league import color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook, upsert_discord_message  # noqa: E402
from playoff_pool import boxes as bx  # noqa: E402
from playoff_pool import bracket, entries, posts, scoring  # noqa: E402
from playoff_pool.nhl_feed import Feed, season_id  # noqa: E402

STATE_PATH = ROOT / "state" / "pool.json"
BOXES_PATH = ROOT / "state" / "boxes.json"
PLAYOFF_GAME = 3
REFRESH_DAYS = 2   # boxscores from the last two nights are re-read for NHL scoring changes
MAX_WEEKS = 14     # weekly schedule reads; the playoffs last about nine weeks
DEADLINE_SEARCH = timedelta(days=27)


def playoff_year(day: date) -> int:
    """The NHL playoffs a date belongs to: spring of that year, or next spring from September."""
    return day.year if day.month <= 8 else day.year + 1


# --- NHL reads ---------------------------------------------------------------------

def scan_schedule(feed: Feed, first: date, last: date, tz: ZoneInfo) -> list[nhl.Game]:
    """Every game from ``first`` through ``last`` (local nights), one request per week."""
    found: dict[str, nhl.Game] = {}
    day = first
    for _ in range(MAX_WEEKS):
        if day > last:
            break
        raw = feed.schedule(day.isoformat())
        for game in nhl.parse_schedule(raw, tz):
            if game.night <= last:
                found[game.game_id] = game
        dates = nhl.schedule_dates(raw)
        day = max(day + timedelta(days=1), (dates[-1] + timedelta(days=1)) if dates else day + timedelta(days=7))
    return sorted(found.values(), key=lambda g: (g.night, g.start.isoformat() if g.start else "", g.game_id))


def first_puck_drop(feed: Feed, anchor: date, tz: ZoneInfo) -> datetime | None:
    """Start time of the first playoff game of the season ``anchor`` falls in (None if not published)."""
    raw = feed.schedule(anchor.isoformat())
    regular_end, _ = nhl_playoffs.season_dates(raw)
    start = regular_end or anchor - timedelta(days=7)
    games = scan_schedule(feed, start, start + DEADLINE_SEARCH, tz)
    starts = [g.start for g in games if g.game_type == PLAYOFF_GAME and g.start is not None]
    return min(starts) if starts else None


def build_boxes(feed: Feed, year: int, teams: list[str], settings: bx.Settings, now: datetime,
                current_rosters: bool) -> bx.Boxes:
    season = season_id(year)
    stats = {team: feed.club_stats(team, season) for team in teams}
    rosters = {team: (feed.roster(team) if current_rosters else None) for team in teams}
    log: list[str] = []
    if not current_rosters:
        log.append("past season: current-roster filter skipped")
    built = bx.build(year, season, teams, stats, rosters, settings, now, log)
    for line in log:
        print(f"BOXES NOTE: {line}")
    return built


@dataclass
class Scan:
    games: dict[str, Any]   # game id -> {"night", "final", "lines"}
    final_games: int
    pending: int            # started playoff games that are not final yet
    through: date | None    # latest night with a final game
    fetched: int


def update_games(feed: Feed, cached: dict[str, Any], boxes: bx.Boxes, now: datetime, tz: ZoneInfo) -> Scan:
    """Read the boxscores the standings need and return the updated cache."""
    games = {gid: g for gid, g in (cached or {}).items() if isinstance(g, dict)}
    if boxes.deadline is None:
        return Scan(games, 0, 0, None, 0)
    today = now.astimezone(tz).date()
    first = boxes.deadline.astimezone(tz).date()
    schedule = [g for g in scan_schedule(feed, first, today, tz) if g.game_type == PLAYOFF_GAME]
    keep = boxes.player_ids()
    pending = fetched = 0
    for game in schedule:
        if game.start is not None and game.start > now:
            continue
        old = games.get(game.game_id)
        if old and old.get("final") and game.night < today - timedelta(days=REFRESH_DAYS):
            continue
        state, lines = scoring.parse_boxscore(feed.boxscore(game.game_id))
        fetched += 1
        if state in scoring.FINAL_STATES:
            games[game.game_id] = {"night": game.night.isoformat(), "final": True,
                                   "lines": {str(pid): line for pid, line in sorted(lines.items()) if pid in keep}}
        else:
            pending += 1
    finals = [g for g in games.values() if g.get("final")]
    through = max((date.fromisoformat(g["night"]) for g in finals), default=None)
    return Scan(games, len(finals), pending, through, fetched)


# --- Standings -----------------------------------------------------------------------

def compute(boxes: bx.Boxes, parsed: entries.Parsed, games: dict[str, Any], eliminated: set[str]) -> list[scoring.Row]:
    goalie_box = boxes.boxes[-1]
    goalies = {p.id for p in goalie_box.players}
    totals = scoring.player_points(games, goalies)
    teams = {p.id: p.team for b in boxes.boxes for p in b.players}
    return scoring.standings(parsed.entries, goalie_box.number, totals, teams, eliminated)


def fingerprint(rows: list[scoring.Row], final_games: int) -> str:
    data = [final_games, [(r.owner, r.total, r.out) for r in rows]]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


def log_standings(rows: list[scoring.Row], boxes: bx.Boxes) -> None:
    for i, r in enumerate(rows, 1):
        best = boxes.player(r.picks.get(r.best_box, 0))
        print(f"  {i:>2}. {r.owner[:24]:<24} {scoring.fmt(r.total):>8}  goalie {scoring.fmt(r.goalie):>7}  "
              f"out {r.out}/{len(r.picks)}  best {best.name if best else '-'}")


def _clock(text: str) -> time:
    hour, minute = (int(part) for part in str(text).split(":", 1))
    return time(hour, minute)


# --- Run -------------------------------------------------------------------------------

def run(
    mode: str,
    *,
    now: datetime | None = None,
    year: int | None = None,
    league: dict[str, Any] | None = None,
    feed: Feed | None = None,
    entries_path: Path = entries.ENTRIES_PATH,
    state_path: Path = STATE_PATH,
    boxes_path: Path = BOXES_PATH,
) -> int:
    cfg = league or load_league()
    tz = timezone_of(cfg)
    settings = bx.Settings.from_cfg(cfg.get("playoff_pool"))
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    current = playoff_year(local.date())
    year = year or current
    if mode == "live" and year != current:
        print(f"ERROR: --year is for preview and test runs only (live runs use {current})")
        return 1
    feed = feed or Feed()
    live = mode == "live"
    print(f"BLHA PLAYOFF POOL mode={mode.upper()} year={year} local_time={local:%Y-%m-%d %H:%M}")

    state = load_json(state_path, {})
    if state.get("year") != year:
        state = {"year": year}
    saved = load_json(boxes_path, {})
    boxes = bx.Boxes.from_dict(saved) if saved.get("year") == year and saved.get("boxes") else None
    if boxes is None and state.get("boxes_message_id"):
        state.pop("boxes_message_id", None)

    series = bracket.parse(feed.bracket(year))
    if boxes is None:
        teams = bracket.field(series)
        if not bracket.field_set(series):
            print(f"RESULT: the {year} NHL playoff field is not set yet ({len(teams)} of {bracket.FIELD_SIZE} teams)")
            return 0
        boxes = build_boxes(feed, year, teams, settings, now, current_rosters=(year == current))
        print(f"BOXES built from {len(teams)} teams: {boxes.rules.get('eligible_skaters')} eligible skaters, "
              f"{len(boxes.boxes[-1].players)} goalies")

    if boxes.deadline is None:
        anchor = local.date() if year == current else date(year, 4, 10)
        boxes.deadline = first_puck_drop(feed, anchor, tz)
    print(f"DEADLINE {boxes.deadline.astimezone(tz).strftime('%a %b %d %H:%M %Z') if boxes.deadline else 'not published yet'}"
          f"{' (locked)' if boxes.locked(now) else ''}")

    ctx = posts.context(year, color_value(cfg.get("color")), test=(mode == "test"))
    secret = settings.webhook
    status = 0

    # 1. The boxes post.
    boxes_body = posts.boxes_payload(ctx, boxes, settings)
    deadline_key = boxes.deadline.isoformat() if boxes.deadline else ""
    if mode == "preview":
        print(json.dumps(boxes_body, indent=2, ensure_ascii=False))
    elif mode == "test":
        ok, detail, _ = send_discord_webhook(secret, boxes_body)
        print(f"{'POSTED' if ok else 'ERROR'} test boxes: {detail}")
        status |= 0 if ok else 1
    elif not state.get("boxes_message_id") or state.get("boxes_deadline") != deadline_key:
        ok, detail, message_id, how = upsert_discord_message(secret, boxes_body, state.get("boxes_message_id"))
        if not ok:
            print(f"ERROR   boxes post: {detail}")
            return 1
        state.update(boxes_message_id=message_id, boxes_deadline=deadline_key)
        print(f"{how.upper():8} boxes post")
    if live:
        save_json(boxes_path, boxes.as_dict())

    parsed = entries.load(entries_path, boxes, tz)
    for problem in parsed.problems:
        print(f"ENTRY WARNING: {problem}")
    print(f"ENTRIES {len(parsed.entries)} valid in {entries_path.name}")

    if not boxes.locked(now):
        print("RESULT: picks are open until the first puck drop; no standings yet")
        return _finish(live, state, state_path, now, status)
    if live and state.get("final_posted"):
        print("RESULT: the final post is already out; the pool is over")
        return _finish(live, state, state_path, now, status)

    # 2. Scores.
    scan = update_games(feed, state.get("games") or {}, boxes, now, tz)
    state["games"] = scan.games
    champion = bracket.champion(series)
    out = bracket.eliminated(series)
    print(f"GAMES final={scan.final_games} pending={scan.pending} boxscores_read={scan.fetched} "
          f"eliminated={','.join(sorted(out)) or 'none'} champion={champion or 'not yet'}")
    rows = compute(boxes, parsed, scan.games, out)
    log_standings(rows, boxes)
    if not rows:
        print("RESULT: no valid entries in entries.yaml; nothing to post")
        return _finish(live, state, state_path, now, status)
    if not scan.final_games:
        print("RESULT: no playoff game has finished yet")
        return _finish(live, state, state_path, now, status)

    # 3. The final post, or today's standings.
    if champion and not scan.pending:
        body = posts.final_payload(ctx, boxes, rows, scan.final_games, bracket.team_name(series, champion))
        label = "final"
    else:
        posted = state.get("standings") or {}
        fp = fingerprint(rows, scan.final_games)
        if live and local.time() < _clock(settings.standings_time):
            print(f"RESULT: standings post after {settings.standings_time}")
            return _finish(live, state, state_path, now, status)
        if live and posted.get("on") == local.date().isoformat():
            print("RESULT: today's standings are already posted")
            return _finish(live, state, state_path, now, status)
        if live and posted.get("fingerprint") == fp:
            print("RESULT: no change since the last standings post")
            return _finish(live, state, state_path, now, status)
        body = posts.standings_payload(ctx, boxes, rows, scan.final_games, scan.through, local.date())
        label = "standings"

    if mode == "preview":
        print(json.dumps(body, indent=2, ensure_ascii=False))
        return status
    ok, detail, _ = send_discord_webhook(secret, body)
    print(f"{'POSTED' if ok else 'ERROR'} {'test ' if mode == 'test' else ''}{label}: {detail}")
    if not ok:
        return _finish(live, state, state_path, now, 1)
    if live and label == "final":
        state["final_posted"] = True
        print(f"POOL SHARK {rows[0].owner}: give them the Pool Shark role and add "
              f"pool_shark to history.yaml for the matching Season")
    elif live:
        state["standings"] = {"on": local.date().isoformat(), "fingerprint": fingerprint(rows, scan.final_games)}
    return _finish(live, state, state_path, now, status)


def _finish(live: bool, state: dict[str, Any], path: Path, now: datetime, status: int) -> int:
    if live:
        state["updated_at"] = now.isoformat()
        save_json(path, state)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--year", default="", help="NHL playoff year for preview/test runs, e.g. 2025")
    args = parser.parse_args()
    year = None
    if str(args.year).strip():
        if not str(args.year).strip().isdigit() or not 2010 <= int(args.year) <= 2100:
            print(f"ERROR: --year must be a year such as 2025, not {args.year!r}")
            return 1
        year = int(args.year)
    try:
        return run(args.mode, year=year)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
