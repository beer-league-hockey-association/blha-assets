#!/usr/bin/env python3
"""Offline checks for the prospect board."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import prospects  # noqa: E402

import minors  # noqa: E402

minors.MIN_GAP = 0
TODAY = date(2026, 10, 3)


def player(i, cid, mid=None, final=None):
    return {"firstName": f"First{cid}{i}", "lastName": f"Lastname{cid}{i}", "positionCode": "G" if cid > 2 else "C",
            "lastAmateurClub": "SOME LONGER CLUB NAME", "lastAmateurLeague": "NTDP - USHL", "birthDate": "2008-03-09",
            "midtermRank": mid if mid is not None else i, "finalRank": final if final is not None else i}


def lists(shift=0):
    return {cid: [player(i, cid, final=i + (shift if i == 7 and cid == 1 else 0)) for i in range(1, 60)] for cid in (1, 2, 3, 4)}


class FakeResponse:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, data):
        self.headers = {}
        self.data = data

    def get(self, url, params=None, timeout=None):
        if url.endswith("/rankings/now"):
            return FakeResponse({"draftYear": 2026, "categoryId": 1, "rankings": self.data[1]})
        cid = int(url.rsplit("/", 1)[1])
        return FakeResponse({"rankings": self.data[cid]})


TOP = {1: 20, 2: 10, 3: 5, 4: 3}


class BoardTests(unittest.TestCase):
    def test_board_fits_one_discord_message_and_has_no_bullets(self):
        board = {"year": 2026, "lists": lists()}
        task = prospects.build_task(board, TOP, TODAY)
        text = "\n\n".join(task["items"])
        self.assertLess(len(text), 3800)
        self.assertNotIn("•", text)
        self.assertIn("top 20", text)
        self.assertIn("top 3", text)
        self.assertIn("age 18", text)

    def test_unranked_players_are_skipped(self):
        ps = [player(1, 1), {**player(2, 1), "midtermRank": None, "finalRank": None}]
        self.assertEqual(len(prospects.ranked(ps)), 1)

    def test_big_moves_are_reported(self):
        old = prospects.snapshot({"year": 2026, "lists": lists()})
        new_board = {"year": 2026, "lists": lists(shift=9)}
        moves = prospects.movers(old, new_board, TOP)
        self.assertEqual(len(moves), 1)
        self.assertIn("moved down from 7 to 16", moves[0])

    def test_small_moves_are_ignored(self):
        old = prospects.snapshot({"year": 2026, "lists": lists()})
        self.assertEqual(prospects.movers(old, {"year": 2026, "lists": lists(shift=3)}, TOP), [])

    def test_config_reads_counts(self):
        self.assertEqual(prospects.load_config(), {1: 20, 2: 10, 3: 5, 4: 3})


class RunTests(unittest.TestCase):
    def _run(self, data, saved=None, mode="live", ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "prospects.json"
        if saved is not None:
            state.write_text(json.dumps(saved))
        posts = []

        def fake_post(secret, payload):
            posts.append(payload)
            return ok, "delivered" if ok else "boom"

        with patch.object(prospects, "STATE_PATH", state), patch.object(prospects, "post_discord_webhook", fake_post):
            c1 = prospects.run(mode, FakeSession(data), TODAY)
            c2 = prospects.run(mode, FakeSession(data), TODAY)
        return c1, c2, posts, state

    def test_first_run_posts_board_once(self):
        c1, c2, posts, state = self._run(lists())
        self.assertEqual((c1, c2, len(posts)), (0, 0, 1))
        ping = str((prospects.load_league().get("commissioner_desk") or {}).get("ping_user_id") or "").strip()
        self.assertEqual(posts[0]["allowed_mentions"], {"users": [ping]} if ping else {"parse": []})
        self.assertIn("hash", json.loads(state.read_text()))

    def test_changed_rankings_post_again(self):
        saved = prospects.snapshot({"year": 2026, "lists": lists()})
        _, _, posts, _ = self._run(lists(shift=9), saved)
        self.assertEqual(len(posts), 1)
        self.assertIn("Biggest moves", posts[0]["embeds"][0]["description"])

    def test_failed_delivery_retries_without_saving(self):
        c1, _, posts, state = self._run(lists(), ok=False)
        self.assertEqual((c1, len(posts)), (1, 2))
        self.assertFalse(state.exists())

    def test_preview_posts_nothing(self):
        _, _, posts, state = self._run(lists(), mode="preview")
        self.assertEqual(posts, [])
        self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
