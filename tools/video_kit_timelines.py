"""FilmCraft timelines for the BLHA Video Kit, written as OpenTimelineIO (.otio) files.

FilmCraft imports OTIO with File > Import: every timeline in a file becomes a sequence, with its
tracks, clips, markers and track volumes, and media paths relative to the .otio file. Each
sequence follows one script in the BLHA Video Scripts doc: the real stings, wipes, music and
b-roll are already in place, placeholder slates mark what to drop in (camera, screen recording,
an EffectCraft render), and a marker sits on every line of the script with the words in it.

Tracks: V1 picture, V2 graphics (EffectCraft renders, many with alpha), V3 overlays (the corner
bug), V4 transitions (pixel wipes); A1 voice, A2 music, A3 effects and stings, A4 the wipes' whooshes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FPS = 30
WPS = 2.5               # reading pace: 150 words a minute

TRACKS = [("V1", "Video", "PICTURE"), ("V2", "Video", "GRAPHICS"), ("V3", "Video", "OVERLAYS"),
          ("V4", "Video", "TRANSITIONS"), ("A1", "Audio", "VOICE"), ("A2", "Audio", "MUSIC"),
          ("A3", "Audio", "EFFECTS"), ("A4", "Audio", "TRANSITIONS")]

# what each piece of real media is and how long it runs (seconds); None = a still
MEDIA = {
    "sting": ("Media/Stings/blha-intro-sting.mp4", 3.0),
    "outro": ("Media/Stings/blha-outro.mp4", 5.0),
    "wipe": ("Media/Transitions/blha-pixel-wipe.mov", 20 / 30),
    "bug": ("Media/Overlays/blha-corner-bug.png", None),
    "hype": ("Media/B-roll/BLHA_Hype_Intro.mp4", 75.2),
    "bed-hype-45s": ("../SoundCraft/Beds/bed-hype-45s.wav", 45.0),
    "bed-week-60s": ("../SoundCraft/Beds/bed-week-60s.wav", 60.0),
    "bed-tutorial-loop": ("../SoundCraft/Beds/bed-tutorial-loop.wav", 38.4),
    "bed-awards-loop": ("../SoundCraft/Beds/bed-awards-loop.wav", 40.0),
    "sting-intro": ("../SoundCraft/Stings and Effects/sting-intro.wav", 3.0),
    "sting-outro": ("../SoundCraft/Stings and Effects/sting-outro.wav", 3.0),
    "sfx-whoosh": ("../SoundCraft/Stings and Effects/sfx-whoosh.wav", 20 / 30),
}


def fr(seconds: float) -> int:
    return int(round(seconds * FPS))


def rt(frames: int) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(FPS), "value": float(frames)}


def trange(start: int, dur: int) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(start), "duration": rt(dur)}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


@dataclass
class Slate:
    kind: str
    title: str
    lines: list[str]

    @property
    def file(self) -> str:
        return f"Media/Slates/{slug(self.kind + ' ' + self.title)}.png"


@dataclass
class Item:
    start: int
    dur: int
    name: str
    url: str
    src_in: int = 0
    avail: int | None = None
    gain: float = 0.0


@dataclass
class Seq:
    name: str
    seconds: float
    tracks: dict = field(default_factory=lambda: {k: [] for k, _, _ in TRACKS})
    markers: list = field(default_factory=list)
    volumes: dict = field(default_factory=dict)

    @property
    def end(self) -> int:
        return fr(self.seconds)

    def put(self, track, start, dur, name, url, src_in=0.0, avail=None, gain=0.0):
        s, d = fr(start), fr(dur)
        s_end = min(s + d, self.end)
        if s_end > s:
            self.tracks[track].append(Item(s, s_end - s, name, url, fr(src_in), None if avail is None else fr(avail), gain))
        return self

    def media(self, track, start, key, dur=None, src_in=0.0, name=None, gain=0.0):
        url, length = MEDIA[key]
        if dur is None:
            dur = (length - src_in) if length else self.seconds - start
        return self.put(track, start, dur, name or key, url, src_in, length, gain)

    def loop(self, track, start, key, until=None, gain=0.0):
        """A music loop laid end to end from `start` to `until` (default: the end)."""
        length = MEDIA[key][1]
        t, until = start, self.seconds if until is None else until
        while t < until - 0.05:
            self.media(track, t, key, min(length, until - t), gain=gain)
            t += length
        return self

    def slate(self, track, start, dur, kind, title, lines):
        sl = Slate(kind, title, lines)
        SLATES[sl.file] = sl
        return self.put(track, start, dur, f"PLACEHOLDER: {title}", sl.file)

    def wipe(self, cut: float):
        """The pixel wipe over a cut (fully covered on the cut's two frames), with its whoosh."""
        self.media("V4", cut - 10 / FPS, "wipe")
        return self.media("A4", cut - 10 / FPS, "sfx-whoosh")

    def marker(self, t, name, comment="", color="YELLOW"):
        self.markers.append((fr(t), name[:80], comment, color))
        return self

    # ------------------------------------------------------------ OTIO
    def otio(self) -> dict:
        children = []
        for key, kind, label in TRACKS:
            items = sorted(self.tracks[key], key=lambda i: i.start)
            kids, pos = [], 0
            for it in items:
                if it.start < pos:
                    raise ValueError(f"{self.name} {key}: {it.name} at {it.start} overlaps the previous clip (ends {pos})")
                if it.start > pos:
                    kids.append({"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": trange(0, it.start - pos),
                                 "effects": [], "markers": [], "enabled": True, "metadata": {}})
                ref = {"OTIO_SCHEMA": "ExternalReference.1", "name": Path(it.url).name, "target_url": it.url,
                       "available_range": None if it.avail is None else trange(0, it.avail),
                       "available_image_bounds": None, "metadata": {}}
                meta = {"filmcraft": {"gain_db": it.gain}} if it.gain else {}
                kids.append({"OTIO_SCHEMA": "Clip.2", "name": it.name, "source_range": trange(it.src_in, it.dur),
                             "effects": [], "markers": [], "enabled": True, "metadata": meta,
                             "media_references": {"DEFAULT_MEDIA": ref}, "active_media_reference_key": "DEFAULT_MEDIA"})
                pos = it.start + it.dur
            vol = self.volumes.get(key)
            children.append({"OTIO_SCHEMA": "Track.1", "name": f"{key} {label}", "kind": kind, "children": kids,
                             "effects": [], "markers": [], "enabled": True, "source_range": None,
                             "metadata": {"filmcraft": {"volume_db": vol}} if vol is not None else {}})
        markers = [{"OTIO_SCHEMA": "Marker.2", "name": n, "marked_range": trange(t, 0), "color": c, "comment": cm,
                    "metadata": {}} for t, n, cm, c in sorted(self.markers)]
        return {"OTIO_SCHEMA": "Timeline.1", "name": self.name, "global_start_time": None, "metadata": {},
                "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": children, "effects": [],
                           "markers": markers, "enabled": True, "source_range": None, "metadata": {}}}


SLATES: dict[str, Slate] = {}


# ---------------------------------------------------------------- reading the scripts
class Scripts:
    def __init__(self, path: Path):
        self.items = json.loads(path.read_text())

    def get(self, prefix: str) -> dict:
        for v in self.items:                         # an exact title (before its parentheses) first
            if re.sub(r" [(].*", "", v["title"]).lower() == prefix.lower():
                return v
        for v in self.items:
            if v["title"].lower().startswith(prefix.lower()):
                return v
        raise KeyError(prefix)

    @staticmethod
    def stamp(s: str) -> float | None:
        m = re.match(r"^(\d+):(\d\d)$", s.strip())
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    def rows(self, prefix: str, start: float = 0.0, length: float | None = None):
        """(time, on screen, say) for each row: the script's own times, or times paced from the
        words at 150 a minute when the script has none (stretched to `length` if given)."""
        v = self.get(prefix)
        head = v["header"] or []
        out = []
        if head and head[0] in ("Time",):
            for r in v["rows"]:
                out.append((self.stamp(r[0]), r[1], r[2]))
            return out
        t = start
        raw = []
        for r in v["rows"]:
            screen, say = r[-2], r[-1]
            raw.append([t, screen, say])
            t += max(3.0, len(say.split()) / WPS + 0.8)
        if length and t > start:
            k = (length - start) / (t - start)
            for r in raw:
                r[0] = start + (r[0] - start) * k
        return [tuple(r) for r in raw]

    def paragraphs(self, prefix: str, skip: int = 1):
        return [n for n in self.get(prefix)["notes"][skip:]]


def say_markers(seq: Seq, rows, color="YELLOW"):
    for t, screen, say in rows:
        seq.marker(t, screen, say, color)


def paced(seq: Seq, start: float, end: float, texts, color="YELLOW", label="SAY"):
    """Markers for paragraphs, spread by their word counts between start and end."""
    words = [max(1, len(re.sub(r"[^\w\s]", " ", s).split())) for s in texts]
    total = sum(words)
    t = start
    for w, s in zip(words, texts):
        seq.marker(t, s[:60], s, color)
        t += (end - start) * w / total


# ---------------------------------------------------------------- common slates
def cam(seq, start, dur, what="CAMERA: YOU ON CAMERA"):
    return seq.slate("V1", start, dur, "camera", what,
                     ["Record 1920x1080 at 30 fps, landscape, eye level, the light in front of you.",
                      "Drop the clip here on V1 (its sound comes with it). The markers above hold the script."])


def screen(seq, start, dur, what="SCREEN RECORDING"):
    return seq.slate("V1", start, dur, "screen", what,
                     ["Record at 1920x1080 with the browser at 125% zoom and notifications off.",
                      "Drop the recording here on V1. Record your voice on A1, following the markers."])


def render(seq, track, start, dur, script, comp, how="H.264", where=None):
    alpha = "ProRes 4444 with alpha" in how
    return seq.slate(track, start, dur, "render", f"{script}: {comp}",
                     [f"EffectCraft: run \"{script}\", then render the comp \"{comp}\" as {how}.",
                      where or f"Drop the render on {track} at {start // 60:.0f}:{start % 60:04.1f}. "
                               + ("It's see-through, so the picture underneath shows." if alpha else "")])


ALPHA = "ProRes 4444 with alpha"


def music(seq, key, start=0.0, until=None, db=-14.0):
    seq.volumes["A2"] = db
    if key.endswith("loop"):
        seq.loop("A2", start, key, until)
    else:
        seq.media("A2", start, key, dur=None if until is None else until - start)
    return seq


def voice_track(seq):
    seq.volumes.setdefault("A1", 0.0)
    seq.volumes.setdefault("A3", -2.0)
    seq.volumes.setdefault("A4", -6.0)


def intro(seq, wipe=True):
    seq.media("V1", 0, "sting").media("A3", 0, "sting-intro")
    if wipe:
        seq.wipe(3.0)


def outro(seq, at):
    seq.media("V1", at, "outro").media("A3", at, "sting-outro")


def bug(seq, start, end):
    seq.media("V3", start, "bug", dur=end - start)


# ---------------------------------------------------------------- the timelines
def hype_trailer(S: Scripts):
    seqs = []
    # Recruiting trailer: cut together from the league's hype intro, ready for a voice.
    q = Seq("Recruiting Trailer", 45)
    intro(q)
    cuts = [(3.0, 4.0, 5.4, "Arena and crowd"), (8.4, 9.6, 5.6, "BLHA logo"), (14.0, 24.0, 8.8, "20 active, 10 minors"),
            (22.8, 46.0, 4.4, "Unlimited trades"), (27.2, 50.4, 5.6, "Dynasty Pot coins"), (32.8, 56.0, 5.6, "Championship banners"),
            (38.4, 67.2, 6.6, "End card: claim your franchise")]
    for at, src, dur, name in cuts:
        q.media("V1", at, "hype", dur=dur, src_in=src, name=f"Hype intro: {name}")
        if at > 3.0:
            q.wipe(at)
    starts = [0.0] + [c[0] for c in cuts]
    for (t, screen_, say), at in zip(S.rows("Recruiting trailer"), starts):
        q.marker(at, screen_, say)
    music(q, "bed-hype-45s", db=-8.0)
    voice_track(q)
    seqs.append(q)

    def hype(name, script, cards_set, cards, v1, wipes=()):
        s = Seq(name, 45)
        intro(s)
        for at, dur in cards:
            render(s, "V2", at, dur, "11 Explainer Cards", f"{cards_set} (alpha)", ALPHA,
                   f"Put the whole 45-second render on V2 at 0:00; its cards land on these spots by themselves.")
        for at, dur, kind, title, lines in v1:
            if kind == "hype":
                s.media("V1", at, "hype", dur=dur, src_in=lines, name=f"Hype intro: {title}")
            elif kind == "render":
                render(s, "V1", at, dur, title, lines)
            else:
                s.slate("V1", at, dur, kind, title, lines)
        for w in wipes:
            s.wipe(w)
        say_markers(s, S.rows(script))
        music(s, "bed-hype-45s", db=-8.0)
        voice_track(s)
        return s

    seqs.append(hype("Startup Draft Hype", "Startup Draft hype", "Startup Draft Hype Cards",
                     [(8, 13), (27, 6), (39, 6)],
                     [(3, 5, "hype", "Empty rink", 4.0), (21, 6, "render", "04 Franchise Cards", "Franchise Cards - All"),
                      (33, 6, "render", "09 Countdown", "Countdown - STARTUP DRAFT")], wipes=(21, 33)))
    seqs.append(hype("Opening Night", "Opening night", "Opening Night Cards",
                     [(8, 23), (37, 8)],
                     [(3, 5, "hype", "Arena lights up", 4.0), (31, 6, "render", "04 Franchise Cards", "Franchise Cards - All")],
                     wipes=(31,)))
    s = Seq("Trade Deadline Day", 45)
    s.media("A3", 0, "sting-intro")
    for at, dur in [(0, 10), (28, 17)]:
        render(s, "V2", at, dur, "11 Explainer Cards", "Trade Deadline Cards (alpha)", ALPHA,
               "Put the whole 45-second render on V2 at 0:00; its cards land on these spots by themselves.")
    for i, at in enumerate((10, 16, 22)):
        render(s, "V1", at, 6, "05 Trade Alert", f"Trade Alert - deadline deal {i + 1}")
        s.wipe(at) if at > 10 else None
    say_markers(s, S.rows("Trade deadline day"))
    music(s, "bed-hype-45s", db=-8.0)
    voice_track(s)
    seqs.append(s)
    seqs.append(hype("Championship Hype", "Championship hype", "Championship Hype Cards",
                     [(9, 5), (22, 15), (42, 3)],
                     [(3, 6, "render", "04 Franchise Cards", "Franchise Card - (each finalist)"),
                      (14, 8, "render", "07 Playoff Bracket", "Bracket - (year)"),
                      (37, 5, "render", "09 Countdown", "Countdown - THE BLHA CHAMPIONSHIP")], wipes=(14, 37)))
    return "BLHA Hype Trailer", seqs


def talking_head(S: Scripts):
    seqs = []
    s = Seq("Commissioner Welcome", 75)
    intro(s, wipe=False)
    cam(s, 3, 65, "CAMERA: THE COMMISSIONER WELCOME")
    render(s, "V2", 3.2, 6, "01 Brand Kit", "Lower Third - YOUR NAME", ALPHA)
    bug(s, 9, 68)
    outro(s, 68)
    render(s, "V2", 68, 7, "01 Brand Kit", "End Card")
    paced(s, 3, 67, S.paragraphs("Commissioner welcome"))
    music(s, "bed-tutorial-loop", until=68, db=-24.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Winter Meetings Recap", 60)
    intro(s, wipe=False)
    cam(s, 3, 54, "CAMERA: WINTER MEETINGS RECAP")
    render(s, "V2", 3.2, 6, "01 Brand Kit", "Lower Third - YOUR NAME", ALPHA)
    bug(s, 9, 57)
    outro(s, 57)
    paced(s, 3, 56, S.paragraphs("Winter Meetings recap"))
    music(s, "bed-tutorial-loop", until=57, db=-24.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Wooden Spoon Preview", 60)
    intro(s, wipe=False)
    cam(s, 3, 54, "CAMERA: THE SPOON HOLDER")
    render(s, "V2", 3.2, 6, "01 Brand Kit", "Lower Third - (Spoon holder)", ALPHA)
    bug(s, 9, 57)
    outro(s, 57)
    paced(s, 3, 56, S.paragraphs("Wooden Spoon preview"))
    music(s, "bed-tutorial-loop", until=57, db=-24.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Owner Spotlight", 480)
    intro(s, wipe=False)
    render(s, "V1", 3, 8, "04 Franchise Cards", "Franchise Card - (the owner's franchise)")
    s.slate("V1", 11, 462, "camera", "THE INTERVIEW: VOICES OR CAMERA",
            ["Two voices recorded at once: you in SoundCraft, the owner on a phone. Clap once at the start.",
             "Line both up on A1 by the clap. For pictures, use the franchise card or a camera clip here."])
    bug(s, 11, 473)
    outro(s, 473)
    qs = [n.lstrip("• ").strip() for n in S.get("Owner spotlight")["notes"] if n.startswith("•")]
    for i, q in enumerate(qs):
        s.marker(11 + i * 45, f"Q{i + 1}: {q}", q, "CYAN")
    music(s, "bed-tutorial-loop", until=11, db=-20.0)
    voice_track(s)
    seqs.append(s)
    return "BLHA Talking Head", seqs


HOWTOS = ["Moving a player to minors", "Setting your daily lineup", "Paying dues with Fantrax Treasurer",
          "Building your draft queue", "Placing a FAAB bid", "Making a trade", "Using IR",
          "Turning on Fantrax notifications", "Opening a ticket", "Meet the League Bot"]


def seconds_in(title: str, default: float) -> float:
    m = re.search(r"\((\d+) seconds", title)
    return float(m.group(1)) if m else default


def card_title(screen_: str) -> str | None:
    m = re.match(r"^(Title|Card|Title card):\s*(.+)$", screen_)
    return m.group(2).strip() if m else None


def screen_tutorial(S: Scripts):
    seqs = []
    s = Seq("Server Tour", 150)
    screen(s, 0, 150, "SCREEN RECORDING: THE SERVER TOUR")
    rows = S.rows("Server tour")
    for t, scr, say in rows[1:-1]:
        render(s, "V2", t + 0.3, 3.5, "01 Brand Kit", f"Section Title - {scr}", ALPHA,
               "Set the section title's words in DATA, render it, and drop it here on V2.")
    bug(s, 0, 150)
    say_markers(s, rows)
    music(s, "bed-tutorial-loop", db=-24.0)
    voice_track(s)
    seqs.append(s)

    for name in HOWTOS:
        v = S.get(name)
        length = seconds_in(v["title"], 60)
        s = Seq(f"How-to - {re.sub(r' [(].*', '', v['title'])}", length)
        rows = S.rows(name, 0, length - 2)
        screen(s, 0, length, f"SCREEN RECORDING: {re.sub(r' [(].*', '', v['title']).upper()}")
        for i, (t, scr, say) in enumerate(rows):
            ct = card_title(scr)
            if ct:
                nxt = rows[i + 1][0] if i + 1 < len(rows) else length
                render(s, "V2", t, max(3.0, nxt - t), "11 Explainer Cards", f"Card - {ct.upper()}",
                       where="The How-to Cards set makes one 6-second comp per card. Drop it here on V2 and trim to fit.")
        bug(s, 0, length)
        say_markers(s, rows)
        music(s, "bed-tutorial-loop", db=-24.0)
        voice_track(s)
        seqs.append(s)

    s = Seq("Draft Order Draw", 180)
    render(s, "V1", 0, 6, "11 Explainer Cards", "Card - STARTUP DRAFT ORDER DRAW")
    screen(s, 6, 168, "SCREEN RECORDING: THE DRAW, ONE TAKE, NO CUTS")
    render(s, "V1", 174, 6, "01 Brand Kit", "End Card")
    say_markers(s, S.rows("Draft order draw", 0, 174))
    voice_track(s)
    seqs.append(s)
    return "BLHA Screen Tutorial", seqs


EXPLAINERS = [("The Constitution in 3 Minutes", "The Constitution in 3 minutes", "Constitution in 3 Minutes", 180),
              ("How Scoring Works", "How scoring works", "How Scoring Works", 60),
              ("Where the Money Goes", "Where the money goes", "Where the Money Goes", 45),
              ("How the Annual Draft Order Works", "How the Annual Draft order works", "Annual Draft Order", 60),
              ("Dynasty Pot Update", "Dynasty Pot update", "Dynasty Pot Update", 30),
              ("Rule Change Vote", "Rule changes explainer", "Rule Change Vote", 56)]


def explainer(S: Scripts):
    seqs = []
    for name, script, comp, length in EXPLAINERS:
        s = Seq(name, length)
        render(s, "V1", 0, length, "11 Explainer Cards", comp, where="Drop the render on V1 at 0:00. It's timed to the script, so the markers line up.")
        say_markers(s, S.rows(script, 0, length - 2))
        music(s, "bed-tutorial-loop", db=-22.0)
        voice_track(s)
        seqs.append(s)
    return "BLHA Explainer", seqs


def week_in_60(S: Scripts):
    s = Seq("Week in 60", 60)
    render(s, "V1", 0, 60, "02 Week in 60", "Week in 60 - Week NN", where="Drop the render on V1 at 0:00. Its WEEK slam lands on the sting's hit at 0.5 s.")
    s.media("A3", 0, "sting-intro")
    say_markers(s, S.rows("Week in 60"))
    music(s, "bed-week-60s", db=-16.0)
    voice_track(s)
    return "BLHA Week in 60", [s]


def monthly_awards(S: Scripts):
    s = Seq("Monthly Awards", 60)
    render(s, "V1", 0, 60, "03 Monthly Awards", "Monthly Awards - MONTH", where="Drop the render on V1 at 0:00. Its title lands on the sting's hit at 0.5 s.")
    s.media("A3", 0, "sting-intro")
    say_markers(s, S.rows("Monthly awards"))
    music(s, "bed-week-60s", db=-16.0)
    voice_track(s)
    return "BLHA Monthly Awards", [s]


def playoff_show(S: Scripts):
    seqs = []
    s = Seq("Bracket Reveal", 60)
    render(s, "V1", 0, 60, "07 Playoff Bracket", "Bracket Reveal - YEAR", where="Drop the render on V1 at 0:00. It's timed to the script.")
    s.media("A3", 0, "sting-intro")
    say_markers(s, S.rows("Bracket reveal"))
    music(s, "bed-week-60s", db=-14.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Round Preview", 45)
    rows = S.rows("Round preview")
    render(s, "V1", 0, 4, "07 Playoff Bracket", "Bracket - YEAR")
    render(s, "V1", 4, 22, "07 Playoff Bracket", "Matchup - (first matchup)")
    render(s, "V1", 26, 16, "07 Playoff Bracket", "Matchup - (second matchup)")
    render(s, "V1", 42, 3, "01 Brand Kit", "End Card")
    s.wipe(4).wipe(26).wipe(42)
    say_markers(s, rows)
    music(s, "bed-hype-45s", db=-12.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Champion", 30)
    intro(s)
    s.slate("V1", 3, 4.6, "card", "FINAL SCORE CARD",
            ["Use 01 Brand Kit's Title Card: eyebrow FINAL, title with both scores.", "Or FilmCraft's own title: Graphics and Titles."])
    render(s, "V1", 7.6, 12, "08 Champion Banner", "Champion Banner - YEAR",
           where="Starts at 0:07.6 so the banner lands at 0:09 with its own sound.")
    s.slate("V1", 19.6, 7.4, "broll", "OWNER PHOTO OR FRANCHISE CARD", ["A photo the owner sent, or the 04 Franchise Cards render for the champion."])
    render(s, "V1", 27, 3, "01 Brand Kit", "End Card")
    say_markers(s, S.rows("Champion"))
    music(s, "bed-hype-45s", until=30, db=-12.0)
    voice_track(s)
    seqs.append(s)

    s = Seq("Third Place and Consolation", 30)
    render(s, "V1", 0, 14, "01 Brand Kit", "Title Card - THIRD PLACE")
    render(s, "V1", 14, 12, "01 Brand Kit", "Title Card - CONSOLATION CHAMPION")
    render(s, "V1", 26, 4, "01 Brand Kit", "End Card")
    s.wipe(14).wipe(26)
    say_markers(s, S.rows("Third place and consolation"))
    music(s, "bed-week-60s", until=30, db=-16.0)
    voice_track(s)
    seqs.append(s)
    return "BLHA Playoff Show", seqs


def season_in_review(S: Scripts):
    rows = S.get("Season in review")["rows"]
    lengths = [8, 28, 28, 28, 28, 24, 40, 24, 8]
    total = sum(lengths) + 5
    s = Seq("Season in Review", total)
    s.media("A3", 0, "sting-intro")
    t = 0.0
    picture = {"Cold open": ("render", "01 Brand Kit", "Title Card - SEASON IN REVIEW"),
               "The draft": ("broll", "THE DRAFT BOARD", ["A screenshot of the draft results, slowly zoomed."]),
               "The early weeks": ("broll", "STANDINGS AFTER WEEK 5", ["A standings screenshot, or the Week 5 Week in 60 render."]),
               "The trades": ("render", "05 Trade Alert", "Trade Alert - (the trade of the season)"),
               "The race": ("broll", "PLAYOFF RACE STANDINGS", ["A screenshot of the playoff-race post near the end."]),
               "The Presidents' Trophy": ("broll", "FINAL STANDINGS", ["A screenshot of the final standings."]),
               "The playoffs": ("render", "07 Playoff Bracket", "Bracket - YEAR"),
               "The final": ("render", "08 Champion Banner", "Champion Banner - YEAR"),
               "Close": ("render", "01 Brand Kit", "End Card")}
    for (chapter, scr, say), ln in zip(rows, lengths):
        p = picture.get(chapter)
        if p and p[0] == "render":
            render(s, "V1", t, ln, p[1], p[2])
        elif p:
            s.slate("V1", t, ln, p[0], p[1], p[2])
        if 0 < t < total - 13:
            render(s, "V2", t + 0.3, 3.5, "01 Brand Kit", f"Section Title - {chapter.upper()}", ALPHA)
            s.wipe(t)
        s.marker(t, f"{chapter}: {scr}", say, "YELLOW")
        t += ln
    outro(s, t)
    s.volumes["A2"] = -18.0
    hype_from = sum(lengths[:6])
    s.loop("A2", 0, "bed-tutorial-loop", until=hype_from)
    s.media("A2", hype_from, "bed-hype-45s", dur=min(45.0, total - hype_from))
    voice_track(s)
    return "BLHA Season in Review", [s]


def awards_night(S: Scripts):
    notes = S.get("Awards Night host script")["notes"]
    s = Seq("Awards Night", 3600)
    t = 0.0

    def seg_cam(dur, title, text):
        nonlocal t
        cam(s, t, dur, f"CAMERA: {title}")
        s.marker(t, title, text, "YELLOW")
        t += dur

    def seg_render(dur, script, comp):
        nonlocal t
        render(s, "V1", t, dur, script, comp)
        t += dur

    seg_render(8, "10 Awards Night", "Awards Night - Title")
    welcome = next((n for n in notes if n.startswith("Good evening")), "")
    seg_cam(30, "1. WELCOME", welcome)
    s.marker(t, "Season in Review", "Play the Season in Review.", "CYAN")
    seg_render(250, "Season in Review", "your finished Season in Review video")
    honors = [n.lstrip("• ") for n in notes if n.startswith("•")][:5]
    labels = ["CONSOLATION CHAMPION", "PRESIDENTS' TROPHY", "THIRD PLACE", "RUNNER-UP", "BLHA CHAMPION"]
    for i, lab in enumerate(labels):
        seg_cam(12, f"2. HONORS: {lab}", honors[i] if i < len(honors) else "")
        seg_render(8, "10 Awards Night", f"Honor - {lab}")
    rules = next((n for n in notes if n.startswith("Every franchise got one ballot")), "")
    seg_cam(30, "3. THE OWNERS' AWARDS", rules)
    seg_render(10, "10 Awards Night", "Owners' Awards - How the Vote Works")
    awards = ["BUST OF THE YEAR", "COMEBACK FRANCHISE", "WAIVER STEAL OF THE YEAR", "TRADE OF THE YEAR", "GM OF THE YEAR"]
    lines = [n.lstrip("• ") for n in notes if n.startswith("•") and ("Of The Year" in n.title() or "Comeback" in n)]
    for i, a in enumerate(awards):
        intro_line = next((l for l in lines if l.upper().startswith(a.split(" OF")[0])), "")
        seg_cam(14, f"AWARD: {a}", intro_line + " Then: \"The nominees for " + a.title() + " are...\"")
        seg_render(16, "10 Awards Night", f"Award - {a}")
    pot = next((n for n in notes if n.startswith("The Dynasty Pot now stands")), "")
    seg_cam(20, "4. THE DYNASTY POT", pot)
    seg_render(8, "10 Awards Night", "Dynasty Pot")
    nxt = next((n for n in notes if n.startswith("The Season Ledger goes up")), "")
    seg_cam(30, "5. WHAT'S NEXT", nxt)
    seg_render(10, "10 Awards Night", "What's Next")
    outro(s, t)
    t += 5
    s.seconds = t
    s.volumes["A2"] = -24.0
    s.loop("A2", 0, "bed-awards-loop")
    voice_track(s)
    return "BLHA Awards Night", [s]


BUILDERS = [hype_trailer, talking_head, screen_tutorial, explainer, week_in_60, monthly_awards, playoff_show,
            season_in_review, awards_night]


def build(out: Path, scripts_json: Path) -> dict[str, list[str]]:
    """Write the nine .otio files into `out` (the kit's FilmCraft folder); returns file -> sequences."""
    S = Scripts(scripts_json)
    SLATES.clear()
    made = {}
    for fn in BUILDERS:
        name, seqs = fn(S)
        doc = {"OTIO_SCHEMA": "SerializableCollection.1", "name": name, "metadata": {},
               "children": [q.otio() for q in seqs]}
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.otio").write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        made[name] = [q.name for q in seqs]
    return made
