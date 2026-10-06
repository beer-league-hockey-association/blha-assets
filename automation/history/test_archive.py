#!/usr/bin/env python3
"""Offline checks for the daily league archive (automation/history/collect.py and store.py).

Uses the live Fantrax fixtures in automation/tests/fixtures: the 2026-27 test
league's calendar, two real rosters (padded to 12 teams), the 180 future
picks and the real startup draft header.
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))

from blha import draft as dr  # noqa: E402
from blha.fantrax import normalize_scores  # noqa: E402
from history import collect, testkit as kit  # noqa: E402
from history.store import Archive, is_test_label, read_jsonl  # noqa: E402

ET = ZoneInfo("America/New_York")
A, B, C, D = kit.TEAMS[0], kit.TEAMS[1], kit.TEAMS[2], kit.TEAMS[3]
REAL_A = "gb4or3npmumb3mgv"   # "Test" (real fixture roster)
REAL_B = "2tml63mumumuxoqh"   # "Test 3" (real fixture roster)


def utc(y: int, mo: int, d: int, h: int = 9, mi: int = 30) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def first_player(raw: dict, team: str, status: str | None = None) -> str:
    return next(i["id"] for i in raw["rosters"][team]["rosterItems"] if status is None or i["status"] == status)


class TempArchive(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = Archive(Path(self.tmp.name) / "archive")

    def run_collect(self, fx: kit.FakeFantrax, when: datetime, mode: str = "live", cfg: dict | None = None) -> int:
        return collect.run(mode, now=when, fx=fx, archive=self.archive, cfg=cfg or kit.CFG)


class SnapshotTests(unittest.TestCase):
    def test_roster_snapshot_reads_live_fixture(self) -> None:
        snap = collect.roster_snapshot(kit.REAL_ROSTERS)
        self.assertEqual(set(snap), {REAL_A, REAL_B})
        self.assertEqual(len(snap[REAL_A]), 36)
        self.assertEqual(sorted(set(snap[REAL_A].values())), ["ACTIVE", "MINORS", "RESERVE"])

    def test_bad_roster_answer_is_refused(self) -> None:
        with self.assertRaises(collect.SnapshotError):
            collect.roster_snapshot({"error": "nope"})

    def test_pick_snapshot_reads_live_fixture(self) -> None:
        picks = collect.pick_snapshot(kit.PICKS)
        self.assertEqual(len(picks), 180)
        self.assertEqual(picks[f"2027|1|{REAL_B}"], REAL_B)

    def test_current_draft_picks_use_the_draft_year(self) -> None:
        raw = {"futureDraftPicks": [], "currentDraftPicks": [
            {"round": 1, "pick": 3, "originalOwnerTeamId": A, "currentOwnerTeamId": B}]}
        self.assertEqual(collect.pick_snapshot(raw, 2028), {f"2028|1|{A}": B})
        self.assertEqual(collect.pick_snapshot(raw, None), {})

    def test_season_key_is_fantrax_season_year(self) -> None:
        self.assertEqual(collect.season_of(kit.INFO), 2026)
        self.assertEqual(collect.season_of({"startDate": "2027-10-01"}), 2027)

    def test_test_label(self) -> None:
        self.assertTrue(is_test_label("2026-27 TEST"))
        self.assertFalse(is_test_label("2027-28"))
        self.assertFalse(is_test_label("Contest league"))

    def test_live_matchup_fixture_is_read_into_the_saved_shape(self) -> None:
        # Captured early in week 2: one team had 11.1 points from 2 games, the rest 0.
        fx = kit.FakeFantrax(matchup=lambda p: normalize_scores(kit.SCORES_P2))
        saved, _ = collect.capture_results(fx, kit.INFO, {}, utc(2026, 10, 12, 11), ET)
        week = saved["2"]
        self.assertEqual(len(week["matchups"]), 6)
        self.assertTrue(all(m["away"]["team"] and m["home"]["team"] for m in week["matchups"]))
        self.assertTrue(week["played"])
        self.assertEqual(sorted(m[s]["score"] for m in week["matchups"] for s in ("away", "home"))[-1], 11.1)


class DiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev = {A: {"p1": "ACTIVE", "p2": "RESERVE", "p3": "MINORS"}, B: {"p4": "ACTIVE", "p5": "IR"}, C: {"p6": "ACTIVE"}}

    def test_add_drop_trade_and_status(self) -> None:
        cur = {A: {"p1": "RESERVE", "p3": "ACTIVE", "p4": "ACTIVE"}, B: {"p2": "ACTIVE", "p5": "ACTIVE", "p9": "ACTIVE"}, C: {}}
        adds, drops, moves, statuses = collect.player_changes(self.prev, cur)
        self.assertEqual(adds, [{"team": B, "player": "p9", "status": "ACTIVE"}])
        self.assertEqual(drops, [{"team": C, "player": "p6"}])
        self.assertEqual({(m["asset"], m["from"], m["to"]) for m in moves},
                         {("player:p2", A, B), ("player:p4", B, A)})
        # MINORS and IR moves are kept; ACTIVE <-> RESERVE lineup changes are not.
        self.assertEqual({(s["player"], s["from"], s["to"]) for s in statuses},
                         {("p3", "MINORS", "ACTIVE"), ("p5", "IR", "ACTIVE")})

    def test_players_drafted_since_last_run_are_not_adds(self) -> None:
        cur = copy.deepcopy(self.prev)
        cur[A]["d1"] = "RESERVE"
        adds, *_ = collect.player_changes(self.prev, cur, {"d1"})
        self.assertEqual(adds, [])

    def test_drafted_since_uses_pick_times(self) -> None:
        draft = dr.parse_results(kit.DRAFT)
        before = draft.start - timedelta(days=1)
        self.assertEqual(len(collect.drafted_since(draft, before)), 24)
        self.assertEqual(collect.drafted_since(draft, draft.end + timedelta(days=2)), set())

    def test_two_team_trade_lists_both_sides(self) -> None:
        moves = [{"asset": "player:p2", "from": A, "to": B}, {"asset": "pick:2028|1|" + B, "from": B, "to": A}]
        [t] = collect.group_trades(moves)
        self.assertEqual(t["teams"], sorted([A, B]))
        self.assertEqual(t["received"][A], ["pick:2028|1|" + B])
        self.assertEqual(t["received"][B], ["player:p2"])
        self.assertNotIn("one_sided", t)

    def test_three_team_trade_is_one_event(self) -> None:
        moves = [{"asset": "player:x", "from": A, "to": B}, {"asset": "player:y", "from": B, "to": C},
                 {"asset": "player:z", "from": C, "to": A}]
        [t] = collect.group_trades(moves)
        self.assertEqual(len(t["teams"]), 3)
        self.assertEqual({k: v for k, v in t["received"].items()}, {A: ["player:z"], B: ["player:x"], C: ["player:y"]})

    def test_separate_trades_stay_separate(self) -> None:
        moves = [{"asset": "player:x", "from": A, "to": B}, {"asset": "player:y", "from": B, "to": A},
                 {"asset": "player:z", "from": C, "to": D}, {"asset": "player:w", "from": D, "to": C}]
        self.assertEqual(len(collect.group_trades(moves)), 2)

    def test_one_way_move_is_flagged(self) -> None:
        [t] = collect.group_trades([{"asset": "player:x", "from": A, "to": B}])
        self.assertTrue(t["one_sided"])

    def test_pick_window_rolling_forward_is_not_a_move(self) -> None:
        prev = {f"2028|1|{A}": A}
        cur = {f"2028|1|{A}": A, f"2030|1|{A}": A}
        self.assertEqual(collect.pick_changes(prev, cur), [])
        self.assertEqual(collect.pick_changes(prev, {f"2028|1|{A}": B}),
                         [{"asset": f"pick:2028|1|{A}", "from": A, "to": B}])

    def test_mass_vanish_is_refused(self) -> None:
        prev = {A: {f"p{i}": "ACTIVE" for i in range(30)}, B: {f"q{i}": "ACTIVE" for i in range(30)}}
        with self.assertRaises(collect.SnapshotError):
            collect.check_sane(prev, {A: prev[A], B: {}})
        collect.check_sane(prev, prev)


class CaptureTests(unittest.TestCase):
    def test_only_final_weeks_are_saved_and_corrections_rechecked(self) -> None:
        fx = kit.FakeFantrax()
        # Week 3 ends Mon Oct 19 2026; it is final from 6 AM that morning.
        saved, changed = collect.capture_results(fx, kit.INFO, {}, utc(2026, 10, 19, 11), ET)
        self.assertEqual(changed, [1, 2, 3])
        self.assertTrue(all(w["played"] and not w["playoff"] for w in saved.values()))
        self.assertEqual(len(saved["2"]["matchups"]), 6)
        fx.calls.clear()
        _, changed = collect.capture_results(fx, kit.INFO, saved, utc(2026, 10, 20, 11), ET)
        self.assertEqual(changed, [])
        self.assertEqual(fx.calls, ["scores:3"])          # inside the 3-day correction window
        fx.calls.clear()
        collect.capture_results(fx, kit.INFO, saved, utc(2026, 10, 26, 11), ET)
        self.assertEqual(fx.calls, ["scores:4"])          # week 3 is settled; only the new week is read

    def test_stat_correction_replaces_the_week(self) -> None:
        saved, _ = collect.capture_results(kit.FakeFantrax(), kit.INFO, {}, utc(2026, 10, 19, 11), ET)

        def corrected(period: int) -> list:
            rows = kit.scores(period)
            rows[0]["away"]["score"] += 1.5
            return rows

        out, changed = collect.capture_results(kit.FakeFantrax(matchup=corrected), kit.INFO, saved, utc(2026, 10, 20, 11), ET)
        self.assertEqual(changed, [3])
        self.assertEqual(out["3"]["matchups"][0]["away"]["score"], saved["3"]["matchups"][0]["away"]["score"] + 1.5)

    def test_weeks_with_nothing_played_are_marked(self) -> None:
        zero = lambda p: [{side: {**m[side], "score": 0.0, "gamesPlayed": 0.0} for side in ("away", "home")} for m in kit.scores(p)]  # noqa: E731
        saved, _ = collect.capture_results(kit.FakeFantrax(matchup=zero), kit.INFO, {}, utc(2026, 10, 6, 11), ET)
        self.assertFalse(saved["1"]["played"])

    def test_playoff_weeks_are_flagged(self) -> None:
        saved, _ = collect.capture_results(kit.FakeFantrax(), kit.INFO, {}, utc(2027, 4, 10), ET)
        self.assertEqual(len(saved), 25)
        self.assertTrue(saved["23"]["playoff"])
        self.assertFalse(saved["22"]["playoff"])

    def test_final_standings_wait_for_fantrax(self) -> None:
        fx = kit.FakeFantrax()
        self.assertIsNone(collect.capture_standings(fx, kit.INFO, None, utc(2026, 12, 1), ET))
        self.assertNotIn("standings", fx.calls)           # not even asked before the last regular week is over
        self.assertIsNone(collect.capture_standings(fx, kit.INFO, None, utc(2027, 3, 10), ET))  # Fantrax shows 0 games
        done = copy.deepcopy(kit.STANDINGS)
        for i, row in enumerate(done):
            row["points"] = f"{11 + i % 3}-{11 - i % 3}-0"
        saved = collect.capture_standings(kit.FakeFantrax(standings=done), kit.INFO, None, utc(2027, 3, 10), ET)
        self.assertEqual(saved["after_week"], 22)
        self.assertEqual(len(saved["rows"]), 12)
        self.assertIsNone(collect.capture_standings(fx, kit.INFO, saved, utc(2027, 3, 11), ET))

    def test_draft_saved_once_when_complete(self) -> None:
        draft = dr.parse_results(kit.DRAFT)
        saved = collect.capture_draft(draft, None, ET)
        self.assertEqual((saved["year"], len(saved["picks"]), saved["order"][0]), (2026, 24, "8j6llh6gmumuxose"))
        self.assertIsNone(collect.capture_draft(draft, saved, ET))
        live = copy.deepcopy(kit.DRAFT)
        live["draftState"] = "in_progress"
        live["draftPicks"][-1]["playerId"] = None
        self.assertIsNone(collect.capture_draft(dr.parse_results(live), None, ET))


class RunTests(TempArchive):
    def test_first_run_is_a_baseline(self) -> None:
        self.assertEqual(self.run_collect(kit.FakeFantrax(), utc(2026, 10, 20)), 0)
        self.assertEqual(self.archive.all_seasons(), [2026])
        self.assertEqual(self.archive.season_events(2026), [])
        self.assertEqual(len(self.archive.rosters(2026)), 12)
        self.assertEqual(len(self.archive.picks(2026)), 180)
        self.assertEqual(sorted(self.archive.results(2026), key=int), ["1", "2", "3"])
        self.assertEqual(len(self.archive.draft(2026)["picks"]), 24)
        meta = self.archive.meta(2026)
        self.assertTrue(meta["test"])
        self.assertEqual(meta["teams"][REAL_A], "Test")
        self.assertIn("baseline_at", meta)
        self.assertTrue(set(self.archive.players()) <= set(kit.PLAYER_IDS))   # only names the archive needs

    def test_changes_become_events(self) -> None:
        raw = kit.rosters_raw()
        self.run_collect(kit.FakeFantrax(rosters=raw), utc(2026, 10, 20))
        nxt = copy.deepcopy(raw)
        a_player, b_player = first_player(nxt, REAL_A, "ACTIVE"), first_player(nxt, REAL_B, "RESERVE")
        kit.move_player(nxt, a_player, REAL_B)
        kit.move_player(nxt, b_player, REAL_A)
        kit.move_player(nxt, "04bdb", REAL_A)               # Jack Hughes from the pool
        dropped = first_player(nxt, C)
        kit.drop_player(nxt, dropped)
        picks = copy.deepcopy(kit.PICKS)
        kit.set_pick_owner(picks, 2028, 1, REAL_B, REAL_A)
        self.run_collect(kit.FakeFantrax(rosters=nxt, picks=picks), utc(2026, 10, 21))
        events = self.archive.season_events(2026)
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds, ["trade", "drop", "add"])
        trade = events[0]
        self.assertEqual(trade["received"][REAL_A], sorted([f"pick:2028|1|{REAL_B}", f"player:{b_player}"]))
        self.assertEqual(trade["received"][REAL_B], [f"player:{a_player}"])
        self.assertEqual((trade["date"], trade["since"]), ("2026-10-21", utc(2026, 10, 20).isoformat()))
        self.assertEqual(events[1]["player"], dropped)
        self.assertEqual((events[2]["player"], events[2]["team"]), ("04bdb", REAL_A))
        self.assertEqual(len({e["id"] for e in events}), 3)
        self.assertEqual(self.archive.players()["04bdb"]["name"], "Hughes, Jack")
        # Nothing changes the next day: nothing new is appended.
        self.run_collect(kit.FakeFantrax(rosters=nxt, picks=picks), utc(2026, 10, 22))
        self.assertEqual(len(self.archive.season_events(2026)), 3)

    def test_preview_writes_nothing(self) -> None:
        self.run_collect(kit.FakeFantrax(), utc(2026, 10, 20), mode="preview")
        self.assertFalse(self.archive.root.exists())

    def test_new_season_never_overwrites_the_old_one(self) -> None:
        self.run_collect(kit.FakeFantrax(), utc(2026, 10, 20))
        before = (self.archive.season_dir(2026) / "results.json").read_text()
        info = copy.deepcopy(kit.INFO)
        info["seasonYear"] = 2027
        cfg = {**kit.CFG, "season_label": "2027-28", "league_id": "newleague"}
        raw = kit.rosters_raw()
        kit.move_player(raw, "04bdb", REAL_A)
        collect.run("live", now=utc(2027, 7, 1), fx=kit.FakeFantrax(info=info, rosters=raw), archive=self.archive, cfg=cfg)
        self.assertEqual(self.archive.all_seasons(), [2026, 2027])
        self.assertEqual(self.archive.season_events(2027), [])            # baseline for the new season
        self.assertEqual((self.archive.season_dir(2026) / "results.json").read_text(), before)
        self.assertFalse(self.archive.meta(2027)["test"])
        self.assertEqual(self.archive.seasons(), [2027])                  # the test season drops out of history

    def test_incomplete_fantrax_answer_saves_nothing(self) -> None:
        self.run_collect(kit.FakeFantrax(), utc(2026, 10, 20))
        broken = kit.rosters_raw()
        for team in list(broken["rosters"])[:8]:
            broken["rosters"][team]["rosterItems"] = []
        with self.assertRaises(collect.SnapshotError):
            self.run_collect(kit.FakeFantrax(rosters=broken), utc(2026, 10, 21))
        self.assertEqual(len(self.archive.rosters(2026)), 12)
        self.assertEqual(sum(len(r) for r in self.archive.rosters(2026).values()), 432)

    def test_pick_feed_failure_keeps_saved_picks(self) -> None:
        self.run_collect(kit.FakeFantrax(), utc(2026, 10, 20))
        self.run_collect(kit.FakeFantrax(picks=RuntimeError("down")), utc(2026, 10, 21))
        self.assertEqual(len(self.archive.picks(2026)), 180)

    def test_events_file_is_append_only_jsonl(self) -> None:
        path = Path(self.tmp.name) / "e.jsonl"
        from history.store import append_jsonl
        append_jsonl(path, [{"a": 1}])
        with path.open("a") as handle:
            handle.write("not json\n")
        append_jsonl(path, [{"b": 2}])
        self.assertEqual(read_jsonl(path), [{"a": 1}, {"b": 2}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
