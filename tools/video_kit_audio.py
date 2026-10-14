"""Music beds, stings and sound effects for the BLHA Video Kit (SoundCraft folder).

Everything is synthesised here in numpy as 8-bit chiptune, in the voice of the league's hype intro
and soundboard: two pulse channels (12.5 / 25 / 50 % duty), a 4-bit triangle bass and a noise kit.
The beds reuse the hype intro's E minor theme so every league video sounds like the same league.

Output: 48 kHz, 24-bit stereo WAV. Beds sit at -16 LUFS so a voice can ride on top; stings and
effects at -14 LUFS (the soundboard's level). Loops are rendered three times over and the middle
pass is kept, so their tails wrap around and the loop point is seamless.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.signal import lfilter

SR = 48_000
NOTE_IDX = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


# ---------------------------------------------------------------- voices
def freq(name: str) -> float:
    n, octv = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((12 * (octv + 1) + NOTE_IDX[n] - 69) / 12)


def env(n, a=0.002, d=0.04, s=0.7, r=0.03):
    e = np.ones(n)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    if na > 0:
        e[:na] = np.linspace(0, 1, min(na, n))[: len(e[:na])]
    if nd > 0:
        seg = e[na:na + nd]
        e[na:na + nd] = 1 - (1 - s) * np.linspace(0, 1, len(seg))
    e[na + nd:] = s
    if 0 < nr < n:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def pulse(fr, dur, duty=0.5, vol=1.0, a=0.002, d=0.04, s=0.7, r=0.03, vib=0.0, slide=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if vib or slide:
        curve = fr * (1 + vib * np.sin(2 * np.pi * 5.5 * t) * np.minimum(1, t / 0.15)) * (2 ** (slide * t / max(dur, 1e-6)))
        ph = np.cumsum(curve) / SR
    else:
        ph = t * fr
    return np.where((ph % 1.0) < duty, 1.0, -1.0) * env(n, a, d, s, r) * vol


def tri(fr, dur, vol=1.0, a=0.002, d=0.02, s=1.0, r=0.02, slide=0.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = np.cumsum(fr * (2 ** (slide * t / max(dur, 1e-6)))) / SR if slide else t * fr
    w = np.round((4 * np.abs((ph % 1.0) - 0.5) - 1) * 7.5) / 7.5      # 4-bit steps like a NES triangle
    return w * env(n, a, d, s, r) * vol


_NOISE = np.random.RandomState(1986).uniform(-1, 1, SR * 6)
_noise_pos = [0]


def noise(dur, vol=1.0, tau=0.05, hp=False, lp=0):
    n = int(dur * SR)
    pos = _noise_pos[0] % (len(_NOISE) - n - 1)
    _noise_pos[0] = (pos + 7919) % len(_NOISE)
    x = _NOISE[pos:pos + n].copy()
    if hp:
        x = np.diff(x, prepend=0.0)
    if lp:
        x = np.repeat(x[::lp], lp)[:n]
    return x * np.exp(-np.arange(n) / SR / tau) * vol


def kick():
    body = tri(150, 0.16, 1.0, a=0.001, d=0.0, s=1.0, r=0.05, slide=-2.0)
    body *= np.exp(-np.arange(len(body)) / SR / 0.06)
    click = noise(0.02, 0.5, 0.006)
    body[:len(click)] += click
    return body


def snare(vol=1.0):
    x = noise(0.16, 0.9, 0.045)
    b = tri(190, 0.05, 0.5, r=0.02, slide=-1.0)
    x[:len(b)] += b
    return x * vol


def hat(open_=False):
    return noise(0.09 if open_ else 0.03, 0.35, 0.03 if open_ else 0.008, hp=True)


def crash(dur=1.6):
    return noise(dur, 0.6, dur / 3.2, hp=True)


def blip(fr, dur=0.06, duty=0.5, vol=1.0):
    return pulse(fr, dur, duty, vol, a=0.001, d=0.01, s=0.8, r=0.02)


def impact(vol=1.0):
    x = noise(0.22, 1.0, 0.06, lp=2)
    b = tri(220, 0.18, 1.0, r=0.05, slide=-2.5)
    x[:len(b)] += b * 0.9
    return x * vol


def riser(dur, f0=200, f1=1800, vol=1.0):
    """Noise swell plus a pulse sweep, rising into a hit at the end."""
    n = int(dur * SR)
    ramp = np.linspace(0, 1, n) ** 2
    x = noise(dur, 1.0, 1e9, hp=True) * ramp * 0.6
    x += pulse(f0, dur, 0.125, 1.0, a=0.01, d=0.0, s=1.0, r=0.01, slide=np.log2(f1 / f0)) * ramp * 0.35
    return x * vol


# ---------------------------------------------------------------- mixing
class Mix:
    def __init__(self, dur: float):
        self.n = int(round(dur * SR))
        self.tracks: dict[str, np.ndarray] = {}

    def add(self, track: str, t: float, sig: np.ndarray, vol: float = 1.0):
        buf = self.tracks.setdefault(track, np.zeros(self.n))
        i = int(round(t * SR))
        if i < 0:
            sig, i = sig[-i:], 0
        if i >= self.n:
            return
        seg = sig[:self.n - i]
        buf[i:i + len(seg)] += seg * vol

    def stereo(self, gains: dict[str, float], pans: dict[str, float] | None = None) -> np.ndarray:
        out = np.zeros((self.n, 2))
        for name, tr in self.tracks.items():
            th = (pans.get(name, 0.0) if pans else 0.0) + 1
            th *= np.pi / 4
            g = gains.get(name, 0.2)
            out[:, 0] += tr * g * np.cos(th) * np.sqrt(2)
            out[:, 1] += tr * g * np.sin(th) * np.sqrt(2)
        return out


GAINS = {"p1": 0.20, "p2": 0.13, "p3": 0.11, "bass": 0.28, "drums": 0.32, "sfx": 0.26}
PANS = {"p2": -0.35, "p3": 0.35}


def k_weight(x):
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x))


def lufs(x: np.ndarray) -> float:
    """Integrated loudness (ITU-R BS.1770, gated) of an (n, 2) or (n,) signal."""
    if x.ndim == 1:
        x = x[:, None]
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    if len(x) < blk:
        x = np.concatenate([x, np.zeros((blk - len(x), x.shape[1]))])
    count = (len(x) - blk) // hop + 1
    ms = np.zeros(count)
    for ch in range(x.shape[1]):
        y = k_weight(x[:, ch]) ** 2
        c = np.concatenate([[0.0], np.cumsum(y)])
        starts = np.arange(count) * hop
        ms += (c[starts + blk] - c[starts]) / blk
    lk = -0.691 + 10 * np.log10(ms + 1e-12)
    gated = ms[lk > -70]
    if not len(gated):
        return -70.0
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10
    gated = gated[(-0.691 + 10 * np.log10(gated + 1e-12)) > rel]
    return float(-0.691 + 10 * np.log10(gated.mean()))


def limiter(x, ceiling=0.891, look=0.004, release=0.06):
    need = np.minimum(1.0, ceiling / (np.abs(x).max(axis=1) + 1e-9))
    g = ndimage.minimum_filter1d(need, int(look * SR) * 2 + 1)
    out = np.empty_like(g)
    cur, rel = 1.0, np.exp(-1.0 / (release * SR))
    for i in range(len(g)):
        cur = g[i] if g[i] < cur else g[i] + (cur - g[i]) * rel
        out[i] = cur
    return x * out[:, None]


def master(x: np.ndarray, target: float, ceiling_db: float = -1.5, fade_in=0.0, fade_out=0.0) -> np.ndarray:
    if fade_in:
        n = int(fade_in * SR)
        x[:n] *= np.linspace(0, 1, n)[:, None]
    if fade_out:
        n = int(fade_out * SR)
        x[-n:] *= np.linspace(1, 0, n)[:, None]
    x = x * 10 ** ((target - lufs(x)) / 20)
    x = limiter(x, 10 ** (ceiling_db / 20))
    return x * 10 ** ((target - lufs(x)) / 20) if abs(lufs(x) - target) > 0.3 else x


def write_wav24(path: Path, x: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    if x.ndim == 1:
        x = np.stack([x, x], 1)
    pcm = np.clip(np.round(x * 8_388_607), -8_388_608, 8_388_607).astype("<i4")
    raw = pcm.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(raw)


def loop_render(build, loop_len: float) -> np.ndarray:
    """Render `build(mix, offset)` for three passes and keep the middle one (seamless loop)."""
    mix = Mix(loop_len * 3)
    for k in range(3):
        build(mix, k * loop_len)
    st = mix.stereo(GAINS, PANS)
    n = int(round(loop_len * SR))
    return st[n:2 * n]


# ---------------------------------------------------------------- the league's themes (from the hype intro)
THEME_A = {
    "Em": [("E5", 2), ("G5", 2), ("B5", 3), ("A5", 1)],
    "C": [("G5", 2), ("E5", 2), ("C5", 3), ("D5", 1)],
    "D": [("A5", 1), ("F#5", 1), ("D5", 2), ("F#5", 2), ("A5", 1), ("B5", 1)],
    "G": [("B5", 2), ("G5", 2), ("D5", 3), ("G5", 1)],
}
THEME_A_END = {"D": [("A5", 1), ("B5", 1), ("D6", 2), ("B5", 2), ("A5", 1), ("B5", 1)], "Em": [("E5", 2), ("B5", 2), ("E6", 4)]}
THEME_B = {
    "Em": ["E5", "E5", "B4", "E5", "G5", "E5", "B5", "G5"],
    "C": ["C5", "C5", "G4", "C5", "E5", "C5", "G5", "E5"],
    "D": ["D5", "D5", "A4", "D5", "F#5", "D5", "A5", "F#5"],
    "G": ["G5", "G5", "D5", "G5", "B5", "G5", "D6", "B5"],
}
ARP = {"Em": ["E4", "G4", "B4", "E5"], "C": ["C4", "E4", "G4", "C5"], "D": ["D4", "F#4", "A4", "D5"], "G": ["G4", "B4", "D5", "G5"],
       "Am": ["A3", "C4", "E4", "A4"]}
ROOT = {"Em": "E", "C": "C", "D": "D", "G": "G", "Am": "A"}


def phrase_song(mix: Mix, phrases, bpm: float, offset: float = 0.0, lead=True, lead_vol=1.0):
    """The hype intro's arranger: phrases are (chord, half-bars, section)."""
    beat = 60.0 / bpm
    e8 = beat / 2
    u = 0
    for pi, (ch, nu, sec) in enumerate(phrases):
        t0 = offset + u * 2 * beat
        nb = nu * 2
        u += nu
        nxt = phrases[pi + 1][2] if pi + 1 < len(phrases) else "end"
        last = nxt != sec
        first = pi == 0 or phrases[pi - 1][2] != sec
        root = ROOT[ch]

        def add(track, b, sig, vol=1.0):
            if b < nb - 1e-9:
                mix.add(track, t0 + b * beat, sig, vol)

        def note(track, b, nm, dur, duty, vol, **kw):
            dur = min(dur, (nb - b) * beat)
            if dur > 0.01:
                add(track, b, pulse(freq(nm), dur, duty, 1.0, **kw), vol)

        if sec in ("build", "A", "B", "A3", "finale", "groove", "groove2"):
            kicks = {"B": [0, 1.5, 2, 3.5], "finale": [0, 1.5, 2], "groove2": [0, 1.5, 2, 3.5]}.get(sec, [0, 2])
            for b in kicks:
                add("drums", b, kick(), 0.9)
            for b in (1, 3):
                add("drums", b, snare(), 0.8 if sec not in ("groove", "groove2") else 0.6)
            step = 0.25 if sec in ("B", "finale", "groove2") else 0.5
            b = 0.0
            while b < nb:
                add("drums", b, hat(open_=(abs(b % 1 - 0.5) < 1e-6 and sec not in ("B", "groove2"))), 0.7)
                b += step
            if last and nxt not in ("end", "outro"):
                for k in range(8):
                    add("drums", nb - 1 + k / 8, snare(), 0.35 + 0.08 * k)
        elif sec == "intro":
            b = 0.0
            while b < nb:
                add("drums", b, hat(), 0.35)
                b += 0.5
            if last:
                for k in range(8):
                    add("drums", nb - 2 + k / 4, snare(), 0.25 + 0.08 * k)
        elif sec == "outro":
            if first:
                add("drums", 0, crash(), 0.7)
                add("drums", 0, kick(), 1.0)
            else:
                b = 0.0
                while b < nb:
                    add("drums", b, hat(), 0.3)
                    b += 0.5
        # bass
        if sec in ("build", "A", "B", "A3", "finale", "groove", "groove2"):
            pat = [2, 2, 3, 2, 2, 2, 3, 3] if sec in ("B", "groove2") else [2, 3, 2, 3, 2, 3, 2, 2]
            for k in range(nb * 2):
                add("bass", k / 2, tri(freq(f"{root}{pat[k % 8]}"), e8 * 0.95, 1.0, r=0.01), 0.9)
        elif sec == "outro" and first:
            add("bass", 0, tri(freq(f"{root}2"), 4 * beat * 2, 1.0, r=1.0), 0.9)
        # pulses
        if sec == "intro" or (sec == "outro" and not first):
            for k in range(nb * 4):
                note("p2", k / 4, ARP[ch][k % 4], beat / 4 * 0.9, 0.125, 0.45 if sec == "intro" else 0.4, s=0.5)
        elif sec == "build":
            riff = [3, 3, 4, 3, 3, 4, 3, 4]
            for k in range(nb * 2):
                note("p1", k / 2, f"{root}{riff[k % 8]}", e8 * 0.7, 0.25, 0.8, s=0.6)
            for k in range(nb * 4):
                note("p2", k / 4, ARP[ch][k % 4], beat / 4 * 0.9, 0.125, 0.5, s=0.5)
        elif sec in ("A", "A3", "finale"):
            mel = THEME_A_END.get(ch, THEME_A[ch]) if last else THEME_A[ch]
            b = 0.0
            if lead:
                for nm, ln in mel:
                    dur = ln * e8
                    long_ = ln >= 3
                    note("p1", b / beat, nm, dur * (0.92 if long_ else 0.85), 0.5, lead_vol, vib=0.006 if long_ else 0.0)
                    if sec in ("A3", "finale"):
                        note("p2", b / beat, nm[:-1] + str(int(nm[-1]) - 1), dur * 0.85, 0.25, 0.55 * lead_vol)
                    b += dur
            for k in range(nb * 4):
                note("p2" if sec == "A" else "p3", k / 4, ARP[ch][(k * (1 if sec == "A" else 3)) % 4], beat / 4 * 0.9, 0.125,
                     0.5 if sec == "A" else 0.4, s=0.5)
        elif sec == "B":
            if lead:
                for k, nm in enumerate(THEME_B[ch]):
                    note("p1", k / 2, nm, e8 * 0.6, 0.25, 0.95 * lead_vol, s=0.5)
            for k in range(nb * 4):
                note("p2", k / 4, ARP[ch][(k * 3) % 4], beat / 4 * 0.9, 0.125, 0.5, s=0.5)
        elif sec in ("groove", "groove2"):          # voice-friendly: arps and a soft off-beat stab, no lead
            for k in range(nb * 4):
                note("p2", k / 4, ARP[ch][(k * (1 if sec == "groove" else 3)) % 4], beat / 4 * 0.9, 0.125, 0.42, s=0.5)
            for b in np.arange(0.5, nb, 1.0):
                lo = ARP[ch][1][:-1] + str(int(ARP[ch][1][-1]) + 1)
                note("p3", b, lo, e8 * 0.5, 0.25, 0.35, s=0.4)
        elif sec == "outro" and first:
            top = {"Em": ("E5", "B5", "G5"), "G": ("G5", "D6", "B5"), "C": ("C5", "G5", "E5"), "D": ("D5", "A5", "F#5")}[ch]
            add("p1", 0, pulse(freq(top[0]), 2.6, 0.5, 1.0, s=0.9, r=1.4, vib=0.01), 1.0)
            add("p2", 0, pulse(freq(top[1]), 2.6, 0.25, 1.0, s=0.9, r=1.4, vib=0.01), 0.7)
            add("p3", 0, pulse(freq(top[2]), 2.6, 0.125, 1.0, s=0.9, r=1.4, vib=0.01), 0.6)
            run = ARP[ch] + [n[:-1] + str(int(n[-1]) + 1) for n in ARP[ch][1:]]
            for k, nm in enumerate(run):
                add("p3", k / 4, pulse(freq(nm), beat / 4, 0.5, 1.0), 0.55)
    return u * 2 * beat


# ---------------------------------------------------------------- beds
def bed_hype() -> np.ndarray:
    """45 s at 150 BPM: quiet intro under the intro sting, the groove lands at 3.2 s, final chord at 41.6 s."""
    phrases = ([("Em", 2, "intro"), ("Em", 2, "intro")]
               + [("Em", 2, "A"), ("C", 2, "A"), ("D", 2, "A"), ("D", 2, "A")]
               + [(c, 2, "B") for c in ["Em", "C", "G", "D"] * 2]
               + [("Em", 2, "A"), ("C", 2, "A"), ("D", 2, "A"), ("D", 2, "A")]
               + [("C", 2, "A3"), ("D", 2, "A3"), ("Em", 2, "A3"), ("Em", 2, "A3")]
               + [("Em", 2, "finale"), ("C", 2, "finale"), ("D", 2, "finale"), ("D", 2, "finale")]
               + [("Em", 2, "outro"), ("Em", 2, "outro")])
    mix = Mix(45.0)
    phrase_song(mix, phrases, 150, lead_vol=0.8)
    return master(mix.stereo(GAINS, PANS), -16.0, fade_out=0.6)


def bed_week() -> np.ndarray:
    """60 s at 150 BPM, voice-friendly: arps, bass and drums with no lead under the talking."""
    prog = ["G", "D", "Em", "C"]
    phrases = ([("G", 2, "intro"), ("G", 2, "intro")]
               + [(c, 2, "groove") for c in prog * 4]
               + [(c, 2, "groove2") for c in prog * 4]
               + [("G", 2, "groove"), ("D", 2, "groove"), ("Em", 2, "groove"), ("C", 2, "groove")]
               + [("G", 2, "outro"), ("G", 1, "outro")])
    mix = Mix(60.0)
    phrase_song(mix, phrases, 150)
    return master(mix.stereo({**GAINS, "drums": 0.26}, PANS), -16.0, fade_out=0.5)


def bed_tutorial() -> np.ndarray:
    """38.4 s loop at 100 BPM (16 bars): soft triangle bass, slow 12.5 % arps, rim ticks. Sits under a voice."""
    bpm = 100
    beat = 60 / bpm
    prog = ["Em", "C", "G", "D"] * 2 + ["C", "D", "Em", "Em", "C", "D", "G", "D"]

    def build(mix, off):
        for bar, ch in enumerate(prog):
            t = off + bar * 4 * beat                    # one chord per bar
            root = ROOT[ch]
            for b in (0, 2):
                mix.add("bass", t + b * beat, tri(freq(f"{root}2"), beat * 1.8, 1.0, r=0.2), 0.8)
            for k in range(8):
                nm = ARP[ch][[0, 1, 2, 3, 2, 1, 2, 3][k]]
                mix.add("p2", t + k * beat / 2, pulse(freq(nm), beat / 2 * 0.8, 0.125, 1.0, d=0.08, s=0.35, r=0.05), 0.5)
            mix.add("p3", t, pulse(freq(ARP[ch][2]), beat * 3.6, 0.25, 1.0, a=0.05, d=0.3, s=0.25, r=0.4), 0.3)
            for b in (1, 3):
                mix.add("drums", t + b * beat, noise(0.03, 0.5, 0.01, hp=True), 0.6)
            for b in np.arange(0.5, 4, 1):
                mix.add("drums", t + b * beat, hat(), 0.35)
            mix.add("drums", t, kick(), 0.45)
            if bar % 4 == 3:
                melody = {"D": ["F#5", "A5", "D6"], "C": ["E5", "G5", "C6"]}.get(ch, ["B4", "E5", "G5"])
                for i, nm in enumerate(melody):
                    mix.add("p1", t + (2 + i * 0.5) * beat, pulse(freq(nm), beat * 0.45, 0.5, 1.0, s=0.5), 0.35)
    st = loop_render(build, len(prog) * 4 * beat)
    return master(st, -16.0)


def bed_awards() -> np.ndarray:
    """40 s loop at 96 BPM (16 bars, two per chord): a slow fanfare for Awards Night, long notes over arps."""
    bpm = 96
    beat = 60 / bpm
    prog = ["G", "D", "Em", "C", "G", "C", "D", "G"]
    fanfare = {0: [("D5", 2), ("G5", 1), ("B5", 1)], 1: [("A5", 3), ("F#5", 1)], 2: [("G5", 2), ("E5", 2)],
               3: [("E5", 2), ("G5", 1), ("C6", 1)], 4: [("B5", 3), ("D6", 1)], 5: [("C6", 2), ("G5", 2)],
               6: [("A5", 2), ("D6", 1), ("C6", 1)], 7: [("B5", 4)]}

    def build(mix, off):
        for i, ch in enumerate(prog):
            t = off + i * 8 * beat
            root = ROOT[ch]
            for b in (0, 4):
                mix.add("bass", t + b * beat, tri(freq(f"{root}2"), beat * 3.9, 1.0, r=0.3), 0.9)
                mix.add("drums", t + b * beat, tri(freq(f"{root}2") * 2, 0.35, 1.0, r=0.2, slide=-0.5), 0.5)   # timpani-ish
            for k in range(32):
                nm = ARP[ch][k % 4]
                mix.add("p3", t + k * beat / 4, pulse(freq(nm), beat / 4 * 0.85, 0.125, 1.0, s=0.4), 0.32)
            b = 0.0
            for nm, ln in fanfare[i]:
                dur = ln * 2 * beat * 0.95
                mix.add("p1", t + b * beat, pulse(freq(nm), dur, 0.5, 1.0, a=0.01, s=0.75, r=0.15, vib=0.008), 0.55)
                mix.add("p2", t + b * beat, pulse(freq(nm[:-1] + str(int(nm[-1]) - 1)), dur, 0.25, 1.0, a=0.01, s=0.7, r=0.15), 0.3)
                b += ln * 2
            for b in (1, 3, 5, 7):
                mix.add("drums", t + b * beat, snare(0.5), 0.5)
            if i % 2 == 1:
                for k in range(8):
                    mix.add("drums", t + (7 + k / 8) * beat, snare(), 0.2 + 0.05 * k)
    st = loop_render(build, len(prog) * 8 * beat)
    return master(st, -16.0)


# ---------------------------------------------------------------- stings and effects
def sting_intro() -> np.ndarray:
    """3.0 s, matched to blha-intro-sting.mp4: riser, the B slams in at 0.5 s, the tagline types on
    from 1.0 s, the gold rule and chord at 2.2 s."""
    mix = Mix(3.0)
    mix.add("sfx", 0.0, riser(0.5, 220, 1760), 0.8)
    mix.add("drums", 0.5, kick(), 1.0)
    mix.add("drums", 0.5, impact(), 0.9)
    mix.add("drums", 0.5, crash(1.4), 0.5)
    mix.add("bass", 0.5, tri(freq("E2"), 0.9, 1.0, r=0.4), 1.0)
    mix.add("p1", 0.5, pulse(freq("E4"), 0.35, 0.5, 1.0, d=0.2, s=0.3), 0.6)
    for i in range(15):                          # typing blips, one every other frame
        mix.add("sfx", 1.0 + i * 2 / 30, blip(freq("B5" if i % 2 else "E6"), 0.025, 0.25), 0.25)
    for k, nm in enumerate(["E5", "G5", "B5", "E6"]):
        mix.add("p2", 1.9 + k * 0.075, blip(freq(nm), 0.07, 0.125), 0.6)
    mix.add("p1", 2.2, pulse(freq("E5"), 0.75, 0.5, 1.0, s=0.8, r=0.45, vib=0.01), 0.9)
    mix.add("p2", 2.2, pulse(freq("B5"), 0.75, 0.25, 1.0, s=0.8, r=0.45, vib=0.01), 0.7)
    mix.add("p3", 2.2, pulse(freq("G5"), 0.75, 0.125, 1.0, s=0.8, r=0.45), 0.6)
    mix.add("bass", 2.2, tri(freq("E2"), 0.75, 1.0, r=0.45), 0.9)
    mix.add("drums", 2.2, crash(0.8), 0.35)
    return master(mix.stereo(GAINS, PANS), -14.0, -1.0, fade_out=0.08)


def sting_outro() -> np.ndarray:
    """3.0 s cadence for the outro: C - D - Em with a rising run and a ringing final chord."""
    mix = Mix(3.0)
    beat = 0.4
    for i, (ch, t) in enumerate([("C", 0.0), ("D", 0.4), ("Em", 0.8)]):
        for k, nm in enumerate(ARP[ch]):
            mix.add("p3", t + k * beat / 4, blip(freq(nm), beat / 4 * 0.9, 0.125), 0.6)
        mix.add("bass", t, tri(freq(f"{ROOT[ch]}2"), 0.38 if i < 2 else 1.9, 1.0, r=0.3 if i < 2 else 1.2), 0.9)
        mix.add("drums", t, kick(), 0.8)
    mix.add("drums", 0.8, crash(1.8), 0.6)
    mix.add("p1", 0.8, pulse(freq("E5"), 2.0, 0.5, 1.0, s=0.9, r=1.3, vib=0.01), 0.9)
    mix.add("p2", 0.8, pulse(freq("B5"), 2.0, 0.25, 1.0, s=0.9, r=1.3, vib=0.01), 0.7)
    for k, nm in enumerate(["E5", "G5", "B5", "E6", "G6", "B6"]):
        mix.add("p3", 0.8 + k * 0.1, pulse(freq(nm), 0.1, 0.5, 1.0), 0.5)
    return master(mix.stereo(GAINS, PANS), -14.0, -1.0, fade_out=0.3)


def sfx_whoosh() -> np.ndarray:
    """20 frames (0.667 s), loudest at 0.333 s where blha-pixel-wipe.mov covers the frame."""
    n = int(0.667 * SR)
    t = np.arange(n) / SR
    shape = np.exp(-((t - 0.333) / 0.12) ** 2)
    x = noise(0.667, 1.0, 1e9, hp=True) * shape
    x += pulse(300, 0.667, 0.125, 1.0, a=0.01, d=0.0, s=1.0, r=0.05, slide=2.0)[:n] * shape * 0.25
    return master(np.stack([x, x], 1), -18.0, -3.0)


def sfx_alert() -> np.ndarray:
    """1.6 s trade alert: a two-tone siren three times over a snare pickup."""
    mix = Mix(1.6)
    for i in range(6):
        mix.add("p1", i * 0.2, pulse(freq("B5" if i % 2 == 0 else "E6"), 0.18, 0.5, 1.0, s=0.8, r=0.03), 0.8)
        mix.add("p2", i * 0.2, pulse(freq("G5" if i % 2 == 0 else "B5"), 0.18, 0.25, 1.0, s=0.8, r=0.03), 0.5)
    for k in range(4):
        mix.add("drums", 1.0 + k * 0.05, snare(), 0.4 + 0.1 * k)
    mix.add("drums", 1.2, impact(), 0.8)
    mix.add("bass", 1.2, tri(freq("E2"), 0.4, 1.0, r=0.2), 0.8)
    return master(mix.stereo(GAINS, PANS), -14.0, -1.0, fade_out=0.05)


def sfx_clinch() -> np.ndarray:
    """2.0 s level-up: a rising major run, a chord and a crash."""
    mix = Mix(2.0)
    for k, nm in enumerate(["E5", "G#5", "B5", "E6", "G#6", "B6"]):
        mix.add("p1", k * 0.07, blip(freq(nm), 0.07, 0.5), 0.8)
    mix.add("drums", 0.45, kick(), 1.0)
    mix.add("drums", 0.45, crash(1.4), 0.55)
    mix.add("p1", 0.45, pulse(freq("E6"), 1.2, 0.5, 1.0, s=0.8, r=0.8, vib=0.012), 0.8)
    mix.add("p2", 0.45, pulse(freq("B5"), 1.2, 0.25, 1.0, s=0.8, r=0.8), 0.6)
    mix.add("p3", 0.45, pulse(freq("G#5"), 1.2, 0.125, 1.0, s=0.8, r=0.8), 0.5)
    mix.add("bass", 0.45, tri(freq("E2"), 1.2, 1.0, r=0.8), 0.9)
    return master(mix.stereo(GAINS, PANS), -14.0, -1.0, fade_out=0.1)


def sfx_reveal() -> np.ndarray:
    """2.0 s reveal hit: impact and crash on the first frame, then a sparkle tail."""
    mix = Mix(2.0)
    mix.add("drums", 0.0, kick(), 1.0)
    mix.add("drums", 0.0, impact(), 1.0)
    mix.add("drums", 0.0, crash(1.8), 0.6)
    mix.add("bass", 0.0, tri(freq("G2"), 1.0, 1.0, r=0.6), 0.9)
    mix.add("p1", 0.0, pulse(freq("G5"), 0.9, 0.5, 1.0, s=0.7, r=0.6, vib=0.01), 0.7)
    mix.add("p2", 0.0, pulse(freq("D6"), 0.9, 0.25, 1.0, s=0.7, r=0.6), 0.5)
    for k, nm in enumerate(["G6", "B6", "D7", "G6", "B6", "D7"]):
        mix.add("p3", 0.15 + k * 0.11, blip(freq(nm), 0.05, 0.5), 0.35 - 0.04 * k)
    return master(mix.stereo(GAINS, PANS), -14.0, -1.0, fade_out=0.2)


BEDS = {"bed-hype-45s": bed_hype, "bed-week-60s": bed_week, "bed-tutorial-loop": bed_tutorial, "bed-awards-loop": bed_awards}
STINGS = {"sting-intro": sting_intro, "sting-outro": sting_outro, "sfx-whoosh": sfx_whoosh, "sfx-alert": sfx_alert,
          "sfx-clinch": sfx_clinch, "sfx-reveal": sfx_reveal}


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64).reshape(-1, 2)


def build(out: Path, soundboard: Path) -> dict[str, dict]:
    """Write every WAV under `out` (Beds/, Stings and Effects/, Soundboard/); returns name -> facts."""
    facts = {}
    for folder, table in (("Beds", BEDS), ("Stings and Effects", STINGS)):
        for name, fn in table.items():
            x = fn()
            write_wav24(out / folder / f"{name}.wav", x)
            facts[name] = {"seconds": round(len(x) / SR, 3), "lufs": round(lufs(x), 1), "peak_db": round(20 * np.log10(np.abs(x).max()), 1)}
    for mp3 in sorted(soundboard.glob("*.mp3")):
        x = decode(mp3)
        write_wav24(out / "Soundboard" / f"{mp3.stem}.wav", x)
        facts[mp3.stem] = {"seconds": round(len(x) / SR, 3), "lufs": round(lufs(x), 1), "peak_db": round(20 * np.log10(np.abs(x).max() + 1e-12), 1)}
    return facts
