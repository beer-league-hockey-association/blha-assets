#!/usr/bin/env python3
"""Offline checks for the dormancy guard."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dormancy  # noqa: E402

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


class FakeGitHub:
    def __init__(self, workflows, quiet_days):
        self._w, self._q, self.enabled = workflows, quiet_days, []

    def workflows(self):
        return self._w

    def last_commit_at(self):
        return NOW - timedelta(days=self._q)

    def enable(self, wid):
        if wid == 99:
            raise RuntimeError("403")
        self.enabled.append(wid)


WF = [
    {"id": 1, "name": "BLHA Scheduler", "state": "disabled_inactivity"},
    {"id": 2, "name": "BLHA Wire Engine", "state": "active"},
    {"id": 3, "name": "Old thing", "state": "disabled_manually"},
]


class RuleTests(unittest.TestCase):
    def test_only_inactivity_disabled_workflows_are_selected(self):
        self.assertEqual([w["id"] for w in dormancy.inactive_workflows(WF)], [1])
        self.assertEqual(dormancy.manually_disabled(WF), ["Old thing"])

    def test_warning_starts_at_45_days_and_repeats_weekly(self):
        self.assertFalse(dormancy.should_warn(NOW - timedelta(days=44), NOW, None))
        self.assertTrue(dormancy.should_warn(NOW - timedelta(days=45), NOW, None))
        self.assertFalse(dormancy.should_warn(NOW - timedelta(days=50), NOW, (NOW - timedelta(days=3)).isoformat()))
        self.assertTrue(dormancy.should_warn(NOW - timedelta(days=50), NOW, (NOW - timedelta(days=8)).isoformat()))

    def test_message_has_no_bullets(self):
        task = dormancy.build_task(["BLHA Scheduler"], [], 50)
        self.assertNotIn("•", "\n".join(task["items"]))
        self.assertIn("about 10 days away", "\n".join(task["items"]))


class RunTests(unittest.TestCase):
    def _run(self, gh, mode="live", saved=None, ok=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "dormancy.json"
        if saved is not None:
            state.write_text(json.dumps(saved))
        posts = []

        def fake_post(secret, payload):
            posts.append(payload)
            return ok, "delivered" if ok else "boom"

        with patch.object(dormancy, "STATE_PATH", state), patch.object(dormancy, "post_discord_webhook", fake_post):
            code = dormancy.run(mode, gh, NOW)
        return code, posts, state

    def test_inactive_workflow_is_reenabled_and_reported(self):
        gh = FakeGitHub(WF, 5)
        code, posts, _ = self._run(gh)
        self.assertEqual((code, gh.enabled, len(posts)), (0, [1], 1))
        self.assertIn("BLHA Scheduler", posts[0]["embeds"][0]["description"])

    def test_preview_changes_nothing(self):
        gh = FakeGitHub(WF, 50)
        code, posts, state = self._run(gh, mode="preview")
        self.assertEqual((code, gh.enabled, posts), (0, [], []))
        self.assertFalse(state.exists())

    def test_quiet_healthy_repo_posts_nothing(self):
        gh = FakeGitHub([WF[1], WF[2]], 10)
        code, posts, _ = self._run(gh)
        self.assertEqual((code, posts), (0, []))

    def test_warning_is_saved_so_it_is_not_daily(self):
        gh = FakeGitHub([WF[1]], 47)
        code, posts, state = self._run(gh)
        self.assertEqual((code, len(posts)), (0, 1))
        self.assertIn("last_warned", json.loads(state.read_text()))
        code, posts, _ = self._run(gh, saved=json.loads(state.read_text()))
        self.assertEqual(posts, [])

    def test_failed_enable_is_reported_and_fails_the_run(self):
        gh = FakeGitHub([{"id": 99, "name": "Stuck", "state": "disabled_inactivity"}], 5)
        code, posts, _ = self._run(gh)
        self.assertEqual(code, 1)
        self.assertIn("Could not re-enable", posts[0]["embeds"][0]["description"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
