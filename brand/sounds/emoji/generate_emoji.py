"""Six 8-bit soundboard emoji (16 x 16 art pixels, exported 128 x 128) in the BLHA palette.

Usage: python brand/sounds/emoji/generate_emoji.py [out_dir]   (default: this folder)
"""
import sys
from PIL import Image
P = {"K": (14, 15, 18), "W": (252, 252, 252), "G": (255, 184, 28), "D": (198, 138, 0), "Y": (255, 215, 106),
     "R": (200, 36, 31), "r": (255, 106, 74), "S": (154, 161, 169), "N": (110, 116, 124), "B": (36, 87, 197),
     "L": (127, 183, 240), "C": (244, 239, 228), "M": (58, 61, 66)}
E = {
 "goalhorn": [
  "................",
  "..G....GG....G..",
  "...G...GG...G...",
  "................",
  ".....KKKKKK.....",
  "....KRRRrrRK....",
  "...KRRRRrWrRK...",
  "...KRRRRRrrRK...",
  "...KRRRRRRRRK...",
  "...KRRRRRRRRK...",
  "..KKKKKKKKKKKK..",
  "..KSSSSSSSSSSK..",
  "..KSWSSSSSSSSK..",
  "..KNNNNNNNNNNK..",
  "..KKKKKKKKKKKK..",
  "................"],
 "gavel": [
  "................",
  "..KKKKKKKKKKKK..",
  ".KGKYYYYYYYYKGK.",
  ".KGKGGGGGGGGKGK.",
  ".KDKDDDDDDDDKDK.",
  "..KKKKKKKKKKKK..",
  "......KGDK......",
  "......KGDK......",
  "......KGDK......",
  "......KGDK......",
  "......KKKK......",
  "................",
  "..KKKKKKKKKKKK..",
  ".KCCCCCCCCCCCCK.",
  ".KMMMMMMMMMMMMK.",
  "..KKKKKKKKKKKK.."],
 "drafthorn": [
  "................",
  "...........KK...",
  ".........KKGK...",
  ".......KKGGGK.G.",
  "..KK.KKGGGGGK...",
  ".KYGKGGGGGGGK.GG",
  ".KGGGGGGGGGGK...",
  ".KGGGGGGGGGGK.GG",
  ".KDDKDDDDDDDK...",
  "..KK.KKDDDDDK.G.",
  ".......KKDDDK...",
  ".........KKDK...",
  "...........KK...",
  "................",
  "................",
  "................"],
 "onclock": [
  "................",
  "..KKK......KKK..",
  ".KGGYK....KGGYK.",
  ".KGGK.KKKK.KGGK.",
  "..KK.KCCCCK.KK..",
  "....KCCCKCCK....",
  "...KCCCCKCCCK...",
  "...KCCCCKCCCK...",
  "...KCCCCKKKCK...",
  "...KCCCCCCCCK...",
  "...KCCCCCCCCK...",
  "....KCCCCCCK....",
  ".....KKKKKK.....",
  "....KK....KK....",
  "................",
  "................"],
 "trade": [
  "................",
  ".........K......",
  ".........KK.....",
  "..KKKKKKKKGK....",
  "..KGGGGGGGGGK...",
  "..KGGGGGGGGGGK..",
  "..KKKKKKKKGGK...",
  ".........KGK....",
  "....KLK..KK.....",
  "...KBLKKKKKKKK..",
  "..KBBBBBBBBBBK..",
  "...KBBBBBBBBBK..",
  "....KBBKKKKKKK..",
  ".....KBK........",
  "......K.........",
  "................"],
 "buzzer": [
  "................",
  "................",
  "..KKKKKKKKKKKK..",
  ".KMMMMMMMMMMMMK.",
  ".KMRRRRMMRRRRMK.",
  ".KMRMMRMMRMMRMK.",
  ".KMRMMRMMRMMRMK.",
  ".KMRMMRMMRMMRMK.",
  ".KMRMMRMMRMMRMK.",
  ".KMRRRRMMRRRRMK.",
  ".KMMMMMMMMMMMMK.",
  "..KKKKKKKKKKKK..",
  ".....KSSSSK.....",
  "....KNNNNNNK....",
  "....KKKKKKKK....",
  "................"],
}
out = sys.argv[1] if len(sys.argv) > 1 else str(__import__("pathlib").Path(__file__).resolve().parent)

for i, (name, rows) in enumerate(E.items()):
    assert len(rows) == 16 and all(len(r) == 16 for r in rows), name
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in P:
                im.putpixel((x, y), P[ch] + (255,))
    big = im.resize((128, 128), Image.NEAREST)
    big.save(f"{out}/blha_{name}.png", optimize=True)


