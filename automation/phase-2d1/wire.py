#!/usr/bin/env python3
"""BLHA Phase 2D.1 — The Wire dry-run collector.

This MVP fetches configured RSS feeds and classifies headlines into BLHA Wire
channels. Discord posting is intentionally disabled in Phase 2D.1.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"

USER_AGENT = "BLHA-The-Wire/0.1 (+https://github.com/diseasewheeze/blha-assets)"

BREAKING = (
    "out indefinitely", "season-ending", "out for season", "suspended",
    "retires", "retirement", "fired", "dismissed", "blockbuster trade",
)
INJURY = (
    "injury", "injured", "day-to-day", "week-to-week", "month-to-month",
    "injured reserve", " ltir", " ir", "surgery", "concussion",
    "activated from ir", "cleared to play", "returns from injury",
)
TRANSACTION = (
    "traded", " trade ", "acquired", "signed", " signs ", "contract",
    "extension", "waived", "waivers", "claimed", "recalled", "call-up",
    "assigned", "reassigned", "loaned",
)
PROSPECT = (
    "prospect", "rookie", "ahl", "ncaa", "college hockey", "chl", "ohl",
    "whl", "qmjhl", "junior", "development camp", "nhl draft",
    "world juniors", "wjc",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def fingerprint(title: str) -> str:
    clean = re.sub(r"[^a-z0-9 ]", "", normalize(title))
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    hay = f" {normalize(text)} "
    return any(n in hay for n in needles)


def route(title: str, breaking_allowed: bool) -> str:
    t = normalize(title)
    if breaking_allowed and contains_any(t, BREAKING):
        return "breaking-news"
    if contains_any(t, INJURY):
        return "injury-report"
    if contains_any(t, TRANSACTION):
        return "nhl-transactions"
    if contains_any(t, PROSPECT):
        return "prospect-wire"
    return "nhl-news"


def fetch_feed(url: str):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()

    # feedparser's public API is parse(); it accepts bytes directly.
    feed = feedparser.parse(response.content)

    # A malformed feed may still yield entries. Only fail when parsing reports
    # an error and there are no usable entries to classify.
    if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
        exc = getattr(feed, "bozo_exception", "unknown feed parsing error")
        raise RuntimeError(f"RSS parse error: {exc}")

    return feed


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    print("BLHA The Wire — Phase 2D.1 DRY RUN")
    print("No Discord messages will be sent.\n")

    total = 0
    for source in cfg["sources"]:
        if not source.get("enabled", False):
            continue
        print(f"## {source['name']}")
        try:
            feed = fetch_feed(source["url"])
        except Exception as exc:
            print(f"ERROR: {exc}\n")
            continue

        entries = list(getattr(feed, "entries", []))
        if not entries:
            print("No entries returned.\n")
            continue

        for entry in entries[:10]:
            title = entry.get("title", "(untitled)")
            link = entry.get("link", "")
            target = route(title, bool(source.get("breaking_allowed")))
            print(f"[{target}] {title}")
            print(f"  {link}")
            print(f"  fingerprint={fingerprint(title)}")
            total += 1
        print()

    print(f"Dry run complete: {total} items classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
