#!/usr/bin/env python3
"""BLHA Phase 2D.1C — The Wire routing, dedupe and Discord delivery engine.

Architecture:
  GitHub Actions = brain
  Discord webhooks = delivery
  Native integrations = preferred where superior (PuckPedia transactions)
  Discord bot = deferred to a later interactive phase

Scheduled production should remain in SHADOW mode until webhook secrets and
routing behavior have been validated. Live mode is implemented but intentionally
safe: the first live run establishes a baseline and sends nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
import yaml

import wire

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"
STATE_DIR = ROOT / "state"
STATE_TTL_HOURS = 72
DEDUPE_WINDOW_HOURS = 48
MAX_SOURCE_ITEMS = 15

WEBHOOK_ENV = {
    "breaking-news": "BLHA_WEBHOOK_BREAKING_NEWS",
    "nhl-news": "BLHA_WEBHOOK_NHL_NEWS",
    "injury-report": "BLHA_WEBHOOK_INJURY_REPORT",
    "nhl-transactions": "BLHA_WEBHOOK_NHL_TRANSACTIONS",
    "prospect-wire": "BLHA_WEBHOOK_PROSPECT_WIRE",
}

CHANNEL_LABELS = {
    "breaking-news": "🚨 BREAKING NEWS",
    "nhl-news": "📰 NHL NEWS",
    "injury-report": "🏥 INJURY REPORT",
    "nhl-transactions": "🔄 NHL TRANSACTIONS",
    "prospect-wire": "🌱 PROSPECT WIRE",
}

CHANNEL_COLORS = {
    "breaking-news": 0xC73E3A,
    "nhl-news": 0xFFB81C,
    "injury-report": 0xD97706,
    "nhl-transactions": 0xFFB81C,
    "prospect-wire": 0xC68F15,
}

WEBHOOK_AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat().replace("+00:00", "Z")


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def stable_key(source_id: str, entry: dict) -> str:
    external = entry.get("external_id") or canonical_url(entry.get("link", "")) or entry.get("title", "")
    raw = f"{source_id}|{external}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def empty_state() -> dict:
    return {"version": 1, "initialized": False, "updated_at": "", "seen": []}


def load_state(mode: str) -> tuple[dict, Path]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{mode}.json"
    if not path.exists():
        return empty_state(), path
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("seen"), list):
            raise ValueError("invalid state shape")
        return state, path
    except Exception as exc:
        print(f"WARNING: could not read {path}: {exc}; starting clean")
        return empty_state(), path


def save_state(state: dict, path: Path) -> None:
    state["updated_at"] = iso_now()
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_seen_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def prune_state(state: dict) -> None:
    cutoff = now_utc() - timedelta(hours=STATE_TTL_HOURS)
    kept = []
    for item in state.get("seen", []):
        seen_at = parse_seen_time(item.get("seen_at", ""))
        if seen_at is None or seen_at >= cutoff:
            kept.append(item)
    state["seen"] = kept[-1000:]


def duplicate_reason(candidate: dict, state: dict) -> str | None:
    now = now_utc()
    title_norm = wire.normalize(candidate["title"])
    url = canonical_url(candidate.get("link", ""))
    fp = wire.fingerprint(candidate["title"])

    for prior in reversed(state.get("seen", [])):
        seen_at = parse_seen_time(prior.get("seen_at", ""))
        if seen_at and now - seen_at > timedelta(hours=DEDUPE_WINDOW_HOURS):
            continue
        if candidate["key"] == prior.get("key"):
            return "same-source-id"
        if url and url == prior.get("url"):
            return "same-url"
        if fp == prior.get("fingerprint"):
            return "same-headline"
        if candidate["channel"] == prior.get("channel"):
            prior_title = prior.get("title_norm", "")
            if prior_title:
                ratio = SequenceMatcher(None, title_norm, prior_title).ratio()
                if ratio >= 0.88:
                    return f"near-duplicate:{ratio:.2f}"
    return None


def remember(candidate: dict, state: dict) -> None:
    state.setdefault("seen", []).append({
        "key": candidate["key"],
        "url": canonical_url(candidate.get("link", "")),
        "fingerprint": wire.fingerprint(candidate["title"]),
        "title_norm": wire.normalize(candidate["title"]),
        "channel": candidate["channel"],
        "source_id": candidate["source_id"],
        "tier": candidate["tier"],
        "seen_at": iso_now(),
    })


def build_candidate(source: dict, entry: dict) -> dict:
    title = entry.get("title", "(untitled)")
    channel = wire.route(title, source)
    return {
        "key": stable_key(source.get("id", "source"), entry),
        "title": title,
        "link": entry.get("link", ""),
        "published": entry.get("published", ""),
        "source_id": source.get("id", ""),
        "source_name": source.get("name", source.get("id", "Unknown")),
        "source_detail": entry.get("source_detail", ""),
        "tier": int(source.get("tier", 9)),
        "channel": channel,
        "discovery_only": bool(source.get("discovery_only", False)),
        "player": entry.get("player", ""),
        "team": entry.get("team", ""),
        "status": entry.get("status", ""),
    }


def fetch_candidates(config: dict) -> list[dict]:
    candidates: list[dict] = []
    sources = [s for s in config.get("sources", []) if s.get("enabled", False)]
    sources.sort(key=lambda s: (int(s.get("tier", 9)), s.get("name", "")))

    for source in sources:
        try:
            entries = wire.fetch_source(source)
        except Exception as exc:
            print(f"SOURCE ERROR [{source.get('name')}]: {exc}")
            continue
        count = 0
        for entry in entries:
            candidate = build_candidate(source, entry)
            if wire.should_ignore(candidate["title"], candidate["source_id"], candidate["channel"]):
                continue
            candidates.append(candidate)
            count += 1
            if count >= MAX_SOURCE_ITEMS:
                break
    return candidates


def discord_payload(candidate: dict) -> dict:
    channel = candidate["channel"]
    source_line = candidate["source_name"]
    if candidate.get("source_detail"):
        source_line += f" • {candidate['source_detail']}"

    description = f"**Source:** {source_line}"
    if candidate.get("published"):
        description += f"\n**Published:** {candidate['published']}"

    return {
        "username": "BLHA News Wire",
        "avatar_url": WEBHOOK_AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": candidate["title"][:256],
            "url": candidate.get("link", "") or None,
            "description": description[:4096],
            "color": CHANNEL_COLORS.get(channel, 0xFFB81C),
            "footer": {"text": f"{CHANNEL_LABELS.get(channel, channel)} • BLHA THE WIRE"},
        }],
    }


def deliver(candidate: dict) -> bool:
    env_name = WEBHOOK_ENV.get(candidate["channel"])
    if not env_name:
        print(f"DELIVERY SKIP: no webhook mapping for {candidate['channel']}")
        return False
    webhook = os.getenv(env_name, "").strip()
    if not webhook:
        print(f"DELIVERY SKIP: missing GitHub Actions secret {env_name}")
        return False

    payload = discord_payload(candidate)
    response = requests.post(webhook, params={"wait": "true"}, json=payload, timeout=25)
    if response.status_code not in (200, 204):
        print(f"DELIVERY ERROR {response.status_code}: {response.text[:300]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("shadow", "live"), default="shadow")
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    state, state_path = load_state(args.mode)
    if args.reset_state:
        state = empty_state()

    prune_state(state)
    candidates = fetch_candidates(cfg)
    print(f"BLHA THE WIRE — mode={args.mode.upper()} candidates={len(candidates)}")

    # Live safety rail: first live invocation only establishes the baseline.
    if args.mode == "live" and not state.get("initialized", False):
        baseline = 0
        for candidate in candidates:
            if candidate["discovery_only"]:
                continue
            remember(candidate, state)
            baseline += 1
        state["initialized"] = True
        save_state(state, state_path)
        print(f"LIVE BASELINE CREATED: {baseline} current items recorded; 0 Discord messages sent.")
        return 0

    posted = 0
    shadowed = 0
    duplicates = 0
    discovery = 0

    for candidate in candidates:
        prefix = f"[{candidate['channel']}] {candidate['source_name']}"

        if candidate["discovery_only"]:
            discovery += 1
            if args.mode == "shadow":
                print(f"DISCOVERY {prefix}: {candidate['title']}")
            continue

        reason = duplicate_reason(candidate, state)
        if reason:
            duplicates += 1
            continue

        if args.mode == "shadow":
            print(f"SHADOW {prefix}: {candidate['title']}")
            remember(candidate, state)
            shadowed += 1
        else:
            if deliver(candidate):
                print(f"POSTED {prefix}: {candidate['title']}")
                remember(candidate, state)
                posted += 1
            else:
                print(f"NOT POSTED {prefix}: {candidate['title']}")

    state["initialized"] = True
    prune_state(state)
    save_state(state, state_path)

    print(
        f"SUMMARY mode={args.mode} posted={posted} shadowed={shadowed} "
        f"duplicates={duplicates} discovery={discovery} state={state_path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
