#!/usr/bin/env python3
"""Build the complete BLHA brand/graphics package in the 8-bit arcade style.

Usage: build_brand_package.py [OUT_DIR]   (default: brand/kit)

Writes the six kit folders, manifest.json, README.txt and the contact sheet,
plus the source marks in brand/primary, brand/secondary, brand/icon and
brand/source (with a custom OUT_DIR the marks go to OUT_DIR/marks/). Every
file is pixel art drawn by tools/blha_pixel.py; headers and the footer divider
come from tools/build_discord_assets.py so the kit matches what Discord hosts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blha_pixel as px  # noqa: E402
import build_discord_assets as bda  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

STAMPS = [  # (slug, word, color, sub line): green yes/paid, red no/owed/urgent, gold pending/history, cream official
    ("official", "OFFICIAL", px.CREAM, "BEER LEAGUE HOCKEY ASSOCIATION"),
    ("approved", "APPROVED", px.GREEN, None),
    ("denied", "DENIED", px.RED, None),
    ("pending", "PENDING", px.GOLD, None),
    ("final", "FINAL", px.CREAM, None),
    ("amended", "AMENDED", px.GOLD, None),
    ("vote-passed", "VOTE PASSED", px.GREEN, None),
    ("vote-failed", "VOTE FAILED", px.RED, None),
    ("commissioner-ruling", "COMMISSIONER RULING", px.CREAM, "BLHA LEAGUE OFFICE"),
    ("champions", "CHAMPIONS", px.GOLD, "BLHA PERMANENT RECORD"),
    ("paid-in-full", "PAID IN FULL", px.GREEN, "BLHA LEDGER"),
    ("dues-outstanding", "DUES OUTSTANDING", px.RED, "BLHA LEDGER"),
    ("urgent-deadline", "URGENT DEADLINE", px.RED, "ACTION REQUIRED"),
]

README = """BLHA BRAND & GRAPHICS PACKAGE (8-BIT ARCADE)
============================================
Every file is pixel art: drawn on a small grid and enlarged with hard edges.
Banners, headers, dividers and stamps use an 8 px grid (one pixel = 8 px).
Built by tools/build_brand_package.py (drawing code in tools/blha_pixel.py).

Palette: black #0E0F12, charcoal #2B2D31, gold #FFB81C, cream #F4EFE4,
ice #EEF5FA, paper #FCFCFC, blue #2457C5, red #C8241F.
Status green #3FA34D appears on stamps only. Team colors appear only on small
jersey or stripe elements, never on league marks.
Type: Jersey 10 (BLHA, titles) and Silkscreen (labels), in brand/fonts with OFL.txt.
Official marks: BLHA in Jersey 10 with gold then black keylines, and the pixel B
traced from the official mark (white, gold, black).

01_logos                 Wordmarks (transparent white / black, textured cream) and the B mark
02_avatars_icons         Server icon, webhook/bot avatar, profile pic, emoji, favicon
03_server_social_banners Discord server banner/splash, social preview, X header, event cover
04_channel_headers       1600x533 (3:1) headers for every channel category + welcome + generic
05_dividers              Footer divider (transparent), thin rule, gold bar
06_seals_stamps          Round official seal (dark/cream) and status stamps (transparent PNG)

Discord notes
- Embed images display at ~400px wide; headers are 3:1 so text stays readable.
- Discord caches by URL: when you replace a file, bump the ?v= version in
  tools/discohook_format.py and run tools/normalize_discohook_templates.py.
- Server banner needs a boosted server; recommended 960x540 or larger (16:9).
- Avatars use the small 14 x 14 pixel B so they stay sharp at Discord's 40-48 px.
- Stamps are transparent PNGs: use as embed thumbnail or image in rulings, votes and ledger posts.
"""


def build_kit(out: Path) -> dict[str, list[tuple[str, Image.Image]]]:
    made: dict[str, list[tuple[str, Image.Image]]] = {}

    def put(group: str, name: str, img: Image.Image, mode: str = "RGB"):
        px.save(out / group / name, img, mode)
        made.setdefault(group, []).append((name, img.convert(mode)))

    g = "01_logos"
    put(g, "blha-wordmark-white-transparent.png", px.wordmark_transparent((2000, 866), "white", 7), "RGBA")
    put(g, "blha-wordmark-black-transparent.png", px.wordmark_transparent((2000, 799), "black", 7), "RGBA")
    put(g, "blha-wordmark-textured-cream.png", px.wordmark_cream())
    put(g, "blha-wordmark-on-charcoal-1920x1080.png", px.wordmark_on((1920, 1080), px.CHARCOAL, "white", 6))
    put(g, "blha-wordmark-on-black-1920x1080.png", px.wordmark_on((1920, 1080), px.BLACK, "white", 6))
    put(g, "blha-wordmark-on-white-1920x1080.png", px.wordmark_on((1920, 1080), px.PAPER, "black", 6))
    put(g, "blha-b-mark-transparent-1024.png", px.b_mark((889, 1024), 31), "RGBA")
    for name, col in (("black", px.BLACK), ("charcoal", px.CHARCOAL), ("cream", px.CREAM), ("gold", px.GOLD)):
        put(g, f"blha-b-icon-{name}-1024.png", px.b_icon(1024, col))

    g = "02_avatars_icons"
    put(g, "blha-server-icon-1024.png", px.avatar(1024))
    put(g, "blha-webhook-avatar-512.png", px.avatar(512))
    put(g, "blha-bot-avatar-round-512.png", px.avatar(512, round_=True), "RGBA")
    put(g, "blha-profile-picture-400.png", px.avatar(400))
    for s in (128, 64):
        put(g, f"blha-emoji-b-{s}.png", px.emoji(s), "RGBA")
    put(g, "blha-favicon-256.png", px.emoji(256, px.BLACK))

    g = "03_server_social_banners"
    big = bda.server_banner()
    put(g, "blha-server-banner-960x540.png", big.resize((960, 540), Image.NEAREST))
    put(g, "blha-server-banner-1920x1080.png", big)
    put(g, "blha-invite-splash-1920x1080.png", px.splash())
    put(g, "blha-github-social-preview-1280x640.png", px.banner((1280, 640), 18, 3, dy=24))
    put(g, "blha-x-header-1500x500.png", px.banner((1500, 500), 12, 2, dy=20))
    put(g, "blha-bot-profile-banner-1360x480.png", px.banner((1360, 480), 12, 2, dy=20))
    put(g, "blha-event-cover-800x320.png", px.banner((800, 320), 10, 2, dy=16, sticks=True, sub_bold=False))

    g = "04_channel_headers"
    for _rel, slug, img in bda.all_headers():
        put(g, f"blha-{slug}-header-1600x533.png", img)

    g = "05_dividers"
    put(g, "blha-footer-divider-1600x180.png", bda.make_footer(), "RGBA")
    put(g, "blha-thin-rule-1600x40.png", px.thin_rule(), "RGBA")
    put(g, "blha-gold-bar-1600x24.png", px.gold_bar(), "RGBA")

    g = "06_seals_stamps"
    put(g, "blha-official-seal-dark-1024.png", px.seal(dark=True), "RGBA")
    put(g, "blha-official-seal-cream-1024.png", px.seal(dark=False), "RGBA")
    put(g, "blha-official-seal-256.png", px.seal(dark=True, k=1), "RGBA")
    for i, (slug, word, col, sub) in enumerate(STAMPS):
        put(g, f"blha-stamp-{slug}.png", px.stamp(word, col, sub, seed=11 + 7 * i), "RGBA")

    (out / "README.txt").write_text(README, encoding="utf-8")
    manifest = {k: [name for name, _img in v] for k, v in made.items()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    groups = [(k.upper(), v) for k, v in made.items()]
    px.save(out / "BLHA_Package_Contact_Sheet.png",
            px.contact_sheet("BLHA BRAND & GRAPHICS PACKAGE", groups, (1800, 5241)), "RGB")
    if out == ROOT / "brand" / "kit":  # the older root-level preview of the same package
        px.save(ROOT / "BLHA_Revised_Header_Preview.png",
                px.contact_sheet("BLHA BRAND & GRAPHICS PACKAGE", groups, (1800, 5033)), "RGB")
    return made


def build_marks(brand: Path) -> list[Path]:
    """The source marks other tools read (same names and sizes as before)."""
    marks = [
        (brand / "primary" / "blha-b-mark.png", px.b_mark((395, 455), 14), "RGBA"),
        (brand / "primary" / "blha-primary-logo.png", px.wordmark_cream(), "RGB"),
        (brand / "secondary" / "blha-league-stamp.png", px.seal(dark=False), "RGBA"),
        (brand / "icon" / "blha-rink-mark.png", px.b_icon(1024, px.BLACK), "RGB"),
        (brand / "source" / "blha-wordmark-white.png", px.wordmark_transparent((1448, 1086), "white", 6), "RGBA"),
        (brand / "source" / "blha-wordmark-black.png", px.wordmark_transparent((1448, 1086), "black", 6), "RGBA"),
        (brand / "source" / "blha-wordmark-textured-cream.png", px.wordmark_cream(), "RGB"),
    ]
    for path, img, mode in marks:
        px.save(path, img, mode)
    return [p for p, _i, _m in marks]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "brand" / "kit"
    made = build_kit(out)
    build_marks(ROOT / "brand" if out == ROOT / "brand" / "kit" else out / "marks")
    print({k: len(v) for k, v in made.items()})


if __name__ == "__main__":
    main()
