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


class RunTests(unittest.TestCase):
    def _run(self, picks_now, saved=None, mode="live", ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "picktrades.json"
        if saved is not None:
            state.write_text(json.dumps({"owners": saved}))
        posts = []

        class FakeFantrax:
            def __init__(self, *a, **k):
                pass

            def draft_picks(self):
                return raw(picks_now)

            def standings(self):
                return [{"rank": i, "teamId": t, "teamName": n, "points": "0-0-0"} for i, (t, n) in enumerate(NAMES.items(), 1)]

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

    def test_preview_posts_and_saves_nothing(self):
        saved = picktrades.snapshot(raw(BASE))
        _, _, posts, state = self._run({**BASE, (2028, 1, "a"): "b"}, saved, mode="preview")
        self.assertEqual(posts, [])
        self.assertEqual(json.loads(state.read_text())["owners"], saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
