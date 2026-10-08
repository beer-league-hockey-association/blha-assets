#!/usr/bin/env python3
"""Offline tests for the BLHA League Bot's voting rules (no Discord connection needed)."""

from __future__ import annotations

import importlib.util
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from blha_vote import embeds, rules  # noqa: E402
from blha_vote.config import load  # noqa: E402
from blha_vote.store import Store  # noqa: E402

UTC = timezone.utc
NOW = datetime(2028, 5, 1, 12, tzinfo=UTC)
S = rules.Settings(amendment_votes_from=datetime(2028, 4, 10, tzinfo=UTC),
                   dues_deadlines={2029: datetime(2029, 6, 30, tzinfo=UTC)})


def league(orphan: str | None = None) -> list[rules.Franchise]:
    return [rules.Franchise(f"F{i}", 100 + i, commissioner=(i == 1), orphaned=(f"F{i}" == orphan))
            for i in range(1, 13)]


class EligibilityTests(unittest.TestCase):
    def test_amendment_all_twelve_vote(self) -> None:
        self.assertEqual(len(rules.eligible(league(), rules.KINDS["amendment"])), 12)

    def test_services_excludes_commissioner(self) -> None:
        names = [f.name for f in rules.eligible(league(), rules.KINDS["services"])]
        self.assertEqual(len(names), 11)
        self.assertNotIn("F1", names)

    def test_no_commissioner_removal_vote(self) -> None:
        # The Constitution has no Commissioner removal (Article XIX).
        self.assertNotIn("removal", rules.KINDS)

    def test_orphan_has_no_vote(self) -> None:
        names = [f.name for f in rules.eligible(league("F5"), rules.KINDS["amendment"])]
        self.assertNotIn("F5", names)

    def test_only_franchise_owner_casts(self) -> None:
        kind = rules.KINDS["amendment"]
        f, why = rules.can_cast({102}, owner_role_id=999, franchises=league(), kind=kind)
        self.assertIsNone(f)
        self.assertIn("Franchise Owner", why)
        f, why = rules.can_cast({102, 999}, owner_role_id=999, franchises=league(), kind=kind)
        self.assertEqual(f.name, "F2")

    def test_two_franchise_roles_refused(self) -> None:
        f, why = rules.can_cast({102, 103, 999}, 999, league(), rules.KINDS["amendment"])
        self.assertIsNone(f)
        self.assertIn("more than one", why)

    def test_commissioner_franchise_refused_on_services(self) -> None:
        f, why = rules.can_cast({101, 999}, 999, league(), rules.KINDS["services"])
        self.assertIsNone(f)
        f, _ = rules.can_cast({101, 999}, 999, league(), rules.KINDS["amendment"])
        self.assertEqual(f.name, "F1")


class OpeningTests(unittest.TestCase):
    amend = rules.KINDS["amendment"]

    def problems(self, **kw):
        base = dict(now=NOW, phase="offseason", proposal_posted_at=NOW - timedelta(days=8),
                    effective_season=2029, settings=S)
        base.update(kw)
        return rules.open_problems(self.amend, **base)

    def test_clean_open(self) -> None:
        self.assertEqual(self.problems(), ([], []))

    def test_active_season_blocks(self) -> None:
        blocking, _ = self.problems(phase="regular")
        self.assertTrue(any("Offseason" in b for b in blocking))

    def test_fantrax_down_fails_closed(self) -> None:
        blocking, _ = self.problems(phase=None)
        self.assertTrue(blocking)

    def test_notice_period(self) -> None:
        blocking, _ = self.problems(proposal_posted_at=NOW - timedelta(days=6))
        self.assertTrue(any("7 days" in b for b in blocking))
        self.assertEqual(self.problems(proposal_posted_at=NOW - timedelta(days=7))[0], [])

    def test_charter_lock(self) -> None:
        blocking, _ = self.problems(now=datetime(2028, 4, 1, tzinfo=UTC),
                                    proposal_posted_at=datetime(2028, 3, 20, tzinfo=UTC))
        self.assertTrue(any("20.1" in b for b in blocking))

    def test_window_must_end_before_week_one(self) -> None:
        blocking, _ = self.problems(phase="preseason", next_season_start=NOW + timedelta(days=5))
        self.assertTrue(any("Active Season" in b for b in blocking))

    def test_dues_deadline(self) -> None:
        late = datetime(2029, 6, 28, tzinfo=UTC)
        blocking, _ = self.problems(now=late, proposal_posted_at=late - timedelta(days=10))
        self.assertTrue(any("dues deadline" in b for b in blocking))

    def test_unknown_deadline_warns(self) -> None:
        blocking, warnings = self.problems(effective_season=2030)
        self.assertEqual(blocking, [])
        self.assertTrue(warnings)

    def test_election_any_time(self) -> None:
        blocking, _ = rules.open_problems(rules.KINDS["interim"], now=NOW, phase="regular",
                                          proposal_posted_at=None, effective_season=None, settings=S)
        self.assertEqual(blocking, [])


class TallyTests(unittest.TestCase):
    def test_eight_yes_passes_out_of_twelve(self) -> None:
        ballots = {f"F{i}": rules.YES for i in range(1, 9)}
        out = rules.tally(rules.KINDS["amendment"], ballots, league(), S)
        self.assertTrue(out.passed)
        self.assertEqual(len(out.not_voted), 4)

    def test_seven_yes_and_abstentions_fail(self) -> None:
        ballots = {f"F{i}": rules.YES for i in range(1, 8)}
        ballots.update({"F8": rules.ABSTAIN, "F9": rules.ABSTAIN})
        self.assertFalse(rules.tally(rules.KINDS["amendment"], ballots, league(), S).passed)

    def test_threshold_unchanged_with_orphan(self) -> None:
        ballots = {f"F{i}": rules.YES for i in range(1, 8)}
        self.assertFalse(rules.tally(rules.KINDS["amendment"], ballots, league("F12"), S).passed)

    def test_commissioner_ballot_ignored_on_services(self) -> None:
        ballots = {f"F{i}": rules.YES for i in range(1, 9)}  # includes F1 (Commissioner)
        out = rules.tally(rules.KINDS["services"], ballots, league(), S)
        self.assertEqual(out.counts[rules.YES], 7)
        self.assertFalse(out.passed)

    def test_election_needs_majority_of_active(self) -> None:
        opts = ["Alex", "Sam"]
        ballots = {f"F{i}": "Alex" for i in range(1, 7)}  # 6 of 12 is not a majority
        out = rules.tally(rules.KINDS["interim"], ballots, league(), S, opts)
        self.assertIsNone(out.winner)
        ballots["F7"] = "Alex"
        self.assertEqual(rules.tally(rules.KINDS["interim"], ballots, league(), S, opts).winner, "Alex")


class PanelTests(unittest.TestCase):
    def test_draws_three_unaffected_franchises(self) -> None:
        pool = {f"F{i}": [1000 + i] for i in range(1, 13)}
        picks = rules.draw_panel(pool, {"F2", "F3"}, random.Random(1))
        self.assertEqual(len(picks), 3)
        self.assertEqual(len({p[0] for p in picks}), 3)
        self.assertFalse({"F2", "F3"} & {p[0] for p in picks})

    def test_too_few_owners(self) -> None:
        pool = {"F1": [1], "F2": [2], "F3": []}
        with self.assertRaises(ValueError):
            rules.draw_panel(pool, set(), random.Random(1))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s = Store(":memory:")

    def test_proposal_vote_ballot_lifecycle(self) -> None:
        pid = self.s.add_proposal(title="T", affected_rule="10.5", replacement="x", effective_season=2029,
                                  kind="amendment", proposed_by="F2", user_id=7, now=NOW)
        vid = self.s.open_vote(kind="amendment", title="T", question="Q", options=[], proposal_id=pid,
                               effective="Season 2029", user_id=1, now=NOW, closes_at=NOW + timedelta(days=7))
        self.assertEqual(self.s.proposal(pid)["status"], "voting")
        self.assertFalse(self.s.cast(vid, "F2", rules.YES, 7, now=NOW))
        self.assertTrue(self.s.cast(vid, "F2", rules.NO, 7, now=NOW))
        self.assertEqual(self.s.ballots(vid), {"F2": rules.NO})
        self.assertEqual(self.s.due_to_close(NOW + timedelta(days=6)), [])
        self.assertEqual(len(self.s.due_to_close(NOW + timedelta(days=7))), 1)
        self.s.close_vote(vid, {"passed": False}, now=NOW)
        self.assertEqual(self.s.proposal(pid)["status"], "failed")
        self.assertEqual(self.s.open_votes(), [])
        self.assertGreaterEqual(len(self.s.audit()), 4)

    def test_reminder_once(self) -> None:
        vid = self.s.open_vote(kind="interim", title="R", question="Q", options=[], proposal_id=None,
                               effective=None, user_id=1, now=NOW, closes_at=NOW + timedelta(days=7))
        later = NOW + timedelta(days=6, hours=1)
        self.assertEqual([v["id"] for v in self.s.due_reminder(later, 24)], [vid])
        self.s.mark_reminded(vid)
        self.assertEqual(self.s.due_reminder(later, 24), [])

    def test_orphans(self) -> None:
        self.s.set_orphaned("F4", True, 1, now=NOW)
        self.assertEqual(self.s.orphaned(), {"F4"})
        self.s.set_orphaned("F4", False, 1, now=NOW)
        self.assertEqual(self.s.orphaned(), set())


class EmbedTests(unittest.TestCase):
    def test_vote_and_result_fit_discord_limits(self) -> None:
        v = {"id": 3, "title": "T" * 100, "question": "Q" * 900, "closes_at": NOW, "effective": "Season 2029"}
        kind = rules.KINDS["amendment"]
        e = embeds.vote_open(v, kind, rules.threshold_text(kind, S, league()), [], ["note"])
        out = rules.tally(kind, {f"F{i}": rules.YES for i in range(1, 9)}, league(), S)
        r = embeds.result(v, kind, out, {f"F{i}": rules.YES for i in range(1, 9)})
        for embed in (e, r):
            self.assertTrue(all(len(f["value"]) <= 1024 for f in embed["fields"]))
            self.assertLess(len(embed["description"]) + sum(len(f["value"]) for f in embed["fields"]), 6000)
            self.assertNotIn("Version", str(embed))
        self.assertIn("PASSED", str(r))
        self.assertIn("F12: not voted", str(r))

    def test_threshold_texts(self) -> None:
        self.assertIn("8 affirmative votes out of 12", rules.threshold_text(rules.KINDS["amendment"], S, league()))
        self.assertIn("other 11", rules.threshold_text(rules.KINDS["services"], S, league()))
        self.assertIn("at least 7", rules.threshold_text(rules.KINDS["interim"], S, league()))


class ConfigTests(unittest.TestCase):
    def test_shipped_config_loads(self) -> None:
        cfg = load(HERE.parent / "config.yaml")
        self.assertEqual(len(cfg.franchises), 12)
        self.assertEqual(sum(f.commissioner for f in cfg.franchises), 1)
        self.assertEqual(cfg.settings.threshold, 8)
        self.assertTrue(cfg.problems)  # IDs are blank until set up


@unittest.skipUnless(importlib.util.find_spec("discord"), "discord.py not installed")
class DiscordSmokeTests(unittest.TestCase):
    """Runs in GitHub Actions, where discord.py is installed."""

    def test_commands_register(self) -> None:
        from blha_vote.app import VoteBot
        bot = VoteBot(load(HERE.parent / "config.yaml"), Store(":memory:"))
        commands = {c.name: c for c in bot.tree.get_commands()}
        self.assertEqual(set(commands), {"proposal", "vote", "franchise", "panel", "pickem", "pool",
                                         "rule", "deadlines", "minor", "myteam", "tradecheck"})
        self.assertEqual({c.name for c in commands["pool"].commands}, {"boxes", "pick", "export"})
        self.assertTrue(commands["pool"].guild_only)
        self.assertEqual({c.name for c in commands["vote"].commands}, {"open", "elect", "status", "cancel"})
        self.assertEqual({c.name for c in commands["proposal"].commands}, {"new", "from-thread"})
        self.assertEqual({c.name for c in commands["pickem"].commands}, {"leaderboard"})
        for name in ("rule", "deadlines", "minor", "myteam", "tradecheck"):
            self.assertTrue(commands[name].guild_only, name)
        self.assertEqual([p.name for p in commands["tradecheck"].parameters],
                         ["team_a", "team_b", "a_players", "a_picks", "b_players", "b_picks", "to_minors", "post"])
        self.assertEqual({p.name: p.required for p in commands["rule"].parameters}, {"query": True, "ephemeral": False})

    def test_league_views_build(self) -> None:
        import asyncio
        import json

        import discord
        from blha_vote import pickem
        from blha_vote.app import PickemPicksView, PickemPostView, ProposalModal, VoteBot
        from blha_vote.shared import FIXTURES

        info = json.loads((FIXTURES / "league_info_2026_test.json").read_text(encoding="utf-8"))
        matchups = pickem.matchups(info, 1)

        async def build():
            bot = VoteBot(load(HERE.parent / "config.yaml"), Store(":memory:"))
            return (PickemPostView(bot), PickemPicksView(bot, "L:2026", 1, matchups, NOW, 7),
                    PickemPicksView(bot, "L:2026", 1, matchups, NOW, 7, page=1),
                    ProposalModal(bot, "amendment", "Commissioner", title_default="T" * 150))

        post, first, second, modal = asyncio.run(build())
        self.assertTrue(post.is_persistent())
        self.assertEqual([c.custom_id for c in post.children], ["blha:pickem:make"])
        selects = [c for c in first.children if isinstance(c, discord.ui.Select)]
        self.assertEqual((len(selects), len(first.children)), (4, 6))  # four menus plus Previous and Next
        self.assertTrue(all(len(s.options) == 2 for s in selects))
        self.assertEqual(len(second.children), 4)
        self.assertEqual(modal.prop_title.default, "T" * 100)

    def test_ballot_view_builds(self) -> None:
        import asyncio
        from blha_vote.app import VoteBot, VoteView

        async def build():
            bot = VoteBot(load(HERE.parent / "config.yaml"), Store(":memory:"))
            yes_no = VoteView(bot, {"id": 1, "kind": "amendment", "options": "[]"})
            menu = VoteView(bot, {"id": 2, "kind": "interim", "options": '["Alex", "Sam"]'})
            return yes_no, menu

        yes_no, menu = asyncio.run(build())
        self.assertEqual([i.custom_id for i in yes_no.children],
                         ["blha:vote:1:yes", "blha:vote:1:no", "blha:vote:1:abstain"])
        self.assertEqual(len(menu.children[0].options), 3)


if __name__ == "__main__":
    unittest.main()
