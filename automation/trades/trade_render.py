"""Discord payloads for the Trade Desk: report card with poll, revisits, deadline-day tracker.

Layouts follow automation/DISCORD_AUTOMATION_STYLE.md: one embed, league and
season line at the top, vertical fields, no decorative emoji, BLHA gold, short
footer. Text and links only (no images). Every vote and points total is for
fun: trades are unlimited, never voted on and never reversed because of value
(Article XI), and nothing here suggests otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from blha.league import AVATAR, DEFAULT_LEAGUE_NAME, color_value

TRADE_DISCUSSION = "💬│trade-discussion"
COMPLETED_TRADES = "🚨│completed-trades"
POLL_QUESTION = "Who won the trade?"
EVEN = "Even"
POLL_HOURS = 72
POLL_ANSWER_MAX = 55         # Discord's limit for a poll answer's text
POLL_ANSWERS_MAX = 10
CARD_FOOTER = "BLHA TRADE CENTER • JUST FOR FUN: THE VOTE NEVER AFFECTS THE TRADE (ARTICLE XI)"
REVISIT_FOOTER = "BLHA TRADE CENTER • JUST FOR FUN: A TRADE IS NEVER REVERSED BECAUSE OF VALUE (ARTICLE XI)"
TRACKER_FOOTER = "BLHA LEAGUE OFFICE • LIVE: UPDATED EVERY 15 MINUTES"
TRACKER_FINAL_FOOTER = "BLHA LEAGUE OFFICE • FINAL"
FIELD_MAX = 1024
EMBED_BUDGET = 5800          # Discord allows 6,000 characters per message; keep a margin
TRACKER_MAX_TRADES = 20
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def ordinal(n: int) -> str:
    return ORDINAL.get(n, f"{n}th")


def _ts(iso: str) -> int:
    when = datetime.fromisoformat(iso)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return int(when.timestamp())


def _clip(text: str, limit: int = FIELD_MAX) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 2].rsplit("\n", 1)[0]
    return cut + "\n…"


def header(cfg: dict[str, Any]) -> str:
    label = str(cfg.get("season_label") or "").strip()
    return f"**{DEFAULT_LEAGUE_NAME}**" + (f" • {label}" if label else "")


def display_name(fantrax_name: str) -> str:
    """'McDavid, Connor' -> 'Connor McDavid'."""
    if fantrax_name.count(",") == 1:
        last, first = (part.strip() for part in fantrax_name.split(",", 1))
        return f"{first} {last}".strip()
    return fantrax_name


def team_name(trade: dict[str, Any], team_id: str) -> str:
    return str((trade.get("names") or {}).get(team_id) or team_id or "Unknown team")


def pick_parts(key: str) -> tuple[int, int, str] | None:
    parts = str(key).split("|")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), parts[2]
    except ValueError:
        return None


def asset_label(trade: dict[str, Any], asset: str, *, short: bool = False) -> str:
    """'Connor McDavid (C, EDM)' or '2028 1st round pick (Test 3)' (short: no position/team, '2028 1st (Test 3)')."""
    kind, _, value = str(asset).partition(":")
    if kind == "player":
        row = (trade.get("players") or {}).get(value) or {}
        name = display_name(str(row.get("name") or f"Player {value}"))
        bits = [b for b in (row.get("position"), row.get("team")) if b and b != "(N/A)"]
        return name if short or not bits else f"{name} ({', '.join(bits)})"
    parsed = pick_parts(value)
    if not parsed:
        return f"Pick {value}"
    year, rnd, original = parsed
    word = "" if short else " round pick"
    return f"{year} {ordinal(rnd)}{word} ({team_name(trade, original)})"


def side_text(trade: dict[str, Any], team_id: str) -> str:
    assets = (trade.get("received") or {}).get(team_id) or []
    players = [a for a in assets if a.startswith("player:")]
    picks = [a for a in assets if not a.startswith("player:")]
    lines = [asset_label(trade, a) for a in sorted(players, key=lambda a: asset_label(trade, a))]
    lines += [asset_label(trade, a) for a in sorted(picks)]
    if not lines:
        return "Nothing Fantrax's data feed shows. FAAB isn't in the feed, so FAAB in a trade isn't listed."
    return _clip("\n".join(lines))


# --- feature 1: report card with poll ------------------------------------------------

def poll(trade: dict[str, Any], hours: int = POLL_HOURS) -> dict[str, Any]:
    """Discord poll create request: one answer per team plus Even, single choice."""
    teams = list(trade["teams"])[: POLL_ANSWERS_MAX - 1]
    answers = [{"poll_media": {"text": team_name(trade, t)[:POLL_ANSWER_MAX]}} for t in teams]
    answers.append({"poll_media": {"text": EVEN}})
    return {
        "question": {"text": POLL_QUESTION},
        "answers": answers,
        "duration": int(hours),
        "allow_multiselect": False,
        "layout_type": 1,
    }


def report_card(trade: dict[str, Any], cfg: dict[str, Any], *, test: bool = False,
                with_poll: bool = True, poll_hours: int = POLL_HOURS) -> dict[str, Any]:
    seen = _ts(trade["at"])
    vote = (f"Who won it? Vote in the poll; it closes in {poll_hours} hours." if with_poll
            else "Who won it? Talk it over below.")
    description = (f"{header(cfg)}\n"
                   f"A trade went through in Fantrax, seen <t:{seen}:f>. {vote}\n"
                   f"Owners post the official record in {COMPLETED_TRADES}.")
    fields = [{"name": f"{team_name(trade, t).upper()} RECEIVES", "value": side_text(trade, t), "inline": False}
              for t in trade["teams"]]
    payload: dict[str, Any] = {
        "username": "BLHA Trade Center",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": ("[TEST] " if test else "") + "TRADE REPORT CARD",
            "description": description,
            "fields": fields[:25],
            "color": color_value(cfg.get("color")),
            "footer": {"text": CARD_FOOTER},
            "timestamp": datetime.fromtimestamp(seen, timezone.utc).isoformat(),
        }],
    }
    if with_poll:
        payload["poll"] = poll(trade, poll_hours)
    return payload


def poll_tally(message: dict[str, Any] | None) -> dict[str, Any] | None:
    """{answers: [(text, votes)], total, final} from a Get Webhook Message answer, or None without a poll."""
    data = (message or {}).get("poll")
    if not isinstance(data, dict):
        return None
    answers = []
    for a in data.get("answers") or []:
        if isinstance(a, dict):
            answers.append((a.get("answer_id"), str(((a.get("poll_media") or {}).get("text")) or "")))
    if not answers:
        return None
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    counts = {c.get("id"): int(c.get("count") or 0) for c in results.get("answer_counts") or [] if isinstance(c, dict)}
    rows = [(text, counts.get(aid, 0)) for aid, text in answers]
    return {"answers": rows, "total": sum(n for _, n in rows), "final": bool(results.get("is_finalized"))}


def tally_text(tally: dict[str, Any]) -> str:
    lines = [f"{text}: {n} vote{'s' if n != 1 else ''}" for text, n in tally["answers"]]
    if not tally["total"]:
        lines = ["No votes were cast."]
    if not tally.get("final"):
        lines.append("(Discord had not finalized the count.)")
    return "\n".join(lines)


# --- feature 1: revisits ---------------------------------------------------------------

def revisit(trade: dict[str, Any], months: int, sides: dict[str, list[dict[str, Any]]], cfg: dict[str, Any], *,
            window: tuple[str, str], tally: dict[str, Any] | None = None, link: str | None = None,
            test: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """TRADE REVISIT — N months. ``sides``: team -> lines, each
    {kind: player, label, points, games, goalie, error, missing_box} or {kind: pick, text}."""
    seen = _ts(trade["at"])
    names = " and ".join(f"**{team_name(trade, t)}**" for t in trade["teams"])
    first, last = window
    description = (f"{header(cfg)}\n"
                   f"The trade between {names}, seen in Fantrax <t:{seen}:D>."
                   + (f" [Original report card]({link})" if link else "") + "\n\n"
                   f"Fantasy points from NHL regular-season games from {first} through {last}, scored with BLHA "
                   "values. Every game counts, even if a player has since moved to another BLHA team.")
    fields = []
    for t in trade["teams"]:
        lines = sides.get(t) or []
        players = [x for x in lines if x["kind"] == "player"]
        text: list[str] = []
        if players:
            scored = [x for x in players if not x.get("error")]
            if scored:
                total = sum(x.get("points") or 0 for x in scored)
                text.append(f"**{total:.2f} points** from the players received")
            for x in players:
                label = x["label"] + (" (G)" if x.get("goalie") else "")
                if x.get("error"):
                    text.append(f"{label}: NHL stats not available ({x['error']})")
                elif not x.get("games"):
                    text.append(f"{label}: no NHL games since the trade")
                else:
                    games = x["games"]
                    text.append(f"{label}: {x['points']:.2f} in {games} game{'s' if games != 1 else ''}")
            gaps = sum(int(x.get("missing_box") or 0) for x in players)
            if gaps:
                text.append(f"Hits and blocks couldn't be read for {gaps} game{'s' if gaps != 1 else ''}.")
        text += [x["text"] for x in lines if x["kind"] == "pick"]
        if not text:
            text = ["Nothing Fantrax's data feed shows (FAAB isn't in the feed)."]
        fields.append({"name": f"{team_name(trade, t).upper()} RECEIVED", "value": _clip("\n".join(text)),
                       "inline": False})
    if tally:
        fields.append({"name": "THE ORIGINAL VOTE", "value": _clip(tally_text(tally)), "inline": False})
    return {
        "username": "BLHA Trade Center",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": ("[TEST] " if test else "") + f"TRADE REVISIT — {months} months",
            "description": description,
            "fields": fields[:25],
            "color": color_value(cfg.get("color")),
            "footer": {"text": REVISIT_FOOTER},
            "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        }],
    }


# --- feature 2: deadline-day tracker ---------------------------------------------------

def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def tracker_field(trade: dict[str, Any], number: int, deadline: datetime | None = None) -> dict[str, Any]:
    seen = _ts(trade["at"])
    late = deadline is not None and seen > deadline.timestamp()
    lines = [f"Seen in Fantrax <t:{seen}:t>" + (" (first check after the deadline)" if late else "")]
    for t in trade["teams"]:
        assets = sorted((trade.get("received") or {}).get(t) or [], key=lambda a: (not a.startswith("player:"), a))
        got = [asset_label(trade, a, short=True) for a in assets]
        lines.append(f"**{team_name(trade, t)}** receives {', '.join(got) if got else 'nothing the feed shows'}")
    return {"name": f"TRADE {number}", "value": _clip("\n".join(lines)), "inline": False}


def _size(embed: dict[str, Any]) -> int:
    total = len(embed.get("title") or "") + len(embed.get("description") or "") + len(embed["footer"]["text"])
    return total + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields") or [])


def tracker(cfg: dict[str, Any], deadline: datetime, trades_today: list[dict[str, Any]], season_count: int, *,
            final: bool, now: datetime, test: bool = False) -> dict[str, Any]:
    """The one live BLHA TRADECENTRE message in 📢│announcements (edited until the deadline, then final)."""
    d = int(deadline.timestamp())
    n = len(trades_today)
    if final:
        title = "BLHA TRADECENTRE — FINAL"
        description = (f"{header(cfg)}\n"
                       f"**Deadline passed — {_plural(n, 'trade')} today.**\n"
                       "Trading reopens the day after the Stanley Cup Final ends (11.6).\n\n"
                       f"**Deadline:** <t:{d}:F>\n"
                       f"**Trades this season:** {season_count}\n\n"
                       f"Report cards and polls: {TRADE_DISCUSSION}")
    else:
        title = "BLHA TRADECENTRE"
        description = (f"{header(cfg)}\n"
                       "Trade deadline day. A trade must be fully processed in Fantrax before the deadline; "
                       "one processed after it is reversed (11.6).\n\n"
                       f"**Deadline:** <t:{d}:F>\n"
                       f"**Time left:** <t:{d}:R>\n"
                       f"**Trades today:** {n}\n"
                       f"**Trades this season:** {season_count}\n\n"
                       f"Report cards and polls: {TRADE_DISCUSSION}")
    fields = [tracker_field(t, i, deadline) for i, t in enumerate(trades_today, 1)]
    if not fields and not final:
        fields = [{"name": "TRADES TODAY", "inline": False,
                   "value": "None yet. A trade shows up here within 15 minutes of going through in Fantrax."}]
    embed = {
        "title": ("[TEST] " if test else "") + title,
        "description": description,
        "fields": fields,
        "color": color_value(cfg.get("color")),
        "footer": {"text": TRACKER_FINAL_FOOTER if final else TRACKER_FOOTER},
        "timestamp": now.isoformat(),
    }
    # Stay inside Discord's 25 fields and 6,000 characters on a busy day.
    shown = min(len(fields), TRACKER_MAX_TRADES)
    while fields and (shown < len(fields) or _size(embed) > EMBED_BUDGET):
        more = len(fields) - shown
        embed["fields"] = fields[:shown] + ([{"name": "MORE TRADES", "inline": False,
                                              "value": f"{_plural(more, 'more trade')} today. Every trade has a "
                                                       f"report card in {TRADE_DISCUSSION}."}] if more else [])
        if _size(embed) <= EMBED_BUDGET:
            break
        shown -= 1
    return {
        "username": "BLHA League Office",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }
