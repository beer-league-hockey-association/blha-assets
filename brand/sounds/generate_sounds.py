#!/usr/bin/env python3
"""Generate the BLHA Discord soundboard sounds from scratch.

Every sound here is pure synthesis (oscillators, filtered noise, damped
resonators and a synthetic reverb). No samples, recordings or downloaded
audio are used, so the output is original BLHA material.

Usage:  python3 generate_sounds.py [out_dir]
Needs:  numpy, scipy, and ffmpeg built with libmp3lame (for MP3 output).
Output is deterministic: fixed random seeds give the same files each run.
"""
import json
import os
import subprocess
import sys

import numpy as np
import scipy.signal as ss

SR = 48000            # delivered sample rate
OS = 2                # oversampling while synthesising (limits aliasing)
FS = SR * OS          # internal synthesis rate
PEAK_DBFS = -1.0
MP3_BITRATE = "192k"
TAU = 2 * np.pi


# ---------------------------------------------------------------- helpers
def tvec(dur, fs=FS):
    return np.arange(int(round(dur * fs))) / fs


def env(t, points, curve=1.0):
    """Piecewise-linear envelope through (time, level) points."""
    xs, ys = zip(*points)
    e = np.interp(t, xs, ys)
    return e ** curve if curve != 1.0 else e


def smooth_noise(n, rate, rng, fs=FS):
    """Unit-variance random wobble with energy below `rate` Hz."""
    k = int(n / fs * rate) + 4
    pts = rng.standard_normal(k)
    x = np.interp(np.linspace(0, k - 3, n), np.arange(k), pts)
    y = ss.sosfiltfilt(ss.butter(2, rate, fs=fs, output="sos"), x)
    return y / (np.std(y) + 1e-12)


def _polyblep(p, dt):
    c = np.zeros_like(p)
    m = p < dt
    x = p[m] / dt[m]
    c[m] = x + x - x * x - 1.0
    m = p > 1.0 - dt
    x = (p[m] - 1.0) / dt[m]
    c[m] = x * x + x + x + 1.0
    return c


def _phase(f, n, phase0):
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    return phase0 + np.cumsum(f) / FS, f / FS


def saw(f, n, phase0=0.0):
    """Band-limited (polyBLEP) sawtooth, range about -1..1."""
    ph, dt = _phase(f, n, phase0)
    p = ph % 1.0
    return 2 * p - 1 - _polyblep(p, dt)


def pulse(f, n, phase0=0.0, duty=0.5):
    """Band-limited pulse built from two sawtooths; duty 0.5 is a square."""
    ph, dt = _phase(f, n, phase0)
    p1 = ph % 1.0
    p2 = (ph + duty) % 1.0
    s1 = 2 * p1 - 1 - _polyblep(p1, dt)
    s2 = 2 * p2 - 1 - _polyblep(p2, dt)
    return s1 - s2


def sine(f, n, phase0=0.0):
    ph, _ = _phase(f, n, phase0)
    return np.sin(TAU * ph)


def _sos(kind, fc, order, fs):
    return ss.butter(order, fc, kind, fs=fs, output="sos")


def lp(x, fc, order=2, fs=FS):
    return ss.sosfilt(_sos("lowpass", fc, order, fs), x)


def hp(x, fc, order=2, fs=FS):
    return ss.sosfilt(_sos("highpass", fc, order, fs), x)


def bp(x, lo, hi, order=2, fs=FS):
    return ss.sosfilt(_sos("bandpass", [lo, hi], order, fs), x)


def peq(x, f0, q, gain_db, fs=FS):
    """RBJ peaking EQ."""
    a = 10 ** (gain_db / 40)
    w0 = TAU * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    b = [1 + alpha * a, -2 * np.cos(w0), 1 - alpha * a]
    den = [1 + alpha / a, -2 * np.cos(w0), 1 - alpha / a]
    return ss.lfilter(b, den, x)


def rms(x):
    return np.sqrt(np.mean(x ** 2)) + 1e-12


def norm_peak(x, peak=1.0):
    return x * (peak / (np.max(np.abs(x)) + 1e-12))


def reverb(x, rng, rt60, wet, tone=6000.0, predelay=0.012, length=None):
    """Convolution with a synthetic (decaying noise) impulse response."""
    length = length or min(rt60 * 1.3, 2.5)
    t = tvec(length)
    ir = rng.standard_normal(len(t)) * np.exp(-6.91 * t / rt60)
    ir = lp(ir, tone, 2)
    ir = np.concatenate([np.zeros(int(predelay * FS)), ir])
    ir /= np.sqrt(np.sum(ir ** 2))
    tail = ss.fftconvolve(x, ir)[: len(x)]
    return x + wet * tail * (rms(x) / rms(tail))


def damped(tt, f, tau, amp=1.0, phase=0.0):
    """Exponentially decaying sinusoid (resonant mode) starting at tt=0."""
    out = np.zeros_like(tt)
    m = tt >= 0
    out[m] = amp * np.exp(-tt[m] / tau) * np.sin(TAU * f * tt[m] + phase)
    return out


def finalize(x, fade_in=0.005, fade_out=0.06):
    """Downsample to SR, remove DC/rumble, fade, normalise to PEAK_DBFS."""
    y = ss.resample_poly(x, 1, OS)
    y = hp(y, 25, 2, fs=SR)
    n_in, n_out = int(fade_in * SR), int(fade_out * SR)
    y[:n_in] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n_in))
    y[-n_out:] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, n_out))
    return norm_peak(y, 10 ** (PEAK_DBFS / 20)).astype(np.float32)


# ----------------------------------------------------------------- sounds
def goal_horn():
    """Big low arena horn: detuned saw/square stack plus crowd swell."""
    rng = np.random.default_rng(101)
    dur = 4.0
    t = tvec(dur)
    n = len(t)

    scoop = 1 - 0.06 * np.exp(-t / 0.05)                        # pressure scoop-up
    droop = 1 - 0.035 * np.clip((t - 3.4) / 0.5, 0, 1) ** 2     # air runs out
    vib = 1 + 0.0028 * np.sin(TAU * 5.2 * t) * np.clip(t / 0.7, 0, 1)
    horn = np.zeros(n)
    for f0, g in [(110.0, 1.0), (138.59, 0.45), (164.81, 0.75), (220.0, 0.55)]:
        for cents in (-7.0, 0.0, 6.0):                          # chorus voices
            drift = 1 + 0.0015 * smooth_noise(n, 1.5, rng)
            f = f0 * 2 ** (cents / 1200) * scoop * droop * vib * drift
            ph0 = rng.random()
            horn += g * (0.6 * saw(f, n, ph0) + 0.4 * pulse(f, n, ph0)) / 3
    horn *= env(t, [(0, 0), (0.07, 1.0), (0.25, 0.92), (3.4, 0.9), (3.9, 0.0), (dur, 0.0)])
    horn = lp(horn, 3200, 4)
    horn = peq(horn, 450, 1.0, 5.0)
    horn = peq(horn, 1400, 1.5, 3.0)
    horn = np.tanh(1.8 * horn / np.max(np.abs(horn))) / np.tanh(1.8)
    horn = hp(horn, 60, 2)

    # crowd: four independent bands of fluttering noise ...
    noise_bed = np.zeros(n)
    for lo, hi, g in [(250, 500, 0.8), (500, 1000, 1.0), (1000, 2000, 0.8), (2000, 4000, 0.45)]:
        band = bp(rng.standard_normal(n), lo, hi, 2)
        flutter = 0.6 + 0.4 * np.tanh(smooth_noise(n, 7, rng))
        noise_bed += g * band * flutter
    # ... plus a few dozen rising "yeah!" voices through "ah" formants
    voices = np.zeros(n)
    for _ in range(28):
        f0 = rng.uniform(140, 420)
        start = rng.uniform(0.15, 1.3)
        tt = np.clip(t - start, 0, None)
        f = f0 * (1 + 0.25 * (1 - np.exp(-tt / 0.3)))
        f *= 1 + 0.012 * np.sin(TAU * rng.uniform(4, 7) * t + rng.uniform(0, TAU))
        venv = np.clip(tt / 0.25, 0, 1) * np.exp(-tt / rng.uniform(1.5, 4.0))
        voices += rng.uniform(0.5, 1.0) * saw(f, n, rng.random()) * venv
    voices = bp(voices, 600, 850) + 0.6 * bp(voices, 1050, 1350) + 0.3 * bp(voices, 2400, 2800)
    crowd = 0.7 * noise_bed / rms(noise_bed) + 0.6 * voices / rms(voices)
    crowd *= env(t, [(0, 0), (0.15, 0.05), (1.4, 1.0), (3.3, 0.9), (dur, 0.0)], 1.5)

    horn = reverb(horn, rng, rt60=1.6, wet=0.22, tone=4500)
    crowd = reverb(crowd, rng, rt60=1.6, wet=0.10, tone=4500)
    mix = horn + crowd * (rms(horn) / rms(crowd)) * 10 ** (-12 / 20)
    return finalize(mix, fade_in=0.005, fade_out=0.08)


def gavel():
    """Three sharp wooden knocks: click + body modes + desk thump."""
    rng = np.random.default_rng(202)
    dur = 1.5
    t = tvec(dur)
    n = len(t)
    out = np.zeros(n)
    for t0, amp in [(0.04, 0.85), (0.42, 0.9), (0.80, 1.0)]:
        tt = t - t0
        m = tt >= 0
        k = rng.uniform(0.98, 1.02)                              # each hit differs a bit
        click = np.zeros(n)
        click[m] = rng.standard_normal(m.sum()) * np.exp(-tt[m] / 0.0018)
        hit = 0.9 * bp(click, 1500, 7000, 2)
        for f, tau, a in [(560, 0.040, 1.0), (790, 0.030, 0.7), (1240, 0.018, 0.35), (2050, 0.010, 0.2)]:
            hit += damped(tt, f * k, tau, a)
        hit += damped(tt, 160 * k, 0.025, 0.5)                   # block/desk thump
        out += amp * hit
    out = reverb(out, rng, rt60=0.35, wet=0.18, tone=5000, predelay=0.005)
    return finalize(out, fade_in=0.002, fade_out=0.05)


def _brass_note(f0, dur, attack_scoop=True, vib_delay=0.4, rng=None, release=0.12):
    """One brass-section note: detuned saws + octave below, filter opens with level."""
    t = tvec(dur + release)
    n = len(t)
    scoop = 2 ** (-40 / 1200 * np.exp(-t / 0.04)) if attack_scoop else 1.0
    vib = 1 + 0.004 * np.sin(TAU * 5.5 * t) * np.clip((t - vib_delay) / 0.3, 0, 1)
    tone = np.zeros(n)
    for cents, g in [(-5, 1.0), (0, 1.0), (5, 1.0), (-1200, 1.05)]:
        f = f0 * 2 ** (cents / 1200) * scoop * vib
        tone += g * saw(f, n, rng.random())
    a = env(t, [(0, 0), (0.025, 1.0), (0.175, 0.8), (dur, 0.78), (dur + release, 0.0)])
    bright = a ** 1.5
    tone = lp(tone, 1100, 2) * (1 - bright) + lp(tone, 7000, 2) * bright
    tone = peq(tone, 2500, 1.2, 3.0)
    return tone * a


def draft_horn():
    """Bright two-note fanfare, D4 up a fifth to A4."""
    rng = np.random.default_rng(303)
    dur = 2.5
    out = np.zeros(len(tvec(dur)))
    for f0, start, length, rel in [(293.66, 0.03, 0.55, 0.06), (440.0, 0.68, 1.45, 0.30)]:
        note = _brass_note(f0, length, rng=rng, release=rel, vib_delay=0.4)
        i = int(start * FS)
        out[i:i + len(note)] += note[: len(out) - i]
    out = hp(out, 90, 2)
    out = reverb(out, rng, rt60=1.2, wet=0.2, tone=7000)
    return finalize(out, fade_in=0.005, fade_out=0.08)


def _tick(t, t0, rng, scale=1.0, amp=1.0):
    tt = t - t0
    m = tt >= 0
    n = len(t)
    burst = np.zeros(n)
    burst[m] = rng.standard_normal(m.sum()) * np.exp(-tt[m] / 0.0012)
    x = hp(burst, 2000, 2)
    for f, tau, a in [(3150, 0.012, 0.8), (4700, 0.008, 0.5), (1850, 0.020, 0.25)]:
        x += damped(tt, f * scale, tau, a)
    # faint escapement pre-click a few ms before the main tick
    pre = np.zeros(n)
    tp = t - (t0 - 0.008)
    mp = tp >= 0
    pre[mp] = rng.standard_normal(mp.sum()) * np.exp(-tp[mp] / 0.0008)
    return amp * (x + 0.12 * hp(pre, 3000, 2))


def on_the_clock():
    """Crisp tick-tock every 0.5 s, building, then a short buzzer on the beat."""
    rng = np.random.default_rng(404)
    dur = 4.25
    t = tvec(dur)
    n = len(t)
    ticks = np.zeros(n)
    for k in range(7):
        t0 = 0.02 + 0.5 * k
        ticks += _tick(t, t0, rng, scale=1.0 if k % 2 == 0 else 0.82, amp=0.6 + 0.4 * k / 6)
    ticks = reverb(ticks, rng, rt60=0.25, wet=0.12, tone=8000, predelay=0.004)
    ticks = lp(ticks, 12000, 4)                                  # keep peak energy in the audible band

    b0, b1 = 3.52, 4.18
    tb = np.clip(t - b0, 0, None)
    buzz = pulse(155.0, n) + pulse(157.5, n, 0.3) + 0.3 * saw(310.0, n)
    buzz *= env(t, [(0, 0), (b0, 0), (b0 + 0.005, 1.0), (b1 - 0.06, 0.95), (b1, 0.0), (dur, 0.0)])
    buzz = lp(buzz, 4000, 2)
    buzz = peq(buzz, 900, 1.0, 4.0)
    buzz = reverb(buzz * (tb > 0), rng, rt60=0.6, wet=0.12, tone=5000)

    mix = norm_peak(ticks, 1.0) + norm_peak(buzz, 0.75)
    return finalize(mix, fade_in=0.004, fade_out=0.05)


def _chime(t, t0, f, rng, tau=0.35, amp=1.0):
    tt = t - t0
    m = tt >= 0
    n = len(t)
    x = np.zeros(n)
    ttm = tt[m]
    idx = 2.0 * np.exp(-ttm / 0.08) + 0.08                       # FM index: bright strike
    mod = np.sin(TAU * 3.5 * f * ttm)
    car = np.sin(TAU * f * ttm + idx * mod)
    x[m] = car * np.exp(-ttm / tau)
    x[m] += 0.25 * np.sin(TAU * 2 * f * ttm) * np.exp(-ttm / (tau * 0.4))
    x[m] *= np.clip(ttm / 0.002, 0, 1)                            # 2 ms strike
    mallet = np.zeros(n)
    mallet[m] = rng.standard_normal(m.sum()) * np.exp(-ttm / 0.002)
    return amp * (x + 0.15 * bp(mallet, 3000, 8000, 2))


def trade_alert():
    """Upbeat rising three-note chime (G5, C6, E6) with a soft low 'deal done' thump."""
    rng = np.random.default_rng(505)
    dur = 1.5
    t = tvec(dur)
    out = np.zeros(len(t))
    for t0, f, tau, a in [(0.02, 783.99, 0.30, 0.8), (0.15, 1046.50, 0.30, 0.85), (0.28, 1318.51, 0.55, 1.0)]:
        out += _chime(t, t0, f, rng, tau, a)
    out += damped(t - 0.28, 1318.51 / 4, 0.2, 0.25)               # weight under the last note
    out = reverb(out, rng, rt60=0.9, wet=0.2, tone=9000)
    return finalize(out, fade_in=0.003, fade_out=0.08)


def final_buzzer():
    """Harsh end-of-period arena buzzer around 240 Hz with electro-mechanical rasp."""
    rng = np.random.default_rng(606)
    dur = 2.5
    t = tvec(dur)
    n = len(t)
    on, off, rel = 0.02, 2.15, 0.18
    spin = 1 - 0.06 * np.clip((t - off) / rel, 0, 1)             # pitch sags as it cuts out
    f = 240.0 * spin
    # phase-locked layers: steady tone, no slow beating
    x = pulse(f, n) + 0.6 * pulse(f, n, 0.2, duty=0.3) + 0.25 * pulse(f * 2, n, 0.5)
    x *= 1 + 0.25 * np.sin(TAU * 120 * t)                           # mains-hum rasp
    x = np.tanh(2.2 * x / np.max(np.abs(x))) / np.tanh(2.2)
    x = hp(x, 150, 2)
    x = lp(x, 6000, 2)
    x = peq(x, 1100, 1.0, 4.0)
    x = peq(x, 2800, 1.5, 3.0)
    x *= env(t, [(0, 0), (on, 0), (on + 0.008, 1.0), (off, 1.0), (off + rel, 0.0), (dur, 0.0)])
    x = reverb(x, rng, rt60=1.8, wet=0.25, tone=4500)
    return finalize(x, fade_in=0.004, fade_out=0.12)


SOUNDS = [
    ("blha-goal-horn", "BLHA Goal Horn", goal_horn),
    ("blha-gavel", "BLHA Gavel", gavel),
    ("blha-draft-horn", "BLHA Draft Horn", draft_horn),
    ("blha-on-the-clock", "BLHA On The Clock", on_the_clock),
    ("blha-trade-alert", "BLHA Trade Alert", trade_alert),
    ("blha-final-buzzer", "BLHA Final Buzzer", final_buzzer),
]


# ------------------------------------------------------------ encode/check
def encode_mp3(y, path, title):
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
        "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-id3v2_version", "3",
        "-metadata", f"title={title}",
        "-metadata", "artist=BLHA",
        "-metadata", "comment=Original synthesized sound owned by the BLHA",
        path,
    ]
    subprocess.run(cmd, input=y.astype("<f4").tobytes(), check=True)


def decode(path):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
           "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4")


def probe(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=format_name,duration,bit_rate:stream=codec_name,sample_rate,channels",
           "-of", "json", path]
    return json.loads(subprocess.run(cmd, capture_output=True, check=True).stdout)


def loudness_lufs(path):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
           "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    summary = err.split("Summary:")[-1]
    for line in summary.splitlines():
        if line.strip().startswith("I:"):
            return float(line.split()[1])
    return float("nan")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    report = []
    for stem, title, fn in SOUNDS:
        y = fn()
        path = os.path.join(out_dir, stem + ".mp3")
        encode_mp3(y, path, title)
        # MP3 coding can nudge peaks; trim gain once so the decoded file sits at about -1 dBFS.
        dec = decode(path)
        peak_db = 20 * np.log10(np.max(np.abs(dec)))
        if abs(peak_db - PEAK_DBFS) > 0.25:
            y = y * 10 ** ((PEAK_DBFS - peak_db) / 20)
            encode_mp3(y, path, title)
            dec = decode(path)
            peak_db = 20 * np.log10(np.max(np.abs(dec)))
        info = probe(path)
        report.append({
            "file": os.path.basename(path),
            "source_seconds": round(len(y) / SR, 3),
            "decoded_seconds": round(len(dec) / SR, 3),
            "probe_seconds": round(float(info["format"]["duration"]), 3),
            "bytes": os.path.getsize(path),
            "codec": info["streams"][0]["codec_name"],
            "sample_rate": int(info["streams"][0]["sample_rate"]),
            "channels": info["streams"][0]["channels"],
            "decoded_peak_dbfs": round(float(peak_db), 2),
            "clipped_samples": int(np.sum(np.abs(dec) >= 0.999)),
            "integrated_lufs": loudness_lufs(path),
        })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
