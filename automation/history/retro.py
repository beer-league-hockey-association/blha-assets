"""Draft retrospectives: how a past draft has turned out, from saved draft results and NHL stats.

Output is measured from NHL regular-season stats since the draft (the Season
that draft supplies onward), scored with BLHA scoring (Article VIII) as far as
the NHL feed allows: skaters goals x5, assists x2.95, shots x0.55; goalies
starts x6.5, saves x0.49, goals against x-5. Hits and blocks are not in the
NHL's public player feed, so they are left out for everyone. Players are
matched to NHL players by name, NHL team and position the same way as the
minor-eligibility watch (automation/commissioner/minors.py).

  Biggest steal       a pick after round 1 whose output ranks furthest ahead of where he was taken
  Biggest miss        the round-1 pick with the least output (players never matched are left out)
  Best undrafted      a player added from the unowned pool after the draft who is still rostered,
  pickup              with the most output since the Season he was added
  Best development    the drafted player whose output rose most from the Season before the draft
                      to the latest Season
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION / "commissioner"))

import minors  # noqa: E402  (NHL lookups shared with the minor-eligibility watch)

from blha.league import AVATAR, color_value  # noqa: E402
from history.context import LeagueHistory, ordinal  # noqa: E402

FOOTER_DIVIDER = (
    "https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/main/"
    "discord/webhooks/shared/blha-footer-divider-1600x90.png?v=8bit-1"
)
SKATER = {"goals": 5.0, "assists": 2.95, "shots": 0.55}
GOALIE = {"starts": 6.5, "saves": 0.49, "goals_against": -5.0, "goals": 5.0, "assists": 2.95}
MEASURE = ("NHL regular-season stats since the draft, scored the BLHA way where the NHL feed allows "
           "(goals, assists and shots; goalies: starts, saves and goals against). Hits and blocks are not in the NHL feed.")


def season_id(year: int) -> int:
    """Season 2026 (2026-27) -> 20262027, as the NHL API writes it."""
    return year * 10000 + year + 1


def season_label(sid: int) -> str:
    return f"{sid // 10000}-{str(sid % 10000)[2:]}"


def row_value(row: dict[str, Any], goalie: bool) -> float:
    def n(key: str) -> float:
        try:
            return float(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    if not goalie:
        return SKATER["goals"] * n("goals") + SKATER["assists"] * n("assists") + SKATER["shots"] * n("shots")
    starts = n("gamesStarted") or n("gamesPlayed")
    ga = n("goalsAgainst")
    shots = n("shotsAgainst")
    if not shots and n("savePctg") and n("savePctg") < 1:
        saves = ga * n("savePctg") / (1 - n("savePctg"))
    else:
        saves = max(shots - ga, 0.0)
    return (GOALIE["starts"] * starts + GOALIE["saves"] * saves + GOALIE["goals_against"] * ga
            + GOALIE["goals"] * n("goals") + GOALIE["assists"] * n("assists"))


def season_stats(landing: dict[str, Any], goalie: bool) -> dict[int, dict[str, float]]:
    """NHL regular-season totals per season id (rows for one season with two teams are added up)."""
    out: dict[int, dict[str, float]] = {}
    for row in landing.get("seasonTotals") or []:
        if not isinstance(row, dict) or row.get("leagueAbbrev") != "NHL" or int(row.get("gameTypeId") or 0) != 2:
            continue
        sid = int(row.get("season") or 0)
        cur = out.setdefault(sid, {"gp": 0.0, "points": 0.0, "value": 0.0})
        cur["gp"] += float(row.get("gamesPlayed") or 0)
        cur["points"] += float(row.get("points") or (row.get("goals") or 0) + (row.get("assists") or 0))
        cur["value"] += row_value(row, goalie)
    return out


def fetch_stats(hist: LeagueHistory, player_ids: list[str], session: requests.Session | None = None,
                index: Any = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Fantrax player id -> {goalie, seasons}; plus the names that could not be matched to an NHL player."""
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "BLHA-History/1.0")
    index = index or minors.build_index(session)
    stats: dict[str, dict[str, Any]] = {}
    unmatched: list[str] = []
    for pid in dict.fromkeys(player_ids):
        info = hist.players.get(pid) or {}
        name = str(info.get("name") or "")
        if not name:
            unmatched.append(pid)
            continue
        first, last = minors.fantrax_name(name)
        found = index.find(first, last, str(info.get("team") or "")) or minors.search_player(session, first, last)
        if not found:
            unmatched.append(name)
            continue
        landing = minors._get(session, f"{minors.NHL}/player/{found['id']}/landing") or {}
        goalie = str(info.get("position") or landing.get("position") or "") == "G"
        stats[pid] = {"nhl_id": found["id"], "goalie": goalie, "seasons": season_stats(landing, goalie)}
    return stats, unmatched


def _since(seasons: dict[Any, dict[str, float]], first: int) -> dict[str, float]:
    total = {"gp": 0.0, "points": 0.0, "value": 0.0}
    for sid, row in seasons.items():
        if int(sid) >= first:
            for k in total:
                total[k] += float(row.get(k) or 0)
    return total


def _event_season(event: dict[str, Any]) -> int:
    """The NHL season an archive event falls in (seasons turn over in September)."""
    day = str(event.get("date") or event.get("at") or "")[:10]
    try:
        y, m = int(day[:4]), int(day[5:7])
    except ValueError:
        return 0
    return season_id(y if m >= 9 else y - 1)


def candidates_for_pickup(hist: LeagueHistory, draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Adds from the pool after the draft, not taken in it, still on a roster."""
    drafted = {str(p.get("player")) for p in draft.get("picks") or []}
    after = str(draft.get("end") or draft.get("date") or "")
    out: dict[str, dict[str, Any]] = {}
    for e in hist.events():
        if e.get("type") != "add" or str(e.get("at") or "") < after:
            continue
        pid = str(e.get("player"))
        if pid in drafted or pid in out or not hist.current_owner(pid):
            continue
        out[pid] = e
    return list(out.values())


def build_report(hist: LeagueHistory, draft: dict[str, Any], stats: dict[str, dict[str, Any]],
                 unmatched: list[str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    year = int(draft.get("year") or 0)
    first = season_id(year)
    before = season_id(year - 1)
    picks = []
    for p in draft.get("picks") or []:
        pid = str(p.get("player") or "")
        if not pid or pid not in stats:
            continue
        seasons = {int(k): v for k, v in (stats[pid].get("seasons") or {}).items()}
        since = _since(seasons, first)
        later = [sid for sid in seasons if sid >= first]
        latest = max(later) if later else None
        picks.append({
            "player": pid, "name": hist.player(pid), "franchise": hist.name(hist.franchise(str(p.get("team") or ""))),
            "round": int(p["round"]), "in_round": int(p["in_round"]), "overall": int(p["overall"]),
            "value": round(since["value"], 1), "gp": int(since["gp"]), "points": int(since["points"]),
            "goalie": bool(stats[pid].get("goalie")),
            "before": round(float((seasons.get(before) or {}).get("value") or 0), 1),
            "latest": round(float((seasons.get(latest) or {}).get("value") or 0), 1) if latest else 0.0,
            "latest_season": latest,
        })
    ranked = sorted(picks, key=lambda r: (-r["value"], r["overall"]))
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank

    late = [r for r in picks if r["round"] >= 2 and r["value"] > 0]
    steal = max(late, key=lambda r: (r["overall"] - r["rank"], r["value"]), default=None)
    early = [r for r in picks if r["round"] == 1]
    miss = min(early, key=lambda r: (r["value"], r["overall"]), default=None)
    grown = [r for r in picks if r["latest_season"] and r["latest_season"] > before]
    development = max(grown, key=lambda r: (r["latest"] - r["before"], r["latest"]), default=None)
    if development and development["latest"] - development["before"] <= 0:
        development = None

    pickup = None
    for e in candidates_for_pickup(hist, draft):
        pid = str(e["player"])
        if pid not in stats:
            continue
        seasons = {int(k): v for k, v in (stats[pid].get("seasons") or {}).items()}
        since = _since(seasons, max(_event_season(e), first))
        row = {"player": pid, "name": hist.player(pid), "franchise": hist.name(hist.franchise(str(e.get("team") or ""))),
               "added": hist.event_date(e), "value": round(since["value"], 1), "gp": int(since["gp"]),
               "points": int(since["points"])}
        if row["value"] > 0 and (pickup is None or row["value"] > pickup["value"]):
            pickup = row

    return {
        "year": year,
        "season": draft.get("season"),
        "kind": "Startup Draft" if max((r["round"] for r in picks), default=0) > 5 or len(draft.get("picks") or []) > 100 else "Annual Draft",
        "as_of": now.isoformat(),
        "since_season": season_label(first),
        "picks_rated": len(picks),
        "picks_total": len(draft.get("picks") or []),
        "unmatched": sorted(unmatched or []),
        "steal": steal, "miss": miss, "pickup": pickup, "development": development,
        "top": ranked[:10],
        "measure": MEASURE,
    }


def slot(row: dict[str, Any]) -> str:
    return f"{row['round']}.{row['in_round']:02d} ({ordinal(row['overall'])} overall)"


def output_text(row: dict[str, Any]) -> str:
    unit = "NHL game" if row["gp"] == 1 else "NHL games"
    extra = "" if row.get("goalie") else f", {row['points']} points"
    return f"{row['value']:g} BLHA points in {row['gp']} {unit}{extra}"


def highlight_lines(report: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    s, m, p, d = report.get("steal"), report.get("miss"), report.get("pickup"), report.get("development")
    out.append(("BIGGEST STEAL", f"**{s['name']}**, {slot(s)} by {s['franchise']}: {output_text(s)} since the draft, "
                f"{'the most' if s['rank'] == 1 else 'the ' + ordinal(s['rank']) + ' most'} productive pick of the class."
                if s else "Not enough NHL games yet."))
    out.append(("BIGGEST MISS", f"**{m['name']}**, {slot(m)} by {m['franchise']}: {output_text(m)} since the draft." if m
                else "Not enough NHL games yet."))
    out.append(("BEST UNDRAFTED PICKUP", f"**{p['name']}**, added by {p['franchise']} on {p['added']} and still rostered: "
                f"{output_text(p)}." if p else "No undrafted pickup has produced yet."))
    out.append(("BEST DEVELOPMENT", f"**{d['name']}**, {slot(d)} by {d['franchise']}: {d['before']:g} BLHA points the season "
                f"before the draft, {d['latest']:g} in {season_label(d['latest_season'])}." if d
                else "No drafted player has a later NHL season to compare yet."))
    return out


def title(report: dict[str, Any]) -> str:
    return f"{report['year']} BLHA {report['kind']}: Retrospective"


def render_text(report: dict[str, Any]) -> str:
    lines = [title(report), f"Rated {report['picks_rated']} of {report['picks_total']} picks; stats since {report['since_season']}."]
    for label, text in highlight_lines(report):
        lines.append(f"{label.title()}: {text.replace('**', '')}")
    if report.get("unmatched"):
        lines.append(f"Not matched to an NHL player ({len(report['unmatched'])}): " + "; ".join(report["unmatched"][:20]))
    lines.append("How it is measured: " + report["measure"])
    return "\n".join(lines)


def payload(report: dict[str, Any], league: dict[str, Any], *, test: bool = False) -> dict[str, Any]:
    fields = [{"name": label, "value": text[:1024], "inline": False} for label, text in highlight_lines(report)]
    fields.append({"name": "HOW IT IS MEASURED", "value": report["measure"][:1024], "inline": False})
    rated = f"Rated {report['picks_rated']} of {report['picks_total']} picks"
    if report.get("unmatched"):
        rated += f" ({len(report['unmatched'])} could not be matched to an NHL player)"
    embed = {
        "title": ("[TEST] " if test else "") + title(report),
        "description": f"How the {report['year']} draft has turned out so far. {rated}.",
        "color": color_value(league.get("color")),
        "fields": fields,
        "footer": {"text": "BLHA DRAFT CENTER • FANTRAX AND NHL DATA"},
        "image": {"url": FOOTER_DIVIDER},
    }
    return {"username": "BLHA Draft Center", "avatar_url": AVATAR, "allowed_mentions": {"parse": []}, "embeds": [embed]}
