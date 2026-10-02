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


_TEAMS = ("Bruins", "Canucks", "Flames", "Kraken", "Lightning", "Oilers", "Predators",
          "Rangers", "Sabres", "Senators", "Stars", "Wild", "Jets")
_EVENTS = ("lands on injured reserve", "returns to practice", "named starter tonight",
           "assigned to minors", "signs extension", "scores twice in win", "suspended two games",
           "activated from waivers", "misses morning skate", "called up from AHL",
           "fined for embellishment", "out with illness", "wins faceoff record")


def _candidate(n: int, channel: str = "injury-report", title: str | None = None) -> dict:
    default_title = f"{_TEAMS[n % len(_TEAMS)]} {channel.split('-')[0]} note: {_EVENTS[(n * 5) % len(_EVENTS)]}"
    return {
        "key": f"key-{channel}-{n}",
        "title": title or default_title,
        "link": f"https://example.test/story/{channel}/{n}",
        "published": "",
        "source_id": "test_source",
        "source_name": "Test Source",
        "source_detail": "",
        "tier": 1,
        "channel": channel,
        "discovery_only": False,
        "dedupe_by_url": True,
        "player": "",
        "team": "",
        "status": "",
        "fantasy_owner": "",
    }


class WireRoundupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[dict] = []
        self.roundups: list[tuple[str, dict]] = []
        self._deliver = engine.deliver
        self._post = engine.post_payload
        engine.deliver = lambda candidate: self.sent.append(candidate) or True
        engine.post_payload = lambda channel, payload: self.roundups.append((channel, payload)) or True

    def tearDown(self) -> None:
        engine.deliver = self._deliver
        engine.post_payload = self._post

    def test_overflow_becomes_one_roundup_not_dropped(self) -> None:
        state = engine.empty_state()
        counts = engine.process_candidates([_candidate(i) for i in range(7)], state, "live")
        self.assertEqual(len(self.sent), engine.MAX_LIVE_POSTS_PER_CHANNEL)
        self.assertEqual(len(self.roundups), 1)
        channel, payload = self.roundups[0]
        self.assertEqual(channel, "injury-report")
        self.assertIn("4 more updates", payload["embeds"][0]["title"])
        self.assertEqual(counts["digested"], 4)
        self.assertEqual(counts["suppressed"], 0)
        self.assertEqual(len(state["seen"]), 7)

    def test_failed_roundup_is_retried_next_run(self) -> None:
        engine.post_payload = lambda channel, payload: False
        state = engine.empty_state()
        engine.process_candidates([_candidate(i) for i in range(5)], state, "live")
        # Only the three individually delivered stories are remembered.
        self.assertEqual(len(state["seen"]), 3)

        # Next run: the three delivered stories are duplicates, and the two
        # leftovers fit under the per-channel limit, so they post individually.
        engine.post_payload = lambda channel, payload: self.roundups.append((channel, payload)) or True
        self.sent.clear()
        engine.process_candidates([_candidate(i) for i in range(5)], state, "live")
        self.assertEqual([c["key"] for c in self.sent], ["key-injury-report-3", "key-injury-report-4"])
        self.assertEqual(self.roundups, [])
        self.assertEqual(len(state["seen"]), 5)

    def test_duplicates_inside_overflow_are_caught(self) -> None:
        state = engine.empty_state()
        batch = [_candidate(i) for i in range(3)]
        batch.append(_candidate(10, title="Star winger out week-to-week with upper-body injury"))
        batch.append(_candidate(11, title="Star winger out week-to-week with upper body injury"))
        engine.process_candidates(batch, state, "live")
        self.assertIn("1 more update", self.roundups[0][1]["embeds"][0]["title"])

    def test_run_wide_cap_spills_other_channels_into_roundups(self) -> None:
        state = engine.empty_state()
        batch = [_candidate(i, "injury-report") for i in range(3)]
        batch += [_candidate(i, "nhl-news") for i in range(3)]
        batch += [_candidate(i, "prospect-wire") for i in range(2)]
        engine.process_candidates(batch, state, "live")
        self.assertEqual(len(self.sent), engine.MAX_LIVE_POSTS_PER_RUN)
        self.assertEqual([c for c, _ in self.roundups], ["prospect-wire"])

    def test_roundup_fits_discord_limit_and_counts_hidden(self) -> None:
        items = [_candidate(i, title=("Very long headline " * 12) + str(i)) for i in range(60)]
        payload, shown = engine.digest_payload("nhl-news", items)
        description = payload["embeds"][0]["description"]
        self.assertLessEqual(len(description), 4096)
        self.assertLess(shown, 60)
        self.assertIn(f"+{60 - shown} more not shown", description)

    def test_roundup_link_text_is_safe(self) -> None:
        item = _candidate(1, title="[Report] Player (LW) out")
        item["link"] = "https://example.test/a_(b)"
        payload, _ = engine.digest_payload("injury-report", [item])
        description = payload["embeds"][0]["description"]
        self.assertIn("[(Report) Player (LW) out](https://example.test/a_(b%29)", description)

    def test_roundup_keeps_blha_roster_tag(self) -> None:
        item = _candidate(1)
        item["fantasy_owner"] = "Team Example"
        payload, _ = engine.digest_payload("injury-report", [item])
        self.assertIn("BLHA roster:** Team Example", payload["embeds"][0]["description"])


if __name__ == "__main__":
    unittest.main()
