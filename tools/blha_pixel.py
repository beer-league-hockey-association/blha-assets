"""BLHA 8-bit pixel-art toolkit, shared by build_discord_assets.py and build_brand_package.py.

Every graphic is painted on a small art grid and enlarged with NEAREST, so each
art pixel is a hard-edged square (banners and headers use an 8 px grid: one art
pixel = 8 export pixels). Text uses the OFL pixel fonts in brand/fonts
(Jersey 10 for display, Silkscreen for labels). Glyphs are rendered at their
design pixel, thresholded to 1-bit and enlarged by whole numbers, so letter
edges stay crisp too.

The B mark is generated here: B_BODY is the white body of the official B,
traced once from the original artwork and stored as run-length rows. b_sprite()
rasterises it at any height and wraps it in gold and black keylines.

Pillow only: the CI workflow installs nothing else.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "brand" / "fonts"

# ---------------------------------------------------------------- palette
BLACK = (14, 15, 18)        # #0E0F12
CHARCOAL = (43, 45, 49)     # #2B2D31
GOLD = (255, 184, 28)       # #FFB81C
CREAM = (244, 239, 228)     # #F4EFE4
ICE = (238, 245, 250)       # #EEF5FA
PAPER = (252, 252, 252)     # #FCFCFC
BLUE = (36, 87, 197)        # #2457C5
RED = (200, 36, 31)         # #C8241F
GREEN = (63, 163, 77)       # #3FA34D  status green: stamps only

# Tones: one-step shades of the palette for grain, dither, bevels, the crowd and the boards.
GOLD_LT, GOLD_DK = (255, 215, 106), (198, 138, 0)
CHAR_LT, CHAR_DK, STANDS = (49, 51, 56), (38, 40, 44), (29, 31, 35)
BLACK_LT, BLACK_DK = (22, 23, 27), (10, 11, 13)
SEAT, SEAT_DK, SEAT_LT = (59, 63, 74), (50, 53, 60), (71, 76, 87)
STEEL, STEEL_DK = (154, 161, 169), (110, 116, 124)
MUTED = (184, 185, 190)
CREAM_DK, CREAM_MD, CREAM_DKR, INK = (230, 222, 204), (237, 231, 218), (218, 209, 189), (58, 54, 49)

# Sprite letters -> colors ("." is transparent)
PAL = {"K": BLACK, "W": PAPER, "G": GOLD, "D": GOLD_DK, "S": STEEL, "N": STEEL_DK,
       "B": BLUE, "R": RED, "L": ICE, "C": CREAM}

SPRITES = {
    # the league site's small B (14 x 14): avatars, emoji, favicon
    "b": ["KKKKKKKKKK....", "KGGGGGGGGGK...", "KGWWWWWWWWGK..", "KGWWKKKKWWWGK.", "KGWWKGGKWWWGK.",
          "KGWWKKKKWWGK..", "KGWWWWWWWWGK..", "KGWWWWWWWWWGK.", "KGWWKKKKKWWWGK", "KGWWKGGGKWWWGK",
          "KGWWKKKKKWWWGK", "KGWWWWWWWWWWGK", "KGGGGGGGGGGGK.", "KKKKKKKKKKKK.."],
    # the ice resurfacer (56 x 28, drives right); its own colors are in SPRITE_PALS["resurfacer"]
    "resurfacer": [
        ".......................KKKKKKKNNNNNNNNKKKK..............", "............KKKK......KBBBBBBBBBBBBBBBBBBBKKK...........",
        "...........KGGGGKK...KBBBBBBBBBBBBBBBBBBBBBBBK..........", ".........KKKGGGGGGK.KBBBBBBBBBBBBBBBBBBBBBBBBBK.........",
        "........KSSSSCCKKK..KSSSSSSSSSSSSSSSSSSSSSSSSSK.........", "........KSMKKCCCK..KKWWWWWWWWWWWWWWWWWWWWWWWWWK.........",
        "........KSMKBBWBKKKKSKWLWWLWWLWWLWWLWWLWWLWWLWK.........", "........KSMKBBBBBBBKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
        "........KSMKBBBBKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........", "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
        "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWWK........", "........KSSSSSSSSSSSSWWWWWWWWWWWWWWWWWWWWWWWWWWWK.......",
        ".........KKWWWWWWWWWWWWWWWKKWWKWWWKWKWWKWWWWWWWWWK......", "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWKKK...",
        "..........KWWWWWWWWWWWWWWWKKWWKWWWKKKWKKKWWWWWWWWWWGCK..", "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWWGGK..",
        "..........KWWWWWWWWWWWWWWWKKWWKKKWKWKWKWKWWWWWWSSSSWWK..", "...KKKKKKKKWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWK..",
        "..KSSSSSSGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGKKKKKKKKKK..", "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...",
        "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...", "..KSSSSSSBBBBKKKBBBBBBKKKBBBBBBBBBBBBBKKKBBBBBBKKKBBK...",
        "..KSMMMMMBBBKKKKKBBBBKKKKKBBBBBBBBBBBKKKKKBBBBKKKKKBK...", "..KSSSSSSKKKKKSKKKKKKKKSKKKKKKKKKKKKKKKSKKKKKKKKSKKKK...",
        "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK....", "CCCCCCK.....KKKKK....KKKKK...........KKKKK....KKKKK.....",
        "KCCCCCCK.....KKK......KKK.............KKK......KKK......", ".KKKKKK.................................................",
    ],
    "puck": ["..KKKKKK..", ".KNNNNNNK.", "KKNNNNNNKK", "KKKKKKKKKK", ".KKKKKKKK."],
    "sticks": ["CC............CC", "CCC..........CCC", ".CCC........CCC.", "..CCC......CCC..", "...CCC....CCC...",
               "....CCC..CCC....", ".....CCCCCC.....", "......CCCC......", ".....CCCCCC.....", "....CCC..CCC....",
               "...CCC....CCC...", "..CCC......CCC..", "GGGC........CGGG", "GGG..........GGG"],
}

# Sprite-specific colors (the resurfacer's rink blue, light-blue ribs, navy hatch and charcoal seat)
SPRITE_PALS = {"resurfacer": {"B": (47, 111, 219), "L": (127, 183, 240), "N": (31, 79, 168), "M": (58, 61, 66)}}

# ---------------------------------------------------------------- the B mark
# White body of the official B (171 x 202 cells, quarter resolution of the original
# artwork); each row lists its filled runs as start+length.
B_BODY = (
    "171x202|0+119;0+121;0+122;0+124;0+126;0+128;0+129;0+131;0+133;0+135;0+137;0+139;0+141;0+142;0+144;"
    "0+146;0+148;0+150;0+152;0+153;0+155;0+157;0+158;0+161;0+162;0+164;0+166;0+168;0+170;0+170;0+171;"
    "0+171;0+171;0+171;0+171;0+35,108+63;0+35,115+56;0+35,123+48;0+35,128+43;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,130+41;0+35,128+43;0+35,127+44;0+35,125+46;0+35,124+47;0+35,122+49;"
    "0+35,120+51;0+35,119+52;0+35,117+54;0+35,116+55;0+35,114+56;0+35,113+56;0+35,111+56;0+35,109+56;"
    "0+35,108+56;0+35,106+56;0+35,104+57;0+35,103+56;0+35,101+57;0+156;0+155;0+153;0+151;0+150;0+148;"
    "0+146;0+145;0+144;0+141;0+140;0+138;0+137;0+135;0+134;0+133;0+134;0+136;0+137;0+139;0+141;0+142;"
    "0+144;0+146;0+147;0+149;0+150;0+153;0+154;0+156;0+157;0+159;0+36,101+59;0+35,103+59;0+35,105+59;"
    "0+35,106+59;0+35,108+59;0+35,110+59;0+35,112+58;0+35,113+58;0+35,115+56;0+35,116+55;0+35,118+53;"
    "0+35,120+51;0+35,122+49;0+35,123+48;0+35,125+46;0+35,127+44;0+35,129+42;0+35,130+41;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;0+35,131+40;"
    "0+35,131+40;0+35,131+40;0+35,131+40;0+35,126+45;0+35,122+49;0+35,115+56;0+35,107+64;0+171;0+171;"
    "0+171;0+171;0+171;0+171;0+171;0+171;0+169;0+167;0+165;0+163;0+162;0+159;0+157;0+155;0+153;0+151;"
    "0+149;0+147;0+145;0+144;0+141;0+139;0+137;0+135;0+133;0+131;0+129;0+127;0+125;0+123;0+121;0+119"
)


@lru_cache(maxsize=None)
def _b_body_image() -> Image.Image:
    size, rows = B_BODY.split("|")
    w, h = (int(v) for v in size.split("x"))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(rows.split(";")):
        for run in filter(None, row.split(",")):
            start, length = (int(v) for v in run.split("+"))
            draw.line((start, y, start + length - 1, y), fill=255)
    return img


def _layer_of(cells: set, x: int, y: int, reach: int) -> int:
    """Rounded distance (in cells) from (x, y) to the nearest filled cell, or reach + 1."""
    best = reach + 1.5
    for dy in range(-reach - 1, reach + 2):
        for dx in range(-reach - 1, reach + 2):
            if (x + dx, y + dy) in cells:
                best = min(best, math.hypot(dx, dy))
    return math.ceil(best - 0.5)


@lru_cache(maxsize=None)
def b_sprite(total_h: int, outer: str = "GGK", counter: str = "GK") -> tuple[str, ...]:
    """The B at total_h rows: white body, then `outer` keylines outside, `counter` lining the counters."""
    reach = len(outer)
    bh = total_h - 2 * reach
    src = _b_body_image()
    bw = max(1, round(src.width / src.height * bh))
    body = src.resize((bw, bh), Image.BOX)
    bp = body.load()
    w, h = bw + 2 * reach, bh + 2 * reach
    cells = {(x + reach, y + reach) for y in range(bh) for x in range(bw) if bp[x, y] >= 128}
    outside, stack = set(), [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        if 0 <= x < w and 0 <= y < h and (x, y) not in cells and (x, y) not in outside:
            outside.add((x, y))
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            if (x, y) in cells:
                row.append("W")
                continue
            layer = _layer_of(cells, x, y, max(reach, len(counter)))
            if (x, y) in outside:
                row.append(outer[layer - 1] if layer <= reach else ".")
            else:
                row.append(counter[min(layer, len(counter)) - 1])
        rows.append("".join(row))
    while all(r[-1] == "." for r in rows):
        rows = [r[:-1] for r in rows]
    while all(r[0] == "." for r in rows):
        rows = [r[1:] for r in rows]
    return tuple(rows)


B32 = lambda: b_sprite(32, "GGK", "GK")            # logos, icons, the primary mark
B48 = lambda: b_sprite(48, "GGKK", "GGK")          # channel headers
B86 = lambda: b_sprite(86, "GGGGKK", "GGGK")       # the official seal


def sprite(rows, scale: int = 1) -> Image.Image:
    pal = {**PAL, **SPRITE_PALS.get(rows, {})} if isinstance(rows, str) else PAL
    rows = SPRITES[rows] if isinstance(rows, str) else rows
    img = Image.new("RGBA", (len(rows[0]), len(rows)), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in pal:
                px[x, y] = pal[ch] + (255,)
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST) if scale > 1 else img


def put(img: Image.Image, rows, x: int, y: int, scale: int = 1) -> None:
    s = sprite(rows, scale)
    img.alpha_composite(s, (x, y))


# ---------------------------------------------------------------- canvas helpers
def art(w: int, h: int, color=None) -> Image.Image:
    return Image.new("RGBA", (w, h), (color + (255,)) if color else (0, 0, 0, 0))


def rect(img, x, y, w, h, color):
    if w > 0 and h > 0:
        ImageDraw.Draw(img).rectangle((x, y, x + w - 1, y + h - 1), fill=color + (255,))


BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def dither(img, x, y, w, h, color, down=True):
    """Ordered (Bayer 4x4) dither: `color` grows from 0 to 100% coverage across the band."""
    px = img.load()
    for j in range(h):
        level = ((j + 0.5) / h if down else 1 - (j + 0.5) / h) * 16
        for i in range(w):
            if BAYER[(y + j) & 3][(x + i) & 3] < level:
                px[x + i, y + j] = color + (255,)


def grain(img, colors, density, seed):
    rnd = random.Random(seed)
    px = img.load()
    w, h = img.size
    for i in range(round(w * h * density)):
        px[rnd.randrange(w), rnd.randrange(h)] = colors[i % len(colors)] + (255,)


def crowd(img, top, h, seed):
    """Stands full of fans: staggered seat dots, a few in gold and cream."""
    w = img.width
    rect(img, 0, top, w, h, STANDS)
    rnd = random.Random(seed)
    px = img.load()
    for j in range(0, h, 2):
        for i in range((j // 2) % 2, w, 2):
            t = rnd.random()
            px[i, top + j] = (GOLD if t < .05 else CREAM if t < .085 else SEAT if t < .4 else SEAT_DK if t < .72 else SEAT_LT) + (255,)


def frame(img, x, y, w, h, t, step, color, wear=0.0, seed=1):
    """Rectangle outline `t` pixels thick with stepped corners; `wear` knocks out a few pixels."""
    rnd = random.Random(seed)
    px = img.load()
    for j in range(h):
        for i in range(w):
            dx, dy = min(i, w - 1 - i), min(j, h - 1 - j)
            s = dx + dy
            if s < step:
                continue
            if (dx < t or dy < t or s < step + t) and not (wear and rnd.random() < wear):
                px[x + i, y + j] = color + (255,)


def ring(img, cx, cy, r0, r1, color, box=None):
    """Fill art pixels whose centers lie between radii r0 and r1 of (cx, cy)."""
    px = img.load()
    x0, y0, x1, y1 = box or (0, 0, img.width, img.height)
    for j in range(y0, y1):
        for i in range(x0, x1):
            if r0 <= math.hypot(i + .5 - cx, j + .5 - cy) <= r1:
                px[i, j] = color + (255,)


def enlarge(img: Image.Image, k: int, size: tuple[int, int], offset: tuple[int, int] | None = None, pad=None) -> Image.Image:
    """Scale the art by k with NEAREST, then crop (or pad) to the exact export size."""
    big = img.resize((img.width * k, img.height * k), Image.NEAREST)
    W, H = size
    if big.width >= W and big.height >= H:
        ox, oy = offset if offset else ((big.width - W) // 2, (big.height - H) // 2)
        return big.crop((ox, oy, ox + W, oy + H))
    out = Image.new("RGBA", size, (pad + (255,)) if pad else (0, 0, 0, 0))
    out.alpha_composite(big, ((W - big.width) // 2, (H - big.height) // 2))
    return out


# ---------------------------------------------------------------- pixel fonts
class PixelFont:
    """A pixel font rendered at its design pixel: mask() returns 1 px per font pixel."""

    def __init__(self, path: Path, size: int, unit: int, cap: int):
        self.font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
        self.unit, self.cap = unit, cap  # render pixels per font pixel, cap height in font pixels

    @lru_cache(maxsize=None)
    def mask(self, text: str) -> tuple[Image.Image, int]:
        """1-bit-style L mask (0/255) at one pixel per font pixel, and the row where capitals start."""
        u = self.unit
        asc, desc = self.font.getmetrics()
        width = (math.ceil(self.font.getlength(text) / u) + 4) * u
        base = (math.ceil(asc / u) + 1) * u
        height = base + (math.ceil(desc / u) + 1) * u
        img = Image.new("L", (width, height), 0)
        ImageDraw.Draw(img).text((u, base), text, font=self.font, fill=255, anchor="ls")
        small = img.resize((width // u, height // u), Image.NEAREST).point(lambda v: 255 if v >= 128 else 0)
        box = small.getbbox()
        if not box:
            return Image.new("L", (1, 1), 0), 0
        cropped = small.crop((box[0], box[1], box[2], box[3]))
        return cropped, base // u - self.cap - box[1]

    def width(self, text: str, scale: int = 1) -> int:
        return self.mask(text)[0].width * scale


@lru_cache(maxsize=None)
def font(name: str) -> PixelFont:
    if name == "jersey":    # Jersey 10: 75-unit pixel on a 1400 em -> size 56 gives 3 px per font pixel
        return PixelFont(FONTS / "jersey10" / "Jersey10-Regular.ttf", 56, 3, 10)
    if name == "silk":      # Silkscreen: 8 px design size -> size 64 gives 8 px per font pixel
        return PixelFont(FONTS / "silkscreen" / "Silkscreen-Regular.ttf", 64, 8, 5)
    if name == "silk-bold":
        return PixelFont(FONTS / "silkscreen" / "Silkscreen-Bold.ttf", 64, 8, 5)
    raise KeyError(name)


def outlined(mask: Image.Image, fill, layers) -> Image.Image:
    """Color a mask and wrap it in stepped keylines (one color per pixel of distance, rounded corners)."""
    reach = len(layers)
    w, h = mask.width + 2 * reach, mask.height + 2 * reach
    mp = mask.load()
    cells = {(x + reach, y + reach) for y in range(mask.height) for x in range(mask.width) if mp[x, y]}
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = out.load()
    for y in range(h):
        for x in range(w):
            if (x, y) in cells:
                px[x, y] = fill + (255,)
            elif reach:
                layer = _layer_of(cells, x, y, reach)
                if 1 <= layer <= reach:
                    px[x, y] = layers[layer - 1] + (255,)
    return out


def text_image(text: str, face: str, scale: int, color, layers=(), shadow=None) -> tuple[Image.Image, int]:
    """Text as an RGBA image at `scale` px per font pixel; returns (image, y of cap top inside it)."""
    mask, cap_top = font(face).mask(text)
    img = outlined(mask, color, layers)
    if shadow:  # hard drop shadow one font pixel down-right
        sh = Image.new("RGBA", (img.width + 1, img.height + 1), (0, 0, 0, 0))
        tint = Image.new("RGBA", img.size, shadow + (255,))
        sh.paste(tint, (1, 1), img)
        sh.alpha_composite(img, (0, 0))
        img = sh
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    return img, (cap_top + len(layers)) * scale


def draw_text(img, text, face, scale, x, cap_y, color, align="l", layers=(), shadow=None, snap=None):
    """Draw text with its capitals starting at cap_y. align: l (x is left) or c (x is center)."""
    t, cap_top = text_image(text, face, scale, color, layers, shadow)
    reach = len(layers) * scale
    left = x - reach if align == "l" else x - (t.width - (scale if shadow else 0)) // 2
    if snap:
        left = round(left / snap) * snap
    img.alpha_composite(t, (left, cap_y - cap_top))
    return t.width


# ---------------------------------------------------------------- the wordmark lockup
VARIANTS = {
    #          fill    keylines (half font-pixel steps)  (whole-pixel steps)  sub/est  sub keyline
    "white": (PAPER, (GOLD, GOLD, BLACK), (GOLD, BLACK), CREAM, BLACK),
    "black": (BLACK, (PAPER, GOLD, GOLD), (GOLD,), BLACK, None),
    "cream": (BLACK, (CREAM, GOLD, GOLD), (GOLD,), BLACK, None),
}


def lockup(a: int, b: int, variant: str = "white", sub_bold: bool = True) -> Image.Image:
    """BLHA in Jersey 10 (a px per font pixel) over BEER LEAGUE HOCKEY ASSOCIATION and EST. 2026
    in Silkscreen (b px per font pixel). Keylines: gold then black on the white version."""
    fill, keys, whole_keys, ink, subkey = VARIANTS[variant]
    mask, cap_top = font("jersey").mask("BLHA")
    if a % 2 == 0:  # keylines on a half-pixel grid
        top = outlined(mask.resize((mask.width * 2, mask.height * 2), Image.NEAREST), fill, keys)
        top = top.resize((top.width * a // 2, top.height * a // 2), Image.NEAREST)
    else:           # odd scale: one keyline per font pixel
        top = outlined(mask, fill, whole_keys)
        top = top.resize((top.width * a, top.height * a), Image.NEAREST)
    sub, sub_cap = text_image("BEER LEAGUE HOCKEY ASSOCIATION", "silk-bold" if sub_bold else "silk", b, ink,
                              (subkey,) if subkey else ())
    est, est_cap = text_image("EST. 2026", "silk", b, ink, (subkey,) if subkey else ())
    rule_w, rule_h, gap = 34 * b, 2 * b, 4 * b
    est_w = est.width + 2 * (rule_w + gap)
    W = max(top.width, sub.width, est_w)
    sub_y = top.height + a - sub_cap
    est_y = sub_y + sub_cap + 5 * b + a - est_cap
    H = est_y + est.height
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(top, ((W - top.width) // 2, 0))
    out.alpha_composite(sub, ((W - sub.width) // 2, sub_y))
    ex = (W - est_w) // 2
    rule_y = est_y + est_cap + (5 * b - rule_h) // 2
    rect(out, ex, rule_y, rule_w, rule_h, GOLD)
    out.alpha_composite(est, (ex + rule_w + gap, est_y))
    rect(out, ex + est_w - rule_w, rule_y, rule_w, rule_h, GOLD)
    return out


def place(img: Image.Image, piece: Image.Image, cx: int, cy: int, snap: int = 1) -> None:
    x = round((cx - piece.width / 2) / snap) * snap
    y = round((cy - piece.height / 2) / snap) * snap
    img.alpha_composite(piece, (x, y))


# ---------------------------------------------------------------- painted backgrounds (art grid)
def bg_plain(w, h, color, textured=True):
    img = art(w, h, color)
    if textured and color == CHARCOAL:
        grain(img, [CHAR_LT, CHAR_DK], .02, w + h)
    elif textured and color == BLACK:
        grain(img, [BLACK_LT, BLACK_DK], .02, w + h)
    return img


def bg_cream(w, h):
    img = art(w, h, CREAM)
    grain(img, [CREAM_DK, CREAM_MD, CREAM_DKR], .06, 77)
    grain(img, [INK], .0012, 5)
    return img


def bg_banner(w, h, bars=1, sticks=False):
    """Charcoal arena: gold boards top and bottom, a crowd fading into charcoal, a dithered fade to black."""
    img = bg_plain(w, h, CHARCOAL)
    ch = round(h * .24)
    f = round(ch * .5)
    crowd(img, bars, ch, w + h)
    dither(img, 0, bars + ch - f, w, f, CHARCOAL)
    bf = round(h * .14)
    dither(img, 0, h - bars - bf, w, bf, BLACK)
    if sticks:
        sy = round(h / 2 - 7) + 1
        put(img, "sticks", 5, sy)
        put(img, "sticks", w - 21, sy)
    rect(img, 0, 0, w, bars, GOLD)
    rect(img, 0, h - bars, w, bars, GOLD)
    return img


SPLASH_ICE = 32


def bg_splash(w=240, h=135):
    """Title screen: black with a dithered arena glow, gold boards and the rink with the ice resurfacer."""
    bars = 2
    img = bg_plain(w, h, BLACK)
    dither(img, 0, bars, w, 44, CHARCOAL, down=False)
    ice_h = SPLASH_ICE
    top = h - bars - ice_h - 6
    iy = top + 6
    rect(img, 0, top, w, 1, STEEL_DK)
    rect(img, 0, top + 1, w, 1, STEEL)
    rect(img, 0, top + 2, w, 3, PAPER)
    rect(img, 0, top + 5, w, 1, GOLD)
    rect(img, 0, iy, w, ice_h, ICE)
    rect(img, w // 2 - 1, iy, 2, ice_h, RED)
    rect(img, round(w * .3) - 1, iy, 2, ice_h, BLUE)
    rect(img, round(w * .7) - 1, iy, 2, ice_h, BLUE)
    rect(img, 0, iy + 3, 26, ice_h - 3, (248, 251, 253))   # fresh ice behind the resurfacer
    put(img, "resurfacer", 20, iy + ice_h - 29)
    put(img, "puck", round(w * .6), iy + ice_h - 7)
    rect(img, 0, 0, w, bars, GOLD)
    rect(img, 0, h - bars, w, bars, GOLD)
    return img


# ---------------------------------------------------------------- finished graphics (export size)
def wordmark_on(size, color, variant, b, dy=0, k=8):
    """Full lockup centered on a flat, lightly textured ground."""
    W, H = size
    aw, ah = math.ceil(W / k), math.ceil(H / k)
    img = enlarge(bg_plain(aw, ah, color, textured=color in (CHARCOAL, BLACK)), k, size)
    place(img, lockup(6 * b, b, variant), W // 2, H // 2 + dy, snap=b)
    return img


def wordmark_transparent(size, variant, b):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    place(img, lockup(6 * b, b, variant), size[0] // 2, size[1] // 2, snap=b)
    return img


def wordmark_cream(size=(1774, 887), b=6):
    W, H = size
    img = enlarge(bg_cream(math.ceil(W / 8), math.ceil(H / 8)), 8, size)
    place(img, lockup(6 * b, b, "cream"), W // 2, H // 2, snap=b)
    return img


def banner(size, a, b, dy=0, bars=1, sticks=False, sub_bold=True):
    W, H = size
    aw, ah = math.ceil(W / 8), math.ceil(H / 8)
    img = enlarge(bg_banner(aw, ah, bars, sticks), 8, size)
    place(img, lockup(a, b, "white", sub_bold), W // 2, H // 2 + dy, snap=b)
    return img


def splash(size=(1920, 1080), b=5):
    W, H = size
    img = enlarge(bg_splash(), 8, size)
    rink_top = (135 - 2 - SPLASH_ICE - 6) * 8
    place(img, lockup(6 * b, b), W // 2, (16 + rink_top) // 2, snap=b)
    return img


HEADER_W, HEADER_H, HEADER_K = 200, 67, 8


def header(title: str, kicker: str, seed: int = 7) -> Image.Image:
    """1600 x 533 channel header on a 200 x 67 art grid: gold eyebrow, big title, the B on the right."""
    a = art(HEADER_W, HEADER_H, CHARCOAL)
    grain(a, [CHAR_LT, CHAR_DK], .02, seed * 31)
    dither(a, 0, 56, HEADER_W, 9, STANDS)
    rect(a, 9, 10, 2, 47, GOLD)
    put(a, B48(), 144, 8)
    rect(a, 0, 65, HEADER_W, 2, GOLD)
    img = enlarge(a, HEADER_K, (1600, 533), offset=(0, 1))
    x = 16 * HEADER_K
    draw_text(img, kicker, "silk", 4, x, 100, GOLD)
    avail = 118 * HEADER_K
    fp = next(s for s in (8, 6, 4, 3) if font("jersey").width(title, s) + s <= avail)
    draw_text(img, title, "jersey", fp, x, 236 - 5 * fp, CREAM, shadow=BLACK)
    draw_text(img, "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026", "silk", 4, x, 372, MUTED)
    return img


def footer_divider() -> Image.Image:
    """Transparent 1600 x 180: cream and gold lines running into a center-ice ring (200 x 23 art grid)."""
    a = art(200, 23)
    rect(a, 8, 10, 86, 2, GOLD)
    rect(a, 106, 10, 86, 2, GOLD)
    for y, step in ((8, 9), (13, 12)):
        rect(a, 8, y, 84, 1, CREAM)
        rect(a, 92, step, 1, 1, CREAM)
        rect(a, 108, y, 84, 1, CREAM)
        rect(a, 107, step, 1, 1, CREAM)
    ring(a, 100, 11, 4.6, 5.9, GOLD, (90, 0, 110, 23))
    return enlarge(a, 8, (1600, 180), offset=(0, 0))


def thin_rule() -> Image.Image:
    a = art(400, 10)
    rect(a, 16, 1, 368, 1, CREAM)
    rect(a, 16, 3, 368, 4, GOLD)
    rect(a, 16, 8, 368, 1, CREAM)
    return enlarge(a, 4, (1600, 40))


def gold_bar() -> Image.Image:
    a = art(200, 3)
    rect(a, 0, 0, 200, 1, GOLD_LT)
    rect(a, 0, 1, 200, 1, GOLD)
    rect(a, 0, 2, 200, 1, GOLD_DK)
    return enlarge(a, 8, (1600, 24))


def b_icon(size: int, color, k: int = 21) -> Image.Image:
    """Large B (28 x 32 art) centered on a flat color."""
    img = Image.new("RGBA", (size, size), color + (255,))
    place(img, sprite(B32(), k), size // 2, size // 2)
    return img


def b_mark(size: tuple[int, int], k: int) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    place(img, sprite(B32(), k), size[0] // 2, size[1] // 2)
    return img


def avatar(size: int, color=BLACK, round_=False) -> Image.Image:
    """Small B (the site's 14 x 14 sprite) on a 20 x 20 grid that survives Discord's 40-48 px display."""
    a = art(20, 20, None if round_ else color)
    if round_:
        ring(a, 10, 10, 0, 10, color)
    put(a, "b", 3, 3)
    return enlarge(a, size // 20, (size, size), pad=None if round_ else color)


def emoji(size: int, bg=None) -> Image.Image:
    a = art(16, 16, bg)
    put(a, "b", 1, 1)
    return enlarge(a, size // 16, (size, size))


def seal(dark: bool = True, k: int = 4) -> Image.Image:
    """Round official seal on a 256 x 256 art grid (k=4 -> 1024 px, k=1 -> 256 px)."""
    N, m = 256, 128
    fill, ink = (CHARCOAL, CREAM) if dark else (CREAM, BLACK)
    a = art(N, N)
    ring(a, m, m, 0, 117.3, fill)
    ring(a, m, m, 117.3, 124.7, GOLD)
    ring(a, m, m, 124.7, 128, BLACK)
    ring(a, m, m, 108, 109.6, GOLD)
    ring(a, m, m, 70.7, 72.3, GOLD)
    rect(a, 14, 127, 3, 3, GOLD)
    rect(a, 239, 127, 3, 3, GOLD)
    put(a, B86(), m - len(B86()[0]) // 2, m - len(B86()) // 2)
    _arc_text(a, "BEER LEAGUE HOCKEY ASSOCIATION", m, 94.5, ink, top=True)
    _arc_text(a, "OFFICIAL • EST. 2026", m, 95, ink, top=False)
    return a if k == 1 else enlarge(a, k, (N * k, N * k))


def _arc_text(img, text, c, r, color, top=True, size=24, gap=1.0):
    """Text around a circle, each letter rotated and re-thresholded so it stays solid pixels."""
    f = ImageFont.truetype(str(FONTS / "jersey10" / "Jersey10-Regular.ttf"), size)
    widths = [f.getlength(ch) for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    pos = -total / 2
    tint = Image.new("RGBA", (64, 64), color + (255,))
    for ch, w in zip(text, widths):
        th = (pos + w / 2) / r
        pos += w + gap
        if ch == " ":
            continue
        tile = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(tile).text((32, 32), ch, font=f, fill=255, anchor="mm")
        if top:
            tile = tile.rotate(-math.degrees(th), resample=Image.BICUBIC)
            px, py = c + r * math.sin(th), c - r * math.cos(th)
        else:
            tile = tile.rotate(math.degrees(th), resample=Image.BICUBIC)
            px, py = c + r * math.sin(th), c + r * math.cos(th)
        tile = tile.point(lambda v: 255 if v >= 128 else 0)
        img.paste(tint, (round(px - 32), round(py - 32)), tile)


STAMP_W, STAMP_H = 115, 46


def stamp(word: str, color, sub: str | None = None, seed: int = 1) -> Image.Image:
    """916 x 368 transparent status stamp: stepped double frame with a little ink wear."""
    a = art(STAMP_W, STAMP_H)
    frame(a, 2, 2, 111, 42, 2, 3, color, wear=.04, seed=seed)
    frame(a, 5, 5, 105, 36, 1, 2, color)
    img = enlarge(a, 8, (916, 368))
    avail = 90 * 8
    jersey = font("jersey")
    fp = next(s for s in range(8 if sub else 10, 2, -1) if jersey.width(word, s) <= avail)
    if sub:
        sfp = next(s for s in (4, 3, 2) if font("silk").width(sub, s) <= avail - 32)
        gap = 28
        block = 10 * fp + gap + 5 * sfp
        top = (368 - block) // 2
        draw_text(img, word, "jersey", fp, 458, top, color, align="c")
        draw_text(img, sub, "silk", sfp, 458, top + 10 * fp + gap, color, align="c")
    else:
        draw_text(img, word, "jersey", fp, 458, 184 - 5 * fp, color, align="c")
    return img


# ---------------------------------------------------------------- contact sheets
def contact_sheet(title: str, groups, size: tuple[int, int], max_w=480, max_h=300) -> Image.Image:
    """Grid of thumbnails with Silkscreen labels; pixel art is shrunk by whole factors with NEAREST."""
    W, H = size
    sheet = Image.new("RGBA", size, BLACK + (255,))
    draw_text(sheet, title, "jersey", 4, 30, 30, PAPER)
    y = 30 + 40 + 34
    for group, items in groups:
        draw_text(sheet, group, "silk-bold", 3, 30, y, GOLD)
        y += 15 + 22
        x, rowh = 30, 0
        for name, im in items:
            f = max(1, math.ceil(max(im.width / max_w, im.height / max_h)))
            t = im.convert("RGBA").resize((max(1, im.width // f), max(1, im.height // f)), Image.NEAREST)
            if t.getextrema()[3][0] < 255:  # transparent asset: show it on a checkerboard
                light = _mostly_dark(t)
                tile = Image.new("RGBA", t.size, (CREAM if light else CHARCOAL) + (255,))
                _checker(tile, CREAM_DKR if light else CHAR_DK)
                tile.alpha_composite(t)
                t = tile
            cell = max(t.width, 200)
            lines = _wrap_label(name, cell)
            h = t.height + 8 + 16 * len(lines)
            if x + cell > W - 30:
                x, y, rowh = 30, y + rowh + 28, 0
            sheet.alpha_composite(t, (x, y))
            for i, line in enumerate(lines):
                draw_text(sheet, line, "silk", 2, x, y + t.height + 8 + 16 * i, CREAM)
            x += cell + 24
            rowh = max(rowh, h)
        y += rowh + 52
    if y > H:
        raise ValueError(f"contact sheet needs {y} px but is {H} px tall")
    return sheet


def _wrap_label(name: str, width: int, scale: int = 2) -> list[str]:
    """Break a file name after hyphens so each line fits `width` pixels."""
    silk, lines, cur = font("silk"), [], ""
    for part in [p + "-" for p in name.split("-")[:-1]] + [name.split("-")[-1]]:
        if cur and silk.width(cur + part, scale) > width:
            lines.append(cur)
            cur = ""
        cur += part
    return lines + [cur]


def _checker(tile: Image.Image, color=CHAR_DK, cell: int = 8):
    d = ImageDraw.Draw(tile)
    for y in range(0, tile.height, cell):
        for x in range(0, tile.width, cell):
            if (x // cell + y // cell) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=color + (255,))


def _mostly_dark(img: Image.Image) -> bool:
    """True when most opaque pixels are dark (a black wordmark needs a light backdrop)."""
    lum = img.convert("L").load()
    alpha = img.getchannel("A").load()
    dark = total = 0
    for y in range(0, img.height, 2):
        for x in range(0, img.width, 2):
            if alpha[x, y] > 128:
                total += 1
                dark += lum[x, y] < 60
    return total > 0 and dark / total > .4


def save(path: Path, img: Image.Image, mode: str = "RGBA") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert(mode).save(path, "PNG", optimize=True)
