"""/tradecheck: Constitution compliance for a proposed trade. It never grades value.

Checks
  (a) Article XII: a team giving a future 1st- or 2nd-round pick must be paid
      through that pick's Season in the League Ledger (12.2 to 12.4), using
      picktrades.py's Pick Clearance parser and verdict.
  (b) 6.1 roster limits after the trade. Incoming players are assumed to
      fill open active spots first, then reserve, unless the owner lists them for minors.
  (c) 11.6 trade window: closed from the deadline (end of Week 20, Sunday
      11:59 PM ET) until the day after the Stanley Cup Final.
  (d) A reminder of what the bot can't detect (11.3, 11.4, 11.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import deadlines
from . import embeds as E
from . import team as T
from .league_data import Clearance
from .shared import minors, picktrades

from blha import season  # noqa: E402  (path set up by .shared)

FOOTER = "BLHA LEAGUE BOT • TRADE CHECK"
# The deadline Week is the last regular Week minus 2 (Week 20 of 22), as in
# automation/commissioner/tasks.yaml (trade_deadline_weeks_before_end).
DEADLINE_WEEKS_BEFORE_END = 2
REOPENS_EVENT = "commissioner-trading-reopens"
DEADLINE_EVENT = "trade-deadline"
WORD_ROUNDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
CANT_CHECK = (
    "• Conditional draft picks are prohibited (11.5).\n"
    "• No outside consideration or side deals: no cash, loans, rentals, predetermined tradebacks or other "
    "off-platform consideration (11.3).\n"
    "• Only current-season FAAB may be traded (11.4).\n"
    "• Required prepayment must be confirmed in the League Ledger before the trade processes (12.4)."
)
ASSUMED = (
    "Incoming players fill open active spots first, then reserve, unless listed in to_minors. Outgoing players leave the slot Fantrax shows "
    "today. Position limits and minor eligibility aren't checked (use /minor)."
)


# ------------------------------------------------------------------ parsing
def split_list(text: str | None) -> list[str]:
    parts = re.split(r"[,;\n]|\band\b|&", text or "", flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def parse_picks(text: str | None) -> tuple[list[tuple[int, int]], list[str]]:
    """'2029 1st, 2028 3rd' -> ([(2029, 1), (2028, 3)], unreadable parts)."""
    picks, unread = [], []
    for part in split_list(text):
        low = part.lower()
        year = re.search(r"\b(20\d{2})\b", low)
        rnd = (re.search(r"\b([1-9])\s*(?:st|nd|rd|th)\b", low)
               or re.search(r"\b(?:round|rd|r)\s*([1-9])\b", low)
               or re.search(r"\b([1-9])\s*(?:round|rd)\b", low))
        number = int(rnd.group(1)) if rnd else next((n for w, n in WORD_ROUNDS.items() if re.search(rf"\b{w}\b", low)), None)
        if year and number:
            picks.append((int(year.group(1)), number))
        else:
            unread.append(part)
    return picks, unread


def roster_players(rosters: dict[str, Any] | None, team_id: str, player_ids: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """A team's players with names (getPlayerIds) and today's status, or None if the team isn't found."""
    items = T.roster_items(rosters, team_id)
    if items is None:
        return None
    out = []
    for item in items:
        info = (player_ids or {}).get(str(item.get("id"))) or {}
        out.append({"id": str(item.get("id")), "name": str(info.get("name") or ""),
                    "position": str(item.get("position") or info.get("position") or ""),
                    "status": T.status_key(item)})
    return out


def display_name(fantrax_name: str) -> str:
    first, last = minors().fantrax_name(fantrax_name)
    return f"{first} {last}".strip()


def match_players(text: str | None, players: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Match typed names to a roster: (found, not on the roster, ambiguous)."""
    m = minors()
    found, missing, ambiguous = [], [], []
    for query in split_list(text):
        q = m.norm(query)
        exact, by_last = [], []
        for p in players:
            if not p["name"]:
                continue
            first, last = m.fantrax_name(p["name"])
            if q in (m.norm(first + last), m.norm(last + first)):
                exact.append(p)
            elif q == m.norm(last):
                by_last.append(p)
        hits = exact or by_last
        if len(hits) == 1:
            if hits[0] not in found:
                found.append(hits[0])
        elif hits:
            ambiguous.append(f"{query} ({' or '.join(display_name(h['name']) for h in hits[:4])})")
        else:
            missing.append(query)
    return found, missing, ambiguous


# ------------------------------------------------------------ trade window
def trade_deadline(info: dict[str, Any] | None, tz: ZoneInfo) -> datetime | None:
    """Sunday 11:59 PM ET at the end of Week 20 (11.6), from the Fantrax calendar."""
    if not info:
        return None
    last_regular, _, _ = season.playoff_settings(info)
    week = season.period(info, last_regular - DEADLINE_WEEKS_BEFORE_END)
    if week is None:
        return None
    day = week.end.astimezone(tz).date()
    while day.weekday() != 6:  # back to that Week's Sunday
        day -= timedelta(days=1)
    deadline = datetime.combine(day, time(23, 59, 59), tzinfo=tz).astimezone(timezone.utc)
    return min(deadline, week.end)


def trade_window(now: datetime, deadline: datetime | None, reopens: datetime | None,
                 season_over: bool = False) -> tuple[str, str]:
    """(open | closed | unknown, explanation) for 11.6."""
    rule = "Trading closes at the end of Week 20 and reopens the day after the Stanley Cup Final ends (11.6)."
    if deadline is None:
        return "unknown", "The bot couldn't read the Fantrax calendar, so it can't check the deadline. " + rule
    if now < deadline:
        return "open", (f"Open. Trade deadline: {E.when(deadline)}. The trade must be fully processed in Fantrax "
                        "before then (11.6).")
    if reopens is not None and reopens > deadline:
        if now >= reopens:
            return "open", f"Open. Trading reopened {E.stamp(reopens)} (11.6)."
        return "closed", f"**Closed** since the deadline {E.stamp(deadline)}. Trading reopens {E.when(reopens)} (11.6)."
    if season_over:
        return "unknown", (f"The deadline passed {E.stamp(deadline)} and the Fantrax season is over. Trading reopens "
                           "the day after the Stanley Cup Final ends, when the Commissioner renews the league; that "
                           "date isn't on the League Calendar yet, so the bot can't confirm it (11.6).")
    return "closed", (f"**Closed** since the deadline {E.stamp(deadline)}. Trading reopens the day after the Stanley "
                      "Cup Final ends; that date isn't on the League Calendar yet (11.6).")


# ------------------------------------------------------------------ checks
@dataclass
class Side:
    franchise: str
    team_id: str
    players_text: str = ""
    picks_text: str = ""
    players_out: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    picks_out: list[tuple[int, int]] = field(default_factory=list)
    unread_picks: list[str] = field(default_factory=list)
    pick_problems: list[str] = field(default_factory=list)
    prepay: list[tuple[str, str]] = field(default_factory=list)   # (paid | unpaid | unknown, line)
    before: dict[str, int] | None = None
    after: dict[str, int] | None = None


@dataclass
class TradeCheck:
    a: Side
    b: Side
    window: tuple[str, str]
    to_minors_unmatched: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def problems(self) -> list[str]:
        out = []
        for s in (self.a, self.b):
            out += [f"{s.franchise}: {x} isn't on its roster" for x in s.missing]
            out += [f"{s.franchise}: {x}" for x in s.pick_problems]
            out += [f"{s.franchise}: prepayment" for status, _ in s.prepay if status == "unpaid"]
            if s.after is not None:
                out += [f"{s.franchise}: {T.LABELS[k]} over by {n}" for k, n in T.over_limits(s.after).items()]
        if self.window[0] == "closed":
            out.append("trade window closed")
        return out


def check_picks(side: Side, picks_raw: Any) -> None:
    """Ownership in Fantrax and the Article XII window."""
    if picks_raw is None:
        return  # reported once as a note by check()
    owned, _ = T.picks_of(picks_raw, side.team_id)
    years = sorted({p["year"] for p in T.future_picks(picks_raw)})
    have: dict[tuple[int, int], int] = {}
    for p in owned:
        have[(p["year"], p["round"])] = have.get((p["year"], p["round"]), 0) + 1
    wanted: dict[tuple[int, int], int] = {}
    for pick in side.picks_out:
        wanted[pick] = wanted.get(pick, 0) + 1
    for (year, rnd), n in sorted(wanted.items()):
        if have.get((year, rnd), 0) >= n:
            continue
        label = f"{year} {T.ordinal(rnd)}"
        if years and year not in years:
            side.pick_problems.append(f"{label} isn't tradeable in Fantrax (picks for {years[0]} to {years[-1]} "
                                      "are, the next three Annual Drafts, 12.1)")
        elif n > 1 and have.get((year, rnd), 0):
            side.pick_problems.append(f"owns only {have[(year, rnd)]} {label} pick(s), not {n}")
        else:
            side.pick_problems.append(f"doesn't own a {label} in Fantrax")


def check_prepayment(side: Side, clearance: Clearance) -> None:
    """Article XII for every future 1st and 2nd the side gives (picktrades.verdict)."""
    pt = picktrades()
    table = clearance.table if clearance.status == "ok" else None
    for year in sorted({y for y, r in side.picks_out if r in pt.PREPAY_ROUNDS}):
        status, paid = pt.verdict({"from": side.team_id, "year": year}, table)
        rounds = "/".join(T.ordinal(r) for r in sorted({r for y, r in side.picks_out if y == year and r in pt.PREPAY_ROUNDS}))
        if status == "paid":
            side.prepay.append((status, f"OK: {side.franchise} is paid through Season {paid}, so it can trade its "
                                        f"{year} {rounds} (needs Season {year})."))
        elif status == "unpaid":
            have = f"Season {paid}" if paid is not None else "no Season yet"
            side.prepay.append((status, f"**NOT PAID:** {side.franchise} must be paid through Season {year} before "
                                        f"trading its {year} {rounds}; the League Ledger shows {have} (12.2, 12.3). "
                                        "Pay first, then trade: an unpaid trade is reversed (12.4, 12.5)."))
        else:
            why = {"unset": "the League Ledger link isn't set up",
                   "error": "the League Ledger couldn't be read right now"}.get(
                clearance.status, "this franchise isn't on the Pick Clearance tab")
            side.prepay.append((status, f"CHECK: {side.franchise} must be paid through Season {year} to trade its "
                                        f"{year} {rounds}, but {why}. Confirm with the Commissioner (12.2 to 12.4)."))


def check(*, a: Side, b: Side, rosters: dict[str, Any] | None, player_ids: dict[str, Any] | None,
          picks_raw: Any, clearance: Clearance, to_minors: str, window: tuple[str, str]) -> TradeCheck:
    result = TradeCheck(a, b, window)
    for side in (a, b):
        side.picks_out, side.unread_picks = parse_picks(side.picks_text)
        players = roster_players(rosters, side.team_id, player_ids)
        if side.players_text.strip():
            if players is None:
                result.notes.append(f"Couldn't read {side.franchise}'s roster from Fantrax, so its players weren't checked.")
            elif player_ids is None:
                result.notes.append(f"Couldn't read player names from Fantrax, so {side.franchise}'s players weren't checked.")
            else:
                side.players_out, side.missing, side.ambiguous = match_players(side.players_text, players)
        check_picks(side, picks_raw)
        check_prepayment(side, clearance)
    if picks_raw is None and (a.picks_out or b.picks_out):
        result.notes.append("Couldn't read draft picks from Fantrax, so pick ownership wasn't checked.")

    # Incoming players fill open active spots first, then reserve, unless the
    # receiving owner would put them in minors.
    to_minors_ids: set[str] = set()
    for query in split_list(to_minors):
        found, _, _ = match_players(query, a.players_out + b.players_out)
        if found:
            to_minors_ids.add(found[0]["id"])
        else:
            result.to_minors_unmatched.append(query)
    for side, incoming in ((a, b.players_out), (b, a.players_out)):
        side.before = T.roster_counts(rosters, side.team_id)
        if side.before is None:
            continue
        after = dict(side.before)
        for p in side.players_out:
            after[p["status"]] = after.get(p["status"], 0) - 1
        for p in incoming:
            if p["id"] in to_minors_ids:
                slot = "minors"
            elif after.get("active", 0) < T.LIMITS["active"]:
                slot = "active"  # an open active spot is filled first (6.1)
            else:
                slot = "reserve"
            after[slot] = after.get(slot, 0) + 1
        side.after = after
    return result


def build(data: Any, a: Side, b: Side, to_minors: str, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    """The /tradecheck embed from a LeagueData-like source (blocking; run in a thread)."""
    any_players = bool(a.players_text.strip() or b.players_text.strip())
    any_picks = bool(a.picks_text.strip() or b.picks_text.strip())
    info = T.safely(data.league_info)
    rosters = T.safely(data.rosters)
    player_ids = T.safely(data.player_ids) if any_players else {}
    picks_raw = T.safely(data.draft_picks) if any_picks else {"futureDraftPicks": []}
    pt = picktrades()
    prepay = any(r in pt.PREPAY_ROUNDS for side in (a, b) for _, r in parse_picks(side.picks_text)[0])
    clearance = (T.safely(data.clearance) or Clearance("error")) if prepay else Clearance("unset")
    events = T.safely(data.events) or {}

    deadline = trade_deadline(info, tz) or deadlines.event_time(events, DEADLINE_EVENT)
    reopens = deadlines.event_time(events, REOPENS_EVENT)
    over = info is not None and season.phase(info, now) == season.OFFSEASON
    window = trade_window(now, deadline, reopens, over)
    return embed(check(a=a, b=b, rosters=rosters, player_ids=player_ids, picks_raw=picks_raw,
                       clearance=clearance, to_minors=to_minors, window=window))


# ---------------------------------------------------------------- rendering
def _gives(side: Side) -> str:
    lines = [f"{display_name(p['name'])} ({T.LABELS.get(p['status'], p['status'])})" for p in side.players_out]
    lines += [f"{y} {T.ordinal(r)}" for y, r in side.picks_out]
    lines += [f"**Not on {side.franchise}'s roster:** {x}" for x in side.missing]
    lines += [f"**More than one match:** {x}" for x in side.ambiguous]
    lines += [f"**Couldn't read pick:** {x} (write it like 2029 1st)" for x in side.unread_picks]
    lines += [f"**{x[0].upper() + x[1:]}**" for x in side.pick_problems]
    return "\n".join(lines) or "Nothing"


def embed(c: TradeCheck) -> dict[str, Any]:
    problems = c.problems()
    unknown = any(s == "unknown" for side in (c.a, c.b) for s, _ in side.prepay) or c.window[0] == "unknown"
    if problems:
        summary = f"**{len(problems)} problem{'s' if len(problems) != 1 else ''} found.** Details below."
    elif unknown:
        summary = "No problems found, but some items need a manual check (marked CHECK)."
    else:
        summary = "No problems found in what the bot can check."
    prepay = [line for side in (c.a, c.b) for _, line in side.prepay]
    if not prepay:
        prepay = ["No future 1st- or 2nd-round picks in this trade, so no prepayment is needed. Rounds 3 to 5 never "
                  "need extra prepayment (12.7)."]
    rosters = []
    for side in (c.a, c.b):
        if side.after is None:
            rosters.append(f"**{side.franchise}:** couldn't read its roster from Fantrax.")
        else:
            line = f"**{side.franchise}:** {T.roster_text(side.after, ' • ')}"
            if side.before is not None and T.over_limits(side.before):
                line += " (already over a limit before this trade)"
            rosters.append(line)
    if any(side.after and T.over_limits(side.after) for side in (c.a, c.b)):
        rosters.append("A team over a limit must fix it within 24 hours of notice (6.4).")
    assumed = ASSUMED
    if c.to_minors_unmatched:
        assumed += " Not part of this trade, ignored for minors: " + ", ".join(c.to_minors_unmatched) + "."
    fields = [
        (f"{c.a.franchise.upper()} GIVES", _gives(c.a)),
        (f"{c.b.franchise.upper()} GIVES", _gives(c.b)),
        ("PREPAYMENT (12.2 TO 12.4)", "\n".join(prepay)),
        ("ROSTER LIMITS AFTER THE TRADE (6.1)", "\n".join(rosters)),
        ("TRADE WINDOW (11.6)", c.window[1]),
        ("THE BOT CAN'T CHECK", CANT_CHECK),
        ("ASSUMED", assumed + (" " + " ".join(c.notes) if c.notes else "")),
    ]
    return E.card("TRADE CHECK", f"**{c.a.franchise}** and **{c.b.franchise}**\n"
                  f"Compliance only: this check never grades value.\n\n{summary}", fields, FOOTER)
