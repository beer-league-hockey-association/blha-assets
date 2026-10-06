#!/usr/bin/env python3
"""Offline regression checks for BLHA playoff bracket logic."""

from __future__ import annotations

import copy
import unittest

import playoff


class PlayoffLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seeds = {
            seed: {
                "teamId": f"t{seed}",
                "teamName": f"Team {seed}",
                "record": "0-0-0",
                "pointsFor": 0.0,
            }
            for seed in range(1, 7)
        }

    def test_reseed_gives_seed_one_lowest_ranked_survivor(self) -> None:
        pairs = playoff.expected_semis(
            self.seeds,
            [self.seeds[3], self.seeds[6]],
        )
        self.assertEqual(playoff.seed_of(pairs[0][0], self.seeds), 1)
        self.assertEqual(playoff.seed_of(pairs[0][1], self.seeds), 6)
        self.assertEqual(playoff.seed_of(pairs[1][0], self.seeds), 2)
        self.assertEqual(playoff.seed_of(pairs[1][1], self.seeds), 3)

    def test_reseed_handles_four_and_five_survivors(self) -> None:
        pairs = playoff.expected_semis(
            self.seeds,
            [self.seeds[4], self.seeds[5]],
        )
        self.assertEqual(playoff.seed_of(pairs[0][1], self.seeds), 5)
        self.assertEqual(playoff.seed_of(pairs[1][1], self.seeds), 4)

    def test_semantic_fingerprint_ignores_timestamp(self) -> None:
        payload = {
            "embeds": [
                {
                    "title": "BLHA Playoffs",
                    "description": "same bracket",
                    "fields": [],
                    "color": 0xFFB81C,
                    "timestamp": "2026-10-01T12:00:00+00:00",
                }
            ]
        }
        later = copy.deepcopy(payload)
        later["embeds"][0]["timestamp"] = "2026-10-01T18:00:00+00:00"
        self.assertEqual(
            playoff.semantic_fingerprint(payload),
            playoff.semantic_fingerprint(later),
        )

    def test_semantic_fingerprint_changes_with_bracket_content(self) -> None:
        payload = {
            "embeds": [
                {
                    "title": "BLHA Playoffs",
                    "description": "same bracket",
                    "fields": [{"name": "ROUND 1", "value": "3 vs 6"}],
                    "timestamp": "2026-10-01T12:00:00+00:00",
                }
            ]
        }
        changed = copy.deepcopy(payload)
        changed["embeds"][0]["fields"][0]["value"] = "3 beat 6"
        self.assertNotEqual(
            playoff.semantic_fingerprint(payload),
            playoff.semantic_fingerprint(changed),
        )


def team(tid: str, score: float = 0.0) -> dict:
    return {"teamId": tid, "teamName": f"Team {tid}", "score": score, "gamesPlayed": 0.0}


def game(a: str, sa: float, b: str, sb: float) -> dict:
    return {"away": team(a, sa), "home": team(b, sb)}


class BracketTests(unittest.TestCase):
    """Playoffs, third place and consolation in shared playoff weeks."""

    def setUp(self) -> None:
        self.seeds = {n: {"teamId": f"t{n}", "teamName": f"Team t{n}", "record": "", "pointsFor": 0.0}
                      for n in range(1, 7)}
        self.cons = {n: {"teamId": f"c{n}", "teamName": f"Team c{n}", "record": "", "pointsFor": 0.0}
                     for n in range(1, 7)}
        # Week 23: QFs plus consolation round 1 in the same Fantrax week.
        self.w1 = [game("t3", 100, "t6", 90), game("t4", 80, "t5", 85),
                   game("c3", 70, "c6", 75), game("c4", 60, "c5", 50)]
        # Week 24: semis (1 v 6 worst survivor... here 5, 2 v 3) plus consolation semis.
        self.w2 = [game("t1", 110, "t5", 120), game("t2", 95, "t3", 99),
                   game("c1", 50, "c6", 40), game("c2", 45, "c4", 47)]

    def scores(self, *weeks):
        return {23 + i: w for i, w in enumerate(weeks)}

    def finals(self, n):
        return {23 + i: True for i in range(n)}

    def test_consolation_games_do_not_leak_into_playoff_semis(self) -> None:
        rounds = playoff.bracket_rounds(self.seeds, self.scores(self.w1), self.finals(1), 23)
        semis = [tuple(t["teamId"] for t in item["pair"]) for item in rounds[2]["matchups"]]
        self.assertEqual(semis, [("t1", "t5"), ("t2", "t3")])

    def test_final_score_found_among_other_matchups(self) -> None:
        w3 = [game("c1", 130, "c4", 120), game("t5", 200, "t3", 210), game("t1", 150, "t2", 140)]
        rounds = playoff.bracket_rounds(self.seeds, self.scores(self.w1, self.w2, w3), self.finals(3), 23)
        final = rounds[3]["matchups"][0]
        self.assertIsNotNone(final["score"])
        self.assertEqual(final["winner"]["teamId"], "t3")

    def test_consolation_bracket_uses_its_own_seeds(self) -> None:
        w3 = [game("c1", 130, "c4", 120), game("t5", 200, "t3", 210)]
        rounds = playoff.bracket_rounds(self.cons, self.scores(self.w1, self.w2, w3), self.finals(3), 23)
        r2 = [tuple(t["teamId"] for t in item["pair"]) for item in rounds[2]["matchups"]]
        self.assertEqual(r2, [("c1", "c6"), ("c2", "c4")])
        self.assertEqual(rounds[3]["matchups"][0]["winner"]["teamId"], "c1")

    def test_third_place_waits_for_semis(self) -> None:
        third = playoff.third_place(self.seeds, self.scores(self.w1), self.finals(1), 23)
        self.assertEqual(third["status"], "waiting")

    def test_third_place_from_fantrax_matchup(self) -> None:
        w3 = [game("t5", 200, "t3", 210), game("t1", 150, "t2", 160)]
        third = playoff.third_place(self.seeds, self.scores(self.w1, self.w2, w3), self.finals(3), 23)
        self.assertEqual(third["status"], "matchup")
        self.assertEqual(third["winner"]["teamId"], "t2")

    def test_third_place_matchup_tie_goes_to_higher_seed(self) -> None:
        w3 = [game("t5", 200, "t3", 210), game("t2", 150, "t1", 150)]
        third = playoff.third_place(self.seeds, self.scores(self.w1, self.w2, w3), self.finals(3), 23)
        self.assertEqual(third["winner"]["teamId"], "t1")

    def test_third_place_no_winner_until_final(self) -> None:
        w3 = [game("t5", 200, "t3", 210), game("t1", 150, "t2", 160)]
        finals = {23: True, 24: True, 25: False}
        third = playoff.third_place(self.seeds, self.scores(self.w1, self.w2, w3), finals, 23)
        self.assertIsNone(third["winner"])

    def test_third_place_without_matchup_shows_waiting(self) -> None:
        w3 = [game("t5", 200, "t3", 210)]
        third = playoff.third_place(self.seeds, self.scores(self.w1, self.w2, w3), self.finals(3), 23)
        self.assertEqual(third["status"], "no_matchup")

    def test_payload_has_third_place_and_consolation_fields(self) -> None:
        w3 = [game("c1", 130, "c4", 120), game("t5", 200, "t3", 210), game("t1", 150, "t2", 160)]
        sc, fin = self.scores(self.w1, self.w2, w3), self.finals(3)
        rounds = playoff.bracket_rounds(self.seeds, sc, fin, 23)
        extras = {
            "third": playoff.third_place(self.seeds, sc, fin, 23),
            "consolation": playoff.bracket_rounds(self.cons, sc, fin, 23),
            "consolation_seeds": self.cons,
        }
        payload = playoff.build_payload({}, self.seeds, rounds, {}, "CHAMPION CROWNED", extras=extras)
        fields = payload["embeds"][0]["fields"]
        names = [f["name"] for f in fields]
        self.assertIn("THIRD PLACE", names)
        self.assertIn("CONSOLATION — FINAL", names)
        cons_final = next(f for f in fields if f["name"] == "CONSOLATION — FINAL")["value"]
        self.assertIn("$50 FAAB", cons_final)
        self.assertTrue(all(len(f["value"]) <= 1024 for f in fields))
        embed = payload["embeds"][0]
        total = len(embed["title"]) + len(embed["description"]) + sum(len(f["name"]) + len(f["value"]) for f in fields)
        self.assertLess(total, 6000)

    def test_consolation_seed_map_needs_six_teams(self) -> None:
        rows = [{"teamId": f"x{i}", "teamName": f"X{i}", "record": "", "pointsFor": 0.0} for i in range(12)]
        cons = playoff.consolation_seed_map(rows, 6)
        self.assertEqual(cons[1]["teamId"], "x6")
        self.assertIsNone(playoff.consolation_seed_map(rows[:10], 6))


if __name__ == "__main__":
    unittest.main()
