#!/usr/bin/env python3
"""Offline checks for league history: history.yaml, Dynasty Pot cycles, trade trees,
rivalries, draft retrospectives, graphics and the Discord posts."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(AUTOMATION.parent / "tools"))

import discohook_format as fmt  # noqa: E402
import discord_webhook  # noqa: E402
from history import post, profiles, records, retro, rivals, trades, testkit as kit  # noqa: E402
from history.context import LeagueHistory, initials, is_snake, natural, slot_pick  # noqa: E402
from history.records import Records, derive_dynasty, validate  # noqa: E402

A, B, C, D = "teamA", "teamB", "teamC", "teamD"
NAMES = {A: "Fantrax North", B: "Fantrax South", C: "Fantrax East", D: "Fantrax West"}

HISTORY = {
    "franchises": {
        "north": {"name": "North Stars", "owner": "Avery", "founded": 2027, "colors": ["#1D4E89", "#F4EFE4"],
                  "logo": "brand/primary/blha-b-mark.png", "team_ids": [A]},
        "south": {"name": "South Shore", "owner": "Blake", "founded": 2027, "colors": ["#C8102E"], "team_ids": [B]},
        "east": {"name": "East Enders", "owner": "Casey", "founded": 2027, "team_ids": [C]},
        "west": {"name": "West Coast", "owner": "Drew", "founded": 2027, "team_ids": [D]},
    },
    "seasons": {
        2027: {"champion": "north", "runner_up": "south", "third_place": "east", "presidents_trophy": "south",
               "consolation_champion": "west", "wooden_spoon": "west",
               "dynasty_pot": {"dues": 200, "unused_reserve": 35, "balance": 235}},
        2028: {"champion": "north", "dynasty_pot": {"dues": 200, "unused_reserve": 0, "balance": 435}},
    },
    "dynasty_pot": {"first_cycle": 2027, "championships": {"north": 2}},
}

PLAYERS = {f"p{i}": {"name": f"Player{i}, Test", "position": "G" if i == 11 else "C", "team": "EDM"} for i in range(1, 25)}

EVENTS_2027 = [
    kit.trade("2027-e1", "2027-07-10T09:30:00+00:00", [("player:p1", A, B), (f"pick:2028|1|{A}", A, B), ("player:p2", B, A)]),
    kit.trade("2027-e2", "2027-08-01T09:30:00+00:00", [("player:p2", A, C), (f"pick:2028|2|{C}", C, A), ("player:p3", C, A)]),
    kit.simple("2027-e3", "2027-09-01T09:30:00+00:00", "drop", A, "p3"),
    kit.simple("2027-e4", "2027-09-02T09:30:00+00:00", "add", D, "p9"),
]
EVENTS_2028 = [
    kit.simple("2028-e1", "2028-08-01T09:30:00+00:00", "add", D, "p20"),
    kit.simple("2028-e2", "2028-08-02T09:30:00+00:00", "add", C, "p21"),
    kit.simple("2028-e3", "2028-08-09T09:30:00+00:00", "drop", C, "p21"),
]
DRAFT_2028 = {
    "key": "2028-07-14", "year": 2028, "date": "2028-07-14T00:00:00+00:00", "end": "2028-07-15T00:00:00+00:00",
    "state": "completed", "order": [A, B, C, D],
    "picks": [
        {"round": 1, "overall": 1, "in_round": 1, "team": B, "player": "p7"},
        {"round": 1, "overall": 2, "in_round": 2, "team": B, "player": "p8"},
        {"round": 1, "overall": 3, "in_round": 3, "team": C, "player": "p10"},
        {"round": 1, "overall": 4, "in_round": 4, "team": D, "player": "p11"},
        {"round": 2, "overall": 5, "in_round": 1, "team": A, "player": "p12"},
        {"round": 2, "overall": 6, "in_round": 2, "team": B, "player": "p14"},
        {"round": 2, "overall": 7, "in_round": 3, "team": A, "player": "p13"},
        {"round": 2, "overall": 8, "in_round": 4, "team": D, "player": "p15"},
    ],
}
ROSTERS_2028 = {A: {"p2x": "ACTIVE", "p13": "MINORS"}, B: {"p1": "ACTIVE", "p7": "RESERVE", "p8": "ACTIVE"},
                C: {"p2": "ACTIVE", "p10": "ACTIVE"}, D: {"p9": "ACTIVE", "p11": "ACTIVE", "p20": "RESERVE"}}
RESULTS_2027 = {
    "1": kit.week(1, [(A, 100.0, B, 90.0), (C, 80.0, D, 80.0)]),
    "2": kit.week(2, [(A, 70.0, C, 90.0), (B, 95.0, D, 85.0)]),
    "3": kit.week(3, [(A, 88.0, B, 99.0), (C, 70.0, D, 75.0)]),
    "4": kit.week(4, [(A, 100.0, B, 50.0)], playoff=True),
    "5": kit.week(5, [(A, 0.0, B, 0.0)], played=False),
}


def build_archive(root: Path) -> None:
    # A test season that must drop out of lifetime records once real seasons exist.
    kit.write_season(root, 2026, teams=NAMES, label="2026-27 TEST",
                     results={"1": kit.week(1, [(A, 1.0, B, 200.0)])})
    kit.write_season(root, 2027, teams=NAMES, label="2027-28", results=RESULTS_2027, events=EVENTS_2027)
    arch = kit.write_season(root, 2028, teams=NAMES, label="2028-29", events=EVENTS_2028, rosters=ROSTERS_2028,
                            draft=DRAFT_2028)
    arch.write_players(PLAYERS)


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "archive"
        build_archive(self.root)
        self.league = {"timezone": "America/New_York", "color": 0xFFB81C, "rivals": [["North Stars", "west"]],
                       "draft_center": {"webhooks": {"results": "BLHA_WEBHOOK_DRAFT_RESULTS"}}}
        self.hist = LeagueHistory(self.root, records=Records(HISTORY), league=self.league)


# --- history.yaml ------------------------------------------------------------------

class HistoryFileTests(unittest.TestCase):
    def test_committed_history_yaml_is_valid(self) -> None:
        data = records.load_raw()
        self.assertEqual(validate(data), [])
        Records.load()  # raises on problems

    def test_valid_example(self) -> None:
        self.assertEqual(validate(HISTORY), [])

    def test_problems_are_reported(self) -> None:
        bad = json.loads(json.dumps(HISTORY))
        bad["franchises"]["north"]["colors"] = ["gold"]
        bad["franchises"]["south"]["team_ids"] = [A]
        bad["franchises"]["east"]["logo"] = "brand/missing.png"
        bad["franchises"]["west"]["nickname"] = "x"
        bad["seasons"]["2027"]["runner_up"] = "north"
        bad["seasons"]["2027"]["wooden_spoon"] = "nobody"
        bad["seasons"]["2027"]["mvp"] = "north"
        bad["extra"] = 1
        text = "\n".join(validate(bad))
        for needle in ("hex colours", f"team id {A} is also listed", "does not exist", "unknown field 'nickname'",
                       "must be different franchises", "'nobody' is not a franchise", "unknown field 'mvp'",
                       "unknown top-level key 'extra'"):
            self.assertIn(needle, text)

    def test_balance_and_counts_must_agree_with_the_champions(self) -> None:
        bad = json.loads(json.dumps(HISTORY))
        bad["seasons"]["2028"]["dynasty_pot"]["balance"] = 400
        bad["dynasty_pot"]["championships"] = {"north": 1}
        text = "\n".join(validate(bad))
        self.assertIn("add up to 435", text)
        self.assertIn("does not match the champions", text)

    def test_cycle_is_won_at_three_titles_and_resets(self) -> None:
        seasons = {2027: {"champion": "north", "dynasty_pot": {"dues": 200, "unused_reserve": 35}},
                   2028: {"champion": "south", "dynasty_pot": {"dues": 200}},
                   2029: {"champion": "north", "dynasty_pot": {"dues": 200}},
                   2030: {"champion": "north", "dynasty_pot": {"dues": 200, "unused_reserve": 10}},
                   2031: {"champion": "south", "dynasty_pot": {"dues": 200}}}
        dynasty, errors = derive_dynasty(seasons, {"first_cycle": 2027})
        self.assertEqual(errors, [])
        [won] = dynasty.past
        self.assertEqual((won.winner, won.ended, won.payout), ("north", 2030, 845))  # 2030's contribution counts (4.5)
        self.assertEqual((dynasty.active.started, dynasty.active.balance, dynasty.active.titles), (2031, 200, {"south": 1}))

    def test_seasons_before_the_first_cycle_do_not_count(self) -> None:
        dynasty, _ = derive_dynasty({2026: {"champion": "north", "dynasty_pot": {"dues": 999}}}, {"first_cycle": 2027})
        self.assertEqual((dynasty.active.balance, dynasty.active.titles), (0, {}))


# --- reading the archive -----------------------------------------------------------

class ContextTests(Fixture):
    def test_test_season_drops_out_once_real_seasons_exist(self) -> None:
        self.assertEqual(self.hist.seasons, [2027, 2028])

    def test_team_ids_map_to_franchises(self) -> None:
        self.assertEqual(self.hist.franchise(A), "north")
        self.assertEqual(self.hist.name("north"), "North Stars")
        self.assertEqual(self.hist.franchise("unknown"), "unknown")
        self.assertEqual(self.hist.pick(f"2028|1|{A}"), "2028 1st round pick (North Stars)")
        self.assertEqual(self.hist.player("p1"), "Test Player1 (C, EDM)")

    def test_unmapped_teams_fall_back_to_their_fantrax_name(self) -> None:
        hist = LeagueHistory(self.root, records=Records({}), league=self.league)
        self.assertEqual(hist.franchise(A), A)
        self.assertEqual(hist.name(A), "Fantrax North")

    def test_draft_slots_linear_and_snake(self) -> None:
        self.assertFalse(is_snake(DRAFT_2028))
        self.assertEqual(slot_pick(DRAFT_2028, 2, C)["player"], "p13")
        self.assertTrue(is_snake({"order": kit.DRAFT["draftOrder"], "picks": [
            {"round": p["round"], "in_round": p["pickInRound"], "team": p["teamId"]} for p in kit.DRAFT["draftPicks"]]}))
        self.assertEqual(self.hist.pick_selection(f"2028|1|{A}")["player"], "p7")

    def test_natural_order_and_initials(self) -> None:
        self.assertEqual(sorted(["Test 10", "Test 2", "Test"], key=natural), ["Test", "Test 2", "Test 10"])
        self.assertEqual((initials("Test 10"), initials("North Stars")), ("T10", "NS"))


# --- trade trees -------------------------------------------------------------------

class TradeTreeTests(Fixture):
    def test_tree_follows_assets_through_later_trades_drafts_and_drops(self) -> None:
        tree = trades.trade_tree(self.hist, "2027-e1", A)
        self.assertEqual(tree.outcome, "Gave 2028 1st round pick (North Stars), Test Player1 (C, EDM)")
        [p2] = tree.children
        self.assertEqual(p2.outcome, "Traded Aug 1, 2027 to East Enders")
        got = {c.asset: c for c in p2.children}
        pick = got[f"pick:2028|2|{C}"]
        self.assertEqual(pick.outcome, "Used at 2.03")
        self.assertEqual((pick.children[0].asset, pick.children[0].outcome), ("player:p13", "Still on the roster (Minors)"))
        self.assertEqual(got["player:p3"].outcome, "Dropped Sep 1, 2027")

    def test_other_side_and_unused_picks(self) -> None:
        tree = trades.trade_tree(self.hist, "2027-e1", B)
        got = {c.asset: c for c in tree.children}
        self.assertEqual(got["player:p1"].outcome, "Still on the roster (Active)")
        self.assertEqual(got[f"pick:2028|1|{A}"].outcome, "Used at 1.01")
        self.assertEqual(got[f"pick:2028|1|{A}"].children[0].label, "Test Player7 (C, EDM)")

    def test_every_side_of_a_trade_and_text_rendering(self) -> None:
        trees = trades.trade_trees(self.hist, "2027-e2")
        self.assertEqual(set(trees), {A, C})
        text = trades.render_text(trades.trade_tree(self.hist, "2027-e1", A))
        self.assertIn("└─ Test Player2 (C, EDM) — Traded Aug 1, 2027 to East Enders", text)
        self.assertIn("   ├─ 2028 2nd round pick (East Enders) — Used at 2.03", text)
        self.assertIn("   │  └─ Test Player13 (C, EDM) — Still on the roster (Minors)", text)
        self.assertEqual({c["asset"] for c in trees[A].to_dict()["children"]}, {"player:p3", f"pick:2028|2|{C}"})

    def test_asset_path(self) -> None:
        path = trades.asset_path(self.hist, "player:p2")
        self.assertEqual([(s["from"], s["to"]) for s in path], [("South Shore", "North Stars"), ("North Stars", "East Enders")])

    def test_unknown_trade(self) -> None:
        with self.assertRaises(KeyError):
            trades.trade_tree(self.hist, "nope", A)

    def test_trade_with_nothing_back(self) -> None:
        kit.write_season(self.root, 2028, teams=NAMES, label="2028-29", rosters=ROSTERS_2028, draft=DRAFT_2028,
                         events=[kit.trade("2028-x", "2028-09-01T09:30:00+00:00", [("player:p8", B, D)])])
        hist = LeagueHistory(self.root, records=Records(HISTORY), league=self.league)
        tree = trades.trade_tree(hist, "2028-x", B)
        self.assertEqual((tree.children, tree.outcome), ([], "Gave Test Player8 (C, EDM)"))


# --- rivalries ---------------------------------------------------------------------

class RivalTests(Fixture):
    def test_lifetime_records_include_playoffs_and_skip_unplayed_weeks(self) -> None:
        h2h = rivals.HeadToHead(self.hist)
        ab = h2h.record("north", "south")
        self.assertEqual((ab.text, ab.games, ab.playoff_games, ab.points_for), ("2-1-0", 3, 1, 288.0))
        self.assertEqual(h2h.record("south", "north").text, "1-2-0")
        self.assertEqual(h2h.record("east", "west").text, "0-1-1")
        self.assertEqual(h2h.lifetime("north").text, "2-2-0")
        self.assertEqual(ab.last, (2027, 4))

    def test_earned_rival_is_most_played_then_closest(self) -> None:
        h2h = rivals.HeadToHead(self.hist)
        self.assertEqual(h2h.earned_rival("north"), "south")
        self.assertEqual(h2h.earned_rival("east"), "west")
        h2h.pairs = {("x", "y"): rivals.Record(wins=3, losses=0), ("x", "z"): rivals.Record(wins=2, losses=1)}
        self.assertEqual(h2h.earned_rival("x"), "z")      # same games, closer record

    def test_declared_rivals_resolve_names_keys_and_ids(self) -> None:
        self.assertEqual(rivals.declared_rivals(self.hist), [("north", "west")])
        hist = LeagueHistory(self.root, records=Records({}), league={"rivals": [[A, "Fantrax West"], ["x"]]})
        self.assertEqual(rivals.declared_rivals(hist), [(A, D)])

    def test_rivalry_note(self) -> None:
        self.assertEqual(rivals.rivalry_note(A, D, self.hist), "Rivals: lifetime 0-0-0")
        self.assertEqual(rivals.rivalry_note(A, B, self.hist), "Rivals (most played): lifetime 2-1-0")
        self.assertEqual(rivals.rivalry_note(C, A, self.hist), "Lifetime 1-0-0")
        self.assertEqual(rivals.rivalry_note(B, "newteam", self.hist), "First meeting")

    def test_rivalry_note_accepts_an_archive_folder(self) -> None:
        note = rivals.rivalry_note(A, B, self.root, records=Records(HISTORY), league={"rivals": []})
        self.assertEqual(note, "Rivals (most played): lifetime 2-1-0")
        empty = Path(self.tmp.name) / "empty"
        self.assertEqual(rivals.rivalry_note(A, B, empty, records=Records({}), league={}), "First meeting")


# --- draft retrospectives ----------------------------------------------------------

def stats_for(values: dict[str, tuple[float, float, float]]) -> dict[str, dict]:
    """player -> (value 2027-28 [before], value 2028-29, value 2029-30)."""
    out = {}
    for pid, (before, first, latest) in values.items():
        out[pid] = {"goalie": False, "seasons": {
            20272028: {"gp": 10, "points": before / 5, "value": before},
            20282029: {"gp": 40, "points": first / 5, "value": first},
            20292030: {"gp": 60, "points": latest / 5, "value": latest}}}
    return out


STATS = stats_for({
    "p7": (0, 5, 5), "p8": (10, 60, 190), "p10": (50, 80, 70), "p11": (20, 30, 20),
    "p12": (0, 3, 2), "p14": (0, 0, 0), "p13": (0, 140, 160), "p15": (0, 10, 10), "p20": (0, 40, 40), "p21": (0, 999, 999),
})


class RetroTests(Fixture):
    def report(self) -> dict:
        return retro.build_report(self.hist, self.hist.drafts()[2028], STATS, ["Nobody, Known"])

    def test_highlights(self) -> None:
        r = self.report()
        self.assertEqual(r["kind"], "Annual Draft")
        self.assertEqual(r["since_season"], "2028-29")
        self.assertEqual(r["steal"]["player"], "p13")       # 7th overall, best output
        self.assertEqual(r["miss"]["player"], "p7")         # least output in round 1
        self.assertEqual(r["development"]["player"], "p8")  # 10 the season before, 190 latest
        self.assertEqual(r["pickup"]["player"], "p20")      # p21 was dropped, p9 was added before the draft
        self.assertEqual(r["pickup"]["franchise"], "West Coast")
        self.assertEqual(r["picks_rated"], 8)

    def test_text_and_discord_payload(self) -> None:
        r = self.report()
        text = retro.render_text(r)
        self.assertIn("Biggest Steal: Test Player13 (C, EDM), 2.03 (7th overall) by North Stars", text)
        self.assertIn("Not matched to an NHL player (1)", text)
        payload = retro.payload(r, self.league, test=True)
        embed = payload["embeds"][0]
        self.assertTrue(embed["title"].startswith("[TEST] 2028 BLHA Annual Draft"))
        self.assertEqual([f["name"] for f in embed["fields"]][:4],
                         ["BIGGEST STEAL", "BIGGEST MISS", "BEST UNDRAFTED PICKUP", "BEST DEVELOPMENT"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("━", json.dumps(payload))

    def test_no_stats_yet(self) -> None:
        r = retro.build_report(self.hist, self.hist.drafts()[2028], {})
        self.assertIsNone(r["steal"])
        self.assertIn("Not enough NHL games yet.", retro.render_text(r))

    def test_nhl_season_scoring(self) -> None:
        landing = {"seasonTotals": [
            {"season": 20282029, "leagueAbbrev": "NHL", "gameTypeId": 2, "gamesPlayed": 40, "goals": 10, "assists": 20, "shots": 100, "points": 30},
            {"season": 20282029, "leagueAbbrev": "NHL", "gameTypeId": 2, "gamesPlayed": 30, "goals": 2, "assists": 3, "shots": 40, "points": 5},
            {"season": 20282029, "leagueAbbrev": "NHL", "gameTypeId": 3, "gamesPlayed": 9, "goals": 9, "assists": 9, "shots": 9},
            {"season": 20272028, "leagueAbbrev": "AHL", "gameTypeId": 2, "gamesPlayed": 70, "goals": 30},
        ]}
        seasons = retro.season_stats(landing, goalie=False)
        self.assertEqual(list(seasons), [20282029])
        self.assertEqual(seasons[20282029]["gp"], 70)
        self.assertAlmostEqual(seasons[20282029]["value"], 12 * 5 + 23 * 2.95 + 140 * 0.55)
        goalie = retro.season_stats({"seasonTotals": [{"season": 20282029, "leagueAbbrev": "NHL", "gameTypeId": 2,
                                                       "gamesPlayed": 10, "gamesStarted": 9, "shotsAgainst": 300,
                                                       "goalsAgainst": 25}]}, goalie=True)
        self.assertAlmostEqual(goalie[20282029]["value"], 9 * 6.5 + 275 * 0.49 - 25 * 5)

    def test_fetch_stats_matches_like_the_minor_eligibility_watch(self) -> None:
        index = retro.minors.Index()
        index.add({"id": 8478402, "first": "Test", "last": "Player7", "birthDate": "2008-01-01", "team": "EDM"})

        class Session:
            headers: dict = {}

            def get(self, url, params=None, timeout=None):
                class R:
                    status_code = 200

                    def json(self):
                        return {"seasonTotals": [{"season": 20282029, "leagueAbbrev": "NHL", "gameTypeId": 2,
                                                  "gamesPlayed": 5, "goals": 1, "assists": 1, "shots": 10}]}

                    def raise_for_status(self):
                        return None
                return R()

        self.hist.players["p8"] = {"name": "Unknown, Somebody", "position": "D", "team": "EDM"}
        with patch.object(retro.minors, "MIN_GAP", 0), patch.object(retro.minors, "search_player", lambda *a: None):
            stats, unmatched = retro.fetch_stats(self.hist, ["p7", "p8"], Session(), index)
        self.assertEqual(list(stats), ["p7"])
        self.assertEqual(stats["p7"]["nhl_id"], 8478402)
        self.assertEqual(stats["p7"]["seasons"][20282029]["gp"], 5)
        self.assertEqual(unmatched, ["Unknown, Somebody"])


# --- profiles, graphics and posts --------------------------------------------------

class ProfileTests(Fixture):
    def test_dynasty_summary(self) -> None:
        s = profiles.dynasty_summary(self.hist)
        self.assertEqual((s["balance"], s["cycle_started"], s["titles_to_win"]), (435, 2027, 3))
        self.assertEqual(s["rows"][0], {"key": "north", "name": "North Stars", "titles": 2, "color": "#1D4E89"})
        self.assertEqual(s["last_added"], {"season": 2028, "dues": 200.0, "unused_reserve": 0.0})

    def test_franchise_profiles(self) -> None:
        by_key = {p["key"]: p for p in profiles.franchise_profiles(self.hist)}
        north = by_key["north"]
        self.assertEqual((north["titles"], north["dynasty_count"], north["rival"], north["rival_kind"]),
                         ([2027, 2028], 2, "West Coast", "declared"))
        self.assertEqual((by_key["south"]["rival"], by_key["south"]["rival_record"]), ("North Stars", "1-2-0"))
        self.assertEqual(by_key["south"]["awards"]["Presidents' Trophy"], [2027])


class GraphicsTests(Fixture):
    def test_pngs_render(self) -> None:
        from PIL import Image

        from history import graphics

        pot = Image.open(io.BytesIO(graphics.dynasty_pot_png(profiles.dynasty_summary(self.hist))))
        self.assertEqual((pot.format, pot.size), ("PNG", (1600, 900)))
        for p in profiles.franchise_profiles(self.hist):
            card = Image.open(io.BytesIO(graphics.franchise_card_png(p)))
            self.assertEqual(card.size, (1600, 900))
        empty = graphics.dynasty_pot_png({"balance": 0, "cycle_started": 2027, "titles_to_win": 3, "rows": []})
        self.assertTrue(empty.startswith(b"\x89PNG"))


class PostTests(Fixture):
    def check_format(self, message: dict) -> None:
        card, last = message["embeds"]
        self.assertTrue(card["image"]["url"].startswith("attachment://"))
        self.assertNotIn("footer", card)
        self.assertEqual(last["image"]["url"], fmt.FOOTER_URL)
        self.assertTrue(fmt.footer_text(last))
        self.assertLessEqual(fmt.message_chars(message["embeds"]), fmt.MAX_CHARS)
        self.assertEqual(message["allowed_mentions"], {"parse": []})

    def test_dynasty_message_follows_the_ledger_template(self) -> None:
        message = post.dynasty_message(profiles.dynasty_summary(self.hist))
        self.check_format(message)
        card = message["embeds"][0]
        self.assertEqual((card["title"], card["color"]), ("DYNASTY POT UPDATE", 13012757))
        self.assertEqual([f["name"] for f in card["fields"]],
                         ["THIS SEASON ADDED", "CHAMPIONSHIP COUNTS THIS CYCLE", "CYCLE STARTED", "TO WIN"])
        self.assertIn("North Stars: 2", card["fields"][1]["value"])
        self.assertEqual(message["embeds"][1]["footer"]["text"], "BLHA LEAGUE LEDGER")

    def test_card_message(self) -> None:
        profile = profiles.franchise_profiles(self.hist)[0]
        message = post.card_message(profile, post.card_filename(profile))
        self.check_format(message)
        self.assertIn("**Owner:**", message["embeds"][0]["description"])

    def run_item(self, item: str, mode: str, ok: bool = True) -> tuple[int, list]:
        sent = []

        def fake_files(secret, payload, files):
            sent.append((secret, payload, [name for name, _ in files]))
            return ok, "delivered" if ok else "boom"

        def fake_post(secret, payload):
            sent.append((secret, payload, []))
            return ok, "delivered" if ok else "boom"

        out = Path(self.tmp.name) / "out"
        with patch.object(post, "post_discord_webhook_files", fake_files), patch.object(post, "post_discord_webhook", fake_post), \
                patch.object(retro, "fetch_stats", lambda hist, ids: (STATS, [])), patch("builtins.print"):
            if item == "dynasty-pot":
                code = post.run_dynasty(mode, self.hist, self.league, out)
            elif item == "franchise-cards":
                code = post.run_cards(mode, self.hist, self.league, out)
            else:
                code = post.run_retro(mode, self.hist, self.league, None)
        return code, sent

    def test_dynasty_pot_posts_one_message_with_its_image(self) -> None:
        code, sent = self.run_item("dynasty-pot", "live")
        self.assertEqual(code, 0)
        self.assertEqual([(s, f) for s, _, f in sent], [("BLHA_WEBHOOK_LEAGUE_LEDGER", ["dynasty-pot.png"])])

    def test_preview_writes_images_and_posts_nothing(self) -> None:
        code, sent = self.run_item("franchise-cards", "preview")
        self.assertEqual((code, sent), (0, []))
        self.assertEqual(len(list((Path(self.tmp.name) / "out").glob("franchise-*.png"))), 4)

    def test_franchise_cards_one_message_each(self) -> None:
        code, sent = self.run_item("franchise-cards", "live")
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 4)
        self.assertTrue(all(s == "BLHA_WEBHOOK_FRANCHISE_DIRECTORY" and len(f) == 1 for s, _, f in sent))
        _, sent = self.run_item("franchise-cards", "test")
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][1]["embeds"][0]["title"].startswith("[TEST] "))

    def test_failed_card_fails_the_run(self) -> None:
        code, _ = self.run_item("franchise-cards", "live", ok=False)
        self.assertEqual(code, 1)

    def test_draft_retro_posts_to_draft_results_and_saves_when_live(self) -> None:
        code, sent = self.run_item("draft-retro", "test")
        self.assertEqual((code, sent[0][0]), (0, "BLHA_WEBHOOK_DRAFT_RESULTS"))
        self.assertIsNone(self.hist.archive.retro(2028))
        code, _ = self.run_item("draft-retro", "live")
        self.assertEqual(self.hist.archive.retro(2028)["steal"]["player"], "p13")

    def test_webhook_names_come_from_league_yaml(self) -> None:
        self.assertEqual(post.webhook({"history": {"webhooks": {"dynasty_pot": "X"}}}, "dynasty_pot"), "X")
        self.assertEqual(post.webhook({}, "franchise_directory"), "BLHA_WEBHOOK_FRANCHISE_DIRECTORY")


class UploadTests(unittest.TestCase):
    def test_files_are_sent_as_multipart_with_attachments(self) -> None:
        calls = []

        class Response:
            status_code = 200
            text = ""

            def json(self):
                return {"id": "1"}

        def fake_post(url, params=None, data=None, files=None, timeout=None):
            calls.append((url, params, json.loads(data["payload_json"]), files))
            return Response()

        with patch.dict(discord_webhook.os.environ, {"SECRET_X": "https://discord.invalid/api/webhooks/1/abc"}), \
                patch.object(discord_webhook.requests, "post", fake_post):
            ok, detail = discord_webhook.post_discord_webhook_files("SECRET_X", {"embeds": []}, [("a.png", b"png")])
        self.assertEqual((ok, detail), (True, "delivered"))
        url, params, payload, files = calls[0]
        self.assertEqual(params, {"wait": "true"})
        self.assertEqual(payload["attachments"], [{"id": 0, "filename": "a.png"}])
        self.assertEqual(files["files[0]"], ("a.png", b"png", "image/png"))

    def test_missing_secret(self) -> None:
        with patch.dict(discord_webhook.os.environ, {}, clear=True):
            ok, detail = discord_webhook.post_discord_webhook_files("NOPE", {}, [("a.png", b"x")])
        self.assertFalse(ok)
        self.assertIn("NOPE", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
