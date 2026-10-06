"""PNG graphics for Discord: the Dynasty Pot and one card per franchise (Pillow).

Brand: charcoal #2B2D31 background, gold #FFB81C accents, cream #F4EFE4 text,
black #0C0D0F panels, the gold vertical bar and rule from the channel headers,
and the B mark from brand/primary/. Fonts: Poppins if installed, otherwise
DejaVu Sans or Liberation Sans (present on GitHub's Ubuntu runners), otherwise
Pillow's built-in font.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from blha.league import REPO_ROOT
from history.context import initials
from history.records import money

W, H = 1600, 900
CHARCOAL = "#2B2D31"
BLACK = "#0C0D0F"
GOLD = "#FFB81C"
CREAM = "#F4EFE4"
GREY = "#9A9CA2"
DIM = "#55575C"
B_MARK = REPO_ROOT / "brand" / "primary" / "blha-b-mark.png"

BOLD_FONTS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
REGULAR_FONTS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    for path in BOLD_FONTS if bold else REGULAR_FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def text_width(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=f)


def fit(draw: ImageDraw.ImageDraw, text: str, width: float, size: int, minimum: int = 18,
        bold: bool = True) -> tuple[str, ImageFont.ImageFont]:
    """Largest font (down to ``minimum``) that fits; truncate with an ellipsis below that."""
    for s in range(size, minimum - 1, -2):
        f = font(s, bold)
        if text_width(draw, text, f) <= width:
            return text, f
    f = font(minimum, bold)
    while text and text_width(draw, text + "…", f) > width:
        text = text[:-1]
    return text.rstrip() + "…", f


def wrap(draw: ImageDraw.ImageDraw, text: str, width: float, f: ImageFont.ImageFont, lines: int = 2) -> list[str]:
    words, out, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if text_width(draw, trial, f) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        last = out[-1]
        while last and text_width(draw, last + "…", f) > width:
            last = last[:-1]
        out[-1] = last.rstrip() + "…"
    return out


def paste_fit(canvas: Image.Image, path: Path, box: tuple[int, int, int, int]) -> bool:
    """Paste an image scaled to fit inside box (x0, y0, x1, y1), centred. False if it cannot be read."""
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return False
    x0, y0, x1, y1 = box
    img.thumbnail((x1 - x0, y1 - y0), Image.LANCZOS)
    canvas.alpha_composite(img, (x0 + (x1 - x0 - img.width) // 2, y0 + (y1 - y0 - img.height) // 2))
    return True


def brand_frame(canvas: Image.Image, draw: ImageDraw.ImageDraw, kicker: str) -> None:
    draw.rectangle((80, 84, 90, 244), fill=GOLD)
    draw.text((118, 80), kicker.upper(), font=font(30), fill=GOLD)
    draw.rectangle((0, H - 18, W, H), fill=GOLD)
    draw.text((80, H - 66), "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026", font=font(24, bold=False), fill=GREY)
    paste_fit(canvas, B_MARK, (W - 150, H - 128, W - 80, H - 34))


def to_png(canvas: Image.Image) -> bytes:
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def dynasty_pot_png(summary: dict[str, Any]) -> bytes:
    canvas = Image.new("RGBA", (W, H), CHARCOAL)
    draw = ImageDraw.Draw(canvas)
    brand_frame(canvas, draw, "BLHA League Ledger")
    draw.text((114, 112), "DYNASTY POT", font=font(104), fill=CREAM)
    need = int(summary.get("titles_to_win") or 3)
    sub = font(26, bold=False)
    y = 252
    for line in wrap(draw, f"Cycle began Season {summary['cycle_started']}. The first franchise to win {need} BLHA "
                     f"Championships in the cycle takes the whole pot (Article IV).", 840, sub, 2):
        draw.text((118, y), line, font=sub, fill=GREY)
        y += 34

    label = "CURRENT BALANCE"
    draw.text((W - 80 - text_width(draw, label, font(26)), 96), label, font=font(26), fill=CREAM)
    bal, bf = fit(draw, money(summary.get("balance")), 500, 140, 56)
    draw.text((W - 80 - text_width(draw, bal, bf), 128), bal, font=bf, fill=GOLD)
    draw.rectangle((80, 330, W - 80, 334), fill=GOLD)

    rows = summary.get("rows") or []
    if not rows:
        draw.text((118, 390), "No franchises recorded yet.", font=font(40, bold=False), fill=CREAM)
        return to_png(canvas)
    per_col = (len(rows) + 1) // 2
    top, bottom = 354, H - 140
    step = min(84, (bottom - top) / max(per_col, 1))
    col_w = (W - 160 - 60) / 2
    pip = int(min(34, step * 0.45))
    leader = max(r["titles"] for r in rows)
    for i, row in enumerate(rows):
        col, line = divmod(i, per_col)
        x = 80 + col * (col_w + 60)
        y = top + line * step
        mid = y + step / 2
        if line:
            draw.line((x, y, x + col_w, y), fill=DIM, width=1)
        swatch = 16
        draw.ellipse((x + 4, mid - swatch, x + 4 + 2 * swatch, mid + swatch), fill=row.get("color") or GOLD, outline=CREAM, width=2)
        pips_w = need * (pip + 12)
        name, nf = fit(draw, row["name"], col_w - 60 - pips_w - 20, 38, 22)
        colour = GOLD if row["titles"] and row["titles"] == leader else CREAM
        draw.text((x + 52, mid), name, font=nf, fill=colour, anchor="lm")
        for p in range(need):
            px = x + col_w - pips_w + p * (pip + 12)
            box = (px, mid - pip / 2, px + pip, mid + pip / 2)
            if p < row["titles"]:
                draw.ellipse(box, fill=GOLD)
            else:
                draw.ellipse(box, outline=GREY, width=3)
    return to_png(canvas)


def franchise_card_png(profile: dict[str, Any]) -> bytes:
    canvas = Image.new("RGBA", (W, H), CHARCOAL)
    draw = ImageDraw.Draw(canvas)
    colors = profile.get("colors") or [GOLD, CREAM]
    primary = colors[0]
    secondary = colors[1] if len(colors) > 1 else CREAM

    panel = (0, 0, 540, H - 18)
    draw.rectangle(panel, fill=primary)
    draw.rectangle((540, 0, 552, H - 18), fill=GOLD)
    logo = profile.get("logo")
    if not (logo and paste_fit(canvas, REPO_ROOT / logo, (70, 170, 470, 570))):
        draw.ellipse((95, 195, 445, 545), fill=BLACK, outline=secondary, width=10)
        mono, mf = fit(draw, initials(profile["name"]), 260, 150, 60)
        draw.text((270, 370), mono, font=mf, fill=secondary, anchor="mm")
    founded = profile.get("founded")
    draw.text((270, 650), f"EST. {founded}" if founded else "BLHA FRANCHISE", font=font(34), fill=CREAM if primary.upper() != CREAM else BLACK,
              anchor="mm")

    x, width = 620, W - 620 - 80
    draw.rectangle((x - 28, 84, x - 18, 220), fill=GOLD)
    draw.text((x, 80), "BLHA FRANCHISE DIRECTORY", font=font(30), fill=GOLD)
    name_font = font(78)
    lines = wrap(draw, profile["name"], width, name_font, 2)
    if len(lines) > 1 or text_width(draw, lines[0], name_font) > width:
        name_font = font(62)
        lines = wrap(draw, profile["name"], width, name_font, 2)
    y = 124
    for line in lines:
        draw.text((x, y), line, font=name_font, fill=CREAM)
        y += int(name_font.size * 1.12)
    y = max(y + 20, 300)
    draw.rectangle((x, y, W - 80, y + 4), fill=GOLD)
    y += 30

    titles = profile.get("titles") or []
    need = int(profile.get("titles_to_win") or 3)
    rival = profile.get("rival")
    rows = [
        ("OWNER", profile.get("owner") or "To be announced"),
        ("FOUNDED", f"Season {founded}" if founded else "To be announced"),
        ("BLHA CHAMPIONSHIPS", f"{len(titles)} ({', '.join(str(t) for t in titles)})" if titles else "None yet"),
        ("DYNASTY POT", f"{profile.get('dynasty_count', 0)} of {need} titles this cycle"),
        ("RIVAL", f"{rival}, lifetime {profile['rival_record']}" if rival else "To be decided on the ice"),
    ]
    step = (H - 110 - y) / len(rows)
    for label, value in rows:
        draw.text((x, y), label, font=font(24), fill=GOLD)
        text, vf = fit(draw, str(value), width, 40, 22, bold=False)
        draw.text((x, y + 30), text, font=vf, fill=CREAM)
        y += step
    draw.rectangle((0, H - 18, W, H), fill=GOLD)
    draw.text((x, H - 66), "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026", font=font(24, bold=False), fill=GREY)
    paste_fit(canvas, B_MARK, (W - 150, H - 128, W - 80, H - 34))
    return to_png(canvas)
