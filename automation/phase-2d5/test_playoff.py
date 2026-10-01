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


if __name__ == "__main__":
    unittest.main()
