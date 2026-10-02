#!/usr/bin/env python3
"""Build frozen BLHA Phase 2C.6 Discohook assets.

Raw GitHub paths intentionally stay stable so existing Discohook JSON files do
not need URL changes when the artwork is regenerated.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WEBHOOKS = ROOT / "discord" / "webhooks"

BG = (43, 45, 49)          # #2B2D31
GOLD = (255, 184, 28)      # #FFB81C
CREAM = (244, 239, 228)    # #F4EFE4
MUTED = (184, 185, 190)
BLACK = (12, 13, 15)
WHITE = (255, 255, 255)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def fit_font(text: str, path: str, max_size: int, max_width: int, min_size: int = 20):
    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(path, size)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
    return ImageFont.truetype(path, min_size)


def add_texture(image: Image.Image, seed: int, density: float = 0.0035):
    rnd = random.Random(seed)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    count = int(width * height * density / 16)
    for _ in range(count):
        x = rnd.randrange(width)
        y = rnd.randrange(height)
        alpha = rnd.randrange(3, 10)
        shade = 255 if rnd.random() > 0.5 else 0
        draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(shade, shade, shade, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def draw_wordmark(draw: ImageDraw.ImageDraw, center_x: int, top_y: int, max_width: int = 275):
    text = "BLHA"
    font = fit_font(text, FONT_BOLD, 70, max_width, 44)
    box = draw.textbbox((0, 0), text, font=font)
    x = center_x - (box[2] - box[0]) // 2

    draw.text((x, top_y), text, font=font, fill=BLACK, stroke_width=7, stroke_fill=GOLD)
    draw.text((x, top_y), text, font=font, fill=WHITE, stroke_width=3, stroke_fill=BLACK)

    sub = "BEER LEAGUE HOCKEY ASSOCIATION"
    sub_font = fit_font(sub, FONT_BOLD, 12, max_width, 9)
    sub_box = draw.textbbox((0, 0), sub, font=sub_font)
    draw.text((center_x - (sub_box[2] - sub_box[0]) // 2, top_y + 76), sub, font=sub_font, fill=CREAM)

    est = "—  EST. 2026  —"
    est_font = ImageFont.truetype(FONT_MONO, 10)
    est_box = draw.textbbox((0, 0), est, font=est_font)
    draw.text((center_x - (est_box[2] - est_box[0]) // 2, top_y + 96), est, font=est_font, fill=GOLD)


B_MARK = ROOT / "brand" / "primary" / "blha-b-mark.png"


def b_mark(height: int) -> Image.Image:
    """The B cut from the official BLHA wordmark (white fill, black/gold keylines)."""
    mark = Image.open(B_MARK).convert("RGBA")
    return mark.resize((round(mark.width * height / mark.height), height), Image.LANCZOS)


def b_icon(size: int) -> Image.Image:
    """Square icon: the B centered on near-black."""
    icon = Image.new("RGBA", (size, size), BLACK + (255,))
    mark = b_mark(round(size * 0.66))
    icon.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return icon


def make_header(title: str, kicker: str) -> Image.Image:
    """3:1 header, 1600x533, large type and the B logo on the right."""
    width, height = 1600, 533
    image = Image.new("RGBA", (width, height), BG + (255,))
    image = add_texture(image, seed=2026 + len(title))
    draw = ImageDraw.Draw(image)

    draw.rectangle((72, 80, 90, 453), fill=GOLD)
    draw.text((130, 90), kicker, font=fit_font(kicker, FONT_MONO, 40, 900, 24), fill=GOLD)
    draw.text((130, 160), title, font=fit_font(title, FONT_BOLD, 128, 930, 56), fill=CREAM)
    draw.text(
        (130, 360),
        "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026",
        font=fit_font("BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026", FONT_REG, 40, 930, 24),
        fill=MUTED,
    )

    mark = b_mark(380)
    image.alpha_composite(mark, (width - 110 - mark.width, (height - 12 - mark.height) // 2))

    draw.rectangle((0, height - 12, width, height), fill=GOLD)
    return image.convert("RGB")


def make_footer() -> Image.Image:
    """Transparent rink divider for seamless Discord embed rendering."""
    width, height = 1600, 180
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    cx, cy = width // 2, height // 2
    ring_r = 42
    break_outer = 70
    left, right = 62, width - 62

    for y, color, thick in ((66, CREAM, 10), (90, GOLD, 12), (114, CREAM, 10)):
        rgba = color + (255,)
        draw.rectangle((left, y - thick // 2, cx - ring_r - break_outer, y + thick // 2), fill=rgba)
        draw.rectangle((cx + ring_r + break_outer, y - thick // 2, right, y + thick // 2), fill=rgba)

    shoulder = 14
    for side in (-1, 1):
        x1 = cx + side * (ring_r + break_outer)
        x2 = cx + side * (ring_r + 23)
        x3 = cx + side * (ring_r + 9)
        draw.line([(x1, 66), (x2, 66), (x3, cy - shoulder)], fill=CREAM + (255,), width=10, joint="curve")
        draw.line([(x1, 114), (x2, 114), (x3, cy + shoulder)], fill=CREAM + (255,), width=10, joint="curve")

    draw.rectangle((cx - ring_r - break_outer, cy - 6, cx - ring_r + 3, cy + 6), fill=GOLD + (255,))
    draw.rectangle((cx + ring_r - 3, cy - 6, cx + ring_r + break_outer, cy + 6), fill=GOLD + (255,))
    draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), outline=GOLD + (255,), width=9)
    return image


def save_png(path: Path, image: Image.Image):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def build_preview(entries: list[tuple[Path, str]], footer_path: Path):
    sheet = Image.new("RGBA", (1320, 1260), (26, 27, 30, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (30, 24),
        "BLHA PHASE 2C.6 — FROZEN DISCOHOOK STANDARD",
        font=ImageFont.truetype(FONT_BOLD, 34),
        fill=CREAM,
    )
    label_font = ImageFont.truetype(FONT_REG, 18)

    for i, (path, title) in enumerate(entries):
        row, col = divmod(i, 2)
        x = 30 + col * 650
        y = 82 + row * 250
        thumb = Image.open(path).convert("RGBA").resize((640, 213), Image.Resampling.LANCZOS)
        sheet.alpha_composite(thumb, (x, y))
        draw.text((x, y + 218), title, font=label_font, fill=MUTED)

    footer_y = 1080
    draw.text((30, footer_y), "SHARED TRANSPARENT FOOTER DIVIDER", font=label_font, fill=MUTED)
    footer = Image.open(footer_path).convert("RGBA").resize((1260, 142), Image.Resampling.LANCZOS)
    sheet.alpha_composite(footer, (30, footer_y + 28))
    save_png(WEBHOOKS / "BLHA_Phase_2C6_Hosting_Preview.png", sheet.convert("RGB"))


def main():
    specs = [
        (WEBHOOKS / "welcome" / "blha-welcome-banner.png", "WELCOME TO THE BLHA", "WELCOME TO THE ROOM"),
        (WEBHOOKS / "league-office" / "blha-constitution-header.png", "LEAGUE CONSTITUTION", "OFFICIAL BLHA RULEBOOK"),
        (WEBHOOKS / "league-office" / "blha-announcements-header.png", "LEAGUE ANNOUNCEMENTS", "OFFICIAL BLHA NOTICE"),
        (WEBHOOKS / "league-office" / "blha-calendar-header.png", "LEAGUE CALENDAR", "OFFICIAL BLHA CALENDAR"),
        (WEBHOOKS / "league-office" / "blha-ledger-header.png", "LEAGUE LEDGER", "OFFICIAL BLHA LEDGER"),
        (WEBHOOKS / "league-office" / "blha-voting-header.png", "LEAGUE VOTING", "OFFICIAL BLHA VOTE"),
        (WEBHOOKS / "draft-center" / "blha-draft-center-header.png", "DRAFT CENTER", "OFFICIAL BLHA DRAFT"),
        (WEBHOOKS / "the-wire" / "blha-the-wire-header.png", "THE WIRE", "BLHA NEWS DESK"),
        (WEBHOOKS / "league-competition" / "blha-competition-header.png", "LEAGUE COMPETITION", "STANDINGS & PLAYOFFS"),
        (WEBHOOKS / "general-managers" / "blha-general-managers-header.png", "GENERAL MANAGERS", "THE CLUBHOUSE"),
        (WEBHOOKS / "trade-center" / "blha-trade-center-header.png", "TRADE CENTER", "OFFICIAL BLHA TRADES"),
        (WEBHOOKS / "scouting" / "blha-scouting-header.png", "SCOUTING DEPARTMENT", "PROSPECTS & PICKS"),
        (WEBHOOKS / "waiver-wire" / "blha-waiver-wire-header.png", "WAIVER WIRE", "FAAB & CLAIMS"),
        (WEBHOOKS / "commissioners-office" / "blha-commissioners-office-header.png", "COMMISSIONER'S OFFICE", "OFFICIAL BLHA RULINGS"),
        (WEBHOOKS / "franchise-hq" / "blha-franchise-hq-header.png", "FRANCHISE HQ", "YOUR CLUB, YOUR CALLS"),
        (WEBHOOKS / "league-office" / "blha-champions-header.png", "BLHA CHAMPIONS", "PERMANENT LEAGUE HISTORY"),
        (WEBHOOKS / "league-office" / "blha-records-header.png", "LEAGUE RECORDS", "THE PERMANENT RECORD"),
        (WEBHOOKS / "shared" / "blha-generic-header-1600x420.png", "BEER LEAGUE HOCKEY ASSOCIATION", "OFFICIAL BLHA"),
    ]

    preview_entries = []
    for path, title, kicker in specs:
        save_png(path, make_header(title, kicker))
        if "generic" not in path.name:
            preview_entries.append((path, title))

    footer_path = WEBHOOKS / "shared" / "blha-footer-divider-1600x90.png"
    save_png(footer_path, make_footer())

    save_png(WEBHOOKS / "avatar" / "blha-webhook-avatar-512.png", b_icon(512).convert("RGB"))
    save_png(ROOT / "discord" / "server" / "blha-server-icon-1024.png", b_icon(1024).convert("RGB"))
    wordmark = Image.new("RGBA", (640, 170), (0, 0, 0, 0))
    draw_wordmark(ImageDraw.Draw(wordmark), 320, 12, max_width=430)
    save_png(WEBHOOKS / "shared" / "blha-banner-wordmark.png", wordmark)

    build_preview(preview_entries, footer_path)

    base = "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/discord/webhooks/"
    (ROOT / "BLHA_URL_MAP.txt").write_text(
        f"""BLHA RAW ASSET URLS\n\nWelcome banner:\n{base}welcome/blha-welcome-banner.png\n\nFooter divider:\n{base}shared/blha-footer-divider-1600x90.png\n\nGeneric header:\n{base}shared/blha-generic-header-1600x420.png\n\nBanner wordmark:\n{base}shared/blha-banner-wordmark.png\n\nHosting preview:\n{base}BLHA_Phase_2C6_Hosting_Preview.png\n\nConstitution:\n{base}league-office/blha-constitution-header.png\n\nAnnouncements:\n{base}league-office/blha-announcements-header.png\n\nCalendar:\n{base}league-office/blha-calendar-header.png\n\nLedger:\n{base}league-office/blha-ledger-header.png\n\nVoting:\n{base}league-office/blha-voting-header.png\n\nDraft Center:\n{base}draft-center/blha-draft-center-header.png\n""",
        encoding="utf-8",
    )

    manifest = {
        "phase": "2C.6-frozen",
        "header_dimensions": "1600x533",
        "header_embed_color": "#2B2D31",
        "footer_dimensions": "1600x180 (legacy filename retained for stable URLs)",
        "footer_background": "transparent",
        "palette": {"charcoal": "#2B2D31", "gold": "#FFB81C", "cream": "#F4EFE4"},
        "design": {
            "status": "frozen",
            "right_circle": "fully inset; never clipped",
            "wordmark": "B from the official wordmark on headers; wordmark file kept for legacy use",
            "footer": "transparent cream/gold/cream rink divider with centered gold ring",
        },
    }
    (WEBHOOKS / "BLHA_Phase_2C6_Hosting_Manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (WEBHOOKS / "README.md").write_text(
        """# BLHA Phase 2C.6 — Frozen Discohook Standard\n\nCanonical hosted graphics for BLHA Discohook messages.\n\n- Headers: 1600x533\n- Header embed side color: #2B2D31\n- Footer: transparent 1600x180 PNG (legacy filename retained)\n- Gold: #FFB81C\n- Cream: #F4EFE4\n- Right side carries the B logo tile with a gold keyline (brand/primary/blha-b-mark.png).\n- Headers are 3:1 with large type; header URLs carry a ?v= cache-busting query.\n- All manual Discohook JSON templates are normalized by tools/normalize_discohook_templates.py.\n\nThis Phase 2C.6 visual format is frozen. Future content may change; the layout standard should not change without an explicit design revision.\n""",
        encoding="utf-8",
    )

    print("BLHA Phase 2C.6 frozen assets generated.")


if __name__ == "__main__":
    main()
