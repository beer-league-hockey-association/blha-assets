#!/usr/bin/env python3
"""BLHA Draft Center: countdown, draft-order reveal and recap, plus private timeout alerts.

Scope (decided Oct 2, 2026): Fantrax already notifies owners when they are on
the clock and when picks are made, so the Draft Center never posts per-pick or
on-the-clock messages. It covers what Fantrax does not:

  📢│draft-announcements  countdown from the Fantrax draft date (the first post is
                        the full announcement), the official draft order, a notice
                        if the date or order changes, and a "Draft Complete" summary
  📋│draft-results        the permanent record, one post per completed round
  Commissioner Desk     private alert when a pick clock runs out or a pick is
                        skipped, with the team's timeout count (Art. 13.5 / 14.3)

Fantrax's data feed does not include the pick clock, so clock lengths and the
nightly pause come from automation/league.yaml (Constitution 13.1, 13.4, 14.3).

Modes:
  preview  print what a live run would post; no Discord, no state change
  test     post clearly labeled [TEST] samples of each post; no state change
  live     post what is due and record it
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parent / "commissioner"))

from blha import draft as dr  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import AVATAR, color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402  (Commissioner Desk private payloads)

STATE_PATH = ROOT / "state" / "draft.json"
FOOTER_DIVIDER = (
    "https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/main/"
    "discord/webhooks/shared/blha-footer-divider-1600x90.png?v=8bit-1"
)
RESULTS_CHANNEL = "**📋│draft-results**"
MAX_MESSAGE_CHARS = 5500  # under Discord's 6,000 total-embed-text limit
MAX_EMBEDS = 10

DEFAULTS: dict[str, Any] = {
    "webhooks": {
        "announcements": "BLHA_WEBHOOK_DRAFT_ANNOUNCEMENTS",
        "results": "BLHA_WEBHOOK_DRAFT_RESULTS",
    },
    "countdown": ["30d", "7d", "1d", "1h", "start"],
    "order_reveal": "7d",
    "pause": ["00:00", "08:00"],
    "linger_hours": 24,
    "kind": "auto",
    "test_pick_clock_minutes": None,
    "drafts": {
        "startup": {"name": "Startup Draft", "rounds": 36, "format": "snake",
                    "pick_clock_hours": 4, "rule": "13.5", "article": "XIII", "pause_rule": "13.4"},
        "annual": {"name": "Annual Draft", "rounds": 5, "format": "linear",
                   "pick_clock_hours": 8, "rule": "14.3", "article": "XIV", "pause_rule": "14.3"},
    },
}


# --- configuration -------------------------------------------------------------

def load_config(league: dict[str, Any]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))
    user = league.get("draft_center") or {}
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            for sub, subval in value.items():
                if isinstance(subval, dict) and isinstance(cfg[key].get(sub), dict):
                    cfg[key][sub].update(subval)
                else:
                    cfg[key][sub] = subval
        else:
            cfg[key] = value
    return cfg


def parse_offset(text: str) -> timedelta:
    text = str(text).strip().lower()
    if text == "start":
        return timedelta(0)
    amount, unit = int(text[:-1]), text[-1]
    return {"d": timedelta(days=amount), "h": timedelta(hours=amount), "m": timedelta(minutes=amount)}[unit]


def pause_window(cfg: dict[str, Any]) -> tuple[time, time] | None:
    pause = cfg.get("pause")
    if not pause:
        return None
    start, end = (time(*(int(x) for x in str(t).split(":"))) for t in pause)
    return start, end


def draft_kind(draft: dr.Draft, info: dict[str, Any], cfg: dict[str, Any]) -> str:
    kind = str(cfg.get("kind") or "auto")
    if kind in cfg["drafts"]:
        return kind
    if draft.rounds:
        return "startup" if draft.rounds > cfg["drafts"]["annual"]["rounds"] else "annual"
    return "startup" if str(info.get("draftType") or "").lower() == "snake" else "annual"


def clock_minutes(kind: str, cfg: dict[str, Any]) -> int:
    override = cfg.get("test_pick_clock_minutes")
    if override:
        return int(override)
    return int(float(cfg["drafts"][kind]["pick_clock_hours"]) * 60)


def active_minutes(start: datetime, end: datetime, tz: ZoneInfo, pause: tuple[time, time] | None) -> float:
    """Minutes between start and end, not counting the nightly clock pause."""
    if end <= start:
        return 0.0
    total = (end - start).total_seconds() / 60
    if not pause:
        return total
    p_start, p_end = pause
    day = start.astimezone(tz).date() - timedelta(days=1)
    last = end.astimezone(tz).date()
    while day <= last:
        a = datetime.combine(day, p_start, tzinfo=tz)
        b = datetime.combine(day if p_end > p_start else day + timedelta(days=1), p_end, tzinfo=tz)
        overlap = (min(b, end) - max(a, start)).total_seconds() / 60
        if overlap > 0:
            total -= overlap
        day += timedelta(days=1)
    return max(total, 0.0)


# --- planning (pure functions; tested offline) ------------------------------------

def plan_countdown(draft: dr.Draft, entry: dict[str, Any], now: datetime, cfg: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Return (offset to post, offsets to mark skipped).

    If a check runs late and several countdown posts are due at once, only the
    most recent one is posted and the older ones are skipped. Pre-draft
    reminders that come due after the draft has started are skipped too.
    """
    if draft.date is None or draft.completed:
        return None, []
    done = entry.get("countdown") or {}
    due = [t for t in cfg["countdown"] if t not in done and now >= draft.date - parse_offset(t)]
    if not due:
        return None, []

    def still_useful(text: str) -> bool:
        if parse_offset(text):
            return now < draft.date
        return now <= draft.date + timedelta(hours=12)

    useful = [t for t in due if still_useful(t)]
    send = min(useful, key=parse_offset) if useful else None
    return send, [t for t in due if t != send]


def order_fingerprint(order: list[str], traded: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps([order, traded], sort_keys=True).encode()).hexdigest()


def plan_order(draft: dr.Draft, traded: list[dict[str, Any]], entry: dict[str, Any], now: datetime,
               cfg: dict[str, Any], *, force: bool = False) -> str | None:
    """Return "reveal", "update" or None."""
    if not draft.order or draft.status(now) != "pre":
        return None
    fp = order_fingerprint(draft.order, traded)
    if entry.get("order_posted"):
        if fp != entry.get("order_fp"):
            return "update"
        return "reveal" if force else None
    if force:
        return "reveal"
    if draft.date and now >= draft.date - parse_offset(cfg.get("order_reveal") or "7d"):
        return "reveal"
    return None


def plan_recap(draft: dr.Draft, entry: dict[str, Any], now: datetime) -> tuple[list[int], bool]:
    """Rounds ready to post, and whether the completion post is due."""
    posted = set(entry.get("rounds_posted") or [])
    done = draft.status(now) == "done"
    rounds = [r for r in range(1, draft.rounds + 1)
              if r not in posted and (draft.round_complete(r) or done) and draft.round_picks(r)]
    return rounds, done and not entry.get("completed_posted")


def plan_alerts(draft: dr.Draft, entry: dict[str, Any], now: datetime, tz: ZoneInfo,
                minutes: int, pause: tuple[time, time] | None) -> list[tuple[dr.Pick, str]]:
    """New (pick, "skipped"|"expired") alerts during a live draft."""
    if draft.status(now) != "live":
        return []
    alerted = entry.get("alerts") or {}
    found: list[tuple[dr.Pick, str]] = []
    for pick in draft.skipped():
        if str(pick.overall) not in alerted:
            found.append((pick, "skipped"))
    current = draft.on_the_clock()
    paused = "pause" in draft.state.lower()  # the commissioner paused the draft in Fantrax
    if current and not paused and str(current.overall) not in alerted:
        started = draft.last_pick_time() or draft.start or draft.date
        if started and active_minutes(started, now, tz, pause) >= minutes:
            found.append((current, "expired"))
    return found


# --- rendering ---------------------------------------------------------------------

class Renderer:
    def __init__(self, league: dict[str, Any], cfg: dict[str, Any], info: dict[str, Any],
                 draft: dr.Draft, players: dict[str, Any] | None = None, *, test: bool = False) -> None:
        self.league, self.cfg, self.info, self.draft = league, cfg, info, draft
        self.tz = timezone_of(league)
        self.kind = draft_kind(draft, info, cfg)
        self.spec = cfg["drafts"][self.kind]
        self.teams = {tid: str((row or {}).get("name") or tid) for tid, row in (info.get("teamInfo") or {}).items()}
        self.players = players or {}
        self.test = test

    @property
    def name(self) -> str:
        year = (self.draft.date or datetime.now(timezone.utc)).astimezone(self.tz).year
        return f"{year} BLHA {self.spec['name']}"

    def team(self, team_id: str) -> str:
        return self.teams.get(team_id, team_id or "Unknown team")

    def player(self, player_id: str) -> str:
        if not player_id:
            return "*pick not made*"
        row = self.players.get(player_id) or {}
        name = str(row.get("name") or player_id)
        if name.count(",") == 1:
            last, first = (part.strip() for part in name.split(",", 1))
            name = f"{first} {last}"
        bits = [b for b in (row.get("position"), row.get("team")) if b and b != "(N/A)"]
        return f"{name} ({' · '.join(bits)})" if bits else name

    def _payload(self, title: str, description: str, fields: list[dict[str, Any]] | None = None,
                 *, divider: bool = True) -> dict[str, Any]:
        embed: dict[str, Any] = {
            "title": ("[TEST] " if self.test else "") + title,
            "description": description,
            "color": color_value(self.league.get("color")),
            "footer": {"text": "BLHA DRAFT CENTER • FANTRAX READ-ONLY DATA"},
        }
        if fields:
            embed["fields"] = fields
        if divider:
            embed["image"] = {"url": FOOTER_DIVIDER}
        return {"username": "BLHA Draft Center", "avatar_url": AVATAR,
                "allowed_mentions": {"parse": []}, "embeds": [embed]}

    def _when(self) -> str:
        if not self.draft.date:
            return "to be announced"
        ts = int(self.draft.date.timestamp())
        return f"<t:{ts}:F> (<t:{ts}:R>)"

    def format_text(self) -> str:
        rounds = self.draft.rounds or self.spec["rounds"]
        fmt = str(self.info.get("draftType") or self.spec["format"]).lower()
        return f"{rounds} rounds, {fmt}"

    def clock_text(self) -> str:
        override = self.cfg.get("test_pick_clock_minutes")
        clock = f"{int(override)} minutes (test setting)" if override else f"{self.spec['pick_clock_hours']} hours per pick"
        pause = self.cfg.get("pause")
        if pause:
            clock += f", paused nightly {pause[0]}–{pause[1]} ET (Article {self.spec['pause_rule']})"
        return clock

    def details(self) -> list[dict[str, Any]]:
        return [
            {"name": "START", "value": self._when(), "inline": False},
            {"name": "FORMAT", "value": self.format_text(), "inline": False},
            {"name": "PICK CLOCK", "value": self.clock_text(), "inline": False},
            {"name": "DRAFT ROOM", "value": "All selections are made in **Fantrax**, which notifies you when you're on the clock. Keep your queue current so a timeout never costs you a pick.", "inline": False},
        ]

    def countdown(self, offset: str, first: bool) -> dict[str, Any]:
        if offset == "start":
            return self._payload(
                f"{self.name} is underway",
                f"The draft opened {self._when()}. Make your picks in Fantrax. Round-by-round results will appear in {RESULTS_CHANNEL}.",
                self.details()[1:] if first else None,
            )
        if first:
            fields = self.details()
            fields.append({"name": "DRAFT ORDER", "value": f"Posted here {self.cfg.get('order_reveal', '7d').replace('d', ' days').replace('h', ' hours')} before the draft.", "inline": False})
            return self._payload(self.name, "Official draft announcement.", fields)
        label = {"d": "day", "h": "hour", "m": "minute"}[offset[-1]]
        amount = int(offset[:-1])
        return self._payload(f"{self.name}: {amount} {label}{'s' if amount != 1 else ''} to go",
                             f"The draft begins {self._when()}.")

    def date_changed(self, old: datetime | None) -> dict[str, Any]:
        before = f" Previously <t:{int(old.timestamp())}:F>." if old else ""
        return self._payload(f"{self.name}: new start time", f"The draft now begins {self._when()}.{before}",
                             self.details()[1:])

    def order(self, traded: list[dict[str, Any]], update: bool) -> dict[str, Any]:
        snake = "snake" in self.format_text()
        lines = "\n".join(f"**{i}.** {self.team(t)}" for i, t in enumerate(self.draft.order, start=1))
        note = ("Round 1 order. The order reverses every round (snake)." if snake
                else "Every round follows this order unless a pick has been traded.")
        fields = [{"name": "ROUND 1", "value": lines[:1024], "inline": False}]
        if traded:
            rows = []
            for slot in traded:
                where = f"Round {slot['round']}"
                if slot.get("pick"):
                    where += f", pick {slot['pick']}"
                rows.append(f"{where}: **{self.team(slot['current'])}** (from {self.team(slot['original'])})")
            fields.append({"name": "TRADED PICKS", "value": "\n".join(rows)[:1024], "inline": False})
        title = f"{self.name}: {'Draft Order Updated' if update else 'Official Draft Order'}"
        return self._payload(title, note + f"\n\n**Start:** {self._when()}", fields)

    def round_embed(self, number: int) -> dict[str, Any]:
        lines = [f"**{p.label}** · {self.team(p.team_id)} — {self.player(p.player_id)}"
                 for p in self.draft.round_picks(number)]
        return {
            "title": ("[TEST] " if self.test else "") + f"{self.name} · Round {number}",
            "description": "\n".join(lines)[:4096],
            "color": color_value(self.league.get("color")),
            "footer": {"text": "BLHA DRAFT CENTER • OFFICIAL RESULTS ARE IN FANTRAX"},
        }

    def round_messages(self, rounds: list[int]) -> list[tuple[list[int], dict[str, Any]]]:
        """Group round embeds into as few messages as Discord's limits allow."""
        messages: list[tuple[list[int], dict[str, Any]]] = []
        batch: list[dict[str, Any]] = []
        numbers: list[int] = []
        size = 0
        for number in rounds:
            embed = self.round_embed(number)
            chars = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
            if batch and (size + chars > MAX_MESSAGE_CHARS or len(batch) >= MAX_EMBEDS):
                messages.append((numbers, self._wrap(batch)))
                batch, numbers, size = [], [], 0
            batch.append(embed)
            numbers.append(number)
            size += chars
        if batch:
            messages.append((numbers, self._wrap(batch)))
        return messages

    def _wrap(self, embeds: list[dict[str, Any]]) -> dict[str, Any]:
        return {"username": "BLHA Draft Center", "avatar_url": AVATAR,
                "allowed_mentions": {"parse": []}, "embeds": embeds}

    def complete(self) -> dict[str, Any]:
        made = [p for p in self.draft.picks if p.made]
        first = self.draft.round_picks(1)[0] if self.draft.round_picks(1) else None
        # One field rather than two inline ones: phones stack inline fields.
        fields = [{"name": "DRAFT", "value": f"{self.draft.rounds} rounds • {len(made)} picks", "inline": False}]
        if self.draft.start:
            fields.append({"name": "STARTED", "value": f"<t:{int(self.draft.start.timestamp())}:F>", "inline": False})
        finished = self.draft.end or self.draft.last_pick_time()
        if finished:
            fields.append({"name": "FINISHED", "value": f"<t:{int(finished.timestamp())}:F>", "inline": False})
        if first and first.made:
            fields.append({"name": "FIRST OVERALL", "value": f"{self.team(first.team_id)} — {self.player(first.player_id)}", "inline": False})
        fields.append({"name": "OFFICIAL RESULTS", "value": f"Every pick is in {RESULTS_CHANNEL}. Fantrax is the official record.", "inline": False})
        return self._payload(f"{self.name} Complete", f"The {self.name} is officially complete.", fields)

    def alert_task(self, found: list[tuple[dr.Pick, str]], timeouts: dict[str, int]) -> dict[str, Any]:
        items = []
        minutes = clock_minutes(self.kind, self.cfg)
        clock = f"{minutes // 60}-hour" if minutes % 60 == 0 else f"{minutes}-minute"
        for pick, why in found:
            team = self.team(pick.team_id)
            count = timeouts.get(pick.team_id, 0)
            nth = {1: "First", 2: "Second", 3: "Third"}.get(count, f"{count}th")
            if why == "expired":
                items.append(f"Pick {pick.label} (#{pick.overall}): {team}'s {clock} clock has run out. {nth} timeout for {team}.")
            else:
                items.append(f"Pick {pick.label} (#{pick.overall}) was skipped: {team} has not picked and the draft has moved on. They can still make the pick in Fantrax. {nth} timeout for {team}.")
        if self.kind == "startup":
            if any(timeouts.get(p.team_id, 0) >= 2 for p, _ in found):
                items.append("Article 13.5: after two timer expirations you may turn on Fantrax auto-draft for that team, or use the announced timeout procedure, until the manager returns.")
        else:
            items.append("Article 14.3: handle timeouts with the Fantrax queue, auto-draft or a temporary skip, as announced before the draft.")
        title = "Draft: pick clock ran out" if all(w == "expired" for _, w in found) else "Draft: pick skipped"
        if len(found) > 1:
            title = f"Draft: {len(found)} timeouts"
        return {"title": title, "section": f"Article {self.spec['article']}", "items": items}


# --- running -----------------------------------------------------------------------

def _entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    return state.setdefault("drafts", {}).setdefault(key, {})


def run(mode: str, item: str, force: bool) -> int:
    league = load_league()
    cfg = load_config(league)
    tz = timezone_of(league)
    now = datetime.now(timezone.utc)
    fx = Fantrax(str(league["league_id"]), user_agent="BLHA-Draft-Center/1.0")
    info = fx.league_info()
    draft = dr.parse_results(fx.draft_results())
    try:
        traded = dr.traded_slots(fx.draft_picks())
    except Exception as exc:
        print(f"WARNING: could not read pick ownership ({exc}); traded picks not shown")
        traded = []

    state = load_json(STATE_PATH, {}) if mode == "live" else {}
    entry = _entry(state, draft.key) if mode == "live" else {}
    status = draft.status(now)
    print(f"BLHA DRAFT CENTER mode={mode.upper()} item={item} draft={draft.key} state={draft.state or '-'} "
          f"status={status} rounds={draft.rounds} picks_made={sum(p.made for p in draft.picks)}")

    if mode == "test":
        return run_test(league, cfg, info, draft, fx, item)

    # First live run ever with a draft that already finished: record it, post nothing.
    if mode == "live" and "baselined" not in state:
        state["baselined"] = now.isoformat()
        if status == "done":
            entry.update({"rounds_posted": list(range(1, draft.rounds + 1)), "completed_posted": "baseline",
                          "countdown": {t: "baseline" for t in cfg["countdown"]}, "order_posted": "baseline",
                          "order_fp": order_fingerprint(draft.order, traded)})
            state["last_key"] = draft.key
            save_json(STATE_PATH, state)
            print("BASELINE: this draft already finished before the Draft Center first ran; nothing posted.")
            return 0

    render = Renderer(league, cfg, info, draft)
    errors = 0

    def send(secret_key: str, payload: dict[str, Any], label: str) -> bool:
        nonlocal errors
        secret = cfg["webhooks"][secret_key] if secret_key != "desk" else desk.secret_name(league)
        if mode == "preview":
            print(f"PREVIEW {label} -> {secret}:\n{json.dumps(payload, indent=2)[:3000]}")
            return False
        ok, detail = post_discord_webhook(secret, payload)
        print(f"{'POSTED ' if ok else 'ERROR  '} {label}: {detail}")
        if not ok:
            errors += 1
        return ok

    def save() -> None:
        if mode == "live":
            state["last_key"] = draft.key
            save_json(STATE_PATH, state)

    # Date moved after it was announced.
    previous_key = state.get("last_key")
    previous = (state.get("drafts") or {}).get(previous_key or "", {})
    if (item in ("all", "countdown") and previous_key and previous_key != draft.key and status == "pre"
            and previous.get("countdown") and not previous.get("completed_posted")):
        old = dr.parse_dt(previous_key) if previous_key != "undated" else None
        if send("announcements", render.date_changed(old), "date change"):
            entry.setdefault("countdown", {})
            for text in cfg["countdown"]:
                if draft.date and now >= draft.date - parse_offset(text):
                    entry["countdown"][text] = "date-change"
            save()

    if item in ("all", "countdown"):
        offset, skip = plan_countdown(draft, entry, now, cfg)
        if skip and mode == "live":
            for text in skip:
                entry.setdefault("countdown", {})[text] = "skipped"
            save()
        if offset:
            # The first post actually sent for this draft is the full announcement.
            first = not any(v != "skipped" for v in (entry.get("countdown") or {}).values())
            if send("announcements", render.countdown(offset, first), f"countdown {offset}"):
                entry.setdefault("countdown", {})[offset] = now.isoformat()
                save()

    if item in ("all", "order"):
        action = plan_order(draft, traded, entry, now, cfg, force=force and item == "order")
        if action and send("announcements", render.order(traded, action == "update"), f"order {action}"):
            entry["order_posted"] = now.isoformat()
            entry["order_fp"] = order_fingerprint(draft.order, traded)
            save()

    if item in ("all", "recap"):
        rounds, completion = plan_recap(draft, entry, now)
        if rounds or completion:
            players = fx.player_ids()
            render.players = players
            for numbers, payload in render.round_messages(rounds):
                if not send("results", payload, f"rounds {numbers[0]}-{numbers[-1]}"):
                    break
                entry["rounds_posted"] = sorted(set(entry.get("rounds_posted") or []) | set(numbers))
                save()
            else:
                if completion and send("announcements", render.complete(), "draft complete"):
                    entry["completed_posted"] = now.isoformat()
                    save()

    if item in ("all", "alerts"):
        kind = render.kind
        found = plan_alerts(draft, entry, now, tz, clock_minutes(kind, cfg), pause_window(cfg))
        if found:
            timeouts = dict(entry.get("timeouts") or {})
            for pick, _ in found:
                timeouts[pick.team_id] = timeouts.get(pick.team_id, 0) + 1
            task = render.alert_task(found, timeouts)
            for line in task["items"]:
                print("  " + line)
            if send("desk", desk.build_payload(task, None, league, now=now), "private timeout alert"):
                entry["timeouts"] = timeouts
                alerts = entry.setdefault("alerts", {})
                for pick, why in found:
                    alerts[str(pick.overall)] = why
                save()

    if mode == "live":
        save()
    print(f"SUMMARY errors={errors}")
    return 1 if errors else 0


def run_test(league: dict[str, Any], cfg: dict[str, Any], info: dict[str, Any], draft: dr.Draft,
             fx: Fantrax, item: str) -> int:
    players = fx.player_ids() if item in ("all", "recap") and draft.picks else {}
    render = Renderer(league, cfg, info, draft, players, test=True)
    posts: list[tuple[str, dict[str, Any], str]] = []
    if item in ("all", "countdown"):
        posts.append(("announcements", render.countdown("7d", first=True), "sample announcement"))
    if item in ("all", "order") and draft.order:
        posts.append(("announcements", render.order([], update=False), "sample draft order"))
    if item in ("all", "recap") and draft.round_picks(1):
        posts.append(("results", render.round_messages([1])[0][1], "sample round 1"))
        if draft.completed:
            posts.append(("announcements", render.complete(), "sample completion"))
    if item in ("all", "alerts") and draft.picks:
        sample = draft.round_picks(1)[0]
        task = render.alert_task([(sample, "expired")], {sample.team_id: 2})
        task["items"].insert(0, "Sample only. No pick has actually timed out.")
        posts.append(("desk", desk.build_payload(task, None, league, test=True), "sample private alert"))
    errors = 0
    for key, payload, label in posts:
        secret = cfg["webhooks"][key] if key != "desk" else desk.secret_name(league)
        ok, detail = post_discord_webhook(secret, payload)
        print(f"{'POSTED ' if ok else 'ERROR  '} {label} -> {secret}: {detail}")
        errors += 0 if ok else 1
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--item", choices=("all", "countdown", "order", "recap", "alerts"), default="all")
    parser.add_argument("--force", action="store_true",
                        help="Live with --item order: post the draft order now, even before the usual reveal time")
    args = parser.parse_args()
    try:
        return run(args.mode, args.item, args.force)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
