#!/usr/bin/env python3
"""Offline checks for Lineup Alerts.

Rosters: the live getTeamRosters sample (team_rosters_sample_test.json, daily
lineup period 8 = Tue Oct 6). getPlayerIds has no entries for those players in
the sample, so each one is given an NHL team here (the shape matches
player_ids_sample.json). NHL games: the synthetic schedule fixture.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import alerts  # noqa: E402
from blha import nhl  # noqa: E402

ET = ZoneInfo("America/New_York")
FIXTURES = HERE.parent / "tests" / "fixtures"
ROSTERS = json.loads((FIXTURES / "team_rosters_sample_test.json").read_text())["response"]
SAMPLE_PLAYERS = json.loads((FIXTURES / "player_ids_sample.json").read_text())
NHL = json.loads((FIXTURES / "nhl_schedule_synthetic.json").read_text())["responses"]
TEST, TEST3 = "gb4or3npmumb3mgv", "2tml63mumumuxoqh"
OWNER = "123456789012345678"
NOW = datetime(2026, 10, 6, 15, 0, tzinfo=ET).astimezone(timezone.utc)

# Tue Oct 6 (synthetic): VAN@CHI 1:00 PM (already started at 3 PM), DET@FLA 7:00 PM,
# EDM@CGY 9:00 PM, LAK@SJS 10:00 PM. NJD, PIT, CAR, MIN, BOS, TOR play later in the week.
OVERRIDES = {
    "05y3a": ("NJD", "C"),        # Test: ACTIVE C, no game -> idle
    "01587": ("PIT", "C"),        # Test: ACTIVE F slot, no game -> idle
    "04lcs": ("MIN", "D"),        # Test: ACTIVE D, no game, but no D on the bench
    "04o0g": ("VAN", "C"),        # Test: ACTIVE C in the 1 PM game -> has a game
    "04f75": ("DET", "C,LW"),     # Test: RESERVE C, plays 7 PM -> option for C and F
    "00qs7": ("FLA", "LW"),       # Test: RESERVE LW, plays 7 PM -> option for F only
    "04f0t": ("VAN", "C"),        # Test: RESERVE C, game already started -> not an option
    "03rfx": ("CAR", "C"),        # Test: RESERVE C, no game
    "04az7": ("", "LW"),          # Test: RESERVE, unknown NHL team -> skipped
    "03jw0": ("LAK", "G"),        # Test: RESERVE G, plays, but no idle goalie
    "0457i": ("NJD", "G"),        # Test 3: ACTIVE G, no game, no G on the bench
    "05ltt": ("XYZ", "LW"),       # Test 3: team code not in the NHL schedule -> skipped
}


def directory() -> dict:
    players = copy.deepcopy(SAMPLE_PLAYERS)
    for team in ROSTERS["rosters"].values():
        for item in team["rosterItems"]:
            pid = item["id"]
            nhl_team, position = OVERRIDES.get(pid, ("EDM", "C" if item["position"] == "F" else item["position"]))
            players[pid] = {"fantraxId": pid, "name": f"Player{pid}, Test", "position": position, "team": nhl_team}
    return players


def nhl_get(url: str) -> dict:
    return NHL.get(url.rsplit("/", 1)[1], {"gameWeek": []})


class FakeFantrax:
    def __init__(self) -> None:
        self.calls = 0

    def league_info(self) -> dict:
        return {"leagueName": "Dynasty Hockey Test League"}

    def rosters(self) -> dict:
        self.calls += 1
        return ROSTERS

    def player_ids(self) -> dict:
        return directory()


class NoFantrax:
    def __getattr__(self, name: str):
        raise AssertionError("Fantrax should not be read")


def league(owners: dict | None = None) -> dict:
    return {
        "league_id": "test", "timezone": "America/New_York", "season_label": "2026-27 TEST",
        "color": 0xFFB81C, "owners": owners or {}, "lineup_alerts": {"webhook": "TEST_LINEUP_HOOK"},
    }


def today_alerts(now: datetime = NOW) -> list[alerts.TeamAlert]:
    games = nhl.fetch_schedule(now.astimezone(ET).date(), now.astimezone(ET).date(), ET, nhl_get)
    playing, known = alerts.todays_games(games, now.astimezone(ET).date())
    return alerts.find_alerts(ROSTERS, directory(), playing, known, now)


class EligibilityTests(unittest.TestCase):
    def test_forwards_fill_f(self) -> None:
        for pos in ("C", "LW", "RW", "F"):
            self.assertTrue(alerts.can_fill("F", {pos}))
        self.assertFalse(alerts.can_fill("F", {"D"}))
        self.assertFalse(alerts.can_fill("F", {"G"}))

    def test_named_slots_need_that_position(self) -> None:
        self.assertTrue(alerts.can_fill("C", {"C"}))
        self.assertFalse(alerts.can_fill("C", {"LW"}))
        self.assertFalse(alerts.can_fill("LW", {"F"}))
        self.assertTrue(alerts.can_fill("D", {"D"}))
        self.assertFalse(alerts.can_fill("D", {"C"}))
        self.assertTrue(alerts.can_fill("G", {"G"}))
        self.assertFalse(alerts.can_fill("G", {"D"}))

    def test_positions_combine_roster_and_directory(self) -> None:
        self.assertEqual(alerts.positions_of("C", "C,LW"), {"C", "LW"})
        self.assertEqual(alerts.positions_of("RW", None), {"RW"})

    def test_names(self) -> None:
        self.assertEqual(alerts.display_name(SAMPLE_PLAYERS["02un4"]["name"]), "Connor McDavid")


class FindAlertTests(unittest.TestCase):
    def test_only_the_affected_franchise(self) -> None:
        found = today_alerts()
        self.assertEqual([a.team_id for a in found], [TEST])

    def test_idle_starters_and_bench_options(self) -> None:
        alert = today_alerts()[0]
        self.assertEqual([(e.player_id, e.slot) for e in alert.idle], [("05y3a", "C"), ("01587", "F")])
        self.assertEqual([e.player_id for e in alert.bench], ["04f75", "00qs7"])
        # The idle D has no D on the bench, so it is not listed.
        self.assertNotIn("04lcs", [e.player_id for e in alert.idle])

    def test_no_alert_once_bench_games_have_started(self) -> None:
        late = datetime(2026, 10, 6, 19, 30, tzinfo=ET).astimezone(timezone.utc)
        self.assertEqual(today_alerts(late), [])

    def test_unknown_team_codes_never_guess(self) -> None:
        games = nhl.fetch_schedule(NOW.astimezone(ET).date(), NOW.astimezone(ET).date(), ET, nhl_get)
        playing, known = alerts.todays_games(games, NOW.astimezone(ET).date())
        self.assertNotIn("XYZ", known)
        self.assertNotIn("", known)
        self.assertIn("NJD", known)       # plays later in the week, so the code is trusted
        self.assertNotIn("NJD", playing)

    def test_no_games_today_means_no_alerts(self) -> None:
        games = nhl.fetch_schedule(NOW.astimezone(ET).date(), NOW.astimezone(ET).date(), ET, nhl_get)
        tomorrow = NOW.astimezone(ET).date() + timedelta(days=5)  # Oct 11: no games in the fixture
        playing, known = alerts.todays_games(games, tomorrow)
        self.assertEqual(alerts.find_alerts(ROSTERS, directory(), playing, known, NOW), [])


class OwnerTests(unittest.TestCase):
    def test_opt_in_by_team_name_or_id(self) -> None:
        alert = alerts.TeamAlert(TEST, "Test")
        self.assertEqual(alerts.owner_for(alert, alerts.owner_ids(league({"test": OWNER}))), OWNER)
        self.assertEqual(alerts.owner_for(alert, alerts.owner_ids(league({TEST: OWNER}))), OWNER)
        self.assertEqual(alerts.owner_for(alert, alerts.owner_ids(league({"Test 3": OWNER}))), "")

    def test_invalid_ids_ignored(self) -> None:
        self.assertEqual(alerts.owner_ids(league({"Test": "@someone", "Test 3": ""})), {})


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_path = Path(tmp.name) / "lineup_alerts.json"
        patcher = patch.object(alerts, "STATE_PATH", self.state_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent: list[tuple[str, dict]] = []

    def fake_send(self, secret: str, payload: dict):
        self.sent.append((secret, payload))
        return True, "delivered", "1"

    def run_alerts(self, mode: str, owners: dict | None, *, all_teams: bool = False,
                   now: datetime = NOW, fx=None) -> tuple[int, str]:
        out = io.StringIO()
        with patch.object(alerts, "send_discord_webhook", self.fake_send), redirect_stdout(out):
            code = alerts.run(mode, all_teams, now=now, league=league(owners), fx=fx or FakeFantrax(),
                              nhl_get=nhl_get)
        return code, out.getvalue()

    def test_nobody_opted_in_reads_nothing(self) -> None:
        code, out = self.run_alerts("live", {}, fx=NoFantrax())
        self.assertEqual(code, 0)
        self.assertIn("no owners have opted in", out)
        self.assertEqual(self.sent, [])

    def test_live_alert_mentions_only_the_owner(self) -> None:
        code, _ = self.run_alerts("live", {"Test": OWNER})
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sent), 1)
        secret, payload = self.sent[0]
        self.assertEqual(secret, "TEST_LINEUP_HOOK")
        self.assertEqual(payload["content"], f"<@{OWNER}>")
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": [OWNER]})
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Lineup Alert — Test")
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        self.assertEqual(fields["In your lineup, no game today"],
                         "C — Test Player05y3a (NJD)\nF — Test Player01587 (PIT)")
        det = int(datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc).timestamp())
        self.assertEqual(fields["On your bench, playing today"].splitlines()[0],
                         f"C/LW — Test Player04f75 (DET, <t:{det}:t>)")
        self.assertEqual(payload["username"], "BLHA Competition Desk")
        self.assertEqual(embed["color"], 0xFFB81C)

    def test_same_alert_not_repeated_same_day(self) -> None:
        self.run_alerts("live", {"Test": OWNER})
        code, out = self.run_alerts("live", {"Test": OWNER}, now=NOW + timedelta(hours=1))
        self.assertEqual((code, len(self.sent)), (0, 1))
        self.assertIn("already alerted today", out)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["alerted"], [TEST])
        self.assertEqual(alerts.alerted_today(state, NOW.astimezone(ET).date() + timedelta(days=1)), set())

    def test_franchise_without_owner_is_not_alerted_live(self) -> None:
        code, out = self.run_alerts("live", {"Test 3": OWNER}, all_teams=True)
        self.assertEqual((code, self.sent), (0, []))
        self.assertIn("owner has not opted in", out)

    def test_test_mode_pings_nobody_and_saves_nothing(self) -> None:
        self.run_alerts("test", {"Test": OWNER})
        payload = self.sent[0][1]
        self.assertTrue(payload["embeds"][0]["title"].startswith("[TEST] "))
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "users": []})
        self.assertFalse(self.state_path.exists())

    def test_preview_all_teams_without_owners(self) -> None:
        code, out = self.run_alerts("preview", {}, all_teams=True)
        self.assertEqual((code, self.sent), (0, []))
        self.assertIn("PREVIEW Test: 2 idle, 2 bench option(s)", out)
        self.assertNotIn('"content"', out)
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
