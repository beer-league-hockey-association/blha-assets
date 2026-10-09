#!/usr/bin/env python3
"""Offline tests for the League Bot's Playoff Pool commands (/pool boxes, /pool pick, /pool export).

Boxes are built by the automation's own code (automation/playoff_pool) from the
synthetic NHL fixture, saved and re-read the way the bot gets boxes.json. The
Discord views are checked only where discord.py is installed (GitHub Actions).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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

    def test_max_age_re_reads_a_cached_copy(self) -> None:
        calls = []
        clock = [0.0]
        served = [boxes_json(deadline=None)]

        def loader():
            calls.append(1)
            return served[0]

        data = LeagueData(client=object(), league_id="x", clock=lambda: clock[0], pool_loader=loader)
        self.assertIsNone(data.pool_boxes().deadline)
        served[0] = boxes_json()                       # the automation has since published the deadline
        clock[0] += 30
        self.assertIsNone(data.pool_boxes(pool.RECHECK_SECONDS).deadline)  # 30 s old: still fresh enough
        clock[0] += 31
        self.assertEqual(data.pool_boxes(pool.RECHECK_SECONDS).deadline, FIRST_PUCK)
        self.assertEqual(len(calls), 2)
        clock[0] += 5 * 60
        data.pool_boxes()
        self.assertEqual(len(calls), 2, "the re-read starts a new 10-minute TTL")


class EntriesViaTests(unittest.TestCase):
    """playoff_pool.entries_via in automation/league.yaml decides whether the bot takes picks."""

    def test_reads_the_league_setting(self) -> None:
        self.assertEqual(pool.entries_via({"playoff_pool": {"entries_via": "bot"}}), pool.BOT)
        self.assertEqual(pool.entries_via({"playoff_pool": {"entries_via": "dm"}}), pool.DM)
        self.assertEqual(pool.entries_via({"playoff_pool": {}}), pool.DM)      # the automation's default
        self.assertEqual(pool.entries_via({}), pool.DM)
        with self.assertRaises(ValueError):
            pool.entries_via({"playoff_pool": {"entries_via": "email"}})

    def test_shipped_league_yaml(self) -> None:
        from blha.league import load_league
        via = pool.entries_via(load_league())
        self.assertIn(via, (pool.BOT, pool.DM))
        self.assertEqual(LeagueData(client=object(), league_id="x").pool_entries_via(), via)

    def test_league_data_falls_back_to_dm(self) -> None:
        bot = LeagueData(client=object(), league_id="x", league_loader=lambda: {"playoff_pool": {"entries_via": "bot"}})
        self.assertEqual(bot.pool_entries_via(), pool.BOT)
        for broken in ({"playoff_pool": {"entries_via": "email"}}, None):
            def loader(raw=broken):
                if raw is None:
                    raise OSError("league.yaml missing")
                return raw
            self.assertEqual(LeagueData(client=object(), league_id="x", league_loader=loader).pool_entries_via(),
                             pool.DM)

    def test_boxes_post_follows_the_setting(self) -> None:
        boxes = pool.load_boxes(boxes_json())
        self.assertIn("/pool pick", pool.boxes_embed(boxes, pool.BOT)["description"])
        dm = pool.boxes_embed(boxes, pool.DM)["description"]
        self.assertNotIn("/pool pick", dm)
        self.assertIn("DM your picks to the Commissioner", dm)
        for text in (pool.DM_ENTRIES, dm):
            self.assertNotIn("github", text.lower())
            self.assertNotIn("http", text)


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
        note = pool.export_note(self.boxes, rows)
        self.assertIn("3 entries (2 complete)", note)
        self.assertNotIn("Ignored", note)

    def test_no_export_before_the_deadline(self) -> None:
        """The Commissioner enters too: before the first puck drop the export would show them every entry."""
        refusal = pool.export_refusal(self.boxes, FIRST_PUCK - timedelta(seconds=1))
        self.assertIn("Picks are still open", refusal)
        self.assertIn(f"<t:{int(FIRST_PUCK.timestamp())}:F>", refusal)
        self.assertIn("Lock in your own picks", refusal)
        self.assertIsNone(pool.export_refusal(self.boxes, FIRST_PUCK))
        unknown = pool.load_boxes(boxes_json(deadline=None))
        self.assertIn("hasn't published the first puck drop", pool.export_refusal(unknown, FIRST_PUCK + timedelta(days=9)))

    def test_only_picks_made_before_the_deadline_count(self) -> None:
        box1, box2 = self.boxes.box(1), self.boxes.box(2)
        before, after = FIRST_PUCK - timedelta(hours=2), FIRST_PUCK + timedelta(minutes=5)
        # Franchise 2 is complete before the puck drop, then changes box 1 twice and box 2 once afterwards.
        self.pick_all("Franchise 2", FIRST_PUCK - timedelta(days=1))
        self.s.pool_pick(2027, "Franchise 2", 1, box1.players[4].id, 7, now=before, box_count=10)
        self.s.pool_pick(2027, "Franchise 2", 1, box1.players[5].id, 7, now=after, box_count=10)
        self.s.pool_pick(2027, "Franchise 2", 1, box1.players[6].id, 7, now=after + timedelta(minutes=1), box_count=10)
        self.s.pool_pick(2027, "Franchise 2", 2, box2.players[3].id, 7, now=FIRST_PUCK, box_count=10)  # at the drop: late
        # Franchise 6 has nine boxes before the puck drop and fills box 10 only after it.
        for box in self.boxes.boxes[:9]:
            self.s.pool_pick(2027, "Franchise 6", box.number, box.players[1].id, 8, now=before, box_count=10)
        self.s.pool_pick(2027, "Franchise 6", 10, self.boxes.box(10).players[0].id, 8, now=after, box_count=10)
        # Franchise 9 only ever picked after the puck drop.
        self.s.pool_pick(2027, "Franchise 9", 3, self.boxes.box(3).players[0].id, 9, now=after, box_count=10)

        self.assertEqual(self.s.pool_picks(2027, "Franchise 2")[1], box1.players[6].id)  # what the menus show
        rows = {name: (picks, entered) for name, picks, entered in self.s.pool_entries(2027, deadline=FIRST_PUCK)}
        self.assertEqual(set(rows), {"Franchise 2", "Franchise 6"})
        picks, entered = rows["Franchise 2"]
        self.assertEqual((picks[1], picks[2]), (box1.players[4].id, box2.players[0].id))  # in place at the drop
        self.assertEqual(entered, FIRST_PUCK - timedelta(days=1) + timedelta(minutes=9))
        picks, entered = rows["Franchise 6"]
        self.assertEqual((len(picks), 10 in picks, entered), (9, False, None))  # incomplete when picks locked
        late = self.s.pool_late_picks(2027, FIRST_PUCK)
        self.assertEqual(late, [("Franchise 2", 1), ("Franchise 2", 2), ("Franchise 6", 10), ("Franchise 9", 3)])

        rows = self.s.pool_entries(2027, deadline=FIRST_PUCK)
        parsed = entries.parse(yaml.safe_load(pool.export_text(self.boxes, rows)), self.boxes, NY)
        self.assertEqual([e.owner for e in parsed.entries], ["Franchise 2", "Franchise 6"])  # nobody dropped as late
        self.assertEqual(parsed.late, [])
        note = pool.export_note(self.boxes, rows, late)
        self.assertIn("2 entries (1 complete)", note)
        self.assertIn("Ignored 4 picks made after the deadline (Franchise 2 box 1, Franchise 2 box 2, "
                      "Franchise 6 box 10, Franchise 9 box 3)", note)


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


# ------------------------------------------------------------ Discord flows (CI)
OWNER, CO_OWNER, COMMISH = 900, 901, 902


class Reply:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.edited: list[dict] = []
        self.deferred = False

    async def send_message(self, content=None, **kw) -> None:
        self.sent.append((content, kw))

    async def edit_message(self, **kw) -> None:
        self.edited.append(kw)

    async def defer(self, **kw) -> None:
        self.deferred = True

    async def send(self, content=None, **kw) -> None:  # followup
        self.sent.append((content, kw))


class FakeInteraction:
    def __init__(self, uid: int, role_ids: set[int]) -> None:
        self.user = SimpleNamespace(id=uid, roles=[SimpleNamespace(id=r) for r in role_ids])
        self.response, self.followup = Reply(), Reply()
        self.original_edits: list[dict] = []
        self.message = self.guild = self.channel = None

    async def edit_original_response(self, **kw) -> None:
        self.original_edits.append(kw)

    def replies(self) -> list:
        return [c for c, _ in self.response.sent + self.followup.sent]


@unittest.skipUnless(importlib.util.find_spec("discord") and importlib.util.find_spec("discord.ui"),
                     "discord.py not installed")
class DiscordPoolFlowTests(unittest.TestCase):
    """/pool pick, the pick menus and /pool export through the slash commands (where discord.py is installed)."""

    def make_bot(self, via: str, served: list):
        from blha_vote.app import VoteBot
        cfg = load(HERE.parent / "config.yaml")
        cfg.owner_role_id, cfg.co_owner_role_id, cfg.commissioner_role_id = OWNER, CO_OWNER, COMMISH
        cfg.franchises = [replace(f, role_id=100 + i) for i, f in enumerate(cfg.franchises, 1)]
        data = LeagueData(client=object(), league_id="x", clock=lambda: self.clock[0],
                          pool_loader=lambda: served[0], league_loader=lambda: {"playoff_pool": {"entries_via": via}})
        return VoteBot(cfg, Store(":memory:"), data=data)

    @staticmethod
    def command(bot, name: str):
        return next(c for c in bot.tree.get_commands() if c.name == "pool").get_command(name)

    def setUp(self) -> None:
        self.clock = [0.0]

    def test_dm_year_turns_the_bot_entries_off(self) -> None:
        import blha_vote.app as app

        async def run():
            with patch.object(app, "utcnow", lambda: NOW):
                bot = self.make_bot("dm", [boxes_json()])
                i = FakeInteraction(7, {OWNER, 102})
                await self.command(bot, "pick").callback(i)
                self.assertEqual(i.replies(), [pool.DM_ENTRIES])
                i = FakeInteraction(1, {OWNER, 101, COMMISH})
                await self.command(bot, "export").callback(i)
                self.assertEqual(i.replies(), [pool.DM_EXPORT])
                i = FakeInteraction(8, set())
                await self.command(bot, "boxes").callback(i)
                self.assertIn("DM your picks", i.followup.sent[-1][1]["embed"].description)
                bot.store.db.close()

        asyncio.run(run())

    def test_pick_and_export_around_the_deadline(self) -> None:
        import blha_vote.app as app
        now = [NOW]
        served = [boxes_json(deadline=None)]          # boxes posted before the NHL published the first puck drop

        async def run():
            with patch.object(app, "utcnow", lambda: now[0]):
                bot = self.make_bot("bot", served)
                commish = FakeInteraction(1, {OWNER, 101, COMMISH})
                await self.command(bot, "export").callback(commish)
                self.assertIn("hasn't published the first puck drop", commish.replies()[-1])
                self.assertNotIn("file", commish.followup.sent[-1][1])
                i = FakeInteraction(7, {OWNER, 102})
                await self.command(bot, "pick").callback(i)
                view = i.followup.sent[-1][1]["view"]
                self.assertIsNone(view.boxes.deadline)
                box1 = view.boxes.box(1)
                # The deadline is published: a pick before it is saved through the deferred response.
                served[0] = boxes_json()
                self.clock[0] += pool.RECHECK_SECONDS + 1
                i = FakeInteraction(7, {OWNER, 102})
                await bot.save_pool_pick(i, view, 1, box1.players[2].id)
                self.assertTrue(i.response.deferred)
                self.assertIn("1 of 10 boxes picked", i.original_edits[-1]["content"])
                self.assertEqual(bot.store.pool_picks(2027, "Franchise 2"), {1: box1.players[2].id})
                # A menu opened while the deadline was unknown can't change a pick after the puck drop.
                stale = app.PoolPicksView(bot, pool.load_boxes(boxes_json(deadline=None)), "Franchise 2")
                now[0] = FIRST_PUCK + timedelta(minutes=3)
                self.clock[0] += pool.RECHECK_SECONDS + 1
                i = FakeInteraction(7, {OWNER, 102})
                await bot.save_pool_pick(i, stale, 1, box1.players[5].id)
                self.assertIn("locked", i.original_edits[-1]["content"])
                self.assertIsNone(i.original_edits[-1]["view"])
                self.assertEqual(bot.store.pool_picks(2027, "Franchise 2"), {1: box1.players[2].id})
                # Can't check the file: the pick isn't saved.
                stale = app.PoolPicksView(bot, pool.load_boxes(boxes_json(deadline=None)), "Franchise 2")
                bot.data._pool_loader = lambda: (_ for _ in ()).throw(RuntimeError("offline"))
                self.clock[0] += pool.RECHECK_SECONDS + 1
                i = FakeInteraction(7, {OWNER, 102})
                await bot.save_pool_pick(i, stale, 2, view.boxes.box(2).players[0].id)
                self.assertIn("wasn't saved", i.followup.sent[-1][0])
                self.assertEqual(len(bot.store.pool_picks(2027, "Franchise 2")), 1)
                bot.data._pool_loader = lambda: served[0]
                # A late pick that got in anyway (say the file had no deadline yet) is left out of the export.
                bot.store.pool_pick(2027, "Franchise 2", 1, box1.players[7].id, 7, now=now[0], box_count=10)
                commish = FakeInteraction(1, {OWNER, 101, COMMISH})
                await self.command(bot, "export").callback(commish)
                note, kw = commish.followup.sent[-1]
                self.assertIn("Ignored 1 pick made after the deadline (Franchise 2 box 1)", note)
                text = kw["file"].fp.read().decode("utf-8")
                self.assertEqual(entries.parse(yaml.safe_load(text), pool.load_boxes(served[0]), NY).entries[0].picks,
                                 {1: box1.players[2].id})
                # Only the Commissioner exports.
                i = FakeInteraction(7, {OWNER, 102})
                await self.command(bot, "export").callback(i)
                self.assertIn("Only the Commissioner", i.replies()[-1])
                bot.store.db.close()

        asyncio.run(run())

    def test_export_waits_for_the_deadline(self) -> None:
        import blha_vote.app as app

        async def run():
            with patch.object(app, "utcnow", lambda: NOW):
                bot = self.make_bot("bot", [boxes_json()])
                bot.store.pool_pick(2027, "Franchise 2", 1, 1, 7, now=NOW, box_count=10)
                commish = FakeInteraction(1, {OWNER, 101, COMMISH})
                await self.command(bot, "export").callback(commish)
                self.assertIn("Picks are still open", commish.replies()[-1])
                self.assertNotIn("file", commish.followup.sent[-1][1])
                self.assertFalse(any(r["action"] == "pool_export" for r in bot.store.audit()))
                bot.store.db.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
