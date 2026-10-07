#!/usr/bin/env python3
"""BLHA animated emoji, group anim_a (25 GIFs).

    python3 anim_a.py            # writes animated/blha_<name>.gif for all 25 + anim_a_sheet.png
    python3 anim_a.py goal fire  # just those (no sheet)

Everything is drawn on the 32 x 32 pix.Canvas and exported x4. Deterministic (seeded RNGs only).
Layering rule: a base scene gets one outline(); anything that must read *on top of* other art
(a puck over a net, tears over a face) is drawn on its own layer, outlined once, then blitted, so
every shape keeps exactly one 1-px keyline.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pix  # noqa: E402
from pix import Canvas  # noqa: E402
from PIL import Image  # noqa: E402

OUT = HERE / "animated"


# =============================================================================================
# helpers
# =============================================================================================
def blit(dst: Canvas, src: Canvas, x: int = 0, y: int = 0):
    data = src.img.load()
    for j in range(src.h):
        for i in range(src.w):
            p = data[i, j]
            if p[3]:
                dst.px(x + i, y + j, p[:3])


def layer(fn) -> Canvas:
    """Draw with fn on a fresh 32 x 32 layer and give it its own keyline."""
    L = Canvas()
    fn(L)
    L.outline()
    return L


def sprite(rows, pal=None) -> Canvas:
    c = Canvas(max(len(r) for r in rows), len(rows))
    c.stamp(rows, 0, 0, pal)
    return c


def rot(dst: Canvas, src: Canvas, ax, ay, sx, sy, deg):
    """Nearest-neighbor rotate src (clockwise on screen for deg > 0) so that the source point
    (sx, sy) lands on the destination point (ax, ay)."""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    data = src.img.load()
    R = int(math.hypot(src.w, src.h)) + 2
    for y in range(int(ay) - R, int(ay) + R + 1):
        if not 0 <= y < dst.h:
            continue
        for x in range(int(ax) - R, int(ax) + R + 1):
            if not 0 <= x < dst.w:
                continue
            dx, dy = x + .5 - ax, y + .5 - ay
            u = dx * ca + dy * sa + sx
            v = -dx * sa + dy * ca + sy
            iu, iv = math.floor(u), math.floor(v)
            if 0 <= iu < src.w and 0 <= iv < src.h:
                p = data[iu, iv]
                if p[3]:
                    dst.px(x, y, p[:3])


def rotp(px_, py_, ox, oy, deg):
    """Rotate point about (ox, oy), clockwise on screen for deg > 0."""
    a = math.radians(deg)
    dx, dy = px_ - ox, py_ - oy
    return ox + dx * math.cos(a) - dy * math.sin(a), oy + dx * math.sin(a) + dy * math.cos(a)


def puck(c: Canvas, x, y, w=6, h=2):
    """Side-on / head-on puck: steel-dark face over a charcoal edge, with a glint."""
    x, y = int(round(x)), int(round(y))
    if h >= 3:
        c.rect(x + 1, y, w - 2, 1, "N")
        c.rect(x, y + 1, w, 1, "N")
        c.rect(x, y + 2, w, 1, "M")
        c.px(x + 1, y + 1, "S")
        return
    c.rect(x, y, w, 1, "N")
    c.rect(x, y + 1, w, h - 1, "M")
    if w >= 3:
        c.px(x + 1, y, "S")


def mesh(c: Canvas, x0, y0, x1, y1, fill="A", line="S", step=4, warp=None):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            u = x if warp is None else warp(x, y)
            c.px(x, y, line if ((u + y) % step == 0 or (u - y) % step == 0) else fill)


def sparkle(c: Canvas, x, y, r=1, colr="W", core=None):
    c.px(x, y, core or colr)
    for i in range(1, r + 1):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c.px(x + dx * i, y + dy * i, colr)


def star(c: Canvas, x, y, r, inner="W", outer="Y", diag=True):
    """Impact burst: a plus with longer straight rays and shorter diagonals."""
    c.rect(x - 1, y - 1, 3, 3, inner)
    for i in range(2, r + 1):
        col_ = inner if i <= r // 2 else outer
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c.px(x + dx * i, y + dy * i, col_)
    if diag:
        for i in range(2, max(2, r - 1)):
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                c.px(x + dx * i, y + dy * i, outer)


def drop(c: Canvas, x, y, size=1):
    """Teardrop (point up) in light blue with a white glint; fills only (outline adds the keyline).
    size 0: 2 x 3, size 1: 3 x 4, size 2: 5 x 7. (x, y) = top-left."""
    if size == 0:
        c.px(x, y, "L"); c.px(x + 1, y, "L")
        c.px(x, y + 1, "W"); c.px(x + 1, y + 1, "L")
        c.px(x, y + 2, "L"); c.px(x + 1, y + 2, "L")
        return
    if size == 1:
        c.stamp([".L.", "LLL", "WLL", "LLB"], x, y)
        return
    c.stamp(["..L..", ".LLL.", ".LLL.", "LLLLL", "LWLLL", "LWLLB", ".LLB."], x, y)


def speed_lines(c: Canvas, x_end, ys, lengths, colr="W"):
    """Horizontal dashes ending at x_end (trailing to the left)."""
    for y, n in zip(ys, lengths):
        c.rect(x_end - n + 1, y, n, 1, colr)


def finish(c: Canvas, *layers: Canvas) -> Canvas:
    c.outline()
    for L in layers:
        blit(c, L)
    return c


# =============================================================================================
# 1. zamboni: resurfacer drives across, ice behind it turns glossy, exits and re-enters
# =============================================================================================
def zamboni():
    rng = random.Random(3)
    Y0, H = 25, 5
    rough = {(x, y): "S" for x in range(1, 31) for y in range(Y0, Y0 + H)}
    for _ in range(22):
        x, y, n = rng.randint(1, 29), rng.randint(Y0, Y0 + H - 1), rng.randint(2, 3)
        for i in range(n):
            if (x + i, y) in rough:
                rough[(x + i, y)] = "I" if y > Y0 else "C"

    def ice(c, gx):
        for (x, y), v in rough.items():
            if x < gx:
                v = "I"
                if y == Y0 + 2 and x % 5:
                    v = "L"
                if (x + (y - Y0)) % 7 == 0 and y < Y0 + 4:
                    v = "W"
            c.px(x, y, v)

    def machine(c, x0, f):
        c.rect(x0 - 7, 23, 6, 2, "B")                       # towel dragging on the ice
        c.rect(x0 - 7, 23, 6, 1, "L")
        c.rect(x0 - 2, 16, 2, 8, "N"); c.rect(x0 - 2, 16, 1, 8, "S")   # conditioner
        c.rect(x0, 12, 16, 10, "W")                         # body
        c.rect(x0, 17, 16, 1, "B")
        c.rect(x0, 21, 16, 1, "S")
        c.px(x0 + 15, 12, None)
        c.rect(x0, 9, 10, 3, "B"); c.rect(x0 + 1, 9, 8, 1, "L")       # snow-tank lid
        c.rect(x0 + 11, 9, 3, 3, "G")                       # driver: gold jacket
        c.rect(x0 + 11, 6, 3, 3, "C"); c.px(x0 + 13, 7, "K")
        c.rect(x0 + 11, 5, 3, 1, "R"); c.px(x0 + 12, 4, "R")
        c.rect(x0 + 14, 9, 2, 1, "A"); c.px(x0 + 15, 10, "A"); c.px(x0 + 15, 11, "A")
        for wx in (x0 + 3, x0 + 12):
            c.circle(wx, 22, 2, "A")
            c.px(wx, 22, "S")
            if f % 2:
                c.px(wx - 1, 22, "N"); c.px(wx + 1, 22, "N")
            else:
                c.px(wx, 21, "N"); c.px(wx, 23, "N")

    frames, durs = [], []
    for f, x0 in enumerate(range(-6, 36, 4)):
        c = Canvas()
        ice(c, x0 - 7)
        machine(c, x0, f)
        frames.append(finish(c)); durs.append(80)
    for spots in ([(7, 22, 1), (20, 21, 2)], [(13, 21, 2), (26, 22, 1)]):
        c = Canvas()
        ice(c, 40)
        for x, y, r in spots:
            sparkle(c, x, y, r)
        frames.append(finish(c)); durs.append(130)
    return frames, durs


# =============================================================================================
# 2. goal: puck flies into the net (side view), the back twine bulges, the net settles
# =============================================================================================
NET_FILL, NET_LINE = "I", "S"


def goal():
    def xr0(y):
        return 15 + 10 * math.sqrt(max(0.0, 1 - ((26 - y) / 19) ** 2))

    def scene(b):
        c = Canvas()
        c.rect(1, 27, 30, 3, "I")
        for x in (2, 13, 23):
            c.rect(x, 28, 3, 1, "S")
        c.rect(7, 27, 2, 3, "R")                       # goal line under the post
        for y in range(8, 26):
            base = xr0(y)
            xr = base + b * math.exp(-((y - 17) / 4.5) ** 2)
            for x in range(9, int(round(xr)) + 1):
                u = int(round(9 + (x - 9) * (base - 9) / max(1.0, xr - 9)))
                on = (u + y) % 4 == 0 or (u - y) % 4 == 0
                c.px(x, y, NET_LINE if on else NET_FILL)
        pts = [(int(round(xr0(y))), y) for y in range(7, 27)]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            c.line(xa, ya, xb, yb, "R")
        c.rect(7, 7, 9, 1, "R")
        c.rect(7, 26, 19, 1, "R")
        c.rect(7, 7, 2, 20, "R"); c.rect(7, 7, 1, 20, "r")
        return c

    keys = [
        (0, (-3, 16), 1), (0, (3, 16), 1), (0, (9, 16), 1), (0, (15, 16), 1),
        (2.5, (20, 16), 0), (5, (24, 16), 0), (3, (22, 18), 0), (0, (20, 21), 0),
        (-1.5, (19, 24), 0), (1, (19, 24), 0), (0, (19, 24), 2), (0, (19, 24), 3),
    ]
    durs = [70, 70, 70, 70, 80, 120, 90, 90, 90, 100, 130, 130]
    frames = []
    for b, (px_, py_), extra in keys:
        c = scene(b)

        def ov(L, px_=px_, py_=py_, extra=extra):
            puck(L, px_, py_, 5)
            if extra == 1:
                speed_lines(L, px_ - 2, [py_ - 1, py_ + 2], [5, 3])
            if extra == 2:
                L.px(px_ + 1, py_, "W")
        frames.append(finish(c, layer(ov)))
    return frames, durs


# =============================================================================================
# 3. snipe: crosshair closes on a top-corner target, locks, puck pings through
# =============================================================================================
def snipe():
    TX, TY = 9, 12

    def scene():
        c = Canvas()
        c.rect(1, 27, 30, 3, "I")
        mesh(c, 4, 7, 27, 26, NET_FILL, NET_LINE)
        c.rect(2, 5, 28, 2, "R"); c.rect(2, 5, 28, 1, "r")
        c.rect(2, 5, 2, 22, "R"); c.rect(28, 5, 2, 22, "R")
        c.rect(2, 5, 1, 22, "r"); c.rect(28, 5, 1, 22, "r")
        return c

    def target(L, hole=False, flash=False):
        L.circle(TX, TY, 4, "W" if flash else "R")
        L.circle(TX, TY, 3, "W")
        L.circle(TX, TY, 2, "W" if flash else "R")
        L.circle(TX, TY, 1, "W")
        L.px(TX, TY, "K" if hole else "R")

    def brackets(L, cx, cy, hs, colr, ticks=False):
        x0, y0 = int(round(cx - hs)), int(round(cy - hs))
        x1, y1 = int(round(cx + hs)), int(round(cy + hs))
        for (x, y, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            for i in range(3):
                L.px(x + sx * i, y, colr); L.px(x, y + sy * i, colr)
        if ticks:
            mx, my = (x0 + x1) // 2, (y0 + y1) // 2
            L.px(mx, y0 - 1, colr); L.px(mx, y1 + 1, colr); L.px(x0 - 1, my, colr); L.px(x1 + 1, my, colr)

    track = [(15.5, 15.5, 14), (14, 14.5, 12), (12, 13.5, 10), (10.5, 12.5, 8.5), (9.5, 12, 7.5)]
    frames, durs = [], []
    for cx, cy, hs in track:
        c = scene()
        frames.append(finish(c, layer(target), layer(lambda L, a=(cx, cy, hs): brackets(L, *a, "W"))))
        durs.append(90)
    # lock: snap tight, gold flash then red
    for hs, d in ((5, 100), (6, 120)):
        c = scene()
        frames.append(finish(c, layer(target), layer(lambda L, h=hs: brackets(L, TX, TY, h, "Y", True))))
        durs.append(d)
    # puck flies from the shooter into the corner
    for (x, y, w, h) in ((14, 26, 7, 3), (11, 18, 5, 2)):
        c = scene()
        frames.append(finish(c, layer(target), layer(lambda L: brackets(L, TX, TY, 6, "Y", True)),
                             layer(lambda L, a=(x, y, w, h): puck(L, *a))))
        durs.append(60)
    # ping
    c = scene()
    frames.append(finish(c, layer(lambda L: target(L, True, True)), layer(lambda L: star(L, TX, TY, 5))))
    durs.append(90)
    c = scene()

    def ring(L):
        for a in range(0, 360, 30):
            r = 8
            L.px(TX + round(r * math.cos(math.radians(a))), TY + round(r * math.sin(math.radians(a))), "Y")
    frames.append(finish(c, layer(lambda L: target(L, True)), layer(ring)))
    durs.append(100)
    for vis in (True, False, True):
        c = scene()
        ls = [layer(lambda L: target(L, True))]
        if vis:
            ls.append(layer(lambda L: brackets(L, TX, TY, 6, "Y", True)))
        frames.append(finish(c, *ls))
        durs.append(130)
    return frames, durs


# =============================================================================================
# 4. bardown: puck clangs the crossbar (spark + ping lines), drops straight down over the line
# =============================================================================================
def bardown():
    def scene(shake=0, glint=None):
        c = Canvas()
        c.rect(1, 23, 30, 7, "I")                          # net floor + ice
        c.rect(1, 25, 30, 2, "R")                          # goal line
        for x in (5, 16, 25):
            c.rect(x, 28, 3, 1, "S")
        mesh(c, 4, 10, 27, 22, NET_FILL, NET_LINE)
        c.rect(2, 6, 2, 20, "R"); c.rect(28, 6, 2, 20, "R")          # posts
        c.rect(2, 6, 1, 20, "r"); c.rect(28, 6, 1, 20, "r")
        c.rect(2, 6, 28, 4, "R"); c.rect(2, 6, 28, 1, "r")           # crossbar
        c.px(5, 6, "W"); c.px(6, 6, "W")
        if glint is not None:
            c.px(glint, 6, "W"); c.px(glint + 1, 6, "W")
        if shake:   # vibration ticks at the bar ends
            for x in (2, 29):
                c.px(x + (-1 if x < 16 else 1), 6 + (shake > 0), "r")
        return c

    def pings(L, stage):
        if stage == 0:
            L.rect(16, 2, 1, 2, "Y"); L.line(12, 3, 11, 2, "Y"); L.line(20, 3, 21, 2, "Y")
        elif stage == 1:
            L.rect(16, 0, 1, 3, "Y"); L.line(11, 3, 9, 1, "Y"); L.line(21, 3, 23, 1, "Y")
            L.line(6, 4, 4, 3, "Y"); L.line(26, 4, 28, 3, "Y")
        else:
            L.px(16, 0, "Y"); L.px(8, 1, "Y"); L.px(24, 1, "Y"); L.px(3, 3, "Y"); L.px(29, 3, "Y")

    def vib(L, k):   # wobble lines above and below the crossbar
        for x0 in (7, 21):
            L.rect(x0 + k, 4, 4, 1, "W")
            L.rect(x0 - k, 11, 4, 1, "W")

    seq = [
        dict(p=(18, 27, 7, 3)), dict(p=(17, 19, 6, 2)), dict(p=(15, 13, 5, 2)),
        dict(p=(14, 10, 5, 2), burst=5, ping=0, vib=1),
        dict(p=(14, 14, 5, 2), burst=2, ping=1, vib=-1, streak=True),
        dict(p=(14, 18, 5, 2), ping=2, vib=1, streak=True),
        dict(p=(14, 22, 5, 2), puff=True),
        dict(p=(14, 20, 5, 2)),
        dict(p=(14, 22, 5, 2)),
        dict(p=(14, 22, 5, 2), glint=10),
        dict(p=(14, 22, 5, 2), glint=17),
        dict(p=(14, 22, 5, 2), glint=24),
    ]
    durs = [60, 60, 60, 120, 90, 80, 90, 80, 100, 120, 120, 120]
    frames = []
    for s in seq:
        c = scene(s.get("vib", 0), s.get("glint"))

        def ov(L, s=s):
            x, y, w, h = s["p"]
            puck(L, x, y, w, h)
            if s.get("streak"):
                L.rect(x + 1, y - 4, 1, 3, "W"); L.rect(x + 3, y - 3, 1, 2, "W")
            if s.get("puff"):
                for q in ((x - 2, y + 1), (x + w + 1, y + 1), (x - 1, y), (x + w, y)):
                    L.px(*q, "W")
        ls = [layer(ov)]
        if "burst" in s:
            ls.append(layer(lambda L, r=s["burst"]: star(L, 16, 10, r)))
        if "ping" in s:
            ls.append(layer(lambda L, st=s["ping"]: pings(L, st)))
        if "vib" in s:
            ls.append(layer(lambda L, k=s["vib"]: vib(L, k)))
        frames.append(finish(c, *ls))
    return frames, durs


# =============================================================================================
# 5. topshelf: puck arcs onto a high shelf beside the cookie jar, which rocks
# =============================================================================================
def topshelf():
    def jar(tilt=0, lid=0, peek=False):
        j = Canvas()
        j.rect(17, 7, 11, 10, "I")                         # glass body
        j.px(17, 7, None); j.px(27, 7, None); j.px(17, 16, None); j.px(27, 16, None)
        for cx, cy in ((20, 14), (25, 14), (22, 10)):          # cookies inside
            j.circle(cx, cy, 2, "o")
            j.rect(cx - 1, cy - 1, 3, 3, "O")
            j.px(cx, cy, "o"); j.px(cx - 1, cy - 1, "C")
        j.rect(18, 8, 1, 7, "W")                           # glass glint
        j.rect(27, 8, 1, 8, "L")
        lx = 2 if peek else 0
        j.rect(18 + lx, 5 - lid, 9, 2, "N"); j.rect(18 + lx, 5 - lid, 9, 1, "S")   # lid + knob
        j.rect(21 + lx, 3 - lid, 3, 2, "S")
        if peek:
            j.circle(21, 5, 2, "o"); j.rect(20, 4, 3, 3, "O"); j.px(21, 5, "o"); j.px(20, 4, "C")
        out = Canvas()
        data = j.img.load()
        for y in range(32):
            sh = 0
            if tilt:
                sh = tilt if y < 9 else (tilt // abs(tilt) if abs(tilt) > 1 and y < 12 else 0)
            for x in range(32):
                p = data[x, y]
                if p[3]:
                    out.px(x + sh, y, p[:3])
        return out

    def shelf(c):
        c.rect(2, 17, 29, 1, "O"); c.rect(2, 18, 29, 1, "o")
        for bx in (5, 26):
            c.rect(bx, 19, 2, 3, "o"); c.px(bx + (1 if bx < 16 else 0), 22, "o")

    path = [(1, 27), (2, 19), (4, 12), (6, 7), (8, 6), (9, 9), (10, 15)]
    frames, durs = [], []
    for i, (x, y) in enumerate(path):
        c = Canvas()
        shelf(c)
        blit(c, jar())

        def ov(L, i=i, x=x, y=y):
            puck(L, x, y, 6)
            if 0 < i < 6:
                px0, py0 = path[i - 1]
                L.px(px0 + 2, py0 + 1, "W")
        frames.append(finish(c, layer(ov)))
        durs.append(70 if i < 6 else 80)
    for tilt, lid, d, crumbs, peek in ((2, 2, 90, True, False), (-2, 4, 110, False, True), (1, 1, 90, False, False),
                                       (-1, 1, 100, False, False), (0, 0, 120, False, False), (0, 0, 120, None, False)):
        c = Canvas()
        shelf(c)
        blit(c, jar(tilt, lid, peek))
        puck(c, 10, 15, 6)
        if crumbs:
            c.px(9, 14, "W"); c.px(17, 14, "W"); c.px(8, 15, "W")
        if crumbs is None:
            c.px(20, 1, "W")
        frames.append(finish(c)); durs.append(d)
    return frames, durs


# =============================================================================================
# 6. fivehole: pads open, puck slides through the gap, pads slam shut too late
# =============================================================================================
PAD_ROWS = [
    ".WWWWW.",
    "WWWWWWW",
    "WBBBBBW",
    "WWWWWWW",
    "WWSSSWW",
    "WWWWWWW",
    "WBBBBBW",
    "WWWWWWW",
    "WWWWWWW",
    "WBBBBBW",
    "WWWWWWW",
    "WWWWWWW",
    "WWWWWWW",
    ".WWWWW.",
]


def fivehole():
    pad = sprite(PAD_ROWS)

    def scene(ripple=0):
        c = Canvas()
        c.rect(1, 24, 30, 6, "I")
        c.rect(1, 25, 30, 1, "R")
        mesh(c, 3, 0, 28, 24, NET_FILL, NET_LINE)
        c.rect(1, 0, 2, 26, "R"); c.rect(29, 0, 2, 26, "R"); c.rect(1, 0, 1, 26, "r"); c.rect(29, 0, 1, 26, "r")
        if ripple:
            for a in range(0, 360, 45):
                c.px(16 + round(ripple * math.cos(math.radians(a))), 15 + round(ripple * .7 * math.sin(math.radians(a))), "W")
        return c

    def goalie(L, ang, slam=False):
        L.rect(8, 0, 16, 4, "B"); L.rect(8, 2, 16, 1, "W")          # jersey hem
        L.rect(9, 4, 14, 7, "B"); L.rect(9, 4, 14, 1, "b")          # pants
        L.rect(15, 8, 2, 3, "A")
        k = ang / 60.0
        for (x0, sgn) in ((9, -1), (16, 1)):
            d = pad.img.load()
            for j in range(pad.h):
                sh = int(round(sgn * j * k))
                for i in range(pad.w):
                    q = d[i, j]
                    if q[3]:
                        L.px(x0 + i + sh, 10 + j, q[:3])
        if slam:
            for x, y in ((7, 24), (6, 23), (25, 24), (26, 23), (16, 24)):
                L.px(x, y, "W")

    seq = [(26, (13, 28, 7, 3), 0), (26, (13, 24, 6, 2), 0), (26, (14, 20, 4, 2), 0), (26, (15, 17, 3, 1), 0),
           (26, None, 3), (12, None, 5), (0, None, 0), (0, None, 0), (0, None, 0)]
    durs = [80, 80, 80, 80, 90, 60, 100, 120, 120]
    frames = []
    for i, (ang, pk, rip) in enumerate(seq):
        c = scene(rip)
        ls = []
        if pk:
            ls.append(layer(lambda L, pk=pk: puck(L, *pk)))
        ls.append(layer(lambda L, a=ang, s=(i == 6): goalie(L, a, s)))
        if i == 7:
            ls.append(layer(lambda L: (L.px(28, 1, "W"))))
        if i == 8:
            ls.append(layer(lambda L: (L.px(4, 1, "W"))))
        frames.append(finish(c, *ls))
    return frames, durs


# =============================================================================================
# 7. dangle: blade toe-drags the puck side to side with motion lines
# =============================================================================================
def dangle():
    def ice(c):
        c.rect(1, 19, 30, 10, "I")
        for q in ((1, 19), (30, 19), (1, 28), (30, 28)):
            c.px(*q, None)
        for x, y in ((3, 21), (24, 27), (12, 27), (26, 21)):
            c.rect(x, y, 3, 1, "S")

    def frame(px_, mode, f):
        c = Canvas()
        ice(c)
        c.outline()
        L = Canvas()
        if mode:
            heel = px_ - 10 if mode > 0 else px_ + 10
            gx = int(round(16 + (heel - 16) * 0.25))
            L.line(gx, 3, heel, 21, "O", 2)
            L.rect(gx - 1, 1, 4, 4, "G"); L.rect(gx - 1, 4, 4, 1, "D")      # top glove
            bx0 = heel if mode > 0 else heel - 7
            L.rect(bx0, 21, 8, 3, "W")                                       # taped blade
            for k in range(1, 8, 2):
                L.rect(bx0 + k, 21, 1, 3, "N")
            toe = bx0 + 7 if mode > 0 else bx0
            L.px(toe, 20, "W")                                               # curled toe
            puck(L, px_ - 3, 22, 6, 3)
            for y, n in ((20, 6), (24, 4)):                                  # motion lines
                if mode > 0:
                    L.rect(bx0 - n - 2, y, n, 1, "L")
                else:
                    L.rect(bx0 + 10, y, n, 1, "L")
            # swish at the hands
            L.px(gx - 3 * mode, 2, "W"); L.px(gx - 4 * mode, 3, "W")
        else:   # blade rolls over the top of the puck
            gx = int(round(16 + (px_ - 16) * 0.25))
            L.line(gx, 3, px_, 16, "O", 2)
            L.rect(gx - 1, 1, 4, 4, "G"); L.rect(gx - 1, 4, 4, 1, "D")
            L.rect(px_ - 3, 17, 8, 2, "W")
            L.px(px_ - 1, 17, "S"); L.px(px_ + 2, 18, "S")
            puck(L, px_ - 3, 22, 6, 3)
            for x, y in ((px_ - 6, 21), (px_ + 6, 21), (px_ - 7, 19), (px_ + 7, 19)):
                L.px(x, y, "W")
        L.outline()
        blit(c, L)
        return c

    seq = [(12, 1), (15, 1), (18, 1), (21, 1), (22, 0), (21, -1), (18, -1), (15, -1), (12, -1), (11, 0)]
    return [frame(x, m, i) for i, (x, m) in enumerate(seq)], [70] * len(seq)


# =============================================================================================
# 8. slapshot: stick winds up high, swings through, puck rockets away
# =============================================================================================
def stick_sprite(gloves=True):
    s = Canvas(12, 20)
    s.rect(4, 0, 2, 18, "O"); s.rect(5, 0, 1, 18, "o")
    s.rect(4, 0, 2, 2, "W")
    s.rect(4, 17, 8, 2, "W")
    s.px(4, 18, "O"); s.px(5, 18, "O")
    for k in (7, 10):
        s.px(k, 17, "S"); s.px(k + 1, 18, "S")
    s.px(11, 17, None)
    if gloves:
        s.rect(3, 2, 4, 3, "G"); s.rect(3, 4, 4, 1, "D")
        s.rect(3, 8, 4, 3, "G"); s.rect(3, 10, 4, 1, "D")
    return s


def slapshot():
    stick = stick_sprite()
    PX, PY = 15, 9          # top-hand pivot
    SX, SY = 5.0, 3.5

    def scene(deg, puck_at=None, smear=None, impact=False, lines=0):
        c = Canvas()
        c.rect(1, 26, 30, 3, "I")
        for x in (3, 12, 24):
            c.rect(x, 27, 3, 1, "S")
        c.outline()
        L = Canvas()
        rot(L, stick, PX, PY, SX, SY, deg)
        L.outline()
        blit(c, L)
        top = Canvas()
        if smear:
            a0, a1 = smear
            for k in range(1, 6):
                a = a0 + (a1 - a0) * k / 6
                for r, colr in ((15, "W"), (13, "S")):
                    x, y = rotp(PX, PY + r, PX, PY, a)
                    top.px(int(round(x)), int(round(y)), colr)
        if puck_at:
            x, y = puck_at
            puck(top, x, y, 5)
            if lines:
                speed_lines(top, x - 2, [y - 2, y + 1, y + 3], [lines, lines + 4, lines - 2])
        if impact:
            star(top, 22, 24, 4)
        top.outline()
        blit(c, top)
        return c

    seq = [
        dict(deg=20), dict(deg=70), dict(deg=112), dict(deg=118),
        dict(deg=50, smear=(118, 50)), dict(deg=-8, smear=(50, -8), impact=True, puck=(21, 23)),
        dict(deg=-50, puck=(27, 19), lines=9), dict(deg=-62, lines=12, ghost=True),
        dict(deg=-64, lines=6, ghost=True), dict(deg=-45), dict(deg=-15),
    ]
    durs = [90, 90, 90, 130, 60, 80, 70, 80, 90, 100, 100]
    frames = []
    for s in seq:
        if "puck" in s:
            pk = s["puck"]
        elif s["deg"] > 0 and "smear" not in s:
            pk = (23, 24)
        elif "smear" in s:
            pk = (23, 24)
        else:
            pk = None
        if s.get("ghost"):
            c = scene(s["deg"])
            L = Canvas()
            n = s["lines"]
            speed_lines(L, 30, [16, 19, 21], [n, n + 4, n - 3])
            L.outline()
            blit(c, L)
        else:
            c = scene(s["deg"], pk, s.get("smear"), s.get("impact", False), s.get("lines", 0))
        frames.append(c)
    return frames, durs


# =============================================================================================
# 9. snapped: stick flexes on the shot and snaps in two, pieces flying
# =============================================================================================
def snapped():
    P0, P2 = (6.0, 3.0), (17.0, 24.0)
    BLADE = [(17.0, 24.0), (24.0, 24.0)]

    def bez(t, bow):
        mx, my = (P0[0] + P2[0]) / 2, (P0[1] + P2[1]) / 2
        dx, dy = P2[0] - P0[0], P2[1] - P0[1]
        n = math.hypot(dx, dy)
        nx, ny = -dy / n, dx / n                           # perpendicular, pointing down-left
        cx_, cy_ = mx + bow * nx, my + bow * ny
        x = (1 - t) ** 2 * P0[0] + 2 * (1 - t) * t * cx_ + t * t * P2[0]
        y = (1 - t) ** 2 * P0[1] + 2 * (1 - t) * t * cy_ + t * t * P2[1]
        return x, y

    def shaft(L, pts, colr="O"):
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            L.line(int(round(xa)), int(round(ya)), int(round(xb)), int(round(yb)), colr, 2)

    def blade(L, a, b):
        L.line(int(round(a[0])), int(round(a[1])), int(round(b[0])), int(round(b[1])), "W", 2)

    def gloves(L, p, q):
        for (x, y) in (p, q):
            L.rect(int(round(x)) - 1, int(round(y)) - 1, 4, 3, "G")
            L.rect(int(round(x)) - 1, int(round(y)) + 1, 4, 1, "D")

    def ice(c):
        c.rect(1, 26, 30, 3, "I")
        for x in (4, 14, 25):
            c.rect(x, 27, 3, 1, "S")

    frames, durs = [], []
    # flex
    for bow, d in ((0, 110), (3, 90), (6, 90), (9, 110)):
        c = Canvas(); ice(c); c.outline()
        L = Canvas()
        pts = [bez(k / 16, bow) for k in range(17)]
        shaft(L, pts)
        blade(L, *BLADE)
        gloves(L, bez(0.02, bow), bez(0.3, bow))
        puck(L, 25, 24, 5)
        if bow >= 4:
            bx, by = bez(0.5, bow)
            L.px(int(bx) - 3, int(by) - 1, "W"); L.px(int(bx) - 4, int(by) + 1, "W")
        L.outline(); blit(c, L)
        frames.append(c); durs.append(d)

    B = bez(0.5, 9)
    top_pts = [P0, (B[0] - 1, B[1] - 1)]
    bot_shaft = [(B[0] + 1, B[1] + 1), P2]
    rng = random.Random(9)
    splinters = []
    for k in range(8):
        a = math.radians(-160 + k * 40 + rng.uniform(-10, 10))
        sp = rng.uniform(1.5, 3)
        splinters.append([B[0], B[1], math.cos(a) * sp, math.sin(a) * sp - 1.2, "OCWO"[k % 4]])

    # bottom piece rigid body: points relative to its center
    bc = ((B[0] + P2[0] + BLADE[1][0]) / 3, (B[1] + P2[1] + BLADE[1][1]) / 3)
    bot_local = [(x - bc[0], y - bc[1]) for x, y in (bot_shaft[0], bot_shaft[1], BLADE[1])]
    poses = [  # (top angle about P0, bottom center dx, dy, bottom angle)
        (0, 0, 0, 0), (-18, 3, -5, 40), (-30, 6, -7, 100), (-24, 8, -3, 160),
        (-12, 8, 2, 200), (-6, 7, 4, 180), (-4, 7, 4, 180), (-4, 7, 4, 180),
    ]
    for i, (ta, bdx, bdy, ba) in enumerate(poses):
        c = Canvas(); ice(c); c.outline()
        L = Canvas()
        tp = [rotp(x, y, P0[0], P0[1], ta) for x, y in top_pts]
        shaft(L, tp)
        L.px(int(round(tp[1][0])) + 1, int(round(tp[1][1])) + 1, "C")
        gloves(L, rotp(*bez(0.02, 0), P0[0], P0[1], ta), rotp(*bez(0.3, 0), P0[0], P0[1], ta))
        cx_, cy_ = bc[0] + bdx, bc[1] + bdy
        if i >= 5:
            # lying flat on the ice
            bp = [(16, 24), (22, 24), (28, 24)]
            shaft(L, bp[:2]); blade(L, bp[1], bp[2])
        else:
            bp = [rotp(cx_ + x, cy_ + y, cx_, cy_, ba) for x, y in bot_local]
            shaft(L, bp[:2]); blade(L, bp[1], bp[2])
            L.px(int(round(bp[0][0])), int(round(bp[0][1])), "C")
        L.outline(); blit(c, L)
        top = Canvas()
        if i == 0:
            star(top, int(B[0]), int(B[1]), 4)
        for s in splinters:
            if i >= 1:
                s[0] += s[2]; s[1] += s[3]; s[3] += 0.7
                s[2] *= 0.85
                if s[1] > 25:
                    s[1] = 25; s[2] = 0; s[3] = 0
            top.px(int(round(s[0])), int(round(s[1])), s[4])
        pk_x = 25 + min(i, 3)
        puck(top, pk_x, 24, 5)
        top.outline(); blit(c, top)
        frames.append(c); durs.append([90, 80, 80, 80, 90, 110, 130, 130][i])
    return frames, durs


# =============================================================================================
# 10. tilly: two gloves drop one after the other, then fists up
# =============================================================================================
GLOVE = [
    "....JJJJJ..",
    "..JJHJHJHJ.",
    "CCJJHJHJHJJ",
    "CCJJHJHJHJJ",
    "CCJJJJJJJJJ",
    "CCJJJJJJJJ.",
    "..TTTTTTT..",
]


def tilly():
    g1 = sprite(GLOVE, {"J": "G", "H": "D", "C": "A", "T": "D"})
    g2 = sprite([r[::-1] for r in GLOVE], {"J": "B", "H": "b", "C": "A", "T": "b"})

    FIST = [
        "YY.YY.YY.YY",
        "GGDGGDGGDGG",
        "GGDGGDGGDGG",
        "GGDGGDGGDGG",
        "DDDDDDDDGGG",
        "YYYYYYYDGGG",
        "GGGGGGGDGGD",
        "DDDDDDDGGGD",
        ".GGGGGGGGD.",
        "..GGGGGGD..",
    ]

    def fist(L, x, y, sleeve, trim, mirror=False):
        L.rect(x + 2, y + 10, 7, 9, sleeve)                # forearm sleeve
        L.rect(x + 2, y + 10, 7, 1, "K")
        L.rect(x + 2, y + 13, 7, 1, trim)
        rows = [r[::-1] for r in FIST] if mirror else FIST
        L.stamp(rows, x, y)

    def ice(c):
        c.ellipse(15.5, 27, 14, 2, "I")
        c.rect(6, 27, 3, 1, "S"); c.rect(21, 28, 3, 1, "S")

    def scene(g1pos=None, g2pos=None, fists=None, puff=None):
        c = Canvas()
        ice(c)
        c.outline()
        if fists:
            (lx, ly), (rx, ry) = fists
            F = Canvas()
            fist(F, lx, ly, "G", "K")
            F.outline()
            blit(c, F)
            F = Canvas()
            fist(F, rx, ry, "B", "W", True)
            F.outline()
            blit(c, F)
        for g, pos in ((g1, g1pos), (g2, g2pos)):
            if pos:
                x, y, a = pos
                L = Canvas()
                rot(L, g, x + 5.5, y + 3.5, 5.5, 3.5, a)
                L.outline()
                blit(c, L)
        if puff:
            P = Canvas()
            for x, y in puff:
                P.px(x, y, "W")
            P.outline()
            blit(c, P)
        return c

    G1, G2 = (2, 21, 0), (19, 22, 0)
    frames, durs = [], []
    seq = [
        dict(g1=(3, -3, 25)), dict(g1=(2, 7, -15)), dict(g1=(2, 16, 8)),
        dict(g1=G1, puff=[(1, 26), (14, 26), (0, 24)]),
        dict(g1=G1, g2=(19, -3, -25)), dict(g1=G1, g2=(19, 8, 15)),
        dict(g1=G1, g2=G2, puff=[(17, 27), (31, 26), (30, 24)]),
        dict(g1=G1, g2=G2, fists=((3, 12), (18, 12))),
        dict(g1=G1, g2=G2, fists=((4, 4), (17, 4))),
        dict(g1=G1, g2=G2, fists=((5, 2), (17, 5))),
        dict(g1=G1, g2=G2, fists=((4, 5), (16, 2))),
        dict(g1=G1, g2=G2, fists=((5, 2), (17, 5))),
        dict(g1=G1, g2=G2, fists=((4, 5), (16, 2))),
        dict(g1=G1, g2=G2, fists=((4, 4), (17, 4))),
    ]
    durs = [70, 70, 70, 110, 70, 70, 120, 70, 90, 100, 100, 100, 100, 120]
    for s in seq:
        frames.append(scene(s.get("g1"), s.get("g2"), s.get("fists"), s.get("puff")))
    return frames, durs


# =============================================================================================
# 11. hattrick: three hats rain down one at a time and pile up
# =============================================================================================
CAP = [
    ".....W..........",
    "...RRRRR........",
    "..RrrRRRR.......",
    ".RrRRRRGGR......",
    ".RRRRRRGGRR.....",
    ".RRRRRRRRRKrrrrr",
    "..........RRRRR.",
]
TOQUE = [
    "...RR...",
    "..RrRR..",
    "..BBBB..",
    ".BLBBBB.",
    ".BBBBBB.",
    "WWWWWWWW",
    "BBBBBBBB",
    "WWWWWWWW",
]
FEDORA = [
    "...NNNNN...",
    "..NSN.NNN..",
    "..NNNNNNN..",
    "..AAAAAAA..",
    "NNNNNNNNNNN",
]


def hattrick():
    cap = sprite(CAP)
    toq = sprite(TOQUE)
    fed = Canvas(11, 5)
    fed.stamp(FEDORA)
    fed.px(5, 1, "N")
    hats = [(cap, (7, 20), 0), (toq, (15, 13), 14), (fed, (5, 14), -12)]   # resting top-left, angle

    def scene(states, sparkles=()):
        c = Canvas()
        c.ellipse(15.5, 27, 14, 2, "I")
        c.rect(6, 28, 3, 1, "S"); c.rect(22, 28, 3, 1, "S")
        c.outline()
        for spr, (x, y), a, sq in states:
            L = Canvas()
            if sq:
                tmp = Canvas(spr.w, spr.h)
                blit(tmp, spr)
                rot(L, tmp, x + spr.w / 2, y + spr.h / 2 + 1, spr.w / 2, spr.h / 2, 0)
            else:
                rot(L, spr, x + spr.w / 2, y + spr.h / 2, spr.w / 2, spr.h / 2, a)
            L.outline()
            blit(c, L)
        if sparkles:
            S = Canvas()
            for x, y, r in sparkles:
                sparkle(S, x, y, r, "Y", "W")
            S.outline()
            blit(c, S)
        return c

    frames, durs = [], []
    rest = []
    falls = [(-24, -2, 28), (-15, -1, -20), (-6, 0, 12)]       # (dy, dx, angle) above the resting spot
    for h, (spr, (x, y), ra) in enumerate(hats):
        for dy, dx, a in falls:
            sgn = 1 if h != 1 else -1
            frames.append(scene(rest + [(spr, (x + sgn * dx, y + dy), sgn * a, False)]))
            durs.append(70)
        rest.append((spr, (x, y), ra, False))
        puff = [(x - 1, y + spr.h - 1, 1), (x + spr.w, y + spr.h - 2, 1)]
        frames.append(scene(rest, puff))
        durs.append(110)
    for sp in ([(4, 6, 2), (27, 9, 1)], [(26, 5, 2), (5, 12, 1)], [(5, 7, 1), (27, 11, 2)]):
        frames.append(scene(rest, sp)); durs.append(130)
    return frames, durs


# =============================================================================================
# 12. cheers: two pint glasses swing in and clink, foam splashes up
# =============================================================================================
def pint():
    g = Canvas(10, 17)
    for r in range(17):
        hw = 5 - (1 if r >= 12 else 0)
        x0, x1 = 5 - hw, 5 + hw - 1
        if r == 0:
            g.rect(x0 + 1, r, x1 - x0 - 1, 1, "W")
        elif r <= 2:
            g.rect(x0, r, x1 - x0 + 1, 1, "W")
            if r == 2:
                g.px(x0 + 2, r, "C"); g.px(x1 - 2, r, "C")
        elif r <= 14:
            g.rect(x0, r, x1 - x0 + 1, 1, "G")
            g.px(x0, r, "I"); g.px(x1, r, "I")
            g.px(x0 + 1, r, "Y")
            g.px(x1 - 1, r, "D")
        else:
            g.rect(x0, r, x1 - x0 + 1, 1, "I")
    g.px(4, 6, "Y"); g.px(6, 9, "Y"); g.px(3, 11, "Y")   # bubbles
    return g


def cheers():
    g = pint()
    gr = pint().flip()
    seq = [  # left glass bottom-center x, y, angle
        (6, 31, -6), (8, 30, 8), (9, 29, 18), (10, 28, 24), (9, 28, 20), (8, 29, 15),
        (7, 29, 10), (6, 30, 5), (5, 30, 0), (5, 31, -4), (5, 31, -6),
    ]
    rng = random.Random(5)
    drops = [[16 + rng.uniform(-1, 1), 10, vx, rng.uniform(-3.4, -2.4)] for vx in (-2.2, -1.2, -0.4, 0.5, 1.3, 2.3)]
    frames, durs = [], []
    for i, (x, y, a) in enumerate(seq):
        c = Canvas()
        for spr, bx, ang in ((g, x, a), (gr, 31 - x, -a)):
            L = Canvas()
            rot(L, spr, bx, y, 5, 17, ang)
            L.outline()
            blit(c, L)
        top = Canvas()
        if i == 3:
            star(top, 16, 11, 4, "W", "Y")
        if i == 4:
            for x_, y_ in ((12, 7), (20, 7), (16, 5)):
                top.px(x_, y_, "Y")
        if i >= 3:
            for d in drops:
                if i > 3:
                    d[0] += d[2]; d[1] += d[3]; d[3] += 0.8
                if d[1] < 30:
                    top.rect(int(round(d[0])), int(round(d[1])), 2, 2, "W")
        if i == 3:
            top.rect(14, 8, 4, 3, "W")
        top.outline()
        blit(c, top)
        frames.append(c)
        durs.append([90, 70, 60, 120, 80, 80, 80, 80, 90, 100, 110][i])
    return frames, durs


# =============================================================================================
# 13. hockeystop: skate blade digs in sideways and throws a spray of snow
# =============================================================================================
SKATE = [
    "....MMM...........",
    "M..MNNNM..........",
    "MMMMNNNM..........",
    "MMMMMWMM..........",
    "MMMMMMWMM.........",
    "MMMMMWMWMM........",
    "MMMMMMWMWMM.......",
    "MGGGGGGGGWMMM.....",
    "MMMMMMMMMMMMMMMM..",
    "MMMMMMMMMMMMMMMMM.",
    "NNNNNNNNNNNNNNNNN.",
    ".WWWW......WWWWW..",
    ".WWWWWWWWWWWWWWWW.",
    "SSSSSSSSSSSSSSSSSW",
]


def hockeystop():
    sk = sprite(SKATE)
    P0, P1, P2 = (18.0, 24.0), (21.0, 9.0), (30.0, 3.0)

    def curve(t):
        return ((1 - t) ** 2 * P0[0] + 2 * (1 - t) * t * P1[0] + t * t * P2[0],
                (1 - t) ** 2 * P0[1] + 2 * (1 - t) * t * P1[1] + t * t * P2[1])

    def spray(S, t0, t1, drop=0.0, gap=False, seed=0):
        """A rooster tail of snow along the curve, thickening as it flies; can break up and fall."""
        r = random.Random(seed)
        n = 30
        for k in range(n + 1):
            t = t0 + (t1 - t0) * k / n
            if gap and int(t * 9) % 2:
                continue
            x, y = curve(t)
            y += drop * (0.4 + t)
            w = 0.8 + 3.0 * t
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    if dx * dx + dy * dy <= w * w and r.random() < 1.0 - 0.5 * t:
                        S.px(int(round(x + dx)), int(round(y + dy)), "W" if r.random() < 0.8 else "I")
            if t > 0.35 and r.random() < 0.35:          # loose clumps flung off the plume
                ox, oy = r.choice((-4, -3, 3, 4)), r.choice((-4, -3, 3))
                S.rect(int(round(x + ox)), int(round(y + oy)), 2, 2, "W")

    def skate(L, x, tilt, dig):
        d = sk.img.load()
        for j in range(sk.h):
            sh = -int(round((sk.h - 1 - j) * tilt / (sk.h - 1)))
            for i in range(sk.w):
                q = d[i, j]
                if q[3]:
                    L.px(x + i + sh, 12 + dig + j, q[:3])

    seq = [(-16, 0, 0, 4), (-9, 0, 0, 4), (-3, 0, 0, 3), (1, 2, 1, 0), (1, 3, 1, 0), (1, 3, 1, 0),
           (1, 2, 1, 0), (1, 1, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0)]
    durs = [60, 60, 60, 70, 80, 80, 90, 90, 100, 120, 130]
    frames = []
    landed = 0
    for i, (x, tilt, dig, lines) in enumerate(seq):
        c = Canvas()
        c.rect(1, 26, 30, 4, "I")
        for xx in (4, 13):
            c.rect(xx, 28, 4, 1, "S")
        if i >= 3:
            c.rect(2, 26, min(3 + 3 * (i - 3), 14), 1, "S")          # scrape mark
        c.outline()
        L = Canvas()
        skate(L, x, tilt, dig)
        if lines:
            speed_lines(L, x - 2, [14, 18, 22], [lines + 2, lines + 4, lines])
        L.outline()
        blit(c, L)
        S = Canvas()
        sp = {3: (0.0, 0.22, 0, False), 4: (0.0, 0.62, 0, False), 5: (0.05, 1.0, 0, False),
              6: (0.3, 1.0, 2.5, True), 7: (0.55, 1.0, 7, True)}.get(i)
        if sp:
            spray(S, *sp, seed=i)
        if i == 8:
            for q in ((24, 17), (28, 14), (22, 21)):
                S.px(*q, "W")
        pile = [0, 0, 0, 0, 1, 2, 3, 4, 4, 4, 4][i]
        for k in range(pile):
            S.rect(20 - k // 2, 25 - k // 2, 3 + 2 * k, 1, "W" if k % 2 else "I")
        if i == 9:
            S.px(26, 20, "W")
        if i == 10:
            S.px(28, 22, "W")
        S.outline()
        blit(c, S)
        frames.append(c)
    return frames, durs


# =============================================================================================
# 14. padsave: goalie kicks out a pad, puck deflects off it and away
# =============================================================================================
def padsave():
    PAD = [".WWWW.", "WWWWWG", "WWWWWG", "GGGGGG", "GGGGGG", "WWWWWG", "WWWWWG", "WWWWWG",
           "WWWWWG", "GGGGGG", "WWWWWG", ".WWWW."]
    pad = sprite(PAD)
    padl = sprite([r[::-1] for r in PAD])

    def goalie(L, ang, drop):
        y0 = drop
        L.rect(13, 0 + y0, 6, 6, "W"); L.px(13, 0 + y0, None); L.px(18, 0 + y0, None)       # mask
        L.rect(13, 0 + y0, 6, 1, "G")
        for x in (14, 16):
            L.rect(x, 3 + y0, 1, 3, "N")
        L.rect(13, 4 + y0, 6, 1, "N")
        L.rect(8, 6 + y0, 16, 3, "G"); L.rect(10, 9 + y0, 12, 5, "G")                       # jersey
        L.rect(10, 11 + y0, 12, 1, "K"); L.rect(8, 6 + y0, 16, 1, "Y")
        L.rect(3, 8 + y0, 5, 6, "W"); L.rect(3, 8 + y0, 1, 6, "G"); L.rect(5, 10 + y0, 2, 2, "S")   # blocker
        L.rect(24, 7 + y0, 5, 6, "G"); L.rect(25, 8 + y0, 3, 4, "D"); L.rect(24, 12 + y0, 5, 1, "W")  # catcher
        L.rect(10, 14 + y0, 12, 4, "A"); L.rect(10, 14 + y0, 12, 1, "M"); L.rect(10, 16 + y0, 12, 1, "G")  # pants
        rot(L, padl, 12.5, 17 + y0, 3, 0, 2)
        rot(L, pad, 19.5, 17 + y0, 3, 0, ang)

    def scene(ang, drop, pk=None, burst=False, trail=()):
        c = Canvas()
        c.rect(1, 28, 30, 3, "I")
        for xx in (4, 14, 23):
            c.rect(xx, 29, 3, 1, "S")
        c.outline()
        L = Canvas()
        goalie(L, ang, drop)
        L.outline()
        blit(c, L)
        T = Canvas()
        for (x, y) in trail:
            T.px(x, y, "W")
        if pk:
            puck(T, pk[0], pk[1], 5)
        if burst:
            star(T, 27, 25, 4)
        T.outline()
        blit(c, T)
        return c

    seq = [
        dict(ang=0, drop=0, pk=(28, 26)),
        dict(ang=-25, drop=1, pk=(27, 26)),
        dict(ang=-55, drop=2, pk=(26, 25), burst=True),
        dict(ang=-58, drop=2, pk=(27, 18), trail=[(27, 23), (27, 22), (28, 21)]),
        dict(ang=-56, drop=2, pk=(28, 10), trail=[(28, 15), (28, 14), (29, 13)]),
        dict(ang=-45, drop=2, pk=(29, 3), trail=[(29, 8), (29, 7), (30, 6)]),
        dict(ang=-28, drop=1),
        dict(ang=-10, drop=0),
        dict(ang=0, drop=0),
    ]
    durs = [100, 70, 110, 70, 70, 70, 90, 100, 130]
    frames = [scene(s_["ang"], s_["drop"], s_.get("pk"), s_.get("burst", False), s_.get("trail", ())) for s_ in seq]
    return frames, durs


# =============================================================================================
# 15. confetti: party popper bursts, confetti flutters down
# =============================================================================================
def confetti():
    BX, BY = 4.0, 28.0
    ux, uy = math.cos(math.radians(-58)), math.sin(math.radians(-58))
    vx_, vy_ = -uy, ux

    def popper(c, recoil=0):
        bx, by = BX - recoil * ux, BY - recoil * uy
        for y in range(32):
            for x in range(32):
                dx, dy = x + .5 - bx, y + .5 - by
                t = dx * ux + dy * uy
                s = dx * vx_ + dy * vy_
                if 0 <= t <= 13 and abs(s) <= 0.7 + t * 0.36:
                    c.px(x, y, "C" if t > 12 else ("R" if int(t // 3) % 2 else "G"))
        c.line(int(bx) - 1, int(by), int(bx) - 3, int(by) + 2, "W")

    rng = random.Random(21)
    cols = "RYLEPVBGW"
    bits = []
    mx, my = BX + 13 * ux, BY + 13 * uy
    for k in range(30):
        a = math.radians(-62 + rng.uniform(-48, 40))
        sp = rng.uniform(3.5, 8.5)
        bits.append(dict(x=mx, y=my, vx=math.cos(a) * sp, vy=math.sin(a) * sp, ph=rng.uniform(0, 6.28),
                         colr=cols[k % len(cols)]))
    streamers = [(-40, "P"), (-75, "L")]

    frames, durs = [], []
    N = 18
    for i in range(N):
        c = Canvas()
        popper(c, 1 if i == 2 else 0)
        if i == 1:
            c.px(int(BX) - 4, int(BY) + 3, "W")
        c.outline()
        T = Canvas()
        if i == 2:
            star(T, int(mx) + 2, int(my) - 2, 4)
        if i >= 2:
            for b in bits:
                if i > 2:
                    b["x"] += b["vx"]; b["y"] += b["vy"]
                    b["vx"] *= 0.7; b["vy"] = b["vy"] * 0.7 + 0.36
                    if b["vy"] > 0:
                        b["x"] += 0.9 * math.sin(b["ph"] + i * 1.2)
                if b["y"] < 31:
                    flip_ = (i + int(b["ph"] * 3)) % 3
                    x, y = int(round(b["x"])), int(round(b["y"]))
                    if flip_ == 0:
                        T.rect(x, y, 2, 1, b["colr"])
                    elif flip_ == 1:
                        T.rect(x, y, 1, 2, b["colr"])
                    else:
                        T.px(x, y, b["colr"])
            if 3 <= i <= 12:
                for a0, colr in streamers:
                    n = min(i - 2, 5) * 2
                    for k in range(n):
                        a = math.radians(a0)
                        x = mx + math.cos(a) * k * 1.4 + math.sin(k * 1.3 + i) * 0.9
                        y = my + math.sin(a) * k * 1.4 + max(0, i - 6) * 0.5 * k / 6
                        T.px(int(round(x)), int(round(y)), colr)
        T.outline()
        blit(c, T)
        frames.append(c)
        durs.append(110 if i < 2 else (70 if i < 6 else 90))
    return frames, durs


# =============================================================================================
# 16. jackpot: slot machine spins, lands on B B B, coins pop out
# =============================================================================================
SYM = {
    "B": (["####.", "##.##", "##.##", "####.", "##.##", "##.##", "####."], "B"),
    "7": (["#####", "...##", "..##.", "..##.", ".##..", ".##..", ".##.."], "R"),
    "C": (["...#.", "..#.#", ".#..#", "#...#", "rr.rr", "rr.rr", "....."], "E"),
    "*": ([".....", "..#..", ".###.", "#####", ".###.", ".#.#.", "....."], "G"),
}
STRIP = ["7", "C", "B", "*"]


def jackpot():
    WX = [6, 12, 18]           # reel windows (5 wide) top y 11..19

    def symbol(c, s, x, y, clip):
        rows, colr = SYM[s]
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                yy = y + j
                if ch != "." and clip[0] <= yy <= clip[1]:
                    c.px(x + i, yy, colr if ch == "#" else "R")

    def machine(c, reels, lever, lights, flash):
        c.rect(3, 7, 23, 22, "R"); c.rect(4, 7, 1, 22, "r")          # cabinet
        c.rect(5, 3, 19, 4, "G"); c.rect(5, 3, 19, 1, "Y")           # marquee
        c.px(5, 3, None); c.px(23, 3, None)
        for k, x in enumerate(range(7, 23, 3)):
            c.px(x, 5, "W" if (k + lights) % 2 else "D")
        c.rect(5, 10, 19, 11, "K")
        for k, x in enumerate(WX):
            c.rect(x, 11, 5, 9, "Y" if flash else "W")
            r = reels[k]
            if isinstance(r, str):
                symbol(c, r, x, 12, (11, 19))
            else:   # spinning: scrolled strip
                off = r % 36
                for n, s in enumerate(STRIP * 2):
                    symbol(c, s, x, 12 + n * 9 - off - 9, (11, 19))
                c.px(x, 11 + (r % 9), "S"); c.px(x + 4, 11 + ((r + 4) % 9), "S")
        c.rect(5, 22, 19, 1, "G")
        c.rect(8, 24, 13, 3, "A"); c.rect(8, 24, 13, 1, "G"); c.rect(9, 25, 11, 1, "K")   # coin tray
        c.rect(26, 15, 2, 5, "N")                                      # lever
        top = {0: 4, 1: 10, 2: 16}[lever]
        c.rect(28, top, 1, 18 - top if top < 16 else 3, "S")
        c.circle(28, top, 1, "R"); c.px(28, top - 1, "r")

    coins = []
    rng = random.Random(8)
    for k in range(8):
        coins.append(dict(born=11 + k, x=13.0, y=22.0, vx=(-1 if k % 2 else 1) * (3.2 + (k % 3) * 0.5),
                          vy=-3.0 + (k % 3) * 0.5))
    seq = [
        (["7", "C", "*"], 0, 0, False), (["7", "C", "*"], 1, 1, False), ([5, 11, 17], 2, 0, False),
        ([12, 20, 26], 1, 1, False), ([19, 29, 35], 0, 0, False), ([26, 2, 8], 0, 1, False),
        (["B", 11, 17], 0, 0, False), (["B", 20, 26], 0, 1, False), (["B", "B", 35], 0, 0, False),
        (["B", "B", 8], 0, 1, False), (["B", "B", "B"], 0, 0, True), (["B", "B", "B"], 0, 1, False),
        (["B", "B", "B"], 0, 0, True), (["B", "B", "B"], 0, 1, False), (["B", "B", "B"], 0, 0, True),
        (["B", "B", "B"], 0, 1, False), (["B", "B", "B"], 0, 0, True), (["B", "B", "B"], 0, 1, False),
    ]
    durs = [120, 80, 60, 60, 60, 60, 80, 60, 80, 60, 110, 90, 90, 90, 90, 90, 100, 110]
    frames = []
    for i, (reels, lever, lights, flash) in enumerate(seq):
        c = Canvas()
        machine(c, reels, lever, lights, flash)
        c.outline()
        T = Canvas()
        for cn in coins:
            if i < cn["born"]:
                continue
            if i > cn["born"]:
                cn["x"] += cn["vx"]; cn["y"] += cn["vy"]; cn["vy"] += 0.7
            if cn["y"] < 31:
                x, y = int(round(cn["x"])), int(round(cn["y"]))
                T.stamp([".GG.", "GYGD", "GGGD", ".DD."], x, y)
        T.outline()
        blit(c, T)
        frames.append(c)
    return frames, durs


# =============================================================================================
# 17. breaking: tiny TV with a scrolling BREAKING banner and a pulsing red light
# =============================================================================================
def breaking():
    msg = "BREAKING"
    tw = Canvas(64, 5)
    w = tw.text(0, 0, msg, "W") - 1
    period = 36
    pulse = ["R", "r", "W", "r", "R", "A"]
    frames, durs = [], []
    for f in range(18):
        c = Canvas()
        c.line(13, 5, 8, 0, "S"); c.line(18, 5, 23, 0, "S")             # rabbit ears
        c.rect(1, 5, 30, 22, "M"); c.rect(1, 5, 30, 1, "N")              # cabinet
        c.px(1, 5, None); c.px(30, 5, None); c.px(1, 26, None); c.px(30, 26, None)
        c.rect(5, 27, 3, 2, "A"); c.rect(24, 27, 3, 2, "A")             # feet
        c.rect(3, 7, 22, 18, "B")                                        # screen
        c.rect(3, 7, 22, 1, "b")
        c.rect(10, 9, 12, 1, "L"); c.rect(10, 11, 8, 1, "L")             # headline graphic
        c.rect(3, 14, 22, 7, "R"); c.rect(3, 14, 22, 1, "r")             # banner
        c.rect(3, 21, 22, 2, "G")
        for k in range(0, 22, 4):
            xk = 3 + (k + f) % 22
            c.px(xk, 22, "D")
        off = (f * 2) % period
        for rep in (0, 1):
            x0 = 25 - off + rep * period - period // 2
            for j in range(5):
                for i in range(w):
                    if tw.img.getpixel((i, j))[3] and 3 <= x0 + i <= 24:
                        c.px(x0 + i, 15 + j, "W")
        # pulsing red light, top-left of screen
        p = pulse[f % 6]
        c.rect(5, 9, 3, 3, p if p != "W" else "r")
        if p == "W":
            c.px(6, 10, "W")
            for x, y in ((4, 10), (8, 10), (6, 8), (6, 12)):
                c.px(x, y, "r")
        c.rect(27, 9, 2, 2, "S"); c.rect(27, 13, 2, 2, "S")              # knobs
        for y in (18, 20, 22):
            c.rect(26, y, 4, 1, "A")
        frames.append(finish(c)); durs.append(90)
    return frames, durs


# =============================================================================================
# 18. penalty: referee raises an arm straight up (delayed penalty), then points to the box
# =============================================================================================
def penalty():
    def ref(c, left, right, whistle=False, toot=0):
        c.rect(7, 3, 8, 3, "A"); c.rect(8, 3, 6, 1, "M")                # helmet
        c.rect(8, 6, 6, 4, "C")                                          # face
        c.px(9, 7, "K"); c.px(12, 7, "K")
        if whistle:
            c.rect(10, 9, 2, 1, "S")
        else:
            c.rect(10, 9, 2, 1, "O")
        for k, x in enumerate(range(6, 16)):                             # striped shirt
            c.rect(x, 10, 1, 9, "W" if (k // 2) % 2 == 0 else "K")
        c.rect(7, 19, 8, 5, "A"); c.rect(10, 22, 2, 2, None)            # pants
        c.rect(6, 24, 4, 3, "A"); c.rect(12, 24, 4, 3, "A")             # skates
        c.rect(5, 27, 5, 1, "S"); c.rect(12, 27, 5, 1, "S")
        # arms: (shoulder)->(hand) as 2-px striped sleeves with an orange armband
        def arm(sx, sy, hx, hy, band):
            n = max(abs(hx - sx), abs(hy - sy))
            for k in range(n + 1):
                x = sx + (hx - sx) * k / n
                y = sy + (hy - sy) * k / n
                colr = "F" if k in band else ("W" if (k // 2) % 2 == 0 else "K")
                c.rect(int(round(x)), int(round(y)), 2, 2, colr)
            c.rect(hx, hy, 2, 2, "C")
        if left == "down":
            arm(4, 11, 4, 18, (2,))
        elif left == "mid":
            arm(4, 10, 1, 4, (2,))
        else:
            arm(4, 10, 4, 1, (2,))
        if right == "down":
            arm(16, 11, 16, 18, (2,))
        elif right == "mid":
            arm(16, 11, 21, 14, (2,))
        else:
            ext = 1 if right == "jab" else 0
            arm(16, 11, 22 + ext, 15, (2,))
            c.px(24 + ext, 15, "C")
        if toot:
            for x, y in ((14 + toot, 8), (15 + toot, 7), (15 + toot, 10)):
                c.px(x, y, "W")

    def box(c, door):
        c.rect(25, 13, 6, 15, "N")
        c.rect(26, 14, 4, 6, "L"); c.px(26, 14, "W")
        c.rect(26, 21, 4, 6, "O"); c.rect(26, 23, 4, 1, "o")
        if door:
            c.rect(25, 13, 1, 15, "S")
            c.rect(24 - door + 1, 14, door, 13, "o")

    seq = [("down", "down", False, 0, 0), ("mid", "down", False, 0, 0), ("up", "down", True, 1, 0),
           ("up", "down", True, 2, 0), ("up", "down", True, 1, 0), ("up", "down", True, 2, 0),
           ("down", "mid", False, 0, 0), ("down", "point", False, 0, 0), ("down", "jab", False, 0, 1),
           ("down", "point", False, 0, 1), ("down", "jab", False, 0, 1), ("down", "point", False, 0, 0)]
    durs = [120, 80, 110, 110, 110, 110, 80, 100, 90, 90, 90, 130]
    frames = []
    for left, right, wh, toot, door in seq:
        c = Canvas()
        box(c, door)
        ref(c, left, right, wh, toot)
        frames.append(finish(c))
    return frames, durs


# =============================================================================================
# 19. hourglass: sand drains top to bottom, then the glass flips over
# =============================================================================================
def hourglass():
    TOP = [3, 5, 6, 6, 6, 5, 5, 4, 3, 2, 1, 1]          # half widths for y 5..16 (top bulb)
    BOT = TOP[::-1]                                     # y 17..28
    Y_TOP, Y_BOT = 5, 17
    rows_top = {Y_TOP + i: w for i, w in enumerate(TOP)}
    rows_bot = {Y_BOT + i: w for i, w in enumerate(BOT)}
    CAP = 46

    def draw(p, f):
        c = Canvas()
        c.rect(8, 2, 16, 2, "O"); c.rect(8, 3, 16, 1, "o")             # caps
        c.rect(8, 29, 16, 2, "O"); c.rect(8, 30, 16, 1, "o")
        c.rect(9, 4, 1, 25, "o"); c.rect(22, 4, 1, 25, "o")             # posts
        for rows in (rows_top, rows_bot):
            for y, w in rows.items():
                c.rect(16 - w, y, 2 * w, 1, "I")
                c.px(16 + w - 1, y, "L")
        # sand left on top: fill rows from the neck upwards; the last row fills from the edges (funnel)
        left = round(CAP * p)
        for y in sorted(rows_top, reverse=True):
            w = rows_top[y]
            if left <= 0:
                break
            n = min(left, 2 * w)
            if n == 2 * w:
                c.rect(16 - w, y, 2 * w, 1, "G")
            else:
                h = n // 2
                c.rect(16 - w, y, h, 1, "G"); c.rect(16 + w - h, y, h, 1, "G")
            left -= n
        # sand below: fill rows from the bottom up; the last row fills from the center (mound)
        fallen = CAP - round(CAP * p)
        for y in sorted(rows_bot, reverse=True):
            w = rows_bot[y]
            if fallen <= 0:
                break
            n = min(fallen, 2 * w)
            h = (n + 1) // 2
            c.rect(16 - h, y, 2 * h, 1, "G")
            fallen -= n
            top_y = y
        # stream
        if 0 < p < 1:
            ty = top_y if CAP - round(CAP * p) > 0 else 28
            for y in range(16, ty):
                c.px(15, y, "Y" if (y + f) % 3 else "G")
        for y in (6, 7, 8):
            c.px(12 if y > 6 else 13, y, "W")
        for y in (20, 21):
            c.px(11, y + 3, "W")
        return c

    frames, durs = [], []
    ps = [1, .9, .8, .7, .6, .5, .4, .3, .2, .1, 0]
    for f, p in enumerate(ps):
        c = draw(p, f)
        frames.append(finish(c)); durs.append(100 if p > 0 else 140)
    base = draw(0, 0)
    for a in (45, 90, 135):
        c = Canvas()
        rot(c, base, 15.5, 16, 15.5, 16, a)
        frames.append(finish(c)); durs.append(70)
    return frames, durs


# =============================================================================================
# 20. fire: a flame that flickers, grows and throws sparks
# =============================================================================================
def fire():
    N = 16
    rng = random.Random(12)
    sparks = [dict(born=rng.randrange(N), x=rng.uniform(9, 22), drift=rng.uniform(-0.8, 0.8)) for _ in range(9)]
    frames, durs = [], []
    for f in range(N):
        ph = 2 * math.pi * f / N
        grow = 0.5 - 0.5 * math.cos(ph)
        H = 18 + 8 * grow
        W = 8 + 2.2 * grow
        base, cx = 29.5, 15.5
        c = Canvas()
        for y in range(32):
            t = (base - (y + .5)) / H
            if t < -0.14 or t > 1:
                continue
            env = W * (1 - max(t, 0)) ** 1.25 * min(1.0, math.sqrt(max(0.0, (t + 0.14) / 0.34)))
            env += 0.9 * max(t, 0) * math.sin(y * 1.3 + ph * 3)
            sway = 2.4 * max(t, 0) ** 1.5 * math.sin(ph * 2 + t * 3.5)
            for x in range(32):
                d = abs(x + .5 - (cx + sway)) / max(env, 0.01)
                di = abs(x + .5 - (cx + sway * 0.6)) / max(env, 0.01)
                if d > 1:
                    continue
                colr = "R"
                if di <= 0.7 and t < 0.78:
                    colr = "F"
                if di <= 0.46 and t < 0.56:
                    colr = "G"
                if di <= 0.24 and t < 0.34:
                    colr = "Y"
                c.px(x, y, colr)
        # side tongues: two smaller flames leaning out from the base
        for side, phase, hk in ((-1, 0.0, 0.5), (1, 2.3, 0.42)):
            h2 = H * (hk + 0.08 * math.sin(ph * 2 + phase))
            w2 = W * 0.42
            ccx = cx + side * W * 0.62
            for y in range(32):
                t = (base - 1 - (y + .5)) / h2
                if t < 0 or t > 1:
                    continue
                env = w2 * (1 - t) ** 1.1 * min(1.0, math.sqrt((t + 0.1) / 0.35))
                lean = side * 2.2 * t ** 1.4 + 0.8 * t * math.sin(ph * 3 + phase)
                for x in range(32):
                    if abs(x + .5 - (ccx + lean)) <= env and not c.get(x, y)[3]:
                        c.px(x, y, "R" if t > 0.45 or abs(x + .5 - (ccx + lean)) > env * 0.5 else "F")
        # detached tip
        tipy = int(base - H - 2 - (f % 4) * 2)
        if f % 4 != 3 and tipy > 0:
            c.rect(int(cx + 2.4 * math.sin(ph * 2 + 3.5)), tipy, 2, 2, "R")
        c.outline()
        S = Canvas()
        for s in sparks:
            age = (f - s["born"]) % N
            if age < 5:
                x = int(round(s["x"] + s["drift"] * age + math.sin(age * 1.7)))
                y = int(round(base - H * 0.7 - age * 3))
                if 0 <= y:
                    S.px(x, y, "Y" if age < 3 else "F")
        S.outline()
        blit(c, S)
        frames.append(c); durs.append(70)
    return frames, durs


# =============================================================================================
# 21. powerplay: battery charges bar by bar, then a lightning bolt crackles
# =============================================================================================
def powerplay():
    BARS = [24, 20, 16, 12, 8]
    BOLTS = [
        [(19, 0), (8, 17), (15, 17), (11, 31), (25, 12), (17, 12), (23, 0)],
        [(18, 1), (9, 15), (15, 15), (12, 30), (24, 13), (17, 13), (22, 1)],
    ]

    def battery(c, n, flash=False):
        c.rect(13, 2, 6, 2, "S")
        c.rect(7, 4, 18, 26, "S"); c.rect(23, 4, 2, 26, "N"); c.rect(7, 4, 18, 1, "W")
        c.rect(9, 6, 14, 22, "A")
        for k in range(n):
            y = BARS[k]
            c.rect(10, y, 12, 3, "W" if flash else "E")
            if not flash:
                c.rect(10, y, 12, 1, "e")

    frames, durs = [], []
    for n in range(6):
        c = Canvas()
        battery(c, n)
        if n == 0:
            c.rect(10, 26, 12, 1, "R")
        frames.append(finish(c)); durs.append(110)
    c = Canvas(); battery(c, 5, True); frames.append(finish(c)); durs.append(80)
    rng = random.Random(2)
    for k in range(6):
        c = Canvas()
        battery(c, 5)
        c.outline()
        L = Canvas()
        pts = BOLTS[k % 2]
        L.poly(pts, "W" if k % 3 == 1 else "Y")
        L.line(pts[0][0] + 1, pts[0][1] + 1, pts[1][0] + 2, pts[1][1] - 1, "W")
        L.line(pts[2][0] - 1, pts[2][1] + 1, pts[3][0], pts[3][1] - 2, "W")
        for _ in range(4):
            x, y = rng.randint(3, 28), rng.randint(1, 29)
            if (x < 7 or x > 25):
                L.px(x, y, "Y")
        if k % 2 == 0:
            L.line(13, 1, 11, 0, "Y"); L.line(19, 1, 21, 0, "Y")
        L.outline()
        blit(c, L)
        frames.append(c); durs.append(70)
    return frames, durs


# =============================================================================================
# face emoji (shared gold face from pix.face)
# =============================================================================================
def happy_eye(c, cx, cy):
    for dx, dy in ((-3, 2), (-2, 1), (-1, 0), (0, 0), (1, 1), (2, 2)):
        c.px(cx + dx, cy + dy, "K"); c.px(cx + dx, cy + dy + 1, "K")


def laugh():
    N = 12
    frames, durs = [], []
    for f in range(N):
        c = Canvas()
        bob = 1 if f % 2 else 0
        pix.face(c, 15.5, 15.5 + bob, 12)
        happy_eye(c, 10, 10 + bob)
        happy_eye(c, 22, 10 + bob)
        h = 7 if f % 2 == 0 else 5
        for y in range(17 + bob, 17 + bob + h + 1):
            t = (y - 17 - bob) / h
            hw = 8 * math.sqrt(max(0, 1 - t * t))
            for x in range(32):
                if abs(x + .5 - 16) <= hw:
                    c.px(x, y, "K")
        for y in range(18 + bob, 17 + bob + h):
            t = (y - 17 - bob) / h
            hw = 7 * math.sqrt(max(0, 1 - t * t))
            for x in range(32):
                if abs(x + .5 - 16) <= hw:
                    c.px(x, y, "A")
        c.rect(10, 18 + bob, 12, 1, "W")
        c.rect(13, 17 + bob + h - 2, 6, 1, "r")
        c.rect(14, 17 + bob + h - 3, 4, 1, "r")
        c.outline()
        T = Canvas()
        # a tear wells up at each outer eye corner, then is flung outward in an arc; one every 3 frames
        for side in (-1, 1):
            ox = 16 + side * 10
            for born in range(-9, N, 3):
                age = (f - born - (1 if side > 0 else 0)) % N
                if age == 0:
                    drop(T, ox - 1 + side, 11 + bob, 1)
                elif age <= 3:
                    x = ox + side * (1 + 1.7 * age)
                    y = 11 - 4.2 * age + 0.9 * age * age
                    drop(T, int(round(x)) - 2, int(round(y)), 2 if age < 3 else 1)
        T.outline()
        blit(c, T)
        frames.append(c); durs.append(80)
    return frames, durs


def cry():
    N = 12
    frames, durs = [], []
    for f in range(N):
        c = Canvas()
        pix.face(c, 15.5, 13.5, 12)
        # sad brows and shut eyes
        c.line(7, 7, 11, 6, "K"); c.line(20, 6, 24, 7, "K")
        c.rect(7, 10, 5, 2, "K"); c.rect(20, 10, 5, 2, "K")
        c.px(7, 9, "K"); c.px(24, 9, "K")
        # wailing mouth (wobbles)
        rx = 4 if f % 2 else 5
        c.ellipse(15.5, 19.5, rx, 3, "K")
        c.ellipse(15.5, 19.5, rx - 1, 2, "A")
        c.rect(14, 21, 4, 1, "r")
        c.outline()
        T = Canvas()
        width = 8 + f * 2
        T.ellipse(15.5, 28.5, min(width, 15), 1.6, "L")
        T.rect(16 - min(width, 15) // 2, 28, min(width, 15), 1, "W")
        for sx in (8, 22):
            for y in range(12, 29):
                T.rect(sx, y, 2, 1, "L")
                if (y - f * 2) % 5 == 0:
                    T.px(sx, y, "W")
                if (y - f * 2) % 5 == 2:
                    T.px(sx + 1, y, "B")
        for k, sx in enumerate((8, 22)):
            if (f + k) % 3 == 0:
                T.px(sx - 2, 26, "W"); T.px(sx + 3, 25, "W")
            elif (f + k) % 3 == 1:
                T.px(sx - 3, 24, "W"); T.px(sx + 4, 24, "W")
        T.outline()
        blit(c, T)
        frames.append(c); durs.append(90)
    return frames, durs


def mindblown():
    CY = 19.5

    def head(f_eyes=0):
        c = Canvas()
        pix.face(c, 15.5, CY, 11)
        for ex in (11, 20):
            c.ellipse(ex, 18, 2, 3 + f_eyes, "W")
            c.rect(ex, 18, 1, 2, "K")
        c.circle(15.5, 25, 2, "K")
        c.circle(15.5, 25, 1, "A")
        return c

    def crack(x):
        return 13 + (1 if (x // 2) % 2 else 0)

    def split(c):
        cap, rest = Canvas(), Canvas()
        data = c.img.load()
        for y in range(32):
            for x in range(32):
                p = data[x, y]
                if p[3]:
                    (cap if y < crack(x) else rest).px(x, y, p[:3])
        return cap, rest

    frames, durs = [], []
    seq = ["calm", "shake1", "shake2", "boom", "fire", "smoke1", "smoke2", "smoke3", "wisp", "fall1", "land", "calm2"]
    for i, st in enumerate(seq):
        c = Canvas()
        if st in ("calm", "calm2"):
            blit(c, head(0))
            if st == "calm2":
                c.px(15, 9, "Y")
            frames.append(finish(c)); durs.append(120 if st == "calm" else 110)
            continue
        if st.startswith("shake"):
            dx = 1 if st == "shake1" else -1
            h = head(1)
            for x in range(6, 26):
                h.px(x, crack(x) - 1, "D")
            blit(c, h, dx, 0)
            frames.append(finish(c)); durs.append(70)
            continue
        cap, rest = split(head(1))
        # open top: dark hole along the crack
        for x in range(6, 26):
            if rest.get(x, crack(x))[3]:
                rest.px(x, crack(x), "A")
                rest.px(x, crack(x) + 1, "D" if x % 3 else "A")
        blit(c, rest)
        c.outline()
        T = Canvas()
        if st == "boom":
            blit(T, cap, 0, -4)
            star(T, 15, 9, 6, "W", "Y")
        elif st == "fire":
            rot(T, cap, 9, 0, 15.5, 10, -35)
            T.circle(15.5, 7, 5, "F"); T.circle(15.5, 7, 3, "Y"); T.circle(15.5, 7, 1, "W")
            for x, y in ((5, 3), (26, 4), (8, 12), (24, 11), (3, 9), (28, 8)):
                T.px(x, y, "G")
        elif st.startswith("smoke"):
            k = int(st[-1])
            yy = 8 - 2 * k
            for (ox, oy, r) in ((-4, 0, 3 + (k > 1)), (4, 0, 3 + (k > 1)), (0, -3, 4), (0, 3, 2)):
                T.circle(15.5 + ox, yy + oy, r, "S")
            for (ox, oy, r) in ((-3, -1, 1), (3, -2, 1), (0, -4, 2)):
                T.circle(15.5 + ox, yy + oy, r, "W")
            T.rect(14, yy + 4, 4, 13 - (yy + 4) + 1, "N")
            if k == 1:
                T.circle(15.5, yy + 1, 2, "F")
            for x, y in ((4 - k, 14 + 3 * k), (27 + k, 13 + 3 * k)):
                T.px(x, y, "G")
        elif st == "wisp":
            T.rect(15, 9, 2, 4, "N")
            T.circle(13, 6, 2, "S"); T.circle(19, 4, 2, "S"); T.circle(16, 2, 1, "W")
            T.px(12, 5, "W"); T.px(19, 3, "W")
        elif st == "fall1":
            blit(T, cap, 0, -7)
        elif st == "land":
            blit(T, cap, 0, -1)
            for x, y in ((4, 12), (27, 12), (3, 10), (28, 10)):
                T.px(x, y, "W")
        T.outline()
        blit(c, T)
        frames.append(c)
        durs.append({"boom": 80, "fire": 80, "smoke1": 90, "smoke2": 100, "smoke3": 100, "wisp": 110,
                     "fall1": 70, "land": 90}[st])
    return frames, durs


def sweat():
    N = 14
    frames, durs = [], []
    # sweat drop path: forms on the brow (top right), grows, then runs down the right side
    path = [(22, 4, 0), (22, 4, 1), (21, 3, 2), (21, 3, 2), (21, 4, 2), (22, 7, 2), (23, 10, 2),
            (24, 14, 2), (25, 18, 2), (25, 23, 1), (25, 27, 1), (25, 31, 0), (None, 0, 0), (None, 0, 0)]
    for f in range(N):
        c = Canvas()
        pix.face(c)
        # worried brows, open eyes
        c.line(7, 9, 11, 7, "K"); c.line(20, 7, 24, 9, "K")
        c.rect(9, 11, 3, 4, "K"); c.rect(20, 11, 3, 4, "K")
        c.px(9, 11, "W"); c.px(20, 11, "W")
        # nervous toothy grin (trembles)
        j = f % 2
        c.rect(7, 18, 18, 6, "K")
        c.px(7, 18, "G"); c.px(24, 18, "G")
        c.rect(8, 19, 16, 4, "W")
        c.rect(8, 21 - 0, 16, 1, "K")
        for x in (11 + j, 15 + j, 19 + j):
            c.rect(x, 19, 1, 4, "K")
        x, y, s = path[f]
        if x is not None and 6 <= f < 11:      # wet streak left on the skin behind the running drop
            for yy in range(8, min(y, 27)):
                tx = 23 + (yy - 8) * 3 // 19
                if c.get(tx + 2, yy)[3] and c.get(tx + 2, yy)[:3] != pix.PAL["K"]:
                    c.px(tx + 2, yy, "Y")
        c.outline()
        T = Canvas()
        if x is not None:
            if s == 2:
                drop(T, x, y, 2)
            elif s == 1:
                drop(T, x + 1, y, 1)
            else:
                drop(T, x + 1, y, 0)
        else:
            T.px(22 + (f - 12), 4, "L")
        T.outline()
        blit(c, T)
        frames.append(c); durs.append([100, 100, 110, 120, 90, 70, 70, 70, 70, 70, 70, 80, 100, 110][f])
    return frames, durs


# =============================================================================================
# registry / main
# =============================================================================================
ALL = [
    ("zamboni", zamboni), ("goal", goal), ("snipe", snipe), ("bardown", bardown), ("topshelf", topshelf),
    ("fivehole", fivehole), ("dangle", dangle), ("slapshot", slapshot), ("snapped", snapped), ("tilly", tilly),
    ("hattrick", hattrick), ("cheers", cheers), ("hockeystop", hockeystop), ("padsave", padsave),
    ("confetti", confetti), ("jackpot", jackpot), ("breaking", breaking), ("penalty", penalty),
    ("hourglass", hourglass), ("fire", fire), ("powerplay", powerplay), ("laugh", laugh), ("cry", cry),
    ("mindblown", mindblown), ("sweat", sweat),
]


def gif_info(path):
    im = Image.open(path)
    ds = []
    try:
        while True:
            ds.append(im.info.get("duration", 0))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    return ds


# Every loop is cyclic, so each GIF starts on its most telling frame: that is the still Discord
# shows when animation is off (and in some pickers).
START = {
    "zamboni": 3, "goal": 5, "snipe": 6, "bardown": 3, "topshelf": 8, "fivehole": 2, "slapshot": 6,
    "snapped": 4, "tilly": 9, "hattrick": 12, "cheers": 5, "hockeystop": 5, "padsave": 2, "confetti": 6,
    "jackpot": 12, "penalty": 2, "hourglass": 4, "fire": 8, "powerplay": 8, "cry": 6, "mindblown": 6,
    "sweat": 4,
}


def main(argv):
    want = [a.replace("blha_", "") for a in argv]
    paths = []
    for name, fn in ALL:
        if want and name not in want:
            continue
        frames, durs = fn()
        k = START.get(name, 0)
        frames, durs = frames[k:] + frames[:k], list(durs[k:]) + list(durs[:k])
        path = OUT / f"blha_{name}.gif"
        pix.save_gif(frames, path, durs)
        ds = gif_info(path)
        ok = 8 <= len(ds) <= 24 and all(60 <= d <= 140 for d in ds)
        print(f"{'ok ' if ok else 'BAD'} blha_{name}.gif  frames={len(ds):2d}  ms={sum(ds):5d}  "
              f"size={path.stat().st_size / 1024:5.1f} KB  durs={ds if not ok else ''}")
        paths.append(path)
    if not want:
        pix.sheet(paths, HERE / "anim_a_sheet.png")
        print("sheet: anim_a_sheet.png")
    return paths


if __name__ == "__main__":
    main(sys.argv[1:])
