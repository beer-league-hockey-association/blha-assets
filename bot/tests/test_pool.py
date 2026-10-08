#!/usr/bin/env python3
"""Offline tests for the League Bot's Playoff Pool commands (/pool boxes, /pool pick, /pool export).

Boxes are built by the automation's own code (automation/playoff_pool) from the
synthetic NHL fixture, saved and re-read the way the bot gets boxes.json. The
Discord views are checked only where discord.py is installed (GitHub Actions).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from blha_vote import embeds, pool  # noqa: E402
from blha_vote.config import load  # noqa: E402
from blha_vote.league_data import LeagueData  # noqa: E402
from blha_vote.shared import FIXTURES  # noqa: E402
from blha_vote.store import Store  # noqa: E402

from playoff_pool import boxes as bx  # noqa: E402
from playoff_pool import bracket, entries  # noqa: E402

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
FIRST_PUCK = datetime(2027, 4, 17, 19, 0, tzinfo=UTC)
NOW = datetime(2027, 4, 16, 12, 0, tzinfo=UTC)


def boxes_json(deadline: datetime | None = FIRST_PUCK) -> dict:
    """boxes.json as the automation saves it."""
    fx = json.loads((FIXTURES / "nhl_playoffs_synthetic.json").read_text(encoding="utf-8"))
    series = bracket.parse(fx["bracket"])
    built = bx.build(2027, "20262027", bracket.field(series), fx["club_stats"], fx["rosters"], bx.Settings(), NOW)
    built.deadline = deadline
    return json.loads(json.dumps(built.as_dict()))


class LoadTests(unittest.TestCase):
    def test_boxes_json_loads(self) -> None:
        boxes = pool.load_boxes(boxes_json())
        self.assertEqual((boxes.year, len(boxes.boxes), boxes.deadline), (2027, 10, FIRST_PUCK))

    def test_missing_or_broken_file_means_not_posted(self) -> None:
        for raw in (None, {}, {"year": 2027, "boxes": []}, {"boxes": [{"oops": 1}]}, "<html>"):
            self.assertIsNone(pool.load_boxes(raw), raw)

    def test_url_can_be_overridden(self) -> None:
        self.assertIn("/automation-state/automation/playoff_pool/state/boxes.json", pool.boxes_url())
        with patch.dict(os.environ, {pool.URL_ENV: "https://example.invalid/boxes.json"}):
            self.assertEqual(pool.boxes_url(), "https://example.invalid/boxes.json")

    def test_league_data_caches_the_boxes(self) -> None:
        calls = []
        clock = [0.0]

        def loader():
            calls.append(1)
            return boxes_json()

        data = LeagueData(client=object(), league_id="x", clock=lambda: clock[0], pool_loader=loader)
        self.assertEqual(data.pool_boxes().year, 2027)
        data.pool_boxes()
        self.assertEqual(len(calls), 1)
        clock[0] += 11 * 60
        data.pool_boxes()
        self.assertEqual(len(calls), 2, "re-read after 10 minutes to pick up the deadline")
        self.assertIsNone(LeagueData(client=object(), league_id="x", pool_loader=lambda: None).pool_boxes())

    def test_failed_read_is_not_cached(self) -> None:
        state = {"fail": True}

        def loader():
            if state["fail"]:
                raise RuntimeError("raw.githubusercontent.com unreachable")
            return boxes_json()

        data = LeagueData(client=object(), league_id="x", pool_loader=loader)
        with self.assertRaises(RuntimeError):
            data.pool_boxes()
        state["fail"] = False
        self.assertIsNotNone(data.pool_boxes())


class ViewLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boxes = pool.load_boxes(boxes_json())

    def test_four_boxes_per_page(self) -> None:
        self.assertEqual([len(p) for p in pool.pages(self.boxes)], [4, 4, 2])

    def test_options_fit_discord_menus(self) -> None:
        for box in self.boxes.boxes:
            self.assertLessEqual(len(box.players), 25)
            for i, p in enumerate(box.players, 1):
                label, description = pool.option(i, p)
                self.assertLessEqual(len(label), 100)
                self.assertLessEqual(len(description), 100)
                self.assertTrue(label.startswith(f"{i}. "))

    def test_picks_content(self) -> None:
        mine = {b.number: b.players[0].id for b in self.boxes.boxes[:3]}
        text = pool.picks_content(self.boxes, "Franchise 2", mine, 0, 3)
        self.assertIn("3 of 10 boxes picked", text)
        self.assertIn("page 1 of 3", text)
        self.assertIn(f"<t:{int(FIRST_PUCK.timestamp())}:F>", text)
        full = {b.number: b.players[0].id for b in self.boxes.boxes}
        self.assertIn("All set.", pool.picks_content(self.boxes, "F", full, 2, 3))
        open_ended = pool.load_boxes(boxes_json(deadline=None))
        self.assertIn("time not published yet", pool.picks_content(open_ended, "F", {}, 0, 3))

    def test_boxes_embed_fits(self) -> None:
        embed = pool.boxes_embed(self.boxes)
        self.assertTrue(embeds.fits([embed]))
        self.assertEqual(len(embed["fields"]), 10)
        self.assertIn("/pool pick", embed["description"])

    def test_valid_pick_and_lock(self) -> None:
        box3 = self.boxes.box(3)
        self.assertTrue(pool.valid_pick(self.boxes, 3, box3.players[0].id))
        self.assertFalse(pool.valid_pick(self.boxes, 4, box3.players[0].id))
        self.assertFalse(pool.valid_pick(self.boxes, 11, box3.players[0].id))
        self.assertFalse(self.boxes.locked(FIRST_PUCK - timedelta(minutes=1)))
        self.assertTrue(self.boxes.locked(FIRST_PUCK))


class StoreAndExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s = Store(":memory:")
        self.boxes = pool.load_boxes(boxes_json())

    def tearDown(self) -> None:
        self.s.db.close()

    def pick_all(self, franchise: str, start: datetime, option: int = 0) -> None:
        for i, box in enumerate(self.boxes.boxes):
            self.s.pool_pick(2027, franchise, box.number, box.players[option].id, 7, now=start + timedelta(minutes=i),
                             box_count=10)

    def test_entry_time_is_when_the_last_box_was_first_filled(self) -> None:
        start = datetime(2027, 4, 16, 1, 0, tzinfo=UTC)
        self.pick_all("Franchise 2", start)
        done = start + timedelta(minutes=9)
        later = start + timedelta(hours=5)
        changed = self.boxes.box(1).players[3].id
        self.assertEqual(self.s.pool_pick(2027, "Franchise 2", 1, changed, 8, now=later, box_count=10), 10)
        rows = self.s.pool_entries(2027)
        self.assertEqual(len(rows), 1)
        name, picks, entered = rows[0]
        self.assertEqual((name, picks[1], entered), ("Franchise 2", changed, done))
        self.assertTrue(any(r["action"] == "pool_pick" for r in self.s.audit()))

    def test_entries_are_kept_per_year_and_franchise(self) -> None:
        self.s.pool_pick(2027, "Franchise 3", 1, self.boxes.box(1).players[0].id, 9, now=NOW, box_count=10)
        self.s.pool_pick(2026, "Franchise 3", 1, 1, 9, now=NOW, box_count=10)
        self.pick_all("Franchise 5", NOW)
        rows = self.s.pool_entries(2027)
        self.assertEqual([(r[0], len(r[1]), r[2] is None) for r in rows],
                         [("Franchise 5", 10, False), ("Franchise 3", 1, True)])
        self.assertEqual(self.s.pool_picks(2026, "Franchise 3"), {1: 1})

    def test_export_is_read_back_by_the_automation(self) -> None:
        self.pick_all("Franchise 1", datetime(2027, 4, 16, 2, 0, tzinfo=UTC), option=2)
        self.pick_all("Franchise 4", datetime(2027, 4, 15, 23, 0, tzinfo=UTC), option=1)
        self.s.pool_pick(2027, "Franchise 9", 10, self.boxes.box(10).players[5].id, 3, now=NOW, box_count=10)
        rows = self.s.pool_entries(2027)
        text = pool.export_text(self.boxes, rows)
        parsed = entries.parse(yaml.safe_load(text), self.boxes, NY)
        self.assertEqual([e.owner for e in parsed.entries], ["Franchise 4", "Franchise 1", "Franchise 9"])
        self.assertEqual(parsed.entries[1].picks, {b.number: b.players[2].id for b in self.boxes.boxes})
        self.assertEqual(parsed.entries[0].entered, datetime(2027, 4, 15, 23, 9, tzinfo=UTC))
        self.assertIsNone(parsed.entries[2].entered)
        self.assertEqual(parsed.late, [])
        note = pool.export_note(self.boxes, rows, NOW)
        self.assertIn("3 entries (2 complete)", note)
        self.assertIn("export again after the deadline", note)
        self.assertNotIn("export again", pool.export_note(self.boxes, rows, FIRST_PUCK))


@unittest.skipUnless(importlib.util.find_spec("discord") and importlib.util.find_spec("discord.ui"),
                     "discord.py not installed")
class DiscordPoolViewTests(unittest.TestCase):
    """Runs in GitHub Actions, where discord.py is installed."""

    def test_picks_view_builds(self) -> None:
        import asyncio

        import discord
        from blha_vote.app import PoolPicksView, VoteBot

        boxes = pool.load_boxes(boxes_json())

        async def build():
            bot = VoteBot(load(HERE.parent / "config.yaml"), Store(":memory:"))
            bot.store.pool_pick(2027, "Franchise 2", 2, boxes.box(2).players[1].id, 7, now=NOW, box_count=10)
            return (PoolPicksView(bot, boxes, "Franchise 2"), PoolPicksView(bot, boxes, "Franchise 2", page=2))

        first, last = asyncio.run(build())
        selects = [c for c in first.children if isinstance(c, discord.ui.Select)]
        self.assertEqual((len(selects), len(first.children)), (4, 6))  # four menus plus Previous and Next
        self.assertEqual(len(selects[0].options), 8)
        self.assertEqual([o.default for o in selects[1].options], [False, True] + [False] * 6)
        last_selects = [c for c in last.children if isinstance(c, discord.ui.Select)]
        self.assertEqual([len(s.options) for s in last_selects], [8, 16])
        self.assertIn("1 of 10 boxes picked", first.content())


if __name__ == "__main__":
    unittest.main()
