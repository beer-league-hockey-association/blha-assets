#!/usr/bin/env python3
"""Shared resilient Discord webhook delivery for BLHA automations."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Return Discord's requested delay when available, else exponential backoff."""
    if response is not None and response.status_code == 429:
        try:
            payload = response.json()
            retry_after = float(payload.get("retry_after") or 0)
            if retry_after > 0:
                return min(retry_after, 30.0)
        except Exception:
            pass

        header = response.headers.get("Retry-After")
        if header:
            try:
                retry_after = float(header)
                if retry_after > 0:
                    return min(retry_after, 30.0)
            except ValueError:
                pass

    return min(2 ** attempt, 16)


def post_discord_webhook(
    secret_name: str,
    payload: dict[str, Any],
    *,
    timeout: int = 25,
    attempts: int = 4,
) -> tuple[bool, str]:
    """Post a Discord webhook payload with bounded retry handling.

    Retries transient network failures, Discord rate limits, and common
    temporary HTTP failures. The webhook URL is always read from an
    environment variable so credentials never enter repository content.
    """
    webhook = os.getenv(secret_name, "").strip()
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}"

    last_detail = "unknown delivery failure"
    for attempt in range(max(1, attempts)):
        response: requests.Response | None = None
        try:
            response = requests.post(
                webhook,
                params={"wait": "true"},
                json=payload,
                timeout=timeout,
            )
            if response.status_code in (200, 204):
                return True, "delivered"

            last_detail = (
                f"Discord returned {response.status_code}: "
                f"{response.text[:300]}"
            )
            if response.status_code not in RETRYABLE_STATUS:
                return False, last_detail
        except requests.RequestException as exc:
            last_detail = f"Discord request failed: {exc}"

        if attempt < attempts - 1:
            time.sleep(_retry_delay(response, attempt))

    return False, last_detail
