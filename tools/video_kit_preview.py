"""Draw preview frames of the compositions a BLHA Video Kit script builds, from the JSON that
tools/video_kit_jsx_mock.js writes. An approximation of EffectCraft's renderer (flat shapes,
images, the brand fonts), good enough to check layout, timing and overflow by eye.

usage: python3 video_kit_preview.py scene.json sheet.png [--times 0.5,2,4] [--images DIR]
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parents[1] / "brand" / "fonts"
FONT_FILES = {"Jersey10-Regular": FONTS / "jersey10" / "Jersey10-Regular.ttf",
              "Silkscreen-Regular": FONTS / "silkscreen" / "Silkscreen-Regular.ttf",
              "Silkscreen-Bold": FONTS / "silkscreen" / "Silkscreen-Bold.ttf"}
W, H = 1920, 1080
_fonts: dict = {}
_images: dict = {}


def font(name, size):
    key = (name, round(size * 100))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(str(FONT_FILES[name]), max(1, round(size)), layout_engine=ImageFont.Layout.BASIC)
    return _fonts[key]


def at(prop, lt):
    keys = prop["keys"]
    if not keys:
        return prop["value"]
    if lt <= keys[0]["t"]:
        return keys[0]["v"]
    for a, b in zip(keys, keys[1:]):
        if a["t"] <= lt < b["t"]:
            if a["interp"] == "hold" or isinstance(a["v"], dict):
                return a["v"]
            f = (lt - a["t"]) / (b["t"] - a["t"])
            if isinstance(a["v"], (int, float)):
                return a["v"] + (b["v"] - a["v"]) * f
            return [x + (y - x) * f for x, y in zip(a["v"], b["v"])]
    return keys[-1]["v"]


def text_rect(doc):
    """Bounds of a text layer around its baseline origin (matches the mock's measure)."""
    f = font(doc["font"], doc["fontSize"])
    lines = re.split(r"\r\n|\r|\n", doc["text"])
    w = max((f.getlength(ln) for ln in lines), default=0)
    cap = {"Jersey10-Regular": 750 / 1400, "Silkscreen-Regular": .7, "Silkscreen-Bold": .7}[doc["font"]] * doc["fontSize"]
    lead = doc["fontSize"] * 1.2 if doc.get("autoLeading", True) else doc["leading"]
    j = doc["justification"]
    left = -w / 2 if j == 7414 else -w if j == 7415 else 0
    return left, -cap, w, cap + (len(lines) - 1) * lead


class Scene:
    def __init__(self, data):
        self.comps = {c["name"]: c for c in data["comps"]}

    def layer(self, comp, name):
        return next((l for l in comp["layers"] if l["name"] == name), None)

    def doc(self, comp, L, t):
        lt = t - L["startTime"]
        prop = L["text"]
        if prop["expression"]:
            m = re.search(r'thisComp\.layer\("(.+?)"\)', prop["expression"])
            src = self.layer(comp, m.group(1)) if m else None
            d = dict(at(prop, lt))
            if src:
                d["text"] = self.doc(comp, src, t)["text"]
            return d
        return at(prop, lt)

    def xform(self, comp, L, t):
        lt = t - L["startTime"]
        tf = L["transform"]
        pos = at(tf["ADBE Position"], lt)
        if tf["ADBE Position"]["expression"]:
            m = re.search(r'thisComp\.layer\("(.+?)"\)', tf["ADBE Position"]["expression"])
            T = self.layer(comp, m.group(1))
            tl, tt, tw, th = text_rect(self.doc(comp, T, t))
            tp, ts, ta = self.xform(comp, T, t)[:3]
            cx, cy = tl + tw / 2, tt + th / 2
            pos = [tp[0] + (cx - ta[0]) * ts / 100, tp[1] + (cy - ta[1]) * ts / 100]
        return pos, at(tf["ADBE Scale"], lt)[0], at(tf["ADBE Anchor Point"], lt), at(tf["ADBE Opacity"], lt)

    def render(self, comp, t, bg=None):
        img = Image.new("RGBA", (W, H), bg or (0, 0, 0, 0))
        for L in reversed(comp["layers"]):
            if not (L["inPoint"] - 1e-6 <= t < L["outPoint"] - 1e-6) or L["kind"] == "audio":
                continue
            pos, scale, anchor, opacity = self.xform(comp, L, t)
            if opacity <= 0 or scale == 0:
                continue
            piece, origin = self.draw_layer(comp, L, t)
            if piece is None:
                continue
            s = scale / 100
            if s != 1:
                piece = piece.resize((max(1, round(piece.width * abs(s))), max(1, round(piece.height * abs(s)))), Image.NEAREST)
            if opacity < 100:
                piece.putalpha(piece.getchannel("A").point(lambda v: int(v * opacity / 100)))
            x = pos[0] + (origin[0] - anchor[0]) * s
            y = pos[1] + (origin[1] - anchor[1]) * s
            img.alpha_composite(piece, (round(x), round(y))) if -piece.width < x < W and -piece.height < y < H else None
        return img

    def draw_layer(self, comp, L, t):
        """The layer's pixels and where its top-left sits in layer space."""
        lt = t - L["startTime"]
        if L["kind"] == "shape":
            size = at(L["size"], lt)
            if L["size"]["expression"]:
                m = re.search(r'thisComp\.layer\("(.+?)"\)', L["size"]["expression"])
                pads = [int(v) for v in re.findall(r"\+ (\d+)\]?", L["size"]["expression"])]
                tl, tt, tw, th = text_rect(self.doc(comp, self.layer(comp, m.group(1)), t))
                size = [tw + pads[0], th + pads[1]]
            col = at(L["color"], lt)
            w, h = max(1, round(size[0])), max(1, round(size[1]))
            return Image.new("RGBA", (w, h), tuple(round(c * 255) for c in col[:3]) + (255,)), (-w / 2, -h / 2)
        if L["kind"] == "text":
            d = self.doc(comp, L, t)
            if not d["text"]:
                return None, (0, 0)
            f = font(d["font"], d["fontSize"])
            left, top, w, h = text_rect(d)
            pad = 4
            im = Image.new("RGBA", (int(w) + 2 * pad + 2, int(h + d["fontSize"]) + 2 * pad), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            lead = d["fontSize"] * 1.2 if d.get("autoLeading", True) else d["leading"]
            col = tuple(round(c * 255) for c in d["fillColor"][:3])
            for i, ln in enumerate(re.split(r"\r\n|\r|\n", d["text"])):
                lw = f.getlength(ln)
                x = pad + (w - lw) / 2 if d["justification"] == 7414 else pad + (w - lw) if d["justification"] == 7415 else pad
                dr.text((x, pad - top + i * lead), ln, font=f, fill=col, anchor="ls")
            return im, (left - pad, top - pad)
        if L["kind"] == "image":
            p = L["source"]["file"]
            if p not in _images:
                _images[p] = Image.open(p).convert("RGBA")
            return _images[p], (0, 0)
        if L["kind"] == "precomp":
            sub = self.comps[L["source"]["comp"]]
            return self.render(sub, lt), (0, 0)
        return None, (0, 0)


def times_for(comp, n=4):
    d = comp["duration"]
    if d <= 8:
        return [round(d * f, 2) for f in (0.25, 0.55, 0.85)]
    return [round(d * (i + 0.6) / n, 2) for i in range(n)]


def sheet(scene: Scene, explicit=None, cell=(480, 270), only=None):
    frames = []
    for name, comp in scene.comps.items():
        if only and not re.search(only, name):
            continue
        for t in (explicit or times_for(comp)):
            if t < comp["duration"]:
                frames.append((name, t, scene.render(comp, t)))
    cols = 4
    rows = math.ceil(len(frames) / cols) or 1
    out = Image.new("RGB", (cols * cell[0], rows * (cell[1] + 22)), (30, 30, 30))
    dr = ImageDraw.Draw(out)
    checker = Image.new("RGBA", (W, H), (255, 0, 255, 255))
    for i, (name, t, im) in enumerate(frames):
        bg = checker.copy()
        bg.alpha_composite(im)
        x, y = (i % cols) * cell[0], (i // cols) * (cell[1] + 22)
        out.paste(bg.convert("RGB").resize(cell, Image.BILINEAR), (x, y + 22))
        dr.text((x + 4, y + 4), f"{name[:48]} @ {t}s", fill=(230, 230, 230))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("out")
    ap.add_argument("--times")
    ap.add_argument("--only")
    a = ap.parse_args()
    scene = Scene(json.loads(Path(a.scene).read_text()))
    times = [float(x) for x in a.times.split(",")] if a.times else None
    sheet(scene, times, only=a.only).save(a.out)


if __name__ == "__main__":
    main()
