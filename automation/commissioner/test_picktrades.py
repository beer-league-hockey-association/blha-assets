#!/usr/bin/env python3
"""Offline checks for the pick-trade alert."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import picktrades  # noqa: E402

NAMES = {"a": "Test 1", "b": "Test 2", "c": "Test 3"}


def raw(owners):
    """owners: {(year, round, original): current}"""
    return {"futureDraftPicks": [
        {"year": y, "round": r, "originalOwnerTeamId": o, "currentOwnerTeamId": c}
        for (y, r, o), c in owners.items()
    ], "currentDraftPicks": []}


BASE = {(2028, 1, "a"): "a", (2028, 3, "a"): "a", (2029, 2, "b"): "b"}


class DiffTests(unittest.TestCase):
    def test_no_change_no_alert(self):
        s = picktrades.snapshot(raw(BASE))
        self.assertEqual(picktrades.changes(s, s), [])

    def test_moved_pick_is_reported_with_seller_and_buyer(self):
        prev = picktrades.snapshot(raw(BASE))
        cur = picktrades.snapshot(raw({**BASE, (2028, 1, "a"): "c"}))
        found = picktrades.changes(prev, cur)
        self.assertEqual(found, [{"year": 2028, "round": 1, "original": "a", "from": "a", "to": "c"}])

    def test_window_rolling_forward_is_not_a_trade(self):
        prev = picktrades.snapshot(raw(BASE))
        cur = picktrades.snapshot(raw({**BASE, (2032, 1, "a"): "a"}))
        self.assertEqual(picktrades.changes(prev, cur), [])

    def test_trade_back_and_resale_are_reported(self):
        prev = picktrades.snapshot(raw({**BASE, (2028, 1, "a"): "c"}))
        cur = picktrades.snapshot(raw({**BASE, (2028, 1, "a"): "b"}))
        c = picktrades.changes(prev, cur)[0]
        text = picktrades.describe(c, NAMES)
        self.assertIn("originally Test 1's", text)
        self.assertIn("Test 3 to Test 2", text)

    def test_bad_response_raises(self):
        with self.assertRaises(ValueError):
            picktrades.snapshot({})


class MessageTests(unittest.TestCase):
    def test_first_and_second_round_ask_for_prepayment_check(self):
        found = [{"year": 2029, "round": 2, "original": "a", "from": "a", "to": "b"}]
        task = picktrades.build_task(found, NAMES)
        text = "\n".join(task["items"])
        self.assertIn("confirm prepayment", task["title"])
        self.assertIn("paid through Season 2029", text)
        self.assertIn("12.5", text)

    def test_later_rounds_need_no_prepayment(self):
        found = [{"year": 2029, "round": 4, "original": "a", "from": "a", "to": "b"}]
        task = picktrades.build_task(found, NAMES)
        self.assertEqual(task["title"], "Pick trade recorded")
        self.assertNotIn("paid through", "\n".join(task["items"]))

    def test_several_moves_make_one_message(self):
        found = [
            {"year": 2029, "round": 1, "original": "a", "from": "a", "to": "b"},
            {"year": 2029, "round": 5, "original": "b", "from": "b", "to": "a"},
        ]
        task = picktrades.build_task(found, NAMES)
        self.assertTrue(task["title"].startswith("2 pick moves"))
        self.assertNotIn("•", "\n".join(task["items"]))


CSV = (
    "Pick Clearance,,\n"
    "Read by the pick-trade alert,,\n"
    "Fantrax team ID,Franchise,Paid through\n"
    "a,Test 1,2029\n"
    "b,Test 2,Not paid\n"
    ",Franchise 12,0\n"
)


class LedgerTests(unittest.TestCase):
    def test_parse_clearance_finds_header_and_reads_years(self):
        table = picktrades.parse_clearance(CSV)
        self.assertEqual(table["a"], {"franchise": "Test 1", "paid_through": 2029})
        self.assertIsNone(table["b"]["paid_through"])
        self.assertNotIn("", table)

    def test_wrong_sheet_is_rejected(self):
        self.assertIsNone(picktrades.parse_clearance("<html>Sign in</html>"))

    def test_verdicts(self):
        table = picktrades.parse_clearance(CSV)
        move = {"year": 2029, "round": 1, "original": "a", "from": "a", "to": "b"}
        self.assertEqual(picktrades.verdict(move, table), ("paid", 2029))
        self.assertEqual(picktrades.verdict({**move, "year": 2030}, table), ("unpaid", 2029))
        self.assertEqual(picktrades.verdict({**move, "from": "b"}, table), ("unpaid", None))
        self.assertEqual(picktrades.verdict({**move, "from": "c"}, table), ("unknown", None))
        self.assertEqual(picktrades.verdict(move, None), ("unknown", None))

    def test_unpaid_seller_gets_reverse_instruction(self):
        table = picktrades.parse_clearance(CSV)
        found = [{"year": 2029, "round": 2, "original": "b", "from": "b", "to": "a"}]
        task = picktrades.build_task(found, NAMES, table)
        text = "\n".join(task["items"])
        self.assertIn("reverse", task["title"])
        self.assertIn("NOT PAID", text)
        self.assertIn("Reverse the entire trade", text)

    def test_paid_seller_needs_no_action(self):
        table = picktrades.parse_clearance(CSV)
        found = [{"year": 2029, "round": 1, "original": "a", "from": "a", "to": "b"}]
        task = picktrades.build_task(found, NAMES, table)
        self.assertEqual(task["title"], "Pick trade: prepayment confirmed")
        self.assertIn("PAID: ", task["items"][1])
        self.assertNotIn("Reverse", "\n".join(task["items"]))

    def test_team_missing_from_sheet_asks_for_hand_check(self):
        table = picktrades.parse_clearance(CSV)
        found = [{"year": 2029, "round": 1, "original": "c", "from": "c", "to": "a"}]
        task = picktrades.build_task(found, NAMES, table)
        self.assertIn("confirm prepayment", task["title"])
        self.assertIn("not on the Pick Clearance tab", "\n".join(task["items"]))


class ReversalTests(unittest.TestCase):
    def test_pick_sent_back_is_marked_as_reversal(self):
        now = picktrades.datetime(2027, 1, 10, tzinfo=picktrades.timezone.utc)
        recent = [{"key": "2029|1|a", "from": "a", "to": "b", "at": "2027-01-09T12:00:00+00:00"}]
        found = [{"year": 2029, "round": 1, "original": "a", "from": "b", "to": "a"}]
        picktrades.mark_reversals(found, recent, now)
        self.assertTrue(found[0].get("reversal"))
        task = picktrades.build_task(found, NAMES, None)
        self.assertEqual(task["title"], "Pick trade reversed")
        self.assertNotIn("paid through", "\n".join(task["items"]))

    def test_old_alert_is_not_a_reversal(self):
        now = picktrades.datetime(2027, 3, 1, tzinfo=picktrades.timezone.utc)
        recent = [{"key": "2029|1|a", "from": "a", "to": "b", "at": "2027-01-09T12:00:00+00:00"}]
        found = [{"year": 2029, "round": 1, "original": "a", "from": "b", "to": "a"}]
        picktrades.mark_reversals(found, recent, now)
        self.assertFalse(found[0].get("reversal"))


class RunTests(unittest.TestCase):
    @staticmethod
    def _fake(picks_now):
        class FakeFantrax:
            def __init__(self, *a, **k):
                pass

            def draft_picks(self):
                return raw(picks_now)

            def standings(self):
                return [{"rank": i, "teamId": t, "teamName": n, "points": "0-0-0"} for i, (t, n) in enumerate(NAMES.items(), 1)]
        return FakeFantrax

    def _run(self, picks_now, saved=None, mode="live", ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "picktrades.json"
        if saved is not None:
            state.write_text(json.dumps({"owners": saved}))
        posts = []
        FakeFantrax = self._fake(picks_now)

        def fake_post(secret, payload):
            posts.append(payload)
            return ok, "delivered" if ok else "boom"

        with patch.object(picktrades, "STATE_PATH", state), patch.object(picktrades, "Fantrax", FakeFantrax), \
                patch.object(picktrades, "post_discord_webhook", fake_post):
            code = picktrades.run(mode)
            code2 = picktrades.run(mode)
        return code, code2, posts, state

    def test_first_run_saves_baseline_without_alert(self):
        code, _, posts, state = self._run(BASE)
        self.assertEqual((code, posts), (0, []))
        self.assertIn("owners", json.loads(state.read_text()))

    def test_trade_alerts_once(self):
        saved = picktrades.snapshot(raw(BASE))
        code, code2, posts, _ = self._run({**BASE, (2028, 1, "a"): "b"}, saved)
        self.assertEqual((code, code2, len(posts)), (0, 0, 1))
        self.assertEqual(posts[0]["allowed_mentions"], {"parse": []})

    def test_failed_delivery_retries_and_does_not_save(self):
        saved = picktrades.snapshot(raw(BASE))
        code, _, posts, state = self._run({**BASE, (2028, 1, "a"): "b"}, saved, ok=False)
        self.assertEqual((code, len(posts)), (1, 2))
        self.assertEqual(json.loads(state.read_text())["owners"], saved)

    def test_alert_remembers_move_and_reversal_is_recognised(self):
        saved = picktrades.snapshot(raw(BASE))
        code, _, posts, state = self._run({**BASE, (2028, 1, "a"): "b"}, saved)
        recent = json.loads(state.read_text())["recent"]
        self.assertEqual([(r["key"], r["from"], r["to"]) for r in recent], [("2028|1|a", "a", "b")])
        posts2 = []
        with patch.object(picktrades, "STATE_PATH", state), \
                patch.object(picktrades, "Fantrax", self._fake(BASE)), \
                patch.object(picktrades, "post_discord_webhook", lambda s, p: (posts2.append(p) or True, "ok")):
            picktrades.run("live")
        self.assertEqual(posts2[0]["embeds"][0]["title"], "Pick trade reversed")

    def test_ledger_verdict_reaches_the_message(self):
        saved = picktrades.snapshot(raw(BASE))
        table = picktrades.parse_clearance(CSV)
        with patch.object(picktrades, "load_clearance", lambda: table):
            _, _, posts, _ = self._run({**BASE, (2029, 2, "b"): "a"}, saved)
        self.assertIn("NOT PAID", posts[0]["embeds"][0]["description"])

    def test_preview_posts_and_saves_nothing(self):
        saved = picktrades.snapshot(raw(BASE))
        _, _, posts, state = self._run({**BASE, (2028, 1, "a"): "b"}, saved, mode="preview")
        self.assertEqual(posts, [])
        self.assertEqual(json.loads(state.read_text())["owners"], saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
