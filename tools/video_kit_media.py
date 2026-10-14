"""Pictures for the BLHA Video Kit: the intro sting, the outro, the pixel wipe, overlays, the
EffectCraft backgrounds and art, and the placeholder slates that sit in the FilmCraft timelines.

All of it is pixel art from tools/blha_pixel.py, drawn on whole-pixel grids and enlarged with
nearest-neighbor so every pixel stays square. Movies are 1920x1080 at 30 fps: H.264 for the full-
screen pieces and ProRes 4444 with alpha for the wipe, which sits on a track above the cut.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from PIL import Image

import blha_pixel as px
from blha_pixel import (BLACK, CHARCOAL, CHAR_DK, CHAR_LT, CREAM, GOLD, GOLD_DK, GOLD_LT, ICE, MUTED, PAPER, RED,
                        BLUE, STANDS, STEEL, STEEL_DK, GREEN, art, rect, dither, grain, put, sprite, enlarge,
                        draw_text, font, lockup, place, B32)

W, H, FPS = 1920, 1080, 30


# ---------------------------------------------------------------- movie writing
def write_movie(path: Path, frames, n: int, alpha: bool = False):
    """Pipe `n` RGBA frames from the generator into ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if alpha:
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0"]
    else:
        codec = ["-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-tune", "animation",
                 "-movflags", "+faststart", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-an", *codec, "-r", str(FPS), str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    count = 0
    for f in frames:
        if f.size != (W, H):
            raise ValueError(f"frame {count} is {f.size}")
        proc.stdin.write(f.convert("RGBA").tobytes())
        count += 1
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed on {path}")
    if count != n:
        raise ValueError(f"{path.name}: wrote {count} frames, expected {n}")


def save_png(path: Path, img: Image.Image):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


BAYER = px.BAYER


def bayer_mask(level: float, cell: int = 8) -> Image.Image:
    """1-bit ordered-dither mask at 1920x1080 in `cell`-pixel squares: level 0 = none, 1 = all."""
    a = Image.new("L", (W // cell, H // cell), 0)
    p = a.load()
    for y in range(a.height):
        for x in range(a.width):
            if BAYER[y & 3][x & 3] < level * 16:
                p[x, y] = 255
    return a.resize((W, H), Image.NEAREST)


# ---------------------------------------------------------------- backgrounds (also used by EffectCraft)
def bg_charcoal() -> Image.Image:
    """The channel-header ground at 1920x1080: textured charcoal, stands dither, gold bar at the bottom."""
    a = art(240, 135, CHARCOAL)
    grain(a, [CHAR_LT, CHAR_DK], .02, 911)
    dither(a, 0, 112, 240, 20, STANDS)
    rect(a, 0, 132, 240, 1, GOLD_LT)
    rect(a, 0, 133, 240, 1, GOLD)
    rect(a, 0, 134, 240, 1, GOLD_DK)
    return enlarge(a, 8, (W, H))


def bg_dots() -> Image.Image:
    """Charcoal with a grid of darker dots (the hype intro's card ground)."""
    a = art(480, 270, CHARCOAL)
    grain(a, [CHAR_LT, CHAR_DK], .015, 77)
    for y in range(2, 270, 6):
        for x in range(2 + (3 if (y // 6) % 2 else 0), 480, 6):
            a.putpixel((x, y), CHAR_DK + (255,))
    return enlarge(a, 4, (W, H))


def bg_arena() -> Image.Image:
    """The arena: gold boards, the crowd fading into charcoal, a dithered fade to black."""
    return enlarge(px.bg_banner(240, 135, bars=1), 8, (W, H))


def bg_black() -> Image.Image:
    return enlarge(px.bg_plain(240, 135, BLACK), 8, (W, H))


# ---------------------------------------------------------------- art pieces for EffectCraft
def b_mark(k: int) -> Image.Image:
    return sprite(B32(), k)


def small_b(k: int) -> Image.Image:
    return sprite("b", k)


def banner_art() -> Image.Image:
    """A blank championship banner (charcoal with a gold frame and a swallowtail), 384 x 592."""
    w, h, tail = 48, 74, 12
    a = art(w, h)
    rect(a, 1, 0, w - 2, 2, STEEL)                   # the rod it hangs from
    rect(a, 0, 0, 1, 2, STEEL_DK)
    rect(a, w - 1, 0, 1, 2, STEEL_DK)
    top, body_h = 2, h - 2
    for y in range(body_h):
        n = y - (body_h - tail)                      # row inside the swallowtail (>= 0)
        cut = n * 1.6 if n >= 0 else -1.0
        for x in range(4, w - 4):
            d = abs(x + .5 - w / 2)
            if d < cut:
                continue
            gold = x < 6 or x >= w - 6 or y < 2 or y >= body_h - 2 or (n >= 0 and d < cut + 2)
            a.putpixel((x, top + y), (GOLD if gold else CHARCOAL) + (255,))
    rnd = random.Random(5)
    for _ in range(40):
        x, y = rnd.randrange(7, w - 7), rnd.randrange(4, body_h - tail - 2)
        a.putpixel((x, top + y), CHAR_LT + (255,))
    return a.resize((w * 8, h * 8), Image.NEAREST)


CUP = ["..GGGGGGGGGGGG..", ".GGLLLLLLLLLLGG.", "GG.GLLLLLLLLG.GG", "G..GLLLLLLLLG..G", "G..GLLLLLLLLG..G",
       "GG.GDLLLLLLDG.GG", ".GGGGDLLLLDGGGG.", "....GGDLLDGG....", "......GDDG......", "......GDDG......",
       ".....GGDDGG.....", "....DDDDDDDD....", "...KKKKKKKKKK...", "...KCCCCCCCCK...", "...KKKKKKKKKK..."]


def trophy(k: int) -> Image.Image:
    pal = {"G": GOLD, "L": GOLD_LT, "D": GOLD_DK, "K": BLACK, "C": CREAM}
    a = art(len(CUP[0]), len(CUP))
    for y, row in enumerate(CUP):
        for x, ch in enumerate(row):
            if ch in pal:
                a.putpixel((x, y), pal[ch] + (255,))
    return a.resize((a.width * k, a.height * k), Image.NEAREST)


def stamp_frame(color) -> Image.Image:
    """The league's status-stamp frame with no word in it (916 x 368)."""
    a = art(px.STAMP_W, px.STAMP_H)
    px.frame(a, 2, 2, 111, 42, 2, 3, color, wear=.04, seed=3)
    px.frame(a, 5, 5, 105, 36, 1, 2, color)
    return enlarge(a, 8, (916, 368))


def corner_bug() -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    b = small_b(6)
    alpha = b.getchannel("A").point(lambda v: int(v * .85))
    b.putalpha(alpha)
    img.alpha_composite(b, (W - 96 - b.width, H - 60 - b.height))
    return img


# ---------------------------------------------------------------- the intro sting (3.0 s)
def intro_sting_frames():
    bg = bg_black()
    sizes = {15: 24, 16: 18, 17: 14}
    shake = {15: (12, -8), 16: (-10, 6), 17: (8, -6), 18: (-6, 4), 19: (4, -2), 20: (-2, 2)}
    flash = {15: .55, 16: .35, 17: .18}
    tag = "BEER LEAGUE HOCKEY ASSOCIATION"
    rnd = random.Random(26)
    sparks = [(rnd.randrange(560, 1360) // 8 * 8, rnd.randrange(170, 640) // 8 * 8, rnd.randrange(66, 84)) for _ in range(26)]
    for f in range(90):
        img = bg.copy()
        if f < 15:                                   # the CRT line opens out from the center
            w = min(W, int(W * ((f + 1) / 13) ** 1.5)) // 8 * 8
            col = CREAM if f >= 12 else GOLD
            rect(img, (W - w) // 2, H // 2 - 4, w, 8, col)
        else:
            k = sizes.get(f, 12)
            b = b_mark(k)
            dx, dy = shake.get(f, (0, 0))
            place(img, b, 960 + dx, 420 + dy, snap=2)
            if f >= 30:                              # the tagline types on, one letter a frame
                n = min(len(tag), f - 29)
                full_w = font("silk-bold").width(tag, 6)
                draw_text(img, tag[:n], "silk-bold", 6, (W - full_w) // 2 // 2 * 2, 680, CREAM)
            if f >= 66:
                g = min(1.0, (f - 65) / 4)
                rw = int(900 * g) // 12 * 12
                rect(img, 960 - rw // 2, 738, rw, 6, GOLD)
                if f >= 68:
                    draw_text(img, "EST. 2026", "silk", 4, 960, 768, GOLD, align="c")
                for x, y, t0 in sparks:              # gold sparkles blink around the B
                    if f >= t0 and (f + x) % 6 < 3 and f < 84:
                        rect(img, x, y, 8, 8, GOLD_LT)
            if f in flash:
                over = Image.new("RGBA", (W, H), GOLD + (int(255 * flash[f]),))
                img.alpha_composite(over)
        if f >= 78:                                  # ordered-dither dissolve to black
            level = min(1.0, (f - 77) / 11)
            img.paste(Image.new("RGBA", (W, H), BLACK + (255,)), (0, 0), bayer_mask(level))
        yield img


# ---------------------------------------------------------------- the outro (5.0 s)
def rink_scene(rx: int, bob: int) -> Image.Image:
    """The title-screen rink (240 x 135 art) with the resurfacer at art x = rx; fresh ice behind it."""
    w, h, bars = 240, 135, 2
    a = px.bg_plain(w, h, BLACK)
    dither(a, 0, bars, w, 44, CHARCOAL, down=False)
    ice_h = px.SPLASH_ICE
    top = h - bars - ice_h - 6
    iy = top + 6
    rect(a, 0, top, w, 1, STEEL_DK)
    rect(a, 0, top + 1, w, 1, STEEL)
    rect(a, 0, top + 2, w, 3, PAPER)
    rect(a, 0, top + 5, w, 1, GOLD)
    rect(a, 0, iy, w, ice_h, ICE)
    if rx > -50:                                     # fresh ice behind the machine, under the lines
        rect(a, 0, iy + 3, max(0, min(w, rx + 6)), ice_h - 3, (248, 251, 253))
    rect(a, w // 2 - 1, iy, 2, ice_h, RED)
    rect(a, round(w * .3) - 1, iy, 2, ice_h, BLUE)
    rect(a, round(w * .7) - 1, iy, 2, ice_h, BLUE)
    put(a, "resurfacer", rx, iy + ice_h - 29 - bob)
    rect(a, 0, 0, w, bars, GOLD)
    rect(a, 0, h - bars, w, bars, GOLD)
    return enlarge(a, 8, (W, H))


def outro_frames():
    lk = lockup(30, 5)
    rink_top = (135 - 2 - px.SPLASH_ICE - 6) * 8
    for f in range(150):
        rx = int(-60 + (f / 149) * 320)
        img = rink_scene(rx, 1 if (f // 4) % 2 else 0)
        drop = max(0, 8 - f) * 24                    # the lockup drops in over 8 frames
        place(img, lk, W // 2, (16 + rink_top) // 2 - 40 - drop, snap=5)
        if f >= 24:
            draw_text(img, "SEE YOU AT THE RINK", "silk", 5, 960, rink_top - 120, CREAM, align="c")
        if f >= 138:
            level = (f - 137) / 12
            img.paste(Image.new("RGBA", (W, H), BLACK + (255,)), (0, 0), bayer_mask(level))
        yield img


# ---------------------------------------------------------------- the pixel wipe (20 frames, alpha)
def wipe_frames():
    cols, rows, cell = 16, 9, 120
    order = {}
    for y in range(rows):
        for x in range(cols):
            order[(x, y)] = (x + (rows - 1 - y) * .5) / (cols - 1 + (rows - 1) * .5)   # a diagonal sweep
    for f in range(20):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for (x, y), o in order.items():
            if f <= 9:                               # cover: blocks fill in, left to right (all by frame 9)
                p = (f + 1) / 10
                on = o <= p
                edge = on and o > p - .12
            else:                                    # uncover from frame 11 (frames 9 and 10 are fully covered)
                p = (f - 10) / 9 * 1.0001
                on = o >= p
                edge = on and o < p + .12
            if on:
                rect(img, x * cell, y * cell, cell, cell, GOLD if edge and f not in (9, 10) else CHARCOAL)
                if not edge:
                    rect(img, x * cell + 52, y * cell + 52, 16, 16, CHAR_DK)
        yield img


# ---------------------------------------------------------------- placeholder slates
KIND = {
    "camera": ("CAMERA", BLUE), "screen": ("SCREEN RECORDING", GREEN), "render": ("EFFECTCRAFT RENDER", GOLD),
    "broll": ("B-ROLL", STEEL), "card": ("FILMCRAFT TITLE", CREAM), "vo": ("VOICE", RED),
}


def wrap(text: str, face: str, scale: int, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font(face).width(t, scale) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def slate(kind: str, title: str, lines: list[str]) -> Image.Image:
    """A placeholder: what goes in this slot, in big type, with the steps under it."""
    label, color = KIND[kind]
    img = bg_dots()
    for x in range(48, W - 48, 48):                  # dashed frame in the kind's color
        rect(img, x, 48, 24, 6, color)
        rect(img, x, H - 54, 24, 6, color)
    for y in range(48, H - 48, 48):
        rect(img, 48, y, 6, 24, color)
        rect(img, W - 54, y, 6, 24, color)
    draw_text(img, f"PLACEHOLDER • {label}", "silk", 4, 120, 120, color)
    scale = 8
    tl = wrap(title.upper(), "jersey", scale, W - 240)
    while len(tl) > 3 and scale > 4:
        scale -= 2
        tl = wrap(title.upper(), "jersey", scale, W - 240)
    y = 190
    for t in tl:
        draw_text(img, t, "jersey", scale, 120, y, CREAM, shadow=BLACK)
        y += scale * 13
    y += 30
    for line in lines:
        for t in wrap(line, "silk", 4, W - 240):
            draw_text(img, t, "silk", 4, 120, y, MUTED)
            y += 40
        y += 12
    b = small_b(4)
    img.alpha_composite(b, (W - 120 - b.width, H - 110 - b.height))
    return img


# ---------------------------------------------------------------- build
def build(media: Path, ec_images: Path) -> dict[str, str]:
    """Write the movies and overlays (FilmCraft/Media) and the EffectCraft art; returns name -> path."""
    out = {}
    write_movie(media / "Stings" / "blha-intro-sting.mp4", intro_sting_frames(), 90)
    write_movie(media / "Stings" / "blha-outro.mp4", outro_frames(), 150)
    write_movie(media / "Transitions" / "blha-pixel-wipe.mov", wipe_frames(), 20, alpha=True)
    save_png(media / "Overlays" / "blha-corner-bug.png", corner_bug())
    images = {
        "bg-charcoal.png": bg_charcoal(), "bg-dots.png": bg_dots(), "bg-arena.png": bg_arena(), "bg-black.png": bg_black(),
        "b-mark-12.png": b_mark(12), "b-mark-8.png": b_mark(8), "b-mark-4.png": b_mark(4), "b-small-6.png": small_b(6),
        "wordmark.png": lockup(30, 5), "wordmark-small.png": lockup(18, 3), "banner.png": banner_art(),
        "trophy.png": trophy(8), "stamp-green.png": stamp_frame(GREEN), "stamp-red.png": stamp_frame(RED),
        "stamp-gold.png": stamp_frame(GOLD),
    }
    for name, img in images.items():
        save_png(ec_images / name, img)
        out[name] = str(ec_images / name)
    save_png(media / "Backgrounds" / "blha-bg-charcoal.png", images["bg-charcoal.png"])
    save_png(media / "Backgrounds" / "blha-bg-arena.png", images["bg-arena.png"])
    return out
