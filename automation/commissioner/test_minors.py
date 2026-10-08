#!/usr/bin/env python3
"""Offline checks for the minor-eligibility watch."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import minors  # noqa: E402

TODAY = date(2026, 10, 3)
minors.MIN_GAP = 0
minors.time.sleep = lambda *_: None


class FakeResponse:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def nhl_player(pid, first, last, birth):
    return {"id": pid, "firstName": {"default": first}, "lastName": {"default": last}, "birthDate": birth}


ROSTERS = {
    "EDM": {"forwards": [nhl_player(1, "Zachary", "Hyman", "1992-06-09"), nhl_player(2, "Young", "Guy", "2005-01-10")],
            "defensemen": [], "goalies": [nhl_player(3, "Pro", "Goalie", "2003-03-03")]},
}
GAMES = {1: 900, 2: 60, 3: 49}


class FakeSession:
    """Serves NHL data; `games` can be changed between runs."""

    def __init__(self):
        self.headers = {}
        self.games = dict(GAMES)

    def get(self, url, params=None, timeout=None):
        if "/roster/" in url:
            team = url.split("/roster/")[1].split("/")[0]
            return FakeResponse(ROSTERS.get(team, {"forwards": [], "defensemen": [], "goalies": []}))
        if "/prospects/" in url:
            return FakeResponse({}, 404)
        if "/landing" in url:
            pid = int(url.split("/player/")[1].split("/")[0])
            return FakeResponse({"birthDate": "2000-01-01", "careerTotals": {"regularSeason": {"gamesPlayed": self.games.get(pid, 0)}}})
        return FakeResponse([])


def rostered():
    return [
        {"fantraxId": "f1", "name": "Hyman, Zach", "position": "RW", "nhl_team": "EDM", "franchise": "Test 1"},
        {"fantraxId": "f2", "name": "Guy, Young", "position": "C", "nhl_team": "EDM", "franchise": "Test 2"},
        {"fantraxId": "f3", "name": "Goalie, Pro", "position": "G", "nhl_team": "EDM", "franchise": "Test 2"},
        {"fantraxId": "f9", "name": "Nobody, Known", "position": "D", "nhl_team": "EDM", "franchise": "Test 3"},
    ]


class RuleTests(unittest.TestCase):
    def test_age_is_birthday_aware(self):
        self.assertEqual(minors.age_on("2000-10-03", TODAY), 26)
        self.assertEqual(minors.age_on("2000-10-04", TODAY), 25)

    def test_age_is_fixed_on_season_start(self):
        from zoneinfo import ZoneInfo

        class Fx:
            def league_info(self):
                return {"scoringPeriods": [
                    {"number": 2, "startDate": "2027-10-11T00:00:00.0-0400", "endDate": "2027-10-17T23:59:59.0-0400"},
                    {"number": 1, "startDate": "2027-10-05T19:00:00.0-0400", "endDate": "2027-10-10T23:59:59.0-0400"},
                ]}

        tz = ZoneInfo("America/New_York")
        ref = minors.age_reference_date(Fx(), tz, date(2028, 2, 1))
        self.assertEqual(ref, date(2027, 10, 5))
        # Born Jan 15, 2002: 25 on opening day, so still eligible in February 2028.
        self.assertEqual(minors.age_on("2002-01-15", ref), 25)
        self.assertEqual(minors.age_on("2002-01-15", date(2028, 2, 1)), 26)

    def test_age_date_falls_back_to_today(self):
        class Broken:
            def league_info(self):
                raise RuntimeError("down")

        self.assertEqual(minors.age_reference_date(Broken(), None, date(2028, 2, 1)), date(2028, 2, 1))

    def test_eligibility_limits(self):
        self.assertTrue(minors.eligible(25, 100, False))
        self.assertFalse(minors.eligible(25, 101, False))
        self.assertFalse(minors.eligible(26, 0, False))
        self.assertTrue(minors.eligible(22, 50, True))
        self.assertFalse(minors.eligible(22, 51, True))

    def test_name_handling(self):
        self.assertEqual(minors.fantrax_name("Hyman, Zach"), ("Zach", "Hyman"))
        self.assertEqual(minors.norm("Tim Stützle Jr."), "timstutzle")


class ThrottleTests(unittest.TestCase):
    def test_429_is_retried(self):
        calls = []

        class Flaky:
            def get(self, url, params=None, timeout=None):
                calls.append(url)
                return FakeResponse({"ok": True}, 429 if len(calls) < 3 else 200)

        self.assertEqual(minors._get(Flaky(), "https://x/y"), {"ok": True})
        self.assertEqual(len(calls), 3)


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.index = minors.Index()
        for p in ROSTERS["EDM"]["forwards"]:
            self.index.add({"id": p["id"], "first": p["firstName"]["default"], "last": p["lastName"]["default"], "birthDate": p["birthDate"], "team": "EDM"})

    def test_nickname_matches_by_initial_and_team(self):
        self.assertEqual(self.index.find("Zach", "Hyman", "EDM")["id"], 1)

    def test_unknown_player_is_not_guessed(self):
        self.assertIsNone(self.index.find("Known", "Nobody", "EDM"))


class EvaluateTests(unittest.TestCase):
    def test_evaluate_and_crossing(self):
        session = FakeSession()
        index = minors.build_index(session)
        now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        with patch.object(minors, "search_player", lambda *a, **k: None):
            cur, unmatched = minors.evaluate(rostered(), index, session, {}, TODAY, now)
        self.assertEqual(unmatched, ["Nobody, Known"])
        self.assertFalse(cur["f1"]["eligible"])  # age 34
        self.assertTrue(cur["f2"]["eligible"])   # 21, 60 games
        self.assertTrue(cur["f3"]["eligible"])   # goalie, 49 games
        prev = {k: v["eligible"] for k, v in cur.items()}
        session.games[3] = 51
        cache = {}
        later = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
        with patch.object(minors, "search_player", lambda *a, **k: None):
            cur2, _ = minors.evaluate(rostered(), index, session, cache, TODAY, later)
        found = minors.crossed(prev, cur2)
        self.assertEqual([p["name"] for p in found], ["Goalie, Pro"])
        self.assertIn("51 career NHL games (limit 50)", minors.reason(found[0]))

    def test_ineligible_before_is_never_realerted(self):
        cur = {"f1": {"eligible": False, "franchise": "x", "name": "a"}}
        self.assertEqual(minors.crossed({"f1": False}, cur), [])
        self.assertEqual(minors.crossed({}, cur), [])


class RunTests(unittest.TestCase):
    def _run(self, session, saved=None, mode="live", ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "minors.json"
        if saved is not None:
            state.write_text(json.dumps(saved))
        posts = []

        class FakeFantrax:
            def __init__(self, *a, **k):
                pass

        def fake_post(secret, payload):
            posts.append(payload)
            return ok, "delivered" if ok else "boom"

        with patch.object(minors, "STATE_PATH", state), patch.object(minors, "Fantrax", FakeFantrax), \
                patch.object(minors, "load_rostered", lambda fx: rostered()), \
                patch.object(minors, "search_player", lambda *a, **k: None), \
                patch.object(minors, "post_discord_webhook", fake_post):
            code = minors.run(mode, TODAY, session)
            code2 = minors.run(mode, TODAY, session)
        return code, code2, posts, state

    def test_first_run_is_baseline_only(self):
        code, _, posts, state = self._run(FakeSession())
        self.assertEqual((code, posts), (0, []))
        self.assertIn("eligible", json.loads(state.read_text()))

    def test_crossing_posts_one_alert_then_stays_quiet(self):
        session = FakeSession()
        session.games[3] = 51
        code, code2, posts, _ = self._run(session, {"eligible": {"f1": False, "f2": True, "f3": True}})
        self.assertEqual((code, code2, len(posts)), (0, 0, 1))
        text = posts[0]["embeds"][0]["description"]
        self.assertIn("Goalie, Pro", text)
        self.assertNotIn("•", text)

    def test_failed_delivery_is_retried_and_not_saved(self):
        session = FakeSession()
        session.games[3] = 51
        saved = {"eligible": {"f1": False, "f2": True, "f3": True}}
        code, _, posts, state = self._run(session, saved, ok=False)
        self.assertEqual((code, len(posts)), (1, 2))
        self.assertEqual(json.loads(state.read_text())["eligible"], saved["eligible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
