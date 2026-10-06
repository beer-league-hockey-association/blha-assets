"""/minor: is a player BLHA minor-eligible? (Article VII)

7.2  Age 25 or younger on the first day of the NHL regular season, measured on
     that date for the whole Season. Fantrax's age calculation is final.
7.3  Skaters: 100 or fewer career NHL regular-season games. Goalies: 50 or fewer.

The NHL lookups and the age and games rules are reused from
automation/commissioner/minors.py. Opening day is the start of Fantrax Week 1,
which the Constitution aligns with the NHL opener (Article V). When Fantrax has
no calendar for the Season yet, October 1 is used and labeled as an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import embeds as E
from .shared import minors

from blha import season  # noqa: E402  (path set up by .shared)

NOTE = "By NHL data. Fantrax's age calculation is final (7.2)."
FOOTER = "BLHA LEAGUE BOT • MINOR ELIGIBILITY"
ESTIMATED_OPENING = (10, 1)
NEAR_LIMIT = 10


@dataclass(frozen=True)
class Opening:
    day: date
    season: int
    estimated: bool


@dataclass(frozen=True)
class Verdict:
    age: int
    games: int
    goalie: bool
    limit: int
    eligible: bool
    reasons: tuple[str, ...]


def verdict(birth: str | date, games: int, goalie: bool, opening_day: date) -> Verdict:
    """The Article VII test, with age measured on opening day (7.2) and the skater or goalie limit (7.3)."""
    m = minors()
    born = birth.isoformat() if isinstance(birth, date) else str(birth)
    age = m.age_on(born, opening_day)
    limit = m.MAX_GP["goalie" if goalie else "skater"]
    reasons = []
    if age > m.MAX_AGE:
        reasons.append(f"age {age} on opening day (limit {m.MAX_AGE})")
    if games > limit:
        reasons.append(f"{games} career NHL regular-season games (limit {limit})")
    return Verdict(age, games, goalie, limit, m.eligible(age, games, goalie), tuple(reasons))


def opening_day(info: dict[str, Any] | None, now: datetime, tz: ZoneInfo) -> Opening:
    """Opening day of the Season minor eligibility is measured for.

    During a Season (and before it, once Fantrax has its calendar) this is the
    start of Week 1. After the Fantrax season ends, it is the next Season's
    opener, estimated as October 1 until the new calendar exists.
    """
    local = now.astimezone(tz)
    fallback_year = local.year if local.month >= 5 else local.year - 1
    if info:
        weeks = season.periods(info)
        year = int(info.get("seasonYear") or 0) or None
        if weeks and now <= weeks[-1].end:
            first = weeks[0].start.astimezone(tz).date()
            return Opening(first, year or first.year, False)
        if weeks:
            year = (year or weeks[0].start.astimezone(tz).year) + 1
        fallback_year = year or fallback_year
    return Opening(date(fallback_year, *ESTIMATED_OPENING), fallback_year, True)


# ------------------------------------------------------------ NHL responses
def query_name(query: str) -> str:
    """Accept Fantrax-style "Last, First" as well as "First Last"."""
    query = " ".join(query.split())
    if "," in query:
        first, last = minors().fantrax_name(query)
        return f"{first} {last}".strip()
    return query


def candidates(hits: Any, query: str, team: str | None = None) -> list[dict[str, Any]]:
    """Players from the NHL search response that match the query, best tier first.

    Tiers: exact full name, then exact last name, then a partial name. When
    several share the exact name and only one is active, that one wins.
    """
    m = minors()
    rows = []
    for h in hits if isinstance(hits, list) else []:
        if not isinstance(h, dict) or not h.get("playerId") or not h.get("name"):
            continue
        try:
            pid = int(h["playerId"])
        except (TypeError, ValueError):
            continue
        rows.append({
            "id": pid, "name": str(h["name"]), "position": str(h.get("positionCode") or ""),
            "team": str(h.get("teamAbbrev") or h.get("lastTeamAbbrev") or ""),
            "active": bool(h.get("active", True)),
        })
    if team:
        wanted = m.TEAM_ALIAS.get(team.strip().upper(), team.strip().upper())
        rows = [r for r in rows if r["team"].upper() == wanted]
    q = m.norm(query_name(query))
    if not q:
        return []
    tiers = (
        lambda r: m.norm(r["name"]) == q,
        lambda r: m.norm(r["name"].split()[-1]) == q,
        lambda r: q in m.norm(r["name"]),
    )
    for test in tiers:
        found = [r for r in rows if test(r)]
        if found:
            active = [r for r in found if r["active"]]
            return active if len(found) > 1 and len(active) == 1 else found
    return []


def landing_facts(landing: Any) -> dict[str, Any]:
    """Birth date, career regular-season games and position from the NHL player landing page."""
    landing = landing if isinstance(landing, dict) else {}
    first = (landing.get("firstName") or {}).get("default", "")
    last = (landing.get("lastName") or {}).get("default", "")
    totals = (landing.get("careerTotals") or {}).get("regularSeason") or {}
    try:
        games = int(totals.get("gamesPlayed") or 0)
    except (TypeError, ValueError):
        games = 0
    return {
        "name": f"{first} {last}".strip(),
        "birthDate": landing.get("birthDate"),
        "games": games,
        "position": str(landing.get("position") or ""),
        "team": str(landing.get("currentTeamAbbrev") or ""),
    }


def ambiguous_message(query: str, found: list[dict[str, Any]]) -> str:
    shown = ", ".join(f"{r['name']} ({r['team'] or 'no team'}, {r['position'] or '?'})" for r in found[:6])
    more = f" and {len(found) - 6} more" if len(found) > 6 else ""
    return (f"More than one player matches “{E.clip(query, 60)}”: {shown}{more}. "
            "Use the full name, or add the NHL team, e.g. `team: CAR`.")


def unknown_message(query: str) -> str:
    return (f"No NHL player matches “{E.clip(query, 60)}”. Check the spelling. The lookup uses the NHL's "
            "player search, so a prospect without an NHL player page can't be found.")


def lookup(nhl: Any, info: dict[str, Any] | None, query: str, team: str | None, now: datetime,
           tz: ZoneInfo) -> tuple[dict[str, Any] | None, str | None]:
    """(embed, None) for one matched player, or (None, message) when unknown or ambiguous.

    ``nhl`` is an NHLLookup (search and landing); blocking, so run it in a thread.
    """
    found = candidates(nhl.search(query_name(query)), query, team)
    if not found:
        return None, unknown_message(query + (f" ({team})" if team else ""))
    if len(found) > 1:
        return None, ambiguous_message(query, found)
    hit = found[0]
    facts = landing_facts(nhl.landing(hit["id"]))
    if not facts["birthDate"]:
        return None, f"The NHL has no birth date for {hit['name']}, so the bot can't check eligibility."
    position = facts["position"] or hit["position"]
    opening = opening_day(info, now, tz)
    v = verdict(str(facts["birthDate"]), facts["games"], position == "G", opening.day)
    player = {"name": facts["name"] or hit["name"], "team": facts["team"] or hit["team"],
              "position": position, "birthDate": facts["birthDate"]}
    return embed(player, v, opening), None


def _day(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def embed(player: dict[str, Any], v: Verdict, opening: Opening) -> dict[str, Any]:
    kind = "Goalie" if v.goalie else "Skater"
    about = " • ".join(x for x in (player.get("team") or "No NHL team", player.get("position"),
                                    f"born {player.get('birthDate')}") if x)
    estimate = (f"\nOpening day for Season {opening.season} isn't in Fantrax yet, so this uses {_day(opening.day)}."
                if opening.estimated else "")
    note = NOTE
    if v.eligible and v.games >= v.limit - NEAR_LIMIT:
        note += f" Within {v.limit - v.games} games of the limit; career games keep counting during the Season (7.3)."
    fields = [
        ("AGE ON OPENING DAY", f"**{v.age}** on {_day(opening.day)} (Season {opening.season}). Measured on that "
                               f"date for the whole Season: 25 or younger (7.2).{estimate}"),
        ("CAREER NHL GAMES", f"**{v.games}** regular-season games"),
        ("THRESHOLD", f"{kind}: {v.limit} or fewer career NHL regular-season games (7.3)"),
    ]
    if not v.eligible:
        fields.append(("WHY NOT", "; ".join(v.reasons).capitalize() + "."))
    fields.append(("NOTE", note))
    return E.card(
        f"MINOR ELIGIBILITY — {str(player.get('name') or '').upper()}",
        f"{about}\n\n**BLHA minor-eligible: {'YES' if v.eligible else 'NO'}**",
        fields,
        FOOTER,
    )
