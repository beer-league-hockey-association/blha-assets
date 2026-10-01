#!/usr/bin/env python3
"""Small offline regression checks for BLHA The Wire."""

from __future__ import annotations

import unittest

import engine
import wire


class WireRoutingTests(unittest.TestCase):
    def test_trade_analysis_stays_news(self) -> None:
        title = "NHL EDGE stats: impact of Marchenko-Knies trade"
        self.assertEqual(wire.classify_title(title, False), "nhl-news")

    def test_actual_trade_routes_transactions(self) -> None:
        title = "Bruins trade Example Player to Rangers"
        self.assertEqual(wire.classify_title(title, False), "nhl-transactions")

    def test_injury_has_priority_over_transaction_words(self) -> None:
        title = "Player will miss two weeks after injury following trade"
        self.assertEqual(wire.classify_title(title, False), "injury-report")


class WireFormattingTests(unittest.TestCase):
    def test_rfc_feed_timestamp_parses(self) -> None:
        value = "Wed, 01 Oct 2026 14:00:00 GMT"
        parsed = engine.published_timestamp(value)
        self.assertIsNotNone(parsed)
        self.assertTrue(str(parsed).endswith("+00:00"))

    def test_player_name_normalization(self) -> None:
        self.assertEqual(
            engine.normalize_player_name("José Example Jr."),
            engine.normalize_player_name("Jose Example"),
        )


if __name__ == "__main__":
    unittest.main()
