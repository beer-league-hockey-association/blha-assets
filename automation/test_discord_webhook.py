#!/usr/bin/env python3
"""Offline regression tests for shared Discord webhook delivery."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

import discord_webhook


class DiscordWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "TEST_DISCORD_WEBHOOK"
        os.environ[self.secret] = "https://discord.example.invalid/webhook"

    def tearDown(self) -> None:
        os.environ.pop(self.secret, None)

    def test_missing_secret_fails_without_request(self) -> None:
        os.environ.pop(self.secret, None)
        with patch("discord_webhook.requests.post") as post:
            ok, detail = discord_webhook.post_discord_webhook(self.secret, {})
        self.assertFalse(ok)
        self.assertIn(self.secret, detail)
        post.assert_not_called()

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_rate_limit_retries_then_succeeds(self, post: Mock, sleep: Mock) -> None:
        limited = Mock(status_code=429, text="rate limited", headers={})
        limited.json.return_value = {"retry_after": 0.25}
        success = Mock(status_code=204, text="", headers={})
        post.side_effect = [limited, success]

        ok, detail = discord_webhook.post_discord_webhook(self.secret, {"embeds": []})

        self.assertTrue(ok)
        self.assertEqual(detail, "delivered")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.25)

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_nonretryable_error_stops_immediately(self, post: Mock, sleep: Mock) -> None:
        bad = Mock(status_code=400, text="bad request", headers={})
        post.return_value = bad

        ok, detail = discord_webhook.post_discord_webhook(self.secret, {})

        self.assertFalse(ok)
        self.assertIn("400", detail)
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_new_post_not_retried_after_read_timeout(self, post: Mock, sleep: Mock) -> None:
        post.side_effect = discord_webhook.requests.ReadTimeout("read timed out")
        ok, _ = discord_webhook.post_discord_webhook(self.secret, {})
        self.assertFalse(ok)
        self.assertEqual(post.call_count, 1)

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_new_post_not_retried_after_server_error(self, post: Mock, sleep: Mock) -> None:
        post.return_value = Mock(status_code=502, text="bad gateway", headers={})
        ok, _ = discord_webhook.post_discord_webhook(self.secret, {})
        self.assertFalse(ok)
        self.assertEqual(post.call_count, 1)

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_connection_error_is_retried(self, post: Mock, sleep: Mock) -> None:
        post.side_effect = [discord_webhook.requests.ConnectionError("no route"),
                            Mock(status_code=204, text="", headers={})]
        ok, _ = discord_webhook.post_discord_webhook(self.secret, {})
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)

    @patch("discord_webhook.time.sleep")
    @patch("discord_webhook.requests.post")
    def test_error_detail_hides_webhook_token(self, post: Mock, sleep: Mock) -> None:
        post.side_effect = discord_webhook.requests.ConnectionError(
            "HTTPSConnectionPool(host='discord.com', port=443): Max retries exceeded with url: "
            "/api/webhooks/1234567890/SECRET-TOKEN_abc?wait=true (Caused by NameResolutionError)")
        ok, detail = discord_webhook.post_discord_webhook(self.secret, {})
        self.assertFalse(ok)
        self.assertNotIn("SECRET-TOKEN", detail)
        self.assertNotIn("1234567890", detail)
        self.assertIn("/api/webhooks/***", detail)


if __name__ == "__main__":
    unittest.main()
