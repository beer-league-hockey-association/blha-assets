#!/usr/bin/env python3
"""Normalize BLHA Discohook JSON templates to the frozen Phase 2C.6 format.

Rules:
- Every Discohook message ends with the shared footer-divider image.
- Channel-intro messages begin with a valid banner embed using the charcoal
  #2B2D31 side color and an invisible footer marker so Discohook does not flag
  the image-only banner as empty.
- Existing message text, fields, semantic colors, and footers are preserved.
- The shared footer image is attached to the final content embed. If that embed
  already uses a different image, a dedicated valid footer embed is appended.
- The frozen footer URL carries a version query so Discord cannot keep serving
  an older cached opaque divider after the asset itself is replaced.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

BASE = "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/discord/webhooks/"
FOOTER_BASE_URL = BASE + "shared/blha-footer-divider-1600x90.png"
FOOTER_URL = FOOTER_BASE_URL + "?v=2c6-frozen"
HEADER_VERSION = "?v=3-b-logo"
HEADER_COLOR = int("2B2D31", 16)
ZWSP = "\u200b"

INTRO_HEADERS = {
    "welcome/01_welcome.json": BASE + "welcome/blha-welcome-banner.png" + HEADER_VERSION,
    "league-office/01_constitution_channel_intro.json": BASE + "league-office/blha-constitution-header.png" + HEADER_VERSION,
    "league-office/02_announcements_channel_intro.json": BASE + "league-office/blha-announcements-header.png" + HEADER_VERSION,
    "league-office/03_calendar_channel_intro.json": BASE + "league-office/blha-calendar-header.png" + HEADER_VERSION,
    "league-office/04_ledger_channel_intro.json": BASE + "league-office/blha-ledger-header.png" + HEADER_VERSION,
    "league-office/05_voting_channel_intro.json": BASE + "league-office/blha-voting-header.png" + HEADER_VERSION,
    "draft-center/06_draft_center_intro.json": BASE + "draft-center/blha-draft-center-header.png" + HEADER_VERSION,
}


def banner_embed(url: str) -> dict:
    return {
        "color": HEADER_COLOR,
        "footer": {"text": ZWSP},
        "image": {"url": url},
    }


def is_banner_like(embed: dict) -> bool:
    if not isinstance(embed, dict):
        return False
    image = embed.get("image")
    if not isinstance(image, dict):
        return False
    url = str(image.get("url") or "")
    return any(
        token in url
        for token in (
            "blha-welcome-banner.png",
            "blha-constitution-header.png",
            "blha-announcements-header.png",
            "blha-calendar-header.png",
            "blha-ledger-header.png",
            "blha-voting-header.png",
            "blha-draft-center-header.png",
        )
    )


def is_footer_url(value: str) -> bool:
    return str(value or "").startswith(FOOTER_BASE_URL)


def ensure_footer(embeds: list[dict]) -> None:
    if not embeds:
        embeds.append({"color": HEADER_COLOR, "footer": {"text": ZWSP}, "image": {"url": FOOTER_URL}})
        return

    target = embeds[-1]
    image = target.get("image") if isinstance(target, dict) else None
    current_url = str(image.get("url") or "") if isinstance(image, dict) else ""

    if not current_url or is_footer_url(current_url):
        target["image"] = {"url": FOOTER_URL}
        return

    embeds.append(
        {
            "color": HEADER_COLOR,
            "footer": {"text": ZWSP},
            "image": {"url": FOOTER_URL},
        }
    )


def normalize_file(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")

    embeds = data.get("embeds")
    if not isinstance(embeds, list):
        raise ValueError(f"{path}: embeds must be a list")

    rel = path.relative_to(TEMPLATES).as_posix()
    header_url = INTRO_HEADERS.get(rel)
    if header_url:
        new_header = banner_embed(header_url)
        if embeds and is_banner_like(embeds[0]):
            embeds[0] = new_header
        else:
            embeds.insert(0, new_header)

    ensure_footer(embeds)

    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    old = path.read_text(encoding="utf-8")
    if rendered == old:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def verify_file(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    embeds = data.get("embeds")
    if not isinstance(embeds, list) or not embeds:
        raise AssertionError(f"{path}: no embeds")

    rel = path.relative_to(TEMPLATES).as_posix()
    if rel in INTRO_HEADERS:
        first = embeds[0]
        if first.get("color") != HEADER_COLOR:
            raise AssertionError(f"{path}: banner color is not #2B2D31")
        if first.get("footer", {}).get("text") != ZWSP:
            raise AssertionError(f"{path}: banner validity marker missing")
        if first.get("image", {}).get("url") != INTRO_HEADERS[rel]:
            raise AssertionError(f"{path}: wrong banner URL")

    footer_found = any(
        isinstance(embed, dict)
        and isinstance(embed.get("image"), dict)
        and embed["image"].get("url") == FOOTER_URL
        for embed in embeds
    )
    if not footer_found:
        raise AssertionError(f"{path}: frozen footer divider missing")


def main() -> None:
    paths = sorted(TEMPLATES.rglob("*.json"))
    changed = 0
    for path in paths:
        changed += int(normalize_file(path))
    for path in paths:
        verify_file(path)

    print(f"DISCOHOOK FORMAT: verified {len(paths)} JSON templates; changed {changed}.")
    print("DISCOHOOK FORMAT: Phase 2C.6 frozen standard applied.")


if __name__ == "__main__":
    main()
