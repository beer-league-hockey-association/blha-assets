"""Print kit: lay a printed piece out once, then write it two ways.

    <name>.idml   an InDesign Markup package that DesignCraft (or InDesign) opens with
                  live text, paragraph and character styles, swatches and embedded art
    <name>.pdf    a print proof with the fonts embedded

Both come from the same model: pages hold boxes (vector rectangles), pictures
and text frames, and every text frame holds styled paragraphs. The PDF is set
with a small line breaker that measures the real fonts, so a frame that would
overflow fails the build instead of being cut off in DesignCraft. The IDML asks
for the same behavior: single-line composer, no hyphenation, no kerning or
ligatures, and the first baseline one leading below the top of the frame.

Coordinates are points from the top-left corner of the page.
"""

from __future__ import annotations

import base64
import re
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "brand" / "fonts"

FACE_FILES = {
    ("Pixelify Sans", "Regular"): "pixelifysans/PixelifySans-Regular.ttf",
    ("Pixelify Sans", "SemiBold"): "pixelifysans/PixelifySans-SemiBold.ttf",
    ("Pixelify Sans", "Bold"): "pixelifysans/PixelifySans-Bold.ttf",
    ("Jersey 10", "Regular"): "jersey10/Jersey10-Regular.ttf",
    ("Silkscreen", "Regular"): "silkscreen/Silkscreen-Regular.ttf",
    ("Silkscreen", "Bold"): "silkscreen/Silkscreen-Bold.ttf",
}

# The league palette as print swatches (RGB).
COLORS = {
    "Charcoal": (43, 45, 49),
    "Ink": (14, 15, 18),
    "Gold": (255, 184, 28),
    "GoldDark": (138, 94, 0),
    "Cream": (244, 239, 228),
    "CreamDark": (226, 216, 194),
    "Muted": (107, 101, 89),
    "Mist": (184, 185, 190),
    "Slate": (91, 93, 99),
    "White": (252, 252, 252),
}
LIGHT_TEXT = {"Cream", "Mist", "White", "Gold"}

BREAK_AFTER = "-–—/"
SAFETY = 1.5   # points kept free under the last line, for font-metric differences between apps


# ------------------------------------------------------------------ the model
@dataclass(frozen=True)
class PStyle:
    name: str
    font: str = "Pixelify Sans"
    face: str = "Regular"
    size: float = 10.0
    leading: float = 14.0
    color: str = "Charcoal"
    tracking: float = 0.0          # thousandths of an em
    align: str = "left"            # left | center | right
    left: float = 0.0
    first: float = 0.0             # first-line indent (negative hangs a bullet or box)
    right: float = 0.0
    before: float = 0.0
    after: float = 0.0
    bullet: bool = False
    tabs: tuple = ()               # ((position, "left" | "right", leader), ...)


@dataclass(frozen=True)
class CStyle:
    name: str
    face: str | None = None
    font: str | None = None
    color: str | None = None
    size: float | None = None
    tracking: float | None = None


@dataclass
class Run:
    text: str
    cs: str | None = None


@dataclass
class Inline:
    """An object in the line of text: a picture (path) or an outlined box (stroke)."""
    w: float
    h: float
    path: Path | None = None
    stroke: str | None = None
    sw: float = 0.75


@dataclass
class Para:
    style: str
    runs: list
    marker: str | None = None      # "box": a checkbox hangs in the first-line indent


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    stroke: str | None = None
    sw: float = 0.0


@dataclass
class Pic:
    x: float
    y: float
    w: float
    h: float
    path: Path


@dataclass
class Frame:
    x: float
    y: float
    w: float
    h: float
    paras: list
    inset: tuple = (0.0, 0.0, 0.0, 0.0)   # top, left, bottom, right


@dataclass
class Page:
    items: list = field(default_factory=list)


@dataclass
class Doc:
    name: str
    title: str
    w: float
    h: float
    styles: dict
    cstyles: dict
    pages: list = field(default_factory=list)
    bleed: float = 9.0


# ------------------------------------------------------------------ fonts and measuring
@lru_cache(maxsize=None)
def rl_font(family: str, face: str) -> str:
    name = f"{family.replace(' ', '')}-{face}"
    pdfmetrics.registerFont(TTFont(name, str(FONTS / FACE_FILES[(family, face)])))
    return name


@dataclass
class Fmt:
    font: str
    size: float
    color: str
    tracking: float


def fmt_of(doc: Doc, ps: PStyle, cs_name: str | None) -> Fmt:
    cs = doc.cstyles.get(cs_name) if cs_name else None
    family = (cs.font if cs and cs.font else ps.font)
    face = (cs.face if cs and cs.face else ps.face)
    return Fmt(rl_font(family, face), cs.size if cs and cs.size else ps.size,
               cs.color if cs and cs.color else ps.color,
               cs.tracking if cs and cs.tracking is not None else ps.tracking)


def text_width(text: str, f: Fmt) -> float:
    return pdfmetrics.stringWidth(text, f.font, f.size) + len(text) * f.tracking / 1000 * f.size


@dataclass
class Tok:
    kind: str                   # text | space | tab | obj
    text: str = ""
    fmt: Fmt | None = None
    w: float = 0.0
    obj: Inline | None = None
    brk: bool = False           # a line may break before this token (after a hyphen or dash)


def tokens(doc: Doc, para: Para) -> list[Tok]:
    ps = doc.styles[para.style]
    out: list[Tok] = []
    for r in para.runs:
        if isinstance(r, Inline):
            out.append(Tok("obj", w=r.w, obj=r))
            continue
        f = fmt_of(doc, ps, r.cs)
        for piece in re.findall(r"\t| +|[^ \t]+", r.text):
            if piece == "\t":
                out.append(Tok("tab", fmt=f))
            elif piece.startswith(" "):
                out.append(Tok("space", piece, f, text_width(piece, f)))
            else:
                parts = re.findall(rf"[^{BREAK_AFTER}]*[{BREAK_AFTER}]+|[^{BREAK_AFTER}]+", piece)
                for i, p in enumerate(parts):
                    out.append(Tok("text", p, f, text_width(p, f), brk=i > 0))
    return out


def _rstrip(ts):
    while ts and ts[-1].kind == "space":
        ts = ts[:-1]
    return ts


def _lstrip(ts):
    while ts and ts[0].kind == "space":
        ts = ts[1:]
    return ts


def break_lines(toks: list[Tok], avail_first: float, avail_rest: float) -> list[list[Tok]]:
    lines, line, avail = [], [], avail_first
    for tok in toks:
        if tok.kind == "space":
            if line:
                line.append(tok)
            continue
        if line and sum(t.w for t in line) + tok.w > avail + 0.01:
            bp = None
            for i in range(len(line), 0, -1):
                nxt = line[i] if i < len(line) else tok
                if nxt.kind != "space" and (line[i - 1].kind == "space" or nxt.brk):
                    bp = i
                    break
            if bp:
                lines.append(_rstrip(line[:bp]))
                line, avail = _lstrip(line[bp:]), avail_rest
        line.append(tok)
    if line:
        lines.append(_rstrip(line))
    return lines


@dataclass
class Placed:
    baseline: float
    x: float                    # left edge of the line's text
    toks: list
    xs: list                    # x of each token
    leaders: list = field(default_factory=list)   # (x0, x1, fmt)
    marker: tuple | None = None # ("bullet" | "box", x, fmt)


class Overflow(Exception):
    pass


def set_frame(doc: Doc, fr: Frame, where: str = "") -> list[Placed]:
    """Lay the frame's paragraphs into lines; raise Overflow if they don't fit."""
    top, left, bottom, right = fr.inset
    x0, inner_w = fr.x + left, fr.w - left - right
    limit = fr.y + fr.h - bottom
    y = fr.y + top
    out: list[Placed] = []
    for pi, para in enumerate(fr.paras):
        ps = doc.styles[para.style]
        if pi:
            y += ps.before
        toks = tokens(doc, para)
        hang = ps.bullet or para.marker
        start_first = ps.left if hang else ps.left + ps.first
        if any(t.kind == "tab" for t in toks):
            lines = [toks]
        else:
            lines = break_lines(toks, inner_w - start_first - ps.right, inner_w - ps.left - ps.right)
        f0 = fmt_of(doc, ps, None)
        for li, line in enumerate(lines):
            y += ps.leading
            desc = -pdfmetrics.getDescent(f0.font, f0.size)
            if y + desc > limit - SAFETY:
                text = "".join(t.text for t in toks)[:60]
                raise Overflow(f"{where}: frame at ({fr.x:.0f},{fr.y:.0f}) overflows at paragraph {pi} ({para.style}): {text!r}")
            start = start_first if li == 0 else ps.left
            pl = Placed(y, x0 + start, line, [])
            if any(t.kind == "tab" for t in line):
                _place_tabs(ps, pl, x0, inner_w)
            else:
                width = sum(t.w for t in line)
                avail = inner_w - start - ps.right
                if width > avail + 0.5:
                    raise Overflow(f"{where}: a word is wider than its frame: {''.join(t.text for t in line)!r}")
                shift = {"left": 0, "center": (avail - width) / 2, "right": avail - width}[ps.align]
                x = x0 + start + shift
                for t in line:
                    pl.xs.append(x)
                    x += t.w
            if li == 0 and hang:
                pl.marker = ("bullet" if ps.bullet else para.marker, x0 + ps.left + ps.first, f0)
            out.append(pl)
        y += ps.after
    return out


def _place_tabs(ps: PStyle, pl: Placed, x0: float, inner_w: float) -> None:
    """One-line paragraph with tab stops: each column starts (or ends) at its stop."""
    cols, cur = [[]], None
    for t in pl.toks:
        if t.kind == "tab":
            cols.append([])
        else:
            cols[-1].append(t)
    stops = list(ps.tabs)
    if len(stops) < len(cols) - 1:
        raise Overflow(f"style {ps.name} has {len(stops)} tab stops for {len(cols) - 1} tabs")
    x = pl.x
    end_prev = x
    for ci, col in enumerate(cols):
        width = sum(t.w for t in col)
        if ci:
            pos, align, leader = stops[ci - 1]
            start = x0 + pos - (width if align == "right" else 0)
            if start < end_prev - 0.01:
                raise Overflow(f"tab column collides in {ps.name}: {''.join(t.text for t in col)!r}")
            if leader:
                pl.leaders.append((end_prev, start, col[0].fmt if col else None))
            x = start
        for t in col:
            pl.xs.append(x)
            x += t.w
        if x > x0 + inner_w + 0.5:
            raise Overflow(f"tab line runs past its frame in {ps.name}")
        end_prev = x
    pl.toks = [t for c in cols for t in c]


# ------------------------------------------------------------------ PDF proof
def _rgb(name):
    r, g, b = COLORS[name]
    return r / 255, g / 255, b / 255


def write_pdf(doc: Doc, path: Path) -> None:
    c = rl_canvas.Canvas(str(path), pagesize=(doc.w, doc.h), pageCompression=1)
    c.setTitle(doc.title)
    c.setAuthor("Beer League Hockey Association")
    c.setCreator("BLHA League Office")
    c.setSubject(doc.title)
    if hasattr(c, "setProducer"):
        c.setProducer("BLHA League Office")
    H = doc.h
    errors = []
    for pn, page in enumerate(doc.pages, 1):
        for it in page.items:
            if isinstance(it, Box):
                if it.fill:
                    c.setFillColorRGB(*_rgb(it.fill))
                if it.stroke:
                    c.setStrokeColorRGB(*_rgb(it.stroke))
                    c.setLineWidth(it.sw)
                c.rect(it.x, H - it.y - it.h, it.w, it.h, stroke=1 if it.stroke else 0, fill=1 if it.fill else 0)
            elif isinstance(it, Pic):
                c.drawImage(str(it.path), it.x, H - it.y - it.h, it.w, it.h, mask="auto")
            elif isinstance(it, Frame):
                try:
                    for pl in set_frame(doc, it, f"{doc.name} p{pn}"):
                        _draw_line(c, H, pl)
                except Overflow as e:
                    errors.append(str(e))
        c.showPage()
    c.save()
    if errors:
        raise Overflow("\n".join(errors))


def _draw_line(c, H, pl: Placed) -> None:
    by = H - pl.baseline
    if pl.marker:
        kind, mx, f = pl.marker
        if kind == "bullet":
            c.setFillColorRGB(*_rgb(f.color))
            c.setFont(f.font, f.size)
            c.drawString(mx, by, "•")
        else:
            s = f.size * 0.72
            c.setStrokeColorRGB(*_rgb(f.color))
            c.setLineWidth(0.75)
            c.rect(mx, by, s, s, stroke=1, fill=0)
    for x0, x1, f in pl.leaders:
        if not f:
            continue
        c.setFillColorRGB(*_rgb("Muted" if f.color not in LIGHT_TEXT else "Slate"))
        c.setFont(f.font, f.size)
        step = f.size * 0.5
        x = (int((x0 + f.size * 0.4) / step) + 1) * step
        while x + step < x1 - f.size * 0.3:
            c.drawString(x, by, ".")
            x += step
    for t, x in zip(pl.toks, pl.xs):
        if t.kind == "text":
            c.setFillColorRGB(*_rgb(t.fmt.color))
            c.setFont(t.fmt.font, t.fmt.size)
            c.drawString(x, by, t.text, charSpace=t.fmt.tracking / 1000 * t.fmt.size)
        elif t.kind == "obj":
            o = t.obj
            if o.path:
                c.drawImage(str(o.path), x, by, o.w, o.h, mask="auto")
            else:
                c.setStrokeColorRGB(*_rgb(o.stroke or "Charcoal"))
                c.setLineWidth(o.sw)
                c.rect(x, by, o.w, o.h, stroke=1, fill=0)


# ------------------------------------------------------------------ IDML package
NS = 'xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="16.0"'
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NO_CS = "CharacterStyle/$ID/[No character style]"
ALIGN = {"left": "LeftAlign", "center": "CenterAlign", "right": "RightAlign"}


def _a(v) -> str:
    return escape(str(v), {'"': "&quot;"})


def _n(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _path(w: float, h: float) -> str:
    pts = "".join(f'<PathPointType Anchor="{_n(x)} {_n(y)}" LeftDirection="{_n(x)} {_n(y)}" RightDirection="{_n(x)} {_n(y)}"/>'
                  for x, y in ((0.0, 0.0), (0.0, h), (w, h), (w, 0.0)))
    return f'<Properties><PathGeometry><GeometryPathType PathOpen="false"><PathPointArray>{pts}</PathPointArray></GeometryPathType></PathGeometry></Properties>'


class _Ids:
    def __init__(self):
        self.n = 0

    def __call__(self, p: str) -> str:
        self.n += 1
        return f"{p}{self.n}"


def _image(ids: _Ids, path: Path, w: float, h: float) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return (f'<Image Self="{ids("im")}" ItemTransform="1 0 0 1 0 0">'
            f'<Properties><Contents><![CDATA[{data}]]></Contents>'
            f'<GraphicBounds Left="0" Top="0" Right="{_n(w)}" Bottom="{_n(h)}"/></Properties>'
            f'<Link Self="{ids("ln")}" LinkResourceURI="file:{_a(path.name)}" '
            f'LinkResourceFormat="$ID/Portable Network Graphics (PNG)" StoredState="Embedded"/></Image>')


def _swatch(c: str | None) -> str:
    return f"Color/{c}" if c else "Swatch/None"


def _tablist(ps: PStyle) -> str:
    stops = list(ps.tabs)
    if ps.bullet and not stops:
        stops = [(ps.left, "left", "")]
    if not stops:
        return ""
    items = "".join(
        f'<ListItem type="record"><Alignment type="enumeration">{ALIGN[al]}</Alignment>'
        f'<AlignmentCharacter type="string">.</AlignmentCharacter><Leader type="string">{_a(ld)}</Leader>'
        f'<Position type="unit">{_n(float(pos))}</Position></ListItem>'
        for pos, al, ld in stops)
    return f'<TabList type="list">{items}</TabList>'


def _styles_xml(doc: Doc) -> str:
    cs = [f'<CharacterStyle Self="{NO_CS}" Name="$ID/[No character style]"/>']
    for s in doc.cstyles.values():
        attrs = []
        if s.face:
            attrs.append(f'FontStyle="{_a(s.face)}"')
        if s.color:
            attrs.append(f'FillColor="Color/{s.color}"')
        if s.size:
            attrs.append(f'PointSize="{_n(float(s.size))}"')
        if s.tracking is not None:
            attrs.append(f'Tracking="{_n(float(s.tracking))}"')
        props = '<BasedOn type="string">$ID/[No character style]</BasedOn>'
        if s.font:
            props += f'<AppliedFont type="string">{_a(s.font)}</AppliedFont>'
        cs.append(f'<CharacterStyle Self="CharacterStyle/{s.name}" Name="{s.name}" {" ".join(attrs)}><Properties>{props}</Properties></CharacterStyle>')

    common = ('Hyphenation="false" Composer="HL Single" KerningMethod="$ID/None" Ligatures="false" '
              'AutoLeading="120" FirstLineIndent="0" LeftIndent="0" RightIndent="0" SpaceBefore="0" SpaceAfter="0"')
    ps = [f'<ParagraphStyle Self="ParagraphStyle/$ID/[No paragraph style]" Name="$ID/[No paragraph style]" '
          f'PointSize="10" FontStyle="Regular" FillColor="Color/Charcoal" Justification="LeftAlign" {common}>'
          f'<Properties><AppliedFont type="string">Pixelify Sans</AppliedFont><Leading type="unit">14</Leading></Properties></ParagraphStyle>',
          '<ParagraphStyle Self="ParagraphStyle/$ID/NormalParagraphStyle" Name="$ID/NormalParagraphStyle">'
          '<Properties><BasedOn type="string">$ID/[No paragraph style]</BasedOn></Properties></ParagraphStyle>']
    for s in doc.styles.values():
        attrs = (f'PointSize="{_n(float(s.size))}" FontStyle="{_a(s.face)}" FillColor="Color/{s.color}" '
                 f'Tracking="{_n(float(s.tracking))}" Justification="{ALIGN[s.align]}" '
                 f'LeftIndent="{_n(float(s.left))}" FirstLineIndent="{_n(float(s.first))}" RightIndent="{_n(float(s.right))}" '
                 f'SpaceBefore="{_n(float(s.before))}" SpaceAfter="{_n(float(s.after))}" '
                 'Hyphenation="false" Composer="HL Single" KerningMethod="$ID/None" Ligatures="false"')
        props = (f'<BasedOn type="string">$ID/[No paragraph style]</BasedOn>'
                 f'<AppliedFont type="string">{_a(s.font)}</AppliedFont><Leading type="unit">{_n(float(s.leading))}</Leading>')
        if s.bullet:
            attrs += ' BulletsAndNumberingListType="BulletList" BulletsTextAfter="^t"'
            props += '<BulletChar BulletCharacterType="UnicodeOnly" BulletCharacterValue="8226"/>'
        props += _tablist(s)
        ps.append(f'<ParagraphStyle Self="ParagraphStyle/{s.name}" Name="{s.name}" {attrs}><Properties>{props}</Properties></ParagraphStyle>')

    obj = ('<ObjectStyle Self="ObjectStyle/$ID/[None]" Name="$ID/[None]"/>'
           '<ObjectStyle Self="ObjectStyle/$ID/[Normal Graphics Frame]" Name="$ID/[Normal Graphics Frame]"/>'
           '<ObjectStyle Self="ObjectStyle/$ID/[Normal Text Frame]" Name="$ID/[Normal Text Frame]"/>')
    return (f'{HEAD}<idPkg:Styles {NS}>\n<RootCharacterStyleGroup Self="rcs">{"".join(cs)}</RootCharacterStyleGroup>\n'
            f'<RootParagraphStyleGroup Self="rps">{"".join(ps)}</RootParagraphStyleGroup>\n'
            f'<RootObjectStyleGroup Self="ros">{obj}</RootObjectStyleGroup>\n</idPkg:Styles>')


def _graphic_xml() -> str:
    colors = ['<Color Self="Color/Black" Model="Process" Space="CMYK" ColorValue="0 0 0 100" Name="Black"/>',
              '<Color Self="Color/Paper" Model="Process" Space="CMYK" ColorValue="0 0 0 0" Name="Paper"/>',
              '<Color Self="Color/Registration" Model="Registration" Space="CMYK" ColorValue="100 100 100 100" Name="Registration"/>']
    colors += [f'<Color Self="Color/{k}" Model="Process" Space="RGB" ColorValue="{r} {g} {b}" Name="{k}"/>'
               for k, (r, g, b) in COLORS.items()]
    colors.append('<Swatch Self="Swatch/None" Name="None"/>')
    return f'{HEAD}<idPkg:Graphic {NS}>\n' + "\n".join(colors) + "\n</idPkg:Graphic>"


def _story_xml(doc: Doc, sid: str, fr: Frame, ids: _Ids) -> str:
    out = []
    for pi, para in enumerate(fr.paras):
        ps = doc.styles[para.style]
        ranges = []
        if para.marker == "box":
            s = ps.size * 0.72
            ranges.append(f'<CharacterStyleRange AppliedCharacterStyle="{NO_CS}">'
                          f'<Rectangle Self="{ids("ck")}" ContentType="Unassigned" StrokeWeight="0.75" '
                          f'StrokeColor="Color/{ps.color}" FillColor="Swatch/None" ItemTransform="1 0 0 1 0 0">{_path(s, s)}'
                          f'<AnchoredObjectSetting AnchoredPosition="InlinePosition" AnchorYoffset="0"/></Rectangle>'
                          f'<Content>\t</Content></CharacterStyleRange>')
        for r in para.runs:
            if isinstance(r, Inline):
                if r.path:
                    body = (f'<Rectangle Self="{ids("ir")}" ContentType="GraphicType" StrokeWeight="0" StrokeColor="Swatch/None" '
                            f'FillColor="Swatch/None" ItemTransform="1 0 0 1 0 0">{_path(r.w, r.h)}'
                            f'<AnchoredObjectSetting AnchoredPosition="InlinePosition" AnchorYoffset="0"/>'
                            f'{_image(ids, r.path, r.w, r.h)}</Rectangle>')
                else:
                    body = (f'<Rectangle Self="{ids("ib")}" ContentType="Unassigned" StrokeWeight="{_n(r.sw)}" '
                            f'StrokeColor="Color/{r.stroke or ps.color}" FillColor="Swatch/None" ItemTransform="1 0 0 1 0 0">'
                            f'{_path(r.w, r.h)}<AnchoredObjectSetting AnchoredPosition="InlinePosition" AnchorYoffset="0"/></Rectangle>')
                ranges.append(f'<CharacterStyleRange AppliedCharacterStyle="{NO_CS}">{body}</CharacterStyleRange>')
            else:
                cs = f"CharacterStyle/{r.cs}" if r.cs else NO_CS
                ranges.append(f'<CharacterStyleRange AppliedCharacterStyle="{cs}"><Content>{escape(r.text)}</Content></CharacterStyleRange>')
        if pi < len(fr.paras) - 1:
            ranges.append(f'<CharacterStyleRange AppliedCharacterStyle="{NO_CS}"><Br/></CharacterStyleRange>')
        out.append(f'<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/{para.style}">{"".join(ranges)}</ParagraphStyleRange>')
    return (f'{HEAD}<idPkg:Story {NS}>\n<Story Self="{sid}" AppliedTOCStyle="n" TrackChanges="false" StoryTitle="$ID/" AppliedNamedGrid="n">'
            f'<StoryPreference OpticalMarginAlignment="false" FrameType="TextFrameType" StoryOrientation="Horizontal" StoryDirection="LeftToRightDirection"/>'
            + "\n".join(out) + "</Story>\n</idPkg:Story>")


def write_idml(doc: Doc, path: Path) -> None:
    W, H = doc.w, doc.h
    ids = _Ids()
    files: dict[str, str] = {}
    spreads, stories = [], []
    for pn, page in enumerate(doc.pages, 1):
        oy = -H / 2
        items = []
        for it in page.items:
            xf = f'ItemTransform="1 0 0 1 {_n(float(it.x))} {_n(float(it.y + oy))}"'
            if isinstance(it, Box):
                items.append(f'<Rectangle Self="{ids("r")}" ItemLayer="L1" ContentType="Unassigned" AppliedObjectStyle="ObjectStyle/$ID/[None]" '
                             f'FillColor="{_swatch(it.fill)}" StrokeColor="{_swatch(it.stroke)}" StrokeWeight="{_n(float(it.sw))}" '
                             f'{xf}>{_path(it.w, it.h)}</Rectangle>')
            elif isinstance(it, Pic):
                items.append(f'<Rectangle Self="{ids("g")}" ItemLayer="L1" ContentType="GraphicType" AppliedObjectStyle="ObjectStyle/$ID/[None]" '
                             f'FillColor="Swatch/None" StrokeColor="Swatch/None" StrokeWeight="0" {xf}>{_path(it.w, it.h)}'
                             f'{_image(ids, it.path, it.w, it.h)}</Rectangle>')
            elif isinstance(it, Frame):
                sid = ids("u")
                stories.append(sid)
                files[f"Stories/Story_{sid}.xml"] = _story_xml(doc, sid, it, ids)
                t, l, b, r = it.inset
                inset = "".join(f'<ListItem type="unit">{_n(float(v))}</ListItem>' for v in (t, l, b, r))
                items.append(f'<TextFrame Self="{ids("tf")}" ParentStory="{sid}" PreviousTextFrame="n" NextTextFrame="n" ContentType="TextType" '
                             f'ItemLayer="L1" AppliedObjectStyle="ObjectStyle/$ID/[None]" FillColor="Swatch/None" StrokeColor="Swatch/None" '
                             f'StrokeWeight="0" {xf}>{_path(it.w, it.h)}'
                             f'<TextFramePreference TextColumnCount="1" FirstBaselineOffset="LeadingOffset" MinimumFirstBaselineOffset="0" '
                             f'AutoSizingType="Off" VerticalJustification="TopAlign" IgnoreWrap="true">'
                             f'<Properties><InsetSpacing type="list">{inset}</InsetSpacing></Properties></TextFramePreference></TextFrame>')
        spid = f"sp{pn}"
        spreads.append(spid)
        files[f"Spreads/Spread_{spid}.xml"] = (
            f'{HEAD}<idPkg:Spread {NS}>\n<Spread Self="{spid}" PageCount="1" BindingLocation="0" ShowMasterItems="true" ItemTransform="1 0 0 1 0 0">'
            f'<Page Self="pg{pn}" Name="{pn}" AppliedMaster="m1" GeometricBounds="0 0 {_n(float(H))} {_n(float(W))}" '
            f'ItemTransform="1 0 0 1 0 {_n(float(oy))}"/>\n' + "\n".join(items) + "\n</Spread>\n</idPkg:Spread>")

    files["Resources/Graphic.xml"] = _graphic_xml()
    files["Resources/Styles.xml"] = _styles_xml(doc)
    b = _n(float(doc.bleed))
    files["Resources/Preferences.xml"] = (
        f'{HEAD}<idPkg:Preferences {NS}>\n<DocumentPreference PageWidth="{_n(float(W))}" PageHeight="{_n(float(H))}" '
        f'PagesPerDocument="{len(doc.pages)}" FacingPages="false" DocumentBleedUniformSize="true" DocumentBleedTopOffset="{b}" '
        f'DocumentBleedBottomOffset="{b}" DocumentBleedInsideOrLeftOffset="{b}" DocumentBleedOutsideOrRightOffset="{b}"/>\n'
        f'<MarginPreference ColumnCount="1" ColumnGutter="12" Top="36" Bottom="36" Left="36" Right="36"/>\n</idPkg:Preferences>')
    files["MasterSpreads/MasterSpread_m1.xml"] = (
        f'{HEAD}<idPkg:MasterSpread {NS}>\n<MasterSpread Self="m1" Name="A-Parent" NamePrefix="A" BaseName="Parent" PageCount="1" ItemTransform="1 0 0 1 0 0">'
        f'<Page Self="mp1" Name="A" GeometricBounds="0 0 {_n(float(H))} {_n(float(W))}" ItemTransform="1 0 0 1 0 {_n(-H / 2)}"/>'
        f'</MasterSpread>\n</idPkg:MasterSpread>')
    dm = [f'{HEAD}<?aid style="50" type="document" readerVersion="6.0" featureSet="257" product="16.0(1)" ?>',
          f'<Document {NS} Self="d" Name="{_a(doc.name)}.indd" StoryList="{" ".join(stories)}">',
          '<idPkg:Graphic src="Resources/Graphic.xml"/>', '<idPkg:Styles src="Resources/Styles.xml"/>',
          '<idPkg:Preferences src="Resources/Preferences.xml"/>',
          '<Layer Self="L1" Name="Layer 1" Visible="true" Locked="false" Printable="true"/>',
          '<idPkg:MasterSpread src="MasterSpreads/MasterSpread_m1.xml"/>']
    dm += [f'<idPkg:Spread src="Spreads/Spread_{s}.xml"/>' for s in spreads]
    dm.append(f'<Section Self="sec1" Length="{len(doc.pages)}" Name="" ContinueNumbering="false" IncludeSectionPrefix="false" '
              f'PageNumberStart="1" Marker="" PageStart="pg1" SectionPrefix=""/>')
    dm += [f'<idPkg:Story src="Stories/Story_{s}.xml"/>' for s in stories]
    dm.append("</Document>")
    files["designmap.xml"] = "\n".join(dm)
    files["META-INF/container.xml"] = (
        f'{HEAD}<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="designmap.xml" media-type="text/xml"/></rootfiles></container>')

    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.adobe.indesign-idml-package", compress_type=zipfile.ZIP_STORED)
        for name in ["designmap.xml", "META-INF/container.xml", "Resources/Graphic.xml", "Resources/Styles.xml",
                     "Resources/Preferences.xml", "MasterSpreads/MasterSpread_m1.xml"]:
            z.writestr(name, files.pop(name), compress_type=zipfile.ZIP_DEFLATED)
        for name in sorted(files):
            z.writestr(name, files[name], compress_type=zipfile.ZIP_DEFLATED)


# ------------------------------------------------------------------ markup
_MARK = re.compile(r"\*\*(.+?)\*\*|\{(\w+):([^}]*)\}|\{(\w+)\}")


def parse(doc: Doc, style: str, text: str, chan=None, emoji=None) -> list:
    """`**bold**` (Strong, or StrongLight on light text), `{Style:text}` (a character style), `{ch:slug}` (a channel),
    `{em:emoji}` (an emoji) and `{box}` (an outlined box in the line)."""
    ps = doc.styles[style]
    runs, pos = [], 0
    for m in _MARK.finditer(text):
        if m.start() > pos:
            runs.append(Run(text[pos:m.start()]))
        if m.group(1) is not None:
            light = ps.color in LIGHT_TEXT and "StrongLight" in doc.cstyles
            runs.append(Run(m.group(1), "StrongLight" if light else "Strong"))
        elif m.group(2) == "ch":
            runs.extend(chan(m.group(3), ps))
        elif m.group(2) == "em":
            runs.append(emoji(m.group(3), ps))
        elif m.group(2):
            if m.group(2) not in doc.cstyles:
                raise KeyError(f"unknown character style {m.group(2)}")
            runs.append(Run(m.group(3), m.group(2)))
        elif m.group(4) == "box":
            s = ps.size * 0.72
            runs.append(Inline(s, s, stroke=ps.color))
        pos = m.end()
    if pos < len(text):
        runs.append(Run(text[pos:]))
    return runs


def check_idml(path: Path) -> dict:
    """Re-read a package: every part parses, every reference resolves."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert names[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        trees = {n: ET.fromstring(z.read(n)) for n in names if n.endswith(".xml")}
    styles = trees["Resources/Styles.xml"]
    pstyles = {e.get("Self") for e in styles.iter("ParagraphStyle")}
    cstyles = {e.get("Self") for e in styles.iter("CharacterStyle")}
    colors = {e.get("Self") for e in trees["Resources/Graphic.xml"]} | {"Swatch/None"}
    story_ids = {e.get("Self") for n, t in trees.items() if n.startswith("Stories/") for e in t.iter("Story")}
    stats = {"pages": 0, "frames": 0, "images": 0, "paragraphs": 0}
    for n, t in trees.items():
        for e in t.iter():
            for k in ("FillColor", "StrokeColor"):
                if e.get(k):
                    assert e.get(k) in colors, (n, k, e.get(k))
            if e.get("AppliedParagraphStyle"):
                assert e.get("AppliedParagraphStyle") in pstyles, (n, e.get("AppliedParagraphStyle"))
                stats["paragraphs"] += 1
            if e.get("AppliedCharacterStyle"):
                assert e.get("AppliedCharacterStyle") in cstyles, (n, e.get("AppliedCharacterStyle"))
            if e.tag == "TextFrame":
                assert e.get("ParentStory") in story_ids, (n, e.get("ParentStory"))
                stats["frames"] += 1
            if e.tag == "Image":
                stats["images"] += 1
            if e.tag == "Page" and n.startswith("Spreads/"):
                stats["pages"] += 1
    return stats


def png_with_dpi(img: Image.Image, path: Path, width_pt: float) -> Path:
    """Save art so its stated resolution places it at exactly width_pt points."""
    dpi = img.width / (width_pt / 72)
    img.save(path, dpi=(dpi, dpi), optimize=True)
    return path
