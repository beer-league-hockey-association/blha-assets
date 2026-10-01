#!/usr/bin/env python3
"""Small offline regression checks for BLHA The Wire."""

from __future__ import annotations

import unittest

import engine
import roster_enrichment
import wire
import run_wire  # applies production routing/enrichment/source adapters


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


class WireSourceTests(unittest.TestCase):
    def test_rss_link_recovers_alternate_href(self) -> None:
        entry = {
            "link": "",
            "links": [
                {"rel": "enclosure", "href": "https://cdn.example.test/audio.mp3"},
                {"rel": "alternate", "href": "https://www.sportsnet.ca/nhl/article/example-story/"},
            ],
            "id": "sportsnet-guid-123",
        }
        self.assertEqual(
            run_wire._rss_entry_link(entry),
            "https://www.sportsnet.ca/nhl/article/example-story/",
        )

    def test_rss_link_can_use_http_guid(self) -> None:
        entry = {
            "link": "",
            "links": [],
            "guid": "https://www.sportsnet.ca/nhl/article/guid-story/",
        }
        self.assertEqual(
            run_wire._rss_entry_link(entry),
            "https://www.sportsnet.ca/nhl/article/guid-story/",
        )

    def test_rss_link_does_not_invent_url_from_non_http_guid(self) -> None:
        entry = {"link": "", "links": [], "guid": "sportsnet:story:12345"}
        self.assertEqual(run_wire._rss_entry_link(entry), "")

    def test_sportsnet_live_tracker_is_ignored(self) -> None:
        title = "Maple Leafs Live Tracker: Toronto vs. New York Islanders"
        self.assertTrue(wire.should_ignore(title, "sportsnet_nhl", "nhl-news"))

    def test_normal_sportsnet_story_is_not_ignored(self) -> None:
        title = "Rebuilding Flames still to feature plenty of feel-good stories"
        self.assertFalse(wire.should_ignore(title, "sportsnet_nhl", "nhl-news"))


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

    def test_fantrax_last_first_name_normalization(self) -> None:
        self.assertEqual(
            roster_enrichment.normalize_player_name("Larkin, Dylan"),
            roster_enrichment.normalize_player_name("Dylan Larkin"),
        )


class FantraxRosterEnrichmentTests(unittest.TestCase):
    def test_roster_items_resolve_through_player_ids(self) -> None:
        rosters = {
            "period": 1,
            "rosters": {
                "team-a": {
                    "teamName": "Test 3",
                    "rosterItems": [
                        {"id": "wire-key-1", "position": "C", "status": "ACTIVE"},
                        {"id": "wire-key-2", "position": "D", "status": "RESERVE"},
                    ],
                }
            },
        }
        # Live getPlayerIds commonly uses the roster ID as the root key while
        # the nested fantraxId is a different alias. Both must resolve.
        players = {
            "wire-key-1": {"fantraxId": "alternate-1", "name": "Example, José Jr."},
            "wire-key-2": {"fantraxId": "alternate-2", "name": "Second, Player"},
        }
        ownership = roster_enrichment.ownership_from_payloads(rosters, players)
        self.assertEqual(
            ownership[roster_enrichment.normalize_player_name("Jose Example")],
            "Test 3",
        )
        self.assertEqual(
            ownership[roster_enrichment.normalize_player_name("Player Second")],
            "Test 3",
        )

    def test_nested_fantrax_id_is_also_an_alias(self) -> None:
        index = roster_enrichment.player_name_index(
            {"wire-key": {"fantraxId": "nested-id", "name": "Larkin, Dylan"}}
        )
        self.assertEqual(index["wire-key"], "Larkin, Dylan")
        self.assertEqual(index["nested-id"], "Larkin, Dylan")


if __name__ == "__main__":
    unittest.main()
