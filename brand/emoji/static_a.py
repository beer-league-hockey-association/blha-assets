"""BLHA static emoji, group A (22 emoji): league mark, gear, rink bits and reaction props.

Run:  python static_a.py          -> writes static/<name>.png for all 22 and static_a_sheet.png
      python static_a.py name ... -> only those (sheet still covers all files that exist)
Deterministic: no randomness.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pix import Canvas, save_png, sheet  # noqa: E402


# --- helpers -------------------------------------------------------------------------------
def grid(text: str) -> list[str]:
    """A multi-line string -> stamp rows (blank first/last lines dropped, '.' transparent)."""
    rows = text.strip("\n").split("\n")
    return [r.rstrip() for r in rows]


def sym(text: str, odd: bool = False) -> list[str]:
    """Left half rows -> mirrored full rows (even width, or odd with the last column as the center).
    Half rows are padded to the same width first so the mirror lines up."""
    rows = grid(text)
    n = max(len(r) for r in rows)
    rows = [r.ljust(n, ".") for r in rows]
    return [r + (r[-2::-1] if odd else r[::-1]) for r in rows]


def rrect(c: Canvas, x, y, w, h, r, col):
    """Filled rectangle with rounded corners of radius r."""
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            cx = min(max(xx + .5, x + r), x + w - r)
            cy = min(max(yy + .5, y + r), y + h - r)
            if (xx + .5 - cx) ** 2 + (yy + .5 - cy) ** 2 <= r * r + .25:
                c.px(xx, yy, col)


def capsule(c: Canvas, x0, y0, x1, y1, r, col):
    """Filled stadium shape: every pixel within r of the segment (x0, y0)-(x1, y1)."""
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy or 1
    for y in range(c.h):
        for x in range(c.w):
            px, py = x + .5, y + .5
            t = max(0, min(1, ((px - x0) * dx + (py - y0) * dy) / L2))
            qx, qy = x0 + t * dx - px, y0 + t * dy - py
            if qx * qx + qy * qy <= r * r:
                c.px(x, y, col)


def recenter(c: Canvas, dy_bias: int = 0) -> Canvas:
    """Move the drawing so its bounding box sits in the middle of the 32 x 32 frame."""
    l, t, r, b = c.img.getbbox()
    w, h = r - l, b - t
    nx, ny = (c.w - w) // 2, (c.h - h) // 2 + dy_bias
    ny = max(0, min(c.h - h, ny))
    crop = c.img.crop((l, t, r, b))
    c.img = c.img.copy()
    c.img.paste((0, 0, 0, 0), (0, 0, c.w, c.h))
    c.img.alpha_composite(crop, (nx, ny))
    return c


def clear_outer(c: Canvas, key="K"):
    """Make keyline pixels that touch the outside transparent (so outline() can redraw them)."""
    from pix import col as _col
    k = _col(key)
    seen, stack = set(), [(x, y) for x in range(c.w) for y in (0, c.h - 1)] + \
        [(x, y) for y in range(c.h) for x in (0, c.w - 1)]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < c.w and 0 <= y < c.h):
            continue
        p = c.get(x, y)
        if p[3] and p != k:
            continue
        seen.add((x, y))
        if p[3]:
            c.px(x, y, None)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


# --- 1. the league B ------------------------------------------------------------------------
B32 = grid("""
..KKKKKKKKKKKKKKKKKK........
.KGGGGGGGGGGGGGGGGGGKK......
KGGGGGGGGGGGGGGGGGGGGGKK....
KGGWWWWWWWWWWWWWWWWGGGGGK...
KGGWWWWWWWWWWWWWWWWWWGGGGK..
KGGWWWWWWWWWWWWWWWWWWWWGGGK.
KGGWWWWWWWWWWWWWWWWWWWWWGGGK
KGGWWWWWGGGGGGGGWWWWWWWWWGGK
KGGWWWWWGKKKKKKGGGGGWWWWWGGK
KGGWWWWWGKKKKKKKKKKGWWWWWGGK
KGGWWWWWGKKKKKKKKKKGWWWWWGGK
KGGWWWWWGKKKKKKKKGGGWWWWWGGK
KGGWWWWWGKKKKKKKGGWWWWWWWGGK
KGGWWWWWGGGGGGGGGWWWWWWWGGGK
KGGWWWWWWWWWWWWWWWWWWWGGGGK.
KGGWWWWWWWWWWWWWWWWWWGGGGK..
KGGWWWWWWWWWWWWWWWWWWGGGGK..
KGGWWWWWWWWWWWWWWWWWWWGGGGK.
KGGWWWWWGGGGGGGGWWWWWWWWGGGK
KGGWWWWWGKKKKKKGGGWWWWWWWGGK
KGGWWWWWGKKKKKKKKGGGWWWWWGGK
KGGWWWWWGKKKKKKKKKKGWWWWWGGK
KGGWWWWWGKKKKKKKKKKGWWWWWGGK
KGGWWWWWGKKKKKKKGGGGWWWWWGGK
KGGWWWWWGGGGGGGGGWWWWWWWWGGK
KGGWWWWWWWWWWWWWWWWWWWWWWGGK
KGGWWWWWWWWWWWWWWWWWWWWGGGGK
KGGWWWWWWWWWWWWWWWWWWGGGGGK.
KGGWWWWWWWWWWWWWWWWGGGGGKK..
KGGGGGGGGGGGGGGGGGGGGGKK....
.KGGGGGGGGGGGGGGGGGGKK......
..KKKKKKKKKKKKKKKKKK........
""")


def blha_b():
    c = Canvas()
    c.stamp(B32, 2, 0)
    clear_outer(c)
    return c.outline()


# --- 2. puck --------------------------------------------------------------------------------
def _ell_low(cx, cy, rx, ry, x):
    """Lowest pixel row of an ellipse (pix.ellipse rules) in column x, or None."""
    best = None
    for y in range(32):
        d = ((x + .5 - cx - .5) / (rx + .5)) ** 2 + ((y + .5 - cy - .5) / (ry + .5)) ** 2
        if d <= 1:
            best = y
    return best


def blha_puck():
    c = Canvas()
    cx, rx, ry, top, bot = 15.5, 14, 6, 10.5, 18.5
    c.ellipse(cx, bot, rx, ry, "A")
    c.rect(1, 11, 30, 8, "A")
    for x in range(1, 31):     # knurled grip band on the side
        yt, yb = _ell_low(cx, top, rx, ry, x), _ell_low(cx, bot, rx, ry, x)
        if yt is None:
            continue
        for y in range(yt + 2, yb - 1):
            if (x + y) % 2 == 0:
                c.px(x, y, "M")
    c.ellipse(cx, top, rx, ry, "N")
    c.ellipse(cx, top - .5, rx - 1, ry - 1, "M")
    for x, y in ((6, 6), (7, 5), (8, 5), (9, 4), (10, 4), (11, 4), (5, 7)):
        c.px(x, y, "S")
    c.stamp(grid("""
DDDDDD..
GGGGGGG.
GG...GG.
GGGGGG..
GG...GG.
GGGGGGG.
"""), 12, 8)
    c.stamp(grid("""
YYYYY...
YY......
YYYYY...
YY......
YY......
"""), 12, 9)
    return recenter(c.outline())


# --- 3. stick -------------------------------------------------------------------------------
def blha_stick():
    c = Canvas()
    for y in range(6, 19):             # shaft: 4 px diagonal band, lit on its upper edge
        x0 = y + 1
        for i, k in enumerate("AMNS"):
            c.px(x0 + i, y, k)
    for y, (a, b) in zip(range(1, 6), ((2, 4), (2, 6), (3, 7), (4, 8), (5, 9))):   # taped knob
        for x in range(a, b + 1):
            c.px(x, y, "S" if (x + y) % 3 == 0 else "W")
    for y in (10, 11, 12):             # gold stick graphic
        x0 = y + 1
        for i, k in enumerate("DGGY"):
            c.px(x0 + i, y, k)
    c.stamp(grid("""
....AMNS.......
...AAMMNS....WW
..AAAMWWSWWSWWW
..AAAAWWSWWSWWW
..AAAAWWSWWSWWW
...AAAWWSWWSWW.
....AASSSSSSS..
"""), 16, 19)
    return recenter(c.outline())


# --- 4. goalie mask -------------------------------------------------------------------------
def blha_mask():
    c = Canvas()
    c.stamp(sym("""
.......WWWWW
.....WWWWWWW
....WWWWWWWW
...WWWWWWWWW
..WWWWWWWWWW
.WWWWWWWWWWW
.WWWWWWWWWWW
WWWWWWWWWWWW
WWWWWWWWWWWW
WWWWWWWWWWWW
WWWWKKKKKKKK
WWWKAAKAAAKA
WWKAAAKAAAKA
WWKKKKKKKKKK
WWKAAAKAAAKA
WWWKAAKAAAKA
WWWKKKKKKKKK
WWWWKAKAAAKA
WWWWWKKAAAKA
WWWWWWKKKKKK
WWWWWWKAAAKA
WWWWWWWKKKKK
WWWWWWWWWWWW
WWWWWWWWWWWW
.WWWWWWWWWWW
.WWWWWWWWWWW
..WWWWWWWWWW
...WWWWWWWWW
....WWWWWWWW
......WWWWWW
""", odd=True), 4, 1)
    c.stamp(sym("""
............
............
............
...D........
..DG....D...
.DGG...DG...
.GYG..DGG..D
DGYG.DGYG.DG
GYYGDGYGGDGY
GYGGGYYGGGYY
""", odd=True), 4, 1)
    for y in range(2, 31):            # cream shading down the right side of the shell
        xs = [x for x in range(32) if c.get(x, y)[:3] == (252, 252, 252)]
        if xs:
            c.px(max(xs), y, "C")
    return recenter(c.outline())


# --- 5. skate -------------------------------------------------------------------------------
def blha_skate():
    c = Canvas()
    c.stamp(grid("""
.NN.............................
.MAN..........NMMN..............
.MAANNNNNNNNN.MAAM..............
..MMMMMMMMMMMNMWWM..............
..MAAAAAAAAAAMWAAWA.............
..MAAAAAAAAAAAMWWAA.............
..MAAAAAAAAAAAAMWAWA............
..MAAAAAAAAAAAAAAWWAA...........
..MAAAAAAAAAAAAAAMAWWA..........
..MAAAAAAAAAAAAAAAMAWAWA........
.MAAAAAAAAAAAAAAAAAMWWAAA.......
.MAAAAAAAAAAAAAAAAAAAMAWWAA.....
.MAAAAAAAAAAAAAAAAAAAAAAAAAA....
.MAAAAAAAAAAAAAAAAAAAAAAAAAAM...
.MGGGGGGGGGGGGGGGGGGGGGGGGGGGM..
.MAAAAAAAAAAAAAAAAAAAAAAAAAAAM..
..KKKKKKKKKKKKKKKKKKKKKKKKKKK...
...WWWWWWW........WWWWWWWWW.....
...CWWWWWC.......CWWWWWWWC......
....CWWWWWWWWWWWWWWWWWWWC.......
..SSIIIIIIIIIIIIIIIIIIIIIIIIIS..
.SSSSSSSSSSSSSSSSSSSSSSSSSSSSSS.
..NNNNNNNNNNNNNNNNNNNNNNNNNNNN..
"""), 0, 4)
    return recenter(c.outline())


# --- 6. helmet ------------------------------------------------------------------------------
def blha_helmet():
    c = Canvas()
    c.stamp(grid("""
........YYYYYYYYYY............
.....YYYGGGGGGGGGGGGG.........
....YGGGGGGGGGGGGGGGGGG.......
...YGGGGGGGGGGGGGGGDGGGG......
..YGGGGGGGGGGGGGGGGDGGGGG.....
..YGGGGGGGGGGGGGGGGDGGGGGG....
.YGGGGGGGGGGGGGGGGGDGGGGGGG...
.YGGGGGGGGGGGGGGGGGDGGGGGGG...
.GGGGGGGGGGGGGGGGGGDGGGGGGGG..
.GGGGGGGGGGGGGGGGGGDGGGGGGGG..
.GGGGGGGGGGGGGGGGGGDGGGGGGGG..
.GGGGGGGGGGGGGGGGGGDDDDDDDDD..
.GGGGGGGGGAAAAAAGG.SLLLLLLLLL.
.GGGGGGGGAMMMMMMAG.LWLLLLLLLLL
.DGGGGGGGAMNMMNMAG.LLWLLLLLLLL
.DGGGGGGGAMMMMMMAG.LLLWLLLLLLL
..DGGGGGGAMNMMNMA..LLLLWLLLLLL
..AAAAAAAAMMMMMMA..LLLLLLLLLLL
...AAAAAAAAAAAAA....AAAAAAAAAA
...........AAAA...............
"""), 1, 5)
    return recenter(c.outline())


# --- 7. jersey ------------------------------------------------------------------------------
def blha_jersey():
    c = Canvas()
    c.stamp(sym("""
.........AAAKKK
......AAAAAAAWK
....AAAAAAAAAAW
..AAAAAAAAAAAAA
.GAAAAAAAAAAAAA
GGGAAAAAAAAAAAA
GGGGGGAAAAAAAAA
GGGGGGGGGGGGGGG
GGGGGGGGGGGGGGG
KKKKKGGGGGGGGGG
WWWWWGGGGGGGGGG
KKKKKKGGGGGGGGG
GGGGGGGGGGGGGGG
GGGGGGGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....GGGGGGGGGG
.....KKKKKKKKKK
.....WWWWWWWWWW
.....KKKKKKKKKK
.....GGGGGGGGGG
"""), 1, 3)
    c.stamp(grid("""
KKKKKK..
KWWWWWK.
KWWKKWWK
KWWKKWWK
KWWWWWK.
KWWKKWWK
KWWKKWWK
KWWWWWK.
KKKKKK..
"""), 12, 11)
    return recenter(c.outline())


# --- 8. rink --------------------------------------------------------------------------------
def blha_rink():
    c = Canvas()
    rrect(c, 1, 6, 30, 20, 7, "I")
    c.rect(4, 8, 1, 16, "R"); c.rect(27, 8, 1, 16, "R")        # goal lines
    c.rect(9, 6, 2, 20, "b"); c.rect(21, 6, 2, 20, "b")        # blue lines
    c.circle(15.5, 15.5, 3, "b", fill=False)                   # center circle
    c.rect(15, 6, 2, 20, "R")                                  # center red line
    c.rect(15, 15, 2, 2, "b")                                  # center dot
    for x in (5, 26):                                          # creases
        c.rect(x, 14, 1, 4, "L")
    c.rect(3, 15, 1, 2, "R"); c.rect(28, 15, 1, 2, "R")        # nets
    for x, y in ((6, 11), (6, 20), (25, 11), (25, 20)):        # end-zone dots
        c.rect(x, y, 1, 1, "R")
    return recenter(c.outline())


# --- 9. cup ---------------------------------------------------------------------------------
def _silver_band(c, x0, x1, y0, y1):
    c.rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, "S")
    c.rect(x0 + 1, y0, 1, y1 - y0 + 1, "W")
    c.rect(x1 - 1, y0, 2, y1 - y0 + 1, "N")


def blha_cup():
    c = Canvas()
    # shallow bowl on top, much narrower than the base
    c.stamp(grid("""
SWWWWWWWWWWWWWWS
SNNNNNNNNNNNNNNS
SWSSSSSSSSSSSNNS
.SWSSSSSSSSSSNN.
..SWSSSSSSSSNN..
....SSSSSSSN....
"""), 8, 1)
    c.rect(11, 7, 10, 1, "G")
    _silver_band(c, 13, 18, 8, 8)
    c.rect(11, 9, 10, 1, "G")
    _silver_band(c, 11, 20, 10, 12)       # tiers step out toward the base
    c.rect(10, 13, 12, 1, "G")
    _silver_band(c, 9, 22, 14, 17)
    c.rect(8, 18, 16, 1, "G")
    _silver_band(c, 7, 24, 19, 22)
    c.rect(6, 23, 20, 1, "G")
    _silver_band(c, 5, 26, 24, 27)
    c.rect(4, 28, 24, 2, "G"); c.rect(4, 29, 24, 1, "D")
    for y in (15, 16, 20, 21, 25, 26):     # engraved name rows
        for x in range(8, 25):
            if c.get(x, y)[:3] == (154, 161, 169) and (x + y) % 2 == 0:
                c.px(x, y, "N")
    return recenter(c.outline())


# --- 10. banner -----------------------------------------------------------------------------
def blha_banner():
    c = Canvas()
    c.poly([(6, 5), (26, 5), (26, 31), (16, 25), (6, 31)], "G")
    c.rect(6, 5, 1, 26, "Y")
    c.rect(24, 5, 2, 26, "D")
    c.rect(6, 5, 20, 2, "D")
    c.rect(2, 3, 28, 2, "o"); c.rect(2, 3, 28, 1, "O")
    c.stamp(grid("""
.YY.
YGGY
YGGD
.DD.
"""), 0, 2)
    c.stamp(grid("""
.YY.
YGGY
YGGD
.DD.
"""), 28, 2)
    c.stamp(grid("""
WWWWWWWWWW
W.WWWWWS.W
W.WWWWWS.W
.WWWWWWSW.
..WWWWS...
....WS....
...WWWS...
..WWWWWS..
"""), 11, 7)
    c.rect(8, 17, 16, 7, "K")
    c.text(9, 18, "2026", "W")
    return recenter(c.outline())


# --- 11. beer -------------------------------------------------------------------------------
def blha_beer():
    c = Canvas()
    c.rect(4, 9, 18, 21, "I")                    # glass
    c.rect(5, 10, 16, 17, "G")                   # beer
    c.rect(5, 10, 1, 17, "Y"); c.rect(18, 10, 3, 17, "D")
    for x, y in ((8, 22), (11, 18), (14, 24), (9, 14), (15, 15), (12, 21)):
        c.px(x, y, "Y")
    c.rect(4, 27, 18, 3, "S"); c.rect(5, 27, 16, 1, "I")
    c.rect(4, 9, 1, 21, "W")
    # handle
    c.rect(22, 12, 4, 2, "I"); c.rect(22, 23, 4, 2, "I"); c.rect(25, 13, 3, 11, "I")
    c.rect(26, 14, 1, 9, "S")
    # foam
    for cx, cy, r in ((7, 6, 3), (12, 4.5, 3.5), (17.5, 5.5, 3), (21, 8, 2), (5, 9, 2)):
        c.circle(cx, cy, r, "W")
    c.rect(3, 9, 20, 2, "W")
    c.rect(3, 11, 2, 3, "W"); c.rect(20, 11, 2, 2, "W")
    for x, y in ((8, 9), (9, 9), (14, 9), (15, 9), (16, 8), (10, 8), (19, 10)):
        c.px(x, y, "C")
    return recenter(c.outline())


# --- 12. whistle ----------------------------------------------------------------------------
def blha_whistle():
    c = Canvas()
    loop = [(25, 11), (28, 8), (28, 4), (26, 1), (23, 1), (20, 3), (20, 6), (22, 9)]
    for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]):      # lanyard: a cord loop off the ring
        c.line(x0, y0, x1, y1, "R", 2)
    for (x0, y0), (x1, y1) in zip(loop[3:6], loop[4:7]):
        c.line(x0, y0, x1, y1, "r")
    c.circle(21, 21, 8.5, "S")                   # chamber
    c.rect(1, 13, 19, 8, "S")                    # mouthpiece
    c.rect(1, 12, 2, 10, "S")
    c.rect(3, 14, 15, 1, "W")
    c.rect(3, 20, 11, 1, "N")
    c.stamp(grid("""
...WWW.......
..WW.........
.WW..........
.W...........
.W..........N
............N
...........NN
..........NN.
........NNN..
...NNNNNNN...
"""), 14, 15)
    c.rect(13, 13, 6, 2, "K")                    # the window on top
    c.rect(1, 15, 1, 4, "N")
    c.circle(26, 12, 1.5, "N"); c.px(26, 12, None); c.px(27, 12, None)   # ring
    return recenter(c.outline())


# --- 13. sin bin ----------------------------------------------------------------------------
def blha_sinbin():
    c = Canvas()
    c.rect(2, 9, 28, 9, "I")                      # glass
    c.stamp(grid("""
..KKKKK...
.KMMMMMK..
.KMMMMLLK.
.KMMMMLLK.
..KKKKKK..
KGGGGGGGGK
GGGGGGGGGG
"""), 4, 11)                                      # a gold skater sitting it out behind the glass
    for x0 in (13, 22):
        c.line(x0, 16, x0 + 5, 11, "W")
    c.rect(2, 9, 1, 9, "S"); c.rect(29, 9, 1, 9, "S")
    c.rect(1, 18, 30, 2, "N"); c.rect(1, 18, 30, 1, "S")      # rail cap
    c.rect(2, 20, 28, 9, "W")                     # boards
    c.rect(2, 26, 28, 4, "G"); c.rect(2, 29, 28, 1, "D")       # kick plate
    c.frame(18, 20, 9, 10, "K")                   # door seam
    c.rect(19, 22, 2, 2, "N")
    c.rect(9, 0, 14, 11, "A"); c.rect(9, 0, 14, 1, "N"); c.rect(9, 0, 1, 11, "N")
    c.stamp(grid("""
.WWWWW.
WWWWWWW
WW...WW
....WWW
..WWWW.
.WWW...
WWWWWWW
WWWWWWW
"""), 12, 2)
    return recenter(c.outline())


# --- 14. tape -------------------------------------------------------------------------------
def blha_tape():
    c = Canvas()
    c.stamp(grid("""
..........NN
.........NAA
........NAA.
.......NAA..
NNNNNNNAAA..
AAAAAAAAA...
AAAAAAAA....
"""), 18, 18)                                    # loose tail peeling off the bottom and curling up
    c.circle(15.5, 12.5, 11, "A")                # depth of the roll
    c.circle(12.5, 12.5, 11, "M")
    c.circle(12.5, 12.5, 8, "N", fill=False)
    c.circle(12.5, 12.5, 5, "O")
    c.circle(12.5, 12.5, 4, "o", fill=False)
    c.circle(12.5, 12.5, 3, None)
    for x, y in ((5, 5), (6, 4), (7, 3), (8, 3), (4, 6), (4, 7)):
        c.px(x, y, "S")
    return recenter(c.outline())


# --- 15. water bottle -----------------------------------------------------------------------
def blha_bottle():
    c = Canvas()
    rrect(c, 8, 11, 16, 20, 3, "L")
    c.rect(9, 17, 14, 12, "b")
    rrect(c, 8, 17, 16, 14, 3, "b")
    c.rect(8, 11, 16, 6, "L")
    for y in (20, 23, 26):
        c.rect(9, y, 14, 1, "B")
    c.rect(10, 12, 1, 16, "W")
    c.rect(9, 7, 14, 4, "A")
    for x in range(10, 22, 2):
        c.rect(x, 7, 1, 4, "M")
    c.rect(10, 6, 12, 1, "A")
    c.line(15, 5, 21, 0, "W", 2)
    c.line(14, 5, 20, 0, "S")
    return recenter(c.outline())


# --- 16. player glove -----------------------------------------------------------------------
def blha_mitt():
    c = Canvas()
    c.stamp(grid("""
.............YY.............
........YY..YGGG.YY.........
.......YGGG.YGGG.YGGG.......
.......YGGG.YGGG.YGGG.YG....
.......DDDD.DDDD.DDDD.YGG...
.......YGGG.YGGG.YGGG.DDD...
.......YGGG.YGGG.YGGG.YGG...
.......YGGG.YGGG.YGGG.YGG...
..YG...DDDD.DDDD.DDDD.DDD...
.YGGG..YGGG.YGGG.YGGG.YGG...
.YGGGG.YGGG.YGGG.YGGG.YGG...
..DYGGG.AAAAAAAAAAAAAAAAA...
...DYGGGNNNNNNNNNNNNNNNNA...
....DYGGAAAAAAAAAAAAAAAAA...
.....DGGGGGGGGGGGGGGGGGGG...
......GGGGGGGGGGGGGGGGGGG...
......GGGGGGGGGGGGGGGGGGG...
......GGGGGGGGGGGGGGGGGDD...
.......DDDDDDDDDDDDDDDDD....
......AAAAAAAAAAAAAAAAAAA...
......MAAAAAAAAAAAAAAAAAA...
.....MAAAAAAAAAAAAAAAAAAAA..
.....GGGGGGGGGGGGGGGGGGGGG..
.....MAAAAAAAAAAAAAAAAAAAA..
....MAAAAAAAAAAAAAAAAAAAAAA.
....NNNNNNNNNNNNNNNNNNNNNNN.
"""), 2, 3)
    return recenter(c.outline())

# --- 17. trapper ----------------------------------------------------------------------------
def blha_trapper():
    c = Canvas()
    capsule(c, 20, 19, 24.5, 5.5, 5.2, "W")                             # finger lobe
    capsule(c, 5.5, 18, 4.5, 11, 3.6, "W")                              # thumb lobe (shorter)
    c.ellipse(13, 20, 9, 3, "W")                                        # palm
    web = Canvas()
    web.poly([(4, 10), (19, 2), (20, 17), (6, 17)], "G")                # web: diagonal from thumb tip to finger tip
    for y in range(32):
        for x in range(32):
            if web.get(x, y)[3] and not c.get(x, y)[3]:
                c.px(x, y, "K" if ((x + y) % 3 == 0 or (x - y) % 3 == 0) else "G")
    c.line(6, 9, 18, 3, "W")                                            # T-trap: top binding + center strap
    c.line(12, 7, 12, 16, "W")
    for y in range(21):                                                 # gold rim round the finger lobe
        for x in range(19, 32):
            p = c.get(x, y)
            if p[3] and p[:3] == (252, 252, 252) and (not c.get(x + 1, y)[3] or not c.get(x, y - 1)[3]):
                c.px(x, y, "G")
    for y in range(6, 21):                                              # gold rim round the thumb
        for x in range(0, 8):
            p = c.get(x, y)
            if p[3] and p[:3] == (252, 252, 252) and (not c.get(x - 1, y)[3] or not c.get(x, y - 1)[3]):
                c.px(x, y, "G")
    c.line(21, 18, 24, 7, "S"); c.line(24, 19, 27, 9, "S")              # finger stitching
    c.ellipse(12.5, 18, 4, 2, "C")                                      # pocket
    c.poly([(5, 22), (22, 22), (23, 30), (4, 30)], "G")                # cuff
    c.rect(4, 25, 20, 1, "W"); c.rect(4, 28, 20, 2, "D")
    return recenter(c.outline())


# --- 18. faceoff dot ------------------------------------------------------------------------
def blha_faceoff():
    c = Canvas()
    rrect(c, 1, 1, 30, 30, 5, "I")
    c.circle(15.5, 15.5, 11, "R"); c.circle(15.5, 15.5, 9, "I")       # faceoff circle
    for x in (11, 19):                                                 # hash marks
        c.rect(x, 1, 2, 3, "R"); c.rect(x, 28, 2, 3, "R")
    for kx, ky, sx, sy in ((10, 11, -1, -1), (21, 11, 1, -1), (10, 20, -1, 1), (21, 20, 1, 1)):
        c.rect(min(kx, kx + 2 * sx), ky, 3, 1, "R")                    # the four L marks
        c.rect(kx, min(ky, ky + 2 * sy), 1, 3, "R")
    c.circle(15.5, 15.5, 3, "R")                                       # the dot
    c.px(13, 13, "r"); c.px(14, 13, "r"); c.px(13, 14, "r")
    for x, y in ((5, 8), (6, 8), (25, 23), (26, 23), (24, 6), (7, 24), (8, 24)):   # skate scratches
        c.px(x, y, "L")
    return recenter(c.outline())

# --- 19. ice cube ---------------------------------------------------------------------------
def blha_ice():
    c = Canvas()
    c.poly([(3, 8), (16, 14), (16, 29), (3, 23)], "L")
    c.poly([(16, 14), (29, 8), (29, 23), (16, 29)], "b")
    c.poly([(16, 2), (29, 8), (16, 14), (3, 8)], "I")
    c.line(16, 15, 16, 28, "W")
    c.line(5, 9, 15, 14, "W")
    for x, y in ((14, 4), (15, 4), (16, 3), (12, 5), (20, 5), (22, 6), (6, 12), (7, 11), (5, 14),
                 (20, 16), (22, 15), (25, 13), (26, 12)):
        c.px(x, y, "W")
    c.stamp(grid("""
..W..
..W..
WWWWW
..W..
..W..
"""), 26, 0)
    return recenter(c.outline())


# --- 20. salt shaker ------------------------------------------------------------------------
def _shaker(u, v):
    """Material of the salt shaker at local point (u across, v up from the foot), or None."""
    if 0 <= v < 17 and abs(u) <= 7.5:                           # glass body
        if v < 1.5:
            return "N" if v < .8 else "S"
        if u < -5.8:
            return "W"
        if u > 5.8:
            return "S"
        if v < 11.5:                                            # salt inside
            return "C" if ((int(u * 3) * 7 + int(v) * 5) % 23 == 0) else "W"
        return "S" if abs(u - 1) < .5 or abs(u + 3) < .5 else "I"
    if 17 <= v < 20 and abs(u) <= 8.5:                          # threaded collar
        return "S" if 18 <= v < 19 else "N"
    if v >= 20 and (u / 8.5) ** 2 + ((v - 20) / 7) ** 2 <= 1:   # chrome dome with holes
        for hu, hv in ((-4, 22), (0, 23), (4, 22), (-2, 25.5), (2, 25.5)):
            if abs(u - hu) < .75 and abs(v - hv) < .75:
                return "K"
        if u < -3 and v > 22:
            return "W"
        if u > 5:
            return "N"
        return "S"
    return None


def blha_salty():
    import math
    big = Canvas(64, 64)
    th = math.radians(28)                                       # tipped over to shake out salt
    ox, oy, sc = 24.0, 50.0, .86                                # foot center on the scratch canvas, scale
    for y in range(64):
        for x in range(64):
            dx, dy = x + .5 - ox, oy - (y + .5)
            k = _shaker((dx * math.cos(th) - dy * math.sin(th)) / sc, (dx * math.sin(th) + dy * math.cos(th)) / sc)
            if k:
                big.px(x, y, k)
    tx, ty = ox + 27 * sc * math.sin(th), oy - 27 * sc * math.cos(th)   # top of the dome
    for gx, gy in ((2, -3), (6, -6), (6, -1), (10, -3), (10, 2)):
        big.px(int(tx + gx), int(ty + gy), "W")                 # salt flying out of the cap
    l, t, r, b = big.img.getbbox()
    assert r - l <= 30 and b - t <= 30, (r - l, b - t)
    c = Canvas()
    c.img.alpha_composite(big.img.crop((l, t, r, b)), (1, 1))
    return recenter(c.outline())


# --- 21. crown ------------------------------------------------------------------------------
def blha_crown():
    c = Canvas()
    c.poly([(3, 21), (2.5, 8), (6.5, 15), (9.5, 6), (12.5, 14), (16, 3), (19.5, 14), (22.5, 6), (25.5, 15),
            (29.5, 8), (29, 21)], "G")
    c.rect(3, 19, 26, 8, "G")
    c.rect(3, 19, 26, 1, "Y"); c.rect(3, 25, 26, 2, "D")
    for cx, cy in ((2, 7), (9, 5), (15.5, 2), (22, 5), (29, 7)):
        c.circle(cx, cy, 1, "Y")
    c.stamp(grid("""
.RR.
RrRR
RRRR
.RR.
"""), 14, 20)
    for x in (7, 22):
        c.stamp(grid("""
.B.
BLB
.B.
"""), x, 21)
    return recenter(c.outline())


# --- 22. trash can --------------------------------------------------------------------------
def blha_trash():
    c = Canvas()
    c.poly([(6, 15), (26, 15), (24, 31), (8, 31)], "S")              # can
    for x in (11, 15, 19, 23):
        c.line(x, 17, x, 29, "N")                                    # ribs
    c.rect(8, 17, 1, 12, "W")
    c.ellipse(15.5, 14, 10, 2, "S")                                  # rim seen a little from above
    c.ellipse(15.5, 14, 8, 1, "A")                                   # dark opening
    c.rect(5, 16, 22, 1, "N")
    c.stamp(grid("""
...WWWS...
.WWSWWWSC.
WWWWSWWWSC
WSWWWSSWWC
.WWSWWWWC.
..CWWSCC..
"""), 13, 8)                                                         # crumpled paper ball
    c.poly([(1, 9), (13, 3), (15, 6), (3, 12)], "N")                 # lid knocked open
    c.line(2, 9, 13, 4, "S")
    c.stamp(grid("""
.SS.
S..S
"""), 5, 4)                                                          # lid handle
    return recenter(c.outline())


EMOJI = [blha_b, blha_puck, blha_stick, blha_mask, blha_skate, blha_helmet, blha_jersey, blha_rink,
         blha_cup, blha_banner, blha_beer, blha_whistle, blha_sinbin, blha_tape, blha_bottle,
         blha_mitt, blha_trapper, blha_faceoff, blha_ice, blha_salty, blha_crown, blha_trash]


def main(names=None):
    out = []
    for fn in EMOJI:
        p = HERE / "static" / f"{fn.__name__}.png"
        if not names or fn.__name__ in names:
            save_png(fn(), p)
        out.append(p)
    sheet([p for p in out if p.exists()], HERE / "static_a_sheet.png")


if __name__ == "__main__":
    main(sys.argv[1:])
