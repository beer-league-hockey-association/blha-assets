#!/usr/bin/env python3
"""Channel names in messages match the server: python tools/test_discord_channels.py"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_channels as c  # noqa: E402
import discohook_format as fmt  # noqa: E402


class ChannelNames(unittest.TestCase):
    def test_full_name(self):
        self.assertEqual(c.name("game-day"), "🏒│game-day")
        self.assertEqual(c.ref("league-suggestions"), "**💡│league-suggestions**")
        self.assertEqual(c.CATEGORY_OF["lineup-alerts"], "🏆 LEAGUE COMPETITION")
        self.assertEqual(c.CATEGORY_OF["owner-handbook"], "🧑🏻‍⚖️ COMMISSIONER'S OFFICE")

    def test_every_name_uses_the_bar(self):
        for slug in c.EMOJI:
            self.assertRegex(c.name(slug), r"^\S+│[a-z]+(-[a-z]+)*$", slug)

    def test_new_channels_have_unused_emoji(self):
        others = {e for s, e in c.EMOJI.items() if s not in c.NEW_CHANNELS}
        for slug in c.NEW_CHANNELS:
            self.assertNotIn(c.EMOJI[slug], others, slug)

    def test_restyle_short_forms(self):
        self.assertEqual(c.restyle("Debate in **gm-lounge**."), "Debate in **💬│gm-lounge**.")
        self.assertEqual(c.restyle("Posts to #game-day daily"), "Posts to **🏒│game-day** daily")
        self.assertEqual(c.restyle("in the rulings-log channel"), "in the ⚖️│rulings-log channel")
        self.assertEqual(c.restyle("📜 **constitution** — rules"), "**📜│constitution** — rules")
        self.assertEqual(c.restyle("• **media** for clips"), "• **📸│media** for clips")

    def test_restyle_leaves_other_text(self):
        for text in ("game-day talk", "The consolation-bracket champion", "[Standings](#standings)",
                     "**Franchise Owner**", "**💬│gm-lounge**", "https://x.test/#game-day"):
            self.assertEqual(c.restyle(text), text)

    def test_restyle_is_idempotent(self):
        once = c.restyle("Use **rules-questions** or #open-a-ticket in the league-ledger channel")
        self.assertEqual(c.restyle(once), once)
        self.assertEqual(c.plain_references(once), [])

    def test_format_rewrites_and_flags(self):
        embed = {"title": "T", "description": "Talk in **news-desk**.", "footer": {"text": "F"}}
        out = fmt.apply([embed])
        self.assertIn("**💬│news-desk**", out[0]["description"])
        self.assertEqual(fmt.problems(out), [])
        flagged = fmt.problems([{**out[0], "description": "Talk in **news-desk**."}])
        self.assertTrue(any("short channel name" in p for p in flagged))


class FooterOnLastMessageOnly(unittest.TestCase):
    """Messages sent back to back: only the last one has footer text and the divider."""

    def test_constitution_sequence(self):
        order = fmt.sequence("constitution")
        self.assertEqual(order[0], "league-office/01_constitution_channel_intro.json")
        self.assertTrue(all(fmt.continues(r) for r in order[:-1]))
        self.assertFalse(fmt.continues(order[-1]))
        self.assertFalse(fmt.continues("league-office/02_announcements_channel_intro.json"))

    def test_continuing_message_has_no_footer(self):
        embed = {"title": "T", "description": "D", "footer": {"text": "SIGN OFF"}}
        out = fmt.apply([embed], cont=True)
        self.assertNotIn("footer", out[0])
        self.assertNotIn("image", out[0])
        self.assertEqual(fmt.problems(out, cont=True), [])
        self.assertTrue(fmt.problems(fmt.apply([embed]), cont=True))
        self.assertTrue(fmt.problems(out, cont=False))


if __name__ == "__main__":
    unittest.main(verbosity=1)
