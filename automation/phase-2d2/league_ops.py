#!/usr/bin/env python3
"""BLHA Phase 2D.2 — League Office calendar/deadline automation.

GitHub Actions is the scheduler/brain. Discord webhooks are delivery.
The module is intentionally independent of Fantrax so league milestones and
commissioner deadlines can be automated without paid services.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "events.yaml"
STATE_PATH = ROOT / "state" / "league_ops.json"
AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)
RUN_WINDOW_MINUTES = 20


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"sent": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sent": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_offset(value: str) -> timedelta:
    value = value.strip().lower()
    if value == "start":
        return timedelta(0)
    unit = value[-1]
    amount = int(value[:-1])
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    raise ValueError(f"unsupported reminder offset: {value}")


def parse_event_time(raw: str | None, local_tz: ZoneInfo) -> datetime | None:
    """Parse event time; naive ISO values are interpreted in the configured zone.

    This lets events.yaml use local wall-clock times such as
    `2027-01-15T20:00:00` without manually choosing -05:00 vs -04:00.
    Explicit offsets and Z timestamps remain supported.
    """
    if not raw:
        return None
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(local_tz)


def reminder_label(offset: str) -> str:
    if offset == "start":
        return "NOW"
    unit = offset[-1]
    amount = int(offset[:-1])
    names = {"d": "DAY", "h": "HOUR", "m": "MINUTE"}
    word = names[unit] + ("" if amount == 1 else "S")
    return f"{amount} {word}"


def event_color(priority: str, fallback: int) -> int:
    if priority == "high":
        return 0xD4AF37
    return fallback


def build_payload(event: dict, channel_cfg: dict, reminder: str, starts_at: datetime, test: bool = False) -> dict:
    unix = int(starts_at.timestamp())
    title_prefix = "[TEST] " if test else ""
    when = "starts now" if reminder == "start" else f"is in {reminder_label(reminder).lower()}"
    description = event.get("description", "").strip()
    body = f"**{event['title']}** {when}."
    if description:
        body += f"\n\n{description}"
    body += f"\n\n**When:** <t:{unix}:F>\n**Relative:** <t:{unix}:R>"

    return {
        "username": "BLHA League Office",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"{title_prefix}{channel_cfg['label']} — {event['title']}",
                "description": body,
                "color": event_color(event.get("priority", "normal"), int(channel_cfg["color"], 16) if isinstance(channel_cfg["color"], str) else channel_cfg["color"]),
                "footer": {"text": f"BLHA LEAGUE OFFICE • {reminder_label(reminder)} REMINDER"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def post_webhook(secret_name: str, payload: dict) -> tuple[bool, str]:
    url = os.getenv(secret_name, "").strip()
    if not url:
        return False, f"missing secret {secret_name}"
    try:
        response = requests.post(url, params={"wait": "true"}, json=payload, timeout=25)
    except Exception as exc:
        return False, f"request failed: {exc}"
    if response.status_code not in (200, 204):
        return False, f"Discord returned {response.status_code}: {response.text[:250]}"
    return True, "delivered"


def due(now: datetime, trigger: datetime) -> bool:
    delta = abs((now - trigger).total_seconds())
    return delta <= RUN_WINDOW_MINUTES * 60


def run(mode: str, reset_state: bool = False) -> int:
    config = load_config()
    tz = ZoneInfo(config.get("settings", {}).get("timezone", "America/New_York"))
    now = datetime.now(tz)
    state = {"sent": {}} if reset_state else load_state()
    sent = state.setdefault("sent", {})
    channels = config.get("channels", {})
    defaults = config.get("settings", {}).get("default_reminders", [])

    print(f"BLHA LEAGUE OFFICE — mode={mode.upper()} now={now.isoformat()}")
    examined = posted = dry = duplicate = skipped = errors = 0

    for event in config.get("events", []):
        if not event.get("enabled", False):
            skipped += 1
            continue
        try:
            starts_at = parse_event_time(event.get("starts_at"), tz)
        except Exception as exc:
            print(f"CONFIG ERROR [{event.get('id','unknown')}]: {exc}")
            errors += 1
            continue
        if not starts_at:
            print(f"CONFIG SKIP [{event.get('id','unknown')}]: no starts_at")
            skipped += 1
            continue

        reminders = event.get("reminders") or defaults
        calendar_channel = event.get("channel", config.get("settings", {}).get("default_channel", "league-calendar"))
        announcement_reminders = set(event.get("announcement_reminders", []))

        for reminder in reminders:
            examined += 1
            trigger = starts_at - parse_offset(reminder)
            destinations = [calendar_channel]
            if reminder in announcement_reminders and "league-announcements" not in destinations:
                destinations.append("league-announcements")

            if not due(now, trigger):
                continue

            for channel in destinations:
                key = f"{event['id']}::{reminder}::{channel}"
                if key in sent:
                    duplicate += 1
                    continue
                channel_cfg = channels.get(channel)
                if not channel_cfg:
                    print(f"CONFIG ERROR [{key}]: unknown channel {channel}")
                    errors += 1
                    continue

                if mode == "dry-run":
                    print(f"DRY-RUN [{channel}] {event['title']} — {reminder_label(reminder)}")
                    dry += 1
                    continue

                payload = build_payload(event, channel_cfg, reminder, starts_at)
                ok, detail = post_webhook(channel_cfg["secret"], payload)
                if ok:
                    print(f"POSTED [{channel}] {event['title']} — {reminder_label(reminder)}")
                    sent[key] = datetime.now(timezone.utc).isoformat()
                    posted += 1
                else:
                    print(f"DELIVERY ERROR [{channel}] {event['title']}: {detail}")
                    errors += 1

    if mode == "live":
        save_state(state)

    print(
        f"SUMMARY mode={mode} examined={examined} posted={posted} dry={dry} "
        f"duplicates={duplicate} skipped={skipped} errors={errors}"
    )
    return 1 if errors else 0


def test_channel(channel: str) -> int:
    config = load_config()
    channels = config.get("channels", {})
    cfg = channels.get(channel)
    if not cfg:
        print(f"ERROR: unknown channel {channel}")
        return 1
    now = datetime.now(timezone.utc)
    event = {
        "id": "controlled-test",
        "title": "League Office Delivery Test",
        "description": "Controlled test only. No league deadline or event is being announced.",
        "priority": "normal",
    }
    payload = build_payload(event, cfg, "1h", now + timedelta(hours=1), test=True)
    ok, detail = post_webhook(cfg["secret"], payload)
    print(("PASS" if ok else "ERROR") + f" [{channel}]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "live", "test"), default="dry-run")
    parser.add_argument("--channel", choices=("league-calendar", "league-announcements"))
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    if args.mode == "test":
        if not args.channel:
            parser.error("--channel is required with --mode test")
        return test_channel(args.channel)
    return run(args.mode, args.reset_state)


if __name__ == "__main__":
    sys.exit(main())
