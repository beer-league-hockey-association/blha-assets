#!/usr/bin/env python3
"""BLHA Commissioner Desk: private reminders for the manual work that keeps the league on track.

Reads the Fantrax season calendar, works out when each task in tasks.yaml is
due (an anchor such as "the last regular week is final" plus an offset) and
posts one checklist reminder per task to the private commissioner channel.
Nothing is ever posted twice. A reminder that is late (GitHub or the
scheduler was down) is still posted, marked OVERDUE, until its overdue window
ends, so an outage cannot make you forget a task. The first live run records
anything already long past as handled so old reminders never flood the channel.

Dated reminders that Fantrax cannot know (dues deadline, draft announcement,
trading reopening) live in automation/league-office/events.yaml and use the
same channel.

Modes:
  preview  print every task with its trigger time and status; no Discord, no state change
  test     send one clearly labeled [TEST] message to the channel; no state change
  live     post what is due and record it
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from blha import season  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import AVATAR, color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402

TASKS_PATH = ROOT / "tasks.yaml"
STATE_PATH = ROOT / "state" / "commissioner.json"
DEFAULT_SECRET = "BLHA_WEBHOOK_COMMISSIONER_DESK"
DEFAULT_CATCHUP = timedelta(hours=36)


def parse_offset(value: Any) -> timedelta:
    """Parse offsets such as 2h, -6h, 14d, 30m. 0 or start means no offset."""
    text = str(value).strip().lower()
    if text in ("0", "start", ""):
        return timedelta(0)
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    unit, amount = text[-1], int(text[:-1])
    if unit == "d":
        return sign * timedelta(days=amount)
    if unit == "h":
        return sign * timedelta(hours=amount)
    if unit == "m":
        return sign * timedelta(minutes=amount)
    raise ValueError(f"unsupported offset: {value!r}")


def load_tasks(path: Path = TASKS_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks.yaml must define a non-empty tasks list")
    seen: set[str] = set()
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id or task_id in seen:
            raise ValueError(f"task id missing or duplicated: {task_id!r}")
        seen.add(task_id)
        for field in ("anchor", "title", "items"):
            if not task.get(field):
                raise ValueError(f"task {task_id}: {field} is required")
        parse_offset(task.get("offset", 0))
    data.setdefault("settings", {})
    return data


def anchors_from(info: dict[str, Any], tz: ZoneInfo, settings: dict[str, Any]) -> dict[str, datetime]:
    """Anchor name -> moment (UTC), for every anchor the Fantrax calendar supports."""
    weeks = season.periods(info)
    if not weeks:
        return {}
    last_regular, first_playoff, _ = season.playoff_settings(info)
    out: dict[str, datetime] = {"first_week_start": weeks[0].start}

    deadline = season.period(info, last_regular - int(settings.get("trade_deadline_weeks_before_end", 2)))
    if deadline:
        out["trade_deadline_final"] = season.final_at(deadline, tz)
    final_regular = season.period(info, last_regular)
    if final_regular:
        out["last_regular_final"] = season.final_at(final_regular, tz)
    for number in range(first_playoff, weeks[-1].number + 1):
        p = season.period(info, number)
        if p:
            out[f"playoff_start:{number - first_playoff + 1}"] = p.start
    out["season_end_final"] = season.final_at(weeks[-1], tz)
    return out


def is_countdown(task: dict[str, Any]) -> bool:
    """A countdown reminds about an event that is still ahead (negative offset)."""
    return task.get("overdue_days") is None and parse_offset(task.get("offset", 0)) < timedelta(0)


def overdue_until(task: dict[str, Any], anchor: datetime, trigger: datetime, default_days: float) -> datetime:
    """Last moment a late reminder is still worth posting.

    A countdown (negative offset, such as "starts in 6 hours") is useless once
    its event has started, so it ends at the anchor. Anything else stays
    relevant for overdue_days after its trigger.
    """
    if is_countdown(task):
        return anchor
    return trigger + timedelta(days=float(task.get("overdue_days", default_days)))


@dataclass
class Decision:
    task_id: str
    title: str
    trigger: datetime | None
    status: str  # send | overdue | sent | early | expired | no-anchor


def plan(
    tasks: list[dict[str, Any]],
    anchors: dict[str, datetime],
    sent: dict[str, str],
    now: datetime,
    catchup: timedelta,
    overdue_days: float = 7,
) -> list[Decision]:
    """Decide what to do with each task right now.

    send     due within the on-time window
    overdue  later than that but inside the task's overdue window: still posted
    expired  past the overdue window: no longer relevant, never posted
    """
    decisions: list[Decision] = []
    for task in tasks:
        anchor = anchors.get(str(task["anchor"]))
        if anchor is None:
            decisions.append(Decision(task["id"], task["title"], None, "no-anchor"))
            continue
        trigger = anchor + parse_offset(task.get("offset", 0))
        key = f"{task['id']}@{trigger.isoformat()}"
        if key in sent:
            status = "sent"
        elif now < trigger:
            status = "early"
        elif is_countdown(task) and now > anchor:
            status = "expired"
        elif now <= trigger + catchup:
            status = "send"
        elif now <= overdue_until(task, anchor, trigger, overdue_days):
            status = "overdue"
        else:
            status = "expired"
        decisions.append(Decision(task["id"], task["title"], trigger, status))
    return decisions


def state_key(task_id: str, trigger: datetime) -> str:
    return f"{task_id}@{trigger.isoformat()}"


def build_payload(
    task: dict[str, Any],
    trigger: datetime | None,
    cfg: dict[str, Any],
    *,
    test: bool = False,
    overdue: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    desk_cfg = cfg.get("commissioner_desk") or {}
    ping = str(desk_cfg.get("ping_user_id") or "").strip()
    lines = [f"☐ {item}" for item in task["items"]]
    body = "\n".join(lines)
    section = task.get("section")
    footer = "BLHA COMMISSIONER DESK"
    if section:
        footer += f" • CHECKLIST {section.upper()}"
    when = ""
    if trigger:
        label = "**Was due:**" if overdue else "**Due:**"
        when = f"\n\n{label} <t:{int(trigger.timestamp())}:F>"
    if overdue:
        body = "This reminder is late, so it may have been missed. Please check it now.\n\n" + body
    payload: dict[str, Any] = {
        "username": "BLHA Commissioner Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"users": [ping]} if ping else {"parse": []},
        "embeds": [{
            "title": ("[TEST] " if test else "") + ("OVERDUE: " if overdue else "") + task["title"],
            "description": body + when,
            "color": color_value(cfg.get("color")),
            "footer": {"text": footer},
            "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        }],
    }
    if ping:
        payload["content"] = f"<@{ping}>"
    return payload


def secret_name(cfg: dict[str, Any]) -> str:
    return str((cfg.get("commissioner_desk") or {}).get("webhook") or DEFAULT_SECRET)


def run(mode: str, now: datetime | None = None) -> int:
    cfg = load_league()
    tz = timezone_of(cfg)
    data = load_tasks()
    settings = data["settings"]
    catchup = timedelta(hours=float(settings.get("catchup_window_hours", 36)))
    now = now or datetime.now(timezone.utc)

    state = load_json(STATE_PATH, {})
    sent: dict[str, str] = state.setdefault("sent", {})
    stored: dict[str, str] = state.setdefault("anchors", {})

    print(f"BLHA COMMISSIONER DESK mode={mode.upper()} now={now.astimezone(tz).isoformat()}")

    try:
        info = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Commissioner-Desk/1.0").league_info()
        anchors = anchors_from(info, tz, settings)
    except Exception as exc:
        print(f"WARNING: could not read Fantrax ({exc}); using saved anchors only")
        anchors = {}
    # Remember anchors so a countdown (for example the 30-day prize deadline)
    # survives the day the league is rolled over to the next season in Fantrax.
    for name, moment in anchors.items():
        stored[name] = moment.isoformat()
    for name, text in stored.items():
        anchors.setdefault(name, datetime.fromisoformat(text))

    by_id = {t["id"]: t for t in data["tasks"]}
    overdue_days = float(settings.get("overdue_window_days", 7))
    decisions = plan(data["tasks"], anchors, sent, now, catchup, overdue_days)
    if mode == "live" and not state.get("baselined"):
        # First live run: anything already long past is history, not a missed task.
        for d in decisions:
            if d.status in ("overdue", "expired") and d.trigger:
                sent[state_key(d.task_id, d.trigger)] = "baseline"
                d.status = "sent"
        state["baselined"] = datetime.now(timezone.utc).isoformat()
        print("First live run: past reminders recorded as handled.")
    elif mode == "preview" and not state.get("baselined"):
        print("NOTE: the first live run records past reminders as handled so they are not posted.")
    errors = posted = 0
    for d in decisions:
        when = d.trigger.astimezone(tz).strftime("%a %b %d %Y %I:%M %p %Z") if d.trigger else "n/a"
        print(f"{d.status.upper():9} {d.task_id:16} {when}  {d.title}")
        if d.status not in ("send", "overdue"):
            continue
        if mode == "preview":
            continue
        payload = build_payload(by_id[d.task_id], d.trigger, cfg, overdue=d.status == "overdue", now=now)
        ok, detail = post_discord_webhook(secret_name(cfg), payload)
        if ok:
            posted += 1
            sent[state_key(d.task_id, d.trigger)] = datetime.now(timezone.utc).isoformat()
            print(f"POSTED    {d.task_id}")
        else:
            errors += 1
            print(f"DELIVERY ERROR {d.task_id}: {detail}")

    if mode == "live":
        save_json(STATE_PATH, state)
    print(f"SUMMARY mode={mode} due={sum(d.status in ('send', 'overdue') for d in decisions)} posted={posted} errors={errors}")
    return 1 if errors else 0


def test_post() -> int:
    cfg = load_league()
    task = {
        "title": "Commissioner Desk delivery test",
        "items": ["Controlled test only. Nothing is due and no league deadline is being announced."],
        "section": "TEST",
    }
    ok, detail = post_discord_webhook(secret_name(cfg), build_payload(task, None, cfg, test=True))
    print(("PASS" if ok else "ERROR") + f" [commissioner-desk]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--at", help="Preview as if it were this local time, e.g. 2027-03-08T08:00")
    args = parser.parse_args()

    if args.mode == "test":
        return test_post()
    now = None
    if args.at:
        if args.mode == "live":
            parser.error("--at is for preview only")
        tz = timezone_of(load_league())
        now = datetime.fromisoformat(args.at)
        now = (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(timezone.utc)
    return run(args.mode, now)


if __name__ == "__main__":
    sys.exit(main())
