"""PNG graphics for Discord in the league's 8-bit look: the Dynasty Pot and one card per franchise.

Drawn with tools/blha_pixel.py (the same toolkit as the brand kit and channel
headers): a charcoal arena ground on an 8 px grid, gold boards, Jersey 10 for
names and numbers and Silkscreen for labels, both rendered as hard-edged pixels.
Team colours appear only on each franchise's pixel jersey and the stripe beside
it; everything else stays in league colours. Pillow only.
"""

from __future__ import annotations

import io
import sys
from typing import Any

from PIL import Image, ImageDraw

from blha.league import REPO_ROOT
from history.records import money

sys.path.insert(0, str(REPO_ROOT / "tools"))
import blha_pixel as px  # noqa: E402

W, H, K = 1600, 900, 8
MUTED = px.MUTED
JERSEY = ["......KKKKKK......", "...KKKPPWWPPKKK...", "..KPPPPPPPPPPPPK..", ".KPPPPPPPPPPPPPPK.", "KPPPPPPPPPPPPPPPPK",
          "KPPPKPPPPPPPPKPPPK", "KSSSKPPPPPPPPKSSSK", "KPPPKPPPPPPPPKPPPK", "KSSSKPPPPPPPPKSSSK", "KPPPKPPPPPPPPKPPPK",
          ".KKKKSSSSSSSSKKKK.", "....KPPPPPPPPK....", "....KSSSSSSSSK....", "....KKKKKKKKKK...."]
COIN = ["..KKK..", ".KGGGK.", "KGGWGGK", "KGGWGGK", "KGGWGGK", ".KGGGK.", "..KKK.."]
COIN_OFF = ["..SSS..", ".S...S.", "S.....S", "S.....S", "S.....S", ".S...S.", "..SSS.."]


def rgb(value: Any, default: tuple[int, int, int]) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4)) if len(text) == 6 else default  # type: ignore[return-value]
    except ValueError:
        return default


def paint(rows: list[str], scale: int, pal: dict[str, tuple[int, int, int]] | None = None) -> Image.Image:
    """A pixel sprite (one character per pixel, "." transparent) enlarged by a whole number."""
    colours = {**px.PAL, "S": px.STEEL, **(pal or {})}
    img = Image.new("RGBA", (len(rows[0]), len(rows)), (0, 0, 0, 0))
    pixels = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in colours:
                pixels[x, y] = colours[ch] + (255,)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def jersey(colors: list[str] | None, scale: int) -> Image.Image:
    colors = colors or []
    main = rgb(colors[0] if colors else None, px.GOLD)
    second = rgb(colors[1] if len(colors) > 1 else None, px.PAPER)
    return paint(JERSEY, scale, {"P": main, "S": second})


def fit(text: str, face: str, width: int, scales: tuple[int, ...]) -> tuple[str, int]:
    """The largest scale at which the text fits; at the smallest, trim it and end with an ellipsis."""
    f = px.font(face)
    for s in scales:
        if f.width(text, s) <= width:
            return text, s
    s = scales[-1]
    while text and f.width(text + "...", s) > width:
        text = text[:-1]
    return text.rstrip() + "...", s


def right_text(img: Image.Image, text: str, face: str, scale: int, right: int, cap_y: int, color, **kw) -> None:
    px.draw_text(img, text, face, scale, right - px.font(face).width(text, scale), cap_y, color, **kw)


def ground() -> Image.Image:
    """Charcoal arena with a dithered fade into the stands along the bottom and the gold boards."""
    a = px.art(W // K, H // K + 1, px.CHARCOAL)
    px.grain(a, [px.CHAR_LT, px.CHAR_DK], .02, 41)
    px.dither(a, 0, 94, W // K, 12, px.STANDS)
    img = px.enlarge(a, K, (W, H), offset=(0, 0))
    ImageDraw.Draw(img).rectangle((0, H - 16, W, H), fill=px.GOLD)
    return img


def sign_off(img: Image.Image, x: int) -> None:
    px.draw_text(img, "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026", "silk", 3, x, H - 56, MUTED)
    b = paint(px.SPRITES["b"], 5)
    img.alpha_composite(b, (W - 80 - b.width, H - 40 - b.height))


def kicker(img: Image.Image, x: int, text: str) -> None:
    ImageDraw.Draw(img).rectangle((x - 40, 80, x - 25, 231), fill=px.GOLD)
    px.draw_text(img, text, "silk", 4, x, 88, px.GOLD)


def to_png(canvas: Image.Image) -> bytes:
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def dynasty_pot_png(summary: dict[str, Any]) -> bytes:
    img = ground()
    draw = ImageDraw.Draw(img)
    x = 120
    kicker(img, x, "BLHA LEAGUE LEDGER")
    px.draw_text(img, "DYNASTY POT", "jersey", 9, x, 128, px.CREAM, shadow=px.BLACK)
    need = int(summary.get("titles_to_win") or 3)
    px.draw_text(img, f"FIRST TO {need} TITLES IN ONE CYCLE TAKES THE POT", "silk", 3, x, 248, MUTED)
    px.draw_text(img, f"CYCLE BEGAN SEASON {summary['cycle_started']} • ARTICLE IV", "silk", 3, x, 280, MUTED)
    right_text(img, "CURRENT BALANCE", "silk", 4, W - 80, 88, px.CREAM)
    balance, scale = fit(money(summary.get("balance")), "jersey", 560, (12, 10, 8, 6))
    right_text(img, balance, "jersey", scale, W - 80, 136, px.GOLD, shadow=px.BLACK)
    draw.rectangle((80, 320, W - 80, 327), fill=px.GOLD)

    rows = summary.get("rows") or []
    if not rows:
        px.draw_text(img, "NO FRANCHISES RECORDED YET", "silk", 4, x, 392, px.CREAM)
        sign_off(img, 80)
        return to_png(img)
    per_col = (len(rows) + 1) // 2
    top, bottom = 344, H - 104
    step = min(80, (bottom - top) // max(per_col, 1) // 8 * 8)
    col_w = (W - 160 - 64) // 2
    coin = 4 if step >= 56 else 3
    leader = max(r["titles"] for r in rows)
    for i, row in enumerate(rows):
        col, line = divmod(i, per_col)
        cx = 80 + col * (col_w + 64)
        y = top + line * step
        if line:
            draw.rectangle((cx, y, cx + col_w, y + 3), fill=px.CHAR_LT)
        shirt = jersey(row.get("colors") or ([row["color"]] if row.get("color") else None), 3)
        img.alpha_composite(shirt, (cx, y + (step - shirt.height) // 2))
        coins_w = need * (7 * coin + 8)
        name_scale = 4 if step >= 64 else 3
        name, s = fit(row["name"], "jersey", col_w - 72 - coins_w - 16, (name_scale, 3))
        colour = px.GOLD if row["titles"] and row["titles"] == leader else px.CREAM
        px.draw_text(img, name, "jersey", s, cx + 72, y + (step - 10 * s) // 2, colour)
        for p in range(need):
            piece = paint(COIN if p < row["titles"] else COIN_OFF, coin)
            img.alpha_composite(piece, (cx + col_w - coins_w + p * (7 * coin + 8), y + (step - piece.height) // 2))
    sign_off(img, 80)
    return to_png(img)


def franchise_card_png(profile: dict[str, Any]) -> bytes:
    img = ground()
    draw = ImageDraw.Draw(img)
    colors = profile.get("colors") or []
    main = rgb(colors[0] if colors else None, px.GOLD)
    second = rgb(colors[1] if len(colors) > 1 else None, main)

    draw.rectangle((0, 0, 535, H - 17), fill=px.BLACK)
    draw.rectangle((536, 0, 551, H - 17), fill=main)          # the team stripe
    draw.rectangle((552, 0, 559, H - 17), fill=second)
    logo = profile.get("logo")
    placed = False
    if logo:
        try:
            art = Image.open(REPO_ROOT / logo).convert("RGBA")
            art.thumbnail((400, 400), Image.LANCZOS)
            img.alpha_composite(art, (268 - art.width // 2, 360 - art.height // 2))
            placed = True
        except Exception:
            placed = False
    if not placed:
        shirt = jersey(colors, 14)
        img.alpha_composite(shirt, (268 - shirt.width // 2, 360 - shirt.height // 2))
    founded = profile.get("founded")
    px.draw_text(img, f"EST. {founded}" if founded else "BLHA FRANCHISE", "silk", 4, 268, 632, px.CREAM, align="c")

    x, width = 640, W - 640 - 80
    kicker(img, x, "BLHA FRANCHISE DIRECTORY")
    name, s = fit(profile["name"], "jersey", width, (9, 8, 7, 6, 5, 4))
    px.draw_text(img, name, "jersey", s, x, 128 + (9 - s) * 5, px.CREAM, shadow=px.BLACK)
    draw.rectangle((x, 248, W - 80, 255), fill=px.GOLD)

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
    y, step = 288, (H - 104 - 288) // len(rows)
    for label, value in rows:
        px.draw_text(img, label, "silk", 3, x, y, px.GOLD)
        text, vs = fit(str(value), "jersey", width, (4, 3))
        px.draw_text(img, text, "jersey", vs, x, y + 28, px.CREAM)
        y += step
    sign_off(img, x)
    return to_png(img)
