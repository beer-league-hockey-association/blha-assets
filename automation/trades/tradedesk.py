#!/usr/bin/env python3
"""BLHA Trade Desk: a report card and poll for every trade, revisits, and the deadline-day tracker.

Every run (every 30 minutes, every 15 on trade-deadline day; see
automation/scheduler/schedule.yaml) compares Fantrax's rosters and draft-pick
ownership with the last saved copy (trade_detect.py). Players and picks that
moved straight from one BLHA team to another in that window are one trade;
free-agent adds and drops are ignored. The first run for a league and season
only saves a baseline.

1. TRADE REPORT CARD (💬│trade-discussion, secret BLHA_WEBHOOK_TRADE_DISCUSSION):
   one message per trade listing what each side received, with a native
   Discord poll "Who won the trade?" (each team, plus Even) open 72 hours. The
   vote is for fun and never affects the trade (Article XI). The message id is
   saved. A trade that exactly undoes a trade from the last 14 days (the
   Commissioner reversing it) is not posted.
2. TRADE REVISIT at 6 and 12 months (same channel): for each side, the BLHA
   fantasy points its players have produced in NHL regular-season games since
   the trade (trade_points.py), wherever they have played since; picks show
   "not yet used" or the player drafted with them (league archive); and the
   final poll result, read back from Discord. It never suggests a trade should
   change.
3. BLHA TRADECENTRE (📢│announcements, secret BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS):
   on trade-deadline day (Sunday of the deadline Week, 11:59 PM ET; deadline
   from blha.season.trade_deadline, the same helper the League Bot uses) one
   live message is posted at 9:00 AM ET and edited every run until the
   deadline: a countdown, every trade seen that day and the number of trades
   this season. The first run after the deadline turns it into the final
   "Deadline passed — N trades today".

A missing webhook secret skips that post with a clear log line; the run does
not fail. Posts are text and links only.

Modes:
  preview  read Fantrax, print what would be posted; no Discord, no state change
           (--at "2027-02-21T21:00" previews another moment, for example deadline day)
  test     post one [TEST] sample (--item card, revisit or tracker); no state change
  live     detect, post and save state
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
for folder in (AUTOMATION, ROOT):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import discord_webhook as dw  # noqa: E402
import trade_detect as td  # noqa: E402
import trade_points as tp  # noqa: E402
import trade_render as tr  # noqa: E402
from blha import season as cal  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import load_json, load_league, save_json, timezone_of  # noqa: E402

STATE_PATH = ROOT / "state" / "tradedesk.json"
DISCUSSION_SECRET = "BLHA_WEBHOOK_TRADE_DISCUSSION"
ANNOUNCEMENTS_SECRET = "BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS"
TRACKER_OPENS = time(9, 0)
FINAL_GRACE = timedelta(hours=6)       # the final tally still posts if the runs right after the deadline were missed
REVISIT_MONTHS = (6, 12)
REVISIT_AT = time(12, 0)               # local time a revisit is posted on its day
REVISIT_GIVE_UP = timedelta(days=3)    # if the NHL can't be read, post with what is readable after this
MAX_REVISITS_PER_RUN = 3
CARD_RETRY = timedelta(hours=6)        # a report card that failed to post is retried this long
CONFIRM_DELAY = 5                      # seconds before re-reading Fantrax to confirm a trade


# --- configuration ---------------------------------------------------------------

def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("trade_desk") or {}


def secret(cfg: dict[str, Any], key: str) -> str:
    default = {"discussion": DISCUSSION_SECRET, "announcements": ANNOUNCEMENTS_SECRET}[key]
    return str((settings(cfg).get("webhooks") or {}).get(key) or default)


def has_secret(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def poll_hours(cfg: dict[str, Any]) -> int:
    return int(settings(cfg).get("poll_hours") or tr.POLL_HOURS)


def is_test_label(label: Any) -> bool:
    return "test" in str(label or "").lower().split()


# --- time ------------------------------------------------------------------------

def when(iso: Any) -> datetime:
    moment = datetime.fromisoformat(str(iso))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def revisit_due(trade: dict[str, Any], months: int, tz: ZoneInfo) -> datetime:
    """Noon local time, ``months`` calendar months after the day the trade was seen."""
    seen = when(trade["at"]).astimezone(tz).date()
    return datetime.combine(add_months(seen, months), REVISIT_AT, tzinfo=tz).astimezone(timezone.utc)


def deadline_day_start(deadline: datetime, tz: ZoneInfo) -> datetime:
    return datetime.combine(deadline.astimezone(tz).date(), time(0, 0), tzinfo=tz).astimezone(timezone.utc)


def tracker_stage(deadline: datetime | None, now: datetime, tz: ZoneInfo) -> str:
    """off (not deadline day or long past), waiting (before 9:00 AM), live (until the deadline), final."""
    if deadline is None:
        return "off"
    day = deadline.astimezone(tz).date()
    opens = datetime.combine(day, TRACKER_OPENS, tzinfo=tz).astimezone(timezone.utc)
    if now < deadline_day_start(deadline, tz) or now > deadline + FINAL_GRACE:
        return "off"
    if now < opens:
        return "waiting"
    return "live" if now < deadline else "final"


# --- output ----------------------------------------------------------------------

def show(payload: dict[str, Any]) -> None:
    """The message as plain text, for logs and preview."""
    for e in payload.get("embeds") or []:
        print(f"  # {e.get('title')}")
        for line in str(e.get("description") or "").splitlines():
            print(f"    {line}")
        for f in e.get("fields") or []:
            print(f"    [{f['name']}]")
            for line in str(f["value"]).splitlines():
                print(f"      {line}")
        print(f"    -- {(e.get('footer') or {}).get('text')}")
    p = payload.get("poll")
    if p:
        answers = " / ".join(a["poll_media"]["text"] for a in p["answers"])
        print(f"    POLL: {p['question']['text']} {answers} ({p['duration']} hours)")


# --- 1. detection -----------------------------------------------------------------

def player_info(fx: Any, trades: list[dict[str, Any]]) -> None:
    """Name, position and NHL team of every player in the trades (Fantrax getPlayerIds)."""
    wanted = {a.split(":", 1)[1] for t in trades for side in t["received"].values() for a in side
              if a.startswith("player:")}
    if not wanted:
        return
    try:
        ids = fx.player_ids()
    except Exception as exc:  # noqa: BLE001 - names are nice to have; ids still identify players
        print(f"WARNING: could not read Fantrax player names ({exc.__class__.__name__}).")
        ids = {}
    for t in trades:
        players = t.setdefault("players", {})
        for side in t["received"].values():
            for a in side:
                if a.startswith("player:"):
                    pid = a.split(":", 1)[1]
                    row = ids.get(pid) if isinstance(ids, dict) else None
                    row = row if isinstance(row, dict) else {}
                    players[pid] = {k: row.get(k) for k in ("name", "position", "team") if row.get(k)}


def detect_trades(state: dict[str, Any], fx: Any, cfg: dict[str, Any], season: int, now: datetime,
                  sleep: Callable[[float], Any] = clock.sleep) -> list[dict[str, Any]]:
    """New trades since the saved snapshot (also updates the snapshot in state)."""
    league = str(cfg["league_id"])
    rosters, picks, names = td.read_snapshot(fx)
    snap = state.get("snapshot") or {}
    last_check = state.get("updated_at") or snap.get("at")
    state["updated_at"] = now.isoformat()   # the only change on a quiet run, which the state save skips
    if snap.get("league_id") != league or snap.get("season") != season or not isinstance(snap.get("rosters"), dict):
        print(f"No saved snapshot for league {league} season {season} yet: saving a baseline. No trades reported this run.")
        state["snapshot"] = {"league_id": league, "season": season, "rosters": rosters, "picks": picks or {},
                             "at": now.isoformat()}
        return []
    prev_picks = snap.get("picks") if isinstance(snap.get("picks"), dict) and snap.get("picks") else None
    found = td.detect(snap["rosters"], rosters, prev_picks, picks)
    if found:
        # Rosters and picks are two separate reads; read both again so a trade
        # processed between them is seen whole, not as two trades.
        sleep(CONFIRM_DELAY)
        rosters, again, names2 = td.read_snapshot(fx)
        picks = again if again is not None else picks
        names = {**names, **names2}
        found = td.detect(snap["rosters"], rosters, prev_picks, picks)
    trades: list[dict[str, Any]] = []
    stamp = now.strftime("%Y%m%dT%H%M%S")
    for i, t in enumerate(found, 1):
        undone = td.reversal_of(t, state.get("trades") or [], now)
        if undone:
            undone["reversed"] = now.isoformat()
            print(f"REVERSAL: this undoes trade {undone['id']} ({' and '.join(undone['names'].get(x, x) for x in undone['teams'])}); "
                  "no report card, and its revisits are cancelled.")
            continue
        record = {
            "id": f"{season}-{stamp}-{i}", "season": season, "league_id": league,
            "test": is_test_label(cfg.get("season_label")),
            "at": now.isoformat(), "since": last_check,
            "teams": t["teams"], "received": t["received"], "sent": t["sent"],
            "names": {k: v for k, v in sorted(names.items())},
            "card": "pending", "revisits": {},
        }
        if t.get("one_sided"):
            record["one_sided"] = True
        trades.append(record)
    player_info(fx, trades)
    cur = {"league_id": league, "season": season, "rosters": rosters,
           "picks": picks if picks is not None else (prev_picks or {})}
    if any(snap.get(k) != v for k, v in cur.items()):
        state["snapshot"] = {**cur, "at": now.isoformat()}   # "at": when rosters or picks last changed
    state.setdefault("trades", []).extend(trades)
    return trades


# --- 1. report cards --------------------------------------------------------------

def post_cards(state: dict[str, Any], cfg: dict[str, Any], now: datetime, mode: str) -> int:
    """Post every report card not posted yet (new trades, or a recent failed post). Returns errors."""
    name, errors = secret(cfg, "discussion"), 0
    for t in state.get("trades") or []:
        if t.get("card") != "pending" or t.get("reversed"):
            continue
        if now - when(t["at"]) > CARD_RETRY:
            t["card"] = "gave up"
            print(f"GAVE UP report card {t['id']}: it could not be posted within {CARD_RETRY}.")
            continue
        payload = tr.report_card(t, cfg, poll_hours=poll_hours(cfg))
        print(f"REPORT CARD {t['id']}:")
        show(payload)
        if mode != "live":
            continue
        if not has_secret(name):
            t["card"] = "skipped"
            print(f"SKIP report card: the {name} secret is not set (💬│trade-discussion webhook). "
                  "Add it in GitHub > Settings > Secrets and variables > Actions; later trades will post.")
            continue
        ok, detail, message_id = dw.send_discord_webhook(name, payload)
        with_poll = True
        if not ok and detail.startswith("Discord returned 400"):
            print(f"POLL WARNING: Discord refused the message with its poll ({detail}). Posting it without the poll.")
            with_poll = False
            ok, detail, message_id = dw.send_discord_webhook(name, tr.report_card(t, cfg, with_poll=False))
        if ok:
            t.update({"card": "posted", "message_id": message_id, "poll": with_poll, "posted_at": now.isoformat()})
            print(f"POSTED report card {t['id']} (message {message_id})")
        else:
            errors += 1
            print(f"DELIVERY ERROR report card {t['id']}: {detail} (will retry next run)")
    return errors


# --- 1. revisits ------------------------------------------------------------------

def due_revisits(state: dict[str, Any], cfg: dict[str, Any], tz: ZoneInfo, now: datetime) -> list[tuple[dict[str, Any], int, datetime]]:
    test_now = is_test_label(cfg.get("season_label"))
    out = []
    for t in state.get("trades") or []:
        if t.get("reversed") or (t.get("test") and not test_now):
            continue  # a TEST-league trade is never revisited in the real league
        for months in REVISIT_MONTHS:
            due = revisit_due(t, months, tz)
            if str(months) not in (t.get("revisits") or {}) and now >= due:
                out.append((t, months, due))
    out.sort(key=lambda x: x[2])
    return out


def history(archive_root: Any = None, cfg: dict[str, Any] | None = None) -> Any:
    """The league archive (for what a traded pick became), or None if it can't be read."""
    try:
        from history.context import LeagueHistory

        return LeagueHistory(archive_root, league=cfg)
    except Exception as exc:  # noqa: BLE001 - picks then show as not yet used / unknown
        print(f"WARNING: could not read the league archive ({exc.__class__.__name__}); picks show without draft results.")
        return None


def pick_text(trade: dict[str, Any], asset: str, hist: Any, today: date) -> str:
    """'2028 1st (not yet used)' or '2028 1st: Connor Bedard (1.03)'."""
    key = asset.split(":", 1)[1]
    parsed = tr.pick_parts(key)
    if not parsed:
        return f"Pick {key}"
    year, rnd, original = parsed
    label = f"{year} {tr.ordinal(rnd)}"
    giver = next((m["from"] for m in trade.get("moves") or [] if m.get("asset") == asset), None)
    giver = giver or next((team for team, gave in (trade.get("sent") or {}).items() if asset in gave), None)
    if giver != original:
        label += f", originally {tr.team_name(trade, original)}'s"
    selection, drafted = None, False
    if hist is not None:
        try:
            drafted = year in hist.drafts()
            selection = hist.pick_selection(key) if drafted else None
        except Exception:  # noqa: BLE001
            selection = None
    if selection and selection.get("player"):
        slot = f"{selection['round']}.{int(selection['in_round']):02d}"
        return f"{label}: {hist.player_name(str(selection['player']))} ({slot})"
    if drafted:
        return f"{label} (used; the archive doesn't show who was taken)"
    if today.year > year:
        return f"{label} (draft results not in the archive)"
    return f"{label} (not yet used)"


def revisit_sides(trade: dict[str, Any], due: datetime, tz: ZoneInfo, stats: Any, hist: Any,
                  ) -> tuple[dict[str, list[dict[str, Any]]], tuple[str, str], bool]:
    """(team -> lines, (first day, last day), complete). Incomplete = an NHL read failed."""
    after = when(trade["at"]).astimezone(tz).date()
    through = due.astimezone(tz).date()
    complete = True
    sides: dict[str, list[dict[str, Any]]] = {}
    for team in trade["teams"]:
        lines = []
        for asset in sorted((trade.get("received") or {}).get(team) or []):
            kind, _, value = asset.partition(":")
            if kind != "player":
                lines.append({"kind": "pick", "text": pick_text(trade, asset, hist, through)})
                continue
            info = (trade.setdefault("players", {})).setdefault(value, {})
            nhl_id = info.get("nhl_id")
            if nhl_id is None and info.get("name"):
                try:
                    nhl_id = stats.find_id(str(info["name"]), str(info.get("team") or ""), str(info.get("position") or ""))
                except Exception as exc:  # noqa: BLE001
                    print(f"NHL WARNING: player search failed for {info['name']} ({exc.__class__.__name__})")
                    complete = False
                if nhl_id is not None:
                    info["nhl_id"] = nhl_id
            prod = stats.production(nhl_id, str(info.get("position") or "") == "G", after, through)
            if prod.error and nhl_id is not None:
                complete = False
            lines.append({"kind": "player", "label": tr.display_name(str(info.get("name") or f"Player {value}")),
                          "points": prod.points, "games": prod.games, "goalie": prod.goalie,
                          "error": "no NHL match" if nhl_id is None else prod.error,
                          "missing_box": prod.missing_box})
        sides[team] = lines
    first = after + timedelta(days=1)
    window = (f"{first.strftime('%b')} {first.day}, {first.year}", f"{through.strftime('%b')} {through.day}, {through.year}")
    return sides, window, complete


def message_link(cfg: dict[str, Any], message_id: str | None, cache: dict[str, Any]) -> str | None:
    if not message_id:
        return None
    if "webhook" not in cache:
        ok, _, body = dw.get_webhook(secret(cfg, "discussion"))
        cache["webhook"] = body if ok else None
    hook = cache["webhook"] or {}
    if hook.get("guild_id") and hook.get("channel_id"):
        return f"https://discord.com/channels/{hook['guild_id']}/{hook['channel_id']}/{message_id}"
    return None


def read_tally(cfg: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any] | None:
    if not trade.get("message_id") or not trade.get("poll"):
        return None
    ok, detail, message = dw.get_discord_message(secret(cfg, "discussion"), str(trade["message_id"]))
    if not ok:
        print(f"NOTE: could not read the poll of trade {trade['id']} back from Discord ({detail}); the revisit leaves it out.")
        return None
    return tr.poll_tally(message)


def post_revisits(state: dict[str, Any], cfg: dict[str, Any], tz: ZoneInfo, now: datetime, mode: str,
                  stats: Any = None, hist: Any = None) -> int:
    due = due_revisits(state, cfg, tz, now)
    if not due:
        return 0
    name = secret(cfg, "discussion")
    if mode == "live" and not has_secret(name):
        print(f"SKIP {len(due)} trade revisit(s): the {name} secret is not set. They post once it is added.")
        return 0
    stats = stats or tp.NhlStats()
    hist = hist if hist is not None else history(cfg=cfg)
    errors, cache = 0, {}
    for trade, months, when_due in due[:MAX_REVISITS_PER_RUN]:
        sides, window, complete = revisit_sides(trade, when_due, tz, stats, hist)
        if not complete and now - when_due < REVISIT_GIVE_UP:
            print(f"WAITING revisit {trade['id']} ({months} months): NHL stats could not be read; will retry next run.")
            continue
        tally = read_tally(cfg, trade) if mode == "live" else None
        link = message_link(cfg, trade.get("message_id"), cache) if mode == "live" else None
        payload = tr.revisit(trade, months, sides, cfg, window=window, tally=tally, link=link, now=now)
        print(f"REVISIT {trade['id']} ({months} months):")
        show(payload)
        if mode != "live":
            continue
        ok, detail, message_id = dw.send_discord_webhook(name, payload)
        if ok:
            trade.setdefault("revisits", {})[str(months)] = {"at": now.isoformat(), "message_id": message_id}
            print(f"POSTED revisit {trade['id']} ({months} months)")
        else:
            errors += 1
            print(f"DELIVERY ERROR revisit {trade['id']}: {detail} (will retry next run)")
    if len(due) > MAX_REVISITS_PER_RUN:
        print(f"{len(due) - MAX_REVISITS_PER_RUN} more revisit(s) are due; they post on the next runs.")
    return errors


# --- 2. deadline-day tracker --------------------------------------------------------

def counted(state: dict[str, Any], league: str, season: int) -> list[dict[str, Any]]:
    return [t for t in state.get("trades") or []
            if not t.get("reversed") and t.get("league_id") == league and t.get("season") == season]


def update_tracker(state: dict[str, Any], cfg: dict[str, Any], info: dict[str, Any], tz: ZoneInfo, now: datetime,
                   season: int, mode: str) -> int:
    deadline = cal.trade_deadline(info, tz)
    stage = tracker_stage(deadline, now, tz)
    if deadline is None:
        print("Tracker: the Fantrax calendar has no trade-deadline Week.")
        return 0
    key = deadline.astimezone(tz).date().isoformat()
    entry = (state.setdefault("deadline", {})).get(key) or {}
    if stage == "off":
        return 0
    if stage == "waiting":
        print(f"Tracker: trade-deadline day; the BLHA TRADECENTRE message starts at {TRACKER_OPENS.strftime('%I:%M %p').lstrip('0')}.")
        return 0
    if entry.get("final"):
        return 0
    league = str(cfg["league_id"])
    season_trades = counted(state, league, season)
    start = deadline_day_start(deadline, tz)
    today = [t for t in season_trades if start <= when(t["at"]) <= now]
    final = stage == "final"
    payload = tr.tracker(cfg, deadline, today, len(season_trades), final=final, now=now)
    print(f"TRACKER ({'final' if final else 'live'}, {'edit' if entry.get('message_id') else 'new message'}):")
    show(payload)
    if mode != "live":
        return 0
    name = secret(cfg, "announcements")
    if not has_secret(name):
        print(f"SKIP tracker: the {name} secret is not set (📢│announcements webhook).")
        return 0
    ok, detail, message_id, action = dw.upsert_discord_message(name, payload, entry.get("message_id"))
    if not ok:
        print(f"DELIVERY ERROR tracker: {detail} (will retry next run)")
        return 1
    entry.update({"message_id": message_id, "updated": now.isoformat(), "deadline": deadline.isoformat()})
    entry.setdefault("created", now.isoformat())
    if final:
        entry["final"] = True
    state["deadline"][key] = entry
    print(f"TRACKER {action.upper()} (message {message_id})")
    return 0


# --- run ---------------------------------------------------------------------------

def run(mode: str, *, now: datetime | None = None, fx: Any = None, cfg: dict[str, Any] | None = None,
        state_path: Path = STATE_PATH, stats: Any = None, hist: Any = None,
        sleep: Callable[[float], Any] = clock.sleep) -> int:
    cfg = cfg or load_league()
    tz = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Trade-Desk/1.0")
    state = load_json(state_path, {})
    state.setdefault("trades", [])
    state.setdefault("deadline", {})

    info = fx.league_info()
    season = td.season_of(info)
    print(f"BLHA TRADE DESK mode={mode.upper()} season={season} ({cfg.get('season_label') or ''}) "
          f"now={now.astimezone(tz).strftime('%a %b %d %Y %I:%M %p %Z')}")
    errors = 0
    try:
        new = detect_trades(state, fx, cfg, season, now, sleep)
        print(f"Trades found this run: {len(new)}.")
    except td.SnapshotError as exc:
        print(f"ERROR: {exc}. Nothing about trades is saved this run.")
        errors += 1
    errors += post_cards(state, cfg, now, mode)
    errors += post_revisits(state, cfg, tz, now, mode, stats, hist)
    errors += update_tracker(state, cfg, info, tz, now, season, mode)
    if mode == "live":
        save_json(state_path, state)
    else:
        print("PREVIEW: nothing posted or saved.")
    return 1 if errors else 0


# --- test posts ----------------------------------------------------------------------

def sample_trade(now: datetime) -> dict[str, Any]:
    return {
        "id": "test", "at": now.isoformat(), "teams": ["a", "b"],
        "names": {"a": "Test 1", "b": "Test 2", "c": "Test 3"},
        "received": {"a": ["pick:2028|1|c", "player:02un4"], "b": ["player:01ztp"]},
        "sent": {"a": ["player:01ztp"], "b": ["pick:2028|1|c", "player:02un4"]},
        "players": {"02un4": {"name": "McDavid, Connor", "position": "C", "team": "EDM"},
                    "01ztp": {"name": "Hyman, Zach", "position": "RW", "team": "EDM"}},
    }


def test_post(item: str) -> int:
    cfg = load_league()
    now = datetime.now(timezone.utc)
    trade = sample_trade(now)
    if item == "card":
        name = secret(cfg, "discussion")
        payload = tr.report_card(trade, cfg, test=True, poll_hours=1)
        payload["embeds"][0]["description"] += "\n\nSample only. No trade has actually happened; the poll closes in 1 hour."
        ok, detail, message_id = dw.send_discord_webhook(name, payload)
        print(("PASS" if ok else "ERROR") + f" [trade report card]: {detail} message={message_id}")
        if ok and message_id:
            got, why, message = dw.get_discord_message(name, message_id)
            tally = tr.poll_tally(message) if got else None
            print(f"READ BACK (Get Webhook Message): {'ok' if got else why}; poll: {json.dumps(tally)}")
        return 0 if ok else 1
    if item == "revisit":
        sides = {"a": [{"kind": "player", "label": "Connor McDavid", "points": 412.35, "games": 41, "goalie": False},
                       {"kind": "pick", "text": "2028 1st, originally Test 3's (not yet used)"}],
                 "b": [{"kind": "player", "label": "Zach Hyman", "points": 198.4, "games": 39, "goalie": False}]}
        tally = {"answers": [("Test 1", 5), ("Test 2", 3), (tr.EVEN, 2)], "total": 10, "final": True}
        payload = tr.revisit(trade, 6, sides, cfg, window=("Jan 16, 2027", "Jul 15, 2027"), tally=tally, test=True)
        payload["embeds"][0]["description"] += "\n\nSample only. These numbers are made up."
        ok, detail = dw.post_discord_webhook(secret(cfg, "discussion"), payload)
        print(("PASS" if ok else "ERROR") + f" [trade revisit]: {detail}")
        return 0 if ok else 1
    name = secret(cfg, "announcements")
    deadline = now + timedelta(hours=3)
    live = tr.tracker(cfg, deadline, [trade], 7, final=False, now=now, test=True)
    live["embeds"][0]["description"] += "\n\nSample only. Today is not the trade deadline."
    ok, detail, message_id, _ = dw.upsert_discord_message(name, live, None)
    print(("PASS" if ok else "ERROR") + f" [tracker post]: {detail}")
    if not ok:
        return 1
    final = tr.tracker(cfg, deadline, [trade], 7, final=True, now=now, test=True)
    final["embeds"][0]["description"] += "\n\nSample only. Today is not the trade deadline."
    ok, detail, _, action = dw.upsert_discord_message(name, final, message_id)
    print(("PASS" if ok else "ERROR") + f" [tracker edit to final, {action}]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--item", choices=("card", "revisit", "tracker"), default="card",
                        help="test mode: which sample to post")
    parser.add_argument("--at", help="preview only: as if it were this local time, e.g. 2027-02-21T21:00")
    args = parser.parse_args()
    if args.mode == "test":
        return test_post(args.item)
    now = None
    if args.at:
        if args.mode == "live":
            parser.error("--at is for preview only")
        tz = timezone_of(load_league())
        now = datetime.fromisoformat(args.at)
        now = (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(timezone.utc)
    return run(args.mode, now=now)


if __name__ == "__main__":
    sys.exit(main())
