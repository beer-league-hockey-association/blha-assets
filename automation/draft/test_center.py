#!/usr/bin/env python3
"""Offline checks for the Draft Center, using the test league's real draft data."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import center  # noqa: E402
from blha import draft as dr  # noqa: E402

ET = ZoneInfo("America/New_York")
FIXTURE = json.loads((ROOT.parent / "tests" / "fixtures" / "draft_results_2026_test.json").read_text())
TEAMS = FIXTURE["_teams"]
INFO = {"draftType": "snake", "teamInfo": {tid: {"name": name, "id": tid} for tid, name in TEAMS.items()}}
LEAGUE = {"league_id": "x", "timezone": "America/New_York", "color": 0xFFB81C}
CFG = center.load_config({"draft_center": {"drafts": {"startup": {"pick_clock_hours": 4}}}})


def et(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


def build_raw(rounds: int = 36, made: int | None = None, date: datetime | None = None,
              state: str = "", times: dict[int, datetime] | None = None) -> dict:
    """A Fantrax-shaped getDraftResults body: snake order from the real draftOrder."""
    order = FIXTURE["draftOrder"]
    picks = []
    overall = 0
    for rnd in range(1, rounds + 1):
        seq = order if rnd % 2 else list(reversed(order))
        for i, team in enumerate(seq, start=1):
            overall += 1
            row = {"round": rnd, "pick": overall, "teamId": team, "pickInRound": i}
            if made is None or overall <= made:
                row["playerId"] = f"p{overall:03d}"
                when = (times or {}).get(overall)
                row["time"] = int(when.timestamp() * 1000) if when else 1791072006000
            picks.append(row)
    date = date or et(2027, 7, 15, 20)
    return {
        "draftDate": date.astimezone(ET).strftime("%Y-%m-%dT%H:%M:%S.0%z"),
        "draftState": state,
        "startDate": None, "endDate": None,
        "draftOrder": order, "draftPicks": picks,
    }


class ParsingTests(unittest.TestCase):
    def test_real_fixture_shape(self) -> None:
        d = dr.parse_results(FIXTURE)
        self.assertEqual(d.state, "completed")
        self.assertTrue(d.completed)
        self.assertEqual(d.rounds, 2)
        self.assertEqual(d.picks[12].team_id, FIXTURE["draftOrder"][-1])  # snake: 2.01 is round 1's last team
        self.assertEqual(d.picks[0].label, "1.01")
        self.assertEqual(d.date, et(2026, 10, 3, 20))

    def test_startup_kind_from_rounds(self) -> None:
        d = dr.parse_results(build_raw(36))
        self.assertEqual(center.draft_kind(d, INFO, CFG), "startup")
        five = dr.parse_results(build_raw(5))
        self.assertEqual(center.draft_kind(five, INFO, CFG), "annual")

    def test_status(self) -> None:
        date = et(2027, 7, 15, 20)
        pre = dr.parse_results(build_raw(36, made=0, date=date))
        self.assertEqual(pre.status(date - timedelta(hours=1)), "pre")
        self.assertEqual(pre.status(date + timedelta(minutes=5)), "live")
        live = dr.parse_results(build_raw(36, made=30, date=date))
        self.assertEqual(live.status(date + timedelta(hours=5)), "live")
        self.assertEqual(live.on_the_clock().overall, 31)
        self.assertEqual(dr.parse_results(build_raw(36, date=date)).status(date), "done")


class WindowTests(unittest.TestCase):
    lead, linger = timedelta(days=31), timedelta(hours=24)

    def test_opens_31_days_before(self) -> None:
        d = dr.parse_results(build_raw(36, made=0, date=et(2027, 7, 15, 20)))
        self.assertIsNone(dr.window_start(d, et(2027, 6, 13, 12), self.lead, self.linger))
        self.assertIsNotNone(dr.window_start(d, et(2027, 6, 15, 12), self.lead, self.linger))

    def test_closes_a_day_after_finish(self) -> None:
        d = dr.parse_results(FIXTURE)  # finished Oct 3, 2026 20:00:07 ET
        self.assertIsNotNone(dr.window_start(d, et(2026, 10, 4, 11), self.lead, self.linger))
        self.assertIsNone(dr.window_start(d, et(2026, 10, 4, 21), self.lead, self.linger))

    def test_stale_unstarted_date_closes(self) -> None:
        d = dr.parse_results(build_raw(36, made=0, date=et(2027, 7, 15, 20)))
        self.assertIsNone(dr.window_start(d, et(2027, 7, 25, 12), self.lead, self.linger))


class CountdownTests(unittest.TestCase):
    date = et(2027, 7, 15, 20)

    def plan(self, now: datetime, done: dict | None = None, made: int = 0) -> tuple:
        d = dr.parse_results(build_raw(36, made=made, date=self.date))
        return center.plan_countdown(d, {"countdown": done or {}}, now, CFG)

    def test_nothing_before_30_days(self) -> None:
        self.assertEqual(self.plan(self.date - timedelta(days=40)), (None, []))

    def test_announcement_at_30_days(self) -> None:
        self.assertEqual(self.plan(self.date - timedelta(days=29, hours=23)), ("30d", []))

    def test_next_step(self) -> None:
        self.assertEqual(self.plan(self.date - timedelta(days=6), {"30d": "x"}), ("7d", []))

    def test_late_check_posts_only_latest(self) -> None:
        send, skip = self.plan(self.date - timedelta(hours=20))
        self.assertEqual(send, "1d")
        self.assertEqual(sorted(skip), ["30d", "7d"])

    def test_start_skips_unsent_hour_warning(self) -> None:
        done = {"30d": "x", "7d": "x", "1d": "x"}
        send, skip = self.plan(self.date + timedelta(minutes=10), done, made=2)
        self.assertEqual((send, skip), ("start", ["1h"]))

    def test_completed_draft_has_no_countdown(self) -> None:
        d = dr.parse_results(build_raw(36, date=self.date, state="completed"))
        self.assertEqual(center.plan_countdown(d, {}, self.date - timedelta(days=1), CFG), (None, []))


class OrderTests(unittest.TestCase):
    date = et(2027, 7, 15, 20)

    def test_reveal_seven_days_out(self) -> None:
        d = dr.parse_results(build_raw(36, made=0, date=self.date))
        self.assertIsNone(center.plan_order(d, [], {}, self.date - timedelta(days=8), CFG))
        self.assertEqual(center.plan_order(d, [], {}, self.date - timedelta(days=6), CFG), "reveal")

    def test_force_reveal_and_update(self) -> None:
        d = dr.parse_results(build_raw(36, made=0, date=self.date))
        early = self.date - timedelta(days=20)
        self.assertEqual(center.plan_order(d, [], {}, early, CFG, force=True), "reveal")
        entry = {"order_posted": "x", "order_fp": center.order_fingerprint(d.order, [])}
        self.assertIsNone(center.plan_order(d, [], entry, early, CFG))
        moved = [{"round": 1, "pick": 3, "original": d.order[2], "current": d.order[0]}]
        self.assertEqual(center.plan_order(d, moved, entry, early, CFG), "update")

    def test_no_order_posts_once_draft_starts(self) -> None:
        d = dr.parse_results(build_raw(36, made=3, date=self.date))
        self.assertIsNone(center.plan_order(d, [], {}, self.date + timedelta(hours=1), CFG))


class RecapTests(unittest.TestCase):
    date = et(2027, 7, 15, 20)

    def test_completed_rounds_post_as_they_finish(self) -> None:
        d = dr.parse_results(build_raw(36, made=30, date=self.date))
        now = self.date + timedelta(hours=8)
        self.assertEqual(center.plan_recap(d, {}, now), ([1, 2], False))
        self.assertEqual(center.plan_recap(d, {"rounds_posted": [1]}, now), ([2], False))

    def test_finished_draft_posts_rest_and_completion(self) -> None:
        d = dr.parse_results(build_raw(36, date=self.date, state="completed"))
        rounds, completion = center.plan_recap(d, {"rounds_posted": list(range(1, 31))}, self.date + timedelta(days=5))
        self.assertEqual((rounds, completion), ([31, 32, 33, 34, 35, 36], True))
        self.assertEqual(center.plan_recap(d, {"rounds_posted": list(range(1, 37)), "completed_posted": "x"},
                                           self.date + timedelta(days=5)), ([], False))

    def test_messages_fit_discord_limits(self) -> None:
        d = dr.parse_results(build_raw(36, date=self.date, state="completed"))
        players = {f"p{i:03d}": {"name": "Longname-Surname, Firstname-Middle", "position": "LW", "team": "CBJ"} for i in range(1, 433)}
        r = center.Renderer(LEAGUE, CFG, INFO, d, players)
        messages = r.round_messages(list(range(1, 37)))
        covered = [n for numbers, _ in messages for n in numbers]
        self.assertEqual(covered, list(range(1, 37)))
        for _, payload in messages:
            embeds = payload["embeds"]
            self.assertLessEqual(len(embeds), 10)
            total = sum(len(e["title"]) + len(e["description"]) + len(e["footer"]["text"]) for e in embeds)
            self.assertLessEqual(total, 6000)
        first_line = messages[0][1]["embeds"][0]["description"].splitlines()[0]
        self.assertIn("**1.01** · Test 4 — Firstname-Middle Longname-Surname (LW · CBJ)", first_line)


class AlertTests(unittest.TestCase):
    pause = center.pause_window(CFG)

    def test_active_minutes_skip_the_nightly_pause(self) -> None:
        start, end = et(2027, 7, 15, 23), et(2027, 7, 16, 9)
        self.assertEqual(center.active_minutes(start, end, ET, self.pause), 120)  # 23-00 and 08-09
        self.assertEqual(center.active_minutes(et(2027, 7, 16, 9), et(2027, 7, 16, 13), ET, self.pause), 240)

    def test_active_minutes_across_the_fall_dst_change(self) -> None:
        # Oct 31, 8 PM to Nov 1, 8 AM ET is 13 real hours (1-2 AM repeats).
        # The midnight-8 AM pause is 9 real hours, so 4 hours count.
        start, end = et(2026, 10, 31, 20), et(2026, 11, 1, 8)
        self.assertEqual(center.active_minutes(start, end, ET, self.pause), 240)

    def test_clock_runs_out_only_after_four_active_hours(self) -> None:
        last = et(2027, 7, 15, 23)
        d = dr.parse_results(build_raw(36, made=30, date=et(2027, 7, 15, 20), times={30: last}))
        self.assertEqual(center.plan_alerts(d, {}, et(2027, 7, 16, 3), ET, 240, self.pause), [])
        found = center.plan_alerts(d, {}, et(2027, 7, 16, 11), ET, 240, self.pause)
        self.assertEqual([(p.overall, why) for p, why in found], [(31, "expired")])
        self.assertEqual(center.plan_alerts(d, {"alerts": {"31": "expired"}}, et(2027, 7, 16, 11), ET, 240, self.pause), [])

    def test_paused_draft_does_not_time_out(self) -> None:
        d = dr.parse_results(build_raw(36, made=30, date=et(2027, 7, 15, 20), state="paused",
                                       times={30: et(2027, 7, 15, 9)}))
        self.assertEqual(center.plan_alerts(d, {}, et(2027, 7, 16, 18), ET, 240, self.pause), [])

    def test_skipped_pick_detected(self) -> None:
        raw = build_raw(36, made=33, date=et(2027, 7, 15, 20), times={33: et(2027, 7, 15, 20, 50)})
        del raw["draftPicks"][30]["playerId"]  # pick 31 skipped, 32 and 33 made
        d = dr.parse_results(raw)
        self.assertEqual(d.on_the_clock().overall, 34)
        found = center.plan_alerts(d, {}, et(2027, 7, 15, 21), ET, 240, self.pause)
        self.assertEqual([(p.overall, why) for p, why in found], [(31, "skipped")])

    def test_second_timeout_cites_article_13_5(self) -> None:
        d = dr.parse_results(build_raw(36, made=30, date=et(2027, 7, 15, 20)))
        r = center.Renderer(LEAGUE, CFG, INFO, d)
        pick = d.on_the_clock()
        task = r.alert_task([(pick, "expired")], {pick.team_id: 2})
        self.assertIn("Second timeout", task["items"][0])
        self.assertIn("Article 13.5", task["items"][-1])
        self.assertEqual(task["section"], "Article XIII")


class RenderTests(unittest.TestCase):
    def renderer(self, made: int = 0) -> center.Renderer:
        return center.Renderer(LEAGUE, CFG, INFO, dr.parse_results(build_raw(36, made=made, date=et(2027, 7, 15, 20))))

    def test_announcement_has_details(self) -> None:
        body = self.renderer().countdown("30d", first=True)
        embed = body["embeds"][0]
        self.assertEqual(embed["title"], "2027 BLHA Startup Draft")
        names = [f["name"] for f in embed["fields"]]
        self.assertEqual(names, ["START", "FORMAT", "PICK CLOCK", "DRAFT ROOM", "DRAFT ORDER"])
        self.assertIn("36 rounds, snake", embed["fields"][1]["value"])
        self.assertIn("4 hours per pick, paused nightly 00:00–08:00 ET (Article 13.4)", embed["fields"][2]["value"])
        self.assertEqual(body["allowed_mentions"], {"parse": []})

    def test_short_countdown(self) -> None:
        body = self.renderer().countdown("1h", first=False)
        self.assertEqual(body["embeds"][0]["title"], "2027 BLHA Startup Draft: 1 hour to go")

    def test_order_with_traded_pick(self) -> None:
        r = self.renderer()
        order = r.draft.order
        body = r.order([{"round": 2, "pick": 5, "original": order[4], "current": order[0]}], update=False)
        fields = body["embeds"][0]["fields"]
        self.assertTrue(fields[0]["value"].startswith("**1.** Test 4"))
        self.assertIn("Round 2, pick 5: **Test 4** (from Test 2)", fields[1]["value"])

    def test_test_clock_override(self) -> None:
        cfg = center.load_config({"draft_center": {"test_pick_clock_minutes": 5}})
        self.assertEqual(center.clock_minutes("startup", cfg), 5)
        self.assertEqual(center.clock_minutes("startup", CFG), 240)
        self.assertEqual(center.clock_minutes("annual", CFG), 480)


if __name__ == "__main__":
    unittest.main()
