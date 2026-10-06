"""Discord embeds for the voting bot, as plain dicts (discord.Embed.from_dict).

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


def proposal(p: dict[str, Any], opens_at: datetime) -> dict[str, Any]:
    season = f"Season {p['effective_season']}" if p.get("effective_season") else "Next Season"
    return _embed(
        "AMENDMENT PROPOSAL — DISCUSSION",
        f"**{p['title']}**\nProposal #{p['id']}",
        [
            ("AFFECTED RULE", p["affected_rule"]),
            ("REPLACEMENT LANGUAGE", p["replacement"]),
            ("INTENDED EFFECTIVE DATE", season),
            ("PROPOSED BY", p["proposed_by"]),
            ("VOTING OPENS", f"**{stamp(opens_at)}** at the earliest • at least 7 days after this post (20.2)"),
        ],
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
