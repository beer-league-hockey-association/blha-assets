"""BLHA static emoji, group static_b (22 emoji).

Run:  python3 static_b.py      -> static/blha_*.png and static_b_sheet.png
Everything is drawn on the 32 x 32 art grid from pix.py and exported x4 (128 x 128).
Deterministic: no randomness.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pix import Canvas, PAL, col, face, save_png, sheet  # noqa: E402

OUT = HERE / "static"
N = 32

# A few extra shades for objects that need them (kept to a minimum).
DKRED = (138, 22, 20)      # deep red shade (apple, L, octopus, sauce)
DKGRN = (32, 110, 50)      # deep green shade (money bag)
DKORG = (206, 92, 12)      # deep orange shade (pylon)


# ----------------------------------------------------------------------------------------------
# helpers on top of pix.Canvas (pixel centers sit at x + .5, y + .5)
# ----------------------------------------------------------------------------------------------
def fill_where(c, test, color):
    for y in range(N):
        for x in range(N):
            if test(x + .5, y + .5):
                c.px(x, y, color)


def disc(c, cx, cy, rx, ry, color):
    fill_where(c, lambda X, Y: ((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2 <= 1, color)


def rdisc(c, cx, cy, rx, ry, deg, color):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)

    def t(X, Y):
        dx, dy = X - cx, Y - cy
        u = dx * ca + dy * sa
        v = -dx * sa + dy * ca
        return (u / rx) ** 2 + (v / ry) ** 2 <= 1
    fill_where(c, t, color)


def seg_dist(X, Y, x0, y0, x1, y1):
    vx, vy = x1 - x0, y1 - y0
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((X - x0) * vx + (Y - y0) * vy) / L))
    px_, py_ = x0 + t * vx, y0 + t * vy
    return math.hypot(X - px_, Y - py_)


def capsule(c, x0, y0, x1, y1, r, color):
    fill_where(c, lambda X, Y: seg_dist(X, Y, x0, y0, x1, y1) <= r, color)


def path(c, pts, r, color):
    for (a, b) in zip(pts, pts[1:]):
        capsule(c, a[0], a[1], b[0], b[1], r, color)


def same(c, x, y, color):
    return c.get(x, y)[:3] == col(color)[:3] and c.get(x, y)[3] > 0


def filled(c, x, y):
    return c.get(x, y)[3] > 0


def recolor(c, src, dst, test=lambda x, y: True):
    for y in range(N):
        for x in range(N):
            if same(c, x, y, src) and test(x, y):
                c.px(x, y, dst)


def edge(c, base, color, dirs, depth=1, against=None):
    """Recolour pixels of `base` that sit within `depth` px of an empty pixel (or a pixel that is not
    in `against`, a set of colors) in any of the directions `dirs`."""
    hits = []
    for y in range(N):
        for x in range(N):
            if not same(c, x, y, base):
                continue
            for dx, dy in dirs:
                for k in range(1, depth + 1):
                    xx, yy = x + dx * k, y + dy * k
                    out = not filled(c, xx, yy)
                    if against is not None and not out:
                        out = not any(same(c, xx, yy, a) for a in against)
                    if out:
                        hits.append((x, y))
                        break
                else:
                    continue
                break
    for x, y in hits:
        c.px(x, y, color)


UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)


def keyed_glyph(c, rows, x, y, fill, shade=None, key="K", diag=True):
    """Stamp a '#' glyph with its own 1-px key line. 's' cells use the shade color."""
    cells = [(i, j, ch) for j, r in enumerate(rows) for i, ch in enumerate(r) if ch not in ". "]
    nb = [(1, 0), (-1, 0), (0, 1), (0, -1)] + ([(1, 1), (1, -1), (-1, 1), (-1, -1)] if diag else [])
    for i, j, _ in cells:
        for dx, dy in nb:
            c.px(x + i + dx, y + j + dy, key)
    for i, j, ch in cells:
        c.px(x + i, y + j, shade if ch == "s" else fill)


def star_pts(cx, cy, ro, ri, n=5, rot=-90):
    pts = []
    for k in range(n * 2):
        r = ro if k % 2 == 0 else ri
        a = math.radians(rot + k * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ----------------------------------------------------------------------------------------------
# the emoji
# ----------------------------------------------------------------------------------------------
def faab():
    """Money bag with a big $ (free-agent budget), tied at the top."""
    c = Canvas()
    # gathered top above the tie (three soft peaks)
    c.poly([(9, 3), (12, 1), (14, 3), (16, 1), (18, 3), (20, 1), (23, 3), (20, 8), (12, 8)], "E")
    # neck flaring into the body
    c.poly([(12, 8), (19, 8), (26, 15), (5, 15)], "E")
    disc(c, 16, 20.5, 13.5, 10.5, DKGRN)
    disc(c, 15.3, 19.8, 12.8, 9.8, "E")
    edge(c, "E", DKGRN, [RIGHT], 1)
    for (x, y) in [(7, 14), (6, 15), (5, 16), (5, 17), (4, 18), (4, 19), (8, 13)]:
        c.px(x, y, "e")
    for (x, y) in [(11, 2), (12, 2), (15, 2), (16, 2)]:
        c.px(x, y, "e")
    # rope tie
    c.rect(11, 7, 10, 2, "O")
    c.rect(11, 8, 10, 1, "o")
    c.px(10, 7, "O"); c.px(21, 7, "O")
    c.px(20, 9, "O"); c.px(21, 10, "O"); c.px(21, 11, "o")
    dollar = [
        ".....##.....",
        "...######...",
        "..########..",
        ".###.##.###.",
        ".###.##.....",
        "..#######...",
        "...#######..",
        ".....##.###.",
        ".###.##.###.",
        "..########..",
        "...######...",
        ".....##.....",
    ]
    keyed_glyph(c, dollar, 10, 14, "G", diag=False)
    for (x, y) in [(15, 14), (16, 14), (13, 15), (14, 15), (12, 16)]:
        c.px(x, y, "Y")
    return c.outline()


def contract():
    """A scroll, rolled at the top, unrolled sheet with text lines, a signature and a wax seal."""
    c = Canvas()
    # sheet
    c.rect(6, 6, 20, 21, "C")
    c.rect(24, 6, 2, 21, "S")      # shade on the right edge of the sheet
    c.rect(6, 7, 20, 1, "S")       # shadow under the roll
    # bottom curl (small roll)
    c.rect(5, 26, 22, 3, "W")
    c.rect(5, 28, 22, 1, "S")
    c.rect(24, 26, 3, 3, "S")
    disc(c, 4.5, 27.5, 1.6, 1.6, "S"); c.px(4, 27, "N")
    # top roll (cylinder) with spiral ends
    c.rect(4, 1, 24, 6, "W")
    c.rect(4, 3, 24, 2, "C")
    c.rect(4, 5, 24, 2, "S")
    c.rect(4, 6, 24, 1, "N")
    for ex in (3.5, 28.5):
        disc(c, ex, 4.0, 2.2, 3.2, "S")
        disc(c, ex, 4.0, 1.2, 2.0, "C")
        c.px(int(ex), 4, "N"); c.px(int(ex), 3, "N")
    # text lines
    for y, (x0, x1) in zip((10, 13, 16), ((9, 22), (9, 21), (9, 17))):
        c.rect(x0, y, x1 - x0 + 1, 1, "N")
    # signature squiggle
    sig = [(9, 22), (10, 21), (11, 20), (12, 21), (12, 22), (13, 23), (14, 22), (15, 21),
           (16, 22), (17, 23), (18, 22)]
    for (x, y) in sig:
        c.px(x, y, "B")
        c.px(x, y + 1, "b") if (x + y) % 3 == 0 else None
    c.rect(9, 24, 10, 1, "S")
    # wax seal
    disc(c, 21.5, 21.5, 3.3, 3.3, "R")
    c.px(20, 19, "r"); c.px(21, 19, "r"); c.px(19, 20, "r"); c.px(20, 20, "r")
    c.px(22, 23, DKRED); c.px(23, 22, DKRED); c.px(21, 23, DKRED); c.px(23, 21, DKRED)
    return c.outline()


def pick():
    """A gold draft-pick ticket with notched corners, a perforated stub and a chunky 1ST."""
    c = Canvas()
    c.rect(1, 7, 30, 18, "G")
    # concave corner notches
    for (cx, cy) in ((1, 7), (31, 7), (1, 25), (31, 25)):
        disc(c, cx, cy, 3.2, 3.2, None)
    # perforation notches top and bottom of the stub line
    disc(c, 10, 7, 1.6, 1.6, None)
    disc(c, 10, 25, 1.6, 1.6, None)
    # bevel
    edge(c, "G", "D", [DOWN, RIGHT])
    edge(c, "G", "Y", [UP, LEFT])
    # perforation
    for y in range(10, 23, 2):
        c.px(9, y, "D")
    # stub star
    c.poly(star_pts(5.0, 16.2, 3.4, 1.4), "D")
    one = [".##.", "###.", ".##.", ".##.", ".##.", ".##.", ".##.", "####"]
    s = [".####", "##...", "##...", ".###.", "...##", "...##", "...##", "####."]
    t = ["######", "..##..", "..##..", "..##..", "..##..", "..##..", "..##..", "..##.."]
    x = 12
    for g in (one, s, t):
        for j, r in enumerate(g):
            for i, ch in enumerate(r):
                if ch == "#":
                    c.px(x + i, 12 + j, "K")
        x += len(g[0]) + 1
    return c.outline()


def scout():
    """Magnifying glass over a gold prospect star."""
    c = Canvas()
    # handle
    capsule(c, 21, 21, 28.5, 28.5, 2.4, "A")
    capsule(c, 21, 21, 28.0, 28.0, 1.0, "M")
    capsule(c, 18.5, 18.5, 21.5, 21.5, 2.0, "N")   # collar
    # lens rim and glass
    disc(c, 12.5, 12.5, 11.0, 11.0, "N")
    disc(c, 12.0, 12.0, 10.5, 10.5, "S")
    disc(c, 12.5, 12.5, 8.4, 8.4, "L")
    # glare arc on the glass
    for (x, y) in [(6, 10), (6, 9), (7, 8), (7, 7), (8, 6), (9, 5)]:
        c.px(x, y, "I")
    # the prospect star in the lens
    c.poly(star_pts(12.8, 13.4, 6.6, 2.7), "G")
    edge(c, "G", "D", [DOWN, RIGHT], against=["G"])
    edge(c, "G", "Y", [UP], against=["G"])
    # twinkles
    for (x, y, k) in [(18, 6, "W"), (17, 6, "I"), (19, 6, "I"), (18, 5, "I"), (18, 7, "I"), (7, 17, "W")]:
        c.px(x, y, k)
    return c.outline()


def lineup():
    """Coach's clipboard: wood board, steel clip, paper with a mini rink and an X / O play."""
    c = Canvas()
    c.rect(3, 3, 26, 28, "O")
    for (x, y) in ((3, 3), (28, 3), (3, 30), (28, 30)):
        c.px(x, y, None)
    edge(c, "O", "o", [DOWN, RIGHT])
    # paper
    c.rect(5, 6, 22, 23, "W")
    c.rect(5, 28, 22, 1, "S")
    # rink outline (rounded), center red line, net at the top
    c.frame(7, 8, 18, 19, "L")
    for (x, y) in ((7, 8), (24, 8), (7, 26), (24, 26)):
        c.px(x, y, "W")
    c.px(8, 9, "L"); c.px(23, 9, "L"); c.px(8, 25, "L"); c.px(23, 25, "L")
    c.rect(8, 17, 16, 1, "R")
    c.rect(14, 9, 4, 1, "R")
    # the play: X (us) drives to the net past the O (them)
    X = ["##..##", ".####.", "..##..", ".####.", "##..##"]
    O = [".####.", "##..##", "##..##", "##..##", ".####."]
    c.stamp(O, 17, 11, {"#": "B"})
    c.stamp(X, 9, 20, {"#": "K"})
    c.stamp(X, 18, 21, {"#": "K"})
    for (x, y) in [(11, 18), (11, 17), (11, 16), (11, 15), (12, 14), (13, 13)]:
        c.px(x, y, "K")
    for (x, y) in [(14, 12), (12, 12), (13, 12), (14, 13), (14, 14)]:
        c.px(x, y, "K")
    # clip
    c.rect(10, 2, 12, 3, "S")
    c.rect(10, 4, 12, 2, "N")
    c.rect(13, 1, 6, 2, "S")
    c.rect(14, 2, 4, 1, "K")
    c.rect(10, 2, 12, 1, "W"); c.rect(13, 1, 6, 1, "W")
    return c.outline()


def medal():
    """Gold medal with a star on a red / blue V ribbon."""
    c = Canvas()
    c.poly([(4, 1), (11, 1), (17, 15), (12, 15)], "R")
    c.poly([(20, 1), (27, 1), (19, 15), (14, 15)], "B")
    c.poly([(7, 1), (8, 1), (14, 15), (13, 15)], "r")
    c.poly([(23, 1), (24, 1), (17, 15), (16, 15)], "b")
    # clasp
    c.rect(12, 13, 8, 3, "D")
    c.rect(12, 13, 8, 1, "Y")
    # medal
    disc(c, 16, 22.5, 8.6, 8.6, "D")
    disc(c, 15.5, 22.0, 7.6, 7.6, "G")
    disc(c, 16, 22.5, 6.0, 6.0, "D")
    disc(c, 15.7, 22.2, 5.4, 5.4, "G")
    c.poly(star_pts(16, 23, 5.4, 2.3), "Y")
    # dark rim around the star so it reads
    for y in range(N):
        for x in range(N):
            if same(c, x, y, "G") and any(same(c, x + dx, y + dy, "Y") for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) and y > 16:
                c.px(x, y, "D")
    c.px(10, 18, "Y"); c.px(11, 17, "Y"); c.px(9, 20, "Y"); c.px(12, 16, "Y")
    return c.outline()


def spoon():
    """The Wooden Spoon: a big wooden spoon on the diagonal."""
    c = Canvas()
    LITE = (222, 170, 108)
    capsule(c, 17, 15, 4.5, 27.5, 2.2, "O")
    disc(c, 4.2, 27.8, 3.0, 3.0, "O")
    rdisc(c, 21.6, 10.4, 10.5, 7.2, -45, "O")
    # shading: lower-right edges darker
    edge(c, "O", "o", [DOWN, RIGHT])
    # bowl hollow
    rdisc(c, 21.6, 10.4, 7.8, 4.8, -45, "o")
    rdisc(c, 22.4, 11.2, 6.2, 3.4, -45, "O")
    # highlights along the upper-left edges
    for (x, y) in [(15, 7), (14, 9), (14, 8), (16, 5), (17, 4), (18, 3), (19, 2)]:
        if same(c, x, y, "O"):
            c.px(x, y, LITE)
    for k in range(10):
        x, y = 15 - k, 15 + k
        if same(c, x - 1, y - 1, "O") or same(c, x - 1, y - 1, "o"):
            c.px(x - 1, y - 1, LITE)
    c.px(2, 26, LITE); c.px(3, 25, LITE)
    # grain on the handle
    for k in range(3):
        c.px(10 - k * 3, 23 + k * 3 - 1, "o")
    c.px(22, 9, LITE); c.px(23, 8, LITE)
    return c.outline()


def pot():
    """The Dynasty Pot: a black cauldron overflowing with gold coins."""
    c = Canvas()
    # handles (rings on the sides)
    for hx in (3.0, 29.0):
        disc(c, hx, 19.5, 2.4, 2.6, "A")
        disc(c, hx, 19.5, 1.0, 1.2, None)
    # cauldron body
    disc(c, 16, 21.5, 12.8, 7.6, "A")
    disc(c, 13.0, 19.8, 6.5, 3.0, "M")
    c.rect(8, 28, 3, 3, "A"); c.rect(21, 28, 3, 3, "A")
    c.px(9, 19, "N"); c.px(10, 18, "N"); c.px(8, 20, "N")
    # rim
    disc(c, 16, 13.8, 14.6, 2.6, "M")
    for x in range(1, 31):
        for y in range(10, 14):
            if same(c, x, y, "M") and not filled(c, x, y - 1):
                c.px(x, y, "N")
    disc(c, 16, 14.4, 14.6, 1.6, "M")
    c.rect(4, 15, 24, 1, "A")
    # coins heaped in the mouth (back to front)
    coins = [(16, 3), (12, 5), (20, 5), (8, 8), (15, 7), (22, 8), (5, 11), (11, 10), (18, 10), (25, 11),
             (8, 12), (14, 12), (21, 12), (27, 13), (3, 13)]
    for (x, y) in coins:
        disc(c, x + .5, y + .6, 3.0, 2.0, "D")
        disc(c, x + .5, y + .1, 2.8, 1.6, "G")
        c.px(x - 1, y - 1, "Y"); c.px(x, y - 1, "Y")
    # a coin tipping over the front of the rim
    disc(c, 23.5, 17.0, 2.9, 2.9, "K")
    disc(c, 23.5, 17.0, 2.2, 2.2, "G")
    c.px(22, 16, "Y"); c.px(23, 15, "Y"); c.px(24, 18, "D"); c.px(25, 17, "D"); c.px(23, 18, "D")
    # sparkle
    c.px(7, 3, "W"); c.px(6, 3, "Y"); c.px(8, 3, "Y"); c.px(7, 2, "Y"); c.px(7, 4, "Y")
    return c.outline()


def octopus():
    """A cute red octopus with eight curling tentacles."""
    c = Canvas()
    tents = [   # back to front
        [(9.0, 15), (5.5, 18), (2.8, 21.5), (2.6, 25.0), (4.6, 26.6), (6.4, 25.0)],
        [(23.0, 15), (26.5, 18), (29.2, 21.5), (29.4, 25.0), (27.4, 26.6), (25.6, 25.0)],
        [(11.0, 17), (8.5, 21), (7.8, 25), (8.6, 28.2), (11.0, 28.8)],
        [(21.0, 17), (23.5, 21), (24.2, 25), (23.4, 28.2), (21.0, 28.8)],
        [(13.5, 18), (12.5, 22.5), (13.2, 26.5), (12.2, 29.6)],
        [(18.5, 18), (19.5, 22.5), (18.8, 26.5), (19.8, 29.6)],
        [(15.0, 18), (15.6, 23), (15.0, 26.0), (15.6, 29.2)],
        [(17.0, 18), (16.6, 21), (17.2, 24.5)],
    ]
    for p in tents:
        path(c, p, 2.15, "K")
        path(c, p, 1.15, "R")
    # head
    disc(c, 16, 10.6, 10.6, 9.6, DKRED)
    disc(c, 15.6, 10.1, 10.1, 9.1, "R")
    # spots and shine
    for (x, y) in [(10, 3), (9, 4), (8, 5), (11, 3)]:
        c.px(x, y, "r")
    c.rect(19, 4, 2, 2, "r"); c.px(23, 7, "r"); c.px(14, 4, "r")
    # eyes
    for ex in (10, 19):
        c.rect(ex, 10, 4, 5, "W")
        c.rect(ex + 1, 12, 2, 3, "K")
        c.px(ex, 10, "R"); c.px(ex + 3, 10, "R")
        c.px(ex + 1, 12, "W")
    # smile
    c.px(15, 17, "K"); c.px(16, 17, "K"); c.px(14, 16, "K"); c.px(17, 16, "K")
    # blush
    c.px(8, 15, "P"); c.px(9, 15, "P"); c.px(22, 15, "P"); c.px(23, 15, "P")
    return c.outline()


def tooth():
    """The emoji face with a huge grin and a missing front tooth."""
    c = face()
    # eyes
    for ex in (9, 20):
        c.rect(ex, 8, 3, 5, "K")
        c.px(ex, 8, "G"); c.px(ex + 2, 8, "G")
        c.px(ex + 1, 9, "W")
    # brows (cocky)
    c.rect(8, 5, 4, 1, "K"); c.rect(20, 5, 4, 1, "K")
    # mouth: wide D shape
    mouth = Canvas()
    mouth.rect(6, 16, 20, 2, "A")
    disc(mouth, 16, 17, 10, 9, "A")
    for y in range(N):
        for x in range(N):
            if same(mouth, x, y, "A") and y >= 16:
                c.px(x, y, (90, 18, 20))
    # keyline the mouth
    for y in range(N):
        for x in range(N):
            if y >= 15 and not (same(mouth, x, y, "A") and y >= 16):
                if any(same(mouth, x + dx, y + dy, "A") and y + dy >= 16 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    c.px(x, y, "K")
    # teeth: top row with the front tooth missing
    for x in range(7, 25):
        for y in (16, 17, 18, 19):
            if not (14 <= x <= 17):
                if same(c, x, y, (90, 18, 20)):
                    c.px(x, y, "W")
    for x in range(7, 25):
        if same(c, x, 19, "W"):
            c.px(x, 19, "S")
    for x in (10, 21):
        c.px(x, 18, "S"); c.px(x, 19, "N")
    for x in (14, 17):
        for y in (16, 17, 18):
            c.px(x, y, "W")
        c.px(x, 19, "S")
    # tongue
    disc(c, 16, 24, 4.5, 2.4, "r")
    for y in range(N):
        for x in range(N):
            if same(c, x, y, "r") and not (same(mouth, x, y, "A") and y >= 16):
                c.px(x, y, "K" if y < 27 else "G")
    return c.outline()


def injury():
    """First-aid kit: white case with a red cross and a handle."""
    c = Canvas()
    # handle
    c.rect(10, 3, 12, 3, "A")
    c.rect(13, 6, 6, 2, None)
    c.rect(10, 6, 3, 3, "A"); c.rect(19, 6, 3, 3, "A")
    c.rect(11, 3, 10, 1, "M")
    # case
    c.rect(1, 8, 30, 22, "W")
    for (x, y) in ((1, 8), (30, 8), (1, 29), (30, 29)):
        c.px(x, y, None)
    edge(c, "W", "S", [DOWN, RIGHT], depth=2)
    c.rect(2, 12, 28, 1, "S")       # lid seam
    c.rect(14, 11, 4, 2, "N")       # latch
    # red cross
    c.rect(13, 15, 6, 13, "R")
    c.rect(9, 18, 14, 6, "R")
    c.rect(13, 15, 6, 1, "r"); c.rect(9, 18, 4, 1, "r"); c.rect(19, 18, 4, 1, "r")
    c.rect(13, 27, 6, 1, DKRED); c.rect(9, 23, 4, 1, DKRED); c.rect(19, 23, 4, 1, DKRED)
    return c.outline()


def mullet():
    """Hockey flow, in profile: short crop on top, long hair flowing down the back over the jersey collar.
    (A straight back-of-head view read as a hair blob at 22 px, so the profile carries the silhouette.)"""
    c = Canvas()
    LITE = (226, 172, 104)
    # jersey shoulder and black collar trim
    c.poly([(5, 24), (14, 23), (24, 23), (28, 26), (29, 30), (2, 30), (3, 26)], "G")
    c.px(2, 30, None); c.px(29, 30, None)
    edge(c, "G", "D", [DOWN, RIGHT])
    c.rect(4, 29, 25, 1, "K")
    c.poly([(12, 20), (22, 20), (24, 23), (11, 23)], "K")
    # head, face and hair laid out row by row: (x0, x1, color)
    rows = {
        1: [(9, 9, "o"), (12, 12, "o"), (15, 15, "o"), (18, 18, "o"), (21, 21, "o")],
        2: [(8, 21, "o")],
        3: [(6, 22, "o")],
        4: [(5, 23, "o")],
        5: [(4, 21, "o"), (22, 24, "G")],
        6: [(4, 18, "o"), (19, 24, "G")],
        7: [(4, 17, "o"), (18, 24, "G")],
        8: [(4, 16, "o"), (17, 25, "G"), (20, 23, "o")],
        9: [(4, 16, "o"), (17, 24, "G")],
        10: [(4, 12, "h"), (13, 24, "G")],
        11: [(4, 12, "h"), (13, 25, "G")],
        12: [(4, 12, "h"), (13, 27, "G")],
        13: [(4, 12, "h"), (13, 28, "G")],
        14: [(4, 12, "h"), (13, 25, "G")],
        15: [(4, 12, "h"), (13, 25, "G"), (21, 25, "o")],
        16: [(4, 12, "h"), (13, 25, "G"), (22, 25, "o")],
        17: [(4, 12, "h"), (13, 14, "D"), (15, 24, "G")],
        18: [(4, 12, "h"), (13, 16, "D"), (17, 23, "G")],
        19: [(3, 12, "h"), (13, 18, "D"), (19, 21, "G")],
        20: [(3, 11, "h")],
        21: [(2, 11, "h")],
        22: [(2, 11, "h")],
        23: [(1, 11, "h")],
        24: [(0, 3, "h"), (5, 7, "h"), (9, 11, "h")],
        25: [(0, 1, "h"), (6, 6, "h"), (10, 10, "h")],
    }
    for y, segs in rows.items():
        for (x0, x1, k) in segs:
            for x in range(x0, x1 + 1):
                c.px(x, y, {"h": "O"}.get(k, k))
    c.px(1, 21, "O"); c.px(1, 22, "O"); c.px(0, 23, None); c.px(0, 24, None); c.px(0, 25, None)
    c.px(1, 25, "O"); c.px(1, 24, "O")
    # long wavy strands in the flow
    for y in range(10, 26):
        for x in range(0, 13):
            if same(c, x, y, "O"):
                w = x + (1 if (y // 3) % 2 else 0)
                c.px(x, y, {0: "o", 1: "O", 2: LITE, 3: "O"}[w % 4])
    # short texture in the crop
    for (x, y) in [(10, 2), (13, 2), (16, 2), (19, 2), (8, 4), (11, 3), (14, 4), (17, 3), (20, 4), (6, 6), (9, 5),
                   (12, 6), (15, 5), (7, 8), (10, 7), (13, 8)]:
        c.px(x, y, "O")
    # ear
    for (x, y) in [(13, 10), (14, 10), (13, 11), (13, 12), (13, 13), (14, 14), (15, 14), (15, 12)]:
        c.px(x, y, "D")
    # eye, nostril, mouth, highlights
    c.rect(21, 10, 2, 2, "K")
    c.px(25, 14, "D")
    c.px(24, 17, "D")
    c.px(23, 6, "Y"); c.px(24, 7, "Y"); c.px(26, 12, "Y"); c.px(27, 13, "Y")
    return c.outline()


def beard(main="o", strand="O"):
    """The emoji face (nudged up 1 px to leave room below the chin) with a big scraggly playoff beard."""
    c = face(cy=14.5)
    # eyes and tired / determined brows
    for ex in (9, 20):
        c.rect(ex, 7, 3, 4, "K")
        c.px(ex + 1, 8, "W")
    c.rect(8, 5, 5, 1, "K"); c.px(12, 6, "K")
    c.rect(19, 5, 5, 1, "K"); c.px(19, 6, "K")
    DK = (92, 54, 22)
    # cheek line: sideburns from ear level, dipping under the cheeks, jagged
    jag_top = [0, 0, 0, 0, 1, 0, 1, -1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, -1, 1, 0, 1, 0, 0, 0, 0, 0, 0]
    # scraggly overhang below the jaw (px past the face edge), one value per column
    hang = [0, 0, 0, 1, 2, 0, 2, 1, 3, 1, 3, 0, 3, 2, 3, 1, 3, 0, 3, 2, 3, 1, 3, 0, 2, 1, 2, 0, 1, 0, 0, 0]
    for x in range(2, 30):
        col_px = [y for y in range(N) if filled(c, x, y)]
        if not col_px:
            continue
        d = abs(x + .5 - 16)
        top = 14 if d < 7 else max(10, int(14 - (d - 7) * 1.2))
        top += jag_top[x]
        bot = min(30, max(col_px) + hang[x])
        for y in range(top, bot + 1):
            c.px(x, y, main)
    for (x, y) in [(2, 14), (2, 15), (2, 16), (29, 14), (29, 15), (29, 16), (2, 18), (29, 18)]:
        c.px(x, y, main)
    # strands: wiry hairs running down and out from the chin (fixed seed, so it is deterministic)
    rng = random.Random(19)
    for _ in range(26):
        x0, y0 = rng.randint(3, 28), rng.randint(13, 27)
        dx = -1 if x0 < 15 else (1 if x0 > 16 else 0)
        length = rng.randint(2, 4)
        for k in range(length):
            xx, yy = x0 + (dx if k >= 2 else 0), y0 + k
            if same(c, xx, yy, main):
                c.px(xx, yy, strand if k < length - 1 or rng.random() < .5 else DK)
    # moustache, mouth
    c.rect(10, 15, 12, 2, strand)
    c.px(9, 16, strand); c.px(22, 16, strand); c.px(9, 17, strand); c.px(22, 17, strand)
    c.rect(13, 18, 6, 2, (110, 20, 22))
    c.rect(13, 18, 6, 1, "K")
    # shadow under the beard
    for x in range(N):
        col_px = [y for y in range(N) if same(c, x, y, main) or same(c, x, y, strand)]
        if col_px and max(col_px) >= 24:
            c.px(x, max(col_px), DK)
    return c.outline()


def big_letter(c, shape_fn, main, light, dark, depth=2):
    """Chunky arcade letter: an extruded dark copy below/right, the face on top, a light top-left bevel."""
    m = Canvas()
    shape_fn(m)
    for d in range(depth, 0, -1):
        for y in range(N):
            for x in range(N):
                if filled(m, x, y):
                    c.px(x + d, y + d, dark)
    for y in range(N):
        for x in range(N):
            if filled(m, x, y):
                c.px(x, y, main)
    for y in range(N):
        for x in range(N):
            if filled(m, x, y) and (not filled(m, x, y - 1) or not filled(m, x - 1, y)):
                c.px(x, y, light)


def w():
    c = Canvas()

    def shape(m):
        m.poly([(1, 3), (7, 3), (11, 26), (6, 26)], "G")
        m.poly([(6, 26), (11, 26), (16, 9), (13, 9)], "G")
        m.poly([(13, 9), (17, 9), (21, 26), (17, 26)], "G")
        m.poly([(17, 26), (22, 26), (27, 3), (21, 3)], "G")
        m.poly([(12, 9), (18, 9), (18, 13), (12, 13)], "G")
    big_letter(c, shape, "G", "Y", "D")
    return c.outline()


def l():
    c = Canvas()

    def shape(m):
        m.rect(6, 1, 10, 27, "R")
        m.rect(6, 19, 20, 9, "R")
    big_letter(c, shape, "R", "r", DKRED, depth=3)
    return c.outline()


def gg():
    c = Canvas()
    c.rect(1, 5, 30, 22, "K")
    for (x, y) in ((1, 5), (30, 5), (1, 26), (30, 26)):
        c.px(x, y, None)
    # bezel
    c.frame(2, 6, 28, 20, "M")
    for (x, y) in ((2, 6), (29, 6), (2, 25), (29, 25)):
        c.px(x, y, "K")
    G = [
        "..########..",
        ".##########.",
        "####....###.",
        "###.........",
        "###.........",
        "###...######",
        "###...######",
        "###.....####",
        "####....####",
        ".##########.",
        "..#########.",
    ]
    for gx in (3, 17):
        for j, r in enumerate(G):
            for i, ch in enumerate(r):
                if ch == "#":
                    below = G[j + 1][i] if j + 1 < len(G) else "."
                    c.px(gx + i, 10 + j, "S" if below != "#" else "W")
    return c.outline()


def pylon():
    """Orange traffic cone with white reflective bands."""
    c = Canvas()
    c.poly([(13.5, 1), (17.5, 1), (25.5, 25), (5.5, 25)], "F")
    c.rect(1, 25, 30, 4, "F")
    for (x, y) in ((1, 28), (30, 28)):
        c.px(x, y, None)
    # bands
    for y in range(N):
        for x in range(N):
            if same(c, x, y, "F") and (8 <= y <= 10 or 16 <= y <= 19):
                c.px(x, y, "W")
    # shading: right side of cone and base darker, left highlight
    def right_part(x, y):
        # pixels in the right ~third of the cone at this row
        xs = [xx for xx in range(N) if filled(c, xx, y)]
        return x >= max(xs) - max(1, (max(xs) - min(xs)) // 3)
    shades = []
    for y in range(0, 25):
        for x in range(N):
            if filled(c, x, y) and right_part(x, y):
                shades.append((x, y))
    for (x, y) in shades:
        c.px(x, y, DKORG if same(c, x, y, "F") else "S")
    c.rect(1, 27, 30, 2, DKORG)
    c.rect(2, 25, 28, 1, "Y")
    c.px(1, 28, None); c.px(30, 28, None)
    for y in range(3, 25):
        xs = [xx for xx in range(N) if filled(c, xx, y)]
        if xs and same(c, min(xs) + 1, y, "F"):
            c.px(min(xs) + 1, y, "Y")
    return c.outline()


def sieve():
    """A leaky colander: pucks dropping straight through the holes."""
    c = Canvas()
    # handles
    c.rect(1, 5, 4, 3, "N"); c.rect(27, 5, 4, 3, "N")
    c.rect(1, 5, 4, 1, "S"); c.rect(27, 5, 4, 1, "S")
    # bowl
    fill_where(c, lambda X, Y: Y >= 6 and ((X - 16) / 13.0) ** 2 + ((Y - 6) / 11.5) ** 2 <= 1, "S")
    disc(c, 16, 6.5, 13.8, 2.2, "N")
    disc(c, 16, 6.2, 12.4, 1.4, "A")
    c.rect(11, 16, 10, 2, "N")      # foot ring
    edge(c, "S", "N", [RIGHT, DOWN])
    # holes
    for (x, y) in [(6, 10), (10, 10), (14, 10), (18, 10), (22, 10), (26, 10),
                   (8, 13), (12, 13), (16, 13), (20, 13), (24, 13)]:
        if filled(c, x, y):
            c.px(x, y, "K")
    # pucks falling out the bottom (top face lit, dark side band)
    for (x, y) in [(4, 20), (13, 20), (22, 21), (8, 26), (18, 26)]:
        c.stamp([".MMMM.", "MNNNNM", "AAAAAA", ".AAAA."], x, y)
    return c.outline()


def chirp():
    """A small gold bird mid-chirp with a speech burst."""
    c = Canvas()
    # speech burst
    c.poly(star_pts(24.0, 7.9, 6.9, 4.5, n=8, rot=-80), "W")
    c.rect(23, 4, 3, 5, "R")
    c.rect(23, 10, 3, 2, "R")
    # bird
    disc(c, 11, 20, 9.2, 8.6, "G")
    disc(c, 12.5, 22.5, 5.5, 4.5, "Y")       # belly
    c.poly([(3, 18), (1, 14), (5, 17)], "D")   # tail
    rdisc(c, 7.5, 22, 4.5, 2.8, 25, "D")      # wing
    c.px(10, 11, "G"); c.px(11, 10, "G"); c.px(12, 11, "G"); c.px(9, 10, "G")   # tuft
    # beak: wide open, mouth showing
    c.rect(19, 17, 3, 3, (110, 20, 22))
    c.poly([(19, 14), (25, 15), (19, 17)], "F")
    c.poly([(19, 20), (24, 22), (19, 22)], "F")
    c.px(19, 15, "Y"); c.px(20, 15, "Y")
    # eye
    c.rect(14, 15, 2, 3, "K"); c.px(14, 15, "W")
    # feet
    c.rect(9, 28, 1, 3, "F"); c.rect(13, 28, 1, 3, "F")
    c.px(8, 30, "F"); c.px(12, 30, "F")
    return c.outline()


def apple():
    """A red apple with a leaf (slang for an assist)."""
    c = Canvas()
    disc(c, 11.5, 18.5, 9.5, 10.5, DKRED)
    disc(c, 20.5, 18.5, 9.5, 10.5, DKRED)
    disc(c, 11.0, 18.0, 9.0, 10.0, "R")
    disc(c, 19.5, 17.5, 8.8, 9.6, "R")
    # dimple at the top
    c.px(15, 8, None); c.px(16, 8, None); c.px(15, 9, "o"); c.px(16, 9, DKRED)
    # shine
    for (x, y) in [(6, 12), (6, 13), (5, 14), (5, 15), (7, 11), (8, 10)]:
        c.px(x, y, "r")
    c.rect(7, 13, 2, 2, "W")
    # stem
    c.rect(15, 3, 2, 6, "o")
    c.px(14, 2, "o"); c.px(14, 3, "o")
    # leaf
    rdisc(c, 21.5, 4.5, 5.2, 2.4, -25, "E")
    for k in range(5):
        c.px(18 + k, 6 - k // 2, "e")
    return c.outline()


def sauce():
    """Hot-sauce bottle with flames on the label."""
    c = Canvas()
    # cap
    c.rect(13, 1, 6, 4, "A"); c.rect(13, 1, 6, 1, "M"); c.rect(13, 3, 6, 1, "M")
    # neck
    c.rect(14, 5, 4, 6, "R")
    # shoulders and body
    c.poly([(14, 10), (17, 10), (23, 16), (8, 16)], "R")
    c.rect(8, 16, 16, 15, "R")
    c.px(8, 30, None); c.px(23, 30, None)
    edge(c, "R", DKRED, [RIGHT], depth=2)
    c.rect(10, 15, 1, 12, "r"); c.px(15, 6, "r"); c.px(15, 7, "r"); c.px(15, 8, "r")
    # label
    c.rect(8, 17, 16, 12, "C")
    c.rect(8, 17, 16, 1, "W")
    c.rect(22, 17, 2, 12, "S")
    flame = [
        "...#.....",
        "...##..#.",
        "..###.##.",
        ".#######.",
        ".###o###.",
        "###ooo###",
        "##ooyoo##",
        "##oyyyo##",
        ".#oyyyo#.",
        "..#####..",
    ]
    c.stamp(flame, 11, 18, {"#": "R", "o": "F", "y": "G"})
    return c.outline()


def lock():
    """Padlock: steel shackle, gold body, keyhole."""
    c = Canvas()
    # shackle
    fill_where(c, lambda X, Y: Y <= 14 and 5.2 <= math.hypot(X - 16, Y - 11) <= 9.0 or
               (Y > 11 and Y <= 16 and (7 <= X <= 10.4 or 21.6 <= X <= 25)), "S")
    fill_where(c, lambda X, Y: Y <= 11 and 5.2 <= math.hypot(X - 16, Y - 11) <= 6.4, "N")
    for (x, y) in [(10, 5), (11, 4), (12, 3), (9, 7), (8, 9)]:
        c.px(x, y, "W")
    # body
    c.rect(3, 14, 26, 17, "G")
    for (x, y) in ((3, 14), (28, 14), (3, 30), (28, 30)):
        c.px(x, y, None)
    edge(c, "G", "D", [DOWN, RIGHT], depth=2)
    c.rect(4, 15, 23, 1, "Y")
    c.rect(4, 16, 1, 12, "Y")
    # keyhole
    disc(c, 16, 20.5, 2.6, 2.6, "K")
    c.rect(15, 21, 2, 6, "K")
    return c.outline()


EMOJI = [
    ("blha_faab", faab), ("blha_contract", contract), ("blha_pick", pick), ("blha_scout", scout),
    ("blha_lineup", lineup), ("blha_medal", medal), ("blha_spoon", spoon), ("blha_pot", pot),
    ("blha_octopus", octopus), ("blha_tooth", tooth), ("blha_injury", injury), ("blha_mullet", mullet),
    ("blha_beard", beard), ("blha_w", w), ("blha_l", l), ("blha_gg", gg),
    ("blha_pylon", pylon), ("blha_sieve", sieve), ("blha_chirp", chirp), ("blha_apple", apple),
    ("blha_sauce", sauce), ("blha_lock", lock),
]


def main():
    paths = []
    for name, fn in EMOJI:
        p = OUT / f"{name}.png"
        save_png(fn(), p)
        paths.append(p)
    sheet(paths, HERE / "static_b_sheet.png", cols=6)
    return paths


if __name__ == "__main__":
    for p in main():
        print(p.name, p.stat().st_size)
