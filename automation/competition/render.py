"""Discord payloads for BLHA Competition Desk posts.

Layouts follow automation/DISCORD_AUTOMATION_STYLE.md and keep the approved
scoreboard / standings / recap / playoff race / preview formats: BLHA
Competition Desk sender, gold accent, vertical fields, no emoji, short footer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
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


FANTRAX_SOURCE = "FANTRAX READ-ONLY DATA"
NHL_SOURCE = "NHL SCHEDULE DATA"
FIELD_LIMIT = 1024


def _clip(text: str, limit: int = FIELD_LIMIT) -> str:
    """Keep a field value inside Discord's limit, cutting at a line break."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 2].rsplit("\n", 1)[0]
    return cut + "\n…"


def _payload(
    ctx: Context,
    title: str,
    description: str,
    fields: list[dict],
    footer: str,
    *,
    source: str = FANTRAX_SOURCE,
) -> dict[str, Any]:
    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": ("[TEST] " + title) if ctx.test else title,
            "description": description,
            "fields": fields[:25],
            "color": ctx.color,
            "footer": {"text": f"{footer} • {source}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }


# --- Scoreboard ---------------------------------------------------------------

def goalie_starts(team: dict, cap: int | None) -> int | None:
    """Goalie games started (Fantrax category GS), or None if not shown."""
    if not cap:
        return None
    categories = team.get("categories") or {}
    if "GS" not in categories:
        return None
    return int(categories["GS"])


def scoreboard_fields(rows: list[dict], goalie_cap: int | None = None) -> list[dict]:
    def starts(team: dict) -> str:
        used = goalie_starts(team, goalie_cap)
        return "" if used is None else f" • Goalie starts: {used} of {goalie_cap}"

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
                f"**{away['teamName']}** *(Away)* — {a_text} • `{_fmt_gp(away['gamesPlayed'])} GP`{starts(away)}\n"
                f"**{home['teamName']}** *(Home)* — {h_text} • `{_fmt_gp(home['gamesPlayed'])} GP`{starts(home)}"
            ),
            "inline": False,
        })
    return fields


def scoreboard(
    ctx: Context,
    p: Period,
    rows: list[dict],
    *,
    final: bool,
    playoffs: bool,
    goalie_cap: int | None = None,
) -> dict[str, Any]:
    label = "Playoffs " if playoffs else ""
    title = f"BLHA {label}Week {p.number} {'Final ' if final else ''}Scoreboard"
    if final:
        note = "*Final scores for the week, from Fantrax. The winning score is bolded.*"
    else:
        note = (
            "*Live scoreboard from Fantrax. This post updates through the week; "
            "the leading score is bolded.*"
        )
    if goalie_cap:
        note += f"\n*Goalie starts are credited up to {goalie_cap} this week (9.2, 9.3).*"
    return _payload(ctx, title, f"{_header(ctx, p)}\n\n{note}", scoreboard_fields(rows, goalie_cap), "SCOREBOARD")


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


def all_play_field(rows: list[dict], week: dict[str, Any], season: dict[str, Any]) -> dict | None:
    """One field: each team's all-play record this week and for the season.

    ``week`` and ``season`` map teamId -> weekly.Record.
    """
    if not week:
        return None
    names = {t["teamId"]: t["teamName"] for row in rows for t in (row["away"], row["home"])}
    order = sorted(
        week,
        key=lambda tid: (-week[tid].wins, -week[tid].ties, -(season[tid].wins if tid in season else 0),
                         names.get(tid, "").lower()),
    )
    lines = []
    for tid in order:
        line = f"**{names.get(tid, 'Unknown Team')}** — {week[tid].text()}"
        if tid in season:
            line += f" • Season {season[tid].text()}"
        lines.append(line)
    return {"name": "All-Play", "value": _clip("\n".join(lines)), "inline": False}


def recap(
    ctx: Context,
    p: Period,
    rows: list[dict],
    *,
    all_play_week: dict[str, Any] | None = None,
    all_play_season: dict[str, Any] | None = None,
) -> dict[str, Any]:
    note = "*Completed matchup results pulled directly from Fantrax.*"
    fields = recap_fields(rows)
    extra = all_play_field(rows, all_play_week or {}, all_play_season or {})
    if extra:
        others = len(all_play_week or {}) - 1
        note += f"\n*All-play: each team's record had it played all {others} other teams this week.*"
        fields.append(extra)
    return _payload(ctx, f"BLHA Week {p.number} Recap", f"{_header(ctx, p)}\n\n{note}", fields, "WEEKLY RECAP")


# --- Weekly awards ------------------------------------------------------------

def _team_score(team: dict) -> str:
    return f"**{team['teamName']}** — {_fmt_score(team['score'])} pts"


def _game(result: Any) -> str:
    w, l = result.winner, result.loser
    return (
        f"**{w['teamName']}** {_fmt_score(w['score'])} – {l['teamName']} {_fmt_score(l['score'])} • "
        f"{result.margin:.2f}-point margin"
    )


def awards(ctx: Context, p: Period, result: Any) -> dict[str, Any] | None:
    """Weekly Awards post from weekly.weekly_awards(); None if nothing to award."""
    if result.empty:
        return None
    fields = [
        {"name": label, "value": _team_score(team), "inline": False}
        for label, team in zip(("First Star", "Second Star", "Third Star"), result.stars)
    ]
    if result.tough_luck:
        r = result.tough_luck
        fields.append({
            "name": "Tough Luck",
            "value": f"{_team_score(r.loser)} in a loss to {r.winner['teamName']} ({_fmt_score(r.winner['score'])})",
            "inline": False,
        })
    if result.lucky_win:
        r = result.lucky_win
        fields.append({
            "name": "Lucky Win",
            "value": f"{_team_score(r.winner)} in a win over {r.loser['teamName']} ({_fmt_score(r.loser['score'])})",
            "inline": False,
        })
    if result.closest:
        fields.append({"name": "Closest Game", "value": _game(result.closest), "inline": False})
    if result.blowout:
        fields.append({"name": "Biggest Blowout", "value": _game(result.blowout), "inline": False})
    note = (
        "*From this week's final Fantrax scores. Stars are the top three scores; Tough Luck is the "
        "highest score in a loss and Lucky Win the lowest score in a win.*"
    )
    return _payload(ctx, f"BLHA Week {p.number} Awards", f"{_header(ctx, p)}\n\n{note}", fields, "WEEKLY AWARDS")


# --- Power rankings -----------------------------------------------------------

def _change(row: Any, has_previous: bool) -> str:
    if not has_previous:
        return "—"
    if row.change is None:
        return "New"
    if row.change > 0:
        return f"Up {row.change}"
    if row.change < 0:
        return f"Down {-row.change}"
    return "Same"


def power_rankings(ctx: Context, after_week: int, rows: list[Any], *, has_previous: bool) -> dict[str, Any] | None:
    """Power Rankings post from weekly.power_rankings(); None if no results yet."""
    if not rows:
        return None
    fields = [
        {
            "name": f"{row.rank}. {row.team_name}",
            "value": (
                f"**Change:** {_change(row, has_previous)} • "
                f"**Record:** {row.record.text()} • "
                f"**PF:** {row.points_for:.2f} • "
                f"**All-Play:** {row.all_play.text()} • "
                f"**Score:** {row.score:.3f}"
            ),
            "inline": False,
        }
        for row in rows
    ]
    note = (
        "*Results only. Score = 50% season points-for + 30% points-for over the last 3 weeks + "
        "20% season all-play win %. Both points-for figures are scaled 0 to 1 across the league "
        "(lowest team 0, highest 1). Change is against last week's rankings.*"
    )
    return _payload(ctx, f"BLHA Power Rankings — After Week {after_week}", f"{_header(ctx)}\n\n{note}",
                    fields, "POWER RANKINGS")


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


# --- Wooden Spoon -------------------------------------------------------------

def wooden_spoon(ctx: Context, row: dict, owner_id: str = "") -> dict[str, Any]:
    """The last-place franchise takes the Wooden Spoon (league tradition, no penalty)."""
    holder = f"<@{owner_id}>" if owner_id else "Its owner"
    fields = [
        {"name": "Final record", "value": f"{row['record']} • {row['pointsFor']:.2f} points for", "inline": False},
        {"name": "The tradition", "value": f"{holder} holds the Wooden Spoon role for the Offseason and writes the "
                                           "preview of next Season, posted before Week 1.", "inline": False},
        {"name": "No penalty", "value": "Draft order is unaffected: it comes from Potential Points (14.5).", "inline": False},
    ]
    note = f"**{row['teamName']}** finishes last in the regular season and takes home the Wooden Spoon."
    payload = _payload(ctx, "The Wooden Spoon", f"{_header(ctx)}\n\n{note}", fields, "WOODEN SPOON")
    if owner_id:
        payload["content"] = f"<@{owner_id}>"
        payload["allowed_mentions"] = {"parse": [], "users": [] if ctx.test else [owner_id]}
    return payload


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


# --- NHL games grid -----------------------------------------------------------

def _day(d: date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def _span(a: date, b: date) -> str:
    if a.month == b.month:
        return f"{a:%b} {a.day}–{b.day}"
    return f"{a:%b} {a.day}–{b:%b} {b.day}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _nights(nights: list[tuple[date, int]]) -> str:
    if not nights:
        return "None this week."
    return "\n".join(f"{_day(night)} — {_count(teams // 2, 'game')}, {teams} teams" for night, teams in nights)


def games_grid(ctx: Context, p: Period, grid: Any) -> dict[str, Any]:
    """NHL games grid for one Fantrax week (blha.nhl.WeekGrid)."""
    fields = []
    for count, teams in grid.by_count():
        label = "No Games" if count == 0 else _count(count, "Game")
        fields.append({"name": label, "value": _clip(", ".join(teams)), "inline": False})
    b2b = [f"**{team}:** " + ", ".join(_span(a, b) for a, b in pairs) for team, pairs in grid.back_to_backs.items()]
    fields.append({"name": "Back-to-Backs", "value": _clip("\n".join(b2b) or "None this week."), "inline": False})
    fields.append({"name": f"Light Nights ({grid.light_max} or fewer teams)", "value": _clip(_nights(grid.light_nights)),
                   "inline": False})
    fields.append({"name": f"Heavy Nights ({grid.heavy_min} or more teams)", "value": _clip(_nights(grid.heavy_nights)),
                   "inline": False})
    note = (
        f"*NHL regular-season games in this Fantrax week ({_count(grid.total_games, 'game')}), to help plan daily "
        "lineups. Lineups lock about one minute before each player's game (5.3).*"
    )
    return _payload(ctx, f"BLHA Week {p.number} NHL Games Grid", f"{_header(ctx, p)}\n\n{note}", fields,
                    "NHL GAMES GRID", source=NHL_SOURCE)
