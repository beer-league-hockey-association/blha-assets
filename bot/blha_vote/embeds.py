"""Discord embeds for the BLHA League Bot, as plain dicts (discord.Embed.from_dict).

Wording and layout follow the league-office vote templates (50, 51, 52) so
bot posts look like the rest of the server: one embed, gold accent, footer
and divider image on the final embed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .rules import ABSTAIN, NO, YES, Kind, Outcome

GOLD = 0xFFB81C
RAW = "https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/main/"
DIVIDER = RAW + "discord/webhooks/shared/blha-footer-divider-1600x90.png?v=2c6-frozen"
STAMP_PASSED = RAW + "brand/kit/06_seals_stamps/blha-stamp-vote-passed.png"
STAMP_FAILED = RAW + "brand/kit/06_seals_stamps/blha-stamp-vote-failed.png"
CHOICE_LABEL = {YES: "Yes", NO: "No", ABSTAIN: "Abstain"}


def stamp(dt: datetime, style: str = "F") -> str:
    """Discord timestamp: each member sees it in their own time zone."""
    return f"<t:{int(dt.timestamp())}:{style}>"


def when(dt: datetime) -> str:
    """Full date and time plus a relative countdown, e.g. for deadlines."""
    return f"{stamp(dt)} ({stamp(dt, 'R')})"


# Discord embed limits.
TITLE_MAX = 256
DESCRIPTION_MAX = 4096
FIELD_NAME_MAX = 256
FIELD_VALUE_MAX = 1024
FIELDS_MAX = 25
FOOTER_MAX = 2048
EMBEDS_MAX = 10
MESSAGE_MAX = 6000


def clip(text: str, limit: int) -> str:
    """Shorten text to a Discord limit, marking the cut."""
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def card(title: str, description: str, fields: list[tuple[str, str]], footer: str,
         *, thumbnail: str | None = None) -> dict[str, Any]:
    """One embed in the house style, clipped to Discord's limits."""
    embed: dict[str, Any] = {
        "title": clip(title, TITLE_MAX),
        "description": clip(description, DESCRIPTION_MAX),
        "color": GOLD,
        "fields": [{"name": clip(n, FIELD_NAME_MAX), "value": clip(v or "​", FIELD_VALUE_MAX), "inline": False}
                   for n, v in fields[:FIELDS_MAX]],
        "footer": {"text": clip(footer, FOOTER_MAX)},
        "image": {"url": DIVIDER},
    }
    if thumbnail:
        embed["thumbnail"] = {"url": thumbnail}
    return embed


def counted(embed: dict[str, Any]) -> int:
    """Characters Discord counts toward the 6,000 per-message limit."""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += len((embed.get("footer") or {}).get("text", ""))
    total += sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    return total


def finish(embeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several embeds in one message: footer text and divider on the final embed only."""
    kept = embeds[:EMBEDS_MAX]
    out = []
    for i, embed in enumerate(kept):
        embed = dict(embed)
        if i < len(kept) - 1:
            embed.pop("footer", None)
            embed.pop("image", None)
        out.append(embed)
    return out


def fits(embeds: list[dict[str, Any]]) -> bool:
    """True if a message with these embeds is within every Discord limit."""
    if not embeds or len(embeds) > EMBEDS_MAX or sum(counted(e) for e in embeds) > MESSAGE_MAX:
        return False
    for e in embeds:
        if len(e.get("title", "")) > TITLE_MAX or len(e.get("description", "")) > DESCRIPTION_MAX:
            return False
        if len(e.get("fields", [])) > FIELDS_MAX:
            return False
        if any(len(f["name"]) > FIELD_NAME_MAX or len(f["value"]) > FIELD_VALUE_MAX or not f["value"]
               for f in e.get("fields", [])):
            return False
    return True


def _embed(title: str, description: str, fields: list[tuple[str, str]], footer: str,
           *, thumbnail: str | None = None) -> dict[str, Any]:
    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": GOLD,
        "fields": [{"name": n, "value": v[:1024], "inline": False} for n, v in fields],
        "footer": {"text": footer},
        "image": {"url": DIVIDER},
    }
    if thumbnail:
        embed["thumbnail"] = {"url": thumbnail}
    return embed


def proposal(p: dict[str, Any], opens_at: datetime, suggestion_url: str | None = None) -> dict[str, Any]:
    season = f"Season {p['effective_season']}" if p.get("effective_season") else "Next Season"
    fields = [
        ("AFFECTED RULE", p["affected_rule"]),
        ("REPLACEMENT LANGUAGE", p["replacement"]),
        ("INTENDED EFFECTIVE DATE", season),
        ("PROPOSED BY", p["proposed_by"]),
    ]
    if suggestion_url:
        fields.append(("FROM SUGGESTION", suggestion_url))
    fields.append(("VOTING OPENS", f"**{stamp(opens_at)}** at the earliest • at least 7 days after this post (20.2)"))
    return _embed(
        "AMENDMENT PROPOSAL — DISCUSSION",
        f"**{p['title']}**\nProposal #{p['id']}",
        fields,
        "BLHA LEAGUE VOTING • DISCUSSION ONLY",
    )


def vote_open(v: dict[str, Any], kind: Kind, threshold: str, options: list[str], warnings: list[str]) -> dict[str, Any]:
    if kind.rule == "supermajority":
        opts = "**Yes** — adopt\n**No** — keep the current rule\n**Abstain** — counted as not affirmative"
        if kind.key == "removal":
            opts = "**Yes** — remove the Commissioner\n**No** — keep the Commissioner\n**Abstain**"
        who = "One formal vote per franchise, cast by the **Franchise Owner**. You can change it until the vote closes."
    else:
        opts = "\n".join(f"**{o}**" for o in options) + "\n**Abstain**"
        who = "One vote per active franchise, cast by the **Franchise Owner**. You can change it until the vote closes."
    fields = [
        ("QUESTION", v["question"]),
        ("OPTIONS", opts),
        ("VOTING CLOSES", f"**{stamp(v['closes_at'])}** ({stamp(v['closes_at'], 'R')})"),
        ("PASSAGE REQUIREMENT", threshold),
        ("WHO VOTES", who),
    ]
    if v.get("effective"):
        fields.append(("EFFECTIVE", f"{v['effective']} • must pass before that Season's dues deadline (20.4)"))
    if warnings:
        fields.append(("NOTE", "\n".join(warnings)))
    return _embed("OFFICIAL BLHA VOTE", f"**{v['title']}**\n{kind.label} • Vote #{v['id']}", fields,
                  "BLHA LEAGUE VOTING • OFFICIAL")


def result(v: dict[str, Any], kind: Kind, outcome: Outcome, ballots: dict[str, str] | None) -> dict[str, Any]:
    if kind.rule == "supermajority":
        verdict = "PASSED" if outcome.passed else "FAILED"
    else:
        verdict = f"ELECTED: {outcome.winner}" if outcome.winner else "NO MAJORITY"
    fields = [("RESULT", f"**{verdict}**"), ("VOTE TOTAL", outcome.summary)]
    if v.get("effective") and kind.rule == "supermajority":
        fields.append(("EFFECTIVE", v["effective"] if outcome.passed else "N/A"))
    if kind.key in ("amendment", "services"):
        fields.append(("NEXT STEP", "The Commissioner updates and reposts the Constitution."
                       if outcome.passed else "No change to the Constitution."))
    elif kind.rule == "majority" and not outcome.winner:
        fields.append(("NEXT STEP", "No candidate reached a majority. A new vote is needed."))
    if ballots is not None:
        lines = [f"{name}: {CHOICE_LABEL.get(choice, choice)}" for name, choice in sorted(ballots.items())]
        lines += [f"{name}: not voted" for name in outcome.not_voted]
        fields.append(("BALLOTS", "\n".join(lines) or "None"))
    thumb = STAMP_PASSED if outcome.passed else STAMP_FAILED
    return _embed("VOTE RESULT", f"**{v['title']}**\n{kind.label} • Vote #{v['id']}", fields,
                  "BLHA LEAGUE VOTING • FINAL RESULT", thumbnail=thumb)


def reminder(v: dict[str, Any], not_voted: list[str]) -> dict[str, Any]:
    return _embed(
        "VOTE CLOSING SOON",
        f"**{v['title']}** • Vote #{v['id']}",
        [("CLOSES", f"**{stamp(v['closes_at'])}** ({stamp(v['closes_at'], 'R')})"),
         ("NOT VOTED YET", "\n".join(not_voted) or "Everyone has voted.")],
        "BLHA LEAGUE VOTING • REMINDER",
    )


def panel(ruling: str, pool: list[str], excluded: list[str], picks: list[tuple[str, int]], at: datetime) -> dict[str, Any]:
    return _embed(
        "REVIEW PANEL DRAW",
        f"Appeal: **{ruling}**",
        [
            ("PANEL", "\n".join(f"<@{uid}> ({name})" for name, uid in picks)),
            ("NOT ELIGIBLE (AFFECTED)", ", ".join(excluded) or "None"),
            ("DRAWN FROM", ", ".join(pool)),
            ("WHEN", stamp(at)),
            ("NEXT", "The Panel decides by majority within 7 days. Its decision is final for this matter (19.4)."),
        ],
        "BLHA COMMISSIONER'S OFFICE • RULINGS LOG",
    )
