"""BLHA Bucks: a play-money sportsbook on other franchises' matchups.

Just for fun. Bucks are not money, are never converted into anything and
can't be traded: nothing here touches FAAB, draft picks, lineups, standings or
any fantasy outcome (Article XI lists the only assets that change hands).
Owners may bet only on matchups their own franchise is not playing in, so no
bet ever gives anyone a reason to play a Week differently, and there is no
collusion angle (Article XVII).

Timeline, on the same Fantrax calendar as Pick'em (pickem.plan):
  post    Week N's lines when Week N-1 is final (Week 1: three days before)
  lock    when Week N's scoring period starts; no bets after that
  settle  when Week N is final

Lines: each team's average score over its last 3 final Weeks (the power
rankings' recent window, automation/competition/weekly.py). The spread is the
difference, rounded to the nearest half point. Before any Week is final every
line is a pick'em (0).

Bets: every player has 100 Bucks to bet each Week; unused Bucks don't carry
over. Bets are even money against the spread: a win adds the stake to the
season profit, a loss subtracts it, and a push (or a matchup Fantrax has no
result for) returns it. After the last regular-season Week the season profit
leader gets the Sharp role (ties share it).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from . import embeds as E
from . import pickem
from .shared import weekly

from blha import season  # noqa: E402  (automation/ is on sys.path via .shared)

WEEKLY_BUCKS = 100
AWAY, HOME = "away", "home"
SIDES = (AWAY, HOME)
WIN, LOSS, PUSH, VOID = "win", "loss", "push", "void"
FOOTER = "BLHA BUCKS • PLAY MONEY ONLY"
RULES = ("Play money only: Bucks never affect FAAB, picks, lineups or standings, and they can't be traded or "
         "cashed in. Even money against the spread; a push returns the stake. Nobody bets on their own matchup.")
HOW_LINES = ("Each team's average score over its last 3 final Weeks; the spread is the difference, rounded to the "
             "nearest half point. Before any Week is final, every line is a pick'em.")


def recent_window() -> int:
    """The power rankings' recent-form window (automation/competition/weekly.py)."""
    return int(weekly().RECENT_WEEKS)


# -------------------------------------------------------------------- lines
def round_half(value: float) -> float:
    """Nearest half point, halves away from zero: 2.25 -> 2.5, 2.2 -> 2.0, -2.25 -> -2.5."""
    steps = math.floor(abs(round(value, 6)) * 2 + 0.5) / 2
    return math.copysign(steps, value) if steps else 0.0


def spread_text(value: float) -> str:
    """+6.5, -3, or pick'em for 0."""
    return "pick'em" if not value else f"{value:+g}"


@dataclass(frozen=True)
class Line:
    """One matchup's line. ``home_spread`` is added to the home score (negative when home is favored)."""

    key: str
    away_id: str
    away: str
    home_id: str
    home: str
    home_spread: float
    away_avg: float | None = None
    home_avg: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Line":
        def avg(v: Any) -> float | None:
            return None if v is None else float(v)
        return cls(str(d["key"]), str(d["away_id"]), str(d["away"]), str(d["home_id"]), str(d["home"]),
                   float(d.get("home_spread") or 0.0), avg(d.get("away_avg")), avg(d.get("home_avg")))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def team(self, side: str) -> str:
        return self.home if side == HOME else self.away

    def team_id(self, side: str) -> str:
        return self.home_id if side == HOME else self.away_id

    def spread(self, side: str) -> float:
        value = self.home_spread if side == HOME else -self.home_spread
        return value + 0.0  # never -0.0

    def involves(self, team_id: str) -> bool:
        return bool(team_id) and team_id in (self.away_id, self.home_id)

    def label(self, side: str) -> str:
        """The side as bettors see it, e.g. "Test 4 -6.5" or "Test 4 (pick'em)"."""
        s = self.spread(side)
        return f"{self.team(side)} {spread_text(s)}" if s else f"{self.team(side)} (pick'em)"

    def text(self) -> str:
        if not self.home_spread:
            return f"{self.away} at {self.home} • pick'em"
        return f"{self.away} {spread_text(self.spread(AWAY))} at {self.home} {spread_text(self.spread(HOME))}"


def history_weeks(number: int, recent: int | None = None) -> list[int]:
    """The Weeks before Week ``number`` whose scores set its lines (the caller keeps the final ones)."""
    window = recent or recent_window()
    return list(range(max(1, number - window), number))


def recent_averages(weeks: dict[int, list[dict[str, Any]]], recent: int | None = None) -> dict[str, float]:
    """Each team's average score over the last ``recent`` played Weeks (0-0 placeholder Weeks skipped)."""
    w = weekly()
    played = list(w.real_weeks(weeks).items())[-(recent or recent_window()):]
    total: dict[str, float] = {}
    games: dict[str, int] = {}
    for _, rows in played:
        for team in w.teams(rows):
            tid = str(team.get("teamId") or "")
            if tid:
                total[tid] = total.get(tid, 0.0) + float(team.get("score") or 0.0)
                games[tid] = games.get(tid, 0) + 1
    return {tid: total[tid] / games[tid] for tid in total}


def make_lines(ms: list[pickem.Matchup], averages: dict[str, float]) -> list[Line]:
    """A line for every matchup; a team with no recent average makes it a pick'em."""
    out = []
    for m in ms:
        away, home = averages.get(m.away_id), averages.get(m.home_id)
        spread = round_half(away - home) if away is not None and home is not None else 0.0
        out.append(Line(m.key, m.away_id, m.away, m.home_id, m.home, spread,
                        None if away is None else round(away, 2), None if home is None else round(home, 2)))
    return out


def lines_for_week(info: dict[str, Any], number: int, now: datetime, tz: ZoneInfo,
                   scores_for: Callable[[int], list[dict[str, Any]]]) -> list[Line]:
    """Week ``number``'s lines from the final Weeks before it (``scores_for`` reads getMatchupScores)."""
    weeks = {}
    for n in history_weeks(number):
        p = season.period(info, n)
        if p is not None and season.is_final(p, now, tz):
            weeks[n] = scores_for(n)
    return make_lines(pickem.matchups(info, number), recent_averages(weeks))


def available(lines: list[Line], team_id: str) -> list[Line]:
    """Lines a member of ``team_id``'s franchise may bet on (never their own matchup)."""
    return [line for line in lines if not line.involves(team_id)]


def side_from(line: Line | None, text: str) -> str | None:
    """"away"/"home" from the menu, or a team name typed by hand."""
    raw = (text or "").strip().lower()
    if raw in SIDES:
        return raw
    if line is not None:
        for side in SIDES:
            if raw in (line.team(side).lower(), line.label(side).lower(), line.team_id(side).lower()):
                return side
    return None


# --------------------------------------------------------------------- bets
@dataclass(frozen=True)
class Bet:
    user_id: int
    matchup: str
    side: str
    amount: int
    franchise: str = ""


def check_bet(line: Line | None, side: str, amount: int, team_id: str, staked_elsewhere: int, *,
              locked: bool, budget: int = WEEKLY_BUCKS) -> str | None:
    """Why this bet can't be placed, or None. An amount of 0 removes the bet on that matchup."""
    if locked:
        return "Bets for this Week are locked."
    if line is None:
        return "That matchup isn't on this Week's board. Pick one from the list."
    if side not in SIDES:
        return "Pick one of the two teams in that matchup."
    if not team_id:
        return "Your franchise isn't linked to a Fantrax team yet, so the bot can't keep you off your own matchup."
    if line.involves(team_id):
        return "You can't bet on your own franchise's matchup."
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        return "Bet a whole number of Bucks."
    left = budget - staked_elsewhere
    if amount > left:
        return f"You have {max(left, 0)} Bucks left to bet this Week."
    return None


def staked(bets: dict[str, tuple[str, int]], *, except_matchup: str | None = None) -> int:
    """Bucks already on the board this Week, optionally leaving out one matchup (a bet being replaced)."""
    return sum(amount for key, (_, amount) in bets.items() if key != except_matchup)


# --------------------------------------------------------------- settlement
def results(lines: list[Line], scores: list[dict[str, Any]] | None) -> dict[str, tuple[float, float]]:
    """matchup key -> (away score, home score), for matchups Fantrax has scores for."""
    by_pair: dict[frozenset[str], dict[str, float]] = {}
    for row in scores or []:
        away, home = row.get("away") or {}, row.get("home") or {}
        a_id, h_id = str(away.get("teamId") or ""), str(home.get("teamId") or "")
        if a_id and h_id:
            by_pair[frozenset((a_id, h_id))] = {a_id: round(float(away.get("score") or 0), 2),
                                                h_id: round(float(home.get("score") or 0), 2)}
    out: dict[str, tuple[float, float]] = {}
    for line in lines:
        pts = by_pair.get(frozenset((line.away_id, line.home_id)))
        if pts is not None:
            out[line.key] = (pts[line.away_id], pts[line.home_id])
    return out


def ready_to_settle(lines: list[Line], found: dict[str, Any], now: datetime, final_time: datetime) -> bool:
    """Settle once Fantrax has every matchup, or a day after the Week is final regardless (like Pick'em)."""
    return len(found) >= len(lines) or now >= final_time + pickem.SCORE_GRACE


def grade(line: Line, side: str, result: tuple[float, float] | None) -> str:
    """win, loss or push against the spread; void when Fantrax has no result."""
    if result is None:
        return VOID
    away, home = result
    mine, theirs = (home, away) if side == HOME else (away, home)
    margin = round(mine + line.spread(side) - theirs, 2)
    return WIN if margin > 0 else LOSS if margin < 0 else PUSH


@dataclass(frozen=True)
class Settled:
    bet: Bet
    outcome: str

    @property
    def net(self) -> int:
        if self.outcome == WIN:
            return self.bet.amount
        if self.outcome == LOSS:
            return -self.bet.amount
        return 0  # push or void: the stake comes back


def settle(bets: Iterable[Bet], lines: list[Line], found: dict[str, Any]) -> list[Settled]:
    by_key = {line.key: line for line in lines}
    out = []
    for bet in bets:
        line = by_key.get(bet.matchup)
        raw = found.get(bet.matchup)
        result = (float(raw[0]), float(raw[1])) if raw is not None else None
        out.append(Settled(bet, grade(line, bet.side, result) if line is not None else VOID))
    return out


@dataclass(frozen=True)
class Standing:
    user_id: int
    profit: int
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    weeks: int = 0

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}-{self.pushes}"


def week_totals(settled: Iterable[Settled]) -> list[Standing]:
    """One Week per player: net Bucks and W-L-P, best first."""
    rows: dict[int, list[int]] = {}
    for s in settled:
        row = rows.setdefault(s.bet.user_id, [0, 0, 0, 0])
        row[0] += s.net
        row[1 if s.outcome == WIN else 2 if s.outcome == LOSS else 3] += 1
    out = [Standing(uid, net, w, l, p, 1) for uid, (net, w, l, p) in rows.items()]
    return sorted(out, key=lambda r: (-r.profit, -r.wins, r.user_id))


def leaderboard(weeks: Iterable[Iterable[Settled]]) -> list[Standing]:
    """Season profit: every settled Week's net added up. Ties: more wins, then user id (stable)."""
    total: dict[int, list[int]] = {}
    for week in weeks:
        for row in week_totals(week):
            t = total.setdefault(row.user_id, [0, 0, 0, 0, 0])
            for i, v in enumerate((row.profit, row.wins, row.losses, row.pushes, row.weeks)):
                t[i] += v
    out = [Standing(uid, *t) for uid, t in total.items()]
    return sorted(out, key=lambda r: (-r.profit, -r.wins, r.user_id))


def ranked(board: list[Standing]) -> list[tuple[str, Standing]]:
    """Rank labels; equal profit shares a rank (T2)."""
    out = []
    for row in board:
        rank = 1 + sum(1 for r in board if r.profit > row.profit)
        tied = sum(1 for r in board if r.profit == row.profit) > 1
        out.append((f"{'T' if tied else ''}{rank}", row))
    return out


def season_leaders(board: list[Standing]) -> list[int]:
    """Who gets the Sharp role: the top season profit among everyone who bet (ties share it)."""
    if not board:
        return []
    top = max(r.profit for r in board)
    return sorted(r.user_id for r in board if r.profit == top)


def role_changes(holders: Iterable[int], winners: Iterable[int]) -> tuple[list[int], list[int]]:
    """(give the role to, take it from): last season's holders lose it unless they won again."""
    have, won = set(holders), set(winners)
    return sorted(won - have), sorted(have - won)


def signed(n: int) -> str:
    return f"{n:+d}" if n else "0"


# ---------------------------------------------------------------- rendering
def lines_embed(number: int, lines: list[Line], locks_at: datetime, label: str) -> dict[str, Any]:
    return E.card(
        f"BLHA BUCKS — WEEK {number} LINES",
        f"{label}. Every owner has **{WEEKLY_BUCKS} Bucks** to bet this Week with `/book bet`; unused Bucks don't "
        f"carry over. Bets lock when the Week starts: **{E.stamp(locks_at)}** ({E.stamp(locks_at, 'R')}).",
        [("LINES", "\n".join(line.text() for line in lines) or "No matchups"),
         ("HOW LINES ARE SET", HOW_LINES),
         ("JUST FOR FUN", RULES)],
        FOOTER,
    )


def _result_line(line: Line, found: dict[str, Any]) -> str:
    raw = found.get(line.key)
    if raw is None:
        return f"{line.away} at {line.home}: no result from Fantrax (bets returned)"
    away, home = float(raw[0]), float(raw[1])
    score = f"{line.away} {away:.2f}, {line.home} {home:.2f}"
    outcome = grade(line, HOME, (away, home))
    if outcome == PUSH:
        return f"{score}: push at {line.label(HOME)} (bets returned)"
    side = HOME if outcome == WIN else AWAY
    return f"**{line.label(side)}** covered ({score})"


def _board_lines(board: list[Standing], limit: int) -> str:
    return "\n".join(f"{rank}. <@{r.user_id}> {signed(r.profit)} ({r.record}, {r.weeks} wk)"
                     for rank, r in ranked(board)[:limit])


def settlement_embed(number: int, lines: list[Line], found: dict[str, Any], settled: list[Settled],
                     board: list[Standing], label: str) -> dict[str, Any]:
    week = "\n".join(f"<@{r.user_id}> {signed(r.profit)} ({r.record})" for r in week_totals(settled)[:25])
    return E.card(
        f"BLHA BUCKS — WEEK {number} SETTLED",
        f"{label}. Wins pay even money, losses cost the stake, pushes are returned. {WEEKLY_BUCKS} fresh Bucks "
        "for everyone next Week.",
        [("AGAINST THE SPREAD", "\n".join(_result_line(line, found) for line in lines) or "No matchups"),
         (f"WEEK {number}", week or "Nobody bet this Week."),
         ("SEASON PROFIT", _board_lines(board, 10) or "No bets settled yet.")],
        FOOTER,
    )


def leaderboard_embed(board: list[Standing], label: str, weeks_settled: int) -> dict[str, Any]:
    if not board:
        return E.card("BLHA BUCKS LEADERBOARD", f"{label}. No BLHA Bucks Week has been settled yet.", [], FOOTER)
    plural = "Week" if weeks_settled == 1 else "Weeks"
    return E.card("BLHA BUCKS LEADERBOARD",
                  f"{label} • {weeks_settled} {plural} settled. Season profit is every Week's net result added up; "
                  f"the leader after the regular season earns the Sharp role.\n\n{_board_lines(board, 25)}",
                  [], FOOTER)


def sharp_embed(role_name: str, leaders: list[int], board: list[Standing], label: str) -> dict[str, Any]:
    who = ", ".join(f"<@{uid}>" for uid in leaders) or "Nobody placed a bet this Season."
    top = board[0].profit if board else 0
    return E.card(
        "BLHA BUCKS — SEASON CHAMPION",
        f"{label} regular season is in the books. {who} "
        f"{'finish' if len(leaders) > 1 else 'finishes'} on top with **{signed(top)} Bucks** and "
        f"{'share' if len(leaders) > 1 else 'earns'} the **{role_name}** role until next Season's leader takes it.",
        [("FINAL STANDINGS", _board_lines(board, 10) or "No bets settled.")],
        FOOTER,
    )


OUTCOME_TEXT = {WIN: "won", LOSS: "lost", PUSH: "push, returned", VOID: "no result, returned"}


def mybets_text(number: int, lines: list[Line], mine: dict[str, tuple[str, int]], locks_at: datetime, *,
                locked: bool, found: dict[str, Any] | None = None, budget: int = WEEKLY_BUCKS) -> str:
    """A member's bets for one Week; with ``found`` (a settled Week) each bet shows how it went."""
    by_key = {line.key: line for line in lines}
    if found is not None:
        state = "settled"
    else:
        state = f"locked {E.stamp(locks_at, 'R')}" if locked else f"locks {E.stamp(locks_at, 'R')}"
    head = f"**Week {number} • BLHA Bucks** • {staked(mine)} bet, {budget - staked(mine)} unused • {state}"
    rows = []
    for key, (side, amount) in mine.items():
        line = by_key.get(key)
        if line is None:
            continue
        other = line.team(AWAY if side == HOME else HOME)
        text = f"{amount} on **{line.label(side)}** vs {other}"
        if found is not None:
            done = settle([Bet(0, key, side, amount)], lines, found)[0]
            text += f" • {OUTCOME_TEXT[done.outcome]} {signed(done.net)}" if done.net else f" • {OUTCOME_TEXT[done.outcome]}"
        rows.append(text)
    return head + ("\n" + "\n".join(rows) if rows else "\nNo bets this Week." if found is not None or locked
                   else "\nNo bets yet. Use `/book bet`.")
