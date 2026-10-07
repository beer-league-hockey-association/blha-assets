"""Pick'em: owners predict the winner of every matchup in each Fantrax Week.

Timeline for regular-season Week N (Fantrax's calendar, blha.season):
  post   when Week N-1 is final (season.final_at), listing Week N's matchups
         (Week 1: three days before it starts)
  lock   when Week N's scoring period starts; no picks after that
  score  when Week N is final (season.is_final): 1 point per correct pick,
         and an exact tie scores nobody

Playoff Weeks are skipped: Fantrax's schedule only has seeds for them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import embeds as E
from . import shared  # noqa: F401  (puts automation/ on sys.path)

from blha import season  # noqa: E402
from blha.fantrax import schedule_for  # noqa: E402

FIRST_WEEK_LEAD = timedelta(days=3)
LATEST_POST = timedelta(hours=1)   # post at least this long before a Week starts
SCORE_GRACE = timedelta(hours=24)  # after this, score even if Fantrax is missing a matchup
PER_PAGE = 4                       # four selects per page; the fifth row holds the buttons
FOOTER = "BLHA PICK'EM"
RULES = "1 point per correct pick. An exact tie scores nobody."


@dataclass(frozen=True)
class Matchup:
    key: str
    away_id: str
    away: str
    home_id: str
    home: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Matchup":
        return cls(str(d["key"]), str(d["away_id"]), str(d["away"]), str(d["home_id"]), str(d["home"]))

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def name(self, team_id: str | None) -> str:
        return {self.away_id: self.away, self.home_id: self.home}.get(team_id or "", "?")


def season_key(league_id: str, info: dict[str, Any]) -> str:
    """Pick'em seasons are kept apart per Fantrax league and Season."""
    return f"{league_id}:{info.get('seasonYear') or 'unknown'}"


def season_label(key: str) -> str:
    year = key.rsplit(":", 1)[-1]
    return f"Season {year}" if year.isdigit() else "This Season"


def regular_weeks(info: dict[str, Any]) -> list[season.Period]:
    last_regular, _, _ = season.playoff_settings(info)
    return [p for p in season.periods(info) if p.number <= last_regular]


def matchups(info: dict[str, Any], number: int) -> list[Matchup]:
    out = []
    for pair in schedule_for(info, number):
        away, home = pair["away"], pair["home"]
        if away["teamId"] and home["teamId"]:
            out.append(Matchup(f"{away['teamId']}@{home['teamId']}", away["teamId"], away["teamName"],
                               home["teamId"], home["teamName"]))
    return out


def post_at(info: dict[str, Any], number: int, tz: ZoneInfo) -> datetime | None:
    """When Week N's Pick'em is posted: once Week N-1 is final."""
    week = season.period(info, number)
    if week is None:
        return None
    before = season.period(info, number - 1)
    if before is None:
        return week.start - FIRST_WEEK_LEAD
    return min(season.final_at(before, tz), week.start - LATEST_POST)


def plan(info: dict[str, Any], now: datetime, tz: ZoneInfo, stored: dict[int, str]) -> list[tuple[str, int]]:
    """Actions due now: ("score" | "lock" | "post", week). ``stored`` maps week -> status."""
    weeks = regular_weeks(info)
    actions: list[tuple[str, int]] = []
    for p in weeks:
        status = stored.get(p.number)
        if status in ("open", "locked") and season.is_final(p, now, tz):
            actions.append(("score", p.number))
        elif status == "open" and now >= p.start:
            actions.append(("lock", p.number))
    for p in weeks:
        if p.number in stored:
            continue
        opens = post_at(info, p.number, tz)
        if opens is not None and opens <= now < p.start and matchups(info, p.number):
            actions.append(("post", p.number))
    return actions


def is_locked(locks_at: datetime, now: datetime) -> bool:
    return now >= locks_at


# ------------------------------------------------------------------ scoring
def winners(ms: list[Matchup], scores: list[dict[str, Any]] | None) -> dict[str, str | None]:
    """matchup key -> winning team id (None for an exact tie), for matchups Fantrax has scores for."""
    by_pair: dict[frozenset[str], dict[str, float]] = {}
    for row in scores or []:
        away, home = row.get("away") or {}, row.get("home") or {}
        a_id, h_id = str(away.get("teamId") or ""), str(home.get("teamId") or "")
        if a_id and h_id:
            by_pair[frozenset((a_id, h_id))] = {a_id: float(away.get("score") or 0), h_id: float(home.get("score") or 0)}
    out: dict[str, str | None] = {}
    for m in ms:
        pts = by_pair.get(frozenset((m.away_id, m.home_id)))
        if pts is None:
            continue
        away, home = round(pts[m.away_id], 2), round(pts[m.home_id], 2)
        out[m.key] = m.away_id if away > home else m.home_id if home > away else None
    return out


def ready_to_score(ms: list[Matchup], found: dict[str, str | None], now: datetime, final_time: datetime) -> bool:
    """Score once Fantrax has every matchup, or a day after the Week is final regardless."""
    return len(found) >= len(ms) or now >= final_time + SCORE_GRACE


def weekly(picks: Iterable[tuple[int, str, str]], won: dict[str, str | None]) -> dict[int, int]:
    """user id -> correct picks this Week, for everyone who picked. Ties and missing results score nobody."""
    out: dict[int, int] = {}
    for user_id, key, team_id in picks:
        out.setdefault(int(user_id), 0)
        if won.get(key) is not None and won.get(key) == team_id:
            out[int(user_id)] += 1
    return out


def leaderboard(weeks: Iterable[dict[int, int]]) -> list[tuple[int, int, int]]:
    """[(user id, season points, weeks played)] best first."""
    total: dict[int, list[int]] = {}
    for week in weeks:
        for user_id, points in week.items():
            row = total.setdefault(user_id, [0, 0])
            row[0] += points
            row[1] += 1
    return sorted(((u, p, w) for u, (p, w) in total.items()), key=lambda r: (-r[1], r[2], r[0]))


def ranked(board: list[tuple[int, int, int]]) -> list[tuple[str, int, int, int]]:
    """Add rank labels; tied totals share a rank (T2)."""
    out = []
    for user_id, points, weeks in board:
        rank = 1 + sum(1 for _, p, _ in board if p > points)
        tied = sum(1 for _, p, _ in board if p == points) > 1
        out.append((f"{'T' if tied else ''}{rank}", user_id, points, weeks))
    return out


def pages(ms: list[Matchup], per_page: int = PER_PAGE) -> list[list[Matchup]]:
    return [ms[i:i + per_page] for i in range(0, len(ms), per_page)] or [[]]


# ---------------------------------------------------------------- rendering
def post_embed(number: int, ms: list[Matchup], locks_at: datetime) -> dict[str, Any]:
    lines = "\n".join(f"{m.away} at {m.home}" for m in ms)
    return E.card(
        f"PICK'EM — WEEK {number}",
        f"Pick the winner of every Week {number} matchup with **Make my picks**. Picks lock when the Week starts: "
        f"**{E.stamp(locks_at)}** ({E.stamp(locks_at, 'R')}).\n{RULES}",
        [("MATCHUPS", lines or "No matchups")],
        FOOTER,
    )


def picks_content(number: int, ms: list[Matchup], mine: dict[str, str], locks_at: datetime,
                  page: int, page_count: int) -> str:
    made = sum(1 for m in ms if m.key in mine)
    text = f"**Week {number} Pick'em** • {made} of {len(ms)} picked • locks {E.stamp(locks_at, 'R')}"
    if page_count > 1:
        text += f" • page {page + 1} of {page_count}"
    if made == len(ms):
        text += "\nAll set. You can change a pick until the lock."
    return text


def _board_lines(board: list[tuple[int, int, int]], limit: int) -> str:
    rows = ranked(board)[:limit]
    return "\n".join(f"{rank}. <@{uid}> — {pts} pt{'s' if pts != 1 else ''} ({weeks} wk)" for rank, uid, pts, weeks in rows)


def results_embed(number: int, ms: list[Matchup], won: dict[str, str | None], week: dict[int, int],
                  board: list[tuple[int, int, int]], label: str) -> dict[str, Any]:
    results = []
    for m in ms:
        if m.key not in won:
            results.append(f"{m.away} at {m.home}: no result from Fantrax (no points)")
        elif won[m.key] is None:
            results.append(f"{m.away} and {m.home} tied exactly (no points)")
        else:
            loser = m.home_id if won[m.key] == m.away_id else m.away_id
            results.append(f"**{m.name(won[m.key])}** beat {m.name(loser)}")
    scored = sorted(week.items(), key=lambda kv: (-kv[1], kv[0]))
    week_lines = "\n".join(f"<@{uid}> {pts}/{len(ms)}" for uid, pts in scored[:25])
    return E.card(
        f"PICK'EM — WEEK {number} RESULTS",
        f"{label}. {RULES}",
        [("WINNERS", "\n".join(results) or "None"),
         (f"WEEK {number}", week_lines or "Nobody picked this Week."),
         ("SEASON LEADERBOARD", _board_lines(board, 10) or "No points yet.")],
        FOOTER,
    )


def leaderboard_embed(board: list[tuple[int, int, int]], label: str, weeks_scored: int) -> dict[str, Any]:
    if not board:
        return E.card("PICK'EM LEADERBOARD", f"{label}. No Pick'em Week has been scored yet.", [], FOOTER)
    plural = "Week" if weeks_scored == 1 else "Weeks"
    return E.card("PICK'EM LEADERBOARD",
                  f"{label} • {weeks_scored} {plural} scored. {RULES}\n\n{_board_lines(board, 25)}", [], FOOTER)
