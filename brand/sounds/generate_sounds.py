#!/usr/bin/env python3
"""Generate the BLHA Discord soundboard sounds as original 8-bit chiptune.

Every sound is synthesised from scratch with the same NES-style voices the league's
arcade brand uses: pulse waves with duty-cycle control, a 4-bit stepped triangle, a
15-bit LFSR noise channel (long and short "metallic" modes) and an 8-bit output
crush. No samples, recordings or downloaded audio are used, so the output is
original BLHA material.

Usage:  python3 generate_sounds.py [out_dir] [--preview PATH.mp3]
Needs:  numpy, and ffmpeg built with libmp3lame (for MP3 output and loudness).
Output is deterministic: fixed seeds and fixed LFSR start states give the same
files each run.  Each file is loudness-normalised with ffmpeg's two-pass loudnorm
to about -14 LUFS integrated with a true peak of -1 dBTP or lower.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np

SR = 44100            # delivered sample rate
MP3_BITRATE = "192k"
TARGET_LUFS = -14.0
TARGET_TP = -1.5      # loudnorm ceiling; MP3 coding can overshoot a little, so stay under -1 dBTP
TAU = 2 * np.pi


# ------------------------------------------------------------------ helpers
def tvec(dur):
    return np.arange(int(round(dur * SR))) / SR


def seconds(n):
    return n / SR


def env_points(t, points):
    """Piecewise-linear envelope through (time, level) points."""
    xs, ys = zip(*points)
    return np.interp(t, xs, ys)


def adsr(n, a=0.002, d=0.03, s=0.7, r=0.03):
    e = np.ones(n)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    if na > 0:
        e[:na] = np.linspace(0, 1, na)
    if nd > 0:
        seg = e[na:na + nd]
        e[na:na + nd] = 1 - (1 - s) * np.linspace(0, 1, len(seg))
    e[na + nd:] = s
    if 0 < nr < n:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def place(buf, t0, sig, vol=1.0):
    """Add sig into buf starting at t0 seconds (clipped to the buffer)."""
    i = int(round(t0 * SR))
    if i >= len(buf) or i < 0:
        return
    seg = sig[: len(buf) - i]
    buf[i:i + len(seg)] += seg * vol


def freq(name):
    idx = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    midi = 12 * (int(name[-1]) + 1) + idx[name[:-1]]
    return 440.0 * 2 ** ((midi - 69) / 12)


# ------------------------------------------------------------------- voices
def _phase(f, n):
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    return np.cumsum(f) / SR


def pulse(f, dur, duty=0.5, vol=1.0, a=0.002, d=0.03, s=0.7, r=0.03, vib=0.0, vib_rate=5.5, vib_delay=0.0):
    """NES-style pulse wave. f may be a scalar or a per-sample array (sweeps). duty 0.125/0.25/0.5."""
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    if vib:
        depth = vib * np.clip((t - vib_delay) / 0.2, 0, 1)
        f = f * (1 + depth * np.sin(TAU * vib_rate * t))
    ph = _phase(f, n)
    w = np.where((ph % 1.0) < duty, 1.0, -1.0)
    return w * adsr(n, a, d, s, r) * vol


def tri(f, dur, vol=1.0, a=0.002, d=0.02, s=1.0, r=0.02):
    """4-bit stepped triangle (16 levels), the NES bass/thump voice."""
    n = int(round(dur * SR))
    ph = _phase(f, n)
    w = 4 * np.abs((ph % 1.0) - 0.5) - 1
    w = np.round(w * 7.5) / 7.5
    return w * adsr(n, a, d, s, r) * vol


def _lfsr(short):
    """15-bit linear feedback shift register, one full period of +/-1 output."""
    reg = 1
    period = 93 if short else 32767
    out = np.empty(period)
    for i in range(period):
        fb = (reg ^ (reg >> (6 if short else 1))) & 1
        reg = (reg >> 1) | (fb << 14)
        out[i] = 1.0 if reg & 1 else -1.0
    return out


LFSR_LONG = _lfsr(False)
LFSR_SHORT = _lfsr(True)


def noise(dur, rate=SR, short=False, vol=1.0, tau=None, offset=0, shape=None):
    """LFSR noise. rate = shift-register clock (lower = darker, sample-and-hold grit);
    short = the 93-step metallic mode; tau = exponential decay; shape = custom envelope."""
    n = int(round(dur * SR))
    idx = (np.arange(n) * (rate / SR)).astype(np.int64) + int(offset)
    seq = LFSR_SHORT if short else LFSR_LONG
    x = seq[idx % len(seq)]
    t = np.arange(n) / SR
    if tau is not None:
        x = x * np.exp(-t / tau)
    if shape is not None:
        x = x * shape
    return x * vol


def lowpass(x, fc):
    """One-pole low-pass (exponential kernel, FFT convolution)."""
    tau_s = SR / (TAU * fc)
    k = np.exp(-np.arange(int(tau_s * 8) + 1) / tau_s)
    k /= k.sum()
    n = len(x) + len(k) - 1
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(k, n), n)
    return y[: len(x)]


def crush(x, bits=8):
    """8-bit output quantisation (the console DAC)."""
    q = 2 ** (bits - 1) - 1
    return np.round(x * q) / q


def finalize(x, fade_in=0.003, fade_out=0.02, bits=8, drive=1.0):
    """Optional soft clip (drive > 1 squashes peaks, like an overdriven console output),
    peak-normalise to 0.9, crush to 8 bits, add tiny fades so nothing clicks."""
    x = x / (np.max(np.abs(x)) + 1e-12)
    if drive != 1.0:
        x = np.tanh(drive * x) / np.tanh(drive)
    x = x * 0.9
    x = crush(x, bits)
    n_in, n_out = int(fade_in * SR), int(fade_out * SR)
    if n_in:
        x[:n_in] *= np.linspace(0, 1, n_in)
    if n_out:
        x[-n_out:] *= np.linspace(1, 0, n_out)
    return x.astype(np.float32)


# ------------------------------------------------------------------- sounds
def goal_horn():
    """Big arcade GOAL! fanfare: low square horn chord, rising arpeggios, LFSR crowd."""
    dur = 4.0
    t = tvec(dur)
    n = len(t)
    mix = np.zeros(n)

    # low square-wave horn chord (E2 power chord), scooping up into pitch, vibrato after 0.5 s
    scoop = 2 ** (-0.6 * np.exp(-t / 0.07))
    vib = 1 + 0.004 * np.sin(TAU * 5.5 * t) * np.clip((t - 0.5) / 0.4, 0, 1)
    e_horn = env_points(t, [(0, 0), (0.02, 1.0), (3.3, 0.95), (3.85, 0.0), (dur, 0.0)])
    for f0, g in [(freq("E2"), 1.0), (freq("B2"), 0.7), (freq("E3"), 0.55)]:
        for cents in (-6.0, 6.0):
            f = f0 * 2 ** (cents / 1200) * scoop * vib
            mix += g * 0.5 * pulse(f, dur, 0.5, 1.0, a=0.001, d=0.0, s=1.0, r=0.0) * e_horn
    mix += 0.8 * tri(freq("E1") * scoop, dur, 1.0, a=0.005, r=0.3) * e_horn

    # rising arpeggio into a held high note, twice
    arp = ["E4", "G4", "B4", "E5", "G5", "B5", "E6"]
    for k, nm in enumerate(arp):
        place(mix, 0.04 + 0.06 * k, pulse(freq(nm), 0.06, 0.25, 1.0, a=0.001, s=0.9, r=0.01), 0.55)
    place(mix, 0.46, pulse(freq("E6"), 1.0, 0.125, 1.0, a=0.002, d=0.5, s=0.35, r=0.1, vib=0.01, vib_delay=0.2), 0.55)
    arp2 = ["E5", "G5", "B5", "E6", "G6", "B6"]
    for k, nm in enumerate(arp2):
        place(mix, 1.6 + 0.05 * k, pulse(freq(nm), 0.05, 0.25, 1.0, a=0.001, s=0.9, r=0.01), 0.5)
    place(mix, 1.9, pulse(freq("B6"), 1.7, 0.125, 1.0, a=0.002, d=0.8, s=0.4, r=0.4, vib=0.012, vib_delay=0.3), 0.4)
    place(mix, 1.9, pulse(freq("E6"), 1.7, 0.25, 1.0, a=0.002, d=0.8, s=0.4, r=0.4, vib=0.012, vib_delay=0.3), 0.35)

    # crowd: dark LFSR noise swelling under the horn, with a little flutter, plus two cheer bursts
    swell = env_points(t, [(0, 0), (0.2, 0.15), (1.4, 1.0), (3.0, 0.8), (3.9, 0.0), (dur, 0.0)])
    flutter = 0.8 + 0.2 * np.sin(TAU * 6.3 * t) * np.sin(TAU * 1.7 * t + 1.0)
    crowd = lowpass(noise(dur, rate=SR, offset=1000), 2200) * swell * flutter
    mix += 0.9 * crowd / (np.max(np.abs(crowd)) + 1e-12)
    for t0, v in [(0.0, 0.5), (1.6, 0.45)]:
        place(mix, t0, noise(0.3, rate=SR // 2, tau=0.09, offset=5000), v)
    return finalize(mix, fade_in=0.002, fade_out=0.05, drive=2.2)


def gavel():
    """Three sharp knocks: short metallic LFSR click plus a low square thump that pitches down."""
    dur = 1.2
    mix = np.zeros(len(tvec(dur)))
    for t0, amp, k in [(0.02, 0.85, 0), (0.40, 0.92, 1), (0.78, 1.0, 2)]:
        click = noise(0.08, rate=SR // 2, short=True, tau=0.016, offset=17 * k)
        nt = int(0.25 * SR)
        tt = np.arange(nt) / SR
        f = 75 + 160 * np.exp(-tt / 0.03)
        thump = pulse(f, 0.25, 0.5, 1.0, a=0.001, d=0.0, s=1.0, r=0.0) * np.exp(-tt / 0.09)
        body = tri(330.0 * (1 + 0.02 * k), 0.16, 1.0, a=0.001, r=0.0) * np.exp(-tt[: int(0.16 * SR)] / 0.05)
        place(mix, t0, click, 0.9 * amp)
        place(mix, t0, thump, 0.85 * amp)
        place(mix, t0, body, 0.35 * amp)
    return finalize(lowpass(mix, 12000), fade_in=0.001, fade_out=0.03, drive=3.5)


def draft_horn():
    """Stately rising fanfare in pulse + triangle: D4, G4, A4, then a held D5 chord."""
    dur = 3.0
    mix = np.zeros(len(tvec(dur)))
    notes = [(0.00, 0.40, "D4"), (0.46, 0.40, "G4"), (0.92, 0.40, "A4")]
    for t0, ln, nm in notes:
        place(mix, t0, pulse(freq(nm), ln, 0.25, 1.0, a=0.004, d=0.05, s=0.85, r=0.04), 0.7)
        place(mix, t0, pulse(freq(nm) * 2 ** (3 / 1200), ln, 0.5, 1.0, a=0.004, d=0.05, s=0.85, r=0.04), 0.35)
        place(mix, t0, tri(freq(nm) / 2, ln, 1.0, a=0.004, r=0.04), 0.9)
    # snare-roll crescendo into the final chord
    for k in range(10):
        place(mix, 0.92 + k * 0.04, noise(0.05, rate=SR, tau=0.012, offset=400 * k), 0.12 + 0.03 * k)
    # final chord: D5 lead with vibrato, F#4 + A4 under it, bass drops to D2, noise crash
    t0, ln = 1.38, 1.55
    place(mix, t0, pulse(freq("D5"), ln, 0.5, 1.0, a=0.004, d=0.1, s=0.9, r=0.25, vib=0.008, vib_delay=0.35), 0.75)
    place(mix, t0, pulse(freq("A4"), ln, 0.25, 1.0, a=0.004, d=0.1, s=0.85, r=0.25, vib=0.006, vib_delay=0.35), 0.45)
    place(mix, t0, pulse(freq("F#4"), ln, 0.25, 1.0, a=0.004, d=0.1, s=0.85, r=0.25, vib=0.006, vib_delay=0.35), 0.4)
    place(mix, t0, tri(freq("D2"), ln, 1.0, a=0.004, r=0.3), 1.0)
    place(mix, t0, lowpass(noise(0.8, rate=SR, tau=0.22, offset=9000), 6000), 0.5)
    return finalize(mix, fade_in=0.002, fade_out=0.04)


def on_the_clock():
    """LFSR tick-tock every half second, then a rising two-tone pulse alarm."""
    dur = 3.0
    mix = np.zeros(len(tvec(dur)))
    for k in range(5):
        t0 = 0.02 + 0.5 * k
        amp = 0.6 + 0.1 * k
        if k % 2 == 0:   # tick: bright metallic click
            place(mix, t0, noise(0.04, rate=SR, short=True, tau=0.006, offset=31 * k), 0.9 * amp)
            place(mix, t0, tri(1800.0, 0.012, 1.0, a=0.001, r=0.004), 0.5 * amp)
        else:            # tock: darker click
            place(mix, t0, noise(0.05, rate=SR // 2, short=True, tau=0.008, offset=7 * k), 0.9 * amp)
            place(mix, t0, tri(1250.0, 0.014, 1.0, a=0.001, r=0.004), 0.5 * amp)
    # alarm: two alternating pitches, 40 ms each, rising five semitones over the run
    a0, a1 = 2.3, 2.94
    k = 0
    tt = a0
    while tt < a1 - 0.02:
        rise = 2 ** (5 / 12 * (tt - a0) / (a1 - a0))
        base = freq("A5") if k % 2 == 0 else freq("E6")
        seg = min(0.04, a1 - tt)
        place(mix, tt, pulse(base * rise, seg, 0.5, 1.0, a=0.001, d=0.0, s=1.0, r=0.004), 0.3)
        place(mix, tt, pulse(base * rise / 2, seg, 0.25, 1.0, a=0.001, d=0.0, s=1.0, r=0.004), 0.12)
        tt += 0.04
        k += 1
    return finalize(lowpass(mix, 9000), fade_in=0.002, fade_out=0.03, drive=2.5)


def trade_alert():
    """Quick item-get chime: rising pulse arpeggio into a held note, then a coin ding."""
    dur = 1.5
    mix = np.zeros(len(tvec(dur)))
    place(mix, 0.0, tri(110.0, 0.08, 1.0, a=0.001, r=0.04), 0.8)
    for k, nm in enumerate(["G5", "C6", "E6"]):
        place(mix, 0.07 * k, pulse(freq(nm), 0.07, 0.5, 1.0, a=0.001, s=0.9, r=0.01), 0.75)
    place(mix, 0.21, pulse(freq("G6"), 0.32, 0.5, 1.0, a=0.001, d=0.25, s=0.3, r=0.05), 0.75)
    place(mix, 0.21, pulse(freq("C6"), 0.32, 0.25, 1.0, a=0.001, d=0.25, s=0.3, r=0.05), 0.35)
    # coin: B6 blip into a ringing E7
    place(mix, 0.56, pulse(freq("B6"), 0.07, 0.5, 1.0, a=0.001, s=0.9, r=0.01), 0.7)
    place(mix, 0.63, pulse(freq("E7"), 0.75, 0.5, 1.0, a=0.001, d=0.6, s=0.0, r=0.05), 0.65)
    return finalize(mix, fade_in=0.001, fade_out=0.04)


def final_buzzer():
    """Harsh, long, detuned square buzzer with a 60 Hz rasp; cuts off cleanly at 2.25 s."""
    dur = 2.5
    on, off = 0.0, 2.25
    t = tvec(dur)
    n = len(t)
    x = (pulse(150.0, dur, 0.5, 1.0, a=0.004, d=0.0, s=1.0, r=0.0)
         + pulse(151.4, dur, 0.5, 1.0, a=0.004, d=0.0, s=1.0, r=0.0)
         + 0.6 * pulse(301.0, dur, 0.3, 1.0, a=0.004, d=0.0, s=1.0, r=0.0)
         + 0.7 * tri(75.0, dur, 1.0, a=0.004, r=0.0))
    x *= 1 + 0.3 * np.sign(np.sin(TAU * 60 * t))               # electro-mechanical rasp
    x = np.tanh(2.6 * x / np.max(np.abs(x))) / np.tanh(2.6)     # hard, harsh clip
    gate = env_points(t, [(0, 0), (on + 0.004, 1.0), (off, 1.0), (off + 0.006, 0.0), (dur, 0.0)])
    x *= gate
    return finalize(x, fade_in=0.002, fade_out=0.0)


SOUNDS = [
    ("blha-goal-horn", "BLHA Goal Horn", goal_horn),
    ("blha-gavel", "BLHA Gavel", gavel),
    ("blha-draft-horn", "BLHA Draft Horn", draft_horn),
    ("blha-on-the-clock", "BLHA On The Clock", on_the_clock),
    ("blha-trade-alert", "BLHA Trade Alert", trade_alert),
    ("blha-final-buzzer", "BLHA Final Buzzer", final_buzzer),
]


# ------------------------------------------------------------- encode/check
def write_wav(path, y):
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kw)


def loudnorm_measure(wav):
    err = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav,
                "-af", f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:print_format=json",
                "-f", "null", "-"]).stderr
    return json.loads(err[err.rfind("{"):err.rfind("}") + 1])


def encode_mp3(wav, path, title, measured):
    """Second loudnorm pass (linear gain from the first-pass measurement) straight into MP3."""
    af = (f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11:"
          f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
          f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
          f"offset={measured['target_offset']}:linear=true:print_format=json")
    err = _run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", wav, "-af", af,
                "-ar", str(SR), "-ac", "1",
                "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-id3v2_version", "3",
                "-metadata", f"title={title}",
                "-metadata", "artist=BLHA",
                "-metadata", "comment=Original 8-bit sound synthesized from scratch and owned by the BLHA",
                path]).stderr
    return json.loads(err[err.rfind("{"):err.rfind("}") + 1])


def decode(path):
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                          "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4")


def probe(path):
    out = _run(["ffprobe", "-v", "error", "-show_entries",
                "format=format_name,duration,bit_rate:stream=codec_name,sample_rate,channels",
                "-of", "json", path]).stdout
    return json.loads(out)


def measure(path):
    """Integrated loudness and true peak of a file, from ffmpeg's ebur128 filter."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = err.split("Summary:")[-1]
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return (float(lufs.group(1)) if lufs else float("nan"), float(tp.group(1)) if tp else float("nan"))


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    report = []
    with tempfile.TemporaryDirectory() as tmp:
        for stem, title, fn in SOUNDS:
            y = fn()
            wav = os.path.join(tmp, stem + ".wav")
            write_wav(wav, y)
            path = os.path.join(out_dir, stem + ".mp3")
            measured = loudnorm_measure(wav)
            applied = encode_mp3(wav, path, title, measured)
            dec = decode(path)
            info = probe(path)
            lufs, tp = measure(path)
            report.append({
                "file": os.path.basename(path),
                "source_seconds": round(len(y) / SR, 3),
                "probe_seconds": round(float(info["format"]["duration"]), 3),
                "bytes": os.path.getsize(path),
                "codec": info["streams"][0]["codec_name"],
                "sample_rate": int(info["streams"][0]["sample_rate"]),
                "channels": info["streams"][0]["channels"],
                "integrated_lufs": lufs,
                "true_peak_dbtp": tp,
                "decoded_sample_peak_dbfs": round(float(20 * np.log10(np.max(np.abs(dec)) + 1e-12)), 2),
                "clipped_samples": int(np.sum(np.abs(dec) >= 0.999)),
                "loudnorm_mode": applied.get("normalization_type"),
                "within_discord_limits": os.path.getsize(path) <= 512 * 1024 and float(info["format"]["duration"]) <= 5.2,
            })
    return report


def write_preview(out_dir, preview_path, gap=0.6):
    """All six sounds back to back with a gap, for auditioning."""
    parts = []
    for stem, _, _ in SOUNDS:
        parts.append(decode(os.path.join(out_dir, stem + ".mp3")))
        parts.append(np.zeros(int(gap * SR), np.float32))
    y = np.concatenate(parts[:-1])
    os.makedirs(os.path.dirname(os.path.abspath(preview_path)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "preview.wav")
        write_wav(wav, y)
        _run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", wav, "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
              "-metadata", "title=BLHA Soundboard (8-bit) preview", "-metadata", "artist=BLHA", preview_path])


def main():
    args = sys.argv[1:]
    preview = None
    if "--preview" in args:
        i = args.index("--preview")
        preview = args[i + 1]
        del args[i:i + 2]
    out_dir = args[0] if args else os.path.dirname(os.path.abspath(__file__))
    report = build(out_dir)
    print(json.dumps(report, indent=2))
    if preview:
        write_preview(out_dir, preview)
        print(f"preview written to {preview}", file=sys.stderr)


if __name__ == "__main__":
    main()
