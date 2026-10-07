"""BLHA animated emoji, group anim_b (25 GIFs).

Run:  python3 anim_b.py            -> writes every GIF to animated/ and the contact sheet anim_b_sheet.png
      python3 anim_b.py name ...   -> only those emoji (plus a big frame strip in .anim_b_tmp/ for checking)
Deterministic: every random choice uses a fixed seed.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pix  # noqa: E402
from pix import Canvas  # noqa: E402

OUT = HERE / "animated"
EMOJI = {}


def emoji(name):
    def deco(fn):
        EMOJI[name] = fn
        return fn
    return deco


# ----------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------
# the only two colors outside the PAL letters
GREEN_DK = (36, 112, 52)      # dumpster shading
SMOKE = (88, 92, 99)          # dumpster smoke (between M and N)


def sprite(rows, pal=None, w=None, h=None):
    """Character map -> Canvas sized to the map."""
    h = h or len(rows)
    w = w or max(len(r) for r in rows)
    s = Canvas(w, h)
    s.stamp(rows, 0, 0, pal)
    return s


def keyline(sp: Canvas, pad=1):
    """Outline a sprite on its own canvas (grown by pad) so it keeps a keyline when pasted over art."""
    g = Canvas(sp.w + 2 * pad, sp.h + 2 * pad)
    g.paste(sp, pad, pad)
    g.outline()
    return g


def put(c, sp, x, y):
    """Paste with clipping (negative coordinates allowed)."""
    x, y = int(round(x)), int(round(y))
    if x >= 0 and y >= 0 and x + sp.w <= c.w and y + sp.h <= c.h:
        c.img.alpha_composite(sp.img, (x, y))
    else:
        arr = np.array(sp.img)
        ys, xs = np.nonzero(arr[:, :, 3])
        for j, i in zip(ys, xs):
            X, Y = x + i, y + j
            if 0 <= X < c.w and 0 <= Y < c.h:
                c.img.putpixel((int(X), int(Y)), tuple(int(v) for v in arr[j, i]))


def _scale2x(a):
    P = a
    A = np.concatenate([a[:1], a[:-1]], 0)
    D = np.concatenate([a[1:], a[-1:]], 0)
    C = np.concatenate([a[:, :1], a[:, :-1]], 1)
    B = np.concatenate([a[:, 1:], a[:, -1:]], 1)

    def eq(x, y):
        return np.all(x == y, axis=2)
    o1 = np.where((eq(C, A) & ~eq(C, D) & ~eq(A, B))[..., None], A, P)
    o2 = np.where((eq(A, B) & ~eq(A, C) & ~eq(B, D))[..., None], B, P)
    o3 = np.where((eq(D, C) & ~eq(D, B) & ~eq(C, A))[..., None], C, P)
    o4 = np.where((eq(B, D) & ~eq(B, A) & ~eq(D, C))[..., None], D, P)
    H, W = a.shape[:2]
    out = np.zeros((H * 2, W * 2, 4), np.uint8)
    out[0::2, 0::2], out[0::2, 1::2], out[1::2, 0::2], out[1::2, 1::2] = o1, o2, o3, o4
    return out


def rotsprite(sp: Canvas, angle, cx, cy):
    """RotSprite-style rotation (scale2x x3, rotate, sample) about art pixel (cx, cy). angle: degrees, +ve = CCW."""
    a = np.array(sp.img)
    a[a[:, :, 3] == 0] = 0
    for _ in range(3):
        a = _scale2x(a)
    im = Image.fromarray(a, "RGBA").rotate(angle, resample=Image.NEAREST, center=(cx * 8 + 4, cy * 8 + 4))
    b = np.array(im)[4::8, 4::8]
    out = Canvas(sp.w, sp.h)
    out.img = Image.fromarray(np.ascontiguousarray(b), "RGBA")
    return out


BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def dither_fade(c: Canvas, level):
    """Keep about `level` (0..1) of the pixels in an ordered-dither pattern (GIF has no partial alpha)."""
    if level >= 1:
        return c
    a = np.array(c.img)
    for y in range(c.h):
        for x in range(c.w):
            if BAYER[y % 4][x % 4] >= level * 16:
                a[y, x] = 0
    c.img = Image.fromarray(a, "RGBA")
    return c


def shift(c: Canvas, dx, dy):
    n = Canvas(c.w, c.h)
    put(n, c, dx, dy)
    return n


def recolor(c: Canvas, mapping):
    a = np.array(c.img)
    out = a.copy()
    for src, dst in mapping.items():
        s = np.array(pix.col(src))
        m = np.all(a == s, axis=2)
        out[m] = pix.col(dst) if dst is not None else (0, 0, 0, 0)
    c.img = Image.fromarray(out, "RGBA")
    return c


def sparkle(c, x, y, col="W", size=1):
    c.px(x, y, col)
    for d in range(1, size + 1):
        c.px(x + d, y, col); c.px(x - d, y, col); c.px(x, y + d, col); c.px(x, y - d, col)


# ----------------------------------------------------------------------------------------------
# shared sprites: gold hands
# ----------------------------------------------------------------------------------------------
def make_open_hand(fw=3, tops=(2, 0, 1, 4), palm_y=10, palm_h=8, wrist_h=4, thumb=True):
    """Open hand, palm toward viewer, fingers up. Returns (sprite, wrist_centre_x, wrist_bottom_y)."""
    T = 4 if thumb else 0
    W = T + 4 * fw + 3 + 1
    H = palm_y + palm_h + wrist_h
    s = Canvas(W, H)
    px0 = T
    px1 = T + 4 * fw + 3 - 1          # palm spans px0..px1
    for i, top in enumerate(tops):
        x0 = T + i * (fw + 1)
        s.rect(x0, top, fw, palm_y - top, "G")
        s.rect(x0 + fw - 1, top + 1, 1, palm_y - top - 1, "D")
        s.px(x0, top, "Y")
        if fw >= 4:
            s.px(x0, top + 1, "Y")
    s.rect(px0, palm_y, px1 - px0 + 1, palm_h, "G")
    s.rect(px1, palm_y, 1, palm_h, "D")
    # round the bottom of the palm into the wrist
    s.px(px0, palm_y + palm_h - 1, None)
    s.px(px1, palm_y + palm_h - 1, None)
    s.px(px1 - 1, palm_y + palm_h - 1, "D")
    wx0, wx1 = px0 + 2, px1 - 2
    s.rect(wx0, palm_y + palm_h, wx1 - wx0 + 1, wrist_h, "G")
    s.rect(wx1, palm_y + palm_h - 1, 1, wrist_h + 1, "D")
    # palm crease
    for k in range(3):
        s.px(px0 + 2 + k, palm_y + palm_h - 3 + (k // 2), "D")
    if thumb:
        ty = palm_y - 3
        for j in range(6):
            xa = max(0, j - 2)
            s.rect(xa, ty + j, 3, 1, "G")
        s.px(0, ty, "Y")
        s.px(2, ty + 1, "D"); s.px(2, ty + 2, "D"); s.px(3, ty + 3, "D")
    return s, (wx0 + wx1) / 2, H - 1


def make_fist(w=15, h=12, wrist=4):
    """Front view raised fist: four curled fingers on top, thumb across the front, wrist below."""
    s = Canvas(w, h + wrist)
    s.rect(0, 1, w, h - 1, "G")
    fw = (w + 1) // 4                         # finger column width incl. separator
    for i in range(4):
        x0 = i * fw
        s.rect(x0, 0, fw - 1, 1, "G")
        s.px(x0, 0, "Y")
        if i < 3:
            s.rect(x0 + fw - 1, 1, 1, 5, "D")  # finger separators
    s.px(0, 1, "Y"); s.px(0, 2, "Y")
    # second knuckle row line
    s.rect(1, 5, w - 2, 1, "D")
    # thumb across the front
    s.rect(0, 6, w - 5, 3, "Y")
    s.rect(0, 9, w - 4, 1, "D")
    s.px(w - 5, 7, "D"); s.px(w - 5, 8, "D")
    s.rect(w - 1, 1, 1, h - 1, "D")
    s.rect(0, h - 1, w, 1, "D")
    s.px(0, h - 1, None); s.px(w - 1, h - 1, None)
    s.px(0, 0, None); s.px(w - 1, 0, None)
    s.rect(2, h, w - 4, wrist, "G")
    s.rect(w - 3, h, 1, wrist, "D")
    return s


def thin_keyline(c: Canvas):
    """Drop keyline pixels that no longer touch color (after a rotation doubled them), then re-outline."""
    a = np.array(c.img)
    k = np.array(pix.col("K"))
    isk = np.all(a == k, axis=2)
    filled = (a[:, :, 3] > 0) & ~isk
    H, W = isk.shape
    out = a.copy()
    for y in range(H):
        for x in range(W):
            if isk[y, x]:
                near = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    X, Y = x + dx, y + dy
                    if 0 <= X < W and 0 <= Y < H and filled[Y, X]:
                        near = True
                if not near:
                    out[y, x] = 0
    c.img = Image.fromarray(out, "RGBA")
    c.outline()
    return c


def rot_keyed(c: Canvas, angle, cx, cy):
    """Outline, rotate (keeping inner keylines such as finger gaps), then tidy the keyline."""
    c = c.copy()
    c.outline()
    if angle:
        c = rotsprite(c, angle, cx, cy)
        thin_keyline(c)
    return c


# ----------------------------------------------------------------------------------------------
# faces
# ----------------------------------------------------------------------------------------------
def eye(c, ex, ey, pdx=2, lid=0, pdy=1, w=6, h=4, pw=2, ph=2):
    """Boxed cartoon eye: K rim, W sclera (w x h at ex, ey), K pupil; lid rows close from the top."""
    c.rect(ex - 1, ey - 1, w + 2, h + 2, "K")
    c.px(ex - 1, ey - 1, "G"); c.px(ex + w, ey - 1, "G")
    c.px(ex - 1, ey + h, "G"); c.px(ex + w, ey + h, "G")
    c.rect(ex, ey, w, h, "W")
    c.rect(ex + pdx, ey + pdy, pw, ph, "K")
    if lid:
        c.rect(ex - 1, ey - 1, w + 2, lid, "G")
        c.rect(ex - 1, ey - 1 + lid, w + 2, 1, "K")
        c.px(ex - 1, ey - 1, "G"); c.px(ex + w, ey - 1, "G")


# ----------------------------------------------------------------------------------------------
# 1. side-eye
# ----------------------------------------------------------------------------------------------
@emoji("blha_sideeye")
def sideeye():
    # (lid, pupil x 0..4, suspicious, brow twitch, mouth shift, ms)
    seq = [
        (0, 2, 0, 0, 0, 120), (1, 2, 1, 0, 0, 70), (2, 2, 1, 0, 0, 80),
        (2, 1, 1, 0, -1, 70), (2, 0, 1, 0, -2, 110), (3, 0, 1, 0, -2, 120), (3, 0, 1, 1, -2, 120),
        (2, 0, 1, 0, -2, 110),
        (2, 2, 1, 0, 0, 70), (2, 4, 1, 0, 2, 110), (3, 4, 1, 0, 2, 120), (3, 4, 1, -1, 2, 120),
        (2, 4, 1, 0, 2, 110),
        (2, 2, 1, 0, 0, 80), (1, 2, 1, 0, 0, 90),
    ]
    frames, durs = [], []
    for lid, pdx, sus, twitch, ms, d in seq:
        c = pix.face()
        ey = 11
        for side, ex in ((0, 7), (1, 18)):
            eye(c, ex, ey, pdx=pdx, lid=lid, pdy=1 if lid < 2 else 2, w=7, h=5, pw=3, ph=3)
            for i in range(9):
                x = ex - 1 + i
                inner = (i >= 5) if side == 0 else (i <= 3)
                if not sus:
                    c.px(x, 7, "K"); c.px(x, 8, "K")
                    continue
                y = ey - 1 + lid - 3 + (1 if inner else 0)
                if twitch and ((twitch > 0 and side == 0) or (twitch < 0 and side == 1)) and not inner:
                    y -= 1
                c.px(x, y, "K"); c.px(x, y - 1, "K")
        if ms == 0:
            c.rect(12, 22, 8, 1, "K")
        else:
            x0 = 13 + ms * 2
            c.rect(x0, 22, 6, 1, "K")
            c.px(x0 + (5 if ms < 0 else 0), 21, "K")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 2. facepalm
# ----------------------------------------------------------------------------------------------
def _palm_over(angle, light=True):
    """Open hand rotated so the fingers point up-left; returns (canvas 48x48, palm center)."""
    h, wx, wy = make_open_hand(fw=2, tops=(2, 0, 1, 4), palm_y=9, palm_h=7, wrist_h=14)
    big = Canvas(48, 48)
    put(big, h, 16, 12)
    pcx, pcy = 16 + 9, 12 + 12
    r = rot_keyed(big, angle, pcx, pcy)
    if light:
        recolor(r, {"G": "Y", "D": "G", "Y": "W"})
    return r, (pcx, pcy)


@emoji("blha_facepalm")
def facepalm():
    ANG = 62
    hand, (pcx, pcy) = _palm_over(ANG)
    ux, uy = math.sin(math.radians(ANG)), math.cos(math.radians(ANG))
    # (face dy, eyes, mouth, hand t (None = no hand, 0 = on face, 1 = off), head shake x, fx, ms)
    seq = [
        (0, "annoyed", "flat", None, 0, None, 120),
        (0, "squint", "flat", None, 0, None, 100),
        (0, "squint", "flat", 1.0, 0, None, 70),
        (0, "squint", "flat", 0.45, 0, None, 70),
        (1, "squint", "flat", 0.0, 0, "slap", 80),
        (2, "squint", "frown", 0.0, 0, "slap2", 100),
        (2, "squint", "frown2", 0.0, -1, None, 120),
        (2, "squint", "frown", 0.0, 1, None, 120),
        (2, "squint", "frown2", 0.0, -1, None, 120),
        (2, "squint", "frown", 0.0, 0, None, 120),
        (2, "closed", "frown", 0.35, 0, None, 70),
        (2, "closed", "frown", 0.8, 0, None, 70),
        (2, "closed", "frown", None, 0, None, 120),
        (1, "closed", "frown2", None, 0, None, 120),
        (1, "annoyed", "flat", None, 0, None, 110),
    ]
    frames, durs = [], []
    for dy, eyes, mouth, t, shake, fx, d in seq:
        c = pix.face(cy=15.5 + dy)
        ey = 12 + dy
        for ex in (7, 18):
            if eyes == "annoyed":
                eye(c, ex, ey, pdx=2, pdy=2, lid=2, w=7, h=5, pw=3, ph=3)
                c.rect(ex - 1, ey - 3, 9, 1, "K")
            elif eyes == "squint":
                eye(c, ex, ey, pdx=2, pdy=3, lid=3, w=7, h=5, pw=3, ph=2)
                c.rect(ex - 1, ey - 2, 9, 1, "K")
            else:   # closed, droopy
                c.rect(ex, ey + 2, 7, 1, "K")
                c.px(ex - 1 if ex < 15 else ex + 7, ey + 3, "K")
        my = 22 + dy
        if mouth == "flat":
            c.rect(12, my, 8, 1, "K")
        elif mouth == "frown":
            c.rect(13, my, 6, 1, "K"); c.px(12, my + 1, "K"); c.px(19, my + 1, "K")
        else:
            c.rect(13, my, 2, 1, "K"); c.rect(15, my - 1, 2, 1, "K"); c.rect(17, my, 2, 1, "K")
            c.px(12, my + 1, "K"); c.px(19, my + 1, "K")
        if t is not None:
            tx, ty = 13 + t * 22 * ux, 11 + dy + t * 22 * uy
            put(c, hand, round(tx - pcx), round(ty - pcy))
        if fx in ("slap", "slap2"):
            n = 3 if fx == "slap" else 2
            for (x0, y0, dx, dy2) in ((2, 6, -1, -1), (7, 2, 0, -1), (2, 19, -1, 1)):
                for i in range(n):
                    c.px(x0 + dx * i, y0 + dy2 * i, "W")
        if shake:
            c = shift(c, shake, 0)
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 3. clap
# ----------------------------------------------------------------------------------------------
def make_flat_hand(fw=3, tops=(2, 0, 1, 3), palm_y=9, palm_h=6, wrist_h=12):
    """Fingers held together (clapping / pointing hand), thumb out on the left."""
    T = 4
    W = T + 4 * fw + 1
    H = palm_y + palm_h + wrist_h
    s = Canvas(W, H)
    for i, top in enumerate(tops):
        x0 = T + i * fw
        s.rect(x0, top, fw, palm_y - top + 1, "G")
        s.px(x0, top, "Y")
        if i > 0:
            s.rect(x0, max(top, tops[i - 1]) + 1, 1, palm_y - max(top, tops[i - 1]) - 2, "D")
    px1 = T + 4 * fw - 1
    s.rect(T, palm_y, 4 * fw, palm_h, "G")
    s.rect(px1, tops[3] + 1, 1, palm_y + palm_h - tops[3] - 1, "D")
    s.rect(T + 1, palm_y + palm_h, 4 * fw - 2, wrist_h, "G")
    s.rect(px1 - 1, palm_y + palm_h, 1, wrist_h, "D")
    ty = palm_y - 2
    for j in range(6):
        s.rect(max(0, j - 2), ty + j, 3, 1, "G")
    s.px(0, ty, "Y")
    s.px(2, ty + 1, "D"); s.px(2, ty + 2, "D"); s.px(3, ty + 3, "D")
    return s


def _clap_left(h, ang, inner, py=33):
    """Left hand leaning right by ang degrees, wrist below the bottom-left, inner edge at x = inner."""
    def make(gx):
        L = Canvas(32, 40); put(L, h, gx - 9, py - h.h + 2)
        return L
    best = None
    for gx in range(-12, 12):
        L = rotsprite(make(gx), -ang, gx, py)
        xs = np.nonzero(np.array(L.img)[:, :, 3].any(axis=0))[0]
        if len(xs) and xs.max() <= inner:
            best = gx
    L = rot_keyed(make(best), -ang, best, py)
    out = Canvas(); put(out, L, 0, 0)
    return out


@emoji("blha_clap")
def clap():
    h = make_flat_hand(fw=3, tops=(2, 0, 1, 3), palm_y=10, palm_h=6, wrist_h=10)
    # (lean angle, inner edge x, burst stage, ms)
    seq = [(8, 10, 0, 90), (16, 13, 0, 60), (22, 15, 1, 70), (20, 14, 2, 80), (12, 11, 3, 70),
           (6, 9, 0, 90), (16, 13, 0, 60), (22, 15, 1, 70), (20, 14, 2, 80), (12, 11, 3, 70)]
    frames, durs = [], []
    for k, (ang, inner, burst, d) in enumerate(seq):
        L = _clap_left(h, ang, inner)
        R = L.copy().flip()
        c = Canvas()
        c.paste(L); c.paste(R)
        if burst:
            # impact lines radiate from the contact point at the fingertips
            ys = np.nonzero(np.array(c.img)[:, :, 3].any(axis=1))[0]
            top = int(ys.min())
            r0, r1 = {1: (1, 4), 2: (2, 5), 3: (4, 6)}[burst]
            for r in range(r0, r1):
                c.px(15, top - 1 - r, "Y"); c.px(16, top - 1 - r, "Y")
                c.px(12 - r, top - r, "Y"); c.px(13 - r, top - r, "Y")
                c.px(18 + r, top - r, "Y"); c.px(19 + r, top - r, "Y")
            if burst == 2 and k > 5:
                sparkle(c, 4, 3, "W"); sparkle(c, 27, 3, "W")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 4. hello (wave)
# ----------------------------------------------------------------------------------------------
def arc(c, cx, cy, r, a0, a1, colr, step=1.5):
    """Arc of radius r around (cx, cy) between angles a0..a1 (degrees from straight up, +ve = right)."""
    pts = set()
    a = a0
    while (a <= a1) if a0 <= a1 else (a >= a1):
        x = cx + r * math.sin(math.radians(a))
        y = cy - r * math.cos(math.radians(a))
        pts.add((int(round(x)), int(round(y))))
        a += step if a0 <= a1 else -step
    for x, y in pts:
        c.px(x, y, colr)


@emoji("blha_hello")
def hello():
    h, wx, wy = make_open_hand(fw=4, tops=(2, 0, 1, 5), palm_y=11, palm_h=9, wrist_h=7)
    PX, PY = 16, 34
    # (tilt: +ve = fingers to the left, motion arcs side (-1 left, +1 right, 0 none),
    #  finger lag (-ve = fingers trail left), ms)
    seq = [(0, 0, -1, 80), (-13, -1, -2, 70), (-24, -1, 1, 110), (-13, 0, 2, 70),
           (0, 0, 1, 70), (13, 1, 2, 70), (24, 1, -1, 110), (13, 0, -2, 70)]

    def lagged(lag):
        s = Canvas(h.w + 6, h.h)
        a = np.array(h.img)
        for y in range(h.h):
            dx = int(round(lag * max(0, 11 - y) / 6)) if lag else 0
            for x in range(h.w):
                if a[y, x, 3]:
                    s.px(x + 3 + dx, y, tuple(int(v) for v in a[y, x, :3]))
        return s
    frames, durs = [], []
    for ang, arcs, lag, d in seq:
        base = Canvas(32, 40)
        put(base, lagged(lag), PX - wx - 3.5, PY - wy)
        hand = rot_keyed(base, ang, PX, PY)
        c = Canvas()
        if arcs:
            # trailing motion arcs on the side the hand swung away from
            tip = -ang                       # hand direction in degrees from up (+ve = right)
            for r, (s0, s1) in ((27, (30, 46)), (21, (34, 50))):
                a0, a1 = (tip + s0, tip + s1) if arcs > 0 else (tip - s1, tip - s0)
                arc(c, PX, PY, r, a0, a1, "W")
        put(c, hand, 0, 0)
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 5. fist pump
# ----------------------------------------------------------------------------------------------
BIG = {   # chunky 2-px-stroke letters for text emoji
    "Y": ["##..##", "##..##", "##..##", ".####.", "..##..", "..##..", "..##..", "..##.."],
    "E": ["#####", "#####", "##...", "####.", "####.", "##...", "#####", "#####"],
    "S": [".#####", "######", "##....", "#####.", ".#####", "....##", "######", "#####."],
}


def big_text(c, x, y, s, colr, font=BIG, gap=1):
    for ch in s:
        g = font[ch]
        for j, row in enumerate(g):
            for i, b in enumerate(row):
                if b == "#":
                    c.px(x + i, y + j, colr)
        x += len(g[0]) + gap
    return x


def starburst(c, cx, cy, rx, ry, n, inner, colr, phase=0.0):
    pts = []
    for i in range(2 * n):
        a = math.pi * i / n + phase
        k = 1 if i % 2 == 0 else inner
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    c.poly(pts, colr)


@emoji("blha_fistpump")
def fistpump():
    # (fist top y, squash, speed lines, burst stage, jitter, ms)
    seq = [
        (3, 0, 0, 0, 0, 110), (1, 0, 0, 0, 0, 80), (15, 1, 1, 0, 0, 60), (13, 0, 0, 1, 0, 70),
        (13, 0, 0, 2, 0, 90), (5, 0, 0, 0, 0, 70), (1, 0, 0, 0, 0, 70), (15, 1, 0, 3, 0, 60),
        (13, 0, 0, 3, 1, 90), (13, 0, 0, 3, -1, 90), (13, 0, 0, 2, 0, 110), (8, 0, 0, 0, 0, 80),
    ]
    frames, durs = [], []
    for fy, squash, lines, burst, jit, d in seq:
        c = Canvas()
        if burst:
            b = Canvas()
            s = {1: 0.6, 2: 1.0, 3: 1.12}[burst]
            starburst(b, 15.5, 6.5, 15.5 * s, 8.5 * s, 9, 0.68, "R", phase=0.17 * burst)
            starburst(b, 15.5, 6.5, 12.5 * s, 6.8 * s, 9, 0.7, "F", phase=0.17 * burst + 0.35)
            if burst >= 2:
                big_text(b, 6 + jit, 3, "YES", "W")
            else:
                for x, y in ((10, 6), (15, 4), (21, 7)):
                    sparkle(b, x, y, "Y")
            put(c, b, 0, 0)
        if lines:
            for x, y0 in ((8, 2), (15, 0), (23, 3)):
                c.rect(x, y0, 1, 8, "W")
        w, hh = (17, 10) if squash else (15, 12)
        f = make_fist(w=w, h=hh, wrist=4)
        fx = 16 - w // 2
        put(c, keyline(f), fx - 1, fy - 1)
        # forearm down to the bottom edge
        top = fy + hh + 3
        if top < 32:
            arm = Canvas()
            arm.rect(fx + 2, top, w - 4, 32 - top, "G")
            arm.rect(fx + w - 3, top, 1, 32 - top, "D")
            arm.outline()
            for y in range(top, 32):
                for x in range(32):
                    p = arm.get(x, y)
                    if p[3]:
                        c.px(x, y, p[:3])
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 6. knee slide
# ----------------------------------------------------------------------------------------------
KNEEL_ARM_UP = [
    "....AA................",
    "...AAAA...............",
    "...AAAA...............",
    "....GG................",
    "....GG................",
    "....GG..MMMMM.........",
    "....GG.MMMMMMM........",
    "....GG.MMMMMMMM.......",
    "....GG.MMMMLLLL.......",
    "....GGGMMMMLLLL.......",
    "....GGGGMMMMMM........",
    ".....GGGGGGGGGG.......",
    ".....GGGGGGGGGGG......",
    ".....GGGGGGGGGGGGGAA..",
    ".....KKKKKKKKKK..AAA..",
    ".....GGGGGGGGGG...O...",
    ".....GGGGGGGGGG...O...",
    ".....AAAAAAAAAA....O..",
    ".....AAAAAAAAAAAAA.O..",
    "....AAAAA...AAAAAA..O.",
    "...AAAA......AAAA...O.",
    "S.AAAA.......AAAA....O",
    "SAAAAA.......AAAA..OOO",
    "SAAAAAA.....SSSSSS....",
]
KNEEL_ARM_MID = [
    "......................",
    "......................",
    "......................",
    "......................",
    ".AA...................",
    "AAAA....MMMMM.........",
    "AAAA...MMMMMMM........",
    ".GG....MMMMMMMM.......",
    ".GGG...MMMMLLLL.......",
    "..GGG..MMMMLLLL.......",
    "...GGGGGMMMMMM........",
    "....GGGGGGGGGG........",
    ".....GGGGGGGGGGG......",
    ".....GGGGGGGGGGGGGAA..",
    ".....KKKKKKKKKK..AAA..",
    ".....GGGGGGGGGG...O...",
    ".....GGGGGGGGGG...O...",
    ".....AAAAAAAAAA....O..",
    ".....AAAAAAAAAAAAA.O..",
    "....AAAAA...AAAAAA..O.",
    "...AAAA......AAAA...O.",
    "S.AAAA.......AAAA....O",
    "SAAAAA.......AAAA..OOO",
    "SAAAAAA.....SSSSSS....",
]


@emoji("blha_kneeslide")
def kneeslide():
    up, mid = sprite(KNEEL_ARM_UP), sprite(KNEEL_ARM_MID)
    rng = random.Random(7)
    xs = [-13, -7, -2, 2, 5, 7, 8, 9, 9, 9, 9, 9, 9, 9, 9, 9]
    speed = [8, 8, 7, 5, 4, 3, 2, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    arms = ["up"] * 10 + ["mid", "up", "mid", "up", "mid", "up"]
    durs = [70, 70, 70, 70, 80, 80, 90, 90, 100, 100, 90, 90, 90, 90, 110, 120]
    # snow particles: (birth frame, start x offset, vy, vx, size)
    parts = []
    for b in range(0, 10):
        for _ in range(3 + speed[b] // 2):
            parts.append((b, rng.uniform(-1, 2), rng.uniform(1.2, 1.2 + 0.35 * speed[b] + 0.5),
                          rng.uniform(-2.2, -0.6), 2 if rng.random() < 0.7 else 1))
    frames = []
    GY = 28   # blade row
    for f, (x, arm) in enumerate(zip(xs, arms)):
        c = Canvas()
        c.rect(0, GY + 1, 32, 2, "I")
        c.rect(0, GY + 3, 32, 1, "L")
        for k in range(4):
            c.px((k * 9 + 3) % 32, GY + 2, "W")
        kx = x + 2
        if kx > 0:                                   # scratch left in the ice by the knee
            c.rect(0, GY + 1, kx, 1, "L")
        # low snow drift piling up behind the knee
        for k in range(min(f, 9)):
            hx = xs[max(0, f - k)] - 1 - k
            hh = max(0, 2 - k // 3) if speed[max(0, f - k)] > 0 else 0
            if hh and 0 <= hx < 32:
                c.rect(hx, GY + 1 - hh, 2, hh, "W")
        for (b, ox, vy, vx, sz) in parts:
            age = f - b
            if age < 0 or age > 5:
                continue
            px_ = xs[b] + 1 + ox + vx * age * 1.5
            py_ = GY - 1 - vy * age * 1.4 + 0.45 * age * age
            if py_ > GY:
                continue
            s = sz if age < 4 else 1
            c.rect(int(round(px_)), int(round(py_)), s, s, "W" if age < 3 else "I")
        put(c, up if arm == "up" else mid, x, GY - 23)
        c.outline()
        frames.append(c)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 7. glass bang
# ----------------------------------------------------------------------------------------------
@emoji("blha_glassbang")
def glassbang():
    near = make_fist(w=15, h=12, wrist=3)
    far = recolor(make_fist(w=11, h=9, wrist=3), {"G": "D", "Y": "G", "D": "o"})
    # (left fist: 'hit'/'back', right fist, glass shake dx, rattle, ms)
    seq = [
        ("back", "back", 0, 0, 100), ("hit", "back", -1, 1, 70), ("back", "back", 1, 2, 70),
        ("back", "hit", 1, 1, 70), ("back", "back", -1, 2, 70), ("hit", "back", -1, 1, 70),
        ("back", "back", 1, 2, 70), ("back", "hit", 1, 1, 70), ("back", "back", -1, 2, 70),
        ("hit", "hit", 0, 3, 80), ("back", "back", 1, 2, 80), ("back", "back", -1, 1, 90),
    ]
    frames, durs = [], []
    for lf, rf, sh, rat, d in seq:
        c = Canvas()
        g = Canvas()
        g.rect(2, 4, 28, 19, "L")
        g.rect(2, 4, 1, 19, "S"); g.rect(29, 4, 1, 19, "S"); g.rect(2, 4, 28, 1, "S")
        order = sorted(((0, lf), (1, rf)), key=lambda t: t[1] == "hit")   # hitting fist drawn last
        for side, state in order:
            f = near if state == "hit" else far
            cx = 9 if side == 0 else 22
            fy = 7 if state == "hit" else 11
            fx = cx - f.w // 2
            arm = Canvas()
            armc = "G" if state == "hit" else "D"
            arm.rect(fx + 3, fy + f.h, f.w - 6, 24 - fy - f.h, armc)
            arm.outline()
            put(g, arm, 0, 0)
            put(g, keyline(f), fx - 1, fy - 1)
            if state == "hit":
                g.rect(fx + 1, fy, f.w - 2, 1, "W")
                # impact ticks on the glass around the fist
                for (x, y, dx, dy) in ((fx - 2, fy - 1, -1, -1), (fx + f.w + 1, fy - 1, 1, -1),
                                       (fx - 2, fy + 6, -1, 0), (fx + f.w + 1, fy + 6, 1, 0)):
                    for i in range(2):
                        X, Y = x + dx * i, y + dy * i
                        if 3 <= X <= 28 and 5 <= Y:
                            g.px(X, Y, "W")
        # glare streaks over everything behind the glass
        for (bx, by, n) in ((3, 12, 8), (3, 16, 12), (21, 22, 7)):
            for i in range(n):
                x, y = bx + i, by - i
                if 3 <= x <= 28 and 5 <= y <= 22:
                    g.px(x, y, "W")
        put(c, g, sh, 0)
        # boards in front (they stay put)
        c.rect(0, 23, 32, 1, "N")
        c.rect(0, 24, 32, 4, "W")
        c.rect(0, 28, 32, 1, "S")
        c.rect(0, 29, 32, 2, "G")
        if rat:   # rattle marks above the shaking pane
            marks = [(5, 1), (15, 0), (25, 1)] if rat != 2 else [(8, 0), (20, 1)]
            if rat == 3:
                marks = [(4, 1), (10, 0), (16, 1), (22, 0), (27, 1)]
            for (x, y) in marks:
                c.rect(x + sh, y, 2 if rat == 3 else 1, 2, "W")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 8. board check
# ----------------------------------------------------------------------------------------------
SKATER_SIDE = [   # side view, facing right; J jersey, T trim, H glove, O stick
    ".....MMMM........",
    "....MMMMMM.......",
    "...MMMMMMMM......",
    "...MMMMMLLL......",
    "...MMMMMLLL......",
    "....MMMMMM.......",
    "...JJJJJJJ.......",
    "..JJJJJJJJJ......",
    "..JJJJJJJJJJ.....",
    "..JJJJJJJJJHH....",
    "..TTTTTTTT.HH....",
    "..JJJJJJJJ..O....",
    "..JJJJJJJJ...O...",
    "...AAAAAA....O...",
    "...AAAAAAA....O..",
    "...AAA.AAA....O..",
    "...AA...AA.....O.",
    "...AA...AA.....O.",
    "..AAA..AAA.....O.",
    "..AAAA.AAAA...OOO",
    ".SSSSS.SSSSS.....",
]


def skater(team="gold", lean=0, flip=False, stick=True):
    pal = {"J": "G", "T": "K", "H": "A"} if team == "gold" else {"J": "B", "T": "W", "H": "A"}
    s = Canvas(17 + 4, 21)
    for j, row in enumerate(SKATER_SIDE):
        dx = int(round(lean * max(0, 13 - j) / 13))
        for i, ch in enumerate(row):
            if ch == "O" and not stick:
                continue
            if ch not in ". ":
                s.px(i + (dx if ch != "O" or j < 12 else dx // 2), j, pal.get(ch, ch))
    if flip:
        s.flip()
    return s


def squash_x(sp: Canvas, keep):
    """Horizontally squash by dropping columns (keep = fraction)."""
    a = np.array(sp.img)
    xs = np.nonzero(a[:, :, 3].any(axis=0))[0]
    x0, x1 = xs.min(), xs.max()
    w = x1 - x0 + 1
    nw = max(1, int(round(w * keep)))
    out = Canvas(sp.w, sp.h)
    for nx in range(nw):
        sx = x0 + int(nx * w / nw)
        for y in range(sp.h):
            if a[y, sx, 3]:
                out.px(x1 - nw + 1 + nx, y, tuple(int(v) for v in a[y, sx, :3]))
    return out


def boards(c, dx=0, wob=0):
    """Side-on dasher board + glass at the right edge."""
    x0 = 25 + dx
    c.rect(x0 + 1 + wob, 1, 4, 13, "L")           # glass
    c.rect(x0 + 1 + wob, 1, 1, 13, "I")
    c.rect(x0, 14, 7, 1, "N")                      # top rail
    c.rect(x0, 15, 7, 11, "W")                     # board
    c.rect(x0, 15, 1, 11, "S")
    c.rect(x0, 26, 7, 3, "G")                      # kick plate


BLUE_BUCKLE = [   # pinned and sagging down the boards, facing left
    "......MMMM....",
    ".....MMMMMM...",
    "....LLMMMMMM..",
    "....LLMMMMMM..",
    "......MMMM....",
    ".....BBBBBBB..",
    "....BBBBBBBB..",
    "...HHBBBBBBB..",
    "....WWWWWWWW..",
    ".....BBBBBBB..",
    ".....AAAAAAA..",
    "...AAAAAAAAA..",
    "..AAAA...AAA..",
    "..AAA....AAA..",
    ".SSSS...SSSS..",
]
BLUE_HEAP = [     # crumpled against the boards, legs out on the ice
    "...........MMMM.",
    "..........MMMMMM",
    ".........LLMMMMM",
    ".........LLMMMMM",
    "..........MMMM..",
    ".........BBBBBB.",
    "........BBBBBBB.",
    ".......HHBBBBBB.",
    "........WWWWWWW.",
    "AA.......BBBBBB.",
    "AAAAAAAAAAAAAAA.",
    "AAAAAAAAAAAAAA..",
    "SSS.............",
]


@emoji("blha_boardcheck")
def boardcheck():
    blue_up = skater("blue", flip=True, stick=False)
    pal = {"H": "A"}
    buckle, heap = sprite(BLUE_BUCKLE, pal), sprite(BLUE_HEAP, pal)
    frames, durs = [], []
    ICE = 29
    # (gold x, gold lean, blue state, board dx, glass wobble, fx, ms)
    seq = [
        (-9, 0, "stand", 0, 0, None, 100), (-5, 2, "stand", 0, 0, "speed", 70), (-1, 3, "stand", 0, 0, "speed", 60),
        (3, 3, "squash", 1, 1, "boom", 70), (3, 2, "squash", -1, -1, "boom2", 70), (2, 1, "squash", 1, 1, None, 70),
        (0, 0, "buckle", -1, -1, None, 80), (-2, 0, "heap", 0, 1, "stars0", 100), (-3, 0, "heap", 0, 0, "stars1", 110),
        (-3, 0, "heap", 0, 0, "stars2", 110), (-3, 0, "heap", 0, 0, "stars0", 110), (-3, 0, "heap", 0, 0, "stars1", 110),
        (-3, 0, "heap", 0, 0, "stars2", 120),
    ]
    for gx, lean, bstate, bdx, wob, fx, d in seq:
        c = Canvas()
        c.rect(0, ICE, 32, 2, "I")
        c.rect(0, ICE + 2, 32, 1, "L")
        boards(c, bdx, wob)
        wall = 25 + bdx
        if bstate == "stand":
            put(c, blue_up, wall - 21, ICE - 21)
        elif bstate == "squash":
            put(c, squash_x(blue_up, 0.6), wall - 21, ICE - 21)
        elif bstate == "buckle":
            put(c, buckle, wall - 14, ICE - 15)
        else:
            put(c, heap, wall - 16, ICE - 13)
        put(c, skater("gold", lean=lean), gx, ICE - 21)
        if wob:
            for (x, y) in ((wall - 1, 2), (wall - 1, 6), (wall + 6, 4)):
                c.rect(x + (wob if x < wall else 0), y, 1, 2, "W")
        if fx == "speed":
            for yy in (7, 11, 15):
                if gx > -2:
                    c.rect(max(0, gx - 2), ICE - 21 + yy, 4, 1, "W")
        if fx in ("boom", "boom2"):
            cx, cy = wall - 11, ICE - 13
            s = 1.0 if fx == "boom" else 0.65
            starburst(c, cx, cy, 5 * s, 5 * s, 6, 0.45, "Y", phase=0.3 if fx == "boom" else 0)
            starburst(c, cx, cy, 2.5 * s, 2.5 * s, 6, 0.5, "W", phase=0.3 if fx == "boom" else 0)
        if fx and fx.startswith("stars"):
            k = int(fx[-1])
            hx, hy = wall - 3, ICE - 16
            for i in range(3):
                ang = (i / 3 + k / 9) * 2 * math.pi
                sparkle(c, int(round(hx + 4 * math.cos(ang))), int(round(hy + 1.5 * math.sin(ang))), "Y")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 9. rat
# ----------------------------------------------------------------------------------------------
RAT = [
    "..............NN......",
    ".............NPPN.....",
    ".............NPPN.....",
    "........SSSSSSPPSS....",
    "......SSSSSSSSSSSSS...",
    "....SSSSSSSSSSSSSKSS..",
    "...SSSSSSSSSSSSSSSSSS.",
    "..SSSSSSSSSSSSSSSSSSSP",
    "..SSSSSSSSSSSSSSSSSS..",
    "..NSSSSSSSSSSSSSSSW...",
    "..NNSSSSSSSSSSSWWW....",
    "...NNNSSSSSSSWWW......",
    "....NNNNNNNNNNN.......",
]


def draw_rat(c, x, y, legs=0, head=0, nose=0, tail=0.0, tail_amp=1.0, bob=0, blink=False):
    """legs: 0 standing, 1/2 running; head: -1 up; nose 0/1 twitch; tail: wave phase."""
    s = sprite(RAT)
    y += bob
    # body (x < 12) and head (x >= 12) so the head can lift
    body = Canvas(22, 13); head_c = Canvas(22, 13)
    a = np.array(s.img)
    for j in range(13):
        for i in range(22):
            if a[j, i, 3]:
                (body if i < 12 else head_c).px(i, j, tuple(int(v) for v in a[j, i, :3]))
    put(c, body, x, y)
    if blink:
        head_c.px(17, 5, "S")
    put(c, head_c, x, y + head)
    # nose twitch: nose pixel hops up and down
    c.px(x + 21, y + 7 + head - nose, "P")
    if nose:
        c.px(x + 21, y + 7 + head, None)
    # whiskers
    wy = y + 7 + head
    for (dy0, dy1) in ((-1, -2 - nose), (0, 1 - nose)):
        c.px(x + 22, wy + dy0, "W"); c.px(x + 23, wy + dy1, "W")
    # feet
    fy = y + 13
    feet = {0: (5, 12), 1: (3, 13), 2: (6, 10)}[legs]
    for fx in feet:
        c.rect(x + fx, fy, 2, 1, "P")
    if legs:
        c.rect(x + feet[0] + (1 if legs == 1 else 0), fy - 1, 1, 1, "N")
    # tail: from the rump, waving
    px_, py_ = x + 2, y + 9
    for t in range(1, 12):
        tx = px_ - t
        ty = py_ + int(round(tail_amp * (1.4 * math.sin(t * 0.55 + tail) - t * 0.15)))
        c.px(tx, ty, "P")
        if t < 4:
            c.px(tx, ty + 1, "P")


@emoji("blha_rat")
def rat():
    GY = 26
    # (x, legs, head, nose, tail phase, tail amp, bob, puff, blink, ms)
    seq = [
        (-17, 2, 0, 0, 1.2, 0.5, -1, 0, 0, 70),
        (-10, 1, 0, 0, 2.4, 0.5, 0, 0, 0, 70), (-3, 2, 0, 0, 3.6, 0.5, -1, 0, 0, 70),
        (4, 0, 0, 0, 4.2, 0.8, 0, 1, 0, 90), (6, 0, 0, 0, 4.4, 1.0, 0, 2, 0, 90),
        (6, 0, -1, 1, 4.4, 1.0, 0, 0, 0, 90), (6, 0, -1, 0, 4.4, 1.0, 0, 0, 0, 80),
        (6, 0, -1, 1, 4.4, 1.0, 0, 0, 0, 90), (6, 0, 0, 0, 5.6, 1.4, 0, 0, 0, 90),
        (6, 0, 0, 0, 7.0, 1.6, 0, 0, 1, 90), (6, 0, 0, 1, 8.4, 1.4, 0, 0, 0, 90),
        (6, 0, -1, 0, 9.4, 1.0, 0, 0, 0, 90), (7, 1, 0, 0, 10.0, 0.5, 0, 0, 0, 70),
        (13, 2, 0, 0, 11.2, 0.5, -1, 0, 0, 70), (20, 1, 0, 0, 12.4, 0.5, 0, 0, 0, 70),
        (27, 2, 0, 0, 13.6, 0.5, -1, 0, 0, 70), (34, 1, 0, 0, 14.8, 0.5, 0, 0, 0, 70),
    ]
    frames, durs = [], []
    for x, legs, head, nose, tph, tamp, bob, puff, blink, d in seq:
        c = Canvas()
        c.rect(0, GY + 2, 32, 2, "I")
        c.rect(0, GY + 4, 32, 1, "L")
        for k in range(3):
            c.px((k * 11 + 5 + x // 3) % 32, GY + 3, "W")
        draw_rat(c, x, GY - 12, legs, head, nose, tph, tamp, bob, blink)
        if puff:   # skid stop: little ice spray at the front feet
            for (px_, py_) in ((x + 20, GY), (x + 22, GY - 1 - puff), (x + 24, GY)):
                c.rect(px_, py_, 2 if puff == 1 else 1, 2 if puff == 1 else 1, "W")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 10. dice
# ----------------------------------------------------------------------------------------------
PIPS = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)], 5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}


def die(c, cx, cy, value, ang, half=5.5, pip="K", face="W", side="S"):
    """A chunky die: square face rotated by ang degrees with a shaded depth edge."""
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def rot(x, y):
        return cx + x * ca - y * sa, cy + x * sa + y * ca
    corners = [rot(-half, -half), rot(half, -half), rot(half, half), rot(-half, half)]
    c.poly([(x + 1.5, y + 1.5) for x, y in corners], side)
    c.poly(corners, face)
    for (u, v) in PIPS[value]:
        x, y = rot(u * 3.0, v * 3.0)
        c.rect(int(math.floor(x)), int(math.floor(y)), 2, 2, pip)


@emoji("blha_dice")
def dice():
    # per frame: (die A: x, y, value, angle) (die B: ...)
    ya = [-1, 6, 12, 17, 12, 15, 17, 16, 17, 17, 17, 17, 17, 17]
    yb = [-7, 0, 7, 13, 17, 12, 16, 17, 16, 17, 17, 17, 17, 17]
    xa = [3, 4, 5, 6, 6, 7, 7, 8, 8, 8, 8, 8, 8, 8]
    xb = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 23, 23, 23, 23]
    aa = [10, 45, 80, 115, 140, 165, 175, 180, 180, 180, 180, 180, 180, 180]
    ab = [-20, -55, -90, -125, -150, -170, -180, -185, -180, -180, -180, -180, -180, -180]
    va = [2, 6, 3, 1, 5, 2, 4, 4, 4, 4, 4, 4, 4, 4]
    vb = [5, 1, 4, 2, 6, 3, 5, 6, 6, 6, 6, 6, 6, 6]
    durs = [70, 70, 70, 70, 80, 80, 80, 90, 100, 110, 110, 110, 110, 120]
    frames = []
    for f in range(len(ya)):
        c = Canvas()
        for (x, y, v, a) in ((xb[f], yb[f], vb[f], ab[f]), (xa[f], ya[f], va[f], aa[f])):
            d1 = Canvas()
            die(d1, x + 0.5, y + 0.5, v, a, half=6.0)
            d1.outline()
            c.paste(d1)
        if f >= 9:      # the result twinkles
            k = f - 9
            spots = [None, (3, 9), (14, 8), (19, 9), (29, 8)]
            if spots[k]:
                sparkle(c, spots[k][0], spots[k][1], "Y", 1)
        c.outline()
        frames.append(c)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 11. lottery drum
# ----------------------------------------------------------------------------------------------
def ball(c, x, y, colr, r=2):
    b = Canvas(2 * r + 3, 2 * r + 3)
    b.circle(r + 1, r + 1, r, colr)
    b.px(r, r, "W")
    b.outline()
    put(c, b, x - r - 1, y - r - 1)


@emoji("blha_lottery")
def lottery():
    CX, CY, R = 12, 12, 11
    cols = ["R", "B", "E", "V", "F", "P", "L"]
    rng = random.Random(11)
    n = 16
    # winning ball once it drops: (x, y, radius)
    gold = {8: (19, 20, 2), 9: (24, 22, 2), 10: (27, 17, 3), 11: (26, 22, 4), 12: (26, 24, 4),
            13: (26, 22, 4), 14: (26, 24, 4), 15: (26, 24, 4)}
    frames, durs = [], []
    for f in range(n):
        c = Canvas()
        # stand
        c.poly([(8, 21), (16, 21), (19, 29), (5, 29)], "N")
        c.rect(4, 28, 17, 3, "A")
        c.rect(7, 23, 2, 5, "S")
        # spout from the drum's lower right
        c.poly([(17, 17), (21, 15), (28, 22), (25, 25)], "S")
        c.poly([(19, 18), (21, 17), (26, 22), (25, 23)], "M")
        # clear drum
        c.circle(CX, CY, R, "N")
        c.circle(CX, CY, R - 1, "I")
        spin = f * 30 if f < 9 else 270 + (f - 9) * 10
        for k in range(3):     # air swirl arcs show the mix churning
            base = spin + 120 * k
            pts = []
            for s in range(5):
                a = math.radians(base + s * 14)
                pts.append((CX + 8 * math.cos(a), CY + 8 * math.sin(a)))
            for p0, p1 in zip(pts, pts[1:]):
                c.line(round(p0[0]), round(p0[1]), round(p1[0]), round(p1[1]), "L")
        calm = f >= 10
        for i, colr in enumerate(cols + (["G"] if f < 8 else [])):
            if calm:
                spots = [(-6, 7), (-2, 8), (2, 8), (6, 7), (-4, 3), (0, 4), (4, 3)]
                bx, by = CX + spots[i][0], CY + spots[i][1] - (1 if (f % 2 and i == 5) else 0)
            else:
                a = math.radians(spin * 1.4 + i * 47 + rng.uniform(-20, 20))
                rr = rng.uniform(2.5, 7.0)
                bx = CX + rr * math.cos(a)
                by = CY + rr * math.sin(a) * 0.9 + 1
            ball(c, int(round(bx)), int(round(by)), colr)
        # glare on the glass
        for (x, y) in ((5, 7), (6, 6), (6, 5), (7, 4), (8, 3), (4, 8), (4, 9)):
            c.px(x, y, "W")
        if f in gold:
            gx, gy, gr = gold[f]
            b = Canvas(2 * gr + 3, 2 * gr + 3)
            b.circle(gr + 1, gr + 1, gr, "G")
            b.px(gr - 1, gr - 1, "Y"); b.px(gr, gr - 2, "Y")
            if gr >= 4:
                b.text(gr, gr - 1, "1", "K")
            b.outline()
            put(c, b, gx - gr - 1, gy - gr - 1)
            if f == 10:
                for (x, y) in ((22, 12), (30, 13), (26, 10)):
                    sparkle(c, x, y, "Y")
            if f in (12, 14):
                sparkle(c, 20, 17 if f == 12 else 19, "Y"); sparkle(c, 30, 17, "W")
        c.outline()
        frames.append(c)
        durs.append(80 if f < 8 else (90 if f < 12 else 120))
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 12. popcorn
# ----------------------------------------------------------------------------------------------
POP_A = [".WW.", "WWWC", "WCYC", ".CC."]
POP_B = ["WW..", "WWCW", ".CYW", "..C."]
POP_C = [".W.", "WWC", "CY."]


@emoji("blha_popcorn")
def popcorn():
    n = 12
    # kernels: (phase, start x, vx, vy, sprite)
    kernels = [(0, 11, -2.0, 3.4, POP_A), (2, 19, 2.1, 3.0, POP_B), (4, 14, -0.9, 3.9, POP_C),
               (6, 9, -2.4, 2.8, POP_B), (8, 20, 1.5, 3.6, POP_A), (10, 16, 0.9, 4.0, POP_C)]
    mound = [(5, 13, POP_A), (9, 12, POP_B), (13, 11, POP_A), (17, 11, POP_B), (21, 12, POP_A),
             (24, 14, POP_C), (8, 10, POP_C), (12, 9, POP_C), (16, 9, POP_A), (20, 10, POP_C)]
    frames, durs = [], []
    for f in range(n):
        c = Canvas()
        for (x, y, spr) in mound:
            jig = 1 if (f + x) % 6 == 0 else 0           # heap jiggles as kernels burst from it
            c.stamp(spr, x, y - jig)
        c.ellipse(15.5, 15.5, 10, 2, "C")
        top, bot = 17, 30
        for y in range(top, bot + 1):
            t = (y - top) / (bot - top)
            x0 = int(round(5 + 3 * t)); x1 = int(round(26 - 3 * t))
            for x in range(x0, x1 + 1):
                stripe = ((x - 15.5) / (1 + 0.2 * t)) // 3
                c.px(x, y, "R" if stripe % 2 == 0 else "W")
        c.rect(4, top, 24, 2, "W")
        c.rect(4, top + 1, 24, 1, "S")
        for (ph, sx, vx, vy, spr) in kernels:
            age = (f - ph) % n
            if age == 0:     # the pop itself
                sparkle(c, sx + 1, 9, "Y", 2)
                c.px(sx + 1, 9, "W")
            elif age <= 7:
                t = age
                x = sx + vx * t
                y = 8 - vy * t + 0.75 * t * t
                c.stamp(spr, int(round(x)), int(round(y)))
        c.outline()
        frames.append(c); durs.append(90)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 13. dumpster fire
# ----------------------------------------------------------------------------------------------
def tongue(c, cx, base, h, w, sway, colr):
    """One flame tongue: wide at the base, curling to a point that sways sideways."""
    if h < 1:
        return
    for dy in range(int(round(h)) + 1):
        t = min(1.0, dy / h)
        hw = (w / 2) * (1 - t) ** 0.75
        off = sway * t * t
        xa, xb = cx + off - hw, cx + off + hw
        for x in range(int(math.floor(xa + 0.5)), int(math.floor(xb + 0.5)) + 1):
            c.px(x, base - dy, colr)


def fire(c, x0, x1, base, f, n, height=13.0, seed=0):
    """Layered tongues (R outside, F, Y, W heart) looping over n frames."""
    w = 2 * math.pi / n
    k = max(3, (x1 - x0) // 5)
    tongues = []
    for i in range(k):
        u = (i + 0.5) / k
        cx = x0 + u * (x1 - x0)
        env = 0.55 + 0.45 * math.sin(math.pi * u)
        h = height * env * (0.84 + 0.16 * math.sin(f * w * (2 if i % 2 else 3) + i * 1.9 + seed))
        sway = 2.2 * math.sin(f * w * 2 + i * 2.4 + seed)
        tongues.append((cx, h, sway))
    for layer, colr, s in ((0, "R", 1.0), (1, "F", 0.78), (2, "Y", 0.52), (3, "W", 0.25)):
        for (cx, h, sway) in tongues:
            tongue(c, cx, base, h * s, 7.5 * (0.5 + 0.5 * s) if layer else 8.0, sway * s, colr)


@emoji("blha_dumpsterfire")
def dumpsterfire():
    n = 12
    frames, durs = [], []
    for f in range(n):
        c = Canvas()
        # lid flung open behind
        c.poly([(5, 16), (26, 16), (29, 10), (8, 10)], GREEN_DK)
        c.rect(9, 11, 19, 1, "E")
        # smoke puffs drifting up (loop over n frames)
        for k, (sx, ph) in enumerate(((8, 0), (23, 6))):
            age = (f - ph) % n
            y = 7 - age * 0.8
            x = sx + math.sin(age * 0.7 + k) * 1.2 + (age * 0.3 if k else -age * 0.3)
            r = 1 + age // 5
            if y > -3 and age < 10:
                c.circle(int(round(x)), int(round(y)), r, SMOKE)
        fire(c, 6, 25, 17, f, n, height=14.0)
        # embers
        for k in range(3):
            age = (f + k * 4) % n
            ex = 8 + k * 7 + (age % 3)
            ey = 8 - age
            if ey >= 0:
                c.px(ex, ey, "Y" if age % 2 else "F")
        # dumpster body
        c.poly([(3, 17), (28, 17), (26, 28), (5, 28)], "E")
        c.rect(3, 17, 26, 2, "e")
        c.rect(3, 18, 26, 1, GREEN_DK)
        for y in (22, 25):
            c.line(5, y, 26, y, GREEN_DK)
        c.rect(25, 19, 2, 9, GREEN_DK)
        c.rect(6, 19, 1, 9, "e")
        # wheels
        for wx in (7, 22):
            c.rect(wx, 28, 3, 2, "A")
            c.px(wx + 1, 29, "N")
        c.outline()
        frames.append(c); durs.append(90)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 14. typing
# ----------------------------------------------------------------------------------------------
@emoji("blha_typing")
def typing():
    # each dot hops in turn: offsets per frame for dots 0..2 (negative = up), plus dot shade
    hop = [0, -2, -3, -2, 0]
    n = 8
    frames, durs = [], []
    for f in range(n):
        c = Canvas()
        # rounded bubble with a tail at the bottom-left
        c.rect(3, 6, 26, 16, "W")
        c.rect(2, 8, 28, 12, "W")
        c.rect(4, 5, 24, 1, "W"); c.rect(4, 22, 24, 1, "W")
        c.poly([(5, 21), (11, 21), (4, 28)], "W")
        c.rect(3, 21, 26, 1, "S"); c.rect(5, 22, 23, 1, "S")
        c.rect(29, 9, 1, 11, "S")
        for i in range(3):
            k = (f - i * 2) % n
            dy = hop[k] if k < len(hop) else 0
            x = 7 + i * 7
            y = 12 + dy
            colr = "A" if dy <= -2 else "N"
            c.rect(x, y, 5, 4, colr)
            c.rect(x + 1, y - 1, 3, 6, colr)
        c.outline()
        frames.append(c); durs.append(90)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 15. rocket
# ----------------------------------------------------------------------------------------------
ROCKET = [
    "......RR......",
    ".....rRRR.....",
    ".....rRRR.....",
    "....rRRRRR....",
    "....RRRRRR....",
    "...WWWWWWWS...",
    "...WWWWWWWS...",
    "...WWKKKWWS...",
    "...WKLLWKWS...",
    "...WKLLLKWS...",
    "...WKLLLKWS...",
    "...WWKKKWWS...",
    "...WWWWWWWS...",
    "...WWWWWWWS...",
    "...WWWWWWWS...",
    "..RWWWWWWWSR..",
    ".RRWWWWWWWSRR.",
    "RRRWWWWWWWSRRR",
    "RRRRWWWWWWRRRR",
    "RRR..NNNN..RRR",
    "RR...NNNN...RR",
]


def puff(c, x, y, r, colr="W", shade="S"):
    c.circle(x, y, r, colr)
    if r >= 2:
        for (dx, dy) in ((r - 1, 1), (r - 1, 0), (0, r), (1, r - 1)):
            c.px(x + dx, y + dy, shade)


@emoji("blha_rocket")
def rocket():
    rk = sprite(ROCKET)
    # (rocket bottom y, flame length, shake, smoke stage, ms)
    seq = [(29, 0, 0, 0, 120), (29, 2, 0, 1, 90), (29, 4, -1, 2, 80), (29, 6, 1, 3, 70),
           (27, 8, 0, 4, 70), (23, 9, -1, 5, 60), (16, 10, 0, 6, 60), (6, 10, 0, 7, 60),
           (-6, 10, 0, 8, 70), (-30, 0, 0, 9, 90), (-30, 0, 0, 10, 100)]
    frames, durs = [], []
    for by, flame, shake, sm, d in seq:
        c = Canvas()
        x = 9 + shake
        top = by - len(ROCKET) + 1
        cx = x + 6.5
        # exhaust trail of puffs left behind on the way up
        if sm >= 5:
            for k, yy in enumerate(range(26, max(-4, by + flame), -4)):
                r = max(1, 3 - k // 2) if sm < 9 else max(1, 2 - k // 3)
                ox = (1 if k % 2 else -1)
                colr = "W" if sm < 8 else ("I" if sm < 10 else "S")
                puff(c, int(cx) + ox, yy, r, colr, "S")
        if 2 <= sm < 9:
            c.rect(int(cx) - 7, 28, 14, 2, "W")
        if flame:
            ph = len(frames) % 2
            # outer flame, pointing down from the nozzle (on the pad it splashes sideways)
            if by >= 29:
                c.rect(int(cx) - flame // 2 - 1, 28, flame + 3, 2, "F")
                c.rect(int(cx) - flame // 4, 28, flame // 2 + 2, 2, "Y")
            for i in range(flame + 1):
                half = 3.2 * (1 - i / (flame + 1)) ** 0.7
                for xx in range(int(round(cx - half)), int(round(cx + half)) + 1):
                    c.px(xx, by + 1 + i, "R")
            for colr, s in (("F", 0.75), ("Y", 0.5), ("W", 0.25)):
                ln = max(1, int(round(flame * s)) + (ph if colr == "F" else 0))
                for i in range(ln):
                    half = 3.2 * s * (1 - i / (ln + 1)) ** 0.7
                    for xx in range(int(round(cx - half)), int(round(cx + half)) + 1):
                        c.px(xx, by + 1 + i, colr)
        if top < 32:
            put(c, rk, x, top)
        if sm:   # ground smoke billowing out to both sides
            g = min(sm, 6)
            fade = sm >= 9
            for side in (-1, 1):
                for k in range(min(3, 1 + g // 2)):
                    px_ = int(cx) + side * (4 + k * 4 + g // 2)
                    py_ = 27 - (k % 2)
                    r = 2 + (1 if g >= 3 and k < 2 else 0) - (1 if fade and k == 2 else 0)
                    puff(c, px_, py_, r, "W" if not fade else "I", "S")
        c.rect(5, 30, 22, 1, "N")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 16 / 17. stonks and tank
# ----------------------------------------------------------------------------------------------
def chart_panel(c, dy=0, paper="W"):
    c.rect(1, 2 + dy, 30, 28, paper)
    for x in range(1, 31, 6):
        c.rect(x + 4, 3 + dy, 1, 26, "I")
    for y in range(4, 29, 6):
        c.rect(2, y + dy, 28, 1, "I")
    c.rect(2, 3 + dy, 1, 26, "N")     # y axis
    c.rect(2, 28 + dy, 28, 1, "N")    # x axis


def polyline_upto(pts, frac):
    """Points of the polyline truncated at fraction frac of its length."""
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs]
    total = sum(lens) * frac
    out = [pts[0]]
    for (a, b), L in zip(segs, lens):
        if total >= L:
            out.append(b); total -= L
        else:
            t = total / L
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            break
    return out


def thick_poly(c, pts, colr, edge="K"):
    for w, col_ in ((4, edge), (2, colr)):
        o = (w - 2) // 2
        for a, b in zip(pts, pts[1:]):
            c.line(round(a[0]) - o, round(a[1]) - o, round(b[0]) - o, round(b[1]) - o, col_, w)


def arrow_head(c, tip, direction, size, colr):
    """Filled arrowhead with a keyline; direction is a unit vector."""
    dx, dy = direction
    px_, py_ = -dy, dx
    base = (tip[0] - dx * size, tip[1] - dy * size)
    tri = [tip, (base[0] + px_ * size * 0.8, base[1] + py_ * size * 0.8),
           (base[0] - px_ * size * 0.8, base[1] - py_ * size * 0.8)]
    big = [(tip[0] + dx * 1.6, tip[1] + dy * 1.6),
           (base[0] + px_ * (size * 0.8 + 1.6) - dx, base[1] + py_ * (size * 0.8 + 1.6) - dy),
           (base[0] - px_ * (size * 0.8 + 1.6) - dx, base[1] - py_ * (size * 0.8 + 1.6) - dy)]
    c.poly(big, "K")
    c.poly(tri, colr)


def fill_under(c, pts, colr, bottom=27, dy=0):
    poly = [(pts[0][0], bottom + dy)] + [(x, y + dy) for x, y in pts] + [(pts[-1][0], bottom + dy)]
    c.poly(poly, colr)


def chart_emoji(pts, colr, fillc, crash=False):
    n_draw = 8
    frames, durs = [], []
    end = pts[-1]
    prev = pts[-2]
    d = (end[0] - prev[0], end[1] - prev[1])
    m = math.hypot(*d)
    unit = (d[0] / m, d[1] / m)
    # frame plan: the line grows over 9 frames, then the arrowhead pops and the result holds
    plan = [("grow", i / n_draw) for i in range(0, n_draw + 1)]
    plan += [("arrow", 1), ("arrow", 2), ("hold", 0), ("hold", 1), ("hold", 2), ("hold", 3)]
    for kind, v in plan:
        c = Canvas()
        shake = 0
        if crash and kind == "arrow":
            shake = 1 if v == 1 else -1
        alarm = crash and kind == "hold" and v in (0, 2)
        chart_panel(c, shake, "P" if alarm else "W")
        if kind == "grow":
            seg = polyline_upto(pts, v)
            if len(seg) > 1:
                thick_poly(c, [(x, y + shake) for x, y in seg], colr)
                head = seg[-1]
                c.rect(int(round(head[0])), int(round(head[1])), 1, 1, "W")
        else:
            if fillc and (kind == "hold" or v == 2):
                fill_under(c, pts, fillc, dy=shake)
            thick_poly(c, [(x, y + shake) for x, y in pts], colr)
            size = {1: 3.2, 2: 4.6}.get(v, 4.0) if kind == "arrow" else (4.0 if v % 2 == 0 else 4.4)
            tip = (end[0] + unit[0] * 2.5, end[1] + unit[1] * 2.5 + shake)
            arrow_head(c, tip, unit, size, colr)
            if crash and kind == "arrow":
                # impact puff where the line smashes into the floor
                for (x, y) in ((20, 26), (30, 25), (25, 22)):
                    sparkle(c, x, y + shake, "S" if v == 2 else "N", 1)
            if not crash and kind == "hold" and v in (1, 3):
                sparkle(c, 7 if v == 1 else 13, 7, "Y", 1)
            if not crash and kind == "arrow" and v == 2:
                sparkle(c, 24, 2, "Y", 1)
        c.outline()
        frames.append(c)
        durs.append(70 if kind == "grow" else (80 if kind == "arrow" else 120))
    return frames, durs


@emoji("blha_stonks")
def stonks():
    pts = [(4, 25), (9, 19), (12, 22), (17, 14), (20, 17), (25, 9), (27, 6)]
    return chart_emoji(pts, "E", "e")


@emoji("blha_tank")
def tank():
    pts = [(4, 6), (9, 11), (12, 8), (17, 16), (20, 13), (25, 22), (27, 25)]
    return chart_emoji(pts, "R", None, crash=True)


# ----------------------------------------------------------------------------------------------
# 18. spotlight
# ----------------------------------------------------------------------------------------------
def star_pts(cx, cy, ro, ri, rot=-90):
    pts = []
    for i in range(10):
        a = math.radians(rot + i * 36)
        r = ro if i % 2 == 0 else ri
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


@emoji("blha_spotlight")
def spotlight():
    PX, PY = 7, 25           # lamp pivot
    SX, SY = 22, 9           # star
    # beam target x along the top (sweep), star state, ms
    seq = [(4, 0, 110), (7, 0, 80), (10, 0, 80), (13, 0, 80), (17, 0, 80), (20, 1, 80),
           (SX, 2, 90), (SX, 3, 90), (SX, 4, 100), (SX, 5, 100), (SX, 4, 100), (SX, 5, 110),
           (None, 6, 120)]
    frames, durs = [], []
    for tx, st, d in seq:
        c = Canvas()
        on = tx is not None
        if on:
            ty = SY + (abs(tx - SX) * 0.15)
            ang = math.atan2(ty - PY, tx - PX)
        else:
            ang = math.atan2(SY - PY, SX - PX)
        ux, uy = math.cos(ang), math.sin(ang)
        nx, ny = -uy, ux
        mouth = (PX + ux * 5, PY + uy * 5)
        if on:
            dist = math.hypot(tx - mouth[0], ty - mouth[1])
            w_end = 5.0
            beam = [(mouth[0] + nx * 2, mouth[1] + ny * 2), (mouth[0] - nx * 2, mouth[1] - ny * 2),
                    (mouth[0] + ux * dist - nx * w_end, mouth[1] + uy * dist - ny * w_end),
                    (mouth[0] + ux * dist + nx * w_end, mouth[1] + uy * dist + ny * w_end)]
            c.poly(beam, "Y")
            c.ellipse(tx, ty, 5, 5, "Y")
            core = [(mouth[0] + nx * 0.8, mouth[1] + ny * 0.8), (mouth[0] - nx * 0.8, mouth[1] - ny * 0.8),
                    (mouth[0] + ux * dist - nx * 2.5, mouth[1] + uy * dist - ny * 2.5),
                    (mouth[0] + ux * dist + nx * 2.5, mouth[1] + uy * dist + ny * 2.5)]
            c.poly(core, "C")
        # the star: dim until the light finds it, then it shines
        lit = st >= 2
        if st >= 3 and on:
            n_r = 8
            ln = 3 if st in (3, 5) else 2
            for i in range(n_r):
                a = math.radians(i * 45 + (22.5 if st == 4 else 0))
                for r in range(10, 10 + ln):
                    c.px(int(round(SX + r * math.cos(a))), int(round(SY + r * math.sin(a))), "Y")
        sc = Canvas()
        ro = 8 if lit and on else 7
        sc.poly(star_pts(SX + 0.5, SY + 0.5, ro, ro * 0.45), "G" if lit and on else "D")
        if lit and on:
            sc.poly(star_pts(SX + 0.5, SY - 0.5, ro * 0.45, ro * 0.22), "Y")
            sc.px(SX - 1, SY - 2, "W")
        sc.outline()
        c.paste(sc)
        if st == 1 and on:
            sparkle(c, SX + 6, SY - 6, "W")
        if st in (2, 5) and on:
            sparkle(c, SX - 8, SY - 6, "W"); sparkle(c, SX + 8, SY + 7, "W")
        # lamp housing aimed along the beam, on a stand
        c.poly([(PX - 2, PY + 2), (PX + 2, PY + 2), (PX + 5, 30), (PX - 5, 30)], "N")
        body = [(PX + nx * 3 - ux * 3, PY + ny * 3 - uy * 3), (PX - nx * 3 - ux * 3, PY - ny * 3 - uy * 3),
                (PX - nx * 3.5 + ux * 5, PY - ny * 3.5 + uy * 5), (PX + nx * 3.5 + ux * 5, PY + ny * 3.5 + uy * 5)]
        c.poly(body, "A")
        lens = [(PX - nx * 3 + ux * 4, PY - ny * 3 + uy * 4), (PX + nx * 3 + ux * 4, PY + ny * 3 + uy * 4),
                (PX + nx * 3 + ux * 5.5, PY + ny * 3 + uy * 5.5), (PX - nx * 3 + ux * 5.5, PY - ny * 3 + uy * 5.5)]
        c.poly(lens, "W" if on else "N")
        c.rect(PX - 1, PY - 1, 2, 2, "S")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 19. fireworks
# ----------------------------------------------------------------------------------------------
@emoji("blha_fireworks")
def fireworks():
    CX, CY = 16, 12
    cols = ["R", "G", "L", "E", "P", "V", "F", "W", "R", "G", "L", "E"]
    nr = 12
    # rocket climb: (y) then burst stages
    climb = [29, 23, 17, 13]
    stages = [  # (kind, inner r, outer r, droop, fade level)
        ("flash", 0, 2, 0, 1), ("rays", 1, 5, 0, 1), ("rays", 3, 9, 0, 1), ("rays", 6, 12, 0.5, 1),
        ("dots", 12, 13, 1.0, 1), ("dots", 13, 14, 2.0, 1), ("dots", 13.5, 14.5, 3.0, 0.7),
        ("dots", 14, 15, 4.0, 0.45), ("dots", 14, 15, 5.0, 0.2),
    ]
    keep = {1: 1, 0.7: 1, 0.45: 2, 0.2: 4}   # fading: thin out the sparks
    frames, durs = [], []
    for i, y in enumerate(climb):
        c = Canvas()
        x = CX + (i % 2)
        c.rect(x, y, 2, 3, "Y")
        c.px(x, y, "W"); c.px(x + 1, y, "W")
        for k in range(1, 4):      # sparkling trail
            ty = y + 3 + k * 2
            if ty < 32:
                c.px(x + (k % 2), ty, "F" if k < 3 else "R")
        c.outline()
        frames.append(c); durs.append(70)
    for kind, r0, r1, droop, fade in stages:
        c = Canvas()
        if kind == "flash":
            c.circle(CX, CY, 2, "W")
            sparkle(c, CX, CY, "Y", 4)
            c.circle(CX, CY, 1, "W")
        for k in range(nr):
            a = 2 * math.pi * k / nr + 0.13
            ca, sa = math.cos(a), math.sin(a)
            colr = cols[k]
            if kind == "rays":
                x0, y0 = CX + r0 * ca, CY + r0 * sa
                x1, y1 = CX + r1 * ca, CY + r1 * sa + droop
                c.line(round(x0), round(y0), round(x1), round(y1), colr)
                c.px(round(x1), round(y1), "W")
            elif kind == "dots":
                if k % keep[fade]:
                    continue
                x1, y1 = CX + r1 * ca, CY + r1 * sa + droop
                sz = 2 if fade >= 1 else 1
                c.rect(round(x1), round(y1), sz, sz, colr if fade > 0.2 else "W")
                tx, ty = CX + r0 * 0.75 * ca, CY + r0 * 0.75 * sa + droop * 0.6
                if fade >= 0.7 and k % 2 == 0:
                    c.px(round(tx), round(ty), colr)
        if kind == "rays" and r0 >= 3:
            sparkle(c, CX, CY, "W", 1)
        c.outline()
        frames.append(c); durs.append(80 if kind != "dots" else 100)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 20. mic drop
# ----------------------------------------------------------------------------------------------
MIC = [
    "..NSSN..",
    ".NSWSSN.",
    "NSSSSSSN",
    "NSNSNSSN",
    "NSSSSSSN",
    ".NSNSSN.",
    "..NNNN..",
    "..AAAA..",
    "..AMMA..",
    "..AMMA..",
    "..AMRA..",
    "..AMMA..",
    "..AMMA..",
    "..AMMA..",
    "..AMMA..",
    "..AMMA..",
    "...AA...",
]


@emoji("blha_micdrop")
def micdrop():
    mic = sprite(MIC)
    fist = make_fist(w=11, h=9, wrist=0)
    hand, wx, wy = make_open_hand(fw=2, tops=(2, 0, 1, 4), palm_y=8, palm_h=6, wrist_h=4)
    oh = Canvas(32, 32); put(oh, hand, 8, 6)
    oh = rot_keyed(oh, 50, 16, 17)           # fingers flung up-left, wrist toward the arm
    FLOOR = 29
    MX = 9
    # (hand, mic top y, mic angle, fx, ms)
    seq = [("fist", 0, 0, None, 120), ("fist", -1, 0, "lift", 100), ("open", 0, 0, "drop0", 80),
           ("open", 4, 0, "fall", 60), ("open", 9, 0, "fall", 60), ("open", FLOOR - 16, 0, "hit", 70),
           ("open", FLOOR - 19, -25, None, 70), ("open", FLOOR - 15, -60, None, 70),
           ("open", FLOOR - 12, -90, "thud", 90), ("open", FLOOR - 12, -90, "thud2", 110),
           ("open", FLOOR - 12, -90, None, 120)]
    frames, durs = [], []
    for state, my, ang, fx, d in seq:
        c = Canvas()
        c.rect(0, FLOOR + 1, 32, 2, "O")
        c.rect(0, FLOOR + 2, 32, 1, "o")
        lift = -1 if fx == "lift" else 0
        # forearm from the right edge, charcoal sleeve with a gold stripe
        arm = Canvas()
        arm.rect(16, 8 + lift, 16, 7, "G")
        arm.rect(16, 14 + lift, 16, 1, "D")
        arm.rect(25, 7 + lift, 7, 9, "A")
        arm.rect(27, 7 + lift, 2, 9, "G")
        arm.outline()
        c.paste(arm)
        m = Canvas(32, 32)
        put(m, mic, MX, my)
        if ang:
            m = rotsprite(m, ang, MX + 4, my + 8)
            ys = np.nonzero(np.array(m.img)[:, :, 3].any(axis=1))[0]
            m = shift(m, 3 if ang <= -60 else 1, FLOOR - int(ys.max()) - (2 if ang == -25 else 0))
        m.outline()
        if state == "fist":
            c.paste(m)
            put(c, keyline(fist), MX - 2, 6 + lift)
        else:
            put(c, oh, -3, -11)
            c.paste(m)
        if fx == "drop0":
            for (x, y) in ((7, 17), (18, 17)):
                c.px(x, y, "W"); c.px(x, y + 1, "W")
        if fx == "fall":
            for x in (MX + 1, MX + 6):
                c.rect(x, my - 4, 1, 3, "W")
        if fx == "hit":
            for (x, y, dx, dy) in ((MX - 2, FLOOR - 1, -1, -1), (MX + 9, FLOOR - 1, 1, -1),
                                   (MX - 3, FLOOR - 4, -1, 0), (MX + 10, FLOOR - 4, 1, 0)):
                for i in range(3):
                    c.px(x + dx * i, y + dy * i, "Y")
        if fx in ("thud", "thud2"):
            k = 1 if fx == "thud" else 2
            for x in (4, 27):
                c.rect(x - k, FLOOR - k + 1, 2 * k, k, "S")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 21. white flag
# ----------------------------------------------------------------------------------------------
@emoji("blha_whiteflag")
def whiteflag():
    n = 10
    fist = make_fist(w=9, h=8, wrist=3)
    frames, durs = [], []
    for f in range(n):
        ph = 2 * math.pi * f / n
        c = Canvas()
        sway = int(round(1.0 * math.sin(ph)))          # pole rocks a little in the hand
        PX = 6
        # pole: leans with the sway (top moves, hand end fixed)
        for y in range(1, 30):
            off = int(round(sway * (29 - y) / 28))
            c.rect(PX + off, y, 2, 1, "O")
            c.px(PX + off + 1, y, "o")
        c.rect(PX + sway - 1, 0, 3, 2, "S")
        c.px(PX + sway - 1, 0, "W")
        # cloth rippling: each column displaced by a traveling wave that grows away from the pole
        top0, h0 = 3, 16
        x0 = PX + 2 + sway
        L = 22
        for i in range(L):
            x = x0 + i
            amp = min(2.6, 0.35 + i * 0.16)
            dy = amp * math.sin(i * 0.48 - ph)
            slope = math.cos(i * 0.48 - ph)
            hh = h0 - (1 if abs(slope) < 0.3 and i > 6 else 0) - int(i / 12)
            y0 = int(round(top0 + dy + (h0 - hh) / 2))
            colr = "W" if slope > -0.15 else ("I" if slope > -0.6 else "S")
            c.rect(x, y0, 1, hh, colr)
            if slope > 0.75 and i > 3:
                c.px(x, y0 + 1, "I")
        # the hand holding the pole
        put(c, keyline(fist), PX - 4, 21)
        c.outline()
        frames.append(c); durs.append(90)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 22. vote
# ----------------------------------------------------------------------------------------------
def ballot(check_stage):
    p = Canvas(12, 13)
    p.rect(0, 0, 12, 13, "W")
    p.rect(11, 1, 1, 12, "S")
    p.rect(2, 2, 8, 1, "S")
    p.frame(2, 5, 6, 6, "K")
    if check_stage >= 1:
        for (x, y) in ((3, 7), (4, 8), (5, 9)):
            p.px(x, y, "E"); p.px(x, y - 1, "E")
    if check_stage >= 2:
        for (x, y) in ((6, 8), (7, 7), (8, 6), (9, 5), (10, 4)):
            p.px(x, y, "E"); p.px(x, y - 1, "E")
    return p


@emoji("blha_vote")
def vote():
    # (ballot y (top), check stage, box squash, sparkle, ms)
    seq = [(2, 0, 0, 0, 110), (2, 1, 0, 0, 80), (2, 2, 0, 0, 90), (1, 2, 0, 0, 100), (4, 2, 0, 0, 70),
           (8, 2, 0, 0, 60), (12, 2, 0, 0, 60), (15, 2, 0, 0, 60), (99, 2, 1, 1, 80), (99, 2, 0, 2, 90),
           (99, 2, 0, 3, 110), (99, 2, 0, 0, 120)]
    frames, durs = [], []
    for by, chk, sq, spk, d in seq:
        c = Canvas()
        top = 15 + sq
        # box: lighter lid in perspective, blue front
        c.poly([(5, top + 3), (26, top + 3), (29, top), (8, top)], "L")
        c.rect(4, top + 3, 24, 30 - top - 3, "B")
        c.rect(4, top + 3, 24, 1, "b")
        c.rect(26, top + 4, 2, 30 - top - 4, "b")
        c.rect(9, 22 + sq, 14, 5, "W")       # label
        c.rect(11, 24 + sq, 10, 1, "S")
        # slot in the lid
        c.rect(10, top + 1, 13, 1, "K")
        # ballot: drawn only above the slot line
        if by < 99:
            p = ballot(chk)
            px0 = 10
            for j in range(p.h):
                y = by + j
                if y >= top + 2:
                    break
                for i in range(p.w):
                    q = p.get(i, j)
                    if q[3]:
                        c.px(px0 + i, y, q[:3])
            # keyline around the visible part of the ballot
            tmp = Canvas()
            for j in range(p.h):
                y = by + j
                if y >= top + 1:
                    break
                tmp.rect(px0, y, p.w, 1, "W")
            tmp.outline()
            a = np.array(tmp.img)
            k_ = np.array(pix.col("K"))
            for y in range(32):
                for x in range(32):
                    if np.all(a[y, x] == k_) and y < top + 1:
                        c.px(x, y, "K")
        if spk:
            s = {1: 1, 2: 2, 3: 1}[spk]
            sparkle(c, 16, top - 3 - s, "Y", s + 1)
            if spk >= 2:
                sparkle(c, 6, top - 4, "W"); sparkle(c, 26, top - 5, "W")
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 23. ghosted
# ----------------------------------------------------------------------------------------------
def ghost(c, x, y, phase, look=0):
    """Ghost about 18 x 22 with its top-left near (x, y); wavy hem animated by phase."""
    cx = x + 9
    c.circle(cx, y + 8, 8, "W")
    c.rect(x + 1, y + 8, 17, 11, "W")
    for i in range(17):
        hem = y + 19 + int(round(1.4 * math.sin(i * 0.9 + phase)))
        c.rect(x + 1 + i, y + 18, 1, hem - (y + 18) + 1, "W")
    # shading on the right side
    for j in range(5, 19):
        c.px(x + 17, y + j, "I")
    c.px(x + 16, y + 3, "I"); c.px(x + 17, y + 4, "I")
    # little arms
    c.rect(x - 1, y + 12, 2, 3, "W")
    c.rect(x + 18, y + 11, 2, 3, "W")
    # vacant eyes and a small 'o' mouth
    for ex in (cx - 5 + look, cx + 2 + look):
        c.rect(ex, y + 6, 3, 4, "K")
        c.px(ex, y + 6, "W"); c.px(ex + 2, y + 6, "W")
    c.rect(cx - 1 + look, y + 12, 2, 2, "K")


@emoji("blha_ghosted")
def ghosted():
    # (fade level, y offset, dots shown, look, ms)
    seq = [(0.25, 7, 0, 0, 90), (0.5, 6, 0, 0, 90), (0.75, 5, 0, 0, 90), (1, 4, 0, 0, 100),
           (1, 3, 0, 1, 100), (1, 3, 1, 1, 110), (1, 4, 2, 1, 110), (1, 5, 3, 1, 120),
           (1, 5, 3, 0, 120), (1, 4, 0, 0, 120), (0.75, 3, 0, 0, 90), (0.5, 3, 0, 0, 90),
           (0.25, 2, 0, 0, 90), (0, 2, 0, 0, 120)]
    frames, durs = [], []
    for k, (lvl, gy, dots, look, d) in enumerate(seq):
        c = Canvas()
        if lvl > 0:
            g = Canvas()
            ghost(g, 1, gy, k * 1.1, look)
            g.outline()
            dither_fade(g, lvl)
            c.paste(g)
        if dots:
            dc = Canvas()
            for i in range(dots):
                dc.rect(20 + i * 4, 21, 3, 3, "W")
            dc.outline()
            c.paste(dc)
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 24. skull
# ----------------------------------------------------------------------------------------------
def skull(c, dx, jaw, eyes):
    """jaw: 0 closed .. 4 wide open. eyes: 'dark', 'glow', 'hot'."""
    x0 = dx
    # jaw first (behind the cheekbones)
    jy = 21 + jaw
    c.rect(x0 + 9, jy, 14, 6, "W")
    c.rect(x0 + 10, jy + 6, 12, 1, "W")
    c.rect(x0 + 21, jy + 1, 2, 5, "S"); c.rect(x0 + 11, jy + 6, 11, 1, "S")
    for i in range(6):            # lower teeth
        c.rect(x0 + 10 + i * 2, jy, 1, 2, "C")
        c.px(x0 + 11 + i * 2, jy, "K"); c.px(x0 + 11 + i * 2, jy + 1, "K")
    if jaw:
        c.rect(x0 + 10, jy - jaw, 12, jaw, "K")      # open mouth
    # cranium
    c.ellipse(x0 + 15.5, 11, 12, 10, "W")
    for x in (x0 + 3, x0 + 28):        # trim the one-pixel nubs at the widest row
        for y in range(32):
            c.px(x, y, None)
    c.rect(x0 + 8, 15, 16, 6, "W")
    for y in range(4, 19):         # shading down the right
        for x in range(x0 + 20, x0 + 29):
            if c.get(x, y)[:3] == pix.PAL["W"] and c.get(x + 1, y)[3] == 0:
                c.px(x, y, "S")
    c.px(x0 + 8, 4, "C"); c.px(x0 + 7, 5, "C"); c.px(x0 + 9, 3, "C")   # brow sheen
    # upper teeth
    c.rect(x0 + 10, 19, 12, 2, "C")
    for i in range(6):
        c.rect(x0 + 11 + i * 2, 19, 1, 2, "K")
    c.rect(x0 + 9, 18, 14, 1, "S")
    # eye sockets
    for ex in (x0 + 7, x0 + 17):
        c.rect(ex, 9, 8, 6, "K")
        c.rect(ex + 1, 8, 6, 8, "K")
        if eyes != "dark":
            c.rect(ex + 2, 10, 4, 4, "R")
            c.rect(ex + 3, 11, 2, 2, "r" if eyes == "glow" else "Y")
    # nose
    c.rect(x0 + 15, 15, 2, 3, "K")
    c.px(x0 + 14, 16, "K"); c.px(x0 + 17, 16, "K")


@emoji("blha_skull")
def skull_emoji():
    # (jaw, eyes, shake, ms)
    seq = [(0, "dark", 0, 110), (2, "dark", 0, 70), (4, "glow", 1, 70), (1, "dark", 0, 70),
           (0, "dark", -1, 70), (3, "glow", 1, 70), (4, "hot", 0, 80), (1, "glow", -1, 70),
           (0, "dark", 0, 80), (2, "dark", 1, 70), (4, "hot", -1, 80), (2, "glow", 0, 70),
           ]
    frames, durs = [], []
    for jaw, eyes, sh, d in seq:
        c = Canvas()
        skull(c, sh, jaw, eyes)
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# 25. LFG
# ----------------------------------------------------------------------------------------------
LFG = {
    "L": ["###......"] * 15 + ["#########"] * 3,
    "F": ["#########"] * 3 + ["###......"] * 4 + ["#######.."] * 3 + ["###......"] * 8,
    "G": [".#######.", "#########", "#########", "###...###", "###......", "###......", "###......",
          "###..####", "###..####", "###..####", "###...###", "###...###", "###...###", "###...###",
          "###...###", "#########", "#########", ".#######."],
}


def letter(ch, squash=0):
    rows = LFG[ch]
    h, w = len(rows), len(rows[0])
    s = Canvas(w + 2 * squash, h)
    src_h = h
    dst_h = h - 2 * squash
    for y in range(dst_h):
        sy = int(y * src_h / dst_h)
        row = rows[sy]
        for x in range(w + 2 * squash):
            sx = int(x * w / (w + 2 * squash))
            if row[sx] == "#":
                s.px(x, y + 2 * squash, "G")
    # shading: dark gold on the bottom / right edges of strokes, light on the top / left
    a = np.array(s.img)
    filled = a[:, :, 3] > 0
    for y in range(s.h):
        for x in range(s.w):
            if not filled[y, x]:
                continue
            right = x + 1 >= s.w or not filled[y, x + 1]
            below = y + 1 >= s.h or not filled[y + 1, x]
            left = x == 0 or not filled[y, x - 1]
            above = y == 0 or not filled[y - 1, x]
            if right or below:
                s.px(x, y, "D")
            elif left or above:
                s.px(x, y, "Y")
    return s


@emoji("blha_lfg")
def lfg():
    XS = {"L": 1, "F": 11, "G": 21}
    BASE = 7           # letter top when landed (18 tall -> bottom at 24)
    # per frame: {letter: (y offset, squash)}, dust, shake, ms
    seq = [
        ({"L": (-12, 0)}, None, 0, 60),
        ({"L": (0, 1)}, "L", 0, 70),
        ({"L": (0, 0), "F": (-12, 0)}, None, 0, 60),
        ({"L": (1, 0), "F": (0, 1)}, "F", 0, 70),
        ({"L": (0, 0), "F": (0, 0), "G": (-12, 0)}, None, 0, 60),
        ({"L": (0, 0), "F": (1, 0), "G": (0, 1)}, "G", 0, 70),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, None, 0, 90),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, "all", 1, 60),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, None, -1, 60),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, "all", 1, 60),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, None, -1, 60),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, "all", 1, 60),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, None, 0, 130),
        ({"L": (0, 0), "F": (0, 0), "G": (0, 0)}, "glint", 0, 120),
    ]
    frames, durs = [], []
    for letters, dust, shake, d in seq:
        c = Canvas()
        for ch, (dy, sq) in letters.items():
            g = letter(ch, sq)
            g = keyline(g)
            jit = (shake if ch != "F" else -shake) if shake else 0
            put(c, g, XS[ch] - 1 - sq + jit, BASE - 1 + dy + (abs(shake) if ch == "F" else 0))
        if dust in ("L", "F", "G"):
            x = XS[dust]
            for (px_, py_) in ((x - 2, 24), (x + 9, 24), (x - 3, 22), (x + 10, 22)):
                c.rect(px_, py_, 2, 1, "W")
            for (px_, py_) in ((x + 1, 2), (x + 4, 1), (x + 7, 2)):
                c.rect(px_, py_, 1, 3, "W")
        if dust == "all":
            for (px_, py_) in ((0, 3), (30, 3), (0, 27), (30, 27)):
                c.rect(px_, py_, 2, 2, "W")
            for x in (5, 15, 25):
                c.rect(x, 28, 3, 1, "W")
        if dust == "glint":
            sparkle(c, 4, 9, "W", 1); sparkle(c, 26, 9, "W", 1)
        c.outline()
        frames.append(c); durs.append(d)
    return frames, durs


# ----------------------------------------------------------------------------------------------
# preview + build
# ----------------------------------------------------------------------------------------------
def preview(name, frames, durations):
    tmp = HERE / ".anim_b_tmp"
    tmp.mkdir(exist_ok=True)
    per = 8
    n = len(frames)
    rows = (n + per - 1) // per
    cell = 136
    W, H = per * cell + 8, rows * (cell + 14) + 8
    im = Image.new("RGB", (W, H), (49, 51, 56))
    d = ImageDraw.Draw(im)
    for i, f in enumerate(frames):
        x, y = 4 + (i % per) * cell, 4 + (i // per) * (cell + 14)
        b = f.big()
        bg = Image.new("RGBA", b.size, (49, 51, 56, 255) if (i // per) % 2 == 0 else (64, 66, 72, 255))
        bg.alpha_composite(b)
        im.paste(bg.convert("RGB"), (x, y))
        dur = durations[i] if isinstance(durations, (list, tuple)) else durations
        d.text((x, y + 130), f"{i}: {dur}ms", fill=(220, 220, 220))
    im.save(tmp / f"{name}.png")


# The GIF starts on a key frame so the still that Discord shows (picker, reduced motion) reads as the
# idea; the loop order is unchanged, only where it begins.
START = {
    "blha_sideeye": 4, "blha_facepalm": 6, "blha_clap": 2, "blha_hello": 2, "blha_fistpump": 8,
    "blha_kneeslide": 9, "blha_glassbang": 1, "blha_boardcheck": 4, "blha_rat": 6, "blha_dice": 9,
    "blha_lottery": 11, "blha_typing": 2, "blha_rocket": 5, "blha_stonks": 11, "blha_tank": 12,
    "blha_spotlight": 8, "blha_fireworks": 7, "blha_micdrop": 3, "blha_vote": 3, "blha_ghosted": 7,
    "blha_skull": 2, "blha_lfg": 12,
}


def build(names=None, show=False):
    OUT.mkdir(exist_ok=True)
    written = []
    for name, fn in EMOJI.items():
        if names and name not in names:
            continue
        frames, durations = fn()
        s = START.get(name, 0)
        frames = frames[s:] + frames[:s]
        durations = list(durations[s:]) + list(durations[:s])
        assert 8 <= len(frames) <= 24, (name, len(frames))
        pix.save_gif(frames, OUT / f"{name}.gif", durations)
        written.append(OUT / f"{name}.gif")
        if show:
            preview(name, frames, durations)
    return written


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        build(args, show=True)
    else:
        files = build()
        order = [OUT / f"{n}.gif" for n in EMOJI]
        pix.sheet(order, HERE / "anim_b_sheet.png")
        print("\n".join(str(p) for p in files))
