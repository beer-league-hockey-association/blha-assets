#!/usr/bin/env python3
"""Offline checks for the BLHA Playoff Pool.

NHL data: automation/tests/fixtures/nhl_playoffs_synthetic.json, a made-up
2027 playoffs in the shapes the pool reads (see its _note: the shapes are
UNVERIFIED against live NHL responses). FakeNHL answers each API URL from it,
building /schedule weeks the way the NHL does (seven days from the date).
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
AUTOMATION = HERE.parent
for folder in (HERE, AUTOMATION):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pool  # noqa: E402
from playoff_pool import boxes as bx  # noqa: E402
from playoff_pool import bracket, entries, posts, scoring  # noqa: E402
from playoff_pool.nhl_feed import Feed, season_id  # noqa: E402

ET = ZoneInfo("America/New_York")
FIXTURE = json.loads((AUTOMATION / "tests" / "fixtures" / "nhl_playoffs_synthetic.json").read_text(encoding="utf-8"))
LEAGUE = {"league_id": "test", "timezone": "America/New_York", "color": 0xFFB81C,
          "playoff_pool": {"webhook": "BLHA_WEBHOOK_GAME_DAY"}}
FIRST_PUCK = datetime(2027, 4, 17, 19, 0, tzinfo=timezone.utc)  # Sat Apr 17, 3:00 PM ET


def et(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


class FakeNHL:
    """Answers api-web.nhle.com/v1 URLs from the synthetic fixture (None = 404)."""

    def __init__(self) -> None:
        self.fx = copy.deepcopy(FIXTURE)
        self.urls: list[str] = []

    def series(self, letter: str) -> dict:
        return next(s for s in self.fx["bracket"]["series"] if s["seriesLetter"] == letter)

    def __call__(self, url: str):
        self.urls.append(url)
        parts = url.split("/v1/", 1)[1].strip("/").split("/")
        kind = parts[0]
        if kind == "playoff-bracket":
            return copy.deepcopy(self.fx["bracket"]) if int(parts[1]) == self.fx["year"] else None
        if kind == "club-stats":
            return self.fx["club_stats"].get(parts[1]) if parts[2] == "20262027" else None
        if kind == "roster":
            return self.fx["rosters"].get(parts[1])
        if kind == "schedule":
            start = date.fromisoformat(parts[1])
            week = []
            for i in range(7):
                day = start + timedelta(days=i)
                games = [g for g in self.fx["games"] if datetime.fromisoformat(
                    g["startTimeUTC"].replace("Z", "+00:00")).astimezone(ET).date() == day]
                week.append({"date": day.isoformat(), "games": copy.deepcopy(games)})
            return {**self.fx["season"], "gameWeek": week}
        if kind == "gamecenter":
            return copy.deepcopy(self.fx["boxscores"].get(parts[1]))
        return None

    def count(self, kind: str) -> int:
        return sum(1 for u in self.urls if f"/v1/{kind}" in u)


def built(per_box: int = 8, rosters: dict | None = None, log: list | None = None) -> bx.Boxes:
    series = bracket.parse(FIXTURE["bracket"])
    return bx.build(2027, "20262027", bracket.field(series), FIXTURE["club_stats"],
                    FIXTURE["rosters"] if rosters is None else rosters,
                    bx.Settings(players_per_box=per_box), et(2027, 4, 16, 7, 45), log)


def box_of(boxes: bx.Boxes, player_id: int) -> int:
    return next(b.number for b in boxes.boxes if any(p.id == player_id for p in b.players))


# --- Bracket --------------------------------------------------------------------------

class BracketTests(unittest.TestCase):
    def test_field_is_set_with_sixteen_teams(self) -> None:
        series = bracket.parse(FIXTURE["bracket"])
        self.assertTrue(bracket.field_set(series))
        self.assertEqual(len(bracket.field(series)), 16)
        self.assertEqual(bracket.champion(series), "")
        self.assertEqual(bracket.eliminated(series), set())

    def test_field_not_set_while_a_spot_is_open(self) -> None:
        raw = copy.deepcopy(FIXTURE["bracket"])
        raw["series"][7].pop("bottomSeedTeam")
        series = bracket.parse(raw)
        self.assertFalse(bracket.field_set(series))
        self.assertEqual(len(bracket.field(series)), 15)
        self.assertFalse(bracket.field_set(bracket.parse(None)))

    def test_losers_are_eliminated_and_final_winner_is_champion(self) -> None:
        raw = copy.deepcopy(FIXTURE["bracket"])
        a = raw["series"][0]                       # FLA (id 13) vs OTT (id 9)
        a.update(topSeedWins=4, bottomSeedWins=1)  # decided by wins alone
        b = raw["series"][1]                       # TBL (id 14) vs TOR (id 10)
        b.update(topSeedWins=2, bottomSeedWins=3, winningTeamId=10, losingTeamId=14)  # decided by id
        final = raw["series"][-1]
        final.update(topSeedTeam=a["topSeedTeam"], bottomSeedTeam=raw["series"][4]["topSeedTeam"],  # WPG
                     topSeedWins=4, bottomSeedWins=3)
        series = bracket.parse(raw)
        self.assertEqual(bracket.eliminated(series), {"OTT", "TBL", "WPG"})
        self.assertEqual(bracket.champion(series), "FLA")
        self.assertEqual(bracket.team_name(series, "FLA"), "Florida Panthers")
        self.assertEqual(bracket.team_name(series, "XYZ"), "XYZ")


# --- Boxes ----------------------------------------------------------------------------

class BoxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boxes = built()

    def test_ten_boxes_tiered_by_points_per_game(self) -> None:
        b = self.boxes.boxes
        self.assertEqual([x.number for x in b], list(range(1, 11)))
        self.assertTrue(all(len(x.players) == 8 for x in b[:9]))
        self.assertEqual(b[8].title, "Box 9: Dark Horses")
        self.assertEqual(b[9].title, "Box 10: Goalies")
        rates = [[p.pts / p.gp for p in x.players] for x in b[:8]]
        for higher, lower in zip(rates, rates[1:]):
            self.assertGreaterEqual(min(higher), max(lower))
        ids = [p.id for x in b for p in x.players]
        self.assertEqual(len(ids), len(set(ids)), "a player is in two boxes")

    def test_minimum_games_and_traded_players_are_left_out(self) -> None:
        skaters = [p for x in self.boxes.boxes[:9] for p in x.players]
        self.assertTrue(all(p.gp >= 20 for p in skaters))
        self.assertIsNone(self.boxes.player(8470200), "TOR's traded-away scorer must not be boxed")
        self.assertEqual(self.boxes.rules["eligible_skaters"], 16 * 11 - 1)

    def test_dark_horses_skip_a_tier_below_box_eight(self) -> None:
        self.assertEqual(self.boxes.rules["dark_horse_ranks"], [73, 80])
        ranked = sorted((p for x in self.boxes.boxes[:9] for p in x.players), key=lambda p: -p.pts / p.gp)
        self.assertLess(max(p.pts / p.gp for p in self.boxes.boxes[8].players),
                        min(p.pts / p.gp for p in self.boxes.boxes[7].players))
        self.assertEqual(len(ranked), 72)

    def test_goalie_box_has_each_teams_likely_starter(self) -> None:
        goalies = self.boxes.boxes[9].players
        self.assertEqual(len(goalies), 16)
        self.assertEqual(len({g.team for g in goalies}), 16)
        self.assertTrue(all(g.goalie and g.gs >= 50 for g in goalies))
        self.assertEqual([g.gs for g in goalies], sorted((g.gs for g in goalies), reverse=True))

    def test_missing_roster_skips_the_filter_and_says_so(self) -> None:
        rosters = dict(FIXTURE["rosters"], TOR=None)
        log: list[str] = []
        boxes = built(rosters=rosters, log=log)
        self.assertIsNotNone(boxes.player(8470200))
        self.assertTrue(any(line.startswith("TOR") for line in log))

    def test_too_few_players_is_an_error(self) -> None:
        series = bracket.parse(FIXTURE["bracket"])
        stats = {team: {"skaters": FIXTURE["club_stats"][team]["skaters"][:2], "goalies": []}
                 for team in bracket.field(series)}
        with self.assertRaises(ValueError):
            bx.build(2027, "20262027", bracket.field(series), stats, {}, bx.Settings(), et(2027, 4, 16))

    def test_players_per_box_is_configurable(self) -> None:
        self.assertTrue(all(len(x.players) == 10 for x in built(per_box=10).boxes[:9]))
        with self.assertRaises(ValueError):
            bx.Settings.from_cfg({"players_per_box": 11})
        with self.assertRaises(ValueError):
            bx.Settings.from_cfg({"entries_via": "email"})
        self.assertEqual(bx.Settings.from_cfg(None).players_per_box, 8)

    def test_find_by_option_id_or_name(self) -> None:
        box1 = self.boxes.box(1)
        first = box1.players[0]
        self.assertIs(box1.find(1), first)
        self.assertIs(box1.find("#1"), first)
        self.assertIs(box1.find(first.id), first)
        self.assertIs(box1.find(str(first.id)), first)
        self.assertIs(box1.find(first.name.upper()), first)
        self.assertIsNone(box1.find(99))
        self.assertIsNone(box1.find("Abbott"), "eight Abbotts: a last name alone is ambiguous")
        self.assertIsNone(box1.find(True))
        accented = next(b for b in self.boxes.boxes if b.find("Elie Cote"))
        self.assertEqual(accented.find("elie côté").name, "Élie Côté")

    def test_round_trip(self) -> None:
        self.boxes.deadline = FIRST_PUCK
        again = bx.Boxes.from_dict(json.loads(json.dumps(self.boxes.as_dict())))
        self.assertEqual(again.as_dict(), self.boxes.as_dict())
        self.assertEqual(again.deadline, FIRST_PUCK)
        self.assertNotIn("gs", again.as_dict()["boxes"][0]["players"][0])


class DeadlineTests(unittest.TestCase):
    def test_first_puck_drop_comes_from_the_schedule(self) -> None:
        nhl = FakeNHL()
        self.assertEqual(pool.first_puck_drop(Feed(nhl), date(2027, 4, 16), ET), FIRST_PUCK)

    def test_unpublished_schedule_means_no_deadline_yet(self) -> None:
        nhl = FakeNHL()
        nhl.fx["games"] = [g for g in nhl.fx["games"] if g["gameType"] != 3]
        self.assertIsNone(pool.first_puck_drop(Feed(nhl), date(2027, 4, 16), ET))

    def test_picks_lock_at_the_first_puck_drop(self) -> None:
        boxes = built()
        self.assertFalse(boxes.locked(FIRST_PUCK + timedelta(days=3)), "unknown deadline stays open")
        boxes.deadline = FIRST_PUCK
        self.assertFalse(boxes.locked(FIRST_PUCK - timedelta(seconds=1)))
        self.assertTrue(boxes.locked(FIRST_PUCK))

    def test_playoff_year(self) -> None:
        self.assertEqual(pool.playoff_year(date(2027, 4, 20)), 2027)
        self.assertEqual(pool.playoff_year(date(2026, 10, 8)), 2027)
        self.assertEqual(season_id(2027), "20262027")


# --- Scoring --------------------------------------------------------------------------

class ScoringTests(unittest.TestCase):
    def test_weights_match_the_constitution(self) -> None:
        sys.path.insert(0, str(AUTOMATION.parent / "tools"))
        import constitution_source as cs

        def hundredths(rows):
            return [round(float(v) * 100) for _, v in rows]

        self.assertEqual(hundredths(cs.SKATERS), list(scoring.SKATER_POINTS.values()))
        self.assertEqual(hundredths(cs.GOALIES), list(scoring.GOALIE_POINTS.values()))

    def test_boxscore_lines_and_points(self) -> None:
        state, lines = scoring.parse_boxscore(FIXTURE["boxscores"]["2026030111"])
        self.assertEqual(state, "OFF")
        skater = lines[8470000]  # 2 G, 1 A, 5 SOG, 1 BLK, 2 HIT, 2 PIM
        self.assertEqual(scoring.line_points(skater, False), 1000 + 295 + 275 + 35 + 40 - 108)
        self.assertEqual(scoring.fmt(scoring.line_points(skater, False)), "15.37")
        goalie = lines[8479000]  # start, 30 saves, 2 GA, 1 A
        self.assertEqual(goalie, {"gs": 1, "sv": 30, "ga": 2, "g": 0, "a": 1})
        self.assertEqual(scoring.line_points(goalie, True), 650 + 1470 - 1000 + 295)
        self.assertEqual(lines[8479031]["gs"], 0)
        self.assertEqual(scoring.line_points(lines[8479030], True), 650 + 28 * 49 - 2000)

    def test_older_field_names_and_no_starter_flag(self) -> None:
        state, lines = scoring.parse_boxscore(FIXTURE["boxscores"]["2026030121"])
        self.assertEqual(state, "FINAL")
        self.assertEqual(lines[8470201]["sog"], 4)
        self.assertEqual(lines[8479020], {"gs": 1, "sv": 25, "ga": 3, "g": 0, "a": 0})
        self.assertEqual(lines[8479011]["gs"], 0, "the goalie with the most ice time gets the start")

    def test_format(self) -> None:
        self.assertEqual(scoring.fmt(-54), "-0.54")
        self.assertEqual(scoring.fmt(0), "0.00")
        self.assertEqual(scoring.fmt(31205), "312.05")

    def test_only_final_games_count(self) -> None:
        games = {"1": {"final": True, "lines": {"5": {"g": 1}}}, "2": {"final": False, "lines": {"5": {"g": 3}}}}
        self.assertEqual(scoring.player_points(games, set()), {5: 500})

    def test_tiebreaks_goalie_points_then_earliest_entry(self) -> None:
        early, late = et(2027, 4, 15, 20), et(2027, 4, 16, 9)
        e = [entries.Entry("A", {1: 1, 10: 9}, late, 0), entries.Entry("B", {1: 2, 10: 8}, early, 1),
             entries.Entry("C", {1: 3, 10: 7}, None, 2), entries.Entry("D", {1: 4, 10: 7}, early, 3)]
        totals = {1: 1000, 9: 500,   # A 1500, goalie 500
                  2: 1200, 8: 300,   # B 1500, goalie 300
                  3: 1100, 7: 400,   # C 1500, goalie 400, no entry time
                  4: 1100}           # D 1500, goalie 400, early entry
        rows = scoring.standings(e, 10, totals, {}, set())
        self.assertEqual([r.owner for r in rows], ["A", "D", "C", "B"])
        self.assertEqual(scoring.tie_note(rows, 0), "ahead on goalie points")
        self.assertEqual(scoring.tie_note(rows, 1), "ahead on earlier entry")
        self.assertEqual(scoring.tie_note(rows, 3), "")

    def test_untimed_entries_fall_back_to_file_order(self) -> None:
        e = [entries.Entry("Later in file", {1: 1}, None, 5), entries.Entry("Earlier", {1: 1}, None, 2)]
        rows = scoring.standings(e, 10, {1: 100}, {}, set())
        self.assertEqual([r.owner for r in rows], ["Earlier", "Later in file"])

    def test_best_pick_and_players_out(self) -> None:
        e = [entries.Entry("A", {1: 11, 2: 12, 10: 13}, None, 0)]
        rows = scoring.standings(e, 10, {11: 300, 12: 700, 13: 50}, {11: "FLA", 12: "OTT", 13: "OTT"}, {"OTT"})
        self.assertEqual((rows[0].total, rows[0].goalie, rows[0].best_box, rows[0].out), (1050, 50, 2, 2))


# --- Entries --------------------------------------------------------------------------

class EntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boxes = built()
        self.boxes.deadline = FIRST_PUCK

    def parse(self, text: str) -> entries.Parsed:
        return entries.parse(yaml.safe_load(text), self.boxes, ET)

    def test_option_numbers_ids_and_names(self) -> None:
        b2 = self.boxes.box(2).players[4]
        b3 = self.boxes.box(3).players[0]
        parsed = self.parse(f"""
year: 2027
entries:
  - owner: "Rink Rats"
    entered: "2027-04-16 21:05"
    picks:
      1: 3
      Box 2: {b2.id}
      "3": "{b3.name.lower()}"
      10: "#1"
""")
        self.assertEqual(len(parsed.entries), 1)
        e = parsed.entries[0]
        self.assertEqual(e.picks, {1: self.boxes.box(1).players[2].id, 2: b2.id, 3: b3.id,
                                   10: self.boxes.box(10).players[0].id})
        self.assertEqual(e.entered, et(2027, 4, 16, 21, 5), "no time zone means league time")
        self.assertIn("Rink Rats: no pick for box 4, 5, 6, 7, 8, 9 (scores 0)", parsed.problems)

    def test_bad_picks_duplicates_and_late_entries(self) -> None:
        wrong_box = self.boxes.box(2).players[0].id
        parsed = self.parse(f"""
year: 2027
entries:
  - owner: A
    picks: {{1: {wrong_box}, 2: 1, 12: 1}}
  - owner: a
    picks: {{1: 1}}
  - owner: Late
    entered: "2027-04-17T15:30:00-04:00"
    picks: {{1: 1}}
  - owner: On time
    entered: 2027-04-17T14:59:00-04:00
    picks: {{1: 1}}
  - picks: {{1: 1}}
""")
        self.assertEqual([e.owner for e in parsed.entries], ["A", "On time"])
        self.assertEqual(parsed.entries[0].picks, {2: self.boxes.box(2).players[0].id})
        self.assertEqual(parsed.late, ["Late"])
        text = "\n".join(parsed.problems)
        for expected in (f"{wrong_box} is not in box 1", "there is no box 12", "a: listed twice",
                         "Late: entered after the deadline", "entry 5: owner is missing"):
            self.assertIn(expected, text)

    def test_other_years_are_ignored(self) -> None:
        parsed = self.parse("year: 2026\nentries:\n  - owner: A\n    picks: {1: 1}\n")
        self.assertEqual(parsed.entries, [])
        self.assertIn("not 2027", parsed.problems[0])

    def test_shipped_entries_file_is_well_formed(self) -> None:
        # Real picks name real NHL players, so only the layout is checked here.
        raw = yaml.safe_load(entries.ENTRIES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(entries.check_structure(raw), [])

    def test_structure_check_catches_typos(self) -> None:
        raw = yaml.safe_load("""
year: "2027"
entrys: []
entries:
  - owner: A
    pick: {1: 1}
  - picks: {1: 1}
  - owner: B
    picks: {11: 1, box 2: 3}
""")
        text = "\n".join(entries.check_structure(raw))
        for needle in ("unknown top-level key 'entrys'", "year must be a year", "A: unknown field 'pick'",
                       "entry 2: needs an owner", "B: 11 is not a box number 1-10"):
            self.assertIn(needle, text)
        self.assertNotIn("box 2", text)
        self.assertEqual(entries.check_structure(yaml.safe_load("year: null\nentries: []\n")), [])

    def test_bot_export_round_trips(self) -> None:
        picks = {b.number: b.players[-1].id for b in self.boxes.boxes}
        rows = [{"owner": 'Puck "Bunnies" Ünited', "entered": et(2027, 4, 16, 12), "picks": picks},
                {"owner": "Half Done", "entered": None, "picks": {1: self.boxes.box(1).players[0].id}}]
        text = entries.dump(self.boxes, rows)
        self.assertIn(f"# {self.boxes.box(1).players[-1].name}", text)
        parsed = entries.parse(yaml.safe_load(text), self.boxes, ET)
        self.assertEqual([(e.owner, e.picks, e.entered) for e in parsed.entries],
                         [('Puck "Bunnies" Ünited', picks, et(2027, 4, 16, 12)),
                          ("Half Done", {1: self.boxes.box(1).players[0].id}, None)])
        self.assertEqual(entries.parse(yaml.safe_load(entries.dump(self.boxes, [])), self.boxes, ET).problems, [])


# --- Posts ----------------------------------------------------------------------------

def no_emoji(test: unittest.TestCase, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    test.assertFalse([c for c in text if ord(c) >= 0x1F000], "automated data posts use no emoji")


class PostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = posts.context(2027, 0xFFB81C, test=False)

    def test_boxes_post_fits_discord_and_explains_entry(self) -> None:
        for per_box, via in ((8, "dm"), (10, "bot")):
            boxes = built(per_box=per_box)
            boxes.deadline = FIRST_PUCK
            body = posts.boxes_payload(self.ctx, boxes, bx.Settings(players_per_box=per_box, entries_via=via))
            embed = body["embeds"][0]
            self.assertLessEqual(posts.message_size(body), 6000)
            self.assertEqual(len(embed["fields"]), 10)
            self.assertTrue(all(len(f["value"]) <= 1024 for f in embed["fields"]))
            self.assertIn(f"<t:{int(FIRST_PUCK.timestamp())}:F>", embed["description"])
            self.assertIn("/pool pick" if via == "bot" else "DM your 10 picks", embed["description"])
            self.assertIn("no money", embed["description"])
            self.assertEqual(body["username"], "BLHA Competition Desk")
            self.assertEqual(body["allowed_mentions"], {"parse": []})
            no_emoji(self, body)
        self.assertIn("hasn't published", posts.deadline_line(built()))

    def test_long_names_still_fit_in_one_message(self) -> None:
        for prefix, shortened in (("", False), ("Maximilian-Alexander-Wolfgang ", True)):
            boxes = built(per_box=10)
            for b in boxes.boxes:
                for p in b.players:
                    first, last = p.name.split(" ", 1)
                    p.name = f"{prefix}{first} {last}-Vanderhoeven"
            body = posts.boxes_payload(self.ctx, boxes, bx.Settings(players_per_box=10))
            first_box = body["embeds"][0]["fields"][0]["value"]
            self.assertLessEqual(posts.message_size(body), 6000)
            self.assertNotIn("pts/gm", first_box)
            self.assertEqual(first_box.startswith("1. M. ") or first_box.startswith("1. A. "), shortened)

    def standings_rows(self, owners: int) -> tuple[bx.Boxes, list[scoring.Row]]:
        boxes = built()
        picks = {b.number: b.players[0].id for b in boxes.boxes}
        e = [entries.Entry(f"Franchise {i}", dict(picks), None, i) for i in range(owners)]
        totals = {pid: 1000 + pid % 97 for pid in picks.values()}
        teams = {p.id: p.team for b in boxes.boxes for p in b.players}
        self.out = sum(1 for pid in picks.values() if teams[pid] == boxes.box(1).players[0].team)
        return boxes, scoring.standings(e, 10, totals, teams, {boxes.box(1).players[0].team})

    def test_standings_post(self) -> None:
        boxes, rows = self.standings_rows(12)
        body = posts.standings_payload(self.ctx, boxes, rows, 14, date(2027, 4, 21), date(2027, 4, 22))
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "Playoff Pool Standings — Thursday, April 22")
        self.assertIn("14 playoff games counted, through Wednesday, April 21", embed["description"])
        self.assertEqual(len(embed["fields"]), 12)
        first = embed["fields"][0]
        self.assertTrue(first["name"].startswith("1. Franchise 0 — "))
        self.assertIn("Best pick: ", first["value"])
        self.assertIn(f"Players out: {self.out} of 10", first["value"])
        self.assertIn("Tied on points; ahead on earlier entry.", first["value"])
        self.assertLessEqual(posts.message_size(body), 6000)
        no_emoji(self, body)

    def test_more_than_twelve_entries_are_listed_compactly(self) -> None:
        boxes, rows = self.standings_rows(14)
        fields = posts.standings_payload(self.ctx, boxes, rows, 1, None, date(2027, 4, 18))["embeds"][0]["fields"]
        self.assertEqual(len(fields), 13)
        self.assertEqual(fields[-1]["name"], "ALSO ENTERED")
        self.assertIn("13. Franchise 12", fields[-1]["value"])

    def test_final_post_names_the_pool_shark(self) -> None:
        boxes, rows = self.standings_rows(3)
        body = posts.final_payload(self.ctx, boxes, rows, 87, "Florida Panthers")
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "2027 Playoff Pool Final: Franchise 0 is the Pool Shark")
        self.assertIn("**Florida Panthers won the Stanley Cup.**", embed["description"])
        self.assertIn("(ahead on earlier entry)", embed["description"])
        no_emoji(self, body)


# --- The job ----------------------------------------------------------------------------

class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        self.paths = {"state_path": folder / "pool.json", "boxes_path": folder / "boxes.json",
                      "entries_path": folder / "entries.yaml"}
        self.nhl = FakeNHL()
        self.upserts: list[tuple[dict, str | None]] = []
        self.sent: list[dict] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_pool(self, when: datetime, mode: str = "live", **kw) -> tuple[int, str]:
        def upsert(secret, payload, message_id):
            self.upserts.append((payload, message_id))
            return True, "delivered", message_id or "m1", "edited" if message_id else "posted"

        def send(secret, payload):
            self.sent.append(payload)
            return True, "delivered", "m2"

        out = io.StringIO()
        with patch.object(pool, "upsert_discord_message", upsert), patch.object(pool, "send_discord_webhook", send), \
                redirect_stdout(out):
            code = pool.run(mode, now=when, league=LEAGUE, feed=Feed(self.nhl), **self.paths, **kw)
        return code, out.getvalue()

    def state(self) -> dict:
        return json.loads(self.paths["state_path"].read_text())

    def write_entries(self, boxes: bx.Boxes) -> None:
        def entry(owner: str, ids: list[int], entered: str) -> dict:
            return {"owner": owner, "entered": entered, "picks": {box_of(boxes, i): i for i in ids}}

        data = {"year": 2027, "entries": [
            entry("Rink Rats", [8470000, 8470001, 8479000], "2027-04-16T10:00:00-04:00"),
            entry("North Stars", [8470100, 8470201, 8479010], "2027-04-16T09:00:00-04:00"),
            entry("Ice Dogs", [8470300, 8470303, 8479030], "2027-04-16T11:00:00-04:00"),
        ]}
        self.paths["entries_path"].write_text(yaml.safe_dump(data), encoding="utf-8")

    def test_waits_until_the_field_is_set(self) -> None:
        self.nhl.fx["bracket"]["series"][7].pop("bottomSeedTeam")
        code, out = self.run_pool(et(2027, 4, 14, 7, 45))
        self.assertEqual(code, 0)
        self.assertIn("not set yet (15 of 16 teams)", out)
        self.assertEqual((self.upserts, self.sent), ([], []))
        self.assertFalse(self.paths["boxes_path"].exists())

    def test_full_pool(self) -> None:
        # Thursday morning: the field is set -> boxes posted once, with the deadline.
        code, out = self.run_pool(et(2027, 4, 16, 7, 45))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.upserts), 1)
        self.assertIsNone(self.upserts[0][1])
        saved = bx.Boxes.from_dict(json.loads(self.paths["boxes_path"].read_text()))
        self.assertEqual(saved.deadline, FIRST_PUCK)
        self.assertEqual(self.state()["boxes_message_id"], "m1")
        self.assertIn("picks are open", out)

        # Evening: nothing new.
        self.write_entries(saved)
        code, out = self.run_pool(et(2027, 4, 16, 19, 45))
        self.assertEqual((code, len(self.upserts), self.sent), (0, 1, []))
        self.assertIn("ENTRIES 3 valid", out)
        clubs = self.nhl.count("club-stats")
        self.assertEqual(clubs, 16, "boxes are built once, then read from state")

        # Sunday 07:45: two games final, one still live, one tonight.
        code, out = self.run_pool(et(2027, 4, 18, 7, 45))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.sent), 1)
        embed = self.sent[0]["embeds"][0]
        self.assertEqual(embed["title"], "Playoff Pool Standings — Sunday, April 18")
        self.assertIn("2 playoff games counted, through Saturday, April 17", embed["description"])
        names = [f["name"] for f in embed["fields"]]
        # Rink Rats 15.37 + 7.00 + 14.15; North Stars 9.09 + 7.80 + 15.71; Ice Dogs 6.85 + 3.87 + 0.22
        self.assertEqual(names, ["1. Rink Rats — 36.52 pts", "2. North Stars — 32.60 pts", "3. Ice Dogs — 10.94 pts"])
        self.assertIn("pending=1", out)
        state = self.state()
        self.assertEqual(state["standings"]["on"], "2027-04-18")
        self.assertEqual(sorted(state["games"]), ["2026030111", "2026030121"])
        self.assertNotIn("8479031", state["games"]["2026030111"]["lines"], "only boxed players are cached")

        # A second run that morning posts nothing.
        code, out = self.run_pool(et(2027, 4, 18, 8, 0))
        self.assertEqual((code, len(self.sent)), (0, 1))
        self.assertIn("already posted", out)

        # Monday: OTT is out; the Cup is decided (made-up fast-forward) and every game is final.
        self.nhl.series("A").update(topSeedWins=4, bottomSeedWins=0)
        final = self.nhl.series("O")
        final.update(topSeedTeam=self.nhl.series("A")["topSeedTeam"],
                     bottomSeedTeam=self.nhl.series("E")["topSeedTeam"], topSeedWins=4, bottomSeedWins=2)
        self.nhl.fx["boxscores"]["2026030151"]["gameState"] = "OFF"
        self.nhl.fx["games"] = [g for g in self.nhl.fx["games"] if g["id"] != 2026030112]
        code, out = self.run_pool(et(2027, 4, 19, 7, 45))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.sent), 2)
        final_embed = self.sent[1]["embeds"][0]
        self.assertEqual(final_embed["title"], "2027 Playoff Pool Final: Rink Rats is the Pool Shark")
        self.assertIn("Florida Panthers won the Stanley Cup", final_embed["description"])
        self.assertIn("Players out: 3 of 3", final_embed["fields"][2]["value"])
        self.assertTrue(self.state()["final_posted"])

        # Afterwards the job does nothing.
        calls = len(self.nhl.urls)
        code, out = self.run_pool(et(2027, 4, 20, 7, 45))
        self.assertEqual((code, len(self.sent)), (0, 2))
        self.assertIn("the pool is over", out)
        self.assertEqual(self.nhl.count("gamecenter"), sum(1 for u in self.nhl.urls[:calls] if "gamecenter" in u))

    def test_deadline_added_to_the_post_once_published(self) -> None:
        playoff_games = [g for g in self.nhl.fx["games"] if g["gameType"] == 3]
        self.nhl.fx["games"] = [g for g in self.nhl.fx["games"] if g["gameType"] != 3]
        self.run_pool(et(2027, 4, 15, 7, 45))
        self.assertIsNone(json.loads(self.paths["boxes_path"].read_text())["deadline"])
        self.assertIn("hasn't published", self.upserts[0][0]["embeds"][0]["description"])
        self.nhl.fx["games"] += playoff_games
        self.run_pool(et(2027, 4, 15, 19, 45))
        self.assertEqual(len(self.upserts), 2)
        self.assertEqual(self.upserts[1][1], "m1", "the same post is edited")
        self.assertEqual(json.loads(self.paths["boxes_path"].read_text())["deadline"], FIRST_PUCK.isoformat())

    def test_standings_wait_for_their_time_and_need_entries(self) -> None:
        self.run_pool(et(2027, 4, 16, 7, 45))
        code, out = self.run_pool(et(2027, 4, 18, 6, 30))
        self.assertIn("no valid entries", out)
        self.write_entries(bx.Boxes.from_dict(json.loads(self.paths["boxes_path"].read_text())))
        code, out = self.run_pool(et(2027, 4, 18, 6, 30))
        self.assertIn("standings post after 07:30", out)
        self.assertEqual(self.sent, [])

    def test_preview_and_test_modes_change_nothing(self) -> None:
        code, out = self.run_pool(et(2027, 4, 16, 7, 45), mode="preview")
        self.assertEqual((code, self.upserts, self.sent), (0, [], []))
        self.assertIn('"title": "2027 Playoff Pool: The Boxes"', out)
        self.assertFalse(self.paths["state_path"].exists() or self.paths["boxes_path"].exists())
        code, out = self.run_pool(et(2027, 4, 16, 7, 45), mode="test")
        self.assertEqual((code, len(self.sent), self.upserts), (0, 1, []))
        self.assertTrue(self.sent[0]["embeds"][0]["title"].startswith("[TEST] "))
        self.assertFalse(self.paths["state_path"].exists())

    def test_past_year_is_preview_only(self) -> None:
        code, out = self.run_pool(et(2027, 10, 8, 9), year=2027)
        self.assertEqual(code, 1)
        self.assertIn("preview and test runs only", out)
        code, out = self.run_pool(et(2027, 10, 8, 9), mode="preview", year=2027)
        self.assertEqual(code, 0, out)
        self.assertIn("current-roster filter skipped", out)
        self.assertEqual(self.nhl.count("roster/"), 0)


class ScheduleConfigTests(unittest.TestCase):
    def test_job_health_and_workflow_agree(self) -> None:
        schedule = yaml.safe_load((AUTOMATION / "scheduler" / "schedule.yaml").read_text())
        job = next(j for j in schedule["jobs"] if j["id"] == "playoff-pool")
        self.assertEqual(job["when"], "nhl-playoffs")
        self.assertNotIn("phases", job, "the NHL playoffs fall in the BLHA Offseason")
        health = yaml.safe_load((AUTOMATION / "health" / "health_config.yaml").read_text())
        self.assertIn(job["workflow"], [w["file"] for w in health["workflows"]])
        workflow = (AUTOMATION.parent / ".github" / "workflows" / job["workflow"]).read_text()
        for needle in ("timeout-minutes:", "concurrency:", "permissions:", "state_branch.sh restore",
                       "state_branch.sh save", "automation/playoff_pool/state/boxes.json"):
            self.assertIn(needle, workflow)


if __name__ == "__main__":
    unittest.main()
