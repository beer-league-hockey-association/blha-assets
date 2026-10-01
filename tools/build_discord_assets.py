#!/usr/bin/env python3
"""Build the unified BLHA Phase 2C.6 Discohook hosting package.

The generated files intentionally keep the existing raw.githubusercontent.com
paths stable so current Discohook JSON templates do not need URL changes.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WEBHOOKS = ROOT / "discord" / "webhooks"

BG = (43, 45, 49)
BG_DARK = (36, 38, 42)
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


def add_texture(image: Image.Image, seed: int, strength: int = 8, density: float = 0.006):
    rnd = random.Random(seed)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    count = int(width * height * density / 16)
    for _ in range(count):
        x = rnd.randrange(width)
        y = rnd.randrange(height)
        alpha = rnd.randrange(4, strength + 5)
        color = 255 if rnd.random() > 0.5 else 0
        radius = 1 if rnd.random() < 0.9 else 2
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(color, color, color, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def draw_wordmark(draw: ImageDraw.ImageDraw, center_x: int, top_y: int, max_width: int = 315):
    text = "BLHA"
    font = fit_font(text, FONT_BOLD, 76, max_width, 48)
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    x = center_x - width // 2

    # Gold outer edge, black keyline, white fill. No white logo card/background.
    draw.text((x, top_y), text, font=font, fill=BLACK, stroke_width=7, stroke_fill=GOLD)
    draw.text((x, top_y), text, font=font, fill=WHITE, stroke_width=3, stroke_fill=BLACK)

    sub = "BEER LEAGUE HOCKEY ASSOCIATION"
    sub_font = fit_font(sub, FONT_BOLD, 13, max_width, 9)
    sub_box = draw.textbbox((0, 0), sub, font=sub_font)
    draw.text((center_x - (sub_box[2]-sub_box[0])//2, top_y + 82), sub, font=sub_font, fill=CREAM)

    est = "—  EST. 2026  —"
    est_font = ImageFont.truetype(FONT_MONO, 11)
    est_box = draw.textbbox((0, 0), est, font=est_font)
    draw.text((center_x - (est_box[2]-est_box[0])//2, top_y + 103), est, font=est_font, fill=GOLD)


def make_header(title: str, kicker: str) -> Image.Image:
    width, height = 1600, 420
    image = Image.new("RGBA", (width, height), BG + (255,))

    # Subtle right-side darkening for depth while retaining the BLHA charcoal base.
    gradient = Image.new("L", (width, 1))
    for x in range(width):
        gradient.putpixel((x, 0), int(max(0, min(255, 255 - 45 * (x / width)))))
    gradient = gradient.resize((width, height))
    image = Image.composite(image, Image.new("RGBA", (width, height), BG_DARK + (80,)), gradient)
    image = add_texture(image, seed=2026 + len(title))
    draw = ImageDraw.Draw(image)

    draw.rectangle((72, 86, 84, 336), fill=GOLD)

    kicker_font = fit_font(kicker, FONT_MONO, 26, 850, 18)
    draw.text((120, 96), kicker, font=kicker_font, fill=GOLD)

    title_font = fit_font(title, FONT_BOLD, 64, 1010, 40)
    draw.text((120, 151), title, font=title_font, fill=CREAM)

    subtitle = "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026"
    subtitle_font = ImageFont.truetype(FONT_REG, 27)
    draw.text((120, 244), subtitle, font=subtitle_font, fill=MUTED)

    # Fully inset hockey faceoff circle; no right-edge clipping.
    center_x, center_y, radius = 1418, 233, 146
    draw.ellipse((center_x-radius, center_y-radius, center_x+radius, center_y+radius), outline=GOLD, width=5)
    draw.line((center_x, center_y-radius+1, center_x, center_y+radius-1), fill=CREAM, width=3)
    draw.ellipse((center_x-12, center_y-12, center_x+12, center_y+12), fill=GOLD)

    draw_wordmark(draw, center_x, 39)
    draw.rectangle((0, height-10, width, height), fill=GOLD)
    return image.convert("RGB")


def make_footer() -> Image.Image:
    width, height = 1600, 90
    image = Image.new("RGBA", (width, height), BG + (255,))
    image = add_texture(image, seed=4242, strength=7, density=0.004)
    draw = ImageDraw.Draw(image)
    center_x, center_y = width // 2, height // 2
    radius, gap = 28, 42

    for y, color, thickness in ((24, CREAM, 8), (43, GOLD, 10), (66, CREAM, 8)):
        draw.rectangle((50, y-thickness//2, center_x-radius-gap, y+thickness//2), fill=color)
        draw.rectangle((center_x+radius+gap, y-thickness//2, width-50, y+thickness//2), fill=color)

    for y, color in ((24, CREAM), (66, CREAM)):
        target_y = center_y - 12 if y < center_y else center_y + 12
        draw.line([(center_x-radius-gap, y-4), (center_x-radius-18, y-4), (center_x-radius-9, target_y)], fill=color, width=8, joint="curve")
        draw.line([(center_x+radius+gap, y-4), (center_x+radius+18, y-4), (center_x+radius+9, target_y)], fill=color, width=8, joint="curve")

    draw.rectangle((center_x-radius-gap, 38, center_x-radius+2, 48), fill=GOLD)
    draw.rectangle((center_x+radius-2, 38, center_x+radius+gap, 48), fill=GOLD)
    draw.ellipse((center_x-radius, center_y-radius, center_x+radius, center_y+radius), outline=GOLD, width=7)
    return image.convert("RGB")


def save_image(path: Path, image: Image.Image):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def build_preview(entries: list[tuple[Path, str]], footer_path: Path):
    thumb_w, thumb_h = 640, 168
    sheet = Image.new("RGB", (1320, (thumb_h + 56) * 4 + 140), (26, 27, 30))
    draw = ImageDraw.Draw(sheet)
    title_font = ImageFont.truetype(FONT_BOLD, 36)
    label_font = ImageFont.truetype(FONT_REG, 18)
    draw.text((30, 24), "BLHA PHASE 2C.6 — UNIFIED DISCOHOOK HOSTING PACKAGE", font=title_font, fill=CREAM)

    for i, (path, title) in enumerate(entries):
        row, col = divmod(i, 2)
        x = 30 + col * 650
        y = 90 + row * (thumb_h + 56)
        image = Image.open(path).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(image, (x, y))
        draw.text((x, y + thumb_h + 8), title, font=label_font, fill=MUTED)

    footer_y = 90 + 4 * (thumb_h + 56)
    draw.text((30, footer_y), "SHARED FOOTER DIVIDER", font=label_font, fill=MUTED)
    footer = Image.open(footer_path).resize((1260, 71), Image.Resampling.LANCZOS)
    sheet.paste(footer, (30, footer_y + 28))
    save_image(WEBHOOKS / "BLHA_Phase_2C6_Hosting_Preview.png", sheet)


def main():
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

    wordmark = Image.new("RGBA", (640, 180), (0, 0, 0, 0))
    draw_wordmark(ImageDraw.Draw(wordmark), 320, 15, max_width=430)
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
        "phase": "2C.6",
        "header_dimensions": "1600x420",
        "footer_dimensions": "1600x90",
        "palette": {"charcoal": "#2B2D31", "gold": "#FFB81C", "cream": "#F4EFE4"},
        "design": {
            "right_circle": "fully inset; never clipped",
            "wordmark": "white BLHA lettering with black keyline and gold outer edge; no white card",
            "footer": "cream/gold/cream rink-line divider with centered gold ring",
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

    readme = f"""# BLHA Phase 2C.6 — Discohook Asset Hosting

This directory is the canonical public hosting package for BLHA Discohook images.

## Visual standard
- Header canvas: **1600×420**
- Footer divider: **1600×90**
- Charcoal: **#2B2D31**
- Gold: **#FFB81C**
- Cream: **#F4EFE4**
- Right-side faceoff circle is fully inset so it cannot clip at Discord's image boundary.
- BLHA banner lettering is white with a black keyline and gold outer edge. There is no white logo card.
- All Welcome, League Office, and Draft Center channel headers use the same grid, typography hierarchy, rink-circle treatment, and footer divider.

## Hosting behavior
Existing template URLs remain stable. Rebuilding these files changes the art without requiring Discohook JSON URL edits.

See `BLHA_URL_MAP.txt` at repository root for copy/paste URLs.
"""
    (WEBHOOKS / "README.md").write_text(readme, encoding="utf-8")

    print("BLHA Phase 2C.6 Discohook hosting package generated.")


if __name__ == "__main__":
    main()
