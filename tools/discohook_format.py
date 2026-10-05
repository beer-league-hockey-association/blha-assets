"""Shared BLHA Discohook message format (one place for the rules).

Every send is ONE Discord message:
- The channel's header banner embed (if it has one), then ONE text embed.
  When a message has several text sections, they merge into that one embed:
  each extra section's title becomes a bold divider field
  ("**━━━━━━━━ TITLE ━━━━━━━━**") whose value is the section's text, followed
  by the section's own fields.
- The header banner embed is charcoal, shows the header image and keeps an
  invisible footer ("\u200b"); without it Discohook rejects it as empty.
- Only the final embed carries real footer text plus the shared gold
  footer-divider image. No other embed has footer text or the divider.
- Discord limits: 25 fields per embed, 256 per field name, 1,024 per field
  value, 4,096 per description, 10 embeds and 6,000 counted characters per
  message. Content that would break a limit is an error, never split.
- MULTI_SECTION_EXCEPTIONS lists the messages whose sections do not fit one
  embed. They keep one embed per section until the Commissioner decides how
  to reshape them; the footer rules still apply.

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
ZWSP = "\u200b"
MAX_EMBEDS = 10
MAX_CHARS = 6000
MAX_FIELDS = 25
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_DESC = 4096

# Messages that cannot become one text embed without splitting content.
# Paths are relative to templates/; a trailing "/" matches a whole folder.
MULTI_SECTION_EXCEPTIONS = {
    "welcome/01_welcome.json": "merging the six sections needs 30 fields (limit 25)",
    "constitution/": "several articles are longer than one field can hold (1,024 characters)",
}


class DoesNotFit(ValueError):
    """Merging the sections would break a Discord limit."""


def is_exception(rel: str | None) -> bool:
    return bool(rel) and any(rel == k or (k.endswith("/") and rel.startswith(k)) for k in MULTI_SECTION_EXCEPTIONS)


def divider_name(title: str) -> str:
    return f"**━━━━━━━━ {title} ━━━━━━━━**"

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
    return {"color": HEADER_COLOR, "footer": {"text": ZWSP}, "image": {"url": url}}


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


def limit_problems(embed: dict) -> list[str]:
    errs: list[str] = []
    if len(embed.get("description") or "") > MAX_DESC:
        errs.append(f"description is {len(embed['description'])} characters (limit {MAX_DESC})")
    fields = embed.get("fields") or []
    if len(fields) > MAX_FIELDS:
        errs.append(f"{len(fields)} fields (limit {MAX_FIELDS})")
    for f in fields:
        if len(f.get("name") or "") > MAX_FIELD_NAME:
            errs.append(f"field name '{f['name'][:40]}' is over {MAX_FIELD_NAME} characters")
        if len(f.get("value") or "") > MAX_FIELD_VALUE:
            errs.append(f"field '{(f.get('name') or '')[:50]}' is {len(f['value'])} characters (limit {MAX_FIELD_VALUE})")
    return errs


def merge_sections(texts: list[dict]) -> dict:
    """Merge text embeds into one: later sections become divider fields."""
    merged = dict(texts[0])
    fields = list(merged.get("fields") or [])
    for section in texts[1:]:
        fields.append({"name": divider_name(section.get("title") or ""),
                       "value": section.get("description") or ZWSP, "inline": False})
        fields += section.get("fields") or []
    merged["fields"] = fields
    errs = limit_problems(merged)
    if message_chars([merged]) > MAX_CHARS:
        errs.append(f"{message_chars([merged])} characters (limit {MAX_CHARS})")
    if errs:
        raise DoesNotFit("; ".join(errs))
    return merged


def apply(embeds: list[dict], banner_url: str | None = None, rel: str | None = None) -> list[dict]:
    """Return the embeds in the BLHA format. Text and order are kept.

    The final embed's footer text is the last real footer text in the message,
    so merging sections never loses the sign-off. Raises DoesNotFit when the
    sections cannot share one embed, unless the message is a listed exception.
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
    if not sign_off:
        raise ValueError("message has no footer text to put on its final embed")
    head = [out[0]] if out and is_banner(out[0]) else []
    texts = [e for e in out[len(head):]
             if not (is_divider(e) and e.keys() <= {"color", "footer", "image"}
                     and footer_text(e) in ("", ZWSP))]
    if not texts:
        raise ValueError("message has no text embed")
    if len(texts) > 1:
        try:
            texts = [merge_sections(texts)]
        except DoesNotFit:
            if not is_exception(rel):
                raise
    if (texts[-1].get("image") or {}).get("url") and not is_divider(texts[-1]):
        # The final card shows its own image, so the divider needs an embed of its own.
        texts.append({"color": HEADER_COLOR})
    last = len(texts) - 1
    for i, e in enumerate(texts):
        if i < last:
            e.pop("footer", None)
            if is_divider(e):
                e.pop("image", None)
        else:
            # Assigning in place keeps an existing key where it already sits in the JSON.
            e["footer"] = {"text": sign_off}
            e["image"] = {"url": FOOTER_URL}
    return head + texts


def problems(embeds: list[dict], banner_url: str | None = None, rel: str | None = None) -> list[str]:
    """Every way these embeds break the format (empty list = compliant)."""
    errs: list[str] = []
    if not isinstance(embeds, list) or not embeds:
        return ["no embeds"]
    if len(embeds) > MAX_EMBEDS:
        errs.append(f"{len(embeds)} embeds (limit {MAX_EMBEDS})")
    chars = message_chars(embeds)
    if chars > MAX_CHARS:
        errs.append(f"{chars} characters (limit {MAX_CHARS})")
    for i, e in enumerate(embeds):
        errs += [f"embed {i + 1}: {p}" for p in limit_problems(e)]
    head = 1 if is_banner(embeds[0]) else 0
    if head and embeds[0] != {"color": HEADER_COLOR, "footer": {"text": ZWSP}, "image": embeds[0].get("image")}:
        errs.append("header banner must be charcoal with the header image and the invisible footer only")
    for i, e in enumerate(embeds[1:], 2):
        if is_banner(e):
            errs.append(f"embed {i} is a header banner; only the first embed may be")
    texts = embeds[head:]
    if len(texts) > 1 and not is_exception(rel):
        errs.append(f"{len(texts)} text embeds; sections must merge into one text embed")
    last = len(embeds) - 1
    for i in range(head, last):
        if "footer" in embeds[i]:
            errs.append(f"embed {i + 1} has a footer; only the final embed may")
        if is_divider(embeds[i]):
            errs.append(f"embed {i + 1} has the footer divider; only the final embed may")
    if not footer_text(embeds[last]) or footer_text(embeds[last]) == ZWSP:
        errs.append("final embed has no footer text")
    if (embeds[last].get("image") or {}).get("url") != FOOTER_URL:
        errs.append("final embed does not use the footer divider image")
    if banner_url and embeds[0] != banner_embed(banner_url):
        errs.append("first embed is not this channel's header banner")
    return errs
