#!/usr/bin/env python3
"""Shared resilient Discord webhook delivery for BLHA automations.

Supports posting a new message and editing a message the same webhook posted
earlier. Editing lets live views (scoreboard, playoff bracket) stay current in
a single post instead of flooding a channel with new messages; Discord does
not notify members when a message is edited.
"""

from __future__ import annotations

import json
import re
import os
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

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


_WEBHOOK_PATH = re.compile(r"(/api/(?:v\d+/)?webhooks/)[^\s'\"?)]+")


def redact(text: str) -> str:
    """Hide webhook ids and tokens that requests puts in its error messages."""
    return _WEBHOOK_PATH.sub(r"\1***", str(text))


def _send_with_retries(
    send: Callable[[], requests.Response],
    attempts: int,
    *,
    creates: bool = False,
) -> tuple[requests.Response | None, str]:
    """Run ``send`` with bounded retries. Returns the final response (or None).

    ``creates`` marks a request that posts a new message. Those are retried only
    when Discord certainly did not receive them (connection errors, 429), so a
    slow reply or a 5xx after Discord accepted the post can't make a duplicate.
    """
    last_detail = "unknown delivery failure"
    response: requests.Response | None = None
    for attempt in range(max(1, attempts)):
        response = None
        try:
            response = send()
            if response.status_code in (200, 204):
                return response, "delivered"
            last_detail = redact(f"Discord returned {response.status_code}: {response.text[:300]}")
            if response.status_code not in RETRYABLE_STATUS:
                return response, last_detail
            if creates and response.status_code != 429:
                return response, last_detail
        except requests.ConnectionError as exc:  # includes ConnectTimeout; never sent
            last_detail = redact(f"Discord request failed: {exc}")
        except requests.RequestException as exc:
            last_detail = redact(f"Discord request failed: {exc}")
            if creates:
                return response, last_detail

        if attempt < attempts - 1:
            time.sleep(_retry_delay(response, attempt))
    return response, last_detail


def _webhook_url(secret_name: str) -> str:
    return os.getenv(secret_name, "").strip()


def message_url(webhook: str, message_id: str) -> str:
    """Build the edit URL for a message posted by ``webhook``."""
    parts = urlsplit(webhook)
    path = parts.path.rstrip("/") + f"/messages/{message_id}"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def send_discord_webhook(
    secret_name: str,
    payload: dict[str, Any],
    *,
    timeout: int = 25,
    attempts: int = 4,
) -> tuple[bool, str, str | None]:
    """Post a new message. Returns (ok, detail, message_id)."""
    webhook = _webhook_url(secret_name)
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}", None

    response, detail = _send_with_retries(
        lambda: requests.post(webhook, params={"wait": "true"}, json=payload, timeout=timeout),
        attempts,
        creates=True,
    )
    if detail != "delivered":
        return False, detail, None

    message_id = None
    try:
        body = response.json() if response is not None and response.status_code == 200 else {}
        message_id = str(body.get("id") or "") or None
    except Exception:
        message_id = None
    return True, "delivered", message_id


def post_discord_webhook_files(
    secret_name: str,
    payload: dict[str, Any],
    files: list[tuple[str, bytes]],
    *,
    timeout: int = 60,
    attempts: int = 4,
) -> tuple[bool, str]:
    """Post one message with attached files (for example a PNG an embed shows as
    ``attachment://<name>``). Same retry handling as post_discord_webhook."""
    webhook = _webhook_url(secret_name)
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}"
    body = dict(payload)
    body["attachments"] = [{"id": i, "filename": name} for i, (name, _) in enumerate(files)]

    def send() -> requests.Response:
        multipart = {f"files[{i}]": (name, data, "image/png" if name.endswith(".png") else "application/octet-stream")
                     for i, (name, data) in enumerate(files)}
        return requests.post(webhook, params={"wait": "true"}, data={"payload_json": json.dumps(body)},
                             files=multipart, timeout=timeout)

    _, detail = _send_with_retries(send, attempts, creates=True)
    return detail == "delivered", detail


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
    ok, detail, _ = send_discord_webhook(secret_name, payload, timeout=timeout, attempts=attempts)
    return ok, detail


def edit_discord_message(
    secret_name: str,
    message_id: str,
    payload: dict[str, Any],
    *,
    timeout: int = 25,
    attempts: int = 4,
) -> tuple[bool, str, int | None]:
    """Edit a message this webhook posted. Returns (ok, detail, http_status)."""
    webhook = _webhook_url(secret_name)
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}", None

    body = {key: value for key, value in payload.items() if key not in ("username", "avatar_url")}
    response, detail = _send_with_retries(
        lambda: requests.patch(message_url(webhook, message_id), json=body, timeout=timeout),
        attempts,
    )
    status = response.status_code if response is not None else None
    return detail == "delivered", detail, status


def _get_json(url: str, timeout: int, attempts: int) -> tuple[bool, str, dict[str, Any] | None]:
    response, detail = _send_with_retries(lambda: requests.get(url, timeout=timeout), attempts)
    if detail != "delivered" or response is None:
        return False, detail, None
    try:
        body = response.json()
    except Exception:
        return False, "Discord returned a body that is not JSON", None
    return (True, "ok", body) if isinstance(body, dict) else (False, "Discord returned an unexpected body", None)


def get_discord_message(
    secret_name: str,
    message_id: str,
    *,
    timeout: int = 25,
    attempts: int = 3,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Read back a message this webhook posted ("Get Webhook Message"), e.g. for poll results.

    Returns (ok, detail, message object).
    """
    webhook = _webhook_url(secret_name)
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}", None
    return _get_json(message_url(webhook, message_id), timeout, attempts)


def get_webhook(secret_name: str, *, timeout: int = 25, attempts: int = 3) -> tuple[bool, str, dict[str, Any] | None]:
    """The webhook object ("Get Webhook with Token"): its guild_id and channel_id, for message links."""
    webhook = _webhook_url(secret_name)
    if not webhook:
        return False, f"missing GitHub Actions secret {secret_name}", None
    return _get_json(webhook, timeout, attempts)


def upsert_discord_message(
    secret_name: str,
    payload: dict[str, Any],
    message_id: str | None,
) -> tuple[bool, str, str | None, str]:
    """Edit ``message_id`` if given, otherwise (or if it was deleted) post new.

    Returns (ok, detail, message_id, action) where action is "edited",
    "posted", or "failed".
    """
    if message_id:
        ok, detail, status = edit_discord_message(secret_name, message_id, payload)
        if ok:
            return True, detail, message_id, "edited"
        if status not in (404,):
            return False, detail, message_id, "failed"
        # The message was deleted in Discord; fall through and post a new one.

    ok, detail, new_id = send_discord_webhook(secret_name, payload)
    return ok, detail, new_id, "posted" if ok else "failed"
