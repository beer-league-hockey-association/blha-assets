#!/usr/bin/env python3
"""Offline checks for the Trade Desk: detection, report card and poll, revisits, deadline-day tracker."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
AUTOMATION = HERE.parent
for folder in (AUTOMATION, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import trade_detect as td  # noqa: E402
import trade_points as tp  # noqa: E402
import trade_render as tr  # noqa: E402
import tradedesk  # noqa: E402
from blha import schedule as sched  # noqa: E402
from blha import season as cal  # noqa: E402

NY = ZoneInfo("America/New_York")
FIXTURES = AUTOMATION / "tests" / "fixtures"
INFO = json.loads((FIXTURES / "league_info_2026_test.json").read_text(encoding="utf-8"))
CFG = {"league_id": "L1", "season_label": "2026-27 TEST", "timezone": "America/New_York", "color": 0xFFB81C}
NAMES = {"a": "Test 1", "b": "Test 2", "c": "Test 3"}
SECRETS = {"BLHA_WEBHOOK_TRADE_DISCUSSION": "https://discord.example/api/webhooks/1/x",
           "BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS": "https://discord.example/api/webhooks/2/y"}


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NY).astimezone(timezone.utc)


def rosters_raw(teams: dict[str, list[str]]) -> dict:
    return {"rosters": {t: {"teamName": NAMES.get(t, t), "rosterItems": [{"id": p, "status": "ACTIVE"} for p in ps]}
                        for t, ps in teams.items()}}


def picks_raw(owners: dict[tuple[int, int, str], str]) -> dict:
    return {"futureDraftPicks": [{"year": y, "round": r, "originalOwnerTeamId": o, "currentOwnerTeamId": c}
                                 for (y, r, o), c in owners.items()]}


BASE_TEAMS = {"a": ["p1", "p2", "p3"], "b": ["p4", "p5", "p6"], "c": ["p7", "p8"]}
BASE_PICKS = {(2028, 1, "a"): "a", (2028, 1, "b"): "b", (2029, 2, "c"): "c"}
PLAYER_IDS = {"p1": {"name": "McDavid, Connor", "position": "C", "team": "EDM"},
              "p4": {"name": "Hyman, Zach", "position": "RW", "team": "EDM"},
              "p5": {"name": "Shesterkin, Igor", "position": "G", "team": "NYR"}}


class FakeFantrax:
    """Serves a queue of (rosters, picks) readings; the last one repeats."""

    def __init__(self, readings: list[tuple[dict, dict]], info: dict | None = None) -> None:
        self.readings = list(readings)
        self.info = info or INFO
        self.reads = 0
        self._picks: dict | None = None

    def league_info(self) -> dict:
        return self.info

    def rosters(self) -> dict:
        teams, picks = self.readings[min(self.reads, len(self.readings) - 1)]
        self.reads += 1
        self._picks = picks
        return rosters_raw(teams)

    def draft_picks(self) -> dict:
        return picks_raw(self._picks)

    def player_ids(self) -> dict:
        return PLAYER_IDS


def quiet(fn, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class Discord:
    """Records webhook calls instead of sending them."""

    def __init__(self, poll_400: bool = False) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.upserts: list[tuple[str, dict, str | None]] = []
        self.poll_400 = poll_400
        self.next_id = 100
        self.message = None

    def send(self, secret_name: str, payload: dict):
        if not os.environ.get(secret_name):
            return False, f"missing GitHub Actions secret {secret_name}", None
        if self.poll_400 and "poll" in payload:
            return False, "Discord returned 400: {\"poll\": [\"Invalid\"]}", None
        self.sent.append((secret_name, payload))
        self.next_id += 1
        return True, "delivered", str(self.next_id)

    def upsert(self, secret_name: str, payload: dict, message_id: str | None):
        self.upserts.append((secret_name, payload, message_id))
        if message_id:
            return True, "delivered", message_id, "edited"
        self.next_id += 1
        return True, "delivered", str(self.next_id), "posted"

    def get_message(self, secret_name: str, message_id: str):
        return (True, "ok", self.message) if self.message else (False, "Discord returned 404", None)

    def get_webhook(self, secret_name: str):
        return True, "ok", {"guild_id": "9", "channel_id": "8"}

    def patches(self):
        return [patch.object(tradedesk.dw, "send_discord_webhook", self.send),
                patch.object(tradedesk.dw, "upsert_discord_message", self.upsert),
                patch.object(tradedesk.dw, "get_discord_message", self.get_message),
                patch.object(tradedesk.dw, "get_webhook", self.get_webhook)]


@contextlib.contextmanager
def discord(fake: Discord, env: dict[str, str] | None = None):
    with contextlib.ExitStack() as stack:
        for p in fake.patches():
            stack.enter_context(p)
        clean = {k: v for k, v in os.environ.items() if k not in SECRETS}
        stack.enter_context(patch.dict(os.environ, {**clean, **(SECRETS if env is None else env)}, clear=True))
        yield fake


def no_sleep(_: float) -> None:
    return None


# --- detection --------------------------------------------------------------------

class DetectionTests(unittest.TestCase):
    def snap(self, teams, picks=BASE_PICKS):
        raw = rosters_raw(teams)
        return td.roster_snapshot(raw), td.picktrades.snapshot(picks_raw(picks))

    def test_players_both_ways_are_one_trade(self):
        prev_r, prev_p = self.snap(BASE_TEAMS)
        cur_r, cur_p = self.snap({"a": ["p2", "p3", "p4"], "b": ["p1", "p5", "p6"], "c": ["p7", "p8"]})
        trades = td.detect(prev_r, cur_r, prev_p, cur_p)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["teams"], ["a", "b"])
        self.assertEqual(trades[0]["received"], {"a": ["player:p4"], "b": ["player:p1"]})
        self.assertNotIn("one_sided", trades[0])

    def test_picks_moving_in_the_same_window_join_the_trade(self):
        prev_r, prev_p = self.snap(BASE_TEAMS)
        cur_r, cur_p = self.snap({"a": ["p2", "p3"], "b": ["p1", "p4", "p5", "p6"], "c": ["p7", "p8"]},
                                 {**BASE_PICKS, (2028, 1, "b"): "a"})
        trades = td.detect(prev_r, cur_r, prev_p, cur_p)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["received"], {"a": ["pick:2028|1|b"], "b": ["player:p1"]})

    def test_three_team_trade_is_one_trade_and_separate_trades_stay_apart(self):
        prev_r, prev_p = self.snap({**BASE_TEAMS, "d": ["p9"], "e": ["p10"]})
        cur_r, cur_p = self.snap({"a": ["p2", "p3", "p7"], "b": ["p1", "p5", "p6"], "c": ["p4", "p8"],
                                  "d": ["p10"], "e": ["p9"]})
        trades = td.detect(prev_r, cur_r, prev_p, cur_p)
        self.assertEqual([t["teams"] for t in trades], [["a", "b", "c"], ["d", "e"]])

    def test_free_agent_adds_and_drops_are_ignored(self):
        prev_r, prev_p = self.snap(BASE_TEAMS)
        cur_r, cur_p = self.snap({"a": ["p1", "p2", "p99"], "b": ["p4", "p5", "p6"], "c": ["p7", "p8"]})
        self.assertEqual(td.detect(prev_r, cur_r, prev_p, cur_p), [])

    def test_status_changes_and_new_pick_years_are_not_trades(self):
        prev_r, prev_p = self.snap(BASE_TEAMS)
        raw = rosters_raw(BASE_TEAMS)
        raw["rosters"]["a"]["rosterItems"][0]["status"] = "MINORS"
        cur_p = td.picktrades.snapshot(picks_raw({**BASE_PICKS, (2031, 1, "a"): "a"}))
        self.assertEqual(td.detect(prev_r, td.roster_snapshot(raw), prev_p, cur_p), [])

    def test_player_for_nothing_visible_is_kept_and_flagged_one_sided(self):
        prev_r, prev_p = self.snap(BASE_TEAMS)
        cur_r, cur_p = self.snap({"a": ["p2", "p3"], "b": ["p1", "p4", "p5", "p6"], "c": ["p7", "p8"]})
        trades = td.detect(prev_r, cur_r, prev_p, cur_p)
        self.assertTrue(trades[0]["one_sided"])
        text = tr.side_text({**trades[0], "names": NAMES}, "a")
        self.assertIn("FAAB", text)

    def test_incomplete_fantrax_answer_raises_instead_of_reporting(self):
        big = {t: [f"{t}{i}" for i in range(10)] for t in "abcd"}
        prev = td.roster_snapshot(rosters_raw(big))
        cur = td.roster_snapshot(rosters_raw({"a": big["a"], "b": [], "c": [], "d": []}))
        with self.assertRaises(td.SnapshotError):
            td.detect(prev, cur, None, None)

    def test_exact_undo_within_two_weeks_is_a_reversal(self):
        now = ny(2027, 1, 10, 12, 0)
        old = {"id": "t1", "at": (now - timedelta(days=2)).isoformat(), "teams": ["a", "b"],
               "received": {"a": ["player:p4"], "b": ["pick:2028|1|a", "player:p1"]},
               "sent": {"a": ["pick:2028|1|a", "player:p1"], "b": ["player:p4"]}}
        undo = {"teams": ["a", "b"], "received": {"a": ["pick:2028|1|a", "player:p1"], "b": ["player:p4"]}}
        self.assertIs(td.reversal_of(undo, [old], now), old)
        self.assertIsNone(td.reversal_of(undo, [old], now + timedelta(days=20)))
        other = {"teams": ["a", "b"], "received": {"a": ["player:p1"], "b": ["player:p4"]}}
        self.assertIsNone(td.reversal_of(other, [old], now))


# --- report card and poll --------------------------------------------------------------

def card_trade() -> dict:
    return {"id": "x", "at": ny(2027, 1, 15, 14, 30).isoformat(), "teams": ["a", "b"], "names": NAMES,
            "received": {"a": ["pick:2028|1|c", "player:p4"], "b": ["player:p1"]},
            "sent": {"a": ["player:p1"], "b": ["pick:2028|1|c", "player:p4"]},
            "players": {"p1": PLAYER_IDS["p1"], "p4": PLAYER_IDS["p4"]}}


class ReportCardTests(unittest.TestCase):
    def test_poll_payload_shape(self):
        payload = tr.report_card(card_trade(), CFG)
        poll = payload["poll"]
        self.assertEqual(poll["question"], {"text": "Who won the trade?"})
        self.assertEqual([a["poll_media"]["text"] for a in poll["answers"]], ["Test 1", "Test 2", "Even"])
        self.assertEqual(poll["duration"], 72)
        self.assertIs(poll["allow_multiselect"], False)
        self.assertEqual(poll["layout_type"], 1)
        self.assertEqual(set(poll), {"question", "answers", "duration", "allow_multiselect", "layout_type"})
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_embed_lists_each_side_and_footer_says_the_vote_is_for_fun(self):
        embed = tr.report_card(card_trade(), CFG)["embeds"][0]
        self.assertEqual(embed["title"], "TRADE REPORT CARD")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields["TEST 1 RECEIVES"], "Zach Hyman (RW, EDM)\n2028 1st round pick (Test 3)")
        self.assertEqual(fields["TEST 2 RECEIVES"], "Connor McDavid (C, EDM)")
        footer = embed["footer"]["text"]
        self.assertIn("JUST FOR FUN", footer)
        self.assertIn("NEVER AFFECTS THE TRADE", footer)
        self.assertIn("ARTICLE XI", footer)
        self.assertIn("🚨│completed-trades", embed["description"])
        self.assertNotIn("image", embed)  # text and links only

    def test_long_names_and_many_teams_fit_discord_poll_limits(self):
        t = card_trade()
        t["teams"] = [str(i) for i in range(12)]
        t["names"] = {str(i): "X" * 80 for i in range(12)}
        poll = tr.poll(t)
        self.assertEqual(len(poll["answers"]), 10)
        self.assertTrue(all(len(a["poll_media"]["text"]) <= 55 for a in poll["answers"]))
        self.assertEqual(poll["answers"][-1]["poll_media"]["text"], "Even")

    def test_poll_results_read_back(self):
        message = {"poll": {"answers": [{"answer_id": 1, "poll_media": {"text": "Test 1"}},
                                        {"answer_id": 2, "poll_media": {"text": "Test 2"}},
                                        {"answer_id": 3, "poll_media": {"text": "Even"}}],
                            "results": {"is_finalized": True,
                                        "answer_counts": [{"id": 1, "count": 4, "me_voted": False},
                                                          {"id": 3, "count": 1, "me_voted": False}]}}}
        tally = tr.poll_tally(message)
        self.assertEqual(tally, {"answers": [("Test 1", 4), ("Test 2", 0), ("Even", 1)], "total": 5, "final": True})
        self.assertEqual(tr.tally_text(tally), "Test 1: 4 votes\nTest 2: 0 votes\nEven: 1 vote")
        self.assertIsNone(tr.poll_tally({"embeds": []}))


# --- revisits: scoring -------------------------------------------------------------------

class FakeNhl:
    """Search, game logs and boxscores in the NHL API's public shape (fixtures, no network)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.logs = {
            (8478402, 20262027): [
                {"gameId": 2026020500, "gameDate": "2027-01-15", "goals": 3, "assists": 0, "shots": 9, "pim": 0},
                {"gameId": 2026020600, "gameDate": "2027-01-16", "goals": 1, "assists": 2, "shots": 5, "pim": 2},
                {"gameId": 2026020700, "gameDate": "2027-03-01", "goals": 0, "assists": 1, "shots": 2, "pim": 0},
            ],
            (8478402, 20272028): [
                {"gameId": 2027020010, "gameDate": "2027-10-10", "goals": 1, "assists": 0, "shots": 3, "pim": 0},
                {"gameId": 2027020900, "gameDate": "2028-02-01", "goals": 4, "assists": 4, "shots": 9, "pim": 0},
            ],
            (8478048, 20262027): [
                {"gameId": 2026020601, "gameDate": "2027-01-17", "gamesStarted": 1, "shotsAgainst": 30,
                 "goalsAgainst": 2, "goals": 0, "assists": 0, "pim": 0},
                {"gameId": 2026020602, "gameDate": "2027-01-19", "gamesStarted": 1, "shotsAgainst": 30,
                 "goalsAgainst": 0, "goals": 0, "assists": 1, "pim": 0},
            ],
        }
        self.boxes = {
            "2026020600": {"playerByGameStats": {"awayTeam": {"forwards": [{"playerId": 8478402, "hits": 3, "blockedShots": 1}]},
                                                 "homeTeam": {"defense": [], "goalies": []}}},
            "2026020700": {"playerByGameStats": {"homeTeam": {"forwards": [{"playerId": 8478402, "hits": 0, "blockedShots": 2}]}}},
            "2027020010": {"playerByGameStats": {"homeTeam": {"forwards": [{"playerId": 8478402, "hits": 1, "blockedShots": 0}]}}},
        }
        self.search = {
            "Connor McDavid": [{"playerId": "8478402", "name": "Connor McDavid", "positionCode": "C", "teamAbbrev": "EDM"}],
            "Igor Shesterkin": [{"playerId": "8478048", "name": "Igor Shesterkin", "positionCode": "G", "teamAbbrev": "NYR"}],
            "Elias Pettersson": [{"playerId": "8480012", "name": "Elias Pettersson", "positionCode": "C", "teamAbbrev": "VAN"},
                                 {"playerId": "8483678", "name": "Elias Pettersson", "positionCode": "D", "teamAbbrev": "VAN"}],
            "Sebastian Aho": [{"playerId": "8478427", "name": "Sebastian Aho", "positionCode": "C", "teamAbbrev": "CAR"},
                              {"playerId": "8480222", "name": "Sebastian Aho", "positionCode": "D", "teamAbbrev": "PIT"}],
        }

    def get(self, url: str, **params):
        self.calls.append(url)
        if url == tp.SEARCH:
            return self.search.get(params["q"], [])
        if "/game-log/" in url:
            parts = url.split("/")
            return {"gameLog": self.logs.get((int(parts[-4]), int(parts[-2])), [])}
        if url.endswith("/boxscore"):
            game = url.split("/")[-2]
            if game not in self.boxes:
                raise RuntimeError("HTTP 500")
            return self.boxes[game]
        return None


class ScoringTests(unittest.TestCase):
    def test_values_come_from_the_constitution(self):
        self.assertEqual(tp.SKATER, {"goals": 5.0, "assists": 2.95, "shots": 0.55, "blockedShots": 0.35,
                                     "hits": 0.20, "pim": -0.54})
        self.assertEqual(tp.GOALIE, {"gamesStarted": 6.5, "saves": 0.49, "goalsAgainst": -5.0, "goals": 5.0,
                                     "assists": 2.95})

    def test_skater_game_math(self):
        row = {"goals": 1, "assists": 2, "shots": 5, "pim": 2, "hits": 3, "blockedShots": 1}
        # 5 + 5.90 + 2.75 - 1.08 + 0.60 + 0.35
        self.assertAlmostEqual(tp.game_points(row, False), 13.52, places=6)

    def test_goalie_game_math_matches_the_scoring_explainer(self):
        # "28 saves on 30 shots -> +10.22" and "30-save shutout -> +21.20" (16_scoring_explained.json)
        self.assertAlmostEqual(tp.game_points({"gamesStarted": 1, "shotsAgainst": 30, "goalsAgainst": 2}, True), 10.22, places=6)
        self.assertAlmostEqual(tp.game_points({"gamesStarted": 1, "shotsAgainst": 30, "goalsAgainst": 0}, True), 21.20, places=6)

    def test_nhl_seasons(self):
        self.assertEqual(tp.nhl_season(date(2027, 1, 15)), 20262027)
        self.assertEqual(tp.nhl_season(date(2027, 10, 1)), 20272028)
        self.assertEqual(tp.seasons_between(date(2027, 1, 15), date(2028, 1, 15)), [20262027, 20272028])

    def test_production_counts_games_after_the_trade_day_through_the_revisit_day_across_seasons(self):
        nhl = FakeNhl()
        stats = tp.NhlStats(nhl.get)
        prod = stats.production(8478402, False, date(2027, 1, 15), date(2028, 1, 15))
        # Jan 15 is the trade day (not counted); Feb 1 2028 is after the revisit (not counted).
        g16 = 5 + 2 * 2.95 + 5 * 0.55 - 2 * 0.54 + 3 * 0.20 + 1 * 0.35
        m01 = 2.95 + 2 * 0.55 + 2 * 0.35
        o10 = 5 + 3 * 0.55 + 0.20
        self.assertEqual(prod.games, 3)
        self.assertAlmostEqual(prod.points, round(g16 + m01 + o10, 2), places=6)
        self.assertEqual(prod.missing_box, 0)
        self.assertTrue(any("20272028" in c for c in nhl.calls))

    def test_unreadable_boxscore_only_loses_hits_and_blocks(self):
        nhl = FakeNhl()
        del nhl.boxes["2027020010"]
        prod = tp.NhlStats(nhl.get).production(8478402, False, date(2027, 1, 15), date(2028, 1, 15))
        self.assertEqual(prod.missing_box, 1)
        self.assertEqual(prod.games, 3)

    def test_goalie_production(self):
        prod = tp.NhlStats(FakeNhl().get).production(8478048, True, date(2027, 1, 15), date(2027, 7, 15))
        self.assertEqual(prod.games, 2)
        self.assertAlmostEqual(prod.points, round(10.22 + 21.20 + 2.95, 2), places=6)
        self.assertTrue(prod.goalie)

    def test_nhl_id_matching_uses_team_and_position_and_refuses_to_guess(self):
        stats = tp.NhlStats(FakeNhl().get)
        self.assertEqual(stats.find_id("McDavid, Connor", "EDM", "C"), 8478402)
        self.assertEqual(stats.find_id("Pettersson, Elias", "VAN", "D"), 8483678)
        self.assertEqual(stats.find_id("Aho, Sebastian", "CAR", "C"), 8478427)
        self.assertIsNone(stats.find_id("Pettersson, Elias", "VAN", ""))
        self.assertIsNone(stats.find_id("Nobody, Real", "TOR", "C"))


# --- revisits: timing and message ----------------------------------------------------------

class FakeHistory:
    def __init__(self, drafts: dict[int, dict] | None = None, selections: dict | None = None) -> None:
        self._drafts = drafts or {}
        self._sel = selections or {}

    def drafts(self):
        return self._drafts

    def pick_selection(self, key):
        return self._sel.get(key)

    def player_name(self, pid):
        return {"z9": "Gavin McKenna"}.get(pid, pid)


class RevisitTests(unittest.TestCase):
    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(tradedesk.add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(tradedesk.add_months(date(2027, 8, 31), 6), date(2028, 2, 29))
        self.assertEqual(tradedesk.add_months(date(2027, 1, 15), 12), date(2028, 1, 15))

    def test_due_at_noon_local_six_and_twelve_months_later(self):
        t = card_trade()
        self.assertEqual(tradedesk.revisit_due(t, 6, NY), ny(2027, 7, 15, 12, 0))
        self.assertEqual(tradedesk.revisit_due(t, 12, NY), ny(2028, 1, 15, 12, 0))

    def test_pick_text(self):
        t = card_trade()
        hist = FakeHistory()
        self.assertEqual(tradedesk.pick_text(t, "pick:2028|1|c", hist, date(2027, 7, 15)),
                         "2028 1st, originally Test 3's (not yet used)")
        own = {**t, "sent": {"b": ["pick:2028|1|b"]}}
        self.assertEqual(tradedesk.pick_text(own, "pick:2028|1|b", hist, date(2027, 7, 15)), "2028 1st (not yet used)")
        drafted = FakeHistory({2028: {}}, {"2028|1|c": {"round": 1, "in_round": 3, "player": "z9"}})
        self.assertEqual(tradedesk.pick_text(t, "pick:2028|1|c", drafted, date(2029, 1, 15)),
                         "2028 1st, originally Test 3's: Gavin McKenna (1.03)")

    def run_revisit(self, trade_overrides=None, message=None, now=None):
        state = {"trades": [{**card_trade(), "players": {"p1": dict(PLAYER_IDS["p1"]), "p4": dict(PLAYER_IDS["p4"])},
                             "card": "posted", "message_id": "55", "poll": True, "revisits": {},
                             "league_id": "L1", "season": 2026, "test": True, **(trade_overrides or {})}]}
        fake = Discord()
        fake.message = message
        nhl = FakeNhl()
        nhl.search["Zach Hyman"] = [{"playerId": "8475786", "name": "Zach Hyman", "positionCode": "R", "teamAbbrev": "EDM"}]
        with discord(fake):
            errors, log = quiet(tradedesk.post_revisits, state, CFG, NY, now or ny(2027, 7, 15, 12, 5), "live",
                                tp.NhlStats(nhl.get), FakeHistory())
        return state, fake, errors, log

    def test_six_month_revisit(self):
        message = {"poll": {"answers": [{"answer_id": 1, "poll_media": {"text": "Test 1"}},
                                        {"answer_id": 2, "poll_media": {"text": "Test 2"}},
                                        {"answer_id": 3, "poll_media": {"text": "Even"}}],
                            "results": {"is_finalized": True, "answer_counts": [{"id": 2, "count": 6}]}}}
        state, fake, errors, log = self.run_revisit(message=message)
        self.assertEqual(errors, 0, log)
        self.assertEqual(len(fake.sent), 1)
        secret_name, payload = fake.sent[0]
        self.assertEqual(secret_name, "BLHA_WEBHOOK_TRADE_DISCUSSION")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "TRADE REVISIT — 6 months")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        # Test 2 received McDavid: Jan 16 and Mar 1 games count (Jan 15 is the trade day).
        mcdavid = round((5 + 2 * 2.95 + 5 * 0.55 - 2 * 0.54 + 0.60 + 0.35) + (2.95 + 2 * 0.55 + 2 * 0.35), 2)
        self.assertIn(f"**{mcdavid:.2f} points**", fields["TEST 2 RECEIVED"])
        self.assertIn(f"Connor McDavid: {mcdavid:.2f} in 2 games", fields["TEST 2 RECEIVED"])
        self.assertIn("Zach Hyman: no NHL games since the trade", fields["TEST 1 RECEIVED"])
        self.assertIn("2028 1st, originally Test 3's (not yet used)", fields["TEST 1 RECEIVED"])
        self.assertEqual(fields["THE ORIGINAL VOTE"], "Test 1: 0 votes\nTest 2: 6 votes\nEven: 0 votes")
        self.assertIn("https://discord.com/channels/9/8/55", embed["description"])
        self.assertIn("NEVER REVERSED BECAUSE OF VALUE", embed["footer"]["text"])
        text = json.dumps(payload).lower()
        for word in ("should be reversed", "unfair", "lopsided", "veto", "winner"):
            self.assertNotIn(word, text)
        self.assertIn("6", state["trades"][0]["revisits"])
        self.assertEqual(state["trades"][0]["players"]["p1"]["nhl_id"], 8478402)

    def test_poll_result_left_out_when_discord_cannot_return_it(self):
        _, fake, errors, log = self.run_revisit(message=None)
        names = [f["name"] for f in fake.sent[0][1]["embeds"][0]["fields"]]
        self.assertNotIn("THE ORIGINAL VOTE", names)
        self.assertIn("could not read the poll", log)

    def test_not_due_yet_and_reversed_and_test_trades(self):
        _, fake, _, _ = self.run_revisit(now=ny(2027, 7, 15, 11, 0))
        self.assertEqual(fake.sent, [])
        _, fake, _, _ = self.run_revisit({"reversed": "2027-01-16T00:00:00+00:00"})
        self.assertEqual(fake.sent, [])
        with patch.dict(CFG, {"season_label": "2027-28"}):
            _, fake, _, _ = self.run_revisit()
        self.assertEqual(fake.sent, [])  # a TEST-league trade is never revisited in the real league

    def test_no_points_total_when_no_player_could_be_scored(self):
        sides = {"a": [{"kind": "player", "label": "Zach Hyman", "points": 0, "games": 0, "error": "no NHL match"}],
                 "b": [{"kind": "pick", "text": "2029 2nd (not yet used)"}]}
        payload = tr.revisit(card_trade(), 6, sides, CFG, window=("Jan 16, 2027", "Jul 15, 2027"))
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        self.assertEqual(fields["TEST 1 RECEIVED"], "Zach Hyman: NHL stats not available (no NHL match)")
        self.assertEqual(fields["TEST 2 RECEIVED"], "2029 2nd (not yet used)")

    def test_twelve_month_revisit_after_six(self):
        state, fake, _, _ = self.run_revisit({"revisits": {"6": {"at": "x"}}}, now=ny(2028, 1, 15, 13, 0))
        self.assertEqual(fake.sent[0][1]["embeds"][0]["title"], "TRADE REVISIT — 12 months")
        self.assertIn("12", state["trades"][0]["revisits"])


# --- deadline day ------------------------------------------------------------------------

def deadline_info(sunday: date) -> dict:
    """A 22-week season whose Week 20 ends the Monday after ``sunday`` (7 PM local)."""
    rows = []
    for n in range(1, 26):
        end = datetime.combine(sunday + timedelta(days=1 + 7 * (n - 20)), time(18, 59, 59), tzinfo=NY)
        rows.append({"number": n, "startDate": (end - timedelta(days=7) + timedelta(seconds=1)).isoformat(),
                     "endDate": end.isoformat()})
    return {"seasonYear": 2026, "scoringPeriods": rows,
            "playoffs": {"lastRegularSeasonPeriod": 22, "firstPlayoffPeriod": 23, "numPlayoffTeams": 6}}


class DeadlineTimingTests(unittest.TestCase):
    def test_deadline_is_sunday_of_week_20_at_11_59_pm_et_and_matches_the_bot(self):
        deadline = cal.trade_deadline(INFO, NY)
        self.assertEqual(deadline.astimezone(NY), datetime(2027, 2, 21, 23, 59, 59, tzinfo=NY))
        sys.path.insert(0, str(AUTOMATION.parent / "bot"))
        try:
            from blha_vote import trade as bot_trade
        except Exception:  # the bot's own dependencies may be missing; its tests cover it
            return
        self.assertEqual(bot_trade.trade_deadline(INFO, NY), deadline)

    def test_stages(self):
        d = cal.trade_deadline(INFO, NY)
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 20, 23, 0), NY), "off")
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 21, 8, 59), NY), "waiting")
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 21, 9, 0), NY), "live")
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 21, 23, 59), NY), "live")
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 22, 0, 0), NY), "final")
        self.assertEqual(tradedesk.tracker_stage(d, ny(2027, 2, 22, 7, 0), NY), "off")

    def test_dst_spring_forward_on_deadline_day(self):
        info = deadline_info(date(2027, 3, 14))   # clocks go forward at 2 AM that Sunday
        d = cal.trade_deadline(info, NY)
        self.assertEqual(d, datetime(2027, 3, 15, 3, 59, 59, tzinfo=timezone.utc))   # 11:59:59 PM EDT
        opens = datetime(2027, 3, 14, 13, 0, tzinfo=timezone.utc)                      # 9:00 AM EDT
        self.assertEqual(tradedesk.tracker_stage(d, opens - timedelta(minutes=1), NY), "waiting")
        self.assertEqual(tradedesk.tracker_stage(d, opens, NY), "live")
        self.assertEqual(sched.deadline_day_window(d, opens, NY), datetime(2027, 3, 14, 5, 0, tzinfo=timezone.utc))

    def test_dst_fall_back_on_deadline_day(self):
        info = deadline_info(date(2026, 11, 1))   # clocks go back at 2 AM that Sunday
        d = cal.trade_deadline(info, NY)
        self.assertEqual(d, datetime(2026, 11, 2, 4, 59, 59, tzinfo=timezone.utc))    # 11:59:59 PM EST
        self.assertEqual(tradedesk.tracker_stage(d, datetime(2026, 11, 1, 13, 59, tzinfo=timezone.utc), NY), "waiting")
        self.assertEqual(tradedesk.tracker_stage(d, datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc), NY), "live")
        start = sched.deadline_day_window(d, datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc), NY)
        self.assertEqual(start, datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc))    # midnight EDT

    def test_scheduler_runs_every_15_minutes_on_deadline_day_and_30_otherwise(self):
        cfg = sched.load_schedule()
        job = next(j for j in cfg["jobs"] if j["id"] == "trade-desk")
        self.assertEqual(job["workflow"], "blha-trade-desk.yml")
        self.assertEqual(job["every_minutes"], 30)
        on = {"trade-deadline-day": (lambda now: datetime(2027, 2, 21, 5, tzinfo=timezone.utc), "x")}
        off = {"trade-deadline-day": (lambda now: None, "x")}
        with patch.dict(sched.CONDITIONS, on):
            fast, why = sched.paced(job)
        self.assertEqual(fast["every_minutes"], 15)
        self.assertIn("trade-deadline-day", why)
        with patch.dict(sched.CONDITIONS, off):
            self.assertEqual(sched.paced(job)[0]["every_minutes"], 30)

        def broken(now):
            raise RuntimeError("Fantrax down")
        with patch.dict(sched.CONDITIONS, {"trade-deadline-day": (broken, "x")}):
            self.assertEqual(sched.paced(job)[0]["every_minutes"], 30)

    def test_window_runs_from_midnight_until_an_hour_after_the_deadline(self):
        d = cal.trade_deadline(INFO, NY)
        self.assertIsNone(sched.deadline_day_window(d, ny(2027, 2, 20, 23, 59), NY))
        self.assertIsNotNone(sched.deadline_day_window(d, ny(2027, 2, 21, 0, 0), NY))
        self.assertIsNotNone(sched.deadline_day_window(d, d + timedelta(minutes=59), NY))
        self.assertIsNone(sched.deadline_day_window(d, d + timedelta(minutes=61), NY))


# --- full runs ---------------------------------------------------------------------------

TRADED = ({"a": ["p2", "p3", "p4"], "b": ["p1", "p5", "p6"], "c": ["p7", "p8"]}, BASE_PICKS)
TRADED_2 = ({"a": ["p2", "p3", "p4"], "b": ["p1", "p6", "p7"], "c": ["p5", "p8"]}, BASE_PICKS)


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "tradedesk.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_desk(self, readings, now, fake, mode="live", env=None):
        fx = FakeFantrax(readings)
        with discord(fake, env):
            code, log = quiet(tradedesk.run, mode, now=now, fx=fx, cfg=CFG, state_path=self.state,
                              stats=tp.NhlStats(FakeNhl().get), hist=FakeHistory(), sleep=no_sleep)
        return code, log, fx

    def saved(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def test_first_run_saves_a_baseline_only(self):
        fake = Discord()
        code, log, _ = self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        self.assertEqual(code, 0, log)
        self.assertIn("baseline", log)
        self.assertEqual(fake.sent, [])
        self.assertEqual(self.saved()["snapshot"]["season"], 2026)

    def test_trade_posts_one_report_card_with_poll_and_saves_the_message_id(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        code, log, fx = self.run_desk([TRADED], ny(2027, 1, 10, 12, 30), fake)
        self.assertEqual(code, 0, log)
        self.assertEqual(fx.reads, 2)   # read again to confirm before posting
        self.assertEqual(len(fake.sent), 1)
        secret_name, payload = fake.sent[0]
        self.assertEqual(secret_name, "BLHA_WEBHOOK_TRADE_DISCUSSION")
        self.assertIn("poll", payload)
        trade = self.saved()["trades"][0]
        self.assertEqual((trade["card"], trade["message_id"], trade["poll"]), ("posted", "101", True))
        self.assertEqual(trade["players"]["p1"]["name"], "McDavid, Connor")
        # Nothing changes on the next run: no second post, and only updated_at moves (the state save skips that).
        before = self.saved()
        self.run_desk([TRADED], ny(2027, 1, 10, 13, 0), fake)
        self.assertEqual(len(fake.sent), 1)
        after = self.saved()
        self.assertNotEqual(before.pop("updated_at"), after.pop("updated_at"))
        self.assertEqual(before, after)

    def test_lineup_status_changes_do_not_change_the_saved_copy(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        before = self.saved()["snapshot"]
        fx = FakeFantrax([(BASE_TEAMS, BASE_PICKS)])
        original = fx.rosters
        fx.rosters = lambda: {"rosters": {t: {**v, "rosterItems": [{**i, "status": "RESERVE"} for i in v["rosterItems"]]}
                                          for t, v in original()["rosters"].items()}}
        with discord(fake):
            quiet(tradedesk.run, "live", now=ny(2027, 1, 10, 12, 30), fx=fx, cfg=CFG, state_path=self.state,
                  stats=tp.NhlStats(FakeNhl().get), hist=FakeHistory(), sleep=no_sleep)
        self.assertEqual(self.saved()["snapshot"], before)

    def test_trade_seen_half_way_is_confirmed_by_the_second_read(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        half = ({"a": ["p2", "p3", "p4"], "b": ["p1", "p5", "p6"], "c": ["p7", "p8"]}, BASE_PICKS)
        whole = (half[0], {**BASE_PICKS, (2028, 1, "b"): "a"})
        self.run_desk([half, whole], ny(2027, 1, 10, 12, 30), fake)
        self.assertEqual(len(fake.sent), 1)
        fields = {f["name"]: f["value"] for f in fake.sent[0][1]["embeds"][0]["fields"]}
        self.assertIn("2028 1st round pick (Test 2)", fields["TEST 1 RECEIVES"])

    def test_poll_refused_falls_back_to_the_embed(self):
        fake = Discord(poll_400=True)
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        code, log, _ = self.run_desk([TRADED], ny(2027, 1, 10, 12, 30), fake)
        self.assertEqual(code, 0, log)
        self.assertNotIn("poll", fake.sent[0][1])
        self.assertIn("POLL WARNING", log)
        self.assertFalse(self.saved()["trades"][0]["poll"])

    def test_missing_secrets_skip_with_a_clear_log_and_do_not_fail(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 2, 21, 8, 0), fake, env={})
        code, log, _ = self.run_desk([TRADED], ny(2027, 2, 21, 10, 0), fake, env={})
        self.assertEqual(code, 0, log)
        self.assertIn("SKIP report card: the BLHA_WEBHOOK_TRADE_DISCUSSION secret is not set", log)
        self.assertIn("SKIP tracker: the BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS secret is not set", log)
        self.assertEqual((fake.sent, fake.upserts), ([], []))
        self.assertEqual(self.saved()["trades"][0]["card"], "skipped")

    def test_preview_posts_and_saves_nothing(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        before = self.state.read_text(encoding="utf-8")
        code, log, _ = self.run_desk([TRADED], ny(2027, 1, 10, 12, 30), fake, mode="preview")
        self.assertEqual(code, 0, log)
        self.assertIn("TRADE REPORT CARD", log)
        self.assertEqual(fake.sent, [])
        self.assertEqual(self.state.read_text(encoding="utf-8"), before)

    def test_deadline_day_tracker_posts_at_9_edits_then_goes_final(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 2, 21, 8, 30), fake)
        self.assertEqual(fake.upserts, [])                    # before 9:00 AM: nothing yet
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 2, 21, 9, 5), fake)
        self.assertEqual(len(fake.upserts), 1)
        secret_name, payload, message_id = fake.upserts[0]
        self.assertEqual((secret_name, message_id), ("BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS", None))
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "BLHA TRADECENTRE")
        deadline = int(cal.trade_deadline(INFO, NY).timestamp())
        self.assertIn(f"<t:{deadline}:R>", embed["description"])
        self.assertIn("**Trades today:** 0", embed["description"])

        self.run_desk([TRADED], ny(2027, 2, 21, 15, 20), fake)
        _, payload, message_id = fake.upserts[-1]
        self.assertEqual(message_id, "101")                   # the same message is edited
        self.assertIn("**Trades today:** 1", payload["embeds"][0]["description"])
        self.assertIn("**Trades this season:** 1", payload["embeds"][0]["description"])
        self.assertEqual(payload["embeds"][0]["fields"][0]["name"], "TRADE 1")

        self.run_desk([TRADED_2], ny(2027, 2, 22, 0, 5), fake)
        _, payload, message_id = fake.upserts[-1]
        self.assertEqual(message_id, "101")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "BLHA TRADECENTRE — FINAL")
        self.assertIn("Deadline passed — 2 trades today.", embed["description"])
        self.assertIn("first check after the deadline", embed["fields"][1]["value"])
        self.assertEqual(embed["footer"]["text"], tr.TRACKER_FINAL_FOOTER)
        self.assertTrue(self.saved()["deadline"]["2027-02-21"]["final"])

        count = len(fake.upserts)
        self.run_desk([TRADED_2], ny(2027, 2, 22, 0, 20), fake)
        self.assertEqual(len(fake.upserts), count)            # final is final

    def test_trades_before_deadline_day_count_for_the_season_not_today(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 2, 20, 12, 0), fake)
        self.run_desk([TRADED], ny(2027, 2, 20, 12, 30), fake)
        self.run_desk([TRADED], ny(2027, 2, 21, 9, 15), fake)
        description = fake.upserts[-1][1]["embeds"][0]["description"]
        self.assertIn("**Trades today:** 0", description)
        self.assertIn("**Trades this season:** 1", description)

    def test_reversal_is_not_posted_and_cancels_revisits(self):
        fake = Discord()
        self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 10, 12, 0), fake)
        self.run_desk([TRADED], ny(2027, 1, 10, 12, 30), fake)
        code, log, _ = self.run_desk([(BASE_TEAMS, BASE_PICKS)], ny(2027, 1, 11, 9, 0), fake)
        self.assertEqual(code, 0, log)
        self.assertIn("REVERSAL", log)
        self.assertEqual(len(fake.sent), 1)
        trades = self.saved()["trades"]
        self.assertEqual(len(trades), 1)
        self.assertIn("reversed", trades[0])


class TrackerLimitsTests(unittest.TestCase):
    def test_busy_deadline_day_stays_inside_discord_limits(self):
        trades = []
        for i in range(30):
            t = card_trade()
            t["names"] = {"a": "A" * 40, "b": "B" * 40, "c": "Test 3"}
            t["received"] = {"a": [f"player:p{i}{j}" for j in range(6)], "b": [f"pick:2028|{j}|c" for j in range(1, 6)]}
            trades.append(t)
        payload = tr.tracker(CFG, cal.trade_deadline(INFO, NY), trades, 55, final=False, now=ny(2027, 2, 21, 20, 0))
        embed = payload["embeds"][0]
        self.assertLessEqual(len(embed["fields"]), 25)
        self.assertLessEqual(tr._size(embed), 6000)
        self.assertEqual(embed["fields"][-1]["name"], "MORE TRADES")
        self.assertTrue(all(len(f["value"]) <= 1024 for f in embed["fields"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
