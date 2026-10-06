"""/myteam: one franchise's roster counts, picks, ledger status and this Week.

Pure functions over Fantrax responses, shared with /tradecheck:
  getTeamRosters  roster items carry only id, slot position and status
                  (ACTIVE, RESERVE, MINORS, IR); names come from getPlayerIds
  getDraftPicks   futureDraftPicks: year, round, original and current owner
  getLeagueInfo   season calendar, schedule and team names
  getMatchupScores  live scores for a Week
FAAB is not in Fantrax's feed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import deadlines
from . import embeds as E
from .league_data import Clearance
from .shared import picktrades

from blha import season  # noqa: E402  (path set up by .shared)
from blha.fantrax import schedule_for  # noqa: E402

# Section 6.1 roster limits by Fantrax status.
LIMITS = {"active": 20, "reserve": 6, "minors": 10, "ir": 5}
LABELS = {"active": "Active", "reserve": "Reserve", "minors": "Minors", "ir": "IR"}
STATUS = {"ACTIVE": "active", "RESERVE": "reserve", "MINORS": "minors", "MINOR": "minors",
          "IR": "ir", "INJURED_RESERVE": "ir"}
ROUND = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
FOOTER = "BLHA LEAGUE BOT • ONLY YOU CAN SEE THIS"
log = logging.getLogger("blha.bot")


def ordinal(n: int) -> str:
    return ROUND.get(n, f"{n}th")


def team_names(info: dict[str, Any] | None) -> dict[str, str]:
    """Fantrax team id -> team name, from getLeagueInfo's teamInfo."""
    out = {}
    for team_id, row in ((info or {}).get("teamInfo") or {}).items():
        if isinstance(row, dict):
            out[str(team_id)] = str(row.get("name") or team_id)
    return out


# ------------------------------------------------------------------ rosters
def roster_items(rosters: dict[str, Any] | None, team_id: str) -> list[dict[str, Any]] | None:
    """One team's roster items, or None if the team isn't in the response."""
    team = ((rosters or {}).get("rosters") or {}).get(team_id)
    if not isinstance(team, dict):
        return None
    return [i for i in team.get("rosterItems") or [] if isinstance(i, dict)]


def status_key(item: dict[str, Any]) -> str:
    return STATUS.get(str(item.get("status") or "").upper(), "other")


def roster_counts(rosters: dict[str, Any] | None, team_id: str) -> dict[str, int] | None:
    items = roster_items(rosters, team_id)
    if items is None:
        return None
    counts = {k: 0 for k in LIMITS}
    for item in items:
        key = status_key(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def over_limits(counts: dict[str, int]) -> dict[str, int]:
    """Status -> how many over its 6.1 limit."""
    return {k: counts.get(k, 0) - limit for k, limit in LIMITS.items() if counts.get(k, 0) > limit}


def roster_text(counts: dict[str, int], separator: str = "\n") -> str:
    parts = []
    for key, limit in LIMITS.items():
        n = counts.get(key, 0)
        part = f"{LABELS[key]} {n}/{limit}"
        parts.append(f"**{part} (over by {n - limit})**" if n > limit else part)
    if counts.get("other"):
        parts.append(f"Other {counts['other']}")
    return separator.join(parts)


# -------------------------------------------------------------------- picks
def future_picks(raw: Any) -> list[dict[str, Any]]:
    picks = raw.get("futureDraftPicks") if isinstance(raw, dict) else None
    out = []
    for p in picks if isinstance(picks, list) else []:
        if not isinstance(p, dict):
            continue
        try:
            out.append({"year": int(p.get("year")), "round": int(p.get("round")),
                        "original": str(p.get("originalOwnerTeamId") or ""),
                        "owner": str(p.get("currentOwnerTeamId") or "")})
        except (TypeError, ValueError):
            continue
    return out


def picks_of(raw: Any, team_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(picks the team owns now, its own picks now owned by someone else)."""
    picks = future_picks(raw)
    owned = sorted((p for p in picks if p["owner"] == team_id), key=lambda p: (p["year"], p["round"], p["original"] != team_id))
    away = sorted((p for p in picks if p["original"] == team_id and p["owner"] != team_id),
                  key=lambda p: (p["year"], p["round"]))
    return owned, away


def picks_text(owned: list[dict[str, Any]], away: list[dict[str, Any]], team_id: str,
               names: dict[str, str]) -> tuple[str, str]:
    by_year: dict[int, list[str]] = {}
    for p in owned:
        label = ordinal(p["round"])
        if p["original"] != team_id:
            label += f" (from {names.get(p['original'], p['original'])})"
        by_year.setdefault(p["year"], []).append(label)
    owned_text = "\n".join(f"**{y}:** {', '.join(v)}" for y, v in sorted(by_year.items())) or "None"
    away_text = "\n".join(f"{p['year']} {ordinal(p['round'])} to {names.get(p['owner'], p['owner'])}" for p in away)
    return owned_text, away_text or "None"


# --------------------------------------------------------------- this Week
def week_for(info: dict[str, Any] | None, now: datetime, tz: ZoneInfo) -> tuple[season.Period | None, bool]:
    """(the Week in progress or next to start, whether it has started)."""
    if not info:
        return None, False
    p = season.upcoming_period(info, now, tz)
    if p:
        return p, p.start <= now
    later = [w for w in season.periods(info) if w.start > now]
    return (later[0], False) if later else (None, False)


def opponent(info: dict[str, Any], number: int, team_id: str,
             scores: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """{id, name, mine, theirs} for a team's matchup in a Week, from live scores or the schedule."""
    for m in scores or []:
        away, home = m.get("away") or {}, m.get("home") or {}
        for me, them in ((away, home), (home, away)):
            if me.get("teamId") == team_id and them.get("teamId"):
                return {"id": them["teamId"], "name": them.get("teamName") or them["teamId"],
                        "mine": float(me.get("score") or 0), "theirs": float(them.get("score") or 0)}
    for pair in schedule_for(info, number):
        for me, them in ((pair["away"], pair["home"]), (pair["home"], pair["away"])):
            if me["teamId"] == team_id and them["teamId"]:
                return {"id": them["teamId"], "name": them["teamName"], "mine": None, "theirs": None}
    return None


def week_text(info: dict[str, Any] | None, period: season.Period | None, started: bool, team_id: str,
              scores: list[dict[str, Any]] | None) -> str:
    if info is None:
        return "Couldn't read Fantrax right now."
    if period is None:
        return "No Week is scheduled right now (Offseason)."
    label = f"Week {period.number}"
    last_regular, first_playoff, _ = season.playoff_settings(info)
    if period.number >= first_playoff:
        label += " (playoffs)"
    opp = opponent(info, period.number, team_id, scores if started else None)
    if opp is None:
        return f"{label}: no matchup for your team in Fantrax (bye, eliminated, or the bracket isn't set). Check Fantrax."
    if not started or opp["mine"] is None:
        return f"{label} vs **{opp['name']}** • starts {E.when(period.start)}"
    mine, theirs = opp["mine"], opp["theirs"]
    state = "leading" if mine > theirs else "trailing" if mine < theirs else "tied"
    return f"{label} vs **{opp['name']}**\n**{mine:.2f}** to {theirs:.2f} ({state}) • ends {E.when(period.end)}"


# ------------------------------------------------------------------- ledger
def paid_through(clearance: Clearance, team_id: str) -> tuple[str, int | None]:
    """(status, Season) where status is paid, none, missing, unset or error."""
    if clearance.status != "ok" or clearance.table is None:
        return clearance.status, None
    entry = clearance.table.get(team_id)
    if entry is None:
        return "missing", None
    paid = entry.get("paid_through")
    return ("paid", paid) if isinstance(paid, int) else ("none", None)


def paid_text(clearance: Clearance, team_id: str) -> str:
    status, paid = paid_through(clearance, team_id)
    return {
        "paid": f"Season {paid}",
        "none": "No Season confirmed yet",
        "missing": "Not on the League Ledger's Pick Clearance tab yet",
        "unset": f"Not available: the League Ledger link ({picktrades().CLEARANCE_ENV}) isn't set",
        "error": "Couldn't read the League Ledger right now",
    }.get(status, "Unknown")


def myteam_embed(franchise: str, fantrax_name: str | None, roster: str, picks: tuple[str, str] | None,
                 week: str, paid: str, deadlines_text: str) -> dict[str, Any]:
    fields = [("ROSTER (6.1)", roster), ("THIS WEEK", week)]
    if picks is None:
        fields.append(("DRAFT PICKS", "Couldn't read draft picks from Fantrax."))
    else:
        fields.append(("DRAFT PICKS OWNED", picks[0]))
        fields.append(("TRADED AWAY", picks[1]))
    fields.append(("LEAGUE LEDGER", f"Paid through: {paid}\nFAAB: check Fantrax\nTo trade a future 1st or 2nd, "
                                    "you must be paid through that pick's Season (12.2)."))
    fields.append(("NEXT DEADLINES", deadlines_text))
    lead = f"Fantrax team: **{fantrax_name}**" if fantrax_name and fantrax_name != franchise else "Your franchise"
    return E.card(franchise.upper(), lead + " • live from Fantrax", fields, FOOTER)


def safely(fn: Callable[..., Any], *args: Any) -> Any:
    """Call a data source; None (and a log line) if it fails, so one outage doesn't sink the reply."""
    try:
        return fn(*args)
    except Exception as exc:  # network, Fantrax or file errors
        log.warning("%s failed: %s", getattr(fn, "__name__", "data source"), exc)
        return None


def build(data: Any, franchise: str, team_id: str, now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    """The /myteam embed from a LeagueData-like source (blocking; run in a thread)."""
    info = safely(data.league_info)
    rosters = safely(data.rosters)
    picks_raw = safely(data.draft_picks)
    period, started = week_for(info, now, tz)
    scores = safely(data.matchup_scores, period.number) if period is not None and started else None
    clearance = safely(data.clearance) or Clearance("error")
    events = safely(data.events)

    names = team_names(info)
    counts = roster_counts(rosters, team_id)
    if rosters is None:
        roster = "Couldn't read rosters from Fantrax right now."
    elif counts is None:
        roster = f"Fantrax has no roster for team ID {team_id}. Check fantrax_team_id in the bot config."
    else:
        roster = roster_text(counts)
        if over_limits(counts):
            roster += "\nOver a limit: fix it within 24 hours of notice (6.4)."
    picks = picks_text(*picks_of(picks_raw, team_id), team_id, names) if picks_raw is not None else None
    if events is None:
        upcoming = "Couldn't read the League Calendar right now."
    else:
        upcoming = deadlines.lines(deadlines.upcoming(events, now, 2))
    return myteam_embed(franchise, names.get(team_id), roster, picks,
                        week_text(info, period, started, team_id, scores), paid_text(clearance, team_id), upcoming)
