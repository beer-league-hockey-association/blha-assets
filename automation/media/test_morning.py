#!/usr/bin/env python3
"""Offline checks for the BLHA Morning Skate.

Fixtures (automation/tests/fixtures/) are SYNTHETIC, hand-built in the shapes
of the NHL score API and the NHL YouTube channel feed: six final games on
2026-10-07 (one OT, one shootout, missing links), a postponed and a preseason
game, and a feed with per-game highlight videos, Shorts and other clips.
Fantrax: two small made-up rosters in the getTeamRosters / getPlayerIds shapes.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import morning  # noqa: E402

ET = ZoneInfo("America/New_York")
NIGHT = date(2026, 10, 7)
FIXTURES = HERE.parent / "tests" / "fixtures"
SCORE = json.loads((FIXTURES / "nhl_score_2026-10-07_synthetic.json").read_text(encoding="utf-8"))
FEED = (FIXTURES / "nhl_youtube_feed_synthetic.xml").read_text(encoding="utf-8")
MORNING = datetime(2026, 10, 8, 8, 35, tzinfo=ET).astimezone(timezone.utc)
LEAGUE = {"league_id": "test", "timezone": "America/New_York", "season_label": "2026-27 TEST", "color": 0xFFB81C,
          "morning_skate": {"enabled": True, "post_time": "08:30", "max_youtube": 3, "include_goal_reel": True}}

ROSTERS = {"period": 9, "rosters": {
    "t1": {"teamName": "Ice Holes", "rosterItems": [{"id": "mcd"}, {"id": "ovi"}, {"id": "epc"}]},
    "t2": {"teamName": "Puck Bunnies", "rosterItems": [{"id": "drai"}, {"id": "jh"}, {"id": "lh"}, {"id": "suz"}]},
    "t3": {"teamName": "Empty Nets", "rosterItems": []},
}}
EMPTY_ROSTERS = {"period": 9, "rosters": {
    "t1": {"teamName": "Ice Holes", "rosterItems": []},
    "t2": {"teamName": "Puck Bunnies", "rosterItems": []},
}}
PLAYERS = {
    "mcd": {"fantraxId": "mcd", "name": "McDavid, Connor", "position": "C", "team": "EDM"},
    "drai": {"fantraxId": "drai", "name": "Draisaitl, Leon", "position": "C", "team": "EDM"},
    "hym": {"fantraxId": "hym", "name": "Hyman, Zach", "position": "RW", "team": "EDM"},          # unrostered
    "ovi": {"fantraxId": "ovi", "name": "Ovechkin, Alex", "position": "LW", "team": "WSH"},
    "epc": {"fantraxId": "epc", "name": "Pettersson, Elias", "position": "C", "team": "VAN"},
    "epd": {"fantraxId": "epd", "name": "Pettersson, Elias", "position": "D", "team": "VAN"},    # same name, same team
    "qh": {"fantraxId": "qh", "name": "Hughes, Quinn", "position": "D", "team": "VAN"},          # unrostered
    "jh": {"fantraxId": "jh", "name": "Hughes, Jack", "position": "C", "team": "NJD"},
    "lh": {"fantraxId": "lh", "name": "Hughes, Luke", "position": "D", "team": "NJD"},
    "suz": {"fantraxId": "suz", "name": "Suzuki, Nick", "position": "C", "team": "MTL"},
}


class FakeFantrax:
    def __init__(self, rosters: dict | None = None, fail: bool = False) -> None:
        self._rosters = ROSTERS if rosters is None else rosters
        self.fail = fail
        self.player_reads = 0

    def league_info(self) -> dict:
        return {"leagueName": "Dynasty Hockey Test League"}

    def rosters(self) -> dict:
        if self.fail:
            raise RuntimeError("Fantrax down")
        return self._rosters

    def player_ids(self) -> dict:
        self.player_reads += 1
        return PLAYERS


def quiet(fn, *args, **kwargs):
    out = io.StringIO()
    with redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


def games() -> list[morning.Game]:
    return morning.parse_scores(SCORE, NIGHT)


def by_label(items: list[morning.Game]) -> dict[str, morning.Game]:
    return {g.label: g for g in items}


def index(rosters: dict = ROSTERS):
    return morning.roster.build_index(rosters, PLAYERS)


class ParseTests(unittest.TestCase):
    def test_final_games_in_start_order(self):
        parsed = games()
        self.assertEqual([g.label for g in parsed],
                         ["PIT at WSH", "NYI at NJD", "TOR at MTL", "CHI at DAL", "VAN at SEA", "EDM at ANA"])
        # The postponed NYR-BOS game and the preseason UTA-SJS game are left out.
        self.assertNotIn("NYR at BOS", by_label(parsed))
        self.assertNotIn("UTA at SJS", by_label(parsed))
        self.assertEqual(morning.unfinished(SCORE), 0)
        wsh = by_label(parsed)["PIT at WSH"]
        self.assertEqual((wsh.away_score, wsh.home_score, wsh.outcome), (2, 5, ""))
        self.assertEqual(wsh.recap, "https://www.nhl.com/video/pit-at-wsh-recap-20260200051")
        self.assertEqual(len(wsh.goals), 7)
        first = wsh.goals[0]
        self.assertEqual((first.team, first.scorer.name, first.scorer.last), ("WSH", "Alex Ovechkin", "Ovechkin"))
        self.assertEqual([p.name for p in first.assists], ["John Carlson", "Dylan Strome"])
        self.assertTrue(first.clip.startswith("https://nhl.com/video/pit-wsh-ovechkin-scores"))

    def test_shootout_goals_do_not_count(self):
        mtl = by_label(games())["TOR at MTL"]
        self.assertEqual((mtl.home_score, mtl.outcome), (3, "SO"))
        self.assertEqual([g.scorer.last for g in mtl.goals], ["Matthews", "Caufield", "Nylander", "Slafkovsky"])

    def test_ot_and_so_labels(self):
        self.assertEqual(by_label(games())["EDM at ANA"].outcome, "OT")
        label = morning.outcome_label
        self.assertEqual(label({"gameOutcome": {"lastPeriodType": "REG"}}), "")
        self.assertEqual(label({"gameOutcome": {"lastPeriodType": "SO"}}), "SO")
        self.assertEqual(label({"gameOutcome": {"lastPeriodType": "OT"}, "periodDescriptor": {"number": 4}}), "OT")
        # Playoff multiple overtime, from otPeriods or from the period number.
        self.assertEqual(label({"gameOutcome": {"lastPeriodType": "OT", "otPeriods": 2}}), "2OT")
        self.assertEqual(label({"gameOutcome": {"lastPeriodType": "OT"}, "periodDescriptor": {"number": 6}}), "3OT")
        self.assertEqual(label({"gameOutcome": None, "periodDescriptor": {"number": 4, "periodType": "OT"}}), "OT")

    def test_links(self):
        self.assertEqual(morning.nhl_url("/video/pit-at-wsh-recap-6406449956112"),
                         "https://www.nhl.com/video/pit-at-wsh-recap-6406449956112")
        self.assertEqual(morning.nhl_url("https://www.nhl.com/video/x"), "https://www.nhl.com/video/x")
        self.assertEqual(morning.nhl_url("http://nhl.com/video/x"), "https://nhl.com/video/x")
        self.assertEqual(morning.nhl_url({"default": "/video/y"}), "https://www.nhl.com/video/y")
        self.assertEqual(morning.nhl_url(None), "")
        self.assertEqual(morning.nhl_url("javascript:alert(1)"), "")

    def test_game_lines_and_missing_links(self):
        lines = {g.label: morning.game_line(g) for g in games()}
        self.assertEqual(lines["EDM at ANA"],
                         "**EDM 3**, ANA 2 (OT) · [Recap](https://www.nhl.com/video/edm-at-ana-recap-20260200101)"
                         " · [Condensed](https://www.nhl.com/video/edm-at-ana-condensed-game-20260200102)")
        self.assertEqual(lines["TOR at MTL"],
                         "**MTL 3**, TOR 2 (SO) · [Recap](https://www.nhl.com/video/tor-at-mtl-recap-20260200071)")
        self.assertEqual(lines["VAN at SEA"], "**VAN 4**, SEA 1")
        self.assertTrue(lines["PIT at WSH"].startswith("**WSH 5**, PIT 2 · [Recap]"))

    def test_other_day_or_changed_api(self):
        self.assertEqual(morning.parse_scores(SCORE, date(2026, 10, 6)), [])
        with self.assertRaises(ValueError):
            morning.parse_scores({"currentDate": "2026-10-07"}, NIGHT)
        self.assertEqual(morning.parse_scores({"currentDate": "2026-10-07", "games": []}, NIGHT), [])


class SummaryTests(unittest.TestCase):
    look = morning.Look("Dynasty Hockey Test League", "2026-27 TEST", 0xFFB81C)

    def test_one_message_for_a_normal_night(self):
        messages = morning.summary_messages(self.look, games(), NIGHT, MORNING)
        self.assertEqual(len(messages), 1)
        body = messages[0]
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        self.assertEqual(body["username"], "BLHA News Wire")
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "LAST NIGHT IN THE NHL — Wednesday, October 7")
        self.assertTrue(embed["description"].startswith("**Dynasty Hockey Test League** • 2026-27 TEST\n*6 games final."))
        self.assertEqual(embed["footer"]["text"], "MORNING SKATE • NHL DATA")
        self.assertEqual(embed["color"], 0xFFB81C)

    def test_long_nights_split_within_discord_limits(self):
        long_url = "https://www.nhl.com/video/" + "a-very-long-recap-slug-" * 6
        many = [morning.Game(str(i), 2, f"A{i:02d}", f"H{i:02d}", 1, 4, "OT" if i % 3 else "",
                             recap=long_url + str(i), condensed=long_url + "c" + str(i)) for i in range(40)]
        messages = morning.summary_messages(self.look, many, NIGHT, MORNING)
        embeds = [e for m in messages for e in m["embeds"]]
        self.assertGreater(len(embeds), 1)
        for message in messages:
            self.assertLessEqual(sum(morning.embed_size(e) for e in message["embeds"]), morning.EMBED_TOTAL_LIMIT)
            self.assertLessEqual(len(message["embeds"]), morning.MAX_EMBEDS)
        for embed in embeds:
            self.assertLessEqual(len(embed["description"]), morning.DESCRIPTION_LIMIT)
        self.assertTrue(embeds[1]["title"].endswith("(continued)"))
        self.assertEqual([("footer" in e) for e in embeds], [False] * (len(embeds) - 1) + [True])
        text = "\n".join(e["description"] for e in embeds)
        for game in many:
            self.assertEqual(text.count(f"**H{int(game.game_id):02d} 4**"), 1)

    def test_playoff_nights_say_so(self):
        playoff = [morning.Game("1", 3, "EDM", "FLA", 2, 3, "2OT")]
        embed = morning.summary_messages(self.look, playoff, NIGHT, MORNING)[0]["embeds"][0]
        self.assertIn("*1 playoff game final.", embed["description"])
        self.assertIn("**FLA 3**, EDM 2 (2OT)", embed["description"])


class GoalReelTests(unittest.TestCase):
    look = morning.Look("Dynasty Hockey Test League", "2026-27 TEST", 0xFFB81C)

    def test_grouped_by_franchise(self):
        reel = morning.build_reel(games(), index())
        self.assertEqual(sorted(f.name for f in reel.franchises.values()), ["Ice Holes", "Puck Bunnies"])
        values = {f.name: morning.franchise_value(f) for f in reel.franchises.values()}
        self.assertEqual(values["Ice Holes"].split("\n"), [
            "McDavid (EDM) — goal [▶](https://nhl.com/video/edm-ana-mcdavid-scores-ot-winner-6406450000127), assist",
            "Ovechkin (WSH) — goal [▶](https://nhl.com/video/pit-wsh-ovechkin-scores-6406450000101)",
        ])
        self.assertEqual(values["Puck Bunnies"].split("\n"), [
            # Two Hugheses on one NHL team: full names. The second goal has no clip.
            "Jack Hughes (NJD) — 2 goals [▶](https://nhl.com/video/nyi-njd-j-hughes-scores-6406450000108)",
            "Draisaitl (EDM) — goal [▶](https://nhl.com/video/edm-ana-draisaitl-scores-6406450000124), assist",
            "Luke Hughes (NJD) — 2 assists",
            "Suzuki (MTL) — assist",  # his shootout goal does not count
        ])
        # Elias Pettersson is skipped: two VAN players share the name.
        self.assertNotIn("Pettersson", json.dumps(values))
        ids = {g.label: g.game_id for g in games()}
        self.assertEqual(reel.by_game, {ids["EDM at ANA"]: 4, ids["NYI at NJD"]: 4,
                                        ids["PIT at WSH"]: 1, ids["TOR at MTL"]: 1})

    def test_reel_message(self):
        reel = morning.build_reel(games(), index())
        messages = morning.reel_messages(self.look, reel, MORNING)
        self.assertEqual(len(messages), 1)
        embed = messages[0]["embeds"][0]
        self.assertEqual(embed["title"], "THE BLHA GOAL REEL")
        self.assertEqual([f["name"] for f in embed["fields"]], ["Puck Bunnies", "Ice Holes"])  # most points first
        self.assertEqual(messages[0]["allowed_mentions"], {"parse": []})
        self.assertNotIn("<@", json.dumps(messages))

    def test_omitted_when_nobody_is_rostered(self):
        fx = FakeFantrax(EMPTY_ROSTERS)
        idx, out = quiet(morning.load_index, fx)
        self.assertIsNone(idx)
        self.assertIn("no players on BLHA rosters", out)
        self.assertEqual(fx.player_reads, 0)
        reel = morning.build_reel(games(), idx)
        self.assertTrue(reel.empty)
        self.assertEqual(morning.reel_messages(self.look, reel, MORNING), [])

    def test_fantrax_failure_means_no_reel(self):
        idx, out = quiet(morning.load_index, FakeFantrax(fail=True))
        self.assertIsNone(idx)
        self.assertIn("no Goal Reel", out)

    def test_large_reels_split_within_discord_limits(self):
        reel = morning.Reel()
        for f in range(20):
            franchise = morning.Franchise(f"Franchise {f:02d}")
            for p in range(8):
                line = morning.ReelLine(f"Player{p}", f"First Player{p}", "EDM",
                                        clips=["https://nhl.com/video/" + "x" * 80], assists=1)
                franchise.lines[f"{f}-{p}"] = line
            reel.franchises[str(f)] = franchise
        messages = morning.reel_messages(self.look, reel, MORNING)
        self.assertGreater(len(messages), 1)
        names = []
        for message in messages:
            self.assertLessEqual(sum(morning.embed_size(e) for e in message["embeds"]), morning.EMBED_TOTAL_LIMIT)
            for embed in message["embeds"]:
                self.assertLessEqual(len(embed["fields"]), morning.MAX_FIELDS)
                for item in embed["fields"]:
                    self.assertLessEqual(len(item["value"]), morning.FIELD_LIMIT)
                    names.append(item["name"])
        self.assertEqual(len(names), 20)

    def test_first_name_variants_match_carefully(self):
        players = {"m1": {"fantraxId": "m1", "name": "Marner, Mitchell", "position": "RW", "team": "VGK"},
                   "s1": {"fantraxId": "s1", "name": "Smith, John", "position": "C", "team": "SJS"},
                   "h1": {"fantraxId": "h1", "name": "Hughes, Jack", "position": "C", "team": "NJD"},
                   "h2": {"fantraxId": "h2", "name": "Hughes, Jackson", "position": "D", "team": "NJD"}}
        rosters = {"rosters": {"t": {"teamName": "Ice Holes", "rosterItems": [{"id": "m1"}, {"id": "s1"}, {"id": "h1"}]}}}
        matcher = morning.Matcher(morning.roster.build_index(rosters, players))
        person = morning.Person
        self.assertEqual(matcher.match(person("1", "Mitch Marner", "Marner", "Mitch"), "VGK").player_id, "m1")
        self.assertIsNone(matcher.match(person("2", "Mitch Marner", "Marner", "Mitch"), "TOR"))   # other team
        self.assertIsNone(matcher.match(person("3", "Jack Smith", "Smith", "Jack"), "SJS"))       # different first name
        self.assertEqual(matcher.match(person("4", "Jack Hughes", "Hughes", "Jack"), "NJD").player_id, "h1")  # exact
        self.assertIsNone(matcher.match(person("5", "Jac Hughes", "Hughes", "Jac"), "NJD"))     # could be either


class YouTubeTests(unittest.TestCase):
    def test_parse_feed(self):
        videos = morning.parse_feed(FEED)
        self.assertEqual(len(videos), 10)
        self.assertEqual(videos[2].url, "https://www.youtube.com/watch?v=EdmAna07Hl1")
        self.assertTrue(videos[0].short and videos[1].short)
        with self.assertRaises(ValueError):
            morning.parse_feed("<html>not a feed</html>")
        with self.assertRaises(ValueError):
            morning.parse_feed("<rss><channel/></rss>")

    def test_title_matching(self):
        lookup = morning.team_lookup(games())

        def matchup(title, link="https://www.youtube.com/watch?v=abcdefghijk"):
            found = morning.highlight_matchup(morning.Video("abcdefghijk", title, link), lookup)
            return (sorted(found[0]), found[1]) if found else None

        self.assertEqual(matchup("Oilers vs. Ducks | NHL Highlights | Oct 7, 2026"), (["ANA", "EDM"], NIGHT))
        self.assertEqual(matchup("Maple Leafs vs. Canadiens | NHL Highlights | Oct 7, 2026"), (["MTL", "TOR"], NIGHT))
        self.assertEqual(matchup("Blue Jackets vs Golden Knights | NHL Highlights | Sept. 28, 2026"),
                         (["CBJ", "VGK"], date(2026, 9, 28)))
        self.assertEqual(matchup("Utah Mammoth vs. St. Louis Blues | NHL Highlights | October 7, 2026"),
                         (["STL", "UTA"], NIGHT))
        self.assertEqual(matchup("Oilers vs. Panthers | Game 3 | NHL Highlights | Jun 9, 2027"),
                         (["EDM", "FLA"], date(2027, 6, 9)))
        self.assertIsNone(matchup("Oilers vs. Ducks | NHL Highlights | Oct 7, 2026", "https://www.youtube.com/shorts/abcdefghijk"))
        self.assertIsNone(matchup("McDavid ends it in overtime #shorts"))
        self.assertIsNone(matchup("Blackhawks vs. Stars | Condensed Game | Oct 7, 2026"))
        self.assertIsNone(matchup("NHL Top 10 Saves of the Week | Week 1"))
        self.assertIsNone(matchup("Oilers vs. Mystery Club | NHL Highlights | Oct 7, 2026"))

    def test_ranking_by_blha_points_then_overtime_then_goals(self):
        parsed = games()
        videos = morning.parse_feed(FEED)
        reel = morning.build_reel(parsed, index())
        picks = morning.rank_highlights(parsed, videos, NIGHT, reel.by_game, 10)
        # EDM-ANA and NYI-NJD both have 4 BLHA points; EDM-ANA went to OT.
        # PIT-WSH and TOR-MTL both have 1; TOR-MTL went to a shootout.
        # CHI-DAL has no highlight video in the feed, so it is skipped.
        self.assertEqual([v.video_id for _, v in picks],
                         ["EdmAna07Hl1", "NyiNjd07Hl1", "TorMtl07Hl1", "PitWsh07Hl1", "VanSea07Hl1"])
        self.assertEqual(len(morning.rank_highlights(parsed, videos, NIGHT, reel.by_game, 3)), 3)
        self.assertEqual(morning.rank_highlights(parsed, videos, NIGHT, reel.by_game, 0), [])

    def test_ranking_without_blha_players(self):
        picks = morning.rank_highlights(games(), morning.parse_feed(FEED), NIGHT, {}, 10)
        # OT/SO first (TOR-MTL started earlier), then total goals: PIT-WSH 7, VAN-SEA 5, NYI-NJD 3.
        self.assertEqual([v.video_id for _, v in picks],
                         ["TorMtl07Hl1", "EdmAna07Hl1", "PitWsh07Hl1", "VanSea07Hl1", "NyiNjd07Hl1"])

    def test_videos_from_another_night_are_ignored(self):
        self.assertEqual(morning.rank_highlights(games(), morning.parse_feed(FEED), date(2026, 10, 6), {}, 3), [])

    def test_video_message_is_just_the_link(self):
        look = morning.Look("L", "S", 1)
        body = morning.video_message(look, morning.Video("EdmAna07Hl1", "t", ""))
        self.assertEqual(body["content"], "https://www.youtube.com/watch?v=EdmAna07Hl1")
        self.assertNotIn("embeds", body)
        self.assertEqual(body["allowed_mentions"], {"parse": []})


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "morning_skate.json"
        self.patch = patch.object(morning, "STATE_PATH", self.state)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_mode(self, mode="live", *, now=MORNING, league=LEAGUE, fx=None, score=SCORE, feed=FEED,
                 fail_on=None, night=None):
        """Run with fake NHL, YouTube and Discord; returns (code, output, posted bodies)."""
        posted, fetched = [], []

        def fake_send(secret, body):
            self.assertEqual(secret, "BLHA_WEBHOOK_MEDIA")
            if fail_on is not None and fail_on(body, len(posted)):
                return False, "Discord returned 500", None
            posted.append(body)
            return True, "delivered", str(len(posted))

        def fetch_text(url):
            fetched.append(url)
            if isinstance(feed, Exception):
                raise feed
            return feed

        with patch.object(morning, "send_discord_webhook", fake_send):
            code, out = quiet(morning.run, mode, now=now, league=league, fx=fx or FakeFantrax(),
                              fetch_json=lambda url: score, fetch_text=fetch_text, night=night)
        self.fetched = fetched
        return code, out, posted

    @staticmethod
    def kinds(posted):
        out = []
        for body in posted:
            if "content" in body:
                out.append(body["content"].rsplit("=", 1)[-1])
            else:
                out.append(body["embeds"][0]["title"])
        return out

    def test_posts_everything_once(self):
        code, out, posted = self.run_mode()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.kinds(posted), ["LAST NIGHT IN THE NHL — Wednesday, October 7", "THE BLHA GOAL REEL",
                                              "EdmAna07Hl1", "NyiNjd07Hl1", "TorMtl07Hl1"])
        saved = json.loads(self.state.read_text())["dates"]["2026-10-07"]
        self.assertEqual((saved["summary"], saved["reel"], saved["complete"]), (1, 1, True))
        self.assertEqual(saved["videos"], ["EdmAna07Hl1", "NyiNjd07Hl1", "TorMtl07Hl1"])

        later = datetime(2026, 10, 8, 11, 0, tzinfo=ET).astimezone(timezone.utc)
        code, out, posted = self.run_mode(now=later)
        self.assertEqual((code, posted), (0, []))
        self.assertIn("already posted", out)

    def test_failed_post_is_retried_without_repeats(self):
        fail_reel = lambda body, n: "embeds" in body and body["embeds"][0]["title"] == "THE BLHA GOAL REEL"
        code, out, posted = self.run_mode(fail_on=fail_reel)
        self.assertEqual(code, 1)
        self.assertIn("retried next run", out)
        self.assertEqual(len(posted), 1)
        saved = json.loads(self.state.read_text())["dates"]["2026-10-07"]
        self.assertEqual((saved["summary"], saved.get("reel"), saved.get("complete")), (1, None, None))

        code, _, posted = self.run_mode()
        self.assertEqual(code, 0)
        self.assertEqual(self.kinds(posted), ["THE BLHA GOAL REEL", "EdmAna07Hl1", "NyiNjd07Hl1", "TorMtl07Hl1"])

    def test_failed_video_post_resumes_with_the_rest(self):
        fail_second_video = lambda body, n: body.get("content", "").endswith("NyiNjd07Hl1")
        code, _, posted = self.run_mode(fail_on=fail_second_video)
        self.assertEqual(code, 1)
        self.assertEqual(len(posted), 3)
        code, _, posted = self.run_mode()
        self.assertEqual(code, 0)
        self.assertEqual(self.kinds(posted), ["NyiNjd07Hl1", "TorMtl07Hl1"])

    def test_youtube_outage_posts_the_rest_and_retries_videos(self):
        code, out, posted = self.run_mode(feed=RuntimeError("HTTP 503"))
        self.assertEqual(code, 1)
        self.assertIn("highlight videos will be retried", out)
        self.assertEqual(len(posted), 2)
        code, _, posted = self.run_mode()
        self.assertEqual(code, 0)
        self.assertEqual(self.kinds(posted), ["EdmAna07Hl1", "NyiNjd07Hl1", "TorMtl07Hl1"])

    def test_empty_rosters_post_no_goal_reel(self):
        fx = FakeFantrax(EMPTY_ROSTERS)
        code, out, posted = self.run_mode(fx=fx)
        self.assertEqual(code, 0)
        self.assertNotIn("THE BLHA GOAL REEL", self.kinds(posted))
        self.assertEqual(self.kinds(posted)[1:], ["TorMtl07Hl1", "EdmAna07Hl1", "PitWsh07Hl1"])
        self.assertEqual(fx.player_reads, 0)

    def test_goal_reel_can_be_turned_off(self):
        league = {**LEAGUE, "morning_skate": {**LEAGUE["morning_skate"], "include_goal_reel": False, "max_youtube": 1}}
        fx = FakeFantrax()
        code, _, posted = self.run_mode(league=league, fx=fx)
        self.assertEqual(code, 0)
        self.assertEqual(self.kinds(posted)[1:], ["TorMtl07Hl1"])
        self.assertEqual(fx.player_reads, 0)

    def test_no_videos_when_max_is_zero(self):
        league = {**LEAGUE, "morning_skate": {**LEAGUE["morning_skate"], "max_youtube": 0}}
        code, _, posted = self.run_mode(league=league)
        self.assertEqual(code, 0)
        self.assertEqual(len(posted), 2)
        self.assertEqual(self.fetched, [])
        self.assertTrue(json.loads(self.state.read_text())["dates"]["2026-10-07"]["complete"])

    def test_nothing_on_nights_without_finals(self):
        for score in ({"currentDate": "2026-10-07", "games": []},
                      {"currentDate": "2026-10-07", "games": [g for g in SCORE["games"] if g["gameState"] == "FUT"]}):
            code, out, posted = self.run_mode(score=score)
            self.assertEqual((code, posted), (0, []))
            self.assertIn("no final NHL games", out)
            self.assertFalse(self.state.exists())

    def test_waits_for_post_time_and_respects_enabled(self):
        early = datetime(2026, 10, 8, 7, 0, tzinfo=ET).astimezone(timezone.utc)
        code, out, posted = self.run_mode(now=early)
        self.assertEqual((code, posted), (0, []))
        self.assertIn("before 08:30", out)
        off = {**LEAGUE, "morning_skate": {**LEAGUE["morning_skate"], "enabled": False}}
        code, out, posted = self.run_mode(league=off)
        self.assertEqual((code, posted), (0, []))
        self.assertIn("enabled is false", out)

    def test_live_never_covers_a_night_still_in_progress(self):
        code, out, posted = self.run_mode(night=date(2026, 10, 8))
        self.assertEqual((code, posted), (0, []))
        self.assertIn("not over yet", out)

    def test_preview_and_test_modes_never_save_state(self):
        code, out, posted = self.run_mode("preview")
        self.assertEqual((code, posted), (0, []))
        self.assertIn('"LAST NIGHT IN THE NHL — Wednesday, October 7"', out)
        self.assertIn("https://www.youtube.com/watch?v=EdmAna07Hl1", out)
        code, _, posted = self.run_mode("test")
        self.assertEqual(code, 0)
        self.assertEqual(len(posted), 5)
        self.assertTrue(posted[0]["embeds"][0]["title"].startswith("[TEST] "))
        self.assertTrue(posted[2]["content"].startswith("[TEST] https://www.youtube.com/"))
        self.assertFalse(self.state.exists())

    def test_state_keeps_recent_dates_only(self):
        old = {f"2026-0{m}-{d:02d}": {"complete": True} for m in (7, 8) for d in range(1, 31)}
        self.state.write_text(json.dumps({"dates": old}))
        self.run_mode()
        dates = json.loads(self.state.read_text())["dates"]
        self.assertEqual(len(dates), morning.KEEP_DATES)
        self.assertIn("2026-10-07", dates)


class ConfigTests(unittest.TestCase):
    def test_league_yaml_section(self):
        cfg = yaml.safe_load((HERE.parent / "league.yaml").read_text(encoding="utf-8"))
        section = cfg["morning_skate"]
        self.assertEqual(set(section) >= {"enabled", "post_time", "max_youtube", "include_goal_reel"}, True)
        self.assertEqual(section.get("webhook", morning.DEFAULT_WEBHOOK), "BLHA_WEBHOOK_MEDIA")
        morning._clock(section["post_time"], morning.DEFAULT_POST_TIME)

    def test_scheduled_and_monitored(self):
        repo = HERE.parents[1]
        schedule = yaml.safe_load((HERE.parent / "scheduler" / "schedule.yaml").read_text(encoding="utf-8"))
        job = next(j for j in schedule["jobs"] if j["id"] == "morning-skate")
        self.assertEqual((job["workflow"], job["daily_at"]), ("blha-morning-skate.yml", ["08:30"]))
        self.assertNotIn("phases", job)  # all year: NHL playoffs run past the BLHA season
        health = yaml.safe_load((HERE.parent / "health" / "health_config.yaml").read_text(encoding="utf-8"))
        self.assertIn("blha-morning-skate.yml", [w["file"] for w in health["workflows"]])
        workflow = (repo / ".github" / "workflows" / "blha-morning-skate.yml").read_text(encoding="utf-8")
        self.assertIn("BLHA_WEBHOOK_MEDIA: ${{ secrets.BLHA_WEBHOOK_MEDIA }}", workflow)
        self.assertIn("automation/media/state/morning_skate.json", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=1)
