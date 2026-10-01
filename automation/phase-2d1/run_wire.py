#!/usr/bin/env python3
"""Production entry point for BLHA The Wire.

Keeps compatibility/enrichment adapters isolated from the core delivery engine
while preserving the existing engine.main() behavior.
"""

from __future__ import annotations

import re
import sys
from typing import Any

import engine
import roster_enrichment
import wire

# Replace the legacy inline enrichment implementation with the validated public
# Fantrax roster-ID resolver. Keeping this adapter explicit lets the core engine
# stay stable while the public Fantrax schema remains loosely documented.
engine.enrich_injury_ownership = roster_enrichment.enrich_injury_ownership

# National-news feeds sometimes describe a concrete absence without using a
# conventional injury keyword, e.g. "Dylan Larkin out for Red Wings' first two
# games". Treat a bounded "out for ... <duration>" phrase as an injury event.
_original_is_injury_event = wire.is_injury_event
_OUT_FOR_DURATION = re.compile(
    r"\bout for\b(?:\s+[a-z0-9][a-z0-9'\-]*){1,8}\s+"
    r"(?:games?|days?|weeks?|months?)\b",
    re.I,
)


def _is_injury_event_with_duration(title: str) -> bool:
    if _original_is_injury_event(title):
        return True
    return _OUT_FOR_DURATION.search(wire.normalize(title)) is not None


wire.is_injury_event = _is_injury_event_with_duration


# Some RSS feeds, notably Sportsnet's NHL feed, do not consistently expose the
# article URL through feedparser's top-level ``entry.link`` field. Recover a
# usable article URL from alternate link elements first, then from GUID/ID only
# when that identifier is itself an HTTP(S) URL. This keeps Discord embed titles
# clickable without inventing or guessing destinations.
def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    if re.match(r"^https?://", text, re.I):
        return text
    return ""


def _rss_entry_link(entry: Any) -> str:
    if not hasattr(entry, "get"):
        return ""

    direct = _http_url(entry.get("link", ""))
    if direct:
        return direct

    links = entry.get("links") or []
    preferred: list[str] = []
    fallback: list[str] = []
    if isinstance(links, (list, tuple)):
        for row in links:
            if not hasattr(row, "get"):
                continue
            href = _http_url(row.get("href", ""))
            if not href:
                continue
            rel = str(row.get("rel") or "").strip().lower()
            if rel in ("", "alternate"):
                preferred.append(href)
            else:
                fallback.append(href)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]

    for key in ("id", "guid"):
        identifier = _http_url(entry.get(key, ""))
        if identifier:
            return identifier
    return ""


def _fetch_rss_with_link_recovery(url: str) -> list[dict[str, str]]:
    response = wire.get(url)
    feed = wire.feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(
            f"Feed parse failed: {getattr(feed, 'bozo_exception', 'unknown error')}"
        )

    items: list[dict[str, str]] = []
    for entry in feed.entries:
        link = _rss_entry_link(entry)
        external_id = entry.get("id", entry.get("guid", link))
        items.append(
            {
                "title": entry.get("title", "(untitled)"),
                "link": link,
                "published": entry.get("published", entry.get("updated", "")),
                "external_id": external_id or link,
            }
        )
    return items


wire.fetch_rss = _fetch_rss_with_link_recovery


# Sportsnet's "Live Tracker" feed items are game-tracker shells rather than
# substantive news articles. They add noise to NHL News and often provide little
# value after the game, so suppress them at the source-filter stage.
_original_should_ignore = wire.should_ignore


def _should_ignore_with_source_noise(title: str, source_id: str, target: str) -> bool:
    if _original_should_ignore(title, source_id, target):
        return True
    if source_id == "sportsnet_nhl" and "live tracker" in wire.normalize(title):
        return True
    return False


wire.should_ignore = _should_ignore_with_source_noise


if __name__ == "__main__":
    sys.exit(engine.main())
