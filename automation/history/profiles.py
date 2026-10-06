"""Dynasty Pot summary and franchise profiles: the data behind the graphics, the posts and the site."""

from __future__ import annotations

from typing import Any

from history.context import LeagueHistory, natural
from history.records import AWARDS
from history.rivals import HeadToHead, declared_rivals

DEFAULT_COLORS = ["#FFB81C", "#F4EFE4"]


def dynasty_summary(hist: LeagueHistory) -> dict[str, Any]:
    d = hist.records.dynasty()
    rows = []
    for key in hist.franchise_keys():
        colors = (hist.records.franchises.get(key) or {}).get("colors") or DEFAULT_COLORS
        rows.append({"key": key, "name": hist.name(key), "titles": int(d.active.titles.get(key, 0)), "color": colors[0]})
    for key, count in d.active.titles.items():
        if key not in {r["key"] for r in rows}:
            rows.append({"key": key, "name": hist.name(key), "titles": count, "color": DEFAULT_COLORS[0]})
    rows.sort(key=lambda r: (-r["titles"], natural(r["name"])))
    return {
        "balance": d.active.balance,
        "cycle_started": d.active.started,
        "titles_to_win": d.titles_to_win,
        "rows": rows,
        "last_added": d.last_added,
        "past": [{"winner": hist.name(c.winner or ""), "started": c.started, "ended": c.ended, "payout": c.payout}
                 for c in d.past],
    }


def first_season(hist: LeagueHistory, key: str) -> int | None:
    for season in hist.seasons:
        teams = hist.archive.meta(season).get("teams") or {}
        if any(hist.franchise(t) == key for t in teams):
            return season
    return None


def rival_of(hist: LeagueHistory, h2h: HeadToHead, key: str) -> tuple[str | None, str]:
    """(rival key, 'declared' or 'most played'); declared rivals in league.yaml win."""
    for a, b in declared_rivals(hist):
        if key in (a, b):
            return (b if key == a else a), "declared"
    earned = h2h.earned_rival(key)
    return (earned, "most played") if earned else (None, "")


def franchise_profiles(hist: LeagueHistory, h2h: HeadToHead | None = None) -> list[dict[str, Any]]:
    h2h = h2h or HeadToHead(hist)
    dynasty = hist.records.dynasty()
    out = []
    for key in hist.franchise_keys():
        row = hist.records.franchises.get(key) or {}
        rival, kind = rival_of(hist, h2h, key)
        awards = hist.records.awards_of(key)
        out.append({
            "key": key,
            "name": hist.name(key),
            "owner": str(row.get("owner") or ""),
            "founded": row.get("founded") or first_season(hist, key),
            "colors": list(row.get("colors") or DEFAULT_COLORS),
            "logo": row.get("logo"),
            "titles": awards.get("champion", []),
            "awards": {AWARDS[a]: years for a, years in awards.items()},
            "dynasty_count": int(dynasty.active.titles.get(key, 0)),
            "titles_to_win": dynasty.titles_to_win,
            "rival": hist.name(rival) if rival else None,
            "rival_kind": kind,
            "rival_record": h2h.record(key, rival).text if rival else "",
            "lifetime": h2h.lifetime(key).text,
            "games": h2h.lifetime(key).games,
        })
    out.sort(key=lambda p: natural(p["name"]))
    return out
