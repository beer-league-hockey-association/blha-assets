#!/usr/bin/env python3
"""Build the complete BLHA brand/graphics package.

Usage: build_brand_package.py [OUT_DIR]   (default: brand/kit; sources in brand/source/)

Sources: the B mark (brand/primary/blha-b-mark.png) and the three official
wordmark files. Headers reuse tools/build_discord_assets.make_header so the
package matches what the automation hosts.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_discord_assets as bda  # noqa: E402

BG, GOLD, CREAM, MUTED, BLACK = bda.BG, bda.GOLD, bda.CREAM, bda.MUTED, bda.BLACK
RED, GREEN = (214, 69, 69), (63, 163, 77)
BOLD, MONO = bda.FONT_BOLD, bda.FONT_MONO


def trim(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    return img.crop(img.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox())


def fit(img: Image.Image, w: int | None = None, h: int | None = None) -> Image.Image:
    if w and (not h or img.width / w >= img.height / h):
        return img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
    return img.resize((round(img.width * h / img.height), h), Image.LANCZOS)


def save(path: Path, img: Image.Image, rgb: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if rgb else img).save(path, "PNG", optimize=True)


def canvas(w: int, h: int, color=BG, texture=True) -> Image.Image:
    img = Image.new("RGBA", (w, h), color + (255,))
    return bda.add_texture(img, seed=w + h) if texture else img


def paste_center(base: Image.Image, mark: Image.Image, cx: int, cy: int):
    base.alpha_composite(mark, (cx - mark.width // 2, cy - mark.height // 2))


def arc_text(img, text, cx, cy, r, font, fill, top=True, spacing=0):
    """Text along a circle, centred on the top (reads clockwise) or bottom (reads left to right)."""
    widths = [font.getlength(c) + spacing for c in text]
    total = sum(widths)
    cur = -total / r / 2
    for ch, wd in zip(text, widths):
        t = cur + wd / r / 2
        cur += wd / r
        if ch == " ":
            continue
        tile = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((120, 120), ch, font=font, fill=fill + (255,), anchor="mm")
        deg = math.degrees(t)
        if top:
            tile = tile.rotate(-deg, resample=Image.BICUBIC)
            px, py = cx + r * math.sin(t), cy - r * math.cos(t)
        else:
            tile = tile.rotate(deg, resample=Image.BICUBIC)
            px, py = cx + r * math.sin(t), cy + r * math.cos(t)
        img.alpha_composite(tile, (round(px - 120), round(py - 120)))


# ---------- builders ----------

def wordmark_on(w, h, wm_white, color=BG, texture=True, frac=0.72, rules=True):
    img = canvas(w, h, color, texture)
    d = ImageDraw.Draw(img)
    mark = fit(wm_white, w=round(w * frac))
    if mark.height > h * 0.62:
        mark = fit(wm_white, h=round(h * 0.62))
    paste_center(img, mark, w // 2, h // 2)
    if rules:
        t = max(4, h // 120)
        d.rectangle((0, 0, w, t * 2), fill=GOLD)
        d.rectangle((0, h - t * 2, w, h), fill=GOLD)
    return img.convert("RGB")


def seal(size, dark=True, bm=None):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size // 2
    fill = BG if dark else CREAM
    ink = CREAM if dark else BLACK
    d.ellipse((6, 6, size - 6, size - 6), fill=BLACK + (255,))
    d.ellipse((size * 0.025, size * 0.025, size * 0.975, size * 0.975), fill=GOLD + (255,))
    d.ellipse((size * 0.045, size * 0.045, size * 0.955, size * 0.955), fill=fill + (255,))
    d.ellipse((size * 0.22, size * 0.22, size * 0.78, size * 0.78), outline=GOLD + (255,), width=max(3, size // 170))  # inner ring
    d.ellipse((size * 0.075, size * 0.075, size * 0.925, size * 0.925), outline=GOLD + (255,), width=max(2, size // 300))
    f = ImageFont.truetype(BOLD, round(size * 0.048))
    arc_text(img, "BEER LEAGUE HOCKEY ASSOCIATION", c, c, size * 0.375, f, ink, top=True, spacing=size * 0.006)
    arc_text(img, "OFFICIAL  •  EST. 2026", c, c, size * 0.375, f, ink, top=False, spacing=size * 0.006)
    for sx in (-1, 1):  # side stars
        d.ellipse((c + sx * size * 0.442 - 7, c - 7, c + sx * size * 0.442 + 7, c + 7), fill=GOLD + (255,))
    mark = fit(bm, h=round(size * 0.40))
    paste_center(img, mark, c, c)
    return img


def status_stamp(text, color, w=900, h=320, sub=None):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgba = color + (255,)
    d.rounded_rectangle((8, 8, w - 8, h - 8), radius=28, outline=rgba, width=12)
    d.rounded_rectangle((34, 34, w - 34, h - 34), radius=18, outline=rgba, width=4)
    font = bda.fit_font(text, BOLD, 170, w - 150, 40)
    ty = h // 2 - (18 if sub else 0)
    d.text((w // 2, ty), text, font=font, fill=rgba, anchor="mm")
    if sub:
        d.text((w // 2, h - 78), sub, font=ImageFont.truetype(MONO, 30), fill=rgba, anchor="mm")
    return img.rotate(3, resample=Image.BICUBIC, expand=True)


def round_icon(src: Image.Image, size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src.resize((size, size), Image.LANCZOS), (0, 0), mask)
    return out


def contact_sheet(root: Path, groups: list[tuple[str, list[Path]]]):
    W = 1800
    thumbs, y = [], 90
    sheet_items = []
    for title, files in groups:
        sheet_items.append(("title", title, y))
        y += 54
        x = 30
        rowh = 0
        for f in files:
            im = Image.open(f).convert("RGBA")
            s = min(420 / im.width, 300 / im.height)
            t = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
            if x + t.width > W - 30:
                x = 30
                y += rowh + 40
                rowh = 0
            sheet_items.append(("img", t, (x, y), f.name))
            x += t.width + 24
            rowh = max(rowh, t.height)
        y += rowh + 60
    sheet = Image.new("RGBA", (W, y + 20), (26, 27, 30, 255))
    d = ImageDraw.Draw(sheet)
    d.text((30, 24), "BLHA BRAND & GRAPHICS PACKAGE", font=ImageFont.truetype(BOLD, 40), fill=CREAM)
    lab = ImageFont.truetype(bda.FONT_REG, 15)
    for it in sheet_items:
        if it[0] == "title":
            d.text((30, it[2]), it[1].upper(), font=ImageFont.truetype(BOLD, 26), fill=GOLD)
        else:
            _, t, pos, name = it
            sheet.alpha_composite(t, pos)
            d.text((pos[0], pos[1] + t.height + 6), name[:48], font=lab, fill=MUTED)
    save(root / "BLHA_Package_Contact_Sheet.png", sheet, rgb=True)


def main():
    root = Path(__file__).resolve().parents[1]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "brand" / "kit"
    src = root / "brand" / "source"
    wm_white = trim(Image.open(src / "blha-wordmark-white.png"))
    wm_black = trim(Image.open(src / "blha-wordmark-black.png"))
    wm_tex = Image.open(src / "blha-wordmark-textured-cream.png").convert("RGB")
    bm = Image.open(bda.B_MARK).convert("RGBA")
    made: dict[str, list[Path]] = {}

    def put(group, rel, img, rgb=False):
        p = out / group / rel
        save(p, img, rgb)
        made.setdefault(group, []).append(p)

    # 1 logos
    g = "01_logos"
    put(g, "blha-wordmark-white-transparent.png", fit(wm_white, w=2000))
    put(g, "blha-wordmark-black-transparent.png", fit(wm_black, w=2000))
    put(g, "blha-wordmark-textured-cream.png", wm_tex, rgb=True)
    put(g, "blha-wordmark-on-charcoal-1920x1080.png", wordmark_on(1920, 1080, wm_white, rules=False), rgb=True)
    put(g, "blha-wordmark-on-black-1920x1080.png", wordmark_on(1920, 1080, wm_white, BLACK, False, rules=False), rgb=True)
    put(g, "blha-wordmark-on-white-1920x1080.png", wordmark_on(1920, 1080, wm_black, (255, 255, 255), False, rules=False), rgb=True)
    put(g, "blha-b-mark-transparent-1024.png", fit(bm, h=1024))
    for name, col in (("black", BLACK), ("charcoal", BG), ("cream", CREAM), ("gold", GOLD)):
        put(g, f"blha-b-icon-{name}-1024.png", _b_on(1024, bm, col), rgb=True)

    # 2 avatars & icons
    g = "02_avatars_icons"
    icon = _b_on(1024, bm, BLACK)
    put(g, "blha-server-icon-1024.png", icon, rgb=True)
    put(g, "blha-webhook-avatar-512.png", icon.resize((512, 512), Image.LANCZOS), rgb=True)
    put(g, "blha-bot-avatar-round-512.png", round_icon(icon, 512))
    put(g, "blha-profile-picture-400.png", icon.resize((400, 400), Image.LANCZOS), rgb=True)
    for s in (128, 64):
        put(g, f"blha-emoji-b-{s}.png", _emoji(bm, s))
    put(g, "blha-favicon-256.png", icon.resize((256, 256), Image.LANCZOS), rgb=True)

    # 3 server & social banners
    g = "03_server_social_banners"
    put(g, "blha-server-banner-960x540.png", wordmark_on(960, 540, wm_white), rgb=True)
    put(g, "blha-server-banner-1920x1080.png", wordmark_on(1920, 1080, wm_white), rgb=True)
    put(g, "blha-invite-splash-1920x1080.png", wordmark_on(1920, 1080, wm_white, BLACK), rgb=True)
    put(g, "blha-github-social-preview-1280x640.png", wordmark_on(1280, 640, wm_white), rgb=True)
    put(g, "blha-x-header-1500x500.png", wordmark_on(1500, 500, wm_white, frac=0.62), rgb=True)
    put(g, "blha-event-cover-800x320.png", wordmark_on(800, 320, wm_white, frac=0.6), rgb=True)

    # 4 channel headers (1600x533)
    g = "04_channel_headers"
    headers = [
        ("welcome", "WELCOME TO THE BLHA", "WELCOME TO THE ROOM"),
        ("constitution", "LEAGUE CONSTITUTION", "OFFICIAL BLHA RULEBOOK"),
        ("announcements", "LEAGUE ANNOUNCEMENTS", "OFFICIAL BLHA NOTICE"),
        ("calendar", "LEAGUE CALENDAR", "OFFICIAL BLHA CALENDAR"),
        ("ledger", "LEAGUE LEDGER", "OFFICIAL BLHA LEDGER"),
        ("voting", "LEAGUE VOTING", "OFFICIAL BLHA VOTE"),
        ("draft-center", "DRAFT CENTER", "OFFICIAL BLHA DRAFT"),
        ("the-wire", "THE WIRE", "BLHA NEWS DESK"),
        ("general-managers", "GENERAL MANAGERS", "THE CLUBHOUSE"),
        ("trade-center", "TRADE CENTER", "OFFICIAL BLHA TRADES"),
        ("scouting", "SCOUTING DEPARTMENT", "PROSPECTS & PICKS"),
        ("waiver-wire", "WAIVER WIRE", "FAAB & CLAIMS"),
        ("competition", "LEAGUE COMPETITION", "STANDINGS & PLAYOFFS"),
        ("commissioners-office", "COMMISSIONER'S OFFICE", "OFFICIAL BLHA RULINGS"),
        ("franchise-hq", "FRANCHISE HQ", "YOUR CLUB, YOUR CALLS"),
        ("champions", "BLHA CHAMPIONS", "PERMANENT LEAGUE HISTORY"),
        ("records", "LEAGUE RECORDS", "THE PERMANENT RECORD"),
        ("generic", "BEER LEAGUE HOCKEY ASSOCIATION", "OFFICIAL BLHA"),
    ]
    for slug, title, kick in headers:
        put(g, f"blha-{slug}-header-1600x533.png", bda.make_header(title, kick), rgb=True)

    # 5 dividers
    g = "05_dividers"
    put(g, "blha-footer-divider-1600x180.png", bda.make_footer())
    thin = Image.new("RGBA", (1600, 40), (0, 0, 0, 0))
    td = ImageDraw.Draw(thin)
    td.rectangle((62, 14, 1538, 26), fill=GOLD + (255,))
    td.rectangle((62, 6, 1538, 9), fill=CREAM + (255,))
    td.rectangle((62, 31, 1538, 34), fill=CREAM + (255,))
    put(g, "blha-thin-rule-1600x40.png", thin)
    bar = Image.new("RGBA", (1600, 24), GOLD + (255,))
    put(g, "blha-gold-bar-1600x24.png", bar)

    # 6 seals & stamps
    g = "06_seals_stamps"
    put(g, "blha-official-seal-dark-1024.png", seal(1024, True, bm))
    put(g, "blha-official-seal-cream-1024.png", seal(1024, False, bm))
    put(g, "blha-official-seal-256.png", seal(1024, True, bm).resize((256, 256), Image.LANCZOS))
    stamps = [
        ("official", "OFFICIAL", CREAM, "BEER LEAGUE HOCKEY ASSOCIATION"),
        ("approved", "APPROVED", GREEN, None),
        ("denied", "DENIED", RED, None),
        ("pending", "PENDING", GOLD, None),
        ("final", "FINAL", CREAM, None),
        ("amended", "AMENDED", GOLD, None),
        ("vote-passed", "VOTE PASSED", GREEN, None),
        ("vote-failed", "VOTE FAILED", RED, None),
        ("commissioner-ruling", "COMMISSIONER RULING", CREAM, "BLHA LEAGUE OFFICE"),
        ("champions", "CHAMPIONS", GOLD, "BLHA PERMANENT RECORD"),
        ("paid-in-full", "PAID IN FULL", GREEN, "BLHA LEDGER"),
        ("dues-outstanding", "DUES OUTSTANDING", RED, "BLHA LEDGER"),
        ("urgent-deadline", "URGENT DEADLINE", RED, "ACTION REQUIRED"),
    ]
    for slug, text, col, sub in stamps:
        put(g, f"blha-stamp-{slug}.png", status_stamp(text, col, sub=sub))

    # docs
    (out / "README.txt").write_text(README, encoding="utf-8")
    manifest = {k: [p.name for p in v] for k, v in made.items()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    contact_sheet(out, [(k, v) for k, v in made.items()])
    print({k: len(v) for k, v in made.items()})


def _b_on(size, bm, color):
    if color == BLACK:
        return bda.b_icon(size)
    img = Image.new("RGBA", (size, size), color + (255,))
    m = fit(bm, h=round(size * 0.66))
    paste_center(img, m, size // 2, size // 2)
    return img


def _emoji(bm, s):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    m = fit(bm, h=round(s * 0.9))
    paste_center(img, m, s // 2, s // 2)
    return img


README = """BLHA BRAND & GRAPHICS PACKAGE
=============================
Palette: charcoal #2B2D31, black #0C0D0F, gold #FFB81C, cream #F4EFE4.
Official marks: the BLHA wordmark and the B cut from it (white fill, black + gold keylines).

01_logos                 Wordmarks (transparent white / black, textured cream) and the B mark
02_avatars_icons         Server icon, webhook/bot avatar, profile pic, emoji, favicon
03_server_social_banners Discord server banner/splash, GitHub social preview, X header, event cover
04_channel_headers       1600x533 (3:1) headers for every channel category + welcome + generic
05_dividers              Footer divider (transparent), thin rule, gold bar
06_seals_stamps          Round official seal (dark/cream) and status stamps (transparent PNG)

Discord notes
- Embed images display at ~400px wide; headers are 3:1 so text stays readable.
- Discord caches by URL: when you replace a file, add ?v=NEXT to its URL.
- Server banner needs a boosted server; recommended 960x540 or larger (16:9).
- Stamps are transparent PNGs: use as embed thumbnail or image in rulings, votes and ledger posts.
"""

if __name__ == "__main__":
    main()
