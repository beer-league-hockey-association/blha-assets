#!/usr/bin/env python3
"""BLHA Phase 2D.1 — The Wire source collectors and dry-run classifier.

This module is shared by the production/shadow engine. It fetches configured
public hockey sources, normalizes entries, and classifies them into BLHA Wire
channels. Direct Discord delivery lives in engine.py.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"
USER_AGENT = "BLHA-The-Wire/0.4 (+https://github.com/diseasewheeze/blha-assets)"

BREAKING = (
    "out indefinitely", "season-ending", "out for the season", "suspended indefinitely",
    "retires", "announces retirement", "fired", "dismissed", "blockbuster trade",
)
INJURY = (
    "injury", "injured", "day-to-day", "week-to-week", "month-to-month",
    "injured reserve", "ltir", "surgery", "concussion", "fractured", "fracture",
    "activated from ir", "cleared to play", "returns from injury", "out indefinitely",
)
TRANSACTION = (
    "traded", "trade", "acquired", "signed", "signs", "re-signs", "re-signed",
    "contract", "extension", "waived", "waivers", "claimed", "recalled", "call-up",
    "assigned", "reassigned", "loaned", "agrees to", "agreed to",
)
PROSPECT = (
    "prospect", "rookie", "ahl", "ncaa", "college hockey", "chl", "ohl", "whl",
    "qmjhl", "junior", "development camp", "nhl draft", "world juniors", "wjc",
)

GENERIC_TITLES = {
    "nhl featured", "nhl headlines", "nhl page featured 2 items", "nhl page featured",
    "featured", "headlines", "latest news",
}
IGNORE_PATTERNS = (
    r"^daily free talk thread",
    r"^game day thread",
    r"^post game thread",
    r"^pre game thread",
    r"^game thread",
    r"^nhl page featured",
    r"^nhl featured$",
    r"^nhl headlines$",
    r"promo code",
    r"bonus bets",
    r"^\[[A-Z]{2,4}\s*\(\d+\).*\]",
)
REPORTER_PREFIX = re.compile(r"^\[[^\]]{2,40}\]\s+")
SAME_TEAM_TRANSFER = re.compile(r"\bfrom\s+(.+?)\s+to\s+\1\b", re.I)
DFO_PLAYER = re.compile(r"^(.+?)\((C|LW|RW|D|G)\)\|([A-Z]{2,4})?$")
ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text.lower()).strip()


def fingerprint(title: str) -> str:
    clean = re.sub(r"[^a-z0-9 ]", "", normalize(title))
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def term_matches(hay: str, term: str) -> bool:
    term = normalize(term)
    if re.fullmatch(r"[a-z0-9-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", hay) is not None
    return term in hay


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    hay = normalize(text)
    return any(term_matches(hay, term) for term in terms)


def classify_title(title: str, breaking_allowed: bool) -> str:
    if breaking_allowed and contains_any(title, BREAKING):
        return "breaking-news"
    if contains_any(title, INJURY):
        return "injury-report"
    if contains_any(title, TRANSACTION):
        return "nhl-transactions"
    if contains_any(title, PROSPECT):
        return "prospect-wire"
    return "nhl-news"


def route(title: str, source: dict) -> str:
    if source.get("force_channel"):
        return str(source["force_channel"])
    return classify_title(title, bool(source.get("breaking_allowed")))


def should_ignore(title: str, source_id: str, target: str) -> bool:
    t = normalize(title)
    if not t or t in GENERIC_TITLES or len(t) < 12:
        return True
    if any(re.search(pattern, t, re.I) for pattern in IGNORE_PATTERNS):
        return True
    if source_id.startswith("eliteprospects_") and SAME_TEAM_TRANSFER.search(title):
        return True
    if source_id == "reddit_hockey":
        attributed = REPORTER_PREFIX.search(title.strip()) is not None
        if target == "nhl-news" and not attributed:
            return True
    return False


def get(url: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    response.raise_for_status()
    return response


def fetch_rss(url: str) -> list[dict[str, str]]:
    response = get(url)
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"Feed parse failed: {getattr(feed, 'bozo_exception', 'unknown error')}")
    items: list[dict[str, str]] = []
    for entry in feed.entries:
        items.append({
            "title": entry.get("title", "(untitled)"),
            "link": entry.get("link", ""),
            "published": entry.get("published", entry.get("updated", "")),
            "external_id": entry.get("id", entry.get("guid", entry.get("link", ""))),
        })
    return items


def fetch_nhl_news(url: str) -> list[dict[str, str]]:
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urljoin(url, anchor.get("href", ""))
        if not title or len(title) < 18 or "/news/" not in href:
            continue
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "link": key, "published": "", "external_id": key})
    if not items:
        raise RuntimeError("NHL.com parser returned no article links")
    return items


def _short_status(text: str, max_words: int = 20) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def fetch_daily_faceoff_injuries(url: str) -> list[dict[str, str]]:
    """Parse Daily Faceoff's dedicated injury page using visible text.

    The dedicated page is intentionally used instead of the all-player-news page,
    which also contains goalie starts, signings, trades and line changes.
    """
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    lines = [re.sub(r"\s+", " ", s).strip() for s in soup.stripped_strings]
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    i = 0
    while i < len(lines):
        match = DFO_PLAYER.match(lines[i])
        if not match:
            i += 1
            continue

        player, position, team = match.groups()
        injury_idx = None
        for j in range(i + 1, min(i + 7, len(lines))):
            if lines[j].strip().lower() == "injury":
                injury_idx = j
                break
        if injury_idx is None:
            i += 1
            continue

        summary = ""
        source_name = ""
        timestamp = ""
        k = injury_idx + 1
        while k < min(injury_idx + 18, len(lines)):
            line = lines[k]
            if k > injury_idx + 1 and DFO_PLAYER.match(line):
                break
            low = line.lower()
            if low in {"image: injury", "injury"} or low.startswith("image:"):
                k += 1
                continue
            if line.startswith("Source:"):
                source_name = line.split("Source:", 1)[1].strip()
                k += 1
                continue
            if ISO_TS.match(line):
                timestamp = line
                k += 1
                continue
            if not summary and len(line) >= 12:
                summary = line
            k += 1

        if summary:
            team_label = team or position
            short = _short_status(summary)
            title = f"{player} ({team_label}) — {short}"
            event_key = f"dfo|{player}|{summary}|{timestamp}"
            if event_key not in seen:
                seen.add(event_key)
                items.append({
                    "title": title,
                    "link": url,
                    "published": timestamp,
                    "external_id": event_key,
                    "player": player,
                    "team": team or "",
                    "position": position,
                    "source_detail": source_name,
                    "status": short,
                })
        i = max(i + 1, k)

    if not items:
        raise RuntimeError("Daily Faceoff injury parser returned no injury entries")
    return items


def fetch_source(source: dict) -> list[dict[str, str]]:
    source_type = source.get("type", "rss")
    parser = source.get("parser")
    if source_type == "rss":
        return fetch_rss(source["url"])
    if source_type == "html" and parser == "nhl_news":
        return fetch_nhl_news(source["url"])
    if source_type == "html" and parser == "daily_faceoff_injuries":
        return fetch_daily_faceoff_injuries(source["url"])
    raise RuntimeError(f"Unsupported source type/parser: {source_type}/{parser}")


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    print("BLHA The Wire — Phase 2D.1 DRY RUN")
    print("No Discord messages will be sent.\n")
    total = 0
    for source in cfg["sources"]:
        if not source.get("enabled", False):
            continue
        mode = "DISCOVERY" if source.get("discovery_only", False) else "LIVE-CANDIDATE"
        print(f"## {source['name']} [{mode}]")
        try:
            entries = fetch_source(source)
        except Exception as exc:
            print(f"ERROR: {exc}\n")
            continue
        emitted = 0
        for entry in entries:
            title = entry.get("title", "(untitled)")
            link = entry.get("link", "")
            target = route(title, source)
            if should_ignore(title, source.get("id", ""), target):
                continue
            label = f"discovery->{target}" if source.get("discovery_only", False) else target
            print(f"[{label}] {title}")
            print(f"  {link}")
            if entry.get("source_detail"):
                print(f"  source-detail={entry['source_detail']}")
            print(f"  fingerprint={fingerprint(title)}")
            emitted += 1
            total += 1
            if emitted >= 10:
                break
        if emitted == 0:
            print("No usable entries after filtering")
        print()
    print(f"Dry run complete: {total} usable items classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
