"""Checks the built BLHA Video Kit (tools/build_video_kit.py), building it first if needed.

    python3 tools/test_video_kit.py [--kit DIR]

Not part of CI: it needs ffmpeg/ffprobe and Node.js, and the build takes about a minute.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_video_kit  # noqa: E402
import jsx_ascii  # noqa: E402

KIT = build_video_kit.SRC / "build" / build_video_kit.KIT_NAME
NODE = next((p for p in ("/opt/node22/bin/node", "node") if subprocess.run(["which", p], capture_output=True).returncode == 0), "node")
SCRIPTS = ["01 Brand Kit", "02 Week in 60", "03 Monthly Awards", "04 Franchise Cards", "05 Trade Alert", "06 Clinched",
           "07 Playoff Bracket", "08 Champion Banner", "09 Countdown", "10 Awards Night", "11 Explainer Cards"]
TIMELINES = ["BLHA Hype Trailer", "BLHA Talking Head", "BLHA Screen Tutorial", "BLHA Explainer", "BLHA Week in 60",
             "BLHA Monthly Awards", "BLHA Playoff Show", "BLHA Season in Review", "BLHA Awards Night"]


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def secs(r: dict) -> float:
    return r["value"] / r["rate"]


class Kit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (KIT / "READ ME.txt").exists():
            build_video_kit.build(KIT)
        cls.fc, cls.ec = KIT / "FilmCraft", KIT / "EffectCraft"

    # ---------------------------------------------------------------- FilmCraft
    def test_every_promised_timeline_exists(self):
        for name in TIMELINES:
            self.assertTrue((self.fc / f"{name}.otio").exists(), name)

    def test_timelines_read_the_way_filmcraft_reads_them(self):
        for f in sorted(self.fc.glob("*.otio")):
            doc = json.loads(f.read_text())
            self.assertEqual(doc["OTIO_SCHEMA"], "SerializableCollection.1")
            self.assertTrue(doc["children"], f.name)
            for tl in doc["children"]:
                self.assertEqual(tl["OTIO_SCHEMA"], "Timeline.1")
                stack = tl["tracks"]
                self.assertEqual(stack["OTIO_SCHEMA"], "Stack.1")
                self.assertTrue(stack["markers"], f"{tl['name']} has no script markers")
                kinds = [t["kind"] for t in stack["children"]]
                self.assertEqual(kinds, ["Video"] * 4 + ["Audio"] * 4, tl["name"])
                lengths = []
                for tr in stack["children"]:
                    t = 0.0
                    for c in tr["children"]:
                        self.assertIn(c["OTIO_SCHEMA"], ("Clip.2", "Gap.1"))
                        d = secs(c["source_range"]["duration"])
                        self.assertGreater(d, 0, f"{tl['name']} {tr['name']}")
                        if c["OTIO_SCHEMA"] == "Clip.2":
                            ref = c["media_references"][c["active_media_reference_key"]]
                            self.assertEqual(ref["OTIO_SCHEMA"], "ExternalReference.1")
                            target = (self.fc / ref["target_url"]).resolve()
                            self.assertTrue(target.exists(), f"{tl['name']}: missing {ref['target_url']}")
                            if ref["available_range"]:
                                start = secs(c["source_range"]["start_time"])
                                self.assertLessEqual(start + d, secs(ref["available_range"]["duration"]) + 1e-6,
                                                     f"{tl['name']}: {c['name']} runs past the end of its media")
                        t += d
                    lengths.append(t)
                for m in stack["markers"]:
                    self.assertLessEqual(secs(m["marked_range"]["start_time"]), max(lengths) + 1e-6, f"{tl['name']}: {m['name']}")

    def test_media_movies(self):
        sting = probe(self.fc / "Media" / "Stings" / "blha-intro-sting.mp4")["streams"][0]
        self.assertEqual((sting["codec_name"], sting["width"], sting["height"], sting["r_frame_rate"], sting["nb_frames"]),
                         ("h264", 1920, 1080, "30/1", "90"))
        wipe = probe(self.fc / "Media" / "Transitions" / "blha-pixel-wipe.mov")["streams"][0]
        self.assertEqual(wipe["codec_name"], "prores")
        self.assertIn("yuva", wipe["pix_fmt"])
        self.assertEqual(wipe["nb_frames"], "20")
        broll = probe(self.fc / "Media" / "B-roll" / "BLHA_Hype_Intro.mp4")
        self.assertAlmostEqual(float(broll["format"]["duration"]), 75.2, places=1)

    # ---------------------------------------------------------------- SoundCraft
    def test_audio_files(self):
        for folder, names in (("Beds", ["bed-hype-45s", "bed-week-60s", "bed-tutorial-loop", "bed-awards-loop"]),
                              ("Stings and Effects", ["sting-intro", "sting-outro", "sfx-whoosh", "sfx-alert", "sfx-clinch", "sfx-reveal"]),
                              ("Soundboard", ["blha-draft-horn", "blha-final-buzzer", "blha-gavel", "blha-goal-horn", "blha-on-the-clock", "blha-trade-alert"])):
            for n in names:
                with wave.open(str(KIT / "SoundCraft" / folder / f"{n}.wav")) as w:
                    self.assertEqual((w.getframerate(), w.getsampwidth(), w.getnchannels()), (48000, 2, 2), n)
                    self.assertGreater(w.getnframes(), 0)
        with wave.open(str(KIT / "SoundCraft" / "Beds" / "bed-hype-45s.wav")) as w:
            self.assertEqual(w.getnframes(), 45 * 48000)

    # ---------------------------------------------------------------- EffectCraft
    def test_scripts_are_ascii_in_code(self):
        for f in list(self.ec.glob("*.jsx")) + [self.ec / "lib" / "blha.jsxinc"]:
            s = f.read_text(encoding="utf-8")
            self.assertEqual(jsx_ascii.escape(s), s, f.name)

    def test_scripts_run_against_the_object_model(self):
        metrics = HERE / "video_kit_font_metrics.json"
        with tempfile.TemporaryDirectory() as tmp:
            for name in SCRIPTS:
                out = Path(tmp) / "scene.json"
                r = subprocess.run([NODE, str(HERE / "video_kit_jsx_mock.js"), str(self.ec / f"{name}.jsx"), str(metrics), str(out)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, name + "\n" + r.stdout + r.stderr)
                scene = json.loads(out.read_text())
                self.assertTrue(scene["comps"], name)
                self.assertTrue(all(Path(p).resolve().is_relative_to(self.ec.resolve()) for p in scene["imports"]), name)
                for comp in scene["comps"]:
                    self.assertTrue(comp["folder"].startswith("BLHA Video Kit"), comp["name"])
                    for L in comp["layers"]:
                        self.assertLess(L["inPoint"], L["outPoint"], f"{comp['name']}: {L['name']}")

    # ---------------------------------------------------------------- the package
    def test_read_me_and_fonts(self):
        text = (KIT / "READ ME.txt").read_text(encoding="utf-8")
        for bad in ("Claude", "GitHub", "github", " AI ", "v2."):
            self.assertNotIn(bad, text)
        for f in ("Jersey10-Regular.ttf", "Silkscreen-Regular.ttf", "Silkscreen-Bold.ttf"):
            self.assertTrue((KIT / "Fonts" / f).exists(), f)
        for n in SCRIPTS:
            self.assertIn(n, text)

    def test_nothing_mentions_the_tools_that_made_it(self):
        for f in list(self.ec.glob("*.jsx")) + [self.ec / "lib" / "blha.jsxinc"] + list(self.fc.glob("*.otio")):
            s = f.read_text(encoding="utf-8")
            self.assertNotRegex(s, r"\bClaude\b|\bAnthropic\b|github\.com", f.name)


if __name__ == "__main__":
    if "--kit" in sys.argv:
        i = sys.argv.index("--kit")
        KIT = Path(sys.argv[i + 1])
        del sys.argv[i:i + 2]
    unittest.main(verbosity=2)
