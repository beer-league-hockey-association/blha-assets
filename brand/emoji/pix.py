"""Tiny pixel-art kit for the BLHA Discord emoji: a 32 x 32 canvas, shape helpers, an automatic
black keyline, and exporters for 128 x 128 PNG (static) and GIF (animated) emoji.

Colours are one-letter keys (see PAL) or RGB tuples. Every emoji is drawn on 32 x 32 art pixels and
enlarged x4 with nearest-neighbour, so each art pixel is a hard 4 x 4 square.
"""
from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZE, SCALE = 32, 4
PAL = {
    "K": (14, 15, 18),     # black keyline
    "A": (43, 45, 49),     # charcoal
    "M": (58, 61, 66),     # mid charcoal
    "N": (110, 116, 124),  # steel dark
    "S": (154, 161, 169),  # steel
    "W": (252, 252, 252),  # paper white
    "C": (244, 239, 228),  # cream
    "I": (238, 245, 250),  # ice
    "L": (127, 183, 240),  # light blue
    "B": (36, 87, 197),    # blue
    "b": (47, 111, 219),   # rink blue
    "G": (255, 184, 28),   # gold
    "Y": (255, 215, 106),  # gold light
    "D": (198, 138, 0),    # gold dark
    "R": (200, 36, 31),    # red
    "r": (255, 106, 74),   # light red / LED
    "F": (255, 138, 30),   # flame orange
    "E": (63, 163, 77),    # green (emoji-only: money, stonks, go)
    "e": (127, 209, 139),  # light green
    "O": (184, 118, 58),   # wood
    "o": (138, 84, 38),    # wood dark
    "P": (242, 160, 180),  # pink
    "V": (122, 79, 192),   # violet
}


def col(c):
    if c is None:
        return None
    if isinstance(c, str):
        return PAL[c] + (255,)
    return tuple(c) + ((255,) if len(c) == 3 else ())


class Canvas:
    def __init__(self, w: int = SIZE, h: int = SIZE):
        self.img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.w, self.h = w, h

    # --- pixels and shapes -----------------------------------------------------------
    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.img.putpixel((int(x), int(y)), col(c) if c is not None else (0, 0, 0, 0))

    def get(self, x, y):
        return self.img.getpixel((x, y)) if 0 <= x < self.w and 0 <= y < self.h else (0, 0, 0, 0)

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.px(xx, yy, c)

    def frame(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c); self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c); self.rect(x + w - 1, y, 1, h, c)

    def line(self, x0, y0, x1, y1, c, width: int = 1):
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            for ox in range(width):
                for oy in range(width):
                    self.px(x0 + ox, y0 + oy, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def ellipse(self, cx, cy, rx, ry, c, fill=True):
        """Pixel-centred ellipse: cx, cy may be .5 for even sizes."""
        for y in range(self.h):
            for x in range(self.w):
                d = ((x + .5 - cx - .5) / (rx + .5)) ** 2 + ((y + .5 - cy - .5) / (ry + .5)) ** 2
                if d <= 1 and (fill or d >= ((max(rx, 1) - .5) / (rx + .5)) ** 2):
                    self.px(x, y, c)

    def circle(self, cx, cy, r, c, fill=True):
        self.ellipse(cx, cy, r, r, c, fill)

    def poly(self, pts, c):
        """Filled polygon, no anti-aliasing (corner points are art-pixel coordinates)."""
        mask = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in pts], fill=255)
        for y in range(self.h):
            for x in range(self.w):
                if mask.getpixel((x, y)):
                    self.px(x, y, c)

    def stamp(self, rows, x=0, y=0, pal=None):
        """Draw a character map ('.' or ' ' transparent). pal maps extra letters to colours."""
        p = dict(pal or {})
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch in ". ":
                    continue
                self.px(x + i, y + j, p.get(ch, ch))

    def text(self, x, y, s, c, font="3x5", gap=1):
        f = FONTS[font]
        for ch in s.upper():
            g = f.get(ch)
            if g is None:
                x += 2
                continue
            for j, row in enumerate(g):
                for i, b in enumerate(row):
                    if b == "#":
                        self.px(x + i, y + j, c)
            x += len(g[0]) + gap
        return x

    def text_width(self, s, font="3x5", gap=1):
        f = FONTS[font]
        return sum((len(f[ch][0]) if ch in f else 1) + gap for ch in s.upper()) - gap

    def outline(self, c="K", diagonal=False):
        """Add a 1-pixel keyline on every transparent pixel touching a coloured one."""
        src = self.img.copy()
        nb = [(1, 0), (-1, 0), (0, 1), (0, -1)] + ([(1, 1), (1, -1), (-1, 1), (-1, -1)] if diagonal else [])
        for y in range(self.h):
            for x in range(self.w):
                if src.getpixel((x, y))[3]:
                    continue
                if any(0 <= x + dx < self.w and 0 <= y + dy < self.h and src.getpixel((x + dx, y + dy))[3]
                       for dx, dy in nb):
                    self.px(x, y, c)
        return self

    def copy(self):
        c = Canvas(self.w, self.h)
        c.img = self.img.copy()
        return c

    def paste(self, other, x=0, y=0):
        self.img.alpha_composite(other.img, (int(x), int(y))) if 0 <= x and 0 <= y else self._paste_clip(other, x, y)

    def _paste_clip(self, other, x, y):
        for j in range(other.h):
            for i in range(other.w):
                p = other.img.getpixel((i, j))
                if p[3]:
                    self.px(x + i, y + j, p[:3])

    def flip(self):
        self.img = self.img.transpose(Image.FLIP_LEFT_RIGHT)
        return self

    def big(self):
        return self.img.resize((self.w * SCALE, self.h * SCALE), Image.NEAREST)


# --- export -------------------------------------------------------------------------------
def save_png(canvas: Canvas, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.big().save(path, optimize=True)
    assert path.stat().st_size < 256 * 1024, path


def save_gif(frames, path, durations=100):
    """Frames are Canvas objects (32 x 32). durations: one number (ms) or one per frame.
    Writes a looping GIF at 128 x 128 with a transparent background."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bigs = [f.big() for f in frames]
    colours = []
    for im in bigs:
        for c in im.getdata():
            if c[3] and c[:3] not in colours:
                colours.append(c[:3])
    assert len(colours) <= 255, f"{path.name}: {len(colours)} colours"
    palette = [(0, 0, 0)] + colours   # index 0 is transparent
    index = {c: i for i, c in enumerate(palette)}
    flat = [v for c in palette for v in c] + [0] * (768 - 3 * len(palette))
    out = []
    for im in bigs:
        p = Image.new("P", im.size, 0)
        p.putpalette(flat)
        p.putdata([index[c[:3]] if c[3] else 0 for c in im.getdata()])
        p.info["transparency"] = 0
        out.append(p)
    if isinstance(durations, (int, float)):
        durations = [int(durations)] * len(out)
    out[0].save(path, save_all=True, append_images=out[1:], duration=list(durations), loop=0,
                transparency=0, disposal=2, optimize=False)
    assert path.stat().st_size < 256 * 1024, f"{path.name}: {path.stat().st_size} bytes"


def sheet(paths, out, cols=8, label=True):
    """Contact sheet: each emoji on Discord dark and light backgrounds; GIFs show every frame in a strip."""
    paths = [Path(p) for p in paths]
    cell = 150
    rows = []
    for p in paths:
        im = Image.open(p)
        frames = []
        try:
            while True:
                frames.append(im.convert("RGBA").copy())
                im.seek(im.tell() + 1)
        except EOFError:
            pass
        rows.append((p.stem, frames))
    strip = max(len(f) for _, f in rows)
    if strip > 1:   # animated: one row per emoji showing all frames (dark) + first frame on light
        W, H = (strip + 1) * 70 + 160, len(rows) * 74 + 10
        sh = Image.new("RGB", (W, H), (49, 51, 56))
        d = ImageDraw.Draw(sh)
        for r, (name, frames) in enumerate(rows):
            y = 6 + r * 74
            d.text((6, y + 28), name, fill=(220, 220, 220))
            light = Image.new("RGBA", (68, 68), (255, 255, 255, 255))
            light.alpha_composite(frames[0].resize((64, 64), Image.NEAREST), (2, 2))
            sh.paste(light.convert("RGB"), (150, y))
            for i, f in enumerate(frames):
                sh.paste(f.resize((64, 64), Image.NEAREST), (222 + i * 70, y), f.resize((64, 64), Image.NEAREST))
        sh.save(out)
        return
    n = len(rows)
    W, H = cols * cell, ((n + cols - 1) // cols) * (cell + 16)
    sh = Image.new("RGB", (W, H), (49, 51, 56))
    d = ImageDraw.Draw(sh)
    for i, (name, frames) in enumerate(rows):
        x, y = (i % cols) * cell, (i // cols) * (cell + 16)
        f = frames[0]
        sh.paste(f, (x + 4, y + 4), f)
        light = Image.new("RGBA", (36, 36), (255, 255, 255, 255))
        light.alpha_composite(f.resize((32, 32), Image.NEAREST), (2, 2))
        sh.paste(light.convert("RGB"), (x + 108, y + 4))
        dark = Image.new("RGBA", (24, 24), (49, 51, 56, 255))
        dark.alpha_composite(f.resize((22, 22), Image.LANCZOS), (1, 1))
        sh.paste(dark.convert("RGB"), (x + 114, y + 46))
        if label:
            d.text((x + 4, y + cell - 12), name, fill=(220, 220, 220))
    sh.save(out)


# --- fonts ----------------------------------------------------------------------------------
_F35 = {
    "A": ["###", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."], "C": ["###", "#..", "#..", "#..", "###"],
    "D": ["##.", "#.#", "#.#", "#.#", "##."], "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": ["###", "#..", "#.#", "#.#", "###"], "H": ["#.#", "#.#", "###", "#.#", "#.#"], "I": ["###", ".#.", ".#.", ".#.", "###"],
    "J": ["..#", "..#", "..#", "#.#", "###"], "K": ["#.#", "#.#", "##.", "#.#", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#.#", "###", "###", "#.#", "#.#"], "N": ["##.", "#.#", "#.#", "#.#", "#.#"], "O": ["###", "#.#", "#.#", "#.#", "###"],
    "P": ["###", "#.#", "###", "#..", "#.."], "Q": ["###", "#.#", "#.#", "###", "..#"], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": ["###", "#..", "###", "..#", "###"], "T": ["###", ".#.", ".#.", ".#.", ".#."], "U": ["#.#", "#.#", "#.#", "#.#", "###"],
    "V": ["#.#", "#.#", "#.#", "#.#", ".#."], "W": ["#.#", "#.#", "###", "###", "#.#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "Z": ["###", "..#", ".#.", "#..", "###"],
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#", "##", ".#", ".#", ".#"], "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", "###", "..#", "###"], "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"], "7": ["###", "..#", "..#", "..#", "..#"], "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"], "!": ["#", "#", "#", ".", "#"], "?": ["###", "..#", ".##", "...", ".#."],
    ".": ["."] * 4 + ["#"], ":": [".", "#", ".", "#", "."], "$": [".#.", "###", "##.", ".##", "###"], "+": ["...", ".#.", "###", ".#.", "..."],
    "-": ["...", "...", "###", "...", "..."], "%": ["#.#", "..#", ".#.", "#..", "#.#"], "'": ["#", "#", ".", ".", "."],
}
FONTS = {"3x5": _F35}


# --- shared pieces so every emoji reads as one family ----------------------------------------
def face(c: Canvas | None = None, cx: float = 15.5, cy: float = 15.5, r: int = 13) -> Canvas:
    """The league's emoji face: a gold disc with a light top-left and a darker lower-right rim.
    Draw eyes and mouth on top, then call outline() once at the end."""
    c = c or Canvas()
    c.circle(cx, cy, r, "D")
    c.circle(cx - 1, cy - 1, r - 1, "G")
    for (dx, dy) in ((-6, -8), (-7, -7), (-8, -6), (-5, -9)):
        c.px(int(cx + .5) + dx, int(cy + .5) + dy, "Y")
    return c


def player(c: Canvas, x: int, y: int, jersey="G", trim="K", flip=False) -> Canvas:
    """A 10 x 14 skater (helmet, visor, jersey with stripe, black pants, skates) with its top-left at x, y.
    League players wear gold (G) with black trim; opponents wear blue (B) with white (W) trim."""
    rows = [
        "...KKKK...",
        "..KMMMMK..",
        "..KMLLMK..",
        "...KKKK...",
        ".KJJJJJJK.",
        "KJJJJJJJJK",
        "KJTTTTTTJK",
        "KJJJJJJJJK",
        ".KJJJJJJK.",
        ".KKKKKKKK.",
        ".KAAKKAAK.",
        ".KAAK.KAK.",
        ".KSSK.KSSK",
        "KKKKK.KKKK",
    ]
    if flip:
        rows = [r[::-1] for r in rows]
    c.stamp(rows, x, y, {"J": jersey, "T": trim})
    return c
