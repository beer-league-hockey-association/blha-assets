#!/usr/bin/env python3
"""Small offline regression checks for BLHA The Wire."""

from __future__ import annotations

import unittest

import engine
import roster_enrichment
import wire


class WireRoutingTests(unittest.TestCase):
    def test_trade_analysis_stays_news(self) -> None:
        title = "NHL EDGE stats: impact of Marchenko-Knies trade"
        self.assertEqual(wire.classify_title(title, False), "nhl-news")

    def test_trade_question_stays_news(self) -> None:
        title = "Would Connor Hellebuyck consider a trade to the Oilers?"
        self.assertEqual(wire.classify_title(title, False), "nhl-news")

    def test_actual_trade_routes_transactions(self) -> None:
        title = "Bruins trade Example Player to Rangers"
        self.assertEqual(wire.classify_title(title, False), "nhl-transactions")

    def test_injury_has_priority_over_transaction_words(self) -> None:
        title = "Player will miss two weeks after injury following trade"
        self.assertEqual(wire.classify_title(title, False), "injury-report")

    def test_out_for_games_routes_injury(self) -> None:
        title = "Dylan Larkin out for Red Wings' first two games"
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


class FantraxRosterEnrichmentTests(unittest.TestCase):
    def test_roster_items_resolve_through_player_ids(self) -> None:
        rosters = {
            "period": 1,
            "rosters": {
                "team-a": {
                    "teamName": "Test 3",
                    "rosterItems": [
                        {"id": "player-1", "position": "C", "status": "ACTIVE"},
                        {"id": "player-2", "position": "D", "status": "RESERVE"},
                    ],
                }
            },
        }
        players = {
            "player-1": {"fantraxId": "player-1", "name": "José Example Jr."},
            "player-2": {"fantraxId": "player-2", "name": "Second Player"},
        }
        ownership = roster_enrichment.ownership_from_payloads(rosters, players)
        self.assertEqual(
            ownership[roster_enrichment.normalize_player_name("Jose Example")],
            "Test 3",
        )
        self.assertEqual(
            ownership[roster_enrichment.normalize_player_name("Second Player")],
            "Test 3",
        )


if __name__ == "__main__":
    unittest.main()
