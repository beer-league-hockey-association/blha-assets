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
   Commissioner reversing it) is not posted. A trade seen after the trade
   deadline, while trading is closed (11.6: until the league is renewed for
   next season, which is how trading reopens), gets a card without a poll
   saying the Commissioner reviews it under Section 11.6, and it doesn't count
   toward the season's trades. A card for three or more teams says the feed
   can't separate trades made minutes apart.
2. TRADE REVISIT at 6 and 12 months (same channel): for each side, the BLHA
   fantasy points its players have produced in NHL regular-season games since
   the trade (trade_points.py), wherever they have played since; picks show
   "not yet used" or the player drafted with them (league archive); and the
   final poll result, read back from Discord. It never suggests a trade should
   change.
3. BLHA DEADLINE DAY TRADE CENTER (📢│announcements, secret BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS):
   on trade-deadline day (Sunday of the deadline Week, 11:59 PM ET; deadline
   from blha.season.trade_deadline, the same helper the League Bot uses) one
   live message is posted at 9:00 AM ET and edited every run until the
   deadline: a countdown, every trade seen that day and the number of trades
   this season. The first run after the deadline turns it into the final
   "Deadline passed — N trades today".

A missing webhook secret skips that post with a clear log line; the run does
not fail. Posts are text and links only.

Safety:
- State is saved after detection and after every post, so a run that dies
  later (a slow NHL API during revisits) never posts the same card twice.
  The order is detection, report cards, the tracker, then revisits, which
  have a time budget and resume on the next run.
- A Fantrax error during detection keeps the saved snapshot; cards, the
  tracker and revisits still run and the run exits non-zero.
- Player moves with nothing coming back are not posted when the window since
  the last good read is longer than STALE_AFTER and includes a waiver run
  (10.3): a drop by one team and a FAAB claim by another would look like a
  trade. The new rosters become the baseline and the log says so. Two-sided
  swaps and pick moves still post. ``read_at`` keeps the last good read for
  this, rewritten at most every READ_HEARTBEAT on quiet runs.
- If getDraftPicks fails while players moved, nothing is posted or saved
  and the next run tries again (for up to PICKS_WAIT), so a player-for-pick
  trade is never split into two cards.

Modes:
  preview     read Fantrax, print what would be posted; no Discord, no state change
              (--at "2027-02-21T21:00" previews another moment, for example deadline day)
  test        post one [TEST] sample (--item card, revisit or tracker); no state change
  live        detect, post and save state
  rebaseline  read Fantrax and save it as the new snapshot without posting anything
              (after a deliberate roster reset, which live mode refuses as incomplete)
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
REVISIT_BUDGET = timedelta(minutes=6)  # NHL reading time per run; the rest resumes next run
CARD_RETRY = timedelta(hours=6)        # a report card that failed to post is retried this long
CONFIRM_DELAY = 5                      # seconds before re-reading Fantrax to confirm a trade
STALE_AFTER = timedelta(hours=3)       # a longer window over a waiver run can hide a drop and a claim
READ_HEARTBEAT = timedelta(hours=2)    # read_at moves at most this often on quiet runs (state commits)
WAIVER_RUN = (time(10, 45), time(12, 0))  # around the daily 11:00 AM ET waiver run (Constitution 10.3)
PICKS_WAIT = timedelta(hours=6)        # how long player moves wait for a readable getDraftPicks


class RetryNextRun(RuntimeError):
    """Detection found something it can't post whole yet; the snapshot is kept for the next run."""


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


def stamp(value: Any) -> datetime | None:
    try:
        return when(value) if value else None
    except (TypeError, ValueError):
        return None


def last_good_read(state: dict[str, Any]) -> datetime | None:
    """The latest moment the saved snapshot is known to match Fantrax.

    ``updated_at`` is exact whenever the state was committed (the state
    branch skips a change to it alone), ``read_at`` is at most READ_HEARTBEAT
    behind, and the snapshot's ``at`` is when rosters or picks last changed.
    """
    found = [stamp(state.get("updated_at")), stamp(state.get("read_at")), stamp((state.get("snapshot") or {}).get("at"))]
    found = [x for x in found if x is not None]
    return max(found) if found else None


def mark_read(state: dict[str, Any], now: datetime) -> None:
    state["updated_at"] = now.isoformat()   # the only change on a quiet run, which the state save skips
    previous = stamp(state.get("read_at"))
    if previous is None or now - previous >= READ_HEARTBEAT:
        state["read_at"] = now.isoformat()


def spans_waiver_run(start: datetime, end: datetime, tz: ZoneInfo) -> bool:
    """True if (start, end] overlaps a daily waiver run (10:45 AM to noon, league time)."""
    day, last = start.astimezone(tz).date(), end.astimezone(tz).date()
    while day <= last:
        opens = datetime.combine(day, WAIVER_RUN[0], tzinfo=tz)
        closes = datetime.combine(day, WAIVER_RUN[1], tzinfo=tz)
        if start < closes and end > opens:
            return True
        day += timedelta(days=1)
    return False


def unsafe_window(since: datetime | None, now: datetime, tz: ZoneInfo) -> str | None:
    """Why a player moving with nothing back can't be told from a waiver drop and claim, or None.

    FAAB claims only process at the daily waiver run (10.3), and a dropped
    player sits on waivers first (10.6), so both fit in one window only when
    it is long and includes a waiver run. Normal 15 to 30 minute windows over
    the waiver run stay trusted.
    """
    if since is None or now - since <= STALE_AFTER or not spans_waiver_run(since, now, tz):
        return None
    hours = (now - since).total_seconds() / 3600
    return (f"the last good Fantrax read was {hours:.1f} hours ago and a waiver run fell in between, "
            "so a waiver drop and a FAAB claim would look the same")


def detect_trades(state: dict[str, Any], fx: Any, cfg: dict[str, Any], season: int, now: datetime,
                  sleep: Callable[[float], Any] = clock.sleep, *, tz: ZoneInfo | None = None,
                  deadline: datetime | None = None, rebaseline: bool = False) -> list[dict[str, Any]]:
    """New trades since the saved snapshot (also updates the snapshot in state).

    Nothing in ``state`` changes unless every read succeeds. ``deadline``
    (11.6) marks trades seen after it. ``rebaseline`` saves what Fantrax shows
    now as the snapshot without looking for trades.
    """
    league = str(cfg["league_id"])
    tz = tz or timezone_of(cfg)
    rosters, picks, names = td.read_snapshot(fx, tz)
    snap = state.get("snapshot") or {}
    since = last_good_read(state)
    fresh = snap.get("league_id") != league or snap.get("season") != season or not isinstance(snap.get("rosters"), dict)
    if fresh or rebaseline:
        if rebaseline:
            print(f"REBASELINE: saving what Fantrax shows now as the snapshot for league {league} season {season}. "
                  "No trades reported; saved trades, cards and revisits are unchanged.")
        else:
            print(f"No saved snapshot for league {league} season {season} yet: saving a baseline. No trades reported this run.")
        kept = (snap.get("picks") or {}) if not fresh else {}
        if picks is None and kept:
            print("Draft picks couldn't be read: keeping the saved pick ownership.")
        state["snapshot"] = {"league_id": league, "season": season, "rosters": rosters,
                             "picks": picks if picks is not None else kept, "at": now.isoformat()}
        mark_read(state, now)
        return []
    prev_picks = snap.get("picks") if isinstance(snap.get("picks"), dict) and snap.get("picks") else None
    moves = td.moves_between(snap["rosters"], rosters, prev_picks, picks)
    if moves:
        # Rosters and picks are two separate reads; read both again so a trade
        # processed between them is seen whole, not as two trades.
        sleep(CONFIRM_DELAY)
        rosters, again, names2 = td.read_snapshot(fx, tz)
        picks = again if again is not None else picks
        names = {**names, **names2}
        moves = td.moves_between(snap["rosters"], rosters, prev_picks, picks)
    if picks is None and prev_picks is not None and any(m["asset"].startswith("player:") for m in moves):
        if since is None or now - since <= PICKS_WAIT:
            raise RetryNextRun("players moved but draft-pick ownership couldn't be read, so a pick in the same "
                               "trade would be missed; nothing posted or saved, the next run tries again")
        print(f"WARNING: draft picks have been unreadable for over {PICKS_WAIT}; posting the player moves without them.")
    reason = unsafe_window(since, now, tz)
    held: list[dict[str, str]] = []
    if reason:
        moves, held = td.hold_back_one_sided_players(moves)
    found = td.group_trades(moves)

    trades: list[dict[str, Any]] = []
    reversals: list[dict[str, Any]] = []
    stamp_id = now.strftime("%Y%m%dT%H%M%S")
    for i, t in enumerate(found, 1):
        undone = td.reversal_of(t, state.get("trades") or [], now)
        if undone:
            reversals.append(undone)
            print(f"REVERSAL: this undoes trade {undone['id']} ({' and '.join(undone['names'].get(x, x) for x in undone['teams'])}); "
                  "no report card, and its revisits are cancelled.")
            continue
        record = {
            "id": f"{season}-{stamp_id}-{i}", "season": season, "league_id": league,
            "test": is_test_label(cfg.get("season_label")),
            "at": now.isoformat(), "since": since.isoformat() if since else None,
            "teams": t["teams"], "received": t["received"], "sent": t["sent"],
            "names": {k: v for k, v in sorted(names.items())},
            "card": "pending", "revisits": {},
        }
        if t.get("one_sided"):
            record["one_sided"] = True
        if deadline is not None and since is not None and since >= deadline:
            record["after_deadline"] = True   # the whole window is after the deadline (11.6)
            print(f"AFTER THE DEADLINE: trade {record['id']} was processed while trading is closed (11.6); "
                  "its card has no poll and it isn't counted.")
        elif deadline is not None and since is not None and since < deadline < now:
            record["at_deadline"] = True      # first check after the deadline: it may have processed just before
        trades.append(record)
    player_info(fx, trades)
    for m in held:
        print(f"NOT POSTED: {m['asset']} went from {names.get(m['from'], m['from'])} to "
              f"{names.get(m['to'], m['to'])} with nothing coming back, but {reason}. Saved as the new baseline.")

    for undone in reversals:
        undone["reversed"] = now.isoformat()
    cur = {"league_id": league, "season": season, "rosters": rosters,
           "picks": picks if picks is not None else (prev_picks or {})}
    if any(snap.get(k) != v for k, v in cur.items()):
        state["snapshot"] = {**cur, "at": now.isoformat()}   # "at": when rosters or picks last changed
    state.setdefault("trades", []).extend(trades)
    mark_read(state, now)
    return trades


# --- 1. report cards --------------------------------------------------------------

def post_cards(state: dict[str, Any], cfg: dict[str, Any], now: datetime, mode: str,
               persist: Callable[[], Any] = lambda: None) -> int:
    """Post every report card not posted yet (new trades, or a recent failed post). Returns errors.

    ``persist`` saves the state after each card, so a run that dies later never posts it again.
    """
    name, errors = secret(cfg, "discussion"), 0
    for t in state.get("trades") or []:
        if t.get("card") != "pending" or t.get("reversed"):
            continue
        if now - when(t["at"]) > CARD_RETRY:
            t["card"] = "gave up"
            print(f"GAVE UP report card {t['id']}: it could not be posted within {CARD_RETRY}.")
            persist()
            continue
        with_poll = not t.get("after_deadline")
        payload = tr.report_card(t, cfg, with_poll=with_poll, poll_hours=poll_hours(cfg))
        print(f"REPORT CARD {t['id']}:")
        show(payload)
        if mode != "live":
            continue
        if not has_secret(name):
            t["card"] = "skipped"
            persist()
            print(f"SKIP report card: the {name} secret is not set (💬│trade-discussion webhook). "
                  "Add it in GitHub > Settings > Secrets and variables > Actions; later trades will post.")
            continue
        ok, detail, message_id = dw.send_discord_webhook(name, payload)
        if not ok and with_poll and detail.startswith("Discord returned 400"):
            print(f"POLL WARNING: Discord refused the message with its poll ({detail}). Posting it without the poll.")
            with_poll = False
            ok, detail, message_id = dw.send_discord_webhook(name, tr.report_card(t, cfg, with_poll=False))
        if ok:
            t.update({"card": "posted", "message_id": message_id, "poll": with_poll, "posted_at": now.isoformat()})
            persist()
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
            label = tr.display_name(str(info.get("name") or f"Player {value}"))
            if getattr(stats, "out_of_time", lambda: False)():
                complete = False   # no more NHL requests this run
                lines.append({"kind": "player", "label": label, "points": 0.0, "games": 0, "goalie": False,
                              "error": tp.OUT_OF_TIME, "missing_box": 0})
                continue
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
            lines.append({"kind": "player", "label": label,
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
                  stats: Any = None, hist: Any = None, *, persist: Callable[[], Any] = lambda: None,
                  stop_at: float | None = None, clock_fn: Callable[[], float] = clock.monotonic) -> int:
    """Post due revisits, at most MAX_REVISITS_PER_RUN and only while ``stop_at`` (a ``clock_fn``
    reading) hasn't passed; the rest resume next run. ``persist`` saves after each post."""
    due = due_revisits(state, cfg, tz, now)
    if not due:
        return 0
    name = secret(cfg, "discussion")
    if mode == "live" and not has_secret(name):
        print(f"SKIP {len(due)} trade revisit(s): the {name} secret is not set. They post once it is added.")
        return 0
    stats = stats or tp.NhlStats()
    if stop_at is not None:
        stats.stop_at, stats.clock = stop_at, clock_fn
    hist = hist if hist is not None else history(cfg=cfg)
    errors, cache = 0, {}
    for done, (trade, months, when_due) in enumerate(due[:MAX_REVISITS_PER_RUN]):
        if stop_at is not None and clock_fn() >= stop_at:
            print(f"TIME: the revisit time budget ({REVISIT_BUDGET}) is used up; "
                  f"{len(due) - done} due revisit(s) resume next run.")
            break
        sides, window, complete = revisit_sides(trade, when_due, tz, stats, hist)
        if not complete and now - when_due < REVISIT_GIVE_UP:
            print(f"WAITING revisit {trade['id']} ({months} months): NHL stats could not be read"
                  f"{' in time' if getattr(stats, 'out_of_time', lambda: False)() else ''}; will retry next run.")
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
            persist()
            print(f"POSTED revisit {trade['id']} ({months} months)")
        else:
            errors += 1
            print(f"DELIVERY ERROR revisit {trade['id']}: {detail} (will retry next run)")
    if len(due) > MAX_REVISITS_PER_RUN:
        print(f"{len(due) - MAX_REVISITS_PER_RUN} more revisit(s) are due; they post on the next runs.")
    return errors


# --- 2. deadline-day tracker --------------------------------------------------------

def counted(state: dict[str, Any], league: str, season: int) -> list[dict[str, Any]]:
    """The season's trades: not reversed, and not seen after the deadline while trading is closed (11.6)."""
    return [t for t in state.get("trades") or []
            if not t.get("reversed") and not t.get("after_deadline")
            and t.get("league_id") == league and t.get("season") == season]


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
        print(f"Tracker: trade-deadline day; the Deadline Day Trade Center message starts at {TRACKER_OPENS.strftime('%I:%M %p').lstrip('0')}.")
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
        sleep: Callable[[float], Any] = clock.sleep, clock_fn: Callable[[], float] = clock.monotonic) -> int:
    cfg = cfg or load_league()
    tz = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Trade-Desk/1.0")
    state = load_json(state_path, {})
    state.setdefault("trades", [])
    state.setdefault("deadline", {})
    saving = mode in ("live", "rebaseline")

    def persist() -> None:
        if saving:
            save_json(state_path, state)

    errors = 0
    try:
        info: dict[str, Any] | None = fx.league_info()
        season = td.season_of(info)
    except Exception as exc:  # noqa: BLE001 - cards and revisits don't need Fantrax
        info, season = None, (state.get("snapshot") or {}).get("season")
        errors += 1
        print(f"ERROR: could not read Fantrax league info ({exc.__class__.__name__}: {str(exc)[:200]}). "
              "Trades and the tracker are skipped this run; report cards and revisits still run.")
    print(f"BLHA TRADE DESK mode={mode.upper()} season={season} ({cfg.get('season_label') or ''}) "
          f"now={now.astimezone(tz).strftime('%a %b %d %Y %I:%M %p %Z')}")

    if mode == "rebaseline":
        if info is None:
            return 1
        try:
            detect_trades(state, fx, cfg, season, now, sleep, tz=tz, rebaseline=True)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: could not read Fantrax ({exc.__class__.__name__}: {str(exc)[:200]}). Nothing saved.")
            return 1
        persist()
        print("REBASELINE: saved. The next live run compares with this snapshot.")
        return 0

    # 1. Detection, saved before anything is posted.
    if info is not None:
        try:
            new = detect_trades(state, fx, cfg, season, now, sleep, tz=tz, deadline=cal.trade_deadline(info, tz))
            print(f"Trades found this run: {len(new)}.")
            persist()
        except RetryNextRun as exc:
            errors += 1
            print(f"RETRY: {exc}.")
        except td.SnapshotError as exc:
            errors += 1
            print(f"ERROR: {exc}. The saved snapshot is kept; nothing about trades is saved this run.")
        except Exception as exc:  # noqa: BLE001 - a Fantrax HTTP error or timeout must not stop the other phases
            errors += 1
            print(f"ERROR: reading Fantrax for trades failed ({exc.__class__.__name__}: {str(exc)[:200]}). "
                  "The saved snapshot is kept; the next run compares with it.")
    # 2. Report cards (saved after each post), 3. the tracker, 4. revisits (time budget, saved after each).
    errors += post_cards(state, cfg, now, mode, persist)
    if info is not None:
        errors += update_tracker(state, cfg, info, tz, now, season, mode)
        persist()
    errors += post_revisits(state, cfg, tz, now, mode, stats, hist, persist=persist,
                            stop_at=clock_fn() + REVISIT_BUDGET.total_seconds(), clock_fn=clock_fn)
    persist()
    if not saving:
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
    parser.add_argument("--mode", choices=("preview", "test", "live", "rebaseline"), default="preview",
                        help="rebaseline: save what Fantrax shows now as the snapshot, posting nothing "
                             "(after a deliberate roster reset)")
    parser.add_argument("--item", choices=("card", "revisit", "tracker"), default="card",
                        help="test mode: which sample to post")
    parser.add_argument("--at", help="preview only: as if it were this local time, e.g. 2027-02-21T21:00")
    args = parser.parse_args()
    if args.mode == "test":
        return test_post(args.item)
    now = None
    if args.at:
        if args.mode != "preview":
            parser.error("--at is for preview only")
        tz = timezone_of(load_league())
        now = datetime.fromisoformat(args.at)
        now = (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(timezone.utc)
    return run(args.mode, now=now)


if __name__ == "__main__":
    sys.exit(main())
