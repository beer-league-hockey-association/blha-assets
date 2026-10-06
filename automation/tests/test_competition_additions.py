#!/usr/bin/env python3
"""Offline checks for goalie starts, all-play, power rankings, weekly awards and the NHL games grid.

Fantrax samples: matchup_scores_period2_test.json (live, with categories) and
league_info_2026_test.json (live week dates). NHL schedule: the synthetic
nhl_schedule_synthetic.json, built in the documented API shape (unverified).
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

AUTOMATION = Path(__file__).resolve().parents[1]
for sub in ("", "competition"):
    sys.path.insert(0, str(AUTOMATION / sub))

import desk  # noqa: E402
import render  # noqa: E402
import scoreboard  # noqa: E402
import weekly  # noqa: E402
from blha import nhl, season  # noqa: E402
from blha.fantrax import normalize_scores, normalize_standings, schedule_for  # noqa: E402
from blha.league import load_league  # noqa: E402

ET = ZoneInfo("America/New_York")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
INFO = json.loads((FIXTURES / "league_info_2026_test.json").read_text())
RAW_SCORES = json.loads((FIXTURES / "matchup_scores_period2_test.json").read_text())["response"]
RAW_STANDINGS = json.loads((FIXTURES / "standings_week0.json").read_text())
NHL = json.loads((FIXTURES / "nhl_schedule_synthetic.json").read_text())["responses"]
CTX = render.Context("Dynasty Hockey Test League", "2026-27 TEST", 0xFFB81C)


def et(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


def nhl_get(url: str) -> dict:
    return NHL.get(url.rsplit("/", 1)[1], {"gameWeek": []})


def team(tid: str, score: float) -> dict:
    return {"teamId": tid, "teamName": f"Team {tid}", "score": score, "gamesPlayed": 0.0, "categories": {}}


def week(*games: tuple[str, float, str, float]) -> list[dict]:
    return [{"away": team(a, sa), "home": team(h, sh)} for a, sa, h, sh in games]


# Four-team league, figures worked out by hand in the comments below.
W1 = week(("A", 120, "B", 100), ("C", 90, "D", 90))
W2 = week(("A", 80, "C", 110), ("B", 130, "D", 70))
W3 = week(("A", 0, "D", 0), ("B", 0, "C", 0))  # placeholder week
SEASON = {1: W1, 2: W2, 3: W3}


def synthetic_week(w: int) -> list[dict]:
    """Distinct, deterministic scores for the 12 test-league teams."""
    rows = []
    for index, pair in enumerate(schedule_for(INFO, w)):
        row = {}
        for side in ("away", "home"):
            t = pair[side]
            i = int(t["teamId"], 36) % 1000
            score = round(60 + (i * 37 + w * 53) % 97 + i * 0.001 + index * 0.0001, 4)
            row[side] = {"teamId": t["teamId"], "teamName": t["teamName"], "score": score,
                         "gamesPlayed": 10.0, "categories": {"GS": 2.0}}
        rows.append(row)
    return rows


class FakeFantrax:
    def __init__(self, counted: int) -> None:
        raw = copy.deepcopy(RAW_STANDINGS)
        for i, row in enumerate(raw):
            wins = counted // 2 + (1 if i % 2 and counted % 2 else 0)
            row["points"] = f"{wins}-{counted - wins}-0"
        self.rows = normalize_standings(raw)
        self.score_calls: list[int] = []

    def league_info(self) -> dict:
        return INFO

    def standings(self) -> list[dict]:
        return self.rows

    def matchup_scores(self, period: int) -> list[dict]:
        self.score_calls.append(period)
        return synthetic_week(period)


class MatchupCategoryTests(unittest.TestCase):
    rows = normalize_scores(RAW_SCORES)

    def test_existing_fields_unchanged(self) -> None:
        first = self.rows[0]["away"]
        self.assertEqual({k: first[k] for k in ("teamId", "teamName", "score", "gamesPlayed")},
                         {"teamId": "8j6llh6gmumuxose", "teamName": "Test 4", "score": 0.0, "gamesPlayed": 0.0})

    def test_category_values_keyed_by_short_name(self) -> None:
        test = self.rows[3]["home"]
        self.assertEqual(test["teamName"], "Test")
        self.assertEqual(test["categories"]["G"], 1.0)
        self.assertEqual(test["categories"]["SOG"], 9.0)
        self.assertEqual(test["categories"]["A"], 0.0)   # {"points": 0}: no value
        self.assertEqual(test["categories"]["GS"], 0.0)  # {}: zero
        self.assertEqual(set(test["categories"]), {"G", "A", "SOG", "Hit", "Blk", "GA", "SV", "GS"})

    def test_missing_categories_give_empty_dict(self) -> None:
        raw = {"matchups": [{"away": {"teamId": "a", "score": 1}, "home": {"teamId": "b", "score": 2}}]}
        self.assertEqual(normalize_scores(raw)[0]["away"]["categories"], {})


class GoalieStartTests(unittest.TestCase):
    def test_cap_is_four_per_calendar_week(self) -> None:
        self.assertEqual(season.goalie_start_cap(season.period(INFO, 1)), 4)   # 6.1 days
        self.assertEqual(season.goalie_start_cap(season.period(INFO, 2)), 4)   # 6.75 days
        self.assertEqual(season.goalie_start_cap(season.period(INFO, 3)), 4)   # 7.25 days

    def test_two_week_periods_get_eight(self) -> None:
        self.assertEqual(season.goalie_start_cap(season.period(INFO, 19)), 8)  # 14 days
        self.assertEqual(season.goalie_start_cap(season.period(INFO, 25)), 8)  # Championship

    def test_scoreboard_shows_starts_from_fixture(self) -> None:
        rows = normalize_scores(RAW_SCORES)
        body = render.scoreboard(CTX, season.period(INFO, 2), rows, final=False, playoffs=False, goalie_cap=4)
        values = [f["value"] for f in body["embeds"][0]["fields"]]
        self.assertEqual(len(values), 6)
        for value in values:
            self.assertEqual(value.count("Goalie starts: 0 of 4"), 2)

    def test_scoreboard_shows_used_starts(self) -> None:
        raw = copy.deepcopy(RAW_SCORES)
        gs = next(c for c in raw["matchups"][0]["categories"] if c["shortName"] == "GS")
        gs["away"] = {"display": "3", "value": 3, "points": 19.5}
        rows = normalize_scores(raw)
        body = render.scoreboard(CTX, season.period(INFO, 25), rows, final=True, playoffs=True, goalie_cap=8)
        value = body["embeds"][0]["fields"][0]["value"]
        self.assertIn("**Test 4** *(Away)* — 0.00 pts • `0 GP` • Goalie starts: 3 of 8", value)
        self.assertIn("Goalie starts: 0 of 8", value)

    def test_no_categories_no_goalie_text(self) -> None:
        rows = [{"away": {"teamId": "a", "teamName": "A", "score": 1.0, "gamesPlayed": 1},
                 "home": {"teamId": "b", "teamName": "B", "score": 2.0, "gamesPlayed": 1}}]
        body = render.scoreboard(CTX, season.period(INFO, 2), rows, final=False, playoffs=False, goalie_cap=4)
        self.assertNotIn("Goalie", body["embeds"][0]["fields"][0]["value"])

    def test_fingerprint_changes_when_a_goalie_starts(self) -> None:
        rows = normalize_scores(RAW_SCORES)
        before = scoreboard.fingerprint(2, rows, False)
        rows[0]["away"]["categories"]["GS"] = 1.0
        self.assertNotEqual(before, scoreboard.fingerprint(2, rows, False))


class AllPlayTests(unittest.TestCase):
    def test_week_all_play(self) -> None:
        ap = {k: v.text() for k, v in weekly.all_play(W1).items()}
        self.assertEqual(ap, {"A": "3-0-0", "B": "2-1-0", "C": "0-2-1", "D": "0-2-1"})

    def test_season_all_play_skips_placeholder_week(self) -> None:
        ap = {k: v.text() for k, v in weekly.season_all_play(SEASON).items()}
        self.assertEqual(ap, {"A": "4-2-0", "B": "5-1-0", "C": "2-3-1", "D": "0-5-1"})
        self.assertEqual(weekly.all_play(W3), {})

    def test_all_play_against_eleven_others(self) -> None:
        ap = weekly.all_play(synthetic_week(2))
        self.assertEqual(len(ap), 12)
        self.assertTrue(all(r.games == 11 for r in ap.values()))
        self.assertEqual(sum(r.wins for r in ap.values()), 66)  # 12 choose 2, no ties

    def test_recap_shows_week_and_season_all_play(self) -> None:
        body = render.recap(CTX, season.period(INFO, 2), W2, all_play_week=weekly.all_play(W2),
                            all_play_season=weekly.season_all_play(SEASON))
        embed = body["embeds"][0]
        field = embed["fields"][-1]
        self.assertEqual(field["name"], "All-Play")
        self.assertEqual(field["value"].splitlines()[0], "**Team B** — 3-0-0 • Season 5-1-0")
        self.assertIn("all 3 other teams", embed["description"])
        self.assertEqual(len(embed["fields"]), 3)  # 2 matchups + all-play


class PowerRankingTests(unittest.TestCase):
    def test_formula_by_hand(self) -> None:
        # PF A 200, B 230, C 200, D 160 -> scaled 0.571, 1, 0.571, 0 (same for the last 3 weeks).
        # All-play % A 4/6, B 5/6, C 2.5/6, D 0.5/6.
        rows = weekly.power_rankings(SEASON)
        self.assertEqual([r.team_id for r in rows], ["B", "A", "C", "D"])
        expected = {"A": 0.8 * 40 / 70 + 0.2 * 4 / 6, "B": 0.8 + 0.2 * 5 / 6,
                    "C": 0.8 * 40 / 70 + 0.2 * 2.5 / 6, "D": 0.2 * 0.5 / 6}
        for row in rows:
            self.assertAlmostEqual(row.score, expected[row.team_id], places=5)
        self.assertEqual(rows[0].record.text(), "1-1-0")
        self.assertEqual(rows[2].record.text(), "1-0-1")

    def test_recent_form_counts(self) -> None:
        # Last week only: A 80, B 130, C 110, D 70 -> C passes A.
        rows = weekly.power_rankings(SEASON, recent=1)
        self.assertEqual([r.team_id for r in rows], ["B", "C", "A", "D"])

    def test_change_since_last_week(self) -> None:
        rows = weekly.power_rankings(SEASON, {"A": 1, "B": 2, "C": 3})
        change = {r.team_id: r.change for r in rows}
        self.assertEqual(change, {"B": 1, "A": -1, "C": 0, "D": None})
        body = render.power_rankings(CTX, 2, rows, has_previous=True)
        values = [f["value"] for f in body["embeds"][0]["fields"]]
        self.assertTrue(values[0].startswith("**Change:** Up 1 • **Record:** 1-1-0 • **PF:** 230.00"))
        self.assertIn("**Change:** Down 1", values[1])
        self.assertIn("**Change:** Same", values[2])
        self.assertIn("**Change:** New", values[3])

    def test_first_rankings_have_no_change(self) -> None:
        body = render.power_rankings(CTX, 1, weekly.power_rankings({1: W1}), has_previous=False)
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "BLHA Power Rankings — After Week 1")
        self.assertIn("**Change:** —", embed["fields"][0]["value"])
        self.assertIn("50% season points-for", embed["description"])

    def test_no_results_no_post(self) -> None:
        self.assertEqual(weekly.power_rankings({3: W3}), [])
        self.assertIsNone(render.power_rankings(CTX, 3, [], has_previous=False))


class AwardTests(unittest.TestCase):
    def test_week_one(self) -> None:
        a = weekly.weekly_awards(W1)
        self.assertEqual([t["teamId"] for t in a.stars], ["A", "B", "C"])
        self.assertEqual(a.tough_luck.loser["teamId"], "B")
        self.assertEqual(a.lucky_win.winner["teamId"], "A")
        self.assertEqual(a.closest.margin, 0)  # the C-D tie
        self.assertEqual(a.blowout.margin, 20)

    def test_week_two(self) -> None:
        a = weekly.weekly_awards(W2)
        self.assertEqual([t["teamId"] for t in a.stars], ["B", "C", "A"])
        self.assertEqual(a.tough_luck.loser["teamId"], "A")   # 80 in a loss
        self.assertEqual(a.lucky_win.winner["teamId"], "C")   # won with 110
        self.assertEqual((a.closest.winner["teamId"], a.closest.margin), ("C", 30))
        self.assertEqual((a.blowout.winner["teamId"], a.blowout.margin), ("B", 60))

    def test_placeholder_week_has_no_awards(self) -> None:
        self.assertTrue(weekly.weekly_awards(W3).empty)
        self.assertIsNone(render.awards(CTX, season.period(INFO, 3), weekly.weekly_awards(W3)))

    def test_zero_zero_matchups_ignored(self) -> None:
        rows = W2 + week(("E", 0, "F", 0))
        a = weekly.weekly_awards(rows)
        self.assertEqual(a.closest.margin, 30)
        self.assertEqual(len(a.stars), 3)

    def test_live_fixture_mid_week(self) -> None:
        a = weekly.weekly_awards(normalize_scores(RAW_SCORES))
        self.assertEqual([t["teamName"] for t in a.stars], ["Test"])  # nobody else has scored
        self.assertEqual(a.closest.winner["teamName"], "Test")

    def test_awards_post(self) -> None:
        body = render.awards(CTX, season.period(INFO, 2), weekly.weekly_awards(W2))
        fields = {f["name"]: f["value"] for f in body["embeds"][0]["fields"]}
        self.assertEqual(list(fields), ["First Star", "Second Star", "Third Star", "Tough Luck", "Lucky Win",
                                        "Closest Game", "Biggest Blowout"])
        self.assertEqual(fields["First Star"], "**Team B** — 130.00 pts")
        self.assertEqual(fields["Tough Luck"], "**Team A** — 80.00 pts in a loss to Team C (110.00)")
        self.assertEqual(fields["Lucky Win"], "**Team C** — 110.00 pts in a win over Team A (80.00)")
        self.assertEqual(fields["Biggest Blowout"], "**Team B** 130.00 – Team D 70.00 • 60.00-point margin")
        self.assertEqual(body["embeds"][0]["title"], "BLHA Week 2 Awards")
        self.assertEqual(body["username"], "BLHA Competition Desk")


class NhlScheduleTests(unittest.TestCase):
    p3 = season.period(INFO, 3)  # Mon Oct 12 1:00 PM ET -> Mon Oct 19 6:59 PM ET

    def games(self) -> list:
        calls: list[str] = []

        def get(url: str) -> dict:
            calls.append(url)
            return nhl_get(url)

        found = nhl.fetch_schedule(self.p3.start.astimezone(ET).date(), self.p3.end.astimezone(ET).date(), ET, get)
        self.calls = calls
        return found

    def test_fetches_each_seven_day_block_the_week_spans(self) -> None:
        self.games()
        self.assertEqual(self.calls, ["https://api-web.nhle.com/v1/schedule/2026-10-12",
                                      "https://api-web.nhle.com/v1/schedule/2026-10-19"])

    def test_parser_reads_documented_shape(self) -> None:
        games = nhl.parse_schedule(NHL["2026-10-12"], ET)
        self.assertEqual(len(games), 47)  # Oct 12-18, incl. one preseason game
        uta = next(g for g in games if g.home == "SJS" and g.away == "UTA")  # {"default": "UTA"}
        self.assertEqual(uta.night.isoformat(), "2026-10-14")  # 10:30 PM ET, not the UTC date
        self.assertEqual(sum(1 for g in games if g.game_type != nhl.REGULAR_SEASON), 1)

    def test_grid(self) -> None:
        grid = nhl.week_grid(self.games(), self.p3.start, self.p3.end, ET)
        # The noon game Mon Oct 12 belongs to Week 2 and the Oct 19 7 PM game to Week 4.
        self.assertEqual(grid.total_games, 45)
        groups = dict(grid.by_count())
        self.assertEqual(groups[4], ["CHI"])
        self.assertEqual(groups[2], ["CGY", "NSH", "OTT", "SJS", "TOR", "UTA", "VAN"])
        self.assertEqual(sum(len(t) for t in groups.values()), 32)
        self.assertEqual(sorted(grid.back_to_backs), ["CHI", "EDM", "LAK", "MTL", "NYR"])
        self.assertEqual([(n.isoformat(), t) for n, t in grid.light_nights],
                         [("2026-10-12", 4), ("2026-10-14", 6), ("2026-10-16", 8)])
        self.assertEqual([(n.isoformat(), t) for n, t in grid.heavy_nights],
                         [("2026-10-13", 22), ("2026-10-17", 24)])

    def test_team_with_no_games_listed(self) -> None:
        games = [g for g in self.games() if "CHI" not in g.teams or g.night.day < 13]
        games += [nhl.Game("x", self.p3.start.astimezone(ET).date().replace(day=21), None, "CHI", "STL", 2)]
        grid = nhl.week_grid(games, self.p3.start, self.p3.end, ET)
        self.assertEqual(dict(grid.by_count())[0], ["CHI"])

    def test_grid_post(self) -> None:
        grid = nhl.week_grid(self.games(), self.p3.start, self.p3.end, ET)
        body = render.games_grid(CTX, self.p3, grid)
        embed = body["embeds"][0]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(embed["title"], "BLHA Week 3 NHL Games Grid")
        self.assertEqual(fields["4 Games"], "CHI")
        self.assertIn("**EDM:** Oct 16–17", fields["Back-to-Backs"])
        self.assertIn("Wed Oct 14 — 3 games, 6 teams", fields["Light Nights (8 or fewer teams)"])
        self.assertIn("Sat Oct 17 — 12 games, 24 teams", fields["Heavy Nights (20 or more teams)"])
        self.assertEqual(embed["footer"]["text"], "NHL GAMES GRID • NHL SCHEDULE DATA")
        self.assertNotIn("FANTRAX", embed["footer"]["text"])


class DeskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "competition.json"
        patcher = patch.object(desk, "STATE_PATH", self.state_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load_league()

    def make(self, counted: int, saved: dict | None = None, test: bool = False) -> desk.Desk:
        return desk.Desk(self.cfg, test=test, fx=FakeFantrax(counted), saved_state=saved or {}, nhl_get=nhl_get)

    def live(self, d: desk.Desk, now: datetime) -> list[tuple[str, str]]:
        sent: list[tuple[str, str]] = []

        def fake_send(secret: str, payload: dict):
            sent.append((secret, payload["embeds"][0]["title"]))
            return True, "delivered", "1"

        with patch.object(desk, "send_discord_webhook", fake_send), redirect_stdout(io.StringIO()):
            self.assertEqual(desk.run("live", list(desk.ITEMS), None, False, desk=d, now=now), 0)
        return sent

    def test_new_webhooks_follow_their_channels(self) -> None:
        d = self.make(0)
        self.assertEqual(d.webhook("awards"), d.webhook("recap"))
        self.assertEqual(d.webhook("rankings"), "BLHA_WEBHOOK_WEEKLY_RECAP")
        self.assertEqual(d.webhook("games"), "BLHA_WEBHOOK_SCOREBOARD")

    def test_season_to_date_reads_every_final_week(self) -> None:
        d = self.make(3)
        body = d.build("recap", 3, et(2026, 10, 19, 8))
        self.assertEqual(sorted(d.fx.score_calls), [1, 2, 3])
        value = body["embeds"][0]["fields"][-1]["value"]
        self.assertEqual(len(value.splitlines()), 12)
        self.assertIn("• Season ", value)

    def test_monday_live_run_after_deploy(self) -> None:
        # State saved before this change: only the original four keys.
        self.state_path.write_text(json.dumps({"recap_week": 1, "standings_week": 1, "preview_week": 2}))
        sent = self.live(self.make(2), et(2026, 10, 12, 8))
        self.assertEqual(sent, [
            ("BLHA_WEBHOOK_WEEKLY_RECAP", "BLHA Week 2 Recap"),
            ("BLHA_WEBHOOK_WEEKLY_RECAP", "BLHA Week 2 Awards"),
            ("BLHA_WEBHOOK_WEEKLY_RECAP", "BLHA Power Rankings — After Week 2"),
            ("BLHA_WEBHOOK_STANDINGS", "BLHA League Standings — After Week 2"),
            ("BLHA_WEBHOOK_SCOREBOARD", "BLHA Week 3 Matchup Preview"),
            ("BLHA_WEBHOOK_SCOREBOARD", "BLHA Week 3 NHL Games Grid"),
        ])
        state = json.loads(self.state_path.read_text())
        self.assertEqual((state["awards_week"], state["rankings_week"], state["games_week"]), (2, 2, 3))
        self.assertEqual(sorted(state["power_ranks"]), ["2"])
        self.assertEqual(sorted(state["power_ranks"]["2"].values()), list(range(1, 13)))
        # Nothing repeats on the evening check.
        self.assertEqual(self.live(self.make(2, state), et(2026, 10, 12, 20)), [])

    def test_mid_week_deploy_posts_nothing_old(self) -> None:
        self.state_path.write_text(json.dumps({"recap_week": 2, "standings_week": 2, "preview_week": 3}))
        self.assertEqual(self.live(self.make(2), et(2026, 10, 14, 20)), [])

    def test_rank_change_uses_saved_ranks(self) -> None:
        self.state_path.write_text(json.dumps({"recap_week": 1, "standings_week": 1, "preview_week": 2}))
        self.live(self.make(2), et(2026, 10, 12, 8))
        state = json.loads(self.state_path.read_text())
        d = self.make(3, state)
        body = d.build("rankings", 3, et(2026, 10, 19, 8))
        rows = weekly.power_rankings(d.season_weeks(3), state["power_ranks"]["2"])
        for field, row in zip(body["embeds"][0]["fields"], rows):
            self.assertNotIn("New", field["value"])
            self.assertIn(f"**Change:** {render._change(row, True)}", field["value"])

    def test_previous_ranks_recomputed_without_state(self) -> None:
        d = self.make(3)
        self.assertEqual(d.previous_ranks(3), weekly.ranks_of(weekly.power_rankings(d.season_weeks(2))))
        self.assertEqual(d.previous_ranks(1), {})

    def test_remember_ranks_keeps_recent_weeks(self) -> None:
        state: dict = {}
        for w in range(1, 7):
            desk.remember_ranks(state, w, {"a": w})
        self.assertEqual(sorted(state["power_ranks"], key=int), ["3", "4", "5", "6"])

    def test_preview_and_test_modes_build_every_item(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(desk.run("preview", list(desk.ITEMS), 3, False, desk=self.make(3)), 0)
        text = out.getvalue()
        for item in desk.ITEMS:
            self.assertIn(f"PREVIEW {item} week 3", text)

        sent: list[str] = []
        with patch.object(desk, "send_discord_webhook", lambda s, p: (sent.append(p["embeds"][0]["title"]) or
                                                                      (True, "delivered", "1"))), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(desk.run("test", ["awards", "rankings", "games"], 3, False,
                                      desk=self.make(3, test=True)), 0)
        self.assertEqual(sent, ["[TEST] BLHA Week 3 Awards", "[TEST] BLHA Power Rankings — After Week 3",
                                "[TEST] BLHA Week 3 NHL Games Grid"])
        self.assertFalse(self.state_path.exists())

    def test_week_without_regular_season_games_is_skipped(self) -> None:
        d = self.make(1)
        # Week 2 data holds only the noon game on Oct 12 (before Week 3 begins).
        self.assertEqual(d.build("games", 2, et(2026, 10, 5, 8))["embeds"][0]["description"].count("(1 game)"), 1)
        empty = desk.Desk(self.cfg, fx=FakeFantrax(1), saved_state={},
                          nhl_get=lambda url: {"gameWeek": [{"date": "2026-10-05", "games": [
                              {"id": 1, "gameType": 1, "startTimeUTC": "2026-10-05T23:00:00Z",
                               "awayTeam": {"abbrev": "BOS"}, "homeTeam": {"abbrev": "TOR"}}]}]})
        self.assertIsNone(empty.build("games", 2, et(2026, 10, 5, 8)))

    def test_empty_nhl_response_is_an_error(self) -> None:
        d = desk.Desk(self.cfg, fx=FakeFantrax(1), saved_state={}, nhl_get=lambda url: {})
        with self.assertRaises(ValueError):
            d.build("games", 2, et(2026, 10, 5, 8))


if __name__ == "__main__":
    unittest.main()
