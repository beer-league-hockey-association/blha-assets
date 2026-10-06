#!/usr/bin/env python3
"""Offline checks for Starting Goalies.

Daily Faceoff: a trimmed capture of the 2026-10-06 page (only the fields BLHA
reads). Fantrax: two small made-up rosters in the getTeamRosters /
getPlayerIds shapes, so the BLHA tags can be checked.
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import starters  # noqa: E402

ET = ZoneInfo("America/New_York")
DAY = date(2026, 10, 6)
PAGE = (HERE.parent / "tests" / "fixtures" / "dailyfaceoff_starting_goalies_2026-10-06.html").read_text()
AFTERNOON = datetime(2026, 10, 6, 14, 40, tzinfo=ET).astimezone(timezone.utc)
LEAGUE = {"league_id": "test", "timezone": "America/New_York", "season_label": "Test",
          "starting_goalies": {"webhook": "BLHA_WEBHOOK_GAME_DAY", "post_from": "11:00"}}

ROSTERS = {"period": 8, "rosters": {
    "t1": {"teamName": "Ice Holes", "rosterItems": [
        {"id": "g1", "position": "G", "status": "ACTIVE"},     # Saros: confirmed starter
        {"id": "g2", "position": "G", "status": "RESERVE"},    # Luukkonen: BUF plays, Ellis likely
        {"id": "s1", "position": "C", "status": "ACTIVE"},
    ]},
    "t2": {"teamName": "Puck Bunnies", "rosterItems": [
        {"id": "g3", "position": "G", "status": "ACTIVE"},     # Hill: VGK starter, unconfirmed
        {"id": "g4", "position": "G", "status": "RESERVE"},    # Ullmark: OTT plays, Ersson unconfirmed
        {"id": "g5", "position": "G", "status": "RESERVE"},    # Vasilevskiy: TBL does not play
    ]},
}}
PLAYERS = {
    "g1": {"fantraxId": "g1", "name": "Saros, Juuse", "position": "G", "team": "NSH"},
    "g2": {"fantraxId": "g2", "name": "Luukkonen, Ukko-Pekka", "position": "G", "team": "BUF"},
    "s1": {"fantraxId": "s1", "name": "Hughes, Jack", "position": "C", "team": "NJD"},
    "g3": {"fantraxId": "g3", "name": "Hill, Adin", "position": "G", "team": "VGK"},
    "g4": {"fantraxId": "g4", "name": "Ullmark, Linus", "position": "G", "team": "OTT"},
    "g5": {"fantraxId": "g5", "name": "Vasilevskiy, Andrei", "position": "G", "team": "TBL"},
    "x1": {"fantraxId": "x1", "name": "Shesterkin, Igor", "position": "G", "team": "NYR"},  # unrostered
}


class FakeFantrax:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def league_info(self) -> dict:
        return {"leagueName": "Dynasty Hockey Test League"}

    def rosters(self) -> dict:
        if self.fail:
            raise RuntimeError("Fantrax down")
        return ROSTERS

    def player_ids(self) -> dict:
        return PLAYERS


def get(url: str) -> str:
    assert url == "https://www.dailyfaceoff.com/starting-goalies/2026-10-06", url
    return PAGE


def quiet(fn, *args, **kwargs):
    out = io.StringIO()
    with redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class ParseTests(unittest.TestCase):
    def test_reads_every_game_in_start_order(self):
        games = starters.parse_page(PAGE, DAY)
        self.assertEqual(len(games), 9)
        first = games[0]
        self.assertEqual(first.start, datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(games[-1].label, "FLA at LAK")
        mn = next(g for g in games if g.away.team == "MIN")
        self.assertEqual((mn.away.goalie, mn.away.status), ("Jesper Wallstedt", "Confirmed"))
        self.assertEqual((mn.home.team, mn.home.goalie, mn.home.status), ("BUF", "Colten Ellis", "Likely"))
        ott = next(g for g in games if g.away.team == "OTT")
        self.assertEqual(ott.away.status, "Unconfirmed")  # null strength on the page

    def test_every_team_slug_maps_to_a_code(self):
        games = starters.parse_page(PAGE, DAY)
        self.assertTrue(all(side.team for g in games for side in (g.away, g.home)))
        self.assertEqual(starters.summary(games), (10, 18))  # the page said "10 of 18 confirmed"

    def test_a_page_for_another_day_is_ignored(self):
        self.assertEqual(starters.parse_page(PAGE, date(2026, 10, 7)), [])

    def test_a_changed_site_layout_is_an_error(self):
        with self.assertRaises(ValueError):
            starters.parse_page("<html><body>No data</body></html>", DAY)

    def test_team_name_fallback(self):
        self.assertEqual(starters._team_code("", "St. Louis Blues"), "STL")
        self.assertEqual(starters._team_code("mystery-club", "Mystery Club"), "")


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.games = starters.parse_page(PAGE, DAY)
        self.index = starters.roster.build_index(ROSTERS, PLAYERS)

    def test_rostered_starters_are_tagged(self):
        self.assertEqual(starters.tag_owners(self.games, self.index), 2)
        owners = {side.goalie: side.owner for g in self.games for side in (g.away, g.home) if side.owner}
        self.assertEqual(owners, {"Juuse Saros": "Ice Holes", "Adin Hill": "Puck Bunnies"})

    def test_rostered_goalies_not_starting(self):
        lines = starters.not_starting(self.games, self.index, AFTERNOON)
        self.assertEqual(lines, ["**Ice Holes** — Ukko-Pekka Luukkonen (BUF): Colten Ellis is likely to start"])
        # Ullmark is skipped: Ottawa's listed starter is unconfirmed. Vasilevskiy: no game.

    def test_started_games_are_not_flagged(self):
        late = datetime(2026, 10, 6, 19, 5, tzinfo=ET).astimezone(timezone.utc)
        self.assertEqual(starters.not_starting(self.games, self.index, late), [])


class PayloadTests(unittest.TestCase):
    def test_message_layout(self):
        games = starters.parse_page(PAGE, DAY)
        index = starters.roster.build_index(ROSTERS, PLAYERS)
        starters.tag_owners(games, index)
        ctx = starters.render.Context("Dynasty Hockey Test League", "Test", 0xFFB81C)
        body = starters.payload(ctx, games, DAY, starters.not_starting(games, index, AFTERNOON), AFTERNOON)
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "Starting Goalies — Tuesday, October 6")
        self.assertIn("**10 of 18 starters confirmed**", embed["description"])
        self.assertIn("[Daily Faceoff](https://www.dailyfaceoff.com/starting-goalies/2026-10-06)", embed["description"])
        self.assertEqual(len(embed["fields"]), 10)  # 9 games + not-starting list
        nsh = next(f for f in embed["fields"] if f["name"] == "NSH at TOR")
        self.assertIn("**NSH** Juuse Saros — Confirmed • *Ice Holes*", nsh["value"])
        self.assertTrue(nsh["value"].startswith("<t:1791327600:t>"))
        self.assertEqual(embed["fields"][-1]["name"], "BLHA GOALIES NOT STARTING TONIGHT")
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        self.assertLess(len(json.dumps(embed)), 6000)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "starting_goalies.json"
        self.patch = patch.object(starters, "STATE_PATH", self.state)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def live(self, now, upsert_result=None, page=PAGE):
        calls = []

        def fake_upsert(secret, body, message_id):
            calls.append((secret, message_id, body))
            return upsert_result or (True, "delivered", message_id or "111", "edited" if message_id else "posted")

        with patch.object(starters, "upsert_discord_message", fake_upsert):
            code, out = quiet(starters.run, "live", now=now, league=LEAGUE, fx=FakeFantrax(), get=lambda url: page)
        return code, out, calls

    def test_too_early_does_nothing(self):
        morning = datetime(2026, 10, 6, 10, 0, tzinfo=ET).astimezone(timezone.utc)
        code, out, calls = self.live(morning)
        self.assertEqual((code, calls), (0, []))
        self.assertIn("before 11:00", out)

    def test_posts_then_edits_only_on_change(self):
        code, _, calls = self.live(AFTERNOON)
        self.assertEqual(code, 0)
        self.assertEqual([c[:2] for c in calls], [("BLHA_WEBHOOK_GAME_DAY", None)])
        saved = json.loads(self.state.read_text())
        self.assertEqual((saved["date"], saved["message_id"]), ("2026-10-06", "111"))

        later = datetime(2026, 10, 6, 15, 40, tzinfo=ET).astimezone(timezone.utc)
        code, out, calls = self.live(later)
        self.assertEqual((code, calls), (0, []))
        self.assertIn("UNCHANGED", out)

        changed = PAGE.replace('"homeGoalieName":"Colten Ellis","homeNewsStrengthName":"Likely"',
                               '"homeGoalieName":"Colten Ellis","homeNewsStrengthName":"Confirmed"')
        self.assertNotEqual(changed, PAGE)
        code, out, calls = self.live(later, page=changed)
        self.assertEqual([c[1] for c in calls], ["111"])  # same message, edited
        self.assertIn("EDITED", out)

    def test_new_day_posts_a_new_message(self):
        self.state.write_text(json.dumps({"date": "2026-10-05", "message_id": "999", "fingerprint": "x"}))
        _, _, calls = self.live(AFTERNOON)
        self.assertEqual(calls[0][1], None)

    def test_after_the_last_puck_drop_the_message_is_final(self):
        self.live(AFTERNOON)
        late = datetime(2026, 10, 6, 22, 30, tzinfo=ET).astimezone(timezone.utc)
        code, out, calls = self.live(late)
        self.assertEqual((code, calls), (0, []))
        self.assertIn("every game has started", out)

    def test_failed_post_keeps_state(self):
        code, out, _ = self.live(AFTERNOON, upsert_result=(False, "HTTP 500", None, "failed"))
        self.assertEqual(code, 1)
        self.assertFalse(self.state.exists())

    def test_fantrax_failure_still_posts_without_tags(self):
        def fake_upsert(secret, body, message_id):
            fake_upsert.body = body
            return True, "delivered", "222", "posted"

        with patch.object(starters, "upsert_discord_message", fake_upsert):
            code, out = quiet(starters.run, "live", now=AFTERNOON, league=LEAGUE, fx=FakeFantrax(fail=True), get=get)
        self.assertEqual(code, 0)
        self.assertIn("posting without BLHA tags", out)
        self.assertEqual(len(fake_upsert.body["embeds"][0]["fields"]), 9)

    def test_preview_and_test_modes_never_save_state(self):
        code, out = quiet(starters.run, "preview", now=AFTERNOON, league=LEAGUE, fx=FakeFantrax(), get=get)
        self.assertEqual(code, 0)
        self.assertIn('"Starting Goalies', out)
        sent = []
        with patch.object(starters, "send_discord_webhook", lambda s, b: (sent.append(b), (True, "delivered", "1"))[1]):
            code, _ = quiet(starters.run, "test", now=AFTERNOON, league=LEAGUE, fx=FakeFantrax(), get=get)
        self.assertEqual(code, 0)
        self.assertTrue(sent[0]["embeds"][0]["title"].startswith("[TEST] "))
        self.assertFalse(self.state.exists())

    def test_no_games_today(self):
        code, out = quiet(starters.run, "live", now=AFTERNOON, league=LEAGUE, fx=FakeFantrax(),
                          get=lambda url: PAGE.replace('"date":"2026-10-06","specificDate"', '"date":"2026-10-05","specificDate"'))
        self.assertEqual(code, 0)
        self.assertIn("no NHL games", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
