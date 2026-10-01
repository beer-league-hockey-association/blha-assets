#!/usr/bin/env python3
"""Build the unified BLHA Phase 2C.6 Discohook hosting package.

The generated files intentionally keep the existing raw.githubusercontent.com
paths stable so current Discohook JSON templates do not need URL changes.

Phase 2C.6 v2 is optimized for Discord embed rendering:
- compact 1600x300 headers instead of 1600x420
- no clipped right-side faceoff circle
- white BLHA lettering with black/gold keylines and no white logo card
- fuller rink-line footer treatment based on the approved divider preview
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WEBHOOKS = ROOT / "discord" / "webhooks"

BG = (43, 45, 49)
GOLD = (255, 184, 28)
CREAM = (244, 239, 228)
MUTED = (184, 185, 190)
BLACK = (12, 13, 15)
WHITE = (255, 255, 255)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def fit_font(text: str, font_path: str, max_size: int, max_width: int, min_size: int = 20):
    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(font_path, size)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
    return ImageFont.truetype(font_path, min_size)


def add_texture(image: Image.Image, seed: int, strength: int = 7, density: float = 0.004):
    rnd = random.Random(seed)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    count = int(width * height * density / 16)
    for _ in range(count):
        x = rnd.randrange(width)
        y = rnd.randrange(height)
        alpha = rnd.randrange(3, strength + 4)
        color = 255 if rnd.random() > 0.5 else 0
        radius = 1 if rnd.random() < 0.9 else 2
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(color, color, color, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def draw_wordmark(draw: ImageDraw.ImageDraw, center_x: int, top_y: int, max_width: int = 300):
    text = "BLHA"
    font = fit_font(text, FONT_BOLD, 70, max_width, 44)
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    x = center_x - width // 2

    # Gold outer edge + black keyline + white letters. No white background card.
    draw.text((x, top_y), text, font=font, fill=BLACK, stroke_width=7, stroke_fill=GOLD)
    draw.text((x, top_y), text, font=font, fill=WHITE, stroke_width=3, stroke_fill=BLACK)

    sub = "BEER LEAGUE HOCKEY ASSOCIATION"
    sub_font = fit_font(sub, FONT_BOLD, 12, max_width, 9)
    sub_box = draw.textbbox((0, 0), sub, font=sub_font)
    draw.text((center_x - (sub_box[2]-sub_box[0])//2, top_y + 76), sub, font=sub_font, fill=CREAM)

    est = "—  EST. 2026  —"
    est_font = ImageFont.truetype(FONT_MONO, 10)
    est_box = draw.textbbox((0, 0), est, font=est_font)
    draw.text((center_x - (est_box[2]-est_box[0])//2, top_y + 96), est, font=est_font, fill=GOLD)


def make_header(title: str, kicker: str) -> Image.Image:
    # Tighter canvas fixes the large dead area visible in Discord/Discohook.
    width, height = 1600, 300
    image = Image.new("RGBA", (width, height), BG + (255,))
    image = add_texture(image, seed=2026 + len(title))
    draw = ImageDraw.Draw(image)

    draw.rectangle((72, 48, 84, 248), fill=GOLD)

    kicker_font = fit_font(kicker, FONT_MONO, 24, 850, 18)
    draw.text((120, 54), kicker, font=kicker_font, fill=GOLD)

    title_font = fit_font(title, FONT_BOLD, 62, 1000, 38)
    draw.text((120, 100), title, font=title_font, fill=CREAM)

    subtitle = "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026"
    subtitle_font = ImageFont.truetype(FONT_REG, 25)
    draw.text((120, 188), subtitle, font=subtitle_font, fill=MUTED)

    # Full faceoff circle, deliberately inset from right and bottom edges.
    center_x, center_y, radius = 1414, 172, 105
    draw.ellipse((center_x-radius, center_y-radius, center_x+radius, center_y+radius), outline=GOLD, width=5)
    draw.line((center_x, center_y-radius+1, center_x, center_y+radius-1), fill=CREAM, width=3)
    draw.ellipse((center_x-11, center_y-11, center_x+11, center_y+11), fill=GOLD)

    draw_wordmark(draw, center_x, 20, max_width=275)
    draw.rectangle((0, height-8, width, height), fill=GOLD)
    return image.convert("RGB")


def make_footer() -> Image.Image:
    """Approved fuller divider treatment, sized for Discord embed readability.

    The legacy filename remains blha-footer-divider-1600x90.png so every existing
    Discohook URL stays valid; the rendered image itself is now 1600x120.
    """
    width, height = 1600, 120
    image = Image.new("RGBA", (width, height), BG + (255,))
    image = add_texture(image, seed=4242, strength=6, density=0.003)
    draw = ImageDraw.Draw(image)

    cx, cy = width // 2, height // 2
    ring_r = 36
    break_gap = 56
    left = 62
    right = width - 62

    # Three strong rink lines: cream / gold / cream.
    lines = ((35, CREAM, 9), (60, GOLD, 11), (85, CREAM, 9))
    for y, color, thickness in lines:
        draw.rectangle((left, y-thickness//2, cx-ring_r-break_gap, y+thickness//2), fill=color)
        draw.rectangle((cx+ring_r+break_gap, y-thickness//2, right, y+thickness//2), fill=color)

    # Angled cream shoulders around the center circle mirror the preferred source.
    shoulder = 12
    draw.line(
        [(cx-ring_r-break_gap, 31), (cx-ring_r-22, 31), (cx-ring_r-10, cy-shoulder)],
        fill=CREAM, width=9, joint="curve"
    )
    draw.line(
        [(cx+ring_r+break_gap, 31), (cx+ring_r+22, 31), (cx+ring_r+10, cy-shoulder)],
        fill=CREAM, width=9, joint="curve"
    )
    draw.line(
        [(cx-ring_r-break_gap, 81), (cx-ring_r-22, 81), (cx-ring_r-10, cy+shoulder)],
        fill=CREAM, width=9, joint="curve"
    )
    draw.line(
        [(cx+ring_r+break_gap, 81), (cx+ring_r+22, 81), (cx+ring_r+10, cy+shoulder)],
        fill=CREAM, width=9, joint="curve"
    )

    # Gold center line feeds cleanly into the full gold ring.
    draw.rectangle((cx-ring_r-break_gap, 55, cx-ring_r+2, 65), fill=GOLD)
    draw.rectangle((cx+ring_r-2, 55, cx+ring_r+break_gap, 65), fill=GOLD)
    draw.ellipse((cx-ring_r, cy-ring_r, cx+ring_r, cy+ring_r), outline=GOLD, width=8)

    return image.convert("RGB")


def save_image(path: Path, image: Image.Image):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def build_preview(entries: list[tuple[Path, str]], footer_path: Path):
    thumb_w, thumb_h = 640, 120
    row_h = thumb_h + 52
    sheet = Image.new("RGB", (1320, row_h * 4 + 210), (26, 27, 30))
    draw = ImageDraw.Draw(sheet)
    title_font = ImageFont.truetype(FONT_BOLD, 34)
    label_font = ImageFont.truetype(FONT_REG, 18)
    draw.text((30, 24), "BLHA PHASE 2C.6 v2 — DISCOHOOK HOSTING PACKAGE", font=title_font, fill=CREAM)

    for i, (path, title) in enumerate(entries):
        row, col = divmod(i, 2)
        x = 30 + col * 650
        y = 82 + row * row_h
        image = Image.open(path).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb_h + 7), title, font=label_font, fill=MUTED)

    footer_y = 82 + 4 * row_h
    draw.text((30, footer_y), "SHARED FOOTER DIVIDER", font=label_font, fill=MUTED)
    footer = Image.open(footer_path).resize((1260, 95), Image.Resampling.LANCZOS)
    sheet.paste(footer, (30, footer_y + 28))
    save_image(WEBHOOKS / "BLHA_Phase_2C6_Hosting_Preview.png", sheet)


def main():
    # Generic filename intentionally remains 1600x420 for URL compatibility;
    # all generated headers are now physically 1600x300.
    specs = [
        (WEBHOOKS / "welcome" / "blha-welcome-banner.png", "WELCOME TO THE BLHA", "WELCOME TO THE ROOM"),
        (WEBHOOKS / "league-office" / "blha-constitution-header.png", "LEAGUE CONSTITUTION", "OFFICIAL BLHA RULEBOOK"),
        (WEBHOOKS / "league-office" / "blha-announcements-header.png", "LEAGUE ANNOUNCEMENTS", "OFFICIAL BLHA NOTICE"),
        (WEBHOOKS / "league-office" / "blha-calendar-header.png", "LEAGUE CALENDAR", "OFFICIAL BLHA CALENDAR"),
        (WEBHOOKS / "league-office" / "blha-ledger-header.png", "LEAGUE LEDGER", "OFFICIAL BLHA LEDGER"),
        (WEBHOOKS / "league-office" / "blha-voting-header.png", "LEAGUE VOTING", "OFFICIAL BLHA VOTE"),
        (WEBHOOKS / "draft-center" / "blha-draft-center-header.png", "DRAFT CENTER", "OFFICIAL BLHA DRAFT"),
        (WEBHOOKS / "shared" / "blha-generic-header-1600x420.png", "BEER LEAGUE HOCKEY ASSOCIATION", "OFFICIAL BLHA"),
    ]

    preview_entries = []
    for path, title, kicker in specs:
        save_image(path, make_header(title, kicker))
        if "generic" not in path.name:
            preview_entries.append((path, title))

    footer_path = WEBHOOKS / "shared" / "blha-footer-divider-1600x90.png"
    save_image(footer_path, make_footer())

    wordmark = Image.new("RGBA", (640, 170), (0, 0, 0, 0))
    draw_wordmark(ImageDraw.Draw(wordmark), 320, 12, max_width=430)
    wordmark_path = WEBHOOKS / "shared" / "blha-banner-wordmark.png"
    wordmark_path.parent.mkdir(parents=True, exist_ok=True)
    wordmark.save(wordmark_path, "PNG", optimize=True)

    build_preview(preview_entries, footer_path)

    base = "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/discord/webhooks/"
    url_map = f"""BLHA RAW ASSET URLS

Base:
{base}

Welcome banner:
{base}welcome/blha-welcome-banner.png

Footer divider:
{base}shared/blha-footer-divider-1600x90.png

Generic header:
{base}shared/blha-generic-header-1600x420.png

Banner wordmark:
{base}shared/blha-banner-wordmark.png

Hosting preview:
{base}BLHA_Phase_2C6_Hosting_Preview.png

Constitution:
{base}league-office/blha-constitution-header.png

Announcements:
{base}league-office/blha-announcements-header.png

Calendar:
{base}league-office/blha-calendar-header.png

Ledger:
{base}league-office/blha-ledger-header.png

Voting:
{base}league-office/blha-voting-header.png

Draft Center:
{base}draft-center/blha-draft-center-header.png
"""
    (ROOT / "BLHA_URL_MAP.txt").write_text(url_map, encoding="utf-8")

    manifest = {
        "phase": "2C.6-v2",
        "header_dimensions": "1600x300",
        "footer_dimensions": "1600x120 (legacy filename retained for stable URLs)",
        "palette": {"charcoal": "#2B2D31", "gold": "#FFB81C", "cream": "#F4EFE4"},
        "design": {
            "discord_optimized": True,
            "right_circle": "fully inset; never clipped",
            "wordmark": "white BLHA lettering with black keyline and gold outer edge; no white card",
            "footer": "fuller cream/gold/cream rink-line divider with centered gold ring",
        },
        "stable_urls": {
            "welcome": base + "welcome/blha-welcome-banner.png",
            "constitution": base + "league-office/blha-constitution-header.png",
            "announcements": base + "league-office/blha-announcements-header.png",
            "calendar": base + "league-office/blha-calendar-header.png",
            "ledger": base + "league-office/blha-ledger-header.png",
            "voting": base + "league-office/blha-voting-header.png",
            "draft_center": base + "draft-center/blha-draft-center-header.png",
            "generic_header": base + "shared/blha-generic-header-1600x420.png",
            "footer": base + "shared/blha-footer-divider-1600x90.png",
        },
    }
    (WEBHOOKS / "BLHA_Phase_2C6_Hosting_Manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    readme = """# BLHA Phase 2C.6 v2 — Discohook Asset Hosting

This directory is the canonical public hosting package for BLHA Discohook images.

## Visual standard
- Header canvas: **1600×300**
- Footer divider: **1600×120** (legacy 1600x90 filename retained so URLs do not break)
- Charcoal: **#2B2D31**
- Gold: **#FFB81C**
- Cream: **#F4EFE4**
- Compact header composition removes unnecessary vertical space in Discord.
- Right-side faceoff circle is fully inset so it cannot clip.
- BLHA banner lettering is white with black/gold keylines and no white logo card.
- Welcome, League Office, and Draft Center headers share one layout system.

## Hosting behavior
Existing template URLs remain stable. Rebuilding these files changes the art without requiring Discohook image URL edits.

Header-only Discohook embeds should contain only the image object; do not add a blank Unicode description/spacer.

See `BLHA_URL_MAP.txt` at repository root for copy/paste URLs.
"""
    (WEBHOOKS / "README.md").write_text(readme, encoding="utf-8")

    print("BLHA Phase 2C.6 v2 Discohook hosting package generated.")


if __name__ == "__main__":
    main()
