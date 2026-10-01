#!/usr/bin/env python3
"""BLHA Phase 2D.1C — The Wire routing, dedupe and Discord delivery engine.

Architecture:
  GitHub Actions = brain
  Discord webhooks = delivery
  Native integrations = preferred where superior (PuckPedia transactions)
  Discord bot = deferred to a later interactive phase
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
import yaml

import wire

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"
STATE_DIR = ROOT / "state"
STATE_TTL_HOURS = 24 * 30
FUZZY_DEDUPE_WINDOW_HOURS = 48
DEFAULT_MAX_SOURCE_ITEMS = 15
MAX_SOURCE_WORKERS = 4
FANTRAX_BASE = "https://www.fantrax.com/fxea/general"

# Production flood guards. Normal 15-minute runs should produce only a handful
# of truly new items. If a feed/parser suddenly exposes a backlog, these limits
# prevent Discord from being flooded. Suppressed items are remembered so they do
# not trickle out over later runs.
MAX_LIVE_POSTS_PER_RUN = 6
MAX_LIVE_POSTS_PER_CHANNEL = 3

# Channels handled primarily by a superior native integration. The GitHub engine
# still collects/classifies/dedupes these stories, but does not post them live.
NATIVE_PRIMARY_CHANNELS = {"nhl-transactions"}

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
    state["seen"] = kept[-5000:]


def duplicate_reason(candidate: dict, state: dict) -> str | None:
    now = now_utc()
    title_norm = wire.normalize(candidate["title"])
    url = canonical_url(candidate.get("link", ""))
    fp = wire.fingerprint(candidate["title"])

    for prior in reversed(state.get("seen", [])):
        if candidate["key"] == prior.get("key"):
            return "same-source-id"
        if candidate.get("dedupe_by_url", True) and url and url == prior.get("url"):
            return "same-url"
        if fp == prior.get("fingerprint"):
            return "same-headline"

        seen_at = parse_seen_time(prior.get("seen_at", ""))
        if seen_at and now - seen_at > timedelta(hours=FUZZY_DEDUPE_WINDOW_HOURS):
            continue
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
        "dedupe_by_url": bool(source.get("dedupe_by_url", True)),
        "player": entry.get("player", ""),
        "team": entry.get("team", ""),
        "status": entry.get("status", ""),
        "fantasy_owner": "",
    }


def source_candidates(source: dict) -> list[dict]:
    entries = wire.fetch_source(source)
    candidates: list[dict] = []
    max_items = int(source.get("max_items", DEFAULT_MAX_SOURCE_ITEMS))
    for entry in entries:
        candidate = build_candidate(source, entry)
        if wire.should_ignore(candidate["title"], candidate["source_id"], candidate["channel"]):
            continue
        candidates.append(candidate)
        if len(candidates) >= max_items:
            break
    return candidates


def fetch_candidates(config: dict, include_discovery: bool = False) -> list[dict]:
    sources = [
        source
        for source in config.get("sources", [])
        if source.get("enabled", False)
        and (include_discovery or not source.get("discovery_only", False))
    ]
    sources.sort(key=lambda source: (int(source.get("tier", 9)), source.get("name", "")))
    if not sources:
        return []

    by_id: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_SOURCE_WORKERS, len(sources))) as pool:
        future_to_source = {pool.submit(source_candidates, source): source for source in sources}
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            source_id = str(source.get("id") or source.get("name") or id(source))
            try:
                by_id[source_id] = future.result()
            except Exception as exc:
                print(f"SOURCE ERROR [{source.get('name')}]: {exc}")
                by_id[source_id] = []

    candidates: list[dict] = []
    for source in sources:
        source_id = str(source.get("id") or source.get("name") or id(source))
        candidates.extend(by_id.get(source_id, []))
    return candidates


def normalize_player_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def extract_player_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("playerName", "fullName", "name"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    for key in ("player", "playerInfo"):
        nested = value.get(key)
        if isinstance(nested, dict):
            found = extract_player_name(nested)
            if found:
                return found
    return ""


def roster_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("players", "roster", "rows"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def fantrax_ownership(league_id: str) -> dict[str, str]:
    if not league_id:
        return {}
    session = requests.Session()
    session.headers.update({
        "User-Agent": "BLHA-Wire-Fantrax-Enrichment/1.0",
        "Accept": "application/json,text/plain,*/*",
    })
    try:
        standings_response = session.get(
            f"{FANTRAX_BASE}/getStandings",
            params={"leagueId": league_id},
            timeout=15,
        )
        standings_response.raise_for_status()
        standings = standings_response.json()
        roster_response = session.get(
            f"{FANTRAX_BASE}/getTeamRosters",
            params={"leagueId": league_id},
            timeout=15,
        )
        roster_response.raise_for_status()
        rosters = roster_response.json()
    except Exception as exc:
        print(f"ROSTER ENRICHMENT WARNING: Fantrax read failed: {exc}")
        return {}

    team_names: dict[str, str] = {}
    if isinstance(standings, list):
        for row in standings:
            if isinstance(row, dict):
                team_id = str(row.get("teamId") or "")
                team_name = str(row.get("teamName") or "")
                if team_id and team_name:
                    team_names[team_id] = team_name

    roster_block = rosters.get("rosters") if isinstance(rosters, dict) else None
    if not isinstance(roster_block, dict):
        print("ROSTER ENRICHMENT WARNING: Fantrax rosters block was not a dict")
        return {}

    ownership: dict[str, str] = {}
    for team_id, raw_roster in roster_block.items():
        owner = team_names.get(str(team_id), "")
        if not owner:
            continue
        for row in roster_rows(raw_roster):
            player = extract_player_name(row)
            key = normalize_player_name(player)
            if key:
                ownership[key] = owner
    print(f"ROSTER ENRICHMENT: loaded {len(ownership)} rostered player names")
    return ownership


def enrich_injury_ownership(candidates: list[dict], config: dict) -> None:
    fantrax_cfg = config.get("fantrax") if isinstance(config.get("fantrax"), dict) else {}
    if not fantrax_cfg.get("roster_enrichment", False):
        return
    injuries = [candidate for candidate in candidates if candidate.get("channel") == "injury-report" and candidate.get("player")]
    if not injuries:
        return
    ownership = fantrax_ownership(str(fantrax_cfg.get("league_id") or "").strip())
    if not ownership:
        return
    matched = 0
    for candidate in injuries:
        owner = ownership.get(normalize_player_name(candidate.get("player", "")), "")
        if owner:
            candidate["fantasy_owner"] = owner
            matched += 1
    print(f"ROSTER ENRICHMENT: matched {matched}/{len(injuries)} injury items to BLHA rosters")


def published_timestamp(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def discord_payload(candidate: dict) -> dict:
    channel = candidate["channel"]
    source_line = candidate["source_name"]
    if candidate.get("source_detail"):
        source_line += f" • {candidate['source_detail']}"

    description = f"**Source:** {source_line}"
    if candidate.get("fantasy_owner"):
        description += f"\n**BLHA roster:** {candidate['fantasy_owner']}"

    timestamp = published_timestamp(candidate.get("published", ""))
    if not timestamp and candidate.get("published"):
        description += f"\n**Published:** {candidate['published']}"

    embed = {
        "title": candidate["title"][:256],
        "url": candidate.get("link", "") or None,
        "description": description[:4096],
        "color": CHANNEL_COLORS.get(channel, 0xFFB81C),
        "footer": {"text": f"{CHANNEL_LABELS.get(channel, channel)} • BLHA THE WIRE"},
    }
    if timestamp:
        embed["timestamp"] = timestamp

    return {
        "username": "BLHA News Wire",
        "avatar_url": WEBHOOK_AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
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

    for attempt in range(3):
        try:
            response = requests.post(
                webhook,
                params={"wait": "true"},
                json=discord_payload(candidate),
                timeout=20,
            )
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            print(f"DELIVERY ERROR: request failed after retries: {exc}")
            return False

        if response.status_code in (200, 204):
            return True

        if response.status_code == 429 and attempt < 2:
            delay = 1.0
            try:
                delay = float(response.json().get("retry_after", delay))
            except Exception:
                try:
                    delay = float(response.headers.get("Retry-After", delay))
                except ValueError:
                    pass
            time.sleep(min(max(delay, 0.5), 10.0))
            continue

        if 500 <= response.status_code <= 599 and attempt < 2:
            time.sleep(2 ** attempt)
            continue

        print(f"DELIVERY ERROR {response.status_code}: {response.text[:300]}")
        return False

    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("shadow", "live"), default="shadow")
    parser.add_argument("--reset-state", action="store_true")
    parser.add_argument("--include-discovery", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    state, state_path = load_state(args.mode)
    if args.reset_state:
        state = empty_state()
        print(f"STATE RESET requested for {args.mode}")

    prune_state(state)
    candidates = fetch_candidates(cfg, include_discovery=args.include_discovery)
    enrich_injury_ownership(candidates, cfg)
    print(
        f"BLHA THE WIRE — mode={args.mode.upper()} candidates={len(candidates)} "
        f"include_discovery={args.include_discovery}"
    )

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

    posted = shadowed = duplicates = discovery = native_skipped = suppressed = 0
    posted_by_channel: dict[str, int] = {}

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
            owner_note = f" [BLHA roster: {candidate['fantasy_owner']}]" if candidate.get("fantasy_owner") else ""
            print(f"SHADOW {prefix}: {candidate['title']}{owner_note}")
            remember(candidate, state)
            shadowed += 1
            continue

        if candidate["channel"] in NATIVE_PRIMARY_CHANNELS:
            print(f"NATIVE-PRIMARY SKIP {prefix}: {candidate['title']}")
            remember(candidate, state)
            native_skipped += 1
            continue

        channel_count = posted_by_channel.get(candidate["channel"], 0)
        if posted >= MAX_LIVE_POSTS_PER_RUN or channel_count >= MAX_LIVE_POSTS_PER_CHANNEL:
            print(f"RATE-GUARD SUPPRESSED {prefix}: {candidate['title']}")
            remember(candidate, state)
            suppressed += 1
            continue

        if deliver(candidate):
            print(f"POSTED {prefix}: {candidate['title']}")
            remember(candidate, state)
            posted += 1
            posted_by_channel[candidate["channel"]] = channel_count + 1
        else:
            print(f"NOT POSTED {prefix}: {candidate['title']}")

    state["initialized"] = True
    prune_state(state)
    save_state(state, state_path)

    print(
        f"SUMMARY mode={args.mode} posted={posted} shadowed={shadowed} "
        f"duplicates={duplicates} discovery={discovery} native_skipped={native_skipped} "
        f"suppressed={suppressed} state={state_path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
