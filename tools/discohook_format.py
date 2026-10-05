"""Shared BLHA Discohook message format (one place for the rules).

Every send is ONE Discord message:
- Up to 10 embeds and at most 6,000 counted characters (title, description,
  field names and values, footer text, author name). A message over either
  limit is an error, never split automatically.
- A channel intro starts with its header banner embed: charcoal side color and
  the header image, and nothing else (no footer).
- Only the final embed carries a footer: its footer text plus the shared gold
  footer-divider image. Every other embed has no footer and no divider.

Used by normalize_discohook_templates.py (enforces and verifies every template),
build_channel_intros.py, build_news_templates.py and build_constitution.py.
The packaging workflow (.github/workflows/blha-package-discohook-json.yml)
checks the same rules independently.
"""

from __future__ import annotations

BASE = "https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/main/discord/webhooks/"
FOOTER_BASE_URL = BASE + "shared/blha-footer-divider-1600x90.png"
FOOTER_URL = FOOTER_BASE_URL + "?v=2c6-frozen"
HEADER_VERSION = "?v=4-b-mark"
HEADER_COLOR = int("2B2D31", 16)
ZWSP = "​"
MAX_EMBEDS = 10
MAX_CHARS = 6000

# Each category folder has one header image. League Office has one header per channel.
CATEGORY_HEADERS = {
    "the-wire": "the-wire/blha-the-wire-header.png",
    "league-competition": "league-competition/blha-competition-header.png",
    "general-managers": "general-managers/blha-general-managers-header.png",
    "trade-center": "trade-center/blha-trade-center-header.png",
    "scouting": "scouting/blha-scouting-header.png",
    "waiver-wire": "waiver-wire/blha-waiver-wire-header.png",
    "commissioners-office": "commissioners-office/blha-commissioners-office-header.png",
    "franchise-hq": "franchise-hq/blha-franchise-hq-header.png",
    "draft-center": "draft-center/blha-draft-center-header.png",
}
LEAGUE_OFFICE_HEADERS = {
    "01_constitution_channel_intro.json": "league-office/blha-constitution-header.png",
    "02_announcements_channel_intro.json": "league-office/blha-announcements-header.png",
    "03_calendar_channel_intro.json": "league-office/blha-calendar-header.png",
    "04_ledger_channel_intro.json": "league-office/blha-ledger-header.png",
    "05_voting_channel_intro.json": "league-office/blha-voting-header.png",
    "06_hall_of_champions_channel_intro.json": "league-office/blha-champions-header.png",
    "07_league_records_channel_intro.json": "league-office/blha-records-header.png",
}
WELCOME = "welcome/01_welcome.json"
WELCOME_HEADER = "welcome/blha-welcome-banner.png"


def header_url(rel: str) -> str | None:
    """Header banner URL for a template path relative to templates/, or None."""
    if rel == WELCOME:
        return BASE + WELCOME_HEADER + HEADER_VERSION
    if not rel.endswith("_channel_intro.json"):
        return None
    category, name = rel.split("/", 1)
    image = LEAGUE_OFFICE_HEADERS[name] if category == "league-office" else CATEGORY_HEADERS[category]
    return BASE + image + HEADER_VERSION


def banner_embed(url: str) -> dict:
    return {"color": HEADER_COLOR, "image": {"url": url}}


def is_banner(embed: dict) -> bool:
    url = str(((embed or {}).get("image") or {}).get("url") or "")
    return url.startswith(BASE) and ("-header.png" in url or "blha-welcome-banner.png" in url)


def is_divider(embed: dict) -> bool:
    return str(((embed or {}).get("image") or {}).get("url") or "").startswith(FOOTER_BASE_URL)


def footer_text(embed: dict) -> str:
    return str(((embed or {}).get("footer") or {}).get("text") or "")


def embed_chars(embed: dict) -> int:
    total = len(embed.get("title") or "") + len(embed.get("description") or "")
    total += len(footer_text(embed)) + len(((embed.get("author") or {}).get("name")) or "")
    for f in embed.get("fields") or []:
        total += len(f.get("name") or "") + len(f.get("value") or "")
    return total


def message_chars(embeds: list[dict]) -> int:
    return sum(embed_chars(e) for e in embeds)


def apply(embeds: list[dict], banner_url: str | None = None) -> list[dict]:
    """Return the embeds in the BLHA format. Content and order are kept.

    The footer text that ends up on the final embed is the last real footer
    text found in the message, so combining cards never loses the sign-off.
    """
    out = [dict(e) for e in embeds]
    if banner_url:
        if out and is_banner(out[0]):
            out[0] = banner_embed(banner_url)
        else:
            out.insert(0, banner_embed(banner_url))
    sign_off = ""
    for e in out:
        text = footer_text(e)
        if text and text != ZWSP:
            sign_off = text
    # Drop embeds that are only a divider (an older layout); their job moves to the last card.
    cleaned = [e for e in out
               if not (is_divider(e) and e.keys() <= {"color", "footer", "image"}
                       and footer_text(e) in ("", ZWSP))]
    if not cleaned or (banner_url and len(cleaned) == 1):
        raise ValueError("message has no content embed to carry the footer")
    if not sign_off:
        raise ValueError("message has no footer text to put on its final embed")
    if (cleaned[-1].get("image") or {}).get("url") and not is_divider(cleaned[-1]):
        # The final card shows its own image, so the divider needs an embed of its own.
        cleaned.append({"color": HEADER_COLOR})
    last = len(cleaned) - 1
    for i, e in enumerate(cleaned):
        if i < last:
            e.pop("footer", None)
            if is_divider(e):
                e.pop("image", None)
        else:
            # Assigning in place keeps an existing key where it already sits in the JSON.
            e["footer"] = {"text": sign_off}
            e["image"] = {"url": FOOTER_URL}
    return cleaned


def problems(embeds: list[dict], banner_url: str | None = None) -> list[str]:
    """Every way these embeds break the format (empty list = compliant)."""
    errs: list[str] = []
    if not isinstance(embeds, list) or not embeds:
        return ["no embeds"]
    if len(embeds) > MAX_EMBEDS:
        errs.append(f"{len(embeds)} embeds (limit {MAX_EMBEDS})")
    chars = message_chars(embeds)
    if chars > MAX_CHARS:
        errs.append(f"{chars} characters (limit {MAX_CHARS})")
    last = len(embeds) - 1
    for i, e in enumerate(embeds):
        if i < last and "footer" in e:
            errs.append(f"embed {i + 1} has a footer; only the final embed may")
        if i < last and is_divider(e):
            errs.append(f"embed {i + 1} has the footer divider; only the final embed may")
    if not footer_text(embeds[last]) or footer_text(embeds[last]) == ZWSP:
        errs.append("final embed has no footer text")
    if (embeds[last].get("image") or {}).get("url") != FOOTER_URL:
        errs.append("final embed does not use the footer divider image")
    if banner_url:
        first = embeds[0]
        if first != banner_embed(banner_url):
            errs.append("first embed is not the header banner (charcoal, header image, no footer)")
    return errs
