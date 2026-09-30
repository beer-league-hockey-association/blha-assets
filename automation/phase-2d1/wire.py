#!/usr/bin/env python3
"""BLHA Phase 2D.1 — The Wire dry-run collector.

Fetches configured public hockey sources and classifies news into BLHA Wire
channels. Discord posting remains intentionally disabled in Phase 2D.1.
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
USER_AGENT = "BLHA-The-Wire/0.3 (+https://github.com/diseasewheeze/blha-assets)"

# Routing priority is intentional: BREAKING -> INJURY -> TRANSACTION -> PROSPECT -> NEWS.
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
    # Reddit highlight/score formatting such as: [VAN (6) - EDM 5] ...
    r"^\[[A-Z]{2,4}\s*\(\d+\).*\]",
)
REPORTER_PREFIX = re.compile(r"^\[[^\]]{2,40}\]\s+")
SAME_TEAM_TRANSFER = re.compile(r"\bfrom\s+(.+?)\s+to\s+\1\b", re.I)


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
    # A source-specific desk is more reliable than headline keyword guessing.
    if source.get("force_channel"):
        return str(source["force_channel"])
    return classify_title(title, bool(source.get("breaking_allowed")))


def should_ignore(title: str, source_id: str, target: str) -> bool:
    t = normalize(title)
    if not t or t in GENERIC_TITLES or len(t) < 12:
        return True
    if any(re.search(pattern, t, re.I) for pattern in IGNORE_PATTERNS):
        return True

    # Elite Prospects occasionally emits bookkeeping/self-transfers that are not useful news.
    if source_id.startswith("eliteprospects_") and SAME_TEAM_TRANSFER.search(title):
        return True

    if source_id == "reddit_hockey":
        # Reddit is discovery-only. Suppress unattributed general chatter while still allowing
        # attributed reporting and clearly classifiable injury/transaction/prospect items.
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
    return [
        {"title": entry.get("title", "(untitled)"), "link": entry.get("link", "")}
        for entry in feed.entries
    ]


def fetch_nhl_news(url: str) -> list[dict[str, str]]:
    """Extract NHL.com article links from the official News page."""
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = urljoin(url, anchor.get("href", ""))
        if not title or len(title) < 18:
            continue
        if "/news/" not in href:
            continue
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "link": key})

    if not items:
        raise RuntimeError("NHL.com parser returned no article links")
    return items


def fetch_source(source: dict) -> list[dict[str, str]]:
    source_type = source.get("type", "rss")
    if source_type == "rss":
        return fetch_rss(source["url"])
    if source_type == "html" and source.get("parser") == "nhl_news":
        return fetch_nhl_news(source["url"])
    raise RuntimeError(f"Unsupported source type/parser: {source_type}/{source.get('parser')}")


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
