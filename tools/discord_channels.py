"""The BLHA server's real channel and category names, and the rule that writes them.

Every channel in the server is named "emoji│name" (U+2502 between them), for
example 🏒│game-day. Messages refer to a channel by that full name, so a post
reads exactly like the server's channel list.

Templates and code may still write a reference the short way, as **game-day**
or "the game-day channel". restyle() turns those into the full name, and
plain_references() lists any short reference left behind. discohook_format
runs both on every message, so a short name can never reach Discord.

When a channel is added or renamed in Discord, change it here and rebuild the
templates (see README, "Rebuilding the Discohook templates").
"""

from __future__ import annotations

import re

BAR = "│"  # │

# Category -> channels, in server order (read from the server on 2026-10-07).
LAYOUT: dict[str, dict[str, str]] = {
    "🏛️ LEAGUE OFFICE": {
        "welcome": "👋🏻", "constitution": "📜", "announcements": "📢", "league-calendar": "📅",
        "league-ledger": "💰", "league-voting": "🗳️", "hall-of-champions": "🏆", "league-records": "📚",
    },
    "📰 THE WIRE": {
        "breaking-news": "🚨", "nhl-news": "📰", "injury-report": "🏥", "nhl-transactions": "🔄",
        "prospect-wire": "🌱", "news-desk": "💬",
    },
    "💼 GENERAL MANAGERS": {
        "gm-lounge": "💬", "game-day": "🏒", "chirps-and-memes": "😂", "off-topic": "🍺", "media": "📸",
    },
    "🔄 TRADE CENTER": {
        "trade-block": "📣", "looking-to-acquire": "🎯", "trade-discussion": "💬",
        "completed-trades": "🚨", "player-values": "📈",
    },
    "🌱 SCOUTING DEPARTMENT": {"scouting": "🔎"},
    "💰 WAIVER WIRE": {"waiver-talk": "💵", "waiver-watch": "👀"},
    "🏆 LEAGUE COMPETITION": {
        "scoreboard": "📊", "standings": "📈", "weekly-recap": "📰", "playoff-race": "🏁",
        "playoffs": "🏆", "consolation-bracket": "🥄",
        "lineup-alerts": "🔔",  # new with the feature batch
    },
    "🧑🏻‍⚖️ COMMISSIONER'S OFFICE": {
        "commissioner-support": "🎫", "rules-questions": "❓", "league-suggestions": "💡",
        "open-a-ticket": "🎟️", "ticket-log": "📙", "ticket-transcripts": "📃",
        "commissioner-room": "🔒", "owner-issues": "👤", "league-accounting": "💰",
        "rulings-log": "⚖️", "automation-health": "⚙️", "backup-log": "💾", "commissioner-desk": "📃",
        "owner-handbook": "📖",  # new with the feature batch
    },
    "🎯 DRAFT CENTER": {
        "draft-announcements": "📢", "draft-room": "🎙️", "draft-day-trades": "🔄", "draft-results": "📋",
    },
    "🏒 FRANCHISE HQ": {
        "franchise-directory": "🏒", "franchise-news": "📰", "roster-showcase": "📋",
    },
}

# Channels that do not exist in the server yet (made during setup).
NEW_CHANNELS = ("lineup-alerts", "owner-handbook")

EMOJI: dict[str, str] = {slug: e for chans in LAYOUT.values() for slug, e in chans.items()}
CATEGORY_OF: dict[str, str] = {slug: cat for cat, chans in LAYOUT.items() for slug in chans}


def name(slug: str) -> str:
    """The channel's full name as Discord shows it, e.g. name("game-day") == "🏒│game-day"."""
    return f"{EMOJI[slug]}{BAR}{slug}"


def ref(slug: str) -> str:
    """A channel reference for message text: the full name in bold."""
    return f"**{name(slug)}**"


_SLUGS = "|".join(sorted(map(re.escape, EMOJI), key=len, reverse=True))
# **slug**, optionally with the channel's own emoji already written in front ("📜 **constitution**").
_BOLD = re.compile(r"(?:(?P<emoji>\S+) )?\*\*(?P<slug>" + _SLUGS + r")\*\*")
# "the slug channel" / "the slug forum" in running text.
_WORD = re.compile(r"(?<![\w│/#*`-])(?P<slug>" + _SLUGS + r")(?= (?:channel|forum)\b)")
# "#slug" written the old way.
_HASH = re.compile(r"(?<![\w(/&])#(?P<slug>" + _SLUGS + r")(?![\w-])")


def _bold(m: re.Match) -> str:
    slug, emoji = m.group("slug"), m.group("emoji")
    if emoji is None or emoji == EMOJI[slug]:
        return ref(slug)
    return f"{emoji} {ref(slug)}"


def restyle(text: str) -> str:
    """Write every short channel reference in text with the channel's full name."""
    if not text:
        return text
    text = _BOLD.sub(_bold, text)
    text = _HASH.sub(lambda m: ref(m.group("slug")), text)
    return _WORD.sub(lambda m: name(m.group("slug")), text)


def plain_references(text: str) -> list[str]:
    """Short channel references left in text (empty when every reference uses the full name)."""
    if not text:
        return []
    found = [m.group(0) for m in _BOLD.finditer(text)]
    found += [m.group(0) for m in _HASH.finditer(text)]
    found += [m.group(0) + " channel" for m in _WORD.finditer(text)]
    return found


def restyle_embed(embed: dict) -> dict:
    """The embed with every text part restyled (title, description, fields, author, footer)."""
    out = dict(embed)
    for key in ("title", "description"):
        if isinstance(out.get(key), str):
            out[key] = restyle(out[key])
    if out.get("fields"):
        out["fields"] = [{**f, "name": restyle(f.get("name") or ""), "value": restyle(f.get("value") or "")}
                         for f in out["fields"]]
    for key in ("author", "footer"):
        part = out.get(key)
        if isinstance(part, dict):
            label = "name" if key == "author" else "text"
            if isinstance(part.get(label), str):
                out[key] = {**part, label: restyle(part[label])}
    return out


def embed_problems(embed: dict) -> list[str]:
    texts = [embed.get("title"), embed.get("description"),
             ((embed.get("author") or {}).get("name")), ((embed.get("footer") or {}).get("text"))]
    for f in embed.get("fields") or []:
        texts += [f.get("name"), f.get("value")]
    return [f"short channel name {p!r}; write the full name, e.g. {ref('game-day')}"
            for t in texts for p in plain_references(t or "")]
