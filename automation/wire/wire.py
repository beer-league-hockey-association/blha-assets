#!/usr/bin/env python3
"""BLHA Phase 2D.1 — The Wire source collectors and dry-run classifier.

Shared by the production/shadow engine. Collectors normalize entries and route
them into BLHA Wire desks. Discord delivery lives in engine.py.
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"
USER_AGENT = "BLHA-The-Wire/0.8 (+https://github.com/beer-league-hockey-association/blha-assets)"

BREAKING = (
    "out indefinitely", "season-ending", "out for the season", "suspended indefinitely",
    "retires", "announces retirement", "fired", "dismissed", "blockbuster trade",
)
# Long absences that belong in Breaking News even without a classic keyword,
# e.g. "Romanov likely to miss rest of season with torn ACL" or
# "Romanov out six to eight months".
BREAKING_EVENT_PATTERNS = (
    r"\b(?:miss(?:es|ing)?|out|sidelined|done)\b.{0,40}\b(?:rest|remainder|balance) of (?:the )?(?:regular )?season\b",
    r"\bout (?:at least )?(?:\w+(?:-\w+)? )?(?:to \w+ )?months?\b",
    r"\btorn (?:acl|achilles)\b",
)
INJURY = (
    "injury", "injured", "torn", "acl", "mcl", "achilles", "likely to miss", "day-to-day", "week-to-week", "month-to-month",
    "injured reserve", "ltir", "surgery", "concussion", "fractured", "fracture",
    "activated from ir", "cleared to play", "returns from injury", "out indefinitely",
    "status report:", "not expected to play", "will not play", "will miss",
    "expected to miss", "ruled out", "not available", "unavailable",
)
INJURY_EVENT_PATTERNS = (
    # A concrete absence without a classic injury word, e.g.
    # "Dylan Larkin out for Red Wings' first two games".
    r"\bout for\b(?:\s+[a-z0-9][a-z0-9'\-]*){1,8}\s+(?:games?|days?|weeks?|months?)\b",
    r"\bout (?:for|at least) (?:the )?(?:next )?(?:first )?\w*(?:\s+\w+){0,3}\s+(?:games?|days?|weeks?|months?)\b",
    r"\bout (?:for|at least) (?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:games?|days?|weeks?|months?)\b",
    r"\bout (?:\d+|two|three|four|five|six|seven|eight|nine|ten)(?:\s*(?:-|to)\s*(?:\d+|two|three|four|five|six|seven|eight|nine|ten))?\s+(?:games?|days?|weeks?|months?)\b",
    r"\bmiss(?:es|ing)? (?:the )?(?:first |next )?\w*(?:\s+\w+){0,3}\s+(?:games?|days?|weeks?|months?)\b",
)

# Use action-oriented patterns instead of broad nouns such as "trade" or
# "contract" so analysis headlines about a transaction remain NHL News.
TRANSACTION_EVENT_PATTERNS = (
    r"\btraded\b",
    r"\btrades?\b.+\bto\b",
    r"\bacquire[sd]?\b",
    r"\bsign(?:s|ed)?\b",
    r"\bre-sign(?:s|ed)?\b",
    r"\bwaived?\b",
    r"\bwaivers\b",
    r"\bclaimed\b",
    r"\brecalled\b",
    r"\bcall-up\b",
    r"\bassigned\b",
    r"\breassigned\b",
    r"\bloaned\b",
    r"\bagrees? to\b",
    r"\bagreed to\b",
    r"\bcontract extension\b",
    r"\bextends?\b.+\bcontract\b",
)
TRANSACTION_ANALYSIS_PATTERNS = (
    r"\?\s*$",
    # Explainers and opinion pieces ("Why the Red Wings need to sign ...").
    # Not "will", "can" or "is": they start player names ("Will Smith signs ...").
    r"^(?:why|how|what|should|could|would)\b",
    r"\bneeds? to (?:sign|trade|re-sign|extend)\b",
    r"\bconsider(?:ing)? (?:a )?trade\b",
    r"\btrade (?:value|values|target|targets|rumor|rumors|rumour|rumours|market|ideas?|proposal|proposals)\b",
    r"\b(?:possible|potential|hypothetical|mock) trade\b",
    r"\b(?:could|would|should|might|may) trade\b",
    r"\bimpact of\b.+\btrade\b",
    r"\bafter (?:the |a )?trade\b",
    r"\bgrading (?:the |a )?trade\b",
    r"\btrade analysis\b",
)
PROSPECT = (
    "prospect", "rookie", "ahl", "ncaa", "college hockey", "chl", "ohl", "whl",
    "qmjhl", "junior", "development camp", "nhl draft", "world juniors", "wjc",
)

GENERIC_TITLES = {
    "nhl featured", "nhl headlines", "nhl page featured 2 items", "nhl page featured",
    "featured", "headlines", "latest news", "nhl top videos", "skip to main content",
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
    r"^nhl top videos$",
    r"^skip to main content$",
    r"promo code",
    r"bonus bets",
    r"^fantasy picks, props, futures\b",
    r"^projected lineups, starting goalies\b",
    r"^\[[A-Z]{2,4}\s*\(\d+\).*\]",
)
REPORTER_PREFIX = re.compile(r"^\[[^\]]{2,40}\]\s+")
SAME_TEAM_TRANSFER = re.compile(r"\bfrom\s+(.+?)\s+to\s+\1\b", re.I)
DFO_PLAYER_WITH_POS = re.compile(r"^(.+?)\s*\(\s*(C|LW|RW|D|G)\s*\)\s*$", re.I)
DFO_LONG_POSITION = re.compile(
    r"\s*\(\s*(?:Center|Left Wing|Right Wing|Defenseman|Defenceman|Goaltender|Goalie)\s*\)\s*$",
    re.I,
)
DFO_POS_TEAM = re.compile(r"\(\s*(C|LW|RW|D|G)\s*\)\s*\|?\s*\(?\s*([A-Z]{2,4})?\s*\)?")
ISO_TS_ANY = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")
TEAM_CODE = re.compile(r"^[A-Z]{2,4}$")
POSITION_CODES = {"C", "LW", "RW", "D", "G"}
DATE_SUFFIX = re.compile(r"\s+[A-Z][a-z]{2}\s+\d{1,2},\s+20\d{2}\s*$")


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


def is_injury_event(title: str) -> bool:
    text = normalize(title)
    return any(re.search(pattern, text, re.I) for pattern in INJURY_EVENT_PATTERNS)


def is_breaking_event(title: str) -> bool:
    text = normalize(title)
    return any(re.search(pattern, text, re.I) for pattern in BREAKING_EVENT_PATTERNS)


def is_transaction_event(title: str) -> bool:
    text = normalize(title)
    if any(re.search(pattern, text, re.I) for pattern in TRANSACTION_ANALYSIS_PATTERNS):
        return False
    return any(re.search(pattern, text, re.I) for pattern in TRANSACTION_EVENT_PATTERNS)


def classify_title(title: str, breaking_allowed: bool) -> str:
    if breaking_allowed and (contains_any(title, BREAKING) or is_breaking_event(title)):
        return "breaking-news"
    if contains_any(title, INJURY) or is_injury_event(title) or is_breaking_event(title):
        return "injury-report"
    if is_transaction_event(title):
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
    if source_id == "sportsnet_nhl" and "men's hockey coach" in t:
        return True
    # Sportsnet "Live Tracker" items are game-tracker shells, not news.
    if source_id == "sportsnet_nhl" and "live tracker" in t:
        return True
    if source_id == "reddit_hockey":
        attributed = REPORTER_PREFIX.search(title.strip()) is not None
        if target == "nhl-news" and not attributed:
            return True
    return False


def get(url: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                if attempt == 0:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(max(float(retry_after), 1.0), 5.0)
                    except ValueError:
                        delay = 2.0
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.5)
                continue
            raise
    raise RuntimeError(f"request failed: {last_error}")


def _http_url(value: object) -> str:
    text = str(value or "").strip()
    return text if re.match(r"^https?://", text, re.I) else ""


def _rss_entry_link(entry: object) -> str:
    """Find a usable article URL for an RSS entry.

    Some feeds (notably Sportsnet) do not always set ``entry.link``. Fall back
    to alternate link elements, then to the GUID/ID only when it is itself an
    HTTP(S) URL. Never invents a destination.
    """
    if not hasattr(entry, "get"):
        return ""
    direct = _http_url(entry.get("link", ""))
    if direct:
        return direct
    preferred: list[str] = []
    fallback: list[str] = []
    for row in entry.get("links") or []:
        if not hasattr(row, "get"):
            continue
        href = _http_url(row.get("href", ""))
        if not href:
            continue
        rel = str(row.get("rel") or "").strip().lower()
        (preferred if rel in ("", "alternate") else fallback).append(href)
    if preferred or fallback:
        return (preferred or fallback)[0]
    for key in ("id", "guid"):
        identifier = _http_url(entry.get(key, ""))
        if identifier:
            return identifier
    return ""


def fetch_rss(url: str) -> list[dict[str, str]]:
    response = get(url)
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"Feed parse failed: {getattr(feed, 'bozo_exception', 'unknown error')}")
    items: list[dict[str, str]] = []
    for entry in feed.entries:
        link = _rss_entry_link(entry)
        items.append({
            "title": entry.get("title", "(untitled)"),
            "link": link,
            "published": entry.get("published", entry.get("updated", "")),
            "external_id": entry.get("id", entry.get("guid", link)) or link,
        })
    return items


def _headline_from_anchor(anchor: Tag) -> str:
    heading = anchor.find(["h1", "h2", "h3", "h4", "h5"])
    if heading:
        title = heading.get_text(" ", strip=True)
    else:
        title = anchor.get_text(" ", strip=True)
    title = re.sub(r"\s+", " ", title).strip()
    title = DATE_SUFFIX.sub("", title).strip()
    return title


def fetch_nhl_news(url: str) -> list[dict[str, str]]:
    response = get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor.get("href", ""))
        if "/news/" not in href:
            continue
        title = _headline_from_anchor(anchor)
        if not title or len(title) < 18:
            continue
        if should_ignore(title, "nhl_latest", classify_title(title, True)):
            continue
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "link": key, "published": "", "external_id": key})
    if not items:
        raise RuntimeError("NHL.com parser returned no article links")
    return items


def _short_status(text: str, max_words: int = 24) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _dfo_lines_after_anchor(anchor: Tag, max_nodes: int = 180) -> list[str]:
    """Collect one Daily Faceoff card by document order."""
    lines: list[str] = []
    nodes = 0
    for element in anchor.next_elements:
        nodes += 1
        if nodes > max_nodes:
            break
        if isinstance(element, Tag):
            if element is not anchor and element.name == "a":
                href = element.get("href", "") or ""
                if "/players/news/" in href:
                    break
            continue
        if not isinstance(element, NavigableString):
            continue
        text = _clean_text(str(element))
        if not text:
            continue
        if not lines or lines[-1] != text:
            lines.append(text)
    return lines


def _extract_dfo_card(anchor: Tag, page_url: str) -> dict[str, str] | None:
    raw_player = _clean_text(anchor.get_text(" ", strip=True))
    if not raw_player:
        return None

    position = ""
    player = raw_player
    player_match = DFO_PLAYER_WITH_POS.match(raw_player)
    if player_match:
        player, position = player_match.groups()
        position = position.upper()

    player = DFO_LONG_POSITION.sub("", player).strip()

    lines = _dfo_lines_after_anchor(anchor)
    if not lines:
        return None

    lead = " ".join(lines[:12])
    pos_team = DFO_POS_TEAM.search(lead)
    team = ""
    if pos_team:
        position = position or (pos_team.group(1) or "").upper()
        possible_team = (pos_team.group(2) or "").upper()
        if possible_team and possible_team not in POSITION_CODES:
            team = possible_team

    if not team:
        for s in lines[:12]:
            candidate = s.strip().strip("|() ").upper()
            if TEAM_CODE.fullmatch(candidate) and candidate not in POSITION_CODES:
                team = candidate
                break

    injury_idx = None
    for idx, s in enumerate(lines[:25]):
        if s.lower() == "injury":
            injury_idx = idx
            break
    if injury_idx is None:
        return None

    summary = ""
    source_name = ""
    timestamp = ""
    after_source = False

    for s in lines[injury_idx + 1:]:
        low = s.lower()
        if low == "injury" or low.startswith("image:"):
            continue
        if s == "Source:":
            after_source = True
            continue
        if s.startswith("Source:"):
            rest = s.split("Source:", 1)[1].strip()
            if rest:
                source_name = rest
            after_source = True
            continue

        ts = ISO_TS_ANY.search(s)
        if ts:
            timestamp = ts.group(1)
            reporter = s[:ts.start()].strip()
            if reporter and after_source and not source_name:
                source_name = reporter
            continue

        if after_source and not source_name and 2 <= len(s) <= 100:
            source_name = s
            continue

        if not summary and len(s) >= 12 and not DFO_POS_TEAM.fullmatch(s):
            summary = s

    if not summary:
        return None

    player_link = urljoin(page_url, anchor.get("href", ""))
    short = _short_status(summary)
    title = f"{player} ({team or position or 'NHL'}) — {short}"
    event_key = f"dfo|{player}|{summary}|{timestamp}"

    return {
        "title": title,
        "link": player_link or page_url,
        "published": timestamp,
        "external_id": event_key,
        "player": player,
        "team": team,
        "position": position,
        "source_detail": source_name,
        "status": short,
    }


def fetch_daily_faceoff_injuries(url: str) -> list[dict[str, str]]:
    """Parse Daily Faceoff's dedicated NHL Injury Report cards."""
    response = get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    anchors = soup.find_all("a", href=re.compile(r"/players/news/"))
    for anchor in anchors:
        item = _extract_dfo_card(anchor, url)
        if not item:
            continue
        key = item["external_id"]
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    if not items:
        player_anchor_count = len(anchors)
        injury_text_count = len(soup.find_all(string=re.compile(r"^\s*Injury\s*$", re.I)))
        sample_players = [_clean_text(a.get_text(" ", strip=True)) for a in anchors[:3]]
        raise RuntimeError(
            "Daily Faceoff injury parser returned no injury entries "
            f"(player_links={player_anchor_count}, injury_labels={injury_text_count}, "
            f"sample_players={sample_players})"
        )
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
        max_items = int(source.get("max_items", 10))
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
            if emitted >= max_items:
                break
        if emitted == 0:
            print("No usable entries after filtering")
        print()
    print(f"Dry run complete: {total} usable items classified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
