#!/usr/bin/env python3
"""Build the BLHA Video Kit: templates for FilmCraft, EffectCraft and SoundCraft.

    python3 tools/build_video_kit.py [--out DIR] [--zip FILE]

Sources (committed):
  brand/video/effectcraft/      the eleven EffectCraft scripts and lib/blha.jsxinc
  brand/video/scripts_snapshot.json   the BLHA Video Scripts doc, parsed (times, lines, words)
  brand/video/b-roll/BLHA_Hype_Intro.mp4   the league hype intro, cut into the recruiting trailer
  brand/video/READ ME.txt       the kit's instructions
  tools/video_kit_audio.py      music beds, stings and effects (numpy chiptune)
  tools/video_kit_media.py      the sting, outro, wipe, overlays, EffectCraft art and slates
  tools/video_kit_timelines.py  the FilmCraft timelines (.otio)

Output (not committed, rebuilt from the sources): brand/video/build/BLHA Video Kit/ and a zip.
tools/test_video_kit.py checks the result.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import jsx_ascii  # noqa: E402
import video_kit_audio as audio  # noqa: E402
import video_kit_media as media  # noqa: E402
import video_kit_timelines as timelines  # noqa: E402

ROOT = HERE.parent
SRC = ROOT / "brand" / "video"
KIT_NAME = "BLHA Video Kit"
EC_AUDIO = ["sting-intro.wav", "sfx-alert.wav", "sfx-clinch.wav", "sfx-reveal.wav"]
FONTS = [("jersey10", ["Jersey10-Regular.ttf"], "Jersey 10"), ("silkscreen", ["Silkscreen-Regular.ttf", "Silkscreen-Bold.ttf"], "Silkscreen")]


def build(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    report = {}

    # SoundCraft: beds, stings and effects, the soundboard
    report["audio"] = audio.build(out / "SoundCraft", ROOT / "brand" / "sounds")

    # FilmCraft media and the EffectCraft art
    fc, ec = out / "FilmCraft", out / "EffectCraft"
    media.build(fc / "Media", ec / "Images")
    hype = SRC / "b-roll" / "BLHA_Hype_Intro.mp4"
    (fc / "Media" / "B-roll").mkdir(parents=True, exist_ok=True)
    shutil.copy2(hype, fc / "Media" / "B-roll" / hype.name)

    # FilmCraft timelines, then the slates they call for
    report["timelines"] = timelines.build(fc, SRC / "scripts_snapshot.json")
    for path, sl in timelines.SLATES.items():
        media.save_png(fc / path, media.slate(sl.kind, sl.title, sl.lines))
    report["slates"] = len(timelines.SLATES)

    # EffectCraft scripts (ASCII-safe for After Effects too) and their sounds
    (ec / "lib").mkdir(parents=True, exist_ok=True)
    for f in sorted((SRC / "effectcraft").glob("*.jsx")) + [SRC / "effectcraft" / "lib" / "blha.jsxinc"]:
        dest = ec / f.relative_to(SRC / "effectcraft")
        dest.write_text(jsx_ascii.escape(f.read_text(encoding="utf-8")), encoding="utf-8")
    (ec / "Audio").mkdir(exist_ok=True)
    for name in EC_AUDIO:
        shutil.copy2(out / "SoundCraft" / "Stings and Effects" / name, ec / "Audio" / name)
    (ec / "Images" / "Logos").mkdir(parents=True, exist_ok=True)
    (ec / "Images" / "Logos" / "PUT TEAM LOGOS HERE.txt").write_text(
        "Square PNG logos (1000 x 1000 or larger, transparent background) go in this folder.\n"
        "Write each file name in that franchise's logo line in 04 Franchise Cards.jsx.\n")

    # fonts
    fonts = out / "Fonts"
    fonts.mkdir()
    for folder, files, family in FONTS:
        for f in files:
            shutil.copy2(ROOT / "brand" / "fonts" / folder / f, fonts / f)
        shutil.copy2(ROOT / "brand" / "fonts" / folder / "OFL.txt", fonts / f"{family} license (OFL).txt")

    shutil.copy2(SRC / "READ ME.txt", out / "READ ME.txt")
    return report


BEDS_NOTE = ("The four music beds come in the second download, \"BLHA Video Kit - Music Beds.zip\".\n"
             "Unzip it and move the four .wav files into this folder.\n")


def zip_kit(out: Path, zpath: Path) -> Path:
    """Two zips that each fit a 30 MB upload: the kit without its music beds, and the beds."""
    zpath.parent.mkdir(parents=True, exist_ok=True)
    beds = out / "SoundCraft" / "Beds"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(out.rglob("*")):
            arc = Path(KIT_NAME) / p.relative_to(out)
            if p.is_dir():
                z.write(p, str(arc) + "/")
            elif p.parent != beds:
                stored = p.suffix.lower() in (".mp4", ".mov", ".png")
                z.write(p, str(arc), compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        z.writestr(str(Path(KIT_NAME) / "SoundCraft" / "Beds" / "PUT THE MUSIC BEDS HERE.txt"), BEDS_NOTE)
    bpath = zpath.with_name(zpath.stem + " - Music Beds.zip")
    with zipfile.ZipFile(bpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(beds.glob("*.wav")):
            z.write(p, f"BLHA Music Beds/{p.name}")
    return bpath


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=SRC / "build" / KIT_NAME)
    ap.add_argument("--zip", type=Path, default=None)
    a = ap.parse_args()
    report = build(a.out)
    for name, seqs in report["timelines"].items():
        print(f"{name}.otio: {len(seqs)} sequences")
    print(f"slates: {report['slates']}")
    for name, f in report["audio"].items():
        print(f"{name}: {f['seconds']} s, {f['lufs']} LUFS, peak {f['peak_db']} dB")
    if a.zip:
        beds = zip_kit(a.out, a.zip)
        for z in (a.zip, beds):
            print(f"zip: {z} ({z.stat().st_size / 2**20:.1f} MiB)")


if __name__ == "__main__":
    main()
