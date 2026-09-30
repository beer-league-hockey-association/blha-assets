#!/usr/bin/env python3
"""Controlled Discord webhook test for BLHA The Wire.

This script does not read feeds, modify dedupe state, or post to the transaction
channel. It only sends clearly labeled test embeds to the selected Wire channel(s).
"""

from __future__ import annotations

import argparse
import os
import sys

import requests

WEBHOOKS = {
    "breaking-news": "BLHA_WEBHOOK_BREAKING_NEWS",
    "nhl-news": "BLHA_WEBHOOK_NHL_NEWS",
    "injury-report": "BLHA_WEBHOOK_INJURY_REPORT",
    "prospect-wire": "BLHA_WEBHOOK_PROSPECT_WIRE",
}

CHANNELS = {
    "breaking-news": {
        "label": "🚨 BREAKING NEWS",
        "title": "[TEST] BLHA Breaking News Delivery",
        "description": "Controlled test message for the BLHA Breaking News webhook. No real news event is being reported.",
        "color": 0xC73E3A,
    },
    "nhl-news": {
        "label": "📰 NHL NEWS",
        "title": "[TEST] BLHA NHL News Delivery",
        "description": "Controlled test message for the BLHA NHL News webhook. The routing and delivery path is working if you can see this.",
        "color": 0xFFB81C,
    },
    "injury-report": {
        "label": "🏥 INJURY REPORT",
        "title": "[TEST] BLHA Injury Report Delivery",
        "description": "Controlled test message for the BLHA Injury Report webhook. No player injury is being reported.",
        "color": 0xD97706,
    },
    "prospect-wire": {
        "label": "🌱 PROSPECT WIRE",
        "title": "[TEST] BLHA Prospect Wire Delivery",
        "description": "Controlled test message for the BLHA Prospect Wire webhook. No prospect update is being reported.",
        "color": 0xC68F15,
    },
}

AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)


def payload(channel: str) -> dict:
    cfg = CHANNELS[channel]
    return {
        "username": "BLHA News Wire",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": cfg["title"],
                "description": cfg["description"],
                "color": cfg["color"],
                "footer": {"text": f"{cfg['label']} • BLHA THE WIRE • DELIVERY TEST"},
            }
        ],
    }


def send(channel: str) -> bool:
    env = WEBHOOKS[channel]
    url = os.getenv(env, "").strip()
    if not url:
        print(f"ERROR [{channel}]: missing secret {env}")
        return False

    try:
        response = requests.post(url, params={"wait": "true"}, json=payload(channel), timeout=25)
    except Exception as exc:
        print(f"ERROR [{channel}]: request failed: {exc}")
        return False

    if response.status_code not in (200, 204):
        print(f"ERROR [{channel}]: Discord returned {response.status_code}: {response.text[:300]}")
        return False

    print(f"PASS [{channel}]: test message delivered")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--channel",
        choices=("breaking-news", "nhl-news", "injury-report", "prospect-wire", "all"),
        required=True,
    )
    args = parser.parse_args()

    selected = list(WEBHOOKS) if args.channel == "all" else [args.channel]
    print("BLHA THE WIRE — CONTROLLED WEBHOOK TEST")
    print("This test does not modify feed state and does not test nhl-transactions.\n")

    ok = True
    for channel in selected:
        ok = send(channel) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
