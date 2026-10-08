#!/usr/bin/env python3
"""Offline tests for BLHA Bucks (/book) and the annual Awards Ballot (/awards).

The pure logic runs everywhere. The Discord flows at the bottom (lines posted,
bets placed and refused, Weeks settled, the Sharp role, ballots cast, closed
and published) run where discord.py is installed, which includes the
regression-tests workflow. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from blha_vote import awards, book, embeds, pickem, rules  # noqa: E402
from blha_vote.config import load  # noqa: E402
from blha_vote.shared import FIXTURES  # noqa: E402
from blha_vote.store import Store  # noqa: E402

from blha import season  # noqa: E402
from blha.fantrax import normalize_standings  # noqa: E402

UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def fixture(name: str):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data["response"] if isinstance(data, dict) and "response" in data else data


INFO = fixture("league_info_2026_test.json")
STANDINGS = normalize_standings(fixture("standings_week0.json"))
WEEK1 = pickem.matchups(INFO, 1)
# Test-league team IDs (the shipped config's franchises, in draft order).
T3, TEST, T2, T4, T5, T6, T7, T8 = ("2tml63mumumuxoqh", "gb4or3npmumb3mgv", "mvh0gxh2mumuxoo4", "8j6llh6gmumuxose",
                                    "tau9p1cvmumuxout", "gobvt8opmumuxoxm", "qqpqauuamumuxp03", "vs89xezfmumuxp44")


def rows(ms: list[pickem.Matchup], points: dict[str, float]) -> list[dict]:
    """getMatchupScores-style rows (normalize_scores shape) for these matchups."""
    return [{"away": {"teamId": m.away_id, "teamName": m.away, "score": points.get(m.away_id, 0.0)},
             "home": {"teamId": m.home_id, "teamName": m.home, "score": points.get(m.home_id, 0.0)}} for m in ms]


def pair(a: str, b: str, sa: float, sb: float) -> list[dict]:
    return [{"away": {"teamId": a, "teamName": a.upper(), "score": sa}, "home": {"teamId": b, "teamName": b.upper(), "score": sb}}]


def line(spread: float = -6.5, away: str = "a", home: str = "h") -> book.Line:
    return book.Line(f"{away}@{home}", away, away.upper(), home, home.upper(), spread)


# ============================================================== BLHA Bucks
class LineMathTests(unittest.TestCase):
    def test_round_to_the_nearest_half_point(self) -> None:
        cases = {2.25: 2.5, 2.2: 2.0, 2.74: 2.5, 2.75: 3.0, 12.26: 12.5, -2.25: -2.5, -2.2: -2.0, 0.2: 0.0, -0.2: 0.0,
                 7.0: 7.0, 20.200000000000003 - 0.0000000001: 20.0}
        for value, expected in cases.items():
            self.assertEqual(book.round_half(value), expected, value)
        self.assertEqual(str(book.round_half(-0.2)), "0.0")  # never "-0.0"

    def test_window_is_the_power_rankings_recent_window(self) -> None:
        from blha_vote.shared import weekly
        self.assertEqual(book.recent_window(), weekly().RECENT_WEEKS)
        self.assertEqual(book.history_weeks(1), [])
        self.assertEqual(book.history_weeks(2), [1])
        self.assertEqual(book.history_weeks(6), [3, 4, 5])

    def test_recent_averages_skip_placeholder_weeks(self) -> None:
        weeks = {1: pair("a", "h", 50, 50), 2: pair("a", "h", 100, 90), 3: pair("a", "h", 0, 0),
                 4: pair("a", "h", 110, 80), 5: pair("a", "h", 120, 100)}
        avg = book.recent_averages(weeks)
        self.assertAlmostEqual(avg["a"], (100 + 110 + 120) / 3)  # Weeks 2, 4, 5: the 0-0 Week 3 is skipped
        self.assertAlmostEqual(avg["h"], 90.0)
        self.assertEqual(book.recent_averages({}), {})

    def test_spread_is_the_average_difference(self) -> None:
        ms = [pickem.Matchup("a@h", "a", "Away", "h", "Home")]
        favored_away = book.make_lines(ms, {"a": 110.3, "h": 100.0})[0]
        self.assertEqual(favored_away.home_spread, 10.5)          # home gets 10.5 points
        self.assertEqual(favored_away.spread(book.AWAY), -10.5)
        self.assertEqual(favored_away.text(), "Away -10.5 at Home +10.5")
        self.assertEqual(favored_away.label(book.HOME), "Home +10.5")
        favored_home = book.make_lines(ms, {"a": 95.0, "h": 101.9})[0]
        self.assertEqual(favored_home.home_spread, -7.0)
        self.assertEqual(favored_home.label(book.HOME), "Home -7")
        even = book.make_lines(ms, {"a": 100.1, "h": 100.0})[0]
        self.assertEqual((even.home_spread, even.text()), (0.0, "Away at Home • pick'em"))
        self.assertEqual(even.label(book.AWAY), "Away (pick'em)")
        unknown = book.make_lines(ms, {"a": 120.0})[0]          # no history for one team: pick'em
        self.assertEqual(unknown.home_spread, 0.0)
        self.assertEqual(book.Line.from_dict(favored_away.as_dict()), favored_away)

    def test_week_one_is_all_pickem(self) -> None:
        lines = book.lines_for_week(INFO, 1, season.period(INFO, 1).start - timedelta(days=2), NY, lambda n: [])
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(x.home_spread == 0 for x in lines))

    def test_lines_read_only_final_weeks(self) -> None:
        asked: list[int] = []

        def scores(n):
            asked.append(n)
            return rows(pickem.matchups(INFO, n), {T8: 100.0, T4: 80.0})

        week4 = season.period(INFO, 4)
        book.lines_for_week(INFO, 5, season.final_at(week4, NY), NY, scores)
        self.assertEqual(asked, [2, 3, 4])
        asked.clear()
        book.lines_for_week(INFO, 5, season.final_at(week4, NY) - timedelta(minutes=1), NY, scores)
        self.assertEqual(asked, [2, 3])  # Week 4 isn't final yet, so it can't set a line
        # Week 1: Test 8 scored 100, its Week 2 opponent Test 2 scored 0, so Test 8 is a 100-point favorite.
        lines = book.lines_for_week(INFO, 2, season.final_at(season.period(INFO, 1), NY), NY, scores)
        test8 = next(x for x in lines if x.involves(T8))
        self.assertEqual((test8.away_id, test8.home_id), (T8, T2))
        self.assertEqual((test8.spread(book.AWAY), test8.spread(book.HOME)), (-100.0, 100.0))


class BettingRuleTests(unittest.TestCase):
    def test_own_matchup_is_banned_either_side(self) -> None:
        x = line(-3.5)
        self.assertIn("own franchise", book.check_bet(x, book.HOME, 10, "a", 0, locked=False))
        self.assertIn("own franchise", book.check_bet(x, book.AWAY, 10, "h", 0, locked=False))
        self.assertIsNone(book.check_bet(x, book.AWAY, 10, "other", 0, locked=False))
        self.assertEqual(book.available([x, line(away="b", home="c")], "a"), [line(away="b", home="c")])

    def test_locking(self) -> None:
        locks = datetime(2026, 10, 5, 23, tzinfo=UTC)
        self.assertFalse(pickem.is_locked(locks, locks - timedelta(seconds=1)))
        self.assertTrue(pickem.is_locked(locks, locks))
        self.assertEqual(book.check_bet(line(), book.HOME, 10, "z", 0, locked=True), "Bets for this Week are locked.")

    def test_budget_and_amounts(self) -> None:
        x = line()
        self.assertIsNone(book.check_bet(x, book.HOME, 100, "z", 0, locked=False))
        self.assertIn("40 Bucks left", book.check_bet(x, book.HOME, 41, "z", 60, locked=False))
        self.assertIsNone(book.check_bet(x, book.HOME, 40, "z", 60, locked=False))
        self.assertIsNone(book.check_bet(x, book.HOME, 0, "z", 100, locked=False))  # 0 removes a bet
        for bad in (-1, 2.5, True):
            self.assertIn("whole number", book.check_bet(x, book.HOME, bad, "z", 0, locked=False))
        self.assertIn("isn't on this Week's board", book.check_bet(None, book.HOME, 5, "z", 0, locked=False))
        self.assertIn("one of the two teams", book.check_bet(x, "", 5, "z", 0, locked=False))
        self.assertIn("isn't linked", book.check_bet(x, book.HOME, 5, "", 0, locked=False))

    def test_replacing_a_bet_frees_its_stake(self) -> None:
        mine = {"a@h": ("home", 70), "b@c": ("away", 30)}
        self.assertEqual(book.staked(mine), 100)
        self.assertEqual(book.staked(mine, except_matchup="a@h"), 30)
        self.assertIsNone(book.check_bet(line(), book.AWAY, 70, "z", book.staked(mine, except_matchup="a@h"),
                                         locked=False))

    def test_side_from_menu_or_typed_name(self) -> None:
        x = line(-6.5)
        self.assertEqual(book.side_from(x, "AWAY"), book.AWAY)
        self.assertEqual(book.side_from(x, "h"), book.HOME)          # team name typed by hand
        self.assertEqual(book.side_from(x, "H -6.5"), book.HOME)    # the label from the menu
        self.assertIsNone(book.side_from(x, "nobody"))
        self.assertEqual(book.side_from(None, "home"), book.HOME)


class SettlementTests(unittest.TestCase):
    def test_against_the_spread(self) -> None:
        fav_home = line(-6.5)  # home must win by 7 or more
        self.assertEqual(book.grade(fav_home, book.HOME, (100.0, 110.0)), book.WIN)
        self.assertEqual(book.grade(fav_home, book.AWAY, (100.0, 110.0)), book.LOSS)
        self.assertEqual(book.grade(fav_home, book.HOME, (100.0, 106.0)), book.LOSS)   # won, didn't cover
        self.assertEqual(book.grade(fav_home, book.AWAY, (100.0, 106.0)), book.WIN)

    def test_pushes(self) -> None:
        whole = line(-10.0)
        self.assertEqual(book.grade(whole, book.HOME, (100.0, 110.0)), book.PUSH)
        self.assertEqual(book.grade(whole, book.AWAY, (100.0, 110.0)), book.PUSH)
        half = line(-6.5)
        self.assertEqual(book.grade(half, book.HOME, (100.25, 106.75)), book.PUSH)  # scores have two decimals
        noisy = line(-0.3 + 0.1 + 0.2 - 6.5)  # float noise in a stored spread can't turn a push into a loss
        self.assertEqual(book.grade(noisy, book.HOME, (100.0, 106.5)), book.PUSH)

    def test_exact_ties(self) -> None:
        pk = line(0.0)
        self.assertEqual(book.grade(pk, book.HOME, (98.4, 98.4)), book.PUSH)
        self.assertEqual(book.grade(pk, book.AWAY, (98.4, 98.4)), book.PUSH)
        dog = line(-2.5)  # a tie means the underdog covers
        self.assertEqual(book.grade(dog, book.AWAY, (98.4, 98.4)), book.WIN)
        self.assertEqual(book.grade(dog, book.HOME, (98.4, 98.4)), book.LOSS)

    def test_settle_week(self) -> None:
        x, y = line(-6.5), line(3.0, "b", "c")
        found = book.results([x, y], pair("a", "h", 100, 110) + pair("b", "c", 90, 93))
        self.assertEqual(found, {"a@h": (100.0, 110.0), "b@c": (90.0, 93.0)})
        bets = [book.Bet(1, "a@h", "home", 25), book.Bet(1, "b@c", "away", 30), book.Bet(2, "a@h", "away", 100),
                book.Bet(3, "b@c", "home", 40), book.Bet(3, "zz@yy", "home", 10)]
        settled = book.settle(bets, [x, y], found)
        self.assertEqual([s.outcome for s in settled], ["win", "loss", "loss", "win", "void"])
        self.assertEqual([s.net for s in settled], [25, -30, -100, 40, 0])
        totals = {r.user_id: r for r in book.week_totals(settled)}
        self.assertEqual((totals[1].profit, totals[1].record), (-5, "1-1-0"))
        self.assertEqual((totals[3].profit, totals[3].record), (40, "1-0-1"))
        self.assertEqual([r.user_id for r in book.week_totals(settled)], [3, 1, 2])

    def test_missing_result_returns_the_stake(self) -> None:
        x = line(-6.5)
        settled = book.settle([book.Bet(1, x.key, "home", 50)], [x], {})
        self.assertEqual((settled[0].outcome, settled[0].net), (book.VOID, 0))
        final = datetime(2026, 10, 12, 10, tzinfo=UTC)
        self.assertFalse(book.ready_to_settle([x], {}, final, final))
        self.assertTrue(book.ready_to_settle([x], {}, final + pickem.SCORE_GRACE, final))
        self.assertTrue(book.ready_to_settle([x], {x.key: (1, 2)}, final, final))

    def test_weekly_reset_nothing_carries_over(self) -> None:
        s = Store(":memory:")
        now = datetime(2026, 10, 1, tzinfo=UTC)
        x = line(-6.5)
        s.add_book_week("L:2026", 1, [x.as_dict()], locks_at=now, now=now)
        s.add_book_week("L:2026", 2, [x.as_dict()], locks_at=now, now=now)
        s.place_bet("L:2026", 1, 7, x.key, "home", 100, "Franchise 2", now=now)   # all in, Week 1
        self.assertIn("0 Bucks left", book.check_bet(line(away="b", home="c"), "home", 1, "z",
                                                     book.staked(s.user_bets("L:2026", 1, 7)), locked=False))
        week2 = s.user_bets("L:2026", 2, 7)
        self.assertEqual(book.staked(week2), 0)                                   # a fresh 100 in Week 2
        self.assertIsNone(book.check_bet(x, "home", 100, "z", book.staked(week2), locked=False))
        lost = book.settle([book.Bet(7, x.key, "home", 100)], [x], {x.key: (100.0, 101.0)})
        won = book.settle([book.Bet(7, x.key, "away", 60)], [x], {x.key: (100.0, 101.0)})
        board = book.leaderboard([lost, won])
        self.assertEqual((board[0].profit, board[0].record, board[0].weeks), (-40, "1-1-0", 2))
        self.assertIn("40 unused", book.mybets_text(2, [x], {x.key: ("away", 60)}, now, locked=False))


class LeaderboardTests(unittest.TestCase):
    def week(self, *results):
        return [book.Settled(book.Bet(uid, f"m{i}", "home", amt), outcome) for i, (uid, amt, outcome) in enumerate(results)]

    def test_season_profit_and_ranks(self) -> None:
        board = book.leaderboard([self.week((1, 50, "win"), (2, 30, "win"), (3, 20, "loss")),
                                  self.week((1, 10, "loss"), (2, 10, "win"), (3, 100, "push"), (4, 5, "loss"))])
        # Equal profit: more wins first (user 2 went 2-0, user 1 went 1-1); the rank is shared.
        self.assertEqual([(r.user_id, r.profit) for r in board], [(2, 40), (1, 40), (4, -5), (3, -20)])
        self.assertEqual([rank for rank, _ in book.ranked(board)], ["T1", "T1", "3", "4"])
        self.assertEqual(board[2].weeks, 1)

    def test_tied_leaders_share_the_role(self) -> None:
        board = book.leaderboard([self.week((1, 50, "win"), (2, 50, "win"), (3, 50, "loss"))])
        self.assertEqual(book.season_leaders(board), [1, 2])
        self.assertEqual(book.season_leaders([]), [])
        losing = book.leaderboard([self.week((5, 10, "loss"), (6, 30, "loss"))])
        self.assertEqual(book.season_leaders(losing), [5])  # the best result still leads

    def test_role_changes_move_the_role(self) -> None:
        self.assertEqual(book.role_changes({1, 2}, [2, 3]), ([3], [1]))
        self.assertEqual(book.role_changes(set(), [9]), ([9], []))
        self.assertEqual(book.role_changes({9}, [9]), ([], []))


class BookTimelineTests(unittest.TestCase):
    def test_book_uses_the_pickem_calendar(self) -> None:
        week1, week2 = season.period(INFO, 1), season.period(INFO, 2)
        self.assertEqual(pickem.plan(INFO, week1.start - timedelta(days=2), NY, {}), [("post", 1)])
        self.assertEqual(pickem.plan(INFO, week1.start, NY, {1: "open"}), [("lock", 1)])
        final1 = season.final_at(week1, NY)
        self.assertEqual(pickem.plan(INFO, final1, NY, {1: "locked"}), [("score", 1), ("post", 2)])
        self.assertEqual(pickem.plan(INFO, final1, NY, {1: "settled", 2: "open"}), [])
        self.assertEqual(pickem.plan(INFO, week2.start + timedelta(hours=1), NY, {1: "settled", 2: "open"}),
                         [("lock", 2)])


class BookStoreTests(unittest.TestCase):
    def test_lifecycle(self) -> None:
        s = Store(":memory:")
        now = datetime(2026, 10, 5, 10, tzinfo=UTC)
        x, y = line(-6.5), line(2.0, "b", "c")
        s.add_book_week("L:2026", 2, [x.as_dict(), y.as_dict()], locks_at=now + timedelta(hours=9), now=now)
        s.set_book_message("L:2026", 2, 10, 20)
        self.assertEqual(s.book_statuses("L:2026"), {2: "open"})
        self.assertEqual(s.latest_book_week("open")["period"], 2)
        s.place_bet("L:2026", 2, 7, x.key, "home", 30, "Franchise 2", now=now)
        s.place_bet("L:2026", 2, 7, x.key, "away", 45, "Franchise 2", now=now)  # replaced, not added
        s.place_bet("L:2026", 2, 7, y.key, "home", 20, "Franchise 2", now=now)
        s.place_bet("L:2026", 2, 8, y.key, "away", 5, "Franchise 9", now=now)
        s.place_bet("L:2026", 2, 8, y.key, "away", 0, "Franchise 9", now=now)   # removed
        self.assertEqual(s.user_bets("L:2026", 2, 7), {x.key: ("away", 45), y.key: ("home", 20)})
        self.assertEqual(s.user_bets("L:2026", 2, 8), {})
        self.assertEqual(len(s.week_bets("L:2026", 2)), 2)
        s.set_book_status("L:2026", 2, "locked")
        self.assertIsNone(s.latest_book_week("open"))
        s.set_book_status("L:2026", 2, "settled", results={x.key: [100.0, 104.0]}, now=now)
        (number, lines, found), = s.settled_book_weeks("L:2026")
        self.assertEqual((number, found), (2, {x.key: [100.0, 104.0]}))
        settled = book.settle([book.Bet(*b[:4], b[4]) for b in s.week_bets("L:2026", 2)],
                              [book.Line.from_dict(d) for d in lines], found)
        self.assertEqual(sorted((t.bet.matchup, t.outcome) for t in settled), [(x.key, "win"), (y.key, "void")])
        self.assertIsNone(s.book_champions("L:2026"))
        s.set_book_champions("L:2026", [7], now=now)
        self.assertEqual(s.book_champions("L:2026"), [7])
        self.assertEqual(s.latest_book_season(), "L:2026")
        self.assertTrue(any(r["action"] == "book_bet" for r in s.audit()))

    def test_existing_database_gains_the_new_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            db = sqlite3.connect(path)
            db.executescript("CREATE TABLE pickem_weeks (season TEXT, period INTEGER, matchups TEXT, locks_at TEXT, "
                             "posted_at TEXT, channel_id INTEGER, message_id INTEGER, status TEXT, winners TEXT, "
                             "scored_at TEXT, PRIMARY KEY (season, period));"
                             "INSERT INTO pickem_weeks VALUES ('L', 1, '[]', 'x', 'x', NULL, NULL, 'open', NULL, NULL);")
            db.commit()
            db.close()
            s = Store(path)
            self.assertEqual(s.book_statuses("L"), {})
            self.assertIsNone(s.latest_awards())
            self.assertEqual(s.pickem_statuses("L"), {1: "open"})
            s.db.close()


class BookEmbedTests(unittest.TestCase):
    def test_posts_fit_and_say_play_money(self) -> None:
        lines = book.make_lines(pickem.matchups(INFO, 2), {m.away_id: 100.0 + i for i, m in enumerate(WEEK1)})
        locks = season.period(INFO, 2).start
        post = book.lines_embed(2, lines, locks, "Season 2026")
        self.assertIn(f"<t:{int(locks.timestamp())}:F>", post["description"])
        self.assertIn("Play money only", json.dumps(post))
        found = book.results(lines, rows(pickem.matchups(INFO, 2), {T4: 120.0, T6: 100.0}))
        bets = [book.Bet(u, lines[u % 6].key, "home", 10 + u) for u in range(40)]
        settled = book.settle(bets, lines, found)
        board = book.leaderboard([settled])
        result = book.settlement_embed(2, lines, found, settled, board, "Season 2026")
        text = json.dumps(result, ensure_ascii=False)
        self.assertIn("covered (Test 4 120.00, Test 6 100.00)", text)
        self.assertIn("push at", text)  # 0-0 placeholders with a pick'em line
        self.assertIn("SEASON PROFIT", text)
        for e in (post, result, book.leaderboard_embed(board, "Season 2026", 1), book.leaderboard_embed([], "S", 0),
                  book.sharp_embed("💸 Sharp", [1, 2], board, "Season 2026")):
            self.assertTrue(embeds.fits([e]))
            self.assertNotIn("Version", json.dumps(e))

    def test_mybets_shows_how_each_bet_went(self) -> None:
        x = line(-6.5)
        when = datetime(2026, 10, 5, tzinfo=UTC)
        text = book.mybets_text(1, [x], {x.key: ("home", 25)}, when, locked=True, found={x.key: [100.0, 110.0]})
        self.assertIn("25 on **H -6.5** vs A • won +25", text)
        self.assertIn("settled", text)
        self.assertIn("No bets yet", book.mybets_text(1, [x], {}, when, locked=False))
        pushed = book.mybets_text(1, [x], {x.key: ("away", 5)}, when, locked=True, found={})
        self.assertIn("no result, returned", pushed)


# ============================================================ Awards Ballot
def league(orphan: str | None = None) -> list[rules.Franchise]:
    return [rules.Franchise(f"F{i}", 100 + i, commissioner=(i == 1), orphaned=(f"F{i}" == orphan),
                            fantrax_team_id=f"t{i}") for i in range(1, 13)]


NAMES = [f.name for f in league()]
GM = awards.BY_KEY["gm"]
TRADE = awards.BY_KEY["trade"]
COMEBACK = awards.BY_KEY["comeback"]
BUST = awards.BY_KEY["bust"]


class NomineeTests(unittest.TestCase):
    def test_parse_hand_typed_nominees(self) -> None:
        found, errors = awards.parse_nominees(
            TRADE, "F3 + F7: Hughes for a 2029 1st; f2, F9: Aho swap\nNobody + F4: x; F5: solo trade", NAMES)
        self.assertEqual([(n.id, n.label, n.franchises) for n in found],
                         [("trade-1", "Hughes for a 2029 1st", ("F3", "F7")), ("trade-2", "Aho swap", ("F2", "F9"))])
        self.assertEqual(len(errors), 2)
        self.assertIn("start with the franchise name", errors[0])
        self.assertIn("name both franchises", errors[1])
        waiver, errors = awards.parse_nominees(awards.BY_KEY["waiver"], "F4: Quinn Hughes off waivers; F6", NAMES,
                                               start=4)
        self.assertEqual([(n.id, n.label) for n in waiver], [("waiver-4", "Quinn Hughes off waivers"), ("waiver-5", "F6")])
        self.assertEqual(errors, [])
        self.assertEqual(waiver[0].subtitle, "F4")
        self.assertEqual(waiver[1].subtitle, "")

    def test_franchise_names_with_separators_match_whole(self) -> None:
        names = ["Pucks, Pints & Co", "Ice Dogs"]
        self.assertEqual(awards.match_franchises("pucks, pints & co", names), ["Pucks, Pints & Co"])
        self.assertEqual(awards.match_franchises("Ice Dogs + Pucks, Pints & Co", names), None)
        self.assertEqual(awards.match_franchises("Ice Dogs", names), ["Ice Dogs"])

    def test_gm_of_the_year_is_every_active_franchise(self) -> None:
        nominees = awards.gm_nominees(league("F5"))
        self.assertEqual(len(nominees), 11)
        self.assertNotIn("F5", [n.label for n in nominees])

    def test_comeback_and_bust_from_the_standings(self) -> None:
        previous = {"F1": 10, "F2": 3, "F3": 7, "F4": 1, "F5": 12, "F6": 4}
        current = {"F1": 2, "F2": 9, "F3": 4, "F4": 1, "F5": 9, "F6": 6, "F7": 5}
        comeback = awards.comeback_nominees(previous, current)
        self.assertEqual([(n.label, n.detail) for n in comeback],
                         [("F1", "10th to 2nd, up 8"), ("F3", "7th to 4th, up 3"), ("F5", "12th to 9th, up 3")])
        self.assertEqual([n.label for n in awards.comeback_nominees(previous, current, top=2)], ["F1", "F3", "F5"])
        bust = awards.bust_nominees(previous, current)
        self.assertEqual([(n.label, n.detail) for n in bust], [("F2", "3rd to 9th, down 6"), ("F6", "4th to 6th, down 2")])
        self.assertEqual(awards.ordinal(11), "11th")
        self.assertEqual(awards.ordinal(22), "22nd")

    def test_ranks_from_fantrax_standings(self) -> None:
        cfg = load(HERE.parent / "config.yaml")
        ranks = awards.ranks_by_franchise(STANDINGS, cfg.franchises)
        self.assertEqual(len(ranks), 12)
        self.assertEqual(ranks["Franchise 4"], 1)  # Test 4 tops the Week 0 sample
        self.assertEqual(sorted(ranks.values()), list(range(1, 13)))

    def test_commissioner_cannot_nominate_own_franchise(self) -> None:
        nominees, errors, notes = awards.build_ballot(
            league(), {"trade": "F1 + F4: blockbuster; F2 + F3: swap", "waiver": "F6: steal"}, None, None, {"F1"})
        self.assertEqual(len(errors), 1)
        self.assertIn("Commissioner can't nominate their own franchise (F1)", errors[0])
        self.assertIn("(19.3)", errors[0])
        self.assertTrue(any("Comeback Franchise isn't on the ballot: last Season's final standings" in n for n in notes))
        # Proposed from the standings, the Commissioner's franchise can be a Comeback nominee: nobody picked it.
        nominees, errors, notes = awards.build_ballot(league(), {"trade": "F2 + F3: swap"}, {"F1": 12, "F2": 1},
                                                      {"F1": 1, "F2": 12}, {"F1"})
        self.assertEqual(errors, [])
        self.assertEqual([n.label for n in nominees["comeback"]], ["F1"])
        self.assertEqual([n.label for n in nominees["bust"]], ["F2"])
        self.assertEqual(list(nominees), ["gm", "trade", "comeback", "bust"])
        self.assertTrue(any("Waiver Steal of the Year isn't on the ballot" in n for n in notes))
        # Typed by hand, it can't.
        _, errors, _ = awards.build_ballot(league(), {"comeback": "F1; F3"}, None, None, {"F1"})
        self.assertEqual(len(errors), 1)

    def test_assistant_and_gm_nomination_rules(self) -> None:
        found, _ = awards.parse_nominees(TRADE, "F1 + F4: deal", NAMES)
        self.assertEqual(awards.nomination_problems(TRADE, found, {"F9"}, commissioner=False), [])  # neutral Assistant
        self.assertIn("can't nominate your own franchise (F4)",
                      awards.nomination_problems(TRADE, found, {"F4"}, commissioner=False)[0])
        self.assertIn("every active franchise is on the ballot", awards.nomination_problems(GM, [], set(), commissioner=True)[0])
        self.assertEqual(awards.next_index([awards.Nominee("trade-1", "x"), awards.Nominee("trade-4", "y")]), 5)
        self.assertEqual(awards.next_index([]), 1)
        crowded = {"trade": [awards.Nominee(f"trade-{i}", str(i)) for i in range(26)]}
        self.assertIn("holds 25", awards.too_many(crowded)[0])

    def test_nominees_round_trip(self) -> None:
        nominees, _, _ = awards.build_ballot(league(), {"trade": "F2 + F3: swap"}, None, None, {"F1"})
        self.assertEqual(awards.nominees_from_json(awards.nominees_to_json(nominees)), nominees)


class BallotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = awards.gm_nominees(league())
        self.trades, _ = awards.parse_nominees(TRADE, "F2 + F3: a; F4 + F5: b; F6 + F7: c", NAMES)

    def test_self_vote_ban(self) -> None:
        own = next(n for n in self.gm if n.label == "F2")
        _, error = awards.choose({}, 1, own.id, GM, self.gm, "F2")
        self.assertEqual(error, "You can't vote for your own franchise for GM of the Year.")
        self.assertNotIn(own, awards.options_for(GM, self.gm, "F2"))
        self.assertEqual(len(awards.options_for(GM, self.gm, "F2")), 11)
        comeback = awards.comeback_nominees({"F2": 9}, {"F2": 1})
        self.assertEqual(awards.options_for(COMEBACK, comeback, "F2"), [])
        _, error = awards.choose({}, 1, comeback[0].id, COMEBACK, comeback, "F2")
        self.assertIn("own franchise", error)
        # Self-votes are fine for the hand-picked fun awards.
        mine, error = awards.choose({}, 1, self.trades[0].id, TRADE, self.trades, "F2")
        self.assertEqual((mine, error), ({1: "trade-1"}, None))

    def test_choose_places_and_moves(self) -> None:
        ballot, _ = awards.choose({}, 1, "gm-3", GM, self.gm, "F2")
        ballot, _ = awards.choose(ballot, 2, "gm-4", GM, self.gm, "F2")
        ballot, _ = awards.choose(ballot, 3, "gm-5", GM, self.gm, "F2")
        self.assertEqual(ballot, {1: "gm-3", 2: "gm-4", 3: "gm-5"})
        moved, _ = awards.choose(ballot, 1, "gm-5", GM, self.gm, "F2")   # 3rd moves up to 1st
        self.assertEqual(moved, {1: "gm-5", 2: "gm-4"})
        replaced, _ = awards.choose(ballot, 2, "gm-9", GM, self.gm, "F2")
        self.assertEqual(replaced, {1: "gm-3", 2: "gm-9", 3: "gm-5"})
        same, error = awards.choose(ballot, 4, "gm-6", GM, self.gm, "F2")
        self.assertEqual((same, error), (ballot, "Pick a 1st, 2nd or 3rd choice."))
        self.assertIn("isn't on the GM of the Year ballot", awards.choose({}, 1, "trade-1", GM, self.gm, "F2")[1])

    def test_ballot_validation(self) -> None:
        nominees = {"gm": self.gm, "trade": self.trades}
        self.assertEqual(awards.ballot_problems({"gm": {1: "gm-3", 2: "gm-4"}, "trade": {1: "trade-1"}}, nominees, "F2"), [])
        problems = awards.ballot_problems({"gm": {1: "gm-2", 2: "gm-4", 3: "gm-4", 4: "gm-5"}, "trade": {1: "trade-9"},
                                           "mvp": {1: "x"}}, nominees, "F2")
        self.assertEqual(len(problems), 5)
        self.assertTrue(any("can't vote for itself" in p for p in problems))
        self.assertTrue(any("ranked twice" in p for p in problems))
        self.assertTrue(any("Unknown award" in p for p in problems))


class TallyTests(unittest.TestCase):
    def nominees(self, n: int = 4) -> list[awards.Nominee]:
        return [awards.Nominee(f"trade-{i}", f"Deal {i}", (f"F{i}", f"F{i + 4}")) for i in range(1, n + 1)]

    def test_five_three_one(self) -> None:
        r = awards.tally(TRADE, self.nominees(), {
            "F1": {1: "trade-1", 2: "trade-2", 3: "trade-3"},
            "F2": {1: "trade-1", 2: "trade-3", 3: "trade-2"},
            "F3": {1: "trade-2", 2: "trade-1"},
            "F4": {},
        })
        self.assertEqual([(row.nominee.id, row.points, row.firsts, row.seconds, row.thirds) for row in r.rows],
                         [("trade-1", 13, 2, 1, 0), ("trade-2", 9, 1, 1, 1), ("trade-3", 4, 0, 1, 1),
                          ("trade-4", 0, 0, 0, 0)])
        self.assertEqual(([w.id for w in r.winners], r.ballots, r.decided_by, r.shared), (["trade-1"], 3, "points", False))

    def test_tie_goes_to_most_first_place_votes(self) -> None:
        r = awards.tally(TRADE, self.nominees(), {
            "F1": {1: "trade-1", 2: "trade-2"},      # Deal 1: 5, Deal 2: 3
            "F2": {1: "trade-1", 2: "trade-2"},      # Deal 1: 10, Deal 2: 6
            "F3": {1: "trade-2", 3: "trade-1"},      # Deal 1: 11, Deal 2: 11
        })
        self.assertEqual([(row.points, row.firsts) for row in r.rows[:2]], [(11, 2), (11, 1)])
        self.assertEqual(([w.id for w in r.winners], r.decided_by), (["trade-1"], "first-place votes"))
        self.assertIn("won the tie on first-place votes", json.dumps(awards.results_embed(2027, [r], 3, 12)))

    def test_still_tied_is_shared(self) -> None:
        r = awards.tally(TRADE, self.nominees(), {
            "F1": {1: "trade-1", 2: "trade-2"},
            "F2": {1: "trade-2", 2: "trade-1"},
        })
        self.assertEqual(([w.id for w in r.winners], r.decided_by, r.shared), (["trade-1", "trade-2"], "shared", True))
        text = json.dumps(awards.results_embed(2027, [r], 2, 12))
        self.assertIn("**Deal 1** (F1 + F5) and **Deal 2** (F2 + F6)", text)
        self.assertIn("shared", text)

    def test_invalid_entries_never_count(self) -> None:
        gm = awards.gm_nominees(league())
        r = awards.tally(GM, gm, {
            "F2": {1: "gm-2", 2: "gm-3", 3: "gm-3"},  # self-vote skipped, duplicate skipped
            "F4": {1: "gm-99", 2: "gm-3"},            # unknown nominee skipped
            "F5": {1: "gm-5"},                        # only a self-vote: no ballot counted
        })
        points = {row.nominee.label: row.points for row in r.rows if row.points}
        self.assertEqual(points, {"F3": 6})
        self.assertEqual(r.ballots, 2)

    def test_no_votes_no_winner(self) -> None:
        r = awards.tally(TRADE, self.nominees(), {})
        self.assertEqual((r.winners, r.decided_by), ([], ""))
        self.assertIn("No votes.", json.dumps(awards.results_embed(2027, [r], 0, 12)))

    def test_only_active_franchises_count(self) -> None:
        nominees = {"trade": self.nominees()}
        ballots = {"F1": {"trade": {1: "trade-4"}}, "F12": {"trade": {1: "trade-3"}}, "F2": {"trade": {}}}
        results = awards.tally_all(nominees, ballots, [n for n in NAMES if n != "F12"])
        self.assertEqual([w.id for w in results[0].winners], ["trade-4"])
        self.assertEqual(awards.returned(ballots, [n for n in NAMES if n != "F12"]), ["F1"])


class AwardsTimingTests(unittest.TestCase):
    NOW = datetime(2028, 4, 12, 15, tzinfo=UTC)

    def test_deadline(self) -> None:
        dt, error = awards.parse_deadline("2028-04-20", self.NOW, NY)
        self.assertIsNone(error)
        self.assertEqual(dt, datetime(2028, 4, 20, 23, 59, 59, tzinfo=NY))
        dt, _ = awards.parse_deadline("2028-04-20 21:00", self.NOW, NY)
        self.assertEqual(dt, datetime(2028, 4, 20, 21, tzinfo=NY))
        self.assertIn("future", awards.parse_deadline("2028-04-01", self.NOW, NY)[1])
        self.assertIn("30 days or less", awards.parse_deadline("2028-06-01", self.NOW, NY)[1])
        self.assertIn("like 2028-04-20", awards.parse_deadline("next friday", self.NOW, NY)[1])

    def test_opens_only_after_the_championship(self) -> None:
        self.assertEqual(awards.open_problems("offseason", 2027), [])
        self.assertEqual(awards.open_problems("preseason", 2027), [])  # next Season's league already renewed
        self.assertEqual(awards.open_problems(None, 2027), [])         # Fantrax down: the Commissioner decides
        self.assertIn("after the BLHA Championship", awards.open_problems("playoffs", 2027)[0])
        self.assertIn("after the BLHA Championship", awards.open_problems("regular", 2027)[0])
        self.assertTrue(awards.open_problems("offseason", 27))
        self.assertEqual(season.phase(INFO, datetime(2027, 6, 1, tzinfo=UTC)), "offseason")


class AwardsStoreTests(unittest.TestCase):
    def test_open_vote_close_publish(self) -> None:
        s = Store(":memory:")
        now = datetime(2028, 4, 12, tzinfo=UTC)
        nominees = {"gm": awards.gm_nominees(league())}
        s.open_awards(2027, awards.nominees_to_json(nominees), user_id=1, now=now, closes_at=now + timedelta(days=7))
        s.set_awards_message(2027, 50, 60)
        self.assertEqual(s.awards_by_message(60)["season"], 2027)
        with self.assertRaises(sqlite3.IntegrityError):  # one ballot per Season
            s.open_awards(2027, "{}", user_id=1, now=now, closes_at=now)
        s.set_award_choices(2027, "F2", "gm", {1: "gm-3", 2: "gm-4"}, user_id=7, now=now)
        s.set_award_choices(2027, "F2", "gm", {1: "gm-5"}, user_id=7, now=now)   # an edit replaces the award
        s.set_award_choices(2027, "F3", "gm", {1: "gm-5", 3: "gm-2"}, user_id=8, now=now)
        self.assertEqual(s.awards_ballot(2027, "F2"), {"gm": {1: "gm-5"}})
        self.assertEqual(s.awards_ballots(2027), {"F2": {"gm": {1: "gm-5"}}, "F3": {"gm": {1: "gm-5", 3: "gm-2"}}})
        self.assertEqual(s.awards_due_to_close(now + timedelta(days=6)), [])
        self.assertEqual(len(s.awards_due_to_close(now + timedelta(days=7))), 1)
        s.close_awards(2027, now=now + timedelta(days=7))
        self.assertEqual(s.awards_season(2027)["status"], "closed")
        self.assertEqual(s.awards_due_to_close(now + timedelta(days=8)), [])
        s.set_awards_results(2027, {"season": 2027}, now=now, user_id=1)
        self.assertEqual(s.latest_awards()["status"], "posted")
        s.save_ranks(2027, {"F1": 3}, now=now)
        self.assertEqual((s.ranks(2027), s.ranks(2026)), ({"F1": 3}, None))
        self.assertEqual({r["action"] for r in s.audit()} >= {"awards_opened", "awards_ballot", "awards_closed",
                                                              "awards_results"}, True)


class AwardsExportTests(unittest.TestCase):
    def results(self):
        gm = awards.gm_nominees(league())
        trades, _ = awards.parse_nominees(TRADE, "F2 + F3: swap; F4 + F5: deal", NAMES)
        nominees = {"gm": gm, "trade": trades}
        ballots = {"F1": {"gm": {1: "gm-3", 2: "gm-2"}, "trade": {1: "trade-2"}},
                   "F2": {"gm": {1: "gm-3"}, "trade": {1: "trade-1", 2: "trade-2"}}}
        return awards.tally_all(nominees, ballots, NAMES)

    def test_payload(self) -> None:
        closed = datetime(2028, 4, 19, 4, tzinfo=UTC)
        payload = awards.season_payload(2027, self.results(), closed_at=closed, ballots=2, eligible=12,
                                        franchises=league())
        self.assertEqual(payload["season"], 2027)
        self.assertEqual(payload["closed_at"], "2028-04-19T04:00:00+00:00")
        self.assertEqual(payload["points"], {"first": 5, "second": 3, "third": 1})
        gm, trade = payload["awards"]
        self.assertEqual((gm["key"], gm["name"]), ("gm", "GM of the Year"))
        self.assertEqual(gm["winners"], [{"nominee": "F3", "franchises": ["F3"], "fantrax_team_ids": ["t3"], "detail": "",
                                          "points": 10, "first_place_votes": 2}])
        self.assertEqual(len(gm["results"]), 12)
        self.assertEqual(trade["winners"][0]["fantrax_team_ids"], ["t4", "t5"])
        self.assertEqual(trade["decided_by"], "points")
        self.assertEqual(trade["results"][0]["first"] + trade["results"][1]["first"], 2)
        json.dumps(payload)  # plain JSON

    def test_export_file_keeps_every_season(self) -> None:
        now = datetime(2028, 4, 20, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "blha_awards.json"
            first = awards.season_payload(2027, self.results(), closed_at=None, ballots=2, eligible=12, franchises=league())
            awards.write_export(path, first, now)
            second = dict(first, season=2028)
            merged = awards.write_export(path, second, now + timedelta(days=365))
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, merged)
            self.assertEqual(on_disk["format"], "blha-awards/1")
            self.assertEqual(list(on_disk["seasons"]), ["2027", "2028"])
            self.assertFalse(any(p.name.endswith(".tmp") for p in path.parent.iterdir()))
            path.write_text("not json", encoding="utf-8")  # a damaged file is replaced, not fatal
            self.assertEqual(list(awards.write_export(path, first, now)["seasons"]), ["2027"])
        self.assertEqual(awards.merge_export({"format": "other", "seasons": {"1": {}}}, first, now)["seasons"].keys(),
                         {"2027"})
        self.assertEqual(awards.default_export_path("/data/blha_votes.db"), Path("/data/blha_awards.json"))

    def test_embeds_fit(self) -> None:
        many = {a.key: [awards.Nominee(f"{a.key}-{i}", "N" * 100, ("F1", "F2"), "detail " * 5) for i in range(25)]
                for a in awards.AWARDS}
        closes = datetime(2028, 4, 20, tzinfo=UTC)
        ballot = awards.ballot_embed(2027, many, closes)
        self.assertTrue(embeds.fits([ballot]))  # 125 long nominees still fit one message
        self.assertTrue(ballot["fields"][0]["value"].endswith("…"))
        small = awards.ballot_embed(2027, {"gm": awards.gm_nominees(league())}, closes)
        self.assertEqual(small["fields"][0]["value"], "\n".join(NAMES))
        text = json.dumps(ballot, ensure_ascii=False)
        self.assertIn("🏆│hall-of-champions", text)
        self.assertIn("(19.3)", text)
        results = awards.results_embed(2027, self.results(), 2, 12)
        self.assertTrue(embeds.fits([results]))
        self.assertIn("GM OF THE YEAR", json.dumps(results))
        content = awards.ballot_content(2027, GM, awards.gm_nominees(league()), {1: "gm-3"}, "F2", closes, 0, 5,
                                        can_rank=True)
        self.assertIn("Your picks: 1st F3", content)
        self.assertIn("no self-votes", content)
        self.assertIn("nothing for you to rank", awards.ballot_content(2027, COMEBACK, [], {}, "F2", closes, 3, 5,
                                                                         can_rank=False))
        self.assertIn("Returned (1): F2", awards.status_text(2027, "open", closes, ["F2"], ["F3"]))


# ------------------------------------------------------------------ config
class ConfigTests(unittest.TestCase):
    def test_shipped_defaults(self) -> None:
        cfg = load(HERE.parent / "config.yaml")
        self.assertEqual((cfg.book_players, cfg.sharp_role, cfg.awards_ballot_days, cfg.awards_export_path),
                         (("owner",), "💸 Sharp", 7, None))
        problems = "\n".join(cfg.problems)
        self.assertIn("discord.book_channel_id is not set, so BLHA Bucks is off.", problems)
        self.assertIn("hall_of_champions_channel_id is not set", problems)

    def test_validation(self) -> None:
        text = """
discord: {franchise_owner_role_id: "44", co_owner_role_id: "55", book_channel_id: "77", hall_of_champions_channel_id: "78"}
franchises:
  - {name: A, role_id: "1", fantrax_team_id: "t1", commissioner: true}
book: {players: [owner, co_owner, fans], sharp_role: "Sharp Shooter"}
awards: {ballot_days: 99, export_path: /data/x.json}
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(text)
        try:
            cfg = load(f.name)
        finally:
            os.unlink(f.name)
        problems = "\n".join(cfg.problems)
        self.assertIn("book.players has 'fans'", problems)
        self.assertIn("awards.ballot_days must be 1 to 30", problems)
        self.assertNotIn("book_channel_id is not set", problems)
        self.assertEqual((cfg.book_role_ids, cfg.sharp_role, cfg.awards_ballot_days, cfg.awards_export_path),
                         ({44, 55}, "Sharp Shooter", 7, "/data/x.json"))
        self.assertEqual((cfg.book_channel_id, cfg.hall_of_champions_channel_id), (77, 78))


# ======================================================= Discord flows (CI)
OWNER, CO_OWNER, COMMISH, ASSISTANT = 900, 901, 902, 903
BOOK_CH, VOTING_CH, HALL_CH = 50, 51, 52


def as_dict(embed) -> dict:
    return embed.to_dict() if hasattr(embed, "to_dict") else dict(embed)


class FakeMessage:
    _next = 1000

    def __init__(self, channel, content=None, **kw) -> None:
        FakeMessage._next += 1
        self.id = FakeMessage._next
        self.channel, self.content, self.kw = channel, content, kw
        self.jump_url = f"https://discord.test/{channel.id}/{self.id}"
        self.edits: list[dict] = []

    async def edit(self, **kw) -> None:
        self.edits.append(kw)


class FakeChannel:
    def __init__(self, cid: int) -> None:
        self.id = cid
        self.sent: list[FakeMessage] = []

    async def send(self, content=None, **kw) -> FakeMessage:
        msg = FakeMessage(self, content, **kw)
        self.sent.append(msg)
        return msg

    async def fetch_message(self, mid: int) -> FakeMessage:
        return next(m for m in self.sent if m.id == mid)


class FakeRole:
    def __init__(self, name: str) -> None:
        self.name, self.members = name, []


class FakeMember:
    def __init__(self, uid: int, role_ids: set[int]) -> None:
        self.id = uid
        self.roles = [SimpleNamespace(id=r) for r in role_ids]

    async def add_roles(self, role, reason=None) -> None:
        role.members.append(self)

    async def remove_roles(self, role, reason=None) -> None:
        role.members.remove(self)


class FakeGuild:
    def __init__(self, members: list[FakeMember], roles: list[FakeRole]) -> None:
        self.members = {m.id: m for m in members}
        self.roles = roles

    def get_member(self, uid: int):
        return self.members.get(uid)

    async def fetch_member(self, uid: int):
        return self.members[uid]


class Reply:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.edited: list[dict] = []

    async def send_message(self, content=None, **kw) -> None:
        self.sent.append((content, kw))

    async def edit_message(self, **kw) -> None:
        self.edited.append(kw)

    async def defer(self, **kw) -> None:
        pass

    async def send(self, content=None, **kw) -> None:  # followup
        self.sent.append((content, kw))


class FakeInteraction:
    def __init__(self, user: FakeMember, message: FakeMessage | None = None, **namespace) -> None:
        self.user, self.message = user, message
        self.response, self.followup = Reply(), Reply()
        self.namespace = SimpleNamespace(**namespace)
        self.guild = self.channel = None


class FlowData:
    """LeagueData stand-in: the test league's calendar, scripted scores and the Week 0 standings."""

    league_id = "w02cjakmmumb3lur"

    def __init__(self, info: dict, scores: dict[int, list[dict]]) -> None:
        self.info, self.scores = info, scores

    def league_info(self):
        return self.info

    def matchup_scores(self, period):
        return self.scores.get(period, [])

    def standings(self):
        return STANDINGS


def flow_config(tmp: str):
    cfg = load(HERE.parent / "config.yaml")
    cfg.owner_role_id, cfg.co_owner_role_id, cfg.commissioner_role_id, cfg.assistant_role_id = (
        OWNER, CO_OWNER, COMMISH, ASSISTANT)
    cfg.guild_id, cfg.book_channel_id, cfg.voting_channel_id, cfg.hall_of_champions_channel_id = 1, BOOK_CH, VOTING_CH, HALL_CH
    cfg.pickem_channel_id = None
    cfg.awards_export_path = str(Path(tmp) / "blha_awards.json")
    cfg.franchises = [replace(f, role_id=100 + i) for i, f in enumerate(cfg.franchises, 1)]
    return cfg


def owner(uid: int, franchise_number: int, *extra: int) -> FakeMember:
    """A Franchise Owner of "Franchise N" (role 100 + N)."""
    return FakeMember(uid, {OWNER, 100 + franchise_number, *extra})


@unittest.skipUnless(importlib.util.find_spec("discord"), "discord.py not installed")
class DiscordFlowTests(unittest.TestCase):
    """Runs in GitHub Actions, where discord.py is installed."""

    def make_bot(self, info: dict, scores: dict[int, list[dict]], tmp: str):
        from blha_vote.app import VoteBot
        bot = VoteBot(flow_config(tmp), Store(":memory:"), data=FlowData(info, scores))
        channels = {cid: FakeChannel(cid) for cid in (BOOK_CH, VOTING_CH, HALL_CH)}

        async def channel(cid):
            return channels.get(cid)

        bot.channel = channel
        return bot, channels

    @staticmethod
    def command(bot, group: str, name: str):
        return next(c for c in bot.tree.get_commands() if c.name == group).get_command(name)

    def test_book_season(self) -> None:
        import blha_vote.app as app
        info = copy.deepcopy(INFO)
        info["playoffs"]["lastRegularSeasonPeriod"] = 2  # a two-Week regular season, so the Sharp role is awarded
        week1, week2 = season.period(info, 1), season.period(info, 2)
        scores = {1: rows(WEEK1, {T8: 120.0, T4: 100.0, TEST: 90.0, T5: 90.0}),
                  2: rows(pickem.matchups(info, 2), {T4: 110.0, T6: 100.0})}
        clock = [week1.start - timedelta(days=2)]
        sharp = FakeRole("💸 Sharp")
        f2, f3, f8, old_holder = owner(7, 2), owner(8, 3), owner(9, 8), FakeMember(5, set())
        sharp.members.append(old_holder)
        guild = FakeGuild([f2, f3, f8, old_holder], [sharp])

        async def run():
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, "utcnow", lambda: clock[0]):
                bot, channels = self.make_bot(info, scores, tmp)
                bot.get_guild = lambda gid: guild
                bet = self.command(bot, "book", "bet")
                await bot.book_tick(clock[0])                                    # Week 1 lines (pick'em)
                post = channels[BOOK_CH].sent[-1]
                self.assertIn("WEEK 1 LINES", as_dict(post.kw["embed"])["title"])
                lines = bot.book_lines_of(bot.store.book_week(bot.store.latest_book_season(), 1))
                t8_t4 = next(x for x in lines if x.involves(T8))
                test_t5 = next(x for x in lines if x.involves(TEST))
                t9_t7 = next(x for x in lines if x.involves(T7))
                # Franchise 8 (Test 8) can't bet on Test 8 at Test 4; Franchise 2 can.
                i = FakeInteraction(f8)
                await bet.callback(i, matchup=t8_t4.key, side="home", amount=10)
                self.assertIn("own franchise", i.response.sent[-1][0])
                i = FakeInteraction(f2)
                await bet.callback(i, matchup=test_t5.key, side="away", amount=10)
                self.assertIn("own franchise", i.response.sent[-1][0])
                i = FakeInteraction(f2)
                await bet.callback(i, matchup=t8_t4.key, side="away", amount=60)
                self.assertIn("**60 Bucks** on **Test 8 (pick'em)**", i.response.sent[-1][0])
                i = FakeInteraction(f2)
                await bet.callback(i, matchup=t9_t7.key, side="home", amount=50)  # only 40 left
                self.assertIn("40 Bucks left", i.response.sent[-1][0])
                i = FakeInteraction(f3)
                await bet.callback(i, matchup=t8_t4.key, side="Test 4", amount=100)
                self.assertIn("**100 Bucks** on **Test 4", i.response.sent[-1][0])
                i = FakeInteraction(FakeMember(11, {CO_OWNER, 104}))           # Co-Owners don't play by default
                await bet.callback(i, matchup=t8_t4.key, side="home", amount=5)
                self.assertIn("for Franchise Owners", i.response.sent[-1][0])
                # The matchup menu never offers your own matchup; the side menu shows each team's spread.
                menu = bot.book_matchup_choices(f8, "")
                self.assertEqual(len(menu), 5)
                self.assertNotIn(t8_t4.key, [c.value for c in menu])
                self.assertEqual(len(bot.book_matchup_choices(f2, "test 9")), 1)
                self.assertEqual([c.name for c in bot.book_side_choices(t8_t4.key)],
                                 ["Test 8 (pick'em) (away)", "Test 4 (pick'em) (home)"])
                self.assertEqual([c.value for c in bot.book_side_choices("nope")], ["away", "home"])
                clock[0] = week1.start                                          # Week 1 starts: locked
                await bot.book_tick(clock[0])
                i = FakeInteraction(f3)
                await bet.callback(i, matchup=t8_t4.key, side="away", amount=1)
                self.assertIn("No Week is open for bets", i.response.sent[-1][0])
                clock[0] = season.final_at(week1, NY)                            # final: settle and post Week 2
                await bot.book_tick(clock[0])
                titles = [as_dict(m.kw["embed"])["title"] for m in channels[BOOK_CH].sent if "embed" in m.kw]
                self.assertEqual(titles[-2:], ["BLHA BUCKS — WEEK 1 SETTLED", "BLHA BUCKS — WEEK 2 LINES"])
                settled = json.dumps(as_dict(channels[BOOK_CH].sent[-2].kw["embed"]), ensure_ascii=False)
                self.assertIn("<@7> +60 (1-0-0)", settled)
                self.assertIn("<@8> -100 (0-1-0)", settled)
                week2_lines = bot.book_lines_of(bot.store.book_week(bot.store.latest_book_season(), 2))
                t8 = next(x for x in week2_lines if x.involves(T8))
                self.assertEqual(t8.spread(book.AWAY if t8.away_id == T8 else book.HOME), -120.0)  # 120 avg vs 0
                i = FakeInteraction(f3)
                mybets = self.command(bot, "book", "mybets")
                await mybets.callback(i)
                self.assertIn("Season profit: **-100 Bucks** (0-1-0), rank 2 of 2", i.response.sent[-1][0])
                # Week 2 (the last regular-season Week) settles with no bets: no settlement post, but the role moves.
                clock[0] = week2.start
                await bot.book_tick(clock[0])
                clock[0] = season.final_at(week2, NY)
                await bot.book_tick(clock[0])
                self.assertEqual([m.id for m in sharp.members], [7])            # last Season's holder lost it
                self.assertEqual(bot.store.book_champions(bot.store.latest_book_season()), [7])
                self.assertIn("SEASON CHAMPION", as_dict(channels[BOOK_CH].sent[-1].kw["embed"])["title"])
                await bot.book_crown(bot.store.latest_book_season(), [])        # once per season
                self.assertEqual([m.id for m in sharp.members], [7])
                board = self.command(bot, "book", "leaderboard")
                i = FakeInteraction(f3)
                await board.callback(i)
                self.assertIn("<@7> +60", json.dumps(as_dict(i.response.sent[-1][1]["embed"]), ensure_ascii=False))

        asyncio.run(run())

    def test_awards_season(self) -> None:
        import blha_vote.app as app
        clock = [datetime(2027, 6, 1, 15, tzinfo=UTC)]  # after the Championship (offseason)
        commish, f2, f3 = owner(1, 1, COMMISH), owner(7, 2), owner(8, 3)
        assistant = owner(9, 9, ASSISTANT)

        async def run():
            with tempfile.TemporaryDirectory() as tmp, patch.object(app, "utcnow", lambda: clock[0]):
                bot, channels = self.make_bot(INFO, {}, tmp)
                bot.store.save_ranks(2026, {f"Franchise {n}": 13 - n for n in range(1, 13)}, now=clock[0])
                opener = self.command(bot, "awards", "open")
                i = FakeInteraction(f2)
                await opener.callback(i, season=2027)
                self.assertIn("Only the Commissioner", i.response.sent[-1][0])
                i = FakeInteraction(commish)                                     # own franchise: refused
                await opener.callback(i, season=2027, trades="Franchise 1 + Franchise 4: blockbuster")
                self.assertIn("can't nominate their own franchise (Franchise 1)", i.followup.sent[-1][0])
                i = FakeInteraction(commish)
                await opener.callback(i, season=2027, trades="Franchise 2 + Franchise 3: swap; Franchise 5 + Franchise 6: deal",
                                      waivers="Franchise 3: Quinn Hughes", deadline="2027-06-05")
                self.assertIn("Awards Ballot is open", i.followup.sent[-1][0])
                post = channels[VOTING_CH].sent[-1]
                self.assertEqual(as_dict(post.kw["embed"])["title"], "BLHA AWARDS NIGHT")
                self.assertTrue(post.kw["view"].is_persistent())
                row = bot.store.awards_season(2027)
                nominees = awards.nominees_from_json(row["nominees"])
                self.assertEqual(list(nominees), ["gm", "trade", "waiver", "comeback", "bust"])
                # A neutral Assistant adds the Commissioner's trade; the Commissioner couldn't.
                nominate = self.command(bot, "awards", "nominate")
                choice = SimpleNamespace(value="trade", name="Trade of the Year")
                i = FakeInteraction(commish)
                await nominate.callback(i, award=choice, nominee="Franchise 1 + Franchise 4: blockbuster")
                self.assertIn("can't nominate their own franchise", i.response.sent[-1][0])
                i = FakeInteraction(assistant)
                await nominate.callback(i, award=choice, nominee="Franchise 1 + Franchise 4: blockbuster")
                self.assertIn("Added to Trade of the Year: blockbuster.", i.response.sent[-1][0])
                self.assertEqual(len(post.edits), 1)                            # the public list is updated
                # Franchise 2's owner fills out GM of the Year; their own franchise isn't offered.
                i = FakeInteraction(f2, message=post)
                await bot.open_awards_ballot(i)
                view = i.response.sent[-1][1]["view"]
                self.assertEqual(view.award.key, "gm")
                selects = [c for c in view.children if hasattr(c, "options")]
                self.assertEqual(len(selects), 3)
                self.assertNotIn("Franchise 2", [o.label for o in selects[0].options])
                gm = {n.label: n.id for n in nominees["gm"]}
                await bot.save_award_choice(FakeInteraction(f2, message=post), view, 1, gm["Franchise 3"])
                i = FakeInteraction(f2, message=post)
                await bot.save_award_choice(i, view, 2, gm["Franchise 2"])      # crafted self-vote
                self.assertIn("own franchise", i.response.sent[-1][0])
                await bot.save_award_choice(FakeInteraction(f2), view, 2, gm["Franchise 4"])
                i = FakeInteraction(f3, message=post)
                await bot.open_awards_ballot(i)
                view3 = i.response.sent[-1][1]["view"]
                await bot.save_award_choice(FakeInteraction(f3), view3, 1, gm["Franchise 4"])
                await bot.save_award_choice(FakeInteraction(f3), view3, 2, gm["Franchise 2"])
                i = FakeInteraction(f2)
                await bot.save_award_choice(i, view3, 3, gm["Franchise 5"])     # someone else's ballot
                self.assertIn("Franchise 3's ballot", i.response.sent[-1][0])
                trade_view = view.again(1)
                self.assertEqual(trade_view.award.key, "trade")
                await bot.save_award_choice(FakeInteraction(f2), trade_view, 1, nominees["trade"][0].id)  # own trade: fine
                self.assertEqual(bot.store.awards_ballot(2027, "Franchise 2"),
                                 {"gm": {1: gm["Franchise 3"], 2: gm["Franchise 4"]}, "trade": {1: "trade-1"}})
                # Results wait for the close; the deadline closes it on the ticker.
                results = self.command(bot, "awards", "results")
                i = FakeInteraction(commish)
                await results.callback(i)
                self.assertIn("still open", i.response.sent[-1][0])
                clock[0] = datetime(2027, 6, 6, 4, tzinfo=UTC)                   # past 2027-06-05 23:59:59 ET
                await bot.ticker()
                self.assertEqual(bot.store.awards_season(2027)["status"], "closed")
                self.assertEqual(post.edits[-1], {"view": None})
                i = FakeInteraction(f3, message=post)
                await bot.save_award_choice(i, view3, 3, gm["Franchise 6"])
                self.assertIn("closed", i.response.edited[-1]["content"])
                i = FakeInteraction(commish)
                await results.callback(i)
                hall = as_dict(channels[HALL_CH].sent[-1].kw["embed"])
                self.assertEqual(hall["title"], "BLHA AWARDS NIGHT: THE WINNERS")
                self.assertIn("**Franchise 4** • 8 points, 1 first-place vote", json.dumps(hall, ensure_ascii=False))
                self.assertIn("2 of 12 franchises returned a ballot", hall["description"])
                export = json.loads(Path(bot.cfg.awards_export_path).read_text(encoding="utf-8"))
                gm_result = export["seasons"]["2027"]["awards"][0]
                self.assertEqual([w["nominee"] for w in gm_result["winners"]], ["Franchise 4"])
                self.assertEqual(i.followup.sent[-1][1]["file"].filename, "blha_awards.json")
                i = FakeInteraction(commish)
                await results.callback(i)
                self.assertIn("already posted", i.response.sent[-1][0])
                status = self.command(bot, "awards", "status")
                i = FakeInteraction(f2)
                await status.callback(i)
                self.assertIn("Returned (2): Franchise 2, Franchise 3", i.response.sent[-1][0])

        asyncio.run(run())

    def test_ballot_view_rows(self) -> None:
        from blha_vote.app import AwardsBallotView, AwardsPostView

        async def build():
            with tempfile.TemporaryDirectory() as tmp:
                bot, _ = self.make_bot(INFO, {}, tmp)
                nominees = {"gm": awards.gm_nominees(bot.franchises()),
                            "comeback": awards.comeback_nominees({"Franchise 2": 9}, {"Franchise 2": 1})}
                closes = datetime(2027, 6, 5, tzinfo=UTC)
                return (AwardsPostView(bot), AwardsBallotView(bot, 2027, "Franchise 2", nominees, closes),
                        AwardsBallotView(bot, 2027, "Franchise 2", nominees, closes, 1))

        post, gm, comeback = asyncio.run(build())
        self.assertEqual([c.custom_id for c in post.children], ["blha:awards:ballot"])
        self.assertTrue(post.is_persistent())
        self.assertEqual(len(gm.children), 6)  # three menus, Previous, Next, Clear
        self.assertEqual(len(comeback.children), 3)  # only its own franchise is nominated: buttons only
        self.assertIn("nothing for you to rank", comeback.content())


if __name__ == "__main__":
    unittest.main()
