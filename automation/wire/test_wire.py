#!/usr/bin/env python3
"""Small offline regression checks for BLHA The Wire."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import engine
import roster
import wire

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


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


    def test_season_ending_injury_is_breaking(self) -> None:
        for title in ("Romanov likely to miss rest of season with torn ACL",
                      "Islanders D Alexander Romanov out six to eight months with torn ACL"):
            self.assertEqual(wire.classify_title(title, True), "breaking-news", title)
            self.assertEqual(wire.classify_title(title, False), "injury-report", title)

    def test_short_absence_is_injury_not_breaking(self) -> None:
        title = "Hughes out 2-3 weeks with lower-body injury"
        self.assertEqual(wire.classify_title(title, True), "injury-report")
        self.assertEqual(wire.classify_title("Kucherov out two weeks", True), "injury-report")

    def test_season_talk_without_absence_stays_news(self) -> None:
        for title in ("What to expect from the Maple Leafs the rest of the season",
                      "NHL's romance-themed audiobooks disappear after opening week of season"):
            self.assertEqual(wire.classify_title(title, True), "nhl-news", title)


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
            wire._rss_entry_link(entry),
            "https://www.sportsnet.ca/nhl/article/example-story/",
        )

    def test_rss_link_can_use_http_guid(self) -> None:
        entry = {
            "link": "",
            "links": [],
            "guid": "https://www.sportsnet.ca/nhl/article/guid-story/",
        }
        self.assertEqual(
            wire._rss_entry_link(entry),
            "https://www.sportsnet.ca/nhl/article/guid-story/",
        )

    def test_rss_link_does_not_invent_url_from_non_http_guid(self) -> None:
        entry = {"link": "", "links": [], "guid": "sportsnet:story:12345"}
        self.assertEqual(wire._rss_entry_link(entry), "")

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
            roster.normalize_player_name("José Example Jr."),
            roster.normalize_player_name("Jose Example"),
        )

    def test_fantrax_last_first_name_normalization(self) -> None:
        self.assertEqual(
            roster.normalize_player_name("Larkin, Dylan"),
            roster.normalize_player_name("Dylan Larkin"),
        )


class RosterTagTests(unittest.TestCase):
    """Real Fantrax player entries, including players who share a name."""

    @classmethod
    def setUpClass(cls) -> None:
        players = json.loads((FIXTURES / "player_ids_sample.json").read_text())
        rosters = {"period": 1, "rosters": {
            "team-a": {"teamName": "Alpha", "rosterItems": [{"id": "03rmx"}, {"id": "03duf"}]},   # Aho (CAR C), Larkin
            "team-b": {"teamName": "Bravo", "rosterItems": [{"id": "060v8"}, {"id": "05rin"}]},   # Pettersson (VAN D), Hughes (LAK)
            "team-c": {"teamName": "Charlie", "rosterItems": [{"id": "01ztp"}, {"id": "02un4"}]},  # Hyman, McDavid
        }}
        cls.index = roster.build_index(rosters, players)

    def test_same_name_different_team(self) -> None:
        self.assertEqual(self.index.match("Sebastian Aho", "CAR", "C").owner_name, "Alpha")
        self.assertIsNone(self.index.match("Sebastian Aho", "PIT", "D"))  # the other Aho is a free agent

    def test_same_name_same_team_uses_position(self) -> None:
        self.assertEqual(self.index.match("Elias Pettersson", "VAN", "D").owner_name, "Bravo")
        self.assertIsNone(self.index.match("Elias Pettersson", "VAN", "C"))

    def test_ambiguous_without_team_is_not_tagged(self) -> None:
        self.assertIsNone(self.index.match("Sebastian Aho"))
        self.assertIsNone(self.index.match("Jack Hughes"))

    def test_team_alias_and_forward_positions(self) -> None:
        self.assertEqual(self.index.match("Jack Hughes", "LA", "C").owner_name, "Bravo")
        # Daily Faceoff lists Hyman at LW; Fantrax has RW. Both are forwards.
        self.assertEqual(self.index.match("Zach Hyman", "EDM", "LW").owner_name, "Charlie")

    def test_headline_scan_tags_unique_names_only(self) -> None:
        found = self.index.scan("Dylan Larkin and Connor McDavid named stars of the week")
        self.assertEqual(sorted(p.owner_name for p in found), ["Alpha", "Charlie"])
        self.assertEqual(self.index.scan("Sebastian Aho scores twice as Hurricanes win"), [])

    def test_tagging_injury_and_news_candidates(self) -> None:
        injury = _candidate(1, "injury-report")
        injury.update(player="Elias Pettersson", team="VAN", position="D")
        news = _candidate(2, "nhl-news", title="Dylan Larkin extends point streak to nine games")
        tagged = roster.tag_candidates([injury, news], self.index)
        self.assertEqual(tagged, 2)
        self.assertEqual(injury["fantasy_owner"], "Bravo")
        self.assertEqual(news["fantasy_owner"], "Alpha (Dylan Larkin)")

    def test_owner_pings_are_opt_in_and_injury_only(self) -> None:
        injury = _candidate(1, "injury-report")
        injury["owners"] = [{"team_id": "team-b", "team_name": "Bravo", "player": "Elias Pettersson"}]
        league = {"owners": {"Bravo": "123456789012345678"}, "wire_pings": {"injuries": True}}
        self.assertEqual(roster.owner_mentions(injury, league), ["123456789012345678"])
        self.assertEqual(roster.owner_mentions(injury, {"owners": {}, "wire_pings": {"injuries": True}}), [])
        news = dict(injury, channel="nhl-news")
        self.assertEqual(roster.owner_mentions(news, league), [])

    def test_ping_payload_only_allows_listed_users(self) -> None:
        item = _candidate(1, "injury-report")
        item["mentions"] = ["123456789012345678"]
        payload = engine.discord_payload(item)
        self.assertEqual(payload["content"], "<@123456789012345678>")
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": ["123456789012345678"]})

    def test_no_ping_by_default(self) -> None:
        payload = engine.discord_payload(_candidate(1, "injury-report"))
        self.assertNotIn("content", payload)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})


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

    def test_rostered_players_get_individual_posts_first(self) -> None:
        state = engine.empty_state()
        batch = [_candidate(i) for i in range(5)]
        batch[4]["owners"] = [{"team_id": "t", "team_name": "Alpha", "player": "X"}]
        engine.process_candidates(batch, state, "live")
        self.assertEqual(self.sent[0]["key"], batch[4]["key"])

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


class WireNewSourceTests(unittest.TestCase):
    def cand(self, source_id: str, key: str) -> dict:
        return {"key": key, "title": f"Episode {key} of a hockey podcast", "link": f"https://example.com/{key}",
                "channel": "media", "source_id": source_id, "tier": 2, "discovery_only": False}

    def test_new_baseline_first_source_posts_nothing_on_first_run(self) -> None:
        cfg = {"sources": [{"id": "pod_a", "baseline_first": True, "force_channel": "media"},
                           {"id": "news", "force_channel": "nhl-news"}]}
        state = {"initialized": True, "seen": []}
        first = engine.baseline_new_sources([self.cand("pod_a", "1"), self.cand("news", "2")], cfg, state)
        self.assertEqual([c["source_id"] for c in first], ["news"])
        self.assertEqual(state["known_sources"], ["pod_a"])
        self.assertEqual([r["source_id"] for r in state["seen"]], ["pod_a"])
        later = engine.baseline_new_sources([self.cand("pod_a", "3")], cfg, state)
        self.assertEqual([c["key"] for c in later], ["3"])

    def test_podcast_sources_route_to_media(self) -> None:
        import yaml
        cfg = yaml.safe_load((Path(__file__).resolve().parent / "sources.yaml").read_text(encoding="utf-8"))
        pods = [s for s in cfg["sources"] if s.get("role") == "podcast-episodes"]
        self.assertTrue(pods)
        for s in pods:
            self.assertEqual(wire.route("Anything at all", s), "media")
            self.assertTrue(s.get("baseline_first"))
        self.assertIn("media", engine.WEBHOOK_ENV)


if __name__ == "__main__":
    unittest.main()
