"""Discord payloads for BLHA Competition Desk posts.

Layouts follow automation/DISCORD_AUTOMATION_STYLE.md and keep the approved
scoreboard / standings / recap / playoff race / preview formats: BLHA
Competition Desk sender, gold accent, vertical fields, no emoji, short footer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from blha.league import AVATAR, DEFAULT_LEAGUE_NAME
from blha.season import Period


@dataclass
class Context:
    league_name: str
    season_label: str
    color: int
    test: bool = False


def _fmt_score(value: float) -> str:
    return f"{value:.2f}"


def _fmt_gp(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _fmt_gb(value: float) -> str:
    if abs(value) < 0.0001:
        return "—"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def window(p: Period | None) -> str:
    if not p:
        return ""
    return f"<t:{int(p.start.timestamp())}:D> – <t:{int(p.end.timestamp())}:D>"


def _header(ctx: Context, p: Period | None = None) -> str:
    text = f"**{ctx.league_name or DEFAULT_LEAGUE_NAME}**"
    if ctx.season_label:
        text += f" • {ctx.season_label}"
    if p:
        text += f"\n**Scoring Period:** {window(p)}"
    return text


def _payload(ctx: Context, title: str, description: str, fields: list[dict], footer: str) -> dict[str, Any]:
    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": ("[TEST] " + title) if ctx.test else title,
            "description": description,
            "fields": fields[:25],
            "color": ctx.color,
            "footer": {"text": f"{footer} • FANTRAX READ-ONLY DATA"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }


# --- Scoreboard ---------------------------------------------------------------

def scoreboard_fields(rows: list[dict]) -> list[dict]:
    fields = []
    for index, row in enumerate(rows, start=1):
        away, home = row["away"], row["home"]
        a, h = _fmt_score(away["score"]), _fmt_score(home["score"])
        if away["score"] > home["score"]:
            a_text, h_text = f"**{a} pts**", f"{h} pts"
        elif home["score"] > away["score"]:
            a_text, h_text = f"{a} pts", f"**{h} pts**"
        else:
            a_text, h_text = f"{a} pts", f"{h} pts"
        fields.append({
            "name": f"Matchup {index}",
            "value": (
                f"**{away['teamName']}** *(Away)* — {a_text} • `{_fmt_gp(away['gamesPlayed'])} GP`\n"
                f"**{home['teamName']}** *(Home)* — {h_text} • `{_fmt_gp(home['gamesPlayed'])} GP`"
            ),
            "inline": False,
        })
    return fields


def scoreboard(ctx: Context, p: Period, rows: list[dict], *, final: bool, playoffs: bool) -> dict[str, Any]:
    label = "Playoffs " if playoffs else ""
    title = f"BLHA {label}Week {p.number} {'Final ' if final else ''}Scoreboard"
    if final:
        note = "*Final scores for the week, from Fantrax. The winning score is bolded.*"
    else:
        note = (
            "*Live scoreboard from Fantrax. This post updates through the week; "
            "the leading score is bolded.*"
        )
    return _payload(ctx, title, f"{_header(ctx, p)}\n\n{note}", scoreboard_fields(rows), "SCOREBOARD")


# --- Weekly recap -------------------------------------------------------------

def recap_fields(rows: list[dict]) -> list[dict]:
    fields = []
    for index, row in enumerate(rows, start=1):
        away, home = row["away"], row["home"]
        a, h = _fmt_score(away["score"]), _fmt_score(home["score"])
        margin = abs(away["score"] - home["score"])
        if away["score"] > home["score"]:
            a_text, h_text = f"**{a} pts**", f"{h} pts"
            result = f"Result: **{away['teamName']}** wins by {margin:.2f} pts"
        elif home["score"] > away["score"]:
            a_text, h_text = f"{a} pts", f"**{h} pts**"
            result = f"Result: **{home['teamName']}** wins by {margin:.2f} pts"
        else:
            a_text, h_text = f"{a} pts", f"{h} pts"
            result = "Result: Tie"
        fields.append({
            "name": f"Matchup {index}",
            "value": (
                f"**{away['teamName']}** *(Away)* — {a_text} • `{_fmt_gp(away['gamesPlayed'])} GP`\n"
                f"**{home['teamName']}** *(Home)* — {h_text} • `{_fmt_gp(home['gamesPlayed'])} GP`\n"
                f"{result}"
            ),
            "inline": False,
        })
    return fields


def recap_summary_fields(rows: list[dict]) -> list[dict]:
    teams = [row[side] for row in rows for side in ("away", "home")]
    if not teams or max(t["score"] for t in teams) <= 0:
        return []
    high = max(teams, key=lambda t: t["score"])
    margins = [(abs(r["away"]["score"] - r["home"]["score"]), r) for r in rows]
    closest_margin, closest = min(margins, key=lambda item: item[0])
    largest_margin, largest = max(margins, key=lambda item: item[0])

    def pairing(row: dict) -> str:
        return f"{row['away']['teamName']} vs. {row['home']['teamName']}"

    return [
        {"name": "High Score", "value": f"**{high['teamName']}** — {_fmt_score(high['score'])} pts", "inline": False},
        {"name": "Closest Matchup", "value": f"{pairing(closest)} — {closest_margin:.2f}-point margin", "inline": False},
        {"name": "Largest Margin", "value": f"{pairing(largest)} — {largest_margin:.2f}-point margin", "inline": False},
    ]


def recap(ctx: Context, p: Period, rows: list[dict]) -> dict[str, Any]:
    description = f"{_header(ctx, p)}\n\n*Completed matchup results pulled directly from Fantrax.*"
    return _payload(ctx, f"BLHA Week {p.number} Recap", description,
                    recap_fields(rows) + recap_summary_fields(rows), "WEEKLY RECAP")


# --- Standings ----------------------------------------------------------------

def standings(ctx: Context, rows: list[dict], *, after_week: int, playoff_cut: int, final: bool) -> dict[str, Any]:
    fields = []
    for row in rows:
        title = f"{row['rank']}. {row['teamName']}"
        if row["rank"] == playoff_cut:
            title += " — Playoff Cut"
        fields.append({
            "name": title,
            "value": (
                f"**Record:** {row['record']} • "
                f"**PF:** {row['pointsFor']:.2f} • "
                f"**GB:** {_fmt_gb(row['gamesBack'])}"
            ),
            "inline": False,
        })
    if final:
        title = "BLHA Final Regular-Season Standings"
        note = f"*Final regular-season standings from Fantrax. The top {playoff_cut} teams qualify for the playoffs.*"
    else:
        title = f"BLHA League Standings — After Week {after_week}"
        note = f"*Standings pulled directly from Fantrax. The top {playoff_cut} teams currently occupy playoff positions.*"
    return _payload(ctx, title, f"{_header(ctx)}\n\n{note}", fields, "STANDINGS")


# --- Playoff race -------------------------------------------------------------

def playoff_race(
    ctx: Context,
    rows: list[dict],
    *,
    after_week: int,
    weeks_left: int,
    playoff_cut: int,
    bubble_depth: int,
) -> dict[str, Any]:
    limit = min(len(rows), playoff_cut + bubble_depth)
    fields = []
    for row in rows[:limit]:
        title = f"{row['rank']}. {row['teamName']}"
        if row["rank"] == playoff_cut:
            title += " — Playoff Cut"
        fields.append({
            "name": title,
            "value": (
                f"**Record:** {row['record']} • "
                f"**PF:** {row['pointsFor']:.2f} • "
                f"**GB:** {_fmt_gb(row['gamesBack'])}"
            ),
            "inline": False,
        })
    left = f"{weeks_left} week{'s' if weeks_left != 1 else ''} left in the regular season"
    note = (
        f"*After Week {after_week} — {left}. The top {playoff_cut} teams currently "
        f"occupy playoff positions; the next {bubble_depth} are on the bubble.*"
    )
    return _payload(ctx, "BLHA Playoff Race", f"{_header(ctx)}\n\n{note}", fields, "PLAYOFF RACE")


# --- Matchup preview ----------------------------------------------------------

def preview(
    ctx: Context,
    p: Period,
    pairs: list[dict],
    records: dict[str, dict],
    *,
    ranks_shown: bool,
) -> dict[str, Any]:
    def line(team: dict) -> str:
        meta = records.get(team.get("teamId", ""), {})
        record = meta.get("record") or "0-0-0"
        if ranks_shown and meta.get("rank"):
            return f"**{team.get('teamName', 'TBD')}** — #{meta['rank']} • {record}"
        return f"**{team.get('teamName', 'TBD')}** — {record}"

    fields = [
        {"name": f"Matchup {i}", "value": f"{line(m['away'])}\nvs\n{line(m['home'])}", "inline": False}
        for i, m in enumerate(pairs, start=1)
    ]
    standing_note = "current Fantrax standing and record" if ranks_shown else "record including last week"
    note = (
        f"*This week's matchups with each team's {standing_note}. "
        "The scoreboard will track scoring once the week is underway.*"
    )
    return _payload(ctx, f"BLHA Week {p.number} Matchup Preview", f"{_header(ctx, p)}\n\n{note}", fields, "SCOREBOARD")
