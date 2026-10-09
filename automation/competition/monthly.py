"""Monthly Awards, from Fantrax matchup scores only.

A fantasy week belongs to the calendar month of its last night (league time).
A Week runs Monday through Sunday (Constitution 5.8), but Fantrax ends it on
the Monday evening when the next week's first game starts, so the last night
is the day before Fantrax's end date: a week ending Monday, November 1 is an
October week. A month's awards go out the morning the first week of the next
month is reported; the season's last regular-season month goes out with the
final regular-season week.

Awards (every regular-season week of the month that was actually played):

- Manager of the Month: most points.
- Best Record of the Month: best head-to-head record (a tie counts half).
- Biggest Single Week: highest one-week score. Periods longer than one
  calendar week (a two-week period over an NHL break) do not count here.
- Hard Luck: most points scored in losses.

Ties go to more total points for the month; if that is equal too, the award
is shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from blha import season
from weekly import Record, latest_names, real_matchups, real_weeks, teams

EPSILON = 1e-9


@dataclass(frozen=True)
class MonthGroup:
    key: str          # "2026-10"
    label: str        # "October 2026"
    month: str        # "October"
    weeks: tuple[int, ...]
    report_week: int  # the week whose report carries this month's awards
    final: bool       # the season's last regular-season month

    @property
    def last_week(self) -> int:
        return self.weeks[-1]


def last_night(period: season.Period, tz: ZoneInfo) -> date:
    """The week's last NHL night (local date).

    A Fantrax week ends when the first game of its last day starts, so that
    day's games belong to the next week: the last night is the day before.
    """
    return period.end.astimezone(tz).date() - timedelta(days=1)


def month_groups(info: dict[str, Any], tz: ZoneInfo, last_regular: int) -> list[MonthGroup]:
    """Regular-season weeks grouped by the month of each week's last night."""
    raw: list[tuple[str, str, str, list[int]]] = []
    for p in season.periods(info):
        if p.number > last_regular:
            break
        night = last_night(p, tz)
        key = f"{night:%Y-%m}"
        if raw and raw[-1][0] == key:
            raw[-1][3].append(p.number)
        else:
            raw.append((key, f"{night:%B %Y}", f"{night:%B}", [p.number]))
    groups = []
    for index, (key, label, month, weeks) in enumerate(raw):
        final = index == len(raw) - 1
        report = weeks[-1] if final else raw[index + 1][3][0]
        groups.append(MonthGroup(key, label, month, tuple(weeks), report, final))
    return groups


def group_for(groups: list[MonthGroup], week: int) -> MonthGroup | None:
    return next((g for g in groups if week in g.weeks), None)


def due_groups(groups: list[MonthGroup], reported_week: int, posted_through: int) -> list[MonthGroup]:
    """Months whose awards are due once ``reported_week`` is reported.

    ``posted_through`` is the last week of the latest month already posted.
    """
    return [g for g in groups if g.report_week <= reported_week and g.last_week > posted_through]


def posted_baseline(groups: list[MonthGroup], recap_week: int) -> int:
    """For state saved before Monthly Awards existed: months whose report has
    already gone out count as posted, so a deploy never posts an old month."""
    done = [g.last_week for g in groups if g.report_week <= recap_week]
    return max(done) if done else 0


# --- Awards -------------------------------------------------------------------

@dataclass
class Winner:
    team_id: str
    team_name: str
    value: float          # the award's own figure
    total: float          # the team's points for the month (tiebreaker)
    record: Record = field(default_factory=Record)
    week: int = 0         # Biggest Single Week: which week
    losses: int = 0       # Hard Luck: how many losses


@dataclass
class MonthlyAwards:
    weeks: list[int]
    manager: list[Winner] = field(default_factory=list)
    record: list[Winner] = field(default_factory=list)
    big_week: list[Winner] = field(default_factory=list)
    hard_luck: list[Winner] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.manager


def best(candidates: list[Winner]) -> list[Winner]:
    """Highest value; ties go to more total points, then are shared."""
    if not candidates:
        return []
    top = max(c.value for c in candidates)
    tied = [c for c in candidates if abs(c.value - top) < EPSILON]
    most = max(c.total for c in tied)
    return sorted((c for c in tied if abs(c.total - most) < EPSILON), key=lambda c: c.team_name.lower())


def monthly_awards(weeks: dict[int, list[dict]], long_weeks: set[int] | frozenset[int] = frozenset()) -> MonthlyAwards:
    """Awards for the given weeks (one month). Empty when nothing was played."""
    played = real_weeks(weeks)
    result = MonthlyAwards(weeks=sorted(played))
    if not played:
        return result
    names = latest_names(played)
    totals: dict[str, float] = {}
    records: dict[str, Record] = {}
    top_week: dict[str, tuple[float, int]] = {}
    loss_points: dict[str, float] = {}
    loss_count: dict[str, int] = {}

    for number, rows in played.items():
        for t in teams(rows):
            totals[t["teamId"]] = totals.get(t["teamId"], 0.0) + t["score"]
        for row in real_matchups(rows):
            away, home = row["away"], row["home"]
            for me, them in ((away, home), (home, away)):
                tid = me["teamId"]
                rec = records.setdefault(tid, Record())
                if me["score"] > them["score"]:
                    rec.wins += 1
                elif me["score"] < them["score"]:
                    rec.losses += 1
                    loss_points[tid] = loss_points.get(tid, 0.0) + me["score"]
                    loss_count[tid] = loss_count.get(tid, 0) + 1
                else:
                    rec.ties += 1
                if number not in long_weeks and me["score"] > top_week.get(tid, (-1.0, 0))[0]:
                    top_week[tid] = (me["score"], number)

    def winner(tid: str, value: float, **extra: Any) -> Winner:
        return Winner(tid, names.get(tid, "Unknown Team"), value, totals.get(tid, 0.0), **extra)

    result.manager = best([winner(tid, pts) for tid, pts in totals.items()])
    result.record = best([winner(tid, rec.pct, record=rec) for tid, rec in records.items() if rec.games])
    result.big_week = best([winner(tid, pts, week=wk) for tid, (pts, wk) in top_week.items()])
    hard = [winner(tid, pts, losses=loss_count[tid]) for tid, pts in loss_points.items() if pts > 0]
    result.hard_luck = best(hard)
    return result


def multi_week_periods(info: dict[str, Any], numbers: list[int] | tuple[int, ...]) -> set[int]:
    """Weeks spanning more than one calendar week (season.calendar_weeks)."""
    out = set()
    for number in numbers:
        p = season.period(info, number)
        if p and season.calendar_weeks(p) > 1:
            out.add(number)
    return out
