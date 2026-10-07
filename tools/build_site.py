#!/usr/bin/env python3
"""Build the BLHA league history website into site/.

A standalone static site (HTML and CSS, no JavaScript) in the league's 8-bit
arcade look: every page, image, sprite and font is served from the site's own
address and nothing points anywhere else. It reads the league archive (the
automation-state branch's archive/ folder), automation/history/history.yaml,
automation/league.yaml (history_site) and the Constitution
(constitution/BLHA_Constitution.md, CHANGELOG.md and the PDF), and builds
cleanly from an empty archive. The BLHA History Site workflow publishes the
folder to Cloudflare Pages.

Layout: a scoreboard header with the full menu and a "you are here" marker,
breadcrumbs on inner pages, alternating ice and arena bands, pixel windows for
each module, and the rafters with the ice resurfacer on the home page. Team
colors appear only on each franchise's pixel jersey and the stripe under its
page header; everything else stays in league colors.

Type: three pixel fonts. Jersey 10 for display, Silkscreen for labels, and
Pixelify Sans for body copy and the Constitution.

Pages use clean addresses (/seasons/2027/, /franchises/rink-rats/), so they
are served from the root of the site's domain.

Usage: python tools/build_site.py [--archive PATH] [--out site]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))

from blha.league import load_league  # noqa: E402
from history.context import LeagueHistory, natural, ordinal  # noqa: E402
from history.profiles import DEFAULT_COLORS, dynasty_summary, franchise_profiles  # noqa: E402
from history.records import AWARDS, Records, money  # noqa: E402
from history.rivals import HeadToHead, declared_rivals  # noqa: E402
from history.store import Archive, default_dir  # noqa: E402
from history.trades import Node, trade_trees  # noqa: E402

CONSTITUTION = ROOT / "constitution" / "BLHA_Constitution.md"
CHANGELOG = ROOT / "constitution" / "CHANGELOG.md"
CONSTITUTION_PDF = ROOT / "constitution" / "BLHA_Constitution.pdf"
FONT_DIR = ROOT / "brand" / "fonts"
KIT = ROOT / "brand" / "kit"
# (output name, source, width to shrink to)
IMAGES = [
    ("favicon.png", KIT / "02_avatars_icons" / "blha-favicon-256.png", 64),
    ("apple-touch-icon.png", KIT / "01_logos" / "blha-b-icon-charcoal-1024.png", 180),
]
# served name -> source (subset WOFF files built from the OFL fonts in brand/fonts)
FONT_FILES = {
    "jersey10.woff": FONT_DIR / "jersey10" / "jersey10.woff",
    "silkscreen.woff": FONT_DIR / "silkscreen" / "silkscreen.woff",
    "silkscreen-bold.woff": FONT_DIR / "silkscreen" / "silkscreen-bold.woff",
    "pixelifysans.woff": FONT_DIR / "pixelifysans" / "pixelifysans.woff",
}
SITE_NAME = "BLHA History"
LEAGUE_NAME = "Beer League Hockey Association"
DESCRIPTION = ("The permanent record of the Beer League Hockey Association: champions, standings, "
               "head-to-head records, trades, drafts and the Constitution.")
SECTIONS = [
    ("seasons", "Seasons"),
    ("franchises", "Franchises"),
    ("head-to-head", "Head-to-head"),
    ("trades", "Trades"),
    ("drafts", "Drafts"),
    ("records", "Records"),
    ("constitution", "Constitution"),
]
INK, BOARDS, GOLD, CREAM = "#2B2D31", "#2B2D31", "#FFB81C", "#F4EFE4"
BLACK = "#0E0F12"
REGULAR_WEEKS = 22   # Constitution 5.x: 22-week regular season
PLAYOFF_TEAMS = 6    # Constitution XVI: six teams, the top two get byes

# --- pixel sprites: one character per pixel, "." is transparent -----------------------
PAL = {"K": "#0E0F12", "W": "#FCFCFC", "G": "#FFB81C", "D": "#C68A00", "S": "#9AA1A9", "B": "#2457C5",
       "R": "#C8241F", "L": "#7FB7F0", "C": "#F4EFE4"}
SPRITES: dict[str, list[str]] = {
    "b": ["KKKKKKKKKK....", "KGGGGGGGGGK...", "KGWWWWWWWWGK..", "KGWWKKKKWWWGK.", "KGWWKGGKWWWGK.", "KGWWKKKKWWGK..",
          "KGWWWWWWWWGK..", "KGWWWWWWWWWGK.", "KGWWKKKKKWWWGK", "KGWWKGGGKWWWGK", "KGWWKKKKKWWWGK", "KGWWWWWWWWWWGK",
          "KGGGGGGGGGGGK.", "KKKKKKKKKKKK.."],
    "cup": ["..KKKKKKKK..", "KKGGGGGGGGKK", "KGKGGGGGWGKG", "KGKGGGGGWGKG", ".KKGGGGGGKK.", "...KGGGGK...", "....KGGK....",
            ".....KK.....", "....KGGK....", "...KKKKKK...", "...KDDDDK...", "...KKKKKK..."],
    "coin": ["..KKK..", ".KGGGK.", "KGGWGGK", "KGGWGGK", "KGGWGGK", ".KGGGK.", "..KKK.."],
    "coinoff": ["..SSS..", ".S...S.", "S.....S", "S.....S", "S.....S", ".S...S.", "..SSS.."],
    "jersey": ["......KKKKKK......", "...KKKPPWWPPKKK...", "..KPPPPPPPPPPPPK..", ".KPPPPPPPPPPPPPPK.", "KPPPPPPPPPPPPPPPPK",
               "KPPPKPPPPPPPPKPPPK", "KSSSKPPPPPPPPKSSSK", "KPPPKPPPPPPPPKPPPK", "KSSSKPPPPPPPPKSSSK", "KPPPKPPPPPPPPKPPPK",
               ".KKKKSSSSSSSSKKKK.", "....KPPPPPPPPK....", "....KSSSSSSSSK....", "....KKKKKKKKKK...."],
    "calendar": ["KKKKKKKKKKKK", "KRRRRRRRRRRK", "KWWWWWWWWWWK", "KWKWKWKWKWWK", "KWWWWWWWWWWK", "KWKWKWKWKWWK", "KWWWWWWWWWWK",
                 "KKKKKKKKKKKK"],
    "sticks": ["K.........K", "GK.......KG", ".GK.....KG.", "..GK...KG..", "...GK.KG...", "....GKG....", "...GK.KG...",
               "..GK...KG..", ".GK.....KG.", "GGK.....KGG", "GG.......GG"],
    "scroll": [".KKKKKKKKK.", "KCCCCCCCCCK", "KCKKKKKKKCK", "KCCCCCCCCCK", "KCKKKKKKCCK", "KCCCCCCCCCK", "KCKKKKKKKCK",
               "KCCCCCCCCCK", ".KKKKKKKKK."],
    "swap": ["...K.......", "..KGK......", ".KGGGK.....", "KGGGGGK....", "..KGK..KGK.", "..KGK..KGK.", ".......KGK.",
             "....KGGGGGK", ".....KGGGK.", "......KGK..", ".......K..."],
    "net": ["KKKKKKKKKKKK", "KWKWKWKWKWWK", "KKWKWKWKWKKK", "KWKWKWKWKWWK", "KKWKWKWKWKKK", "KWKWKWKWKWWK", "KRRRRRRRRRRK"],
}
# The ice resurfacer (56 x 28, drives to the right): frame 0 wheels straight, frame 1 body bobbed up a pixel.
RESURFACER_PAL = {**PAL, "B": "#2F6FDB", "N": "#1F4FA8", "M": "#3A3D42"}
RESURFACER = (
    [".......................KKKKKKKNNNNNNNNKKKK..............",
     "............KKKK......KBBBBBBBBBBBBBBBBBBBKKK...........",
     "...........KGGGGKK...KBBBBBBBBBBBBBBBBBBBBBBBK..........",
     ".........KKKGGGGGGK.KBBBBBBBBBBBBBBBBBBBBBBBBBK.........",
     "........KSSSSCCKKK..KSSSSSSSSSSSSSSSSSSSSSSSSSK.........",
     "........KSMKKCCCK..KKWWWWWWWWWWWWWWWWWWWWWWWWWK.........",
     "........KSMKBBWBKKKKSKWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMKBBBBBBBKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMKBBBBKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWWK........",
     "........KSSSSSSSSSSSSWWWWWWWWWWWWWWWWWWWWWWWWWWWK.......",
     ".........KKWWWWWWWWWWWWWWWKKWWKWWWKWKWWKWWWWWWWWWK......",
     "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWKKK...",
     "..........KWWWWWWWWWWWWWWWKKWWKWWWKKKWKKKWWWWWWWWWWGCK..",
     "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWWGGK..",
     "..........KWWWWWWWWWWWWWWWKKWWKKKWKWKWKWKWWWWWWSSSSWWK..",
     "...KKKKKKKKWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWK..",
     "..KSSSSSSGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGKKKKKKKKKK..",
     "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...",
     "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...",
     "..KSSSSSSBBBBKKKBBBBBBKKKBBBBBBBBBBBBBKKKBBBBBBKKKBBK...",
     "..KSMMMMMBBBKKKKKBBBBKKKKKBBBBBBBBBBBKKKKKBBBBKKKKKBK...",
     "..KSSSSSSKKKKKSKKKKKKKKSKKKKKKKKKKKKKKKSKKKKKKKKSKKKK...",
     "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK....",
     "CCCCCCK.....KKKKK....KKKKK...........KKKKK....KKKKK.....",
     "KCCCCCCK.....KKK......KKK.............KKK......KKK......",
     ".KKKKKK................................................."],
    ["..............................KKKKKKKK..................",
     ".......................KKKKKKKNNNNNNNNKKKK..............",
     "............KKKK......KBBBBBBBBBBBBBBBBBBBKKK...........",
     "...........KGGGGKK...KBBBBBBBBBBBBBBBBBBBBBBBK..........",
     ".........KKKGGGGGGK.KBBBBBBBBBBBBBBBBBBBBBBBBBK.........",
     "........KSSSSCCKKK..KSSSSSSSSSSSSSSSSSSSSSSSSSK.........",
     "........KSMKKCCCK..KKWWWWWWWWWWWWWWWWWWWWWWWWWK.........",
     "........KSMKBBWBKKKKSKWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMKBBBBBBBKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMKBBBBKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWK.........",
     "........KSMMMMKKKKKKKWWLWWLWWLWWLWWLWWLWWLWWLWWK........",
     "........KSSSSSSSSSSSSWWWWWWWWWWWWWWWWWWWWWWWWWWWK.......",
     ".........KKWWWWWWWWWWWWWWWKKWWKWWWKWKWWKWWWWWWWWWK......",
     "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWKKK...",
     "..........KWWWWWWWWWWWWWWWKKWWKWWWKKKWKKKWWWWWWWWWWGCK..",
     "..........KWWWWWWWWWWWWWWWKWKWKWWWKWKWKWKWWWWWWWWWWGGK..",
     "..........KWWWWWWWWWWWWWWWKKWWKKKWKWKWKWKWWWWWWSSSSWWK..",
     "...KKKKKKKKWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWK..",
     "..KSSSSSSGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGKKKKKKKKKK..",
     "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...",
     "..KSMMMMMBBBBKKKBBBBBBKKKBBBBBBBBBBBBBKKKBBBBBBKKKBBK...",
     "..KSSSSSSBBBKKKKKBBBBKKKKKBBBBBBBBBBBKKKKKBBBBKKKKKBK...",
     "..KSMMMMMBBBKSKSKBBBBKSKSKBBBBBBBBBBBKSKSKBBBBKSKSKBK...",
     ".KKSSSSSSKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK...",
     "KCCCCCCKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK....",
     "CCCCCCK......KKK......KKK.............KKK......KKK......",
     "KKKKKK.................................................."],
)
LEAGUE_JERSEY = (GOLD, BLACK)   # the league's own jersey, used where no franchise is meant


def sprite_svg(rows: list[str], pal: dict[str, str]) -> str:
    """An SVG with one 1x1 square per sprite pixel (merged into runs), drawn with crisp edges at any whole-number size."""
    w, h = max(len(r) for r in rows), len(rows)
    paths: dict[str, list[str]] = {}
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            ch = row[x]
            end = x
            while end < len(row) and row[end] == ch:
                end += 1
            if ch in pal:
                paths.setdefault(pal[ch], []).append(f"M{x} {y}h{end - x}v1h-{end - x}z")
            x = end
    body = "".join(f'<path fill="{color}" d="{"".join(d)}"/>' for color, d in paths.items())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'shape-rendering="crispEdges">{body}</svg>\n')


# --- small helpers -----------------------------------------------------------------

def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "section"


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def long_date(when: datetime) -> str:
    return f"{when.strftime('%B')} {when.day}, {when.year}"


def short_date(when: datetime) -> str:
    return f"{when.strftime('%b')} {when.day}"


def score(value: float) -> str:
    return f"{value:.2f}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def ink_for(hex_color: str) -> str:
    """Charcoal or cream text, whichever reads better on this background."""
    h = hex_color.lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return INK
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return INK if lum > 0.28 else CREAM


def safe_color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"#[0-9A-Fa-f]{6}", text) else default


def table(head: list[str], rows: list[list[str]], *, num: Iterable[int] = (), cls: str = "", caption: str = "",
          row_cls: list[str] | None = None) -> str:
    """Rows are already-escaped HTML cells."""
    num = set(num)
    th = "".join(f'<th scope="col" class="num">{esc(h)}</th>' if i in num else f'<th scope="col">{esc(h)}</th>'
                 for i, h in enumerate(head))
    body = ""
    for n, r in enumerate(rows):
        rc = row_cls[n] if row_cls and n < len(row_cls) and row_cls[n] else ""
        cells = "".join(f'<td class="num">{c}</td>' if i in num else f"<td>{c}</td>" for i, c in enumerate(r))
        body += (f'<tr class="{rc}">' if rc else "<tr>") + cells + "</tr>"
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    cls_attr = f' class="{cls}"' if cls else ""
    return f'<div class="scroll"><table{cls_attr}>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def empty(text: str) -> str:
    return f'<p class="empty">{esc(text)}</p>'


def window(title: str, body: str, *, small: str = "", foot: str = "", ident: str = "", level: int = 2,
           cls: str = "") -> str:
    """A pixel window: black title bar, paper body, optional footer link."""
    id_attr = f' id="{ident}"' if ident else ""
    small_html = f"<small>{esc(small)}</small>" if small else ""
    foot_html = f'<div class="foot">{foot}</div>' if foot else ""
    extra = f" {cls}" if cls else ""
    return (f'<section class="win{extra}"{id_attr}><h{level}><span>{esc(title)}</span>{small_html}</h{level}>'
            f'<div class="body">{body}</div>{foot_html}</section>')


def sec_head(title: str, ident: str, more: str = "") -> str:
    return f'<div class="sec-head"><h2 id="{ident}">{esc(title)}</h2>{more}</div>'


# --- markdown (the Constitution and its changelog) ---------------------------------

def inline(text: str) -> str:
    text = esc(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", text)


def flush_block(out: list[str], para: list[str], items: list[str]) -> None:
    """Close an open paragraph or list (each list is emptied after it is written)."""
    if para:
        out.append("<p>" + "<br>".join(para) + "</p>")
        para.clear()
    if items:
        out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
        items.clear()


def markdown(text: str, *, shift: int = 0) -> tuple[str, list[tuple[str, str]]]:
    """Small Markdown subset: headings, paragraphs, lists (- or •), blockquotes, tables. Returns (html, h2 anchors)."""
    out: list[str] = []
    anchors: list[tuple[str, str]] = []
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    for block in blocks:
        lines = block.splitlines()
        first = lines[0]
        m = re.match(r"^(#{1,4})\s+(.*)$", first)
        if m and len(lines) == 1:
            level = min(len(m.group(1)) + shift, 6)
            ident = slug(m.group(2))
            if level == 2 + shift:
                anchors.append((ident, m.group(2)))
            out.append(f'<h{level} id="{ident}">{inline(m.group(2))}</h{level}>')
            continue
        if all(line.startswith(">") for line in lines):
            inner = "<br>".join(inline(line.lstrip(">").strip()) for line in lines)
            out.append(f"<blockquote>{inner}</blockquote>")
            continue
        if first.startswith("|") and len(lines) >= 2 and re.match(r"^\|[\s:|-]+\|$", lines[1]):
            cells = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]  # noqa: E731
            head = "".join(f"<th>{inline(c)}</th>" for c in cells(first))
            rows = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>" for r in lines[2:])
            out.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
            continue
        para: list[str] = []
        items: list[str] = []
        for line in lines:
            item = re.match(r"^\s*(?:[-•])\s+(.*)$", line)
            if item:
                flush_block(out, para, [])
                items.append(inline(item.group(1)))
            else:
                flush_block(out, [], items)
                para.append(inline(line.strip()))
        flush_block(out, para, items)
    return "\n".join(out), anchors


ARTICLE = re.compile(r"^Article ([IVXLC]+) — (.*)$")


def constitution_html() -> tuple[str, list[tuple[str, str, str]]]:
    """The Constitution as arcade-styled HTML: numbered article headings, section chips, and the Quick
    Reference in a panel. Returns (html, [(anchor, "Article I" or "", title)])."""
    text, anchors = markdown(CONSTITUTION.read_text(encoding="utf-8"), shift=0)
    text = re.sub(r"<h1[^>]*>.*?</h1>", "", text, count=1)
    items = []
    for ident, title in anchors:
        m = ARTICLE.match(title)
        number, name = (f"Article {m.group(1)}", m.group(2)) if m else ("", title)
        items.append((ident, number, name))
        label = f'<span class="art-no">{esc(number)}</span>' if number else ""
        text = re.sub(rf'<h2 id="{re.escape(ident)}">.*?</h2>',
                      lambda _m, i=ident, lab=label, n=name: f'<h2 id="{i}">{lab}<span class="art-title">{inline(n)}</span></h2>',
                      text, count=1)
    text = re.sub(r"<p><strong>(\d+\.\d+)</strong>", r'<p><strong class="sec-no">\1</strong>', text)
    text = re.sub(r'(<h2 id="quick-reference">.*?</h2>)\n(<ul>.*?</ul>)', r'\1\n<div class="qr">\2</div>', text, count=1)
    return text, items


# --- stylesheet --------------------------------------------------------------------
# @@name@@ marks an asset address filled in when the stylesheet is written.

CSS = """
@font-face{font-family:"Jersey 10";src:url("@@fonts/jersey10.woff@@") format("woff");font-display:swap}
@font-face{font-family:"Silkscreen";src:url("@@fonts/silkscreen.woff@@") format("woff");font-weight:400;font-display:swap}
@font-face{font-family:"Silkscreen";src:url("@@fonts/silkscreen-bold.woff@@") format("woff");font-weight:700;font-display:swap}
@font-face{font-family:"Pixelify Sans";src:url("@@fonts/pixelifysans.woff@@") format("woff");font-weight:400 700;font-display:swap}
:root{--black:#0E0F12;--char:#2B2D31;--char-2:#3A3D43;--gold:#FFB81C;--gold-lt:#FFD76A;--gold-dk:#8A5E00;--cream:#F4EFE4;
--ice:#EEF5FA;--ice-2:#E0ECF5;--paper:#FCFCFC;--line:#C3CFDA;--ink:#14161A;--muted:#4C5563;--soft:#B9BEC6;
--blue:#2457C5;--red:#C8241F;--steel:#9AA1A9;--led:#FF6A4A;
--display:"Jersey 10","Silkscreen",ui-monospace,monospace;--label:"Silkscreen",ui-monospace,monospace;
--text:"Pixelify Sans",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;--u:8px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--ice);color:var(--ink);font-family:var(--text);font-size:1.0625rem;line-height:1.55;font-variant-ligatures:none}
img{max-width:100%}
.px{display:block;flex:none}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--blue);text-decoration-thickness:2px;text-underline-offset:3px}
a:hover{background:var(--gold);color:var(--ink);text-decoration-color:var(--ink)}
:focus-visible{outline:3px solid var(--ink);outline-offset:2px;box-shadow:0 0 0 6px var(--gold)}
.skip{position:absolute;left:-9999px;top:8px;background:var(--gold);color:var(--ink);padding:8px 12px;z-index:9;font-family:var(--label);font-size:.8rem}
.skip:focus{left:16px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.in{max-width:1120px;margin:0 auto;padding-inline:calc(var(--u)*3)}
p{margin:0 0 1rem}
b,strong{font-weight:600}
.muted{color:var(--muted)}
.note{color:var(--muted);font-size:.95rem;max-width:68ch;margin:0 0 1rem}
.lede{max-width:62ch}

/* scoreboard header */
.sb{background:var(--black);color:var(--paper);border-bottom:var(--u) solid var(--gold)}
.sb-top{display:flex;flex-wrap:wrap;align-items:center;gap:var(--u) calc(var(--u)*3);padding-block:calc(var(--u)*2) var(--u)}
.logo{display:flex;align-items:center;gap:12px;text-decoration:none;color:var(--paper)}
.logo:hover{background:none;color:var(--paper)}
.logo b{display:block;font-family:var(--display);font-weight:400;font-size:2.6rem;line-height:.8;color:var(--gold)}
.logo small{display:block;font-family:var(--label);font-size:.68rem;color:var(--soft);letter-spacing:.03em;margin-top:6px}
.status{margin:0 0 0 auto;display:flex;gap:calc(var(--u)*2);align-items:flex-end}
.led{font-family:var(--label);font-size:.68rem;color:var(--soft);text-transform:uppercase;line-height:1.2}
.led dd{margin:0;font-family:var(--display);font-size:2rem;line-height:.85;color:var(--led);letter-spacing:.05em}
.menu ul{display:flex;flex-wrap:wrap;gap:0 4px;list-style:none;margin:0;padding:0}
.menu a{display:flex;align-items:center;min-height:44px;padding:0 12px 0 22px;position:relative;color:var(--paper);text-decoration:none;font-family:var(--label);font-size:.8rem;text-transform:uppercase;letter-spacing:.02em}
.menu a::before{content:"";position:absolute;left:8px;top:50%;margin-top:-5px;border:5px solid transparent;border-left:7px solid var(--gold);opacity:0}
.menu a:hover{background:var(--char);color:var(--paper)}
.menu a:hover::before{opacity:.6}
.menu a[aria-current]{background:var(--gold);color:var(--black)}
.menu a[aria-current]::before{opacity:1;border-left-color:var(--black)}

/* breadcrumbs and page heads */
.crumbs{background:var(--ice-2);border-bottom:2px solid var(--line);font-size:.95rem}
.crumbs ol{display:flex;flex-wrap:wrap;gap:4px 10px;list-style:none;margin:0;padding:10px 0}
.crumbs li+li::before{content:"\\25B8";margin-right:10px;color:var(--muted)}
.crumbs [aria-current]{color:var(--muted)}
.head{padding-block:calc(var(--u)*4) calc(var(--u)*2);display:flex;flex-wrap:wrap;align-items:flex-end;gap:calc(var(--u)*2) calc(var(--u)*4)}
.head h1,.intro h1,.missing h1{font-family:var(--display);font-weight:400;font-size:clamp(3rem,7vw,4.5rem);line-height:.8;margin:0;text-shadow:4px 4px 0 var(--gold)}
.head .sub{margin:12px 0 0;color:var(--muted);max-width:62ch}
.pager{margin-left:auto;display:flex;flex-wrap:wrap;gap:8px}
.btn{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 14px;background:var(--paper);color:var(--ink);text-decoration:none;font-family:var(--label);font-size:.75rem;text-transform:uppercase;box-shadow:0 -3px 0 var(--ink),0 3px 0 var(--ink),-3px 0 0 var(--ink),3px 0 0 var(--ink);margin:3px}
.btn:hover{background:var(--gold)}
.btn.off{color:var(--steel);box-shadow:0 -3px 0 var(--line),0 3px 0 var(--line),-3px 0 0 var(--line),3px 0 0 var(--line)}
.jump{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 calc(var(--u)*3);padding:0;list-style:none;font-family:var(--label);font-size:.75rem;text-transform:uppercase}
.jump a{display:inline-block;padding:8px 0}

/* bands give the page its pace: ice, then the dark arena */
.band{padding-block:calc(var(--u)*5)}
.band.tight{padding-block:calc(var(--u)*3)}
.band.flush{padding-top:0}
.band.dark{background:var(--char);color:var(--paper)}
.band.dark a{text-decoration-color:var(--gold)}
.sec-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px 16px;margin:0 0 calc(var(--u)*2)}
.sec-head h2{font-family:var(--display);font-weight:400;font-size:2.4rem;line-height:.8;margin:0}
.sec-head .more{font-family:var(--label);font-size:.75rem;text-transform:uppercase}

/* windows */
.win{background:var(--paper);margin:4px;box-shadow:0 -4px 0 var(--ink),0 4px 0 var(--ink),-4px 0 0 var(--ink),4px 0 0 var(--ink),8px 8px 0 0 rgba(36,87,197,.28);min-width:0;color:var(--ink);scroll-margin-top:16px}
.win>h2,.win>h3{margin:0;background:var(--ink);color:var(--gold);font-family:var(--label);font-weight:700;font-size:.82rem;text-transform:uppercase;letter-spacing:.02em;padding:10px 16px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 12px}
.win>h2 small,.win>h3 small{color:var(--soft);font-weight:400;font-size:.7rem}
.win .body{padding:calc(var(--u)*2)}
.win .body>:last-child{margin-bottom:0}
.win .foot{padding:0 calc(var(--u)*2) calc(var(--u)*2);font-family:var(--label);font-size:.72rem;text-transform:uppercase}
.win .foot a{display:inline-block;padding:6px 0}
.grid{display:grid;gap:calc(var(--u)*4);align-items:start}
.g-2-1{grid-template-columns:minmax(0,2fr) minmax(0,1fr)}
.g-1-1{grid-template-columns:repeat(2,minmax(0,1fr))}
.stack{display:grid;gap:calc(var(--u)*4);align-content:start;min-width:0}

/* tables: numbers right, horizontal rules only, tabular figures */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll+.scroll,.scroll+p,p+.scroll{margin-top:calc(var(--u)*2)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
caption{text-align:left;font-family:var(--label);font-size:.75rem;text-transform:uppercase;padding:0 0 10px}
th{font-family:var(--label);font-weight:400;font-size:.66rem;text-transform:uppercase;text-align:left;color:var(--muted);padding:0 12px 8px 0;border-bottom:3px solid var(--ink);white-space:nowrap;vertical-align:bottom}
td{padding:8px 12px 8px 0;border-bottom:2px dotted var(--line);white-space:nowrap;vertical-align:middle}
th:last-child,td:last-child{padding-right:0}
.num{text-align:right;width:1%}
th.num,td.num{padding-left:12px}
td.wrap{white-space:normal}
tr.cut td{border-bottom:4px solid var(--red)}
.rank{font-family:var(--display);font-size:1.5rem;line-height:.8;color:var(--blue)}
.big{font-family:var(--display);font-size:1.7rem;line-height:.8}
.hi{color:var(--gold-dk)}
.cut-note{font-size:.88rem;color:var(--muted);margin:10px 0 0;display:flex;align-items:center;gap:8px}
.cut-note i{display:inline-block;width:24px;height:4px;background:var(--red)}
.who{white-space:nowrap;display:inline-flex;align-items:center;gap:8px}
.who .px{display:inline-block}
.tag{display:inline-block;font-family:var(--label);font-size:.62rem;text-transform:uppercase;color:var(--paper);background:var(--blue);padding:2px 5px;margin-left:8px;vertical-align:2px;white-space:nowrap}
.tag.gold{background:var(--gold);color:var(--ink);margin:0 6px 0 0}
.won{font-weight:600}
.matrix{width:auto}
.matrix th,.matrix td{text-align:center;padding:7px 9px}
.matrix th:first-child,.matrix td:first-child{text-align:left;position:sticky;left:0;background:var(--paper);padding-left:0}
.matrix td.self{color:var(--steel)}
.match-t td:first-child,.match-t th:first-child{text-align:right}
abbr[title]{text-decoration:none}
.facts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:10px 20px;margin:0}
.facts dt{font-family:var(--label);font-size:.66rem;text-transform:uppercase;color:var(--muted);padding-top:4px}
.facts dd{margin:0}
.empty{border:3px dashed var(--line);padding:16px;color:var(--muted);max-width:68ch;margin:0}
.band.dark .empty{border-color:var(--char-2);color:var(--soft)}

/* home */
.intro{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:calc(var(--u)*4);align-items:start;padding-block:calc(var(--u)*5)}
.intro h1{font-size:clamp(3.4rem,8vw,5.6rem);line-height:.78;margin:0 0 16px;text-shadow:5px 5px 0 var(--gold)}
.intro .lead{font-size:1.2rem;max-width:44ch;margin:0 0 20px}
.pills{display:flex;flex-wrap:wrap;gap:8px 12px;margin:0 0 4px;padding:0;list-style:none}
.pills li{font-family:var(--label);font-size:.7rem;text-transform:uppercase;background:var(--ink);color:var(--paper);padding:8px 10px}
.pills li b{color:var(--gold);font-weight:700}
.progress{display:flex;gap:3px;margin-top:16px;max-width:420px}
.progress i{flex:1;height:12px;background:var(--line)}
.progress i.on{background:var(--blue)}
.intro .note{margin-top:16px}
.scores{display:grid;gap:6px}
.score{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0 12px;background:var(--ink);color:#C9CDD2;padding:6px 12px;font-size:.98rem}
.score a{text-decoration-color:var(--char-2)}
.score .w{color:var(--gold)}
.score .s{font-family:var(--display);font-size:1.35rem;line-height:1;text-align:right}
.potamt{font-family:var(--display);font-size:4.4rem;line-height:.8;margin:0 0 12px;text-shadow:4px 4px 0 var(--gold)}
.race{list-style:none;margin:12px 0 0;padding:0}
.race li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:8px 0;border-top:2px dotted var(--line)}
.coins{display:inline-flex;gap:4px}
.champ{display:flex;gap:14px;align-items:center}
.champ .sub{color:var(--muted);font-size:.95rem}

/* the rafters, and the rink with the ice resurfacer */
.rafters{background:radial-gradient(circle,#3B3F4A 1.5px,transparent 2px) 0 0/10px 10px,radial-gradient(circle,#2A2D35 1.5px,transparent 2px) 5px 5px/10px 10px,#1A1C22;color:var(--paper)}
.rafters .sec-head{padding-top:calc(var(--u)*3);margin:0}
.rafters .sec-head a{color:var(--paper);text-decoration-color:var(--gold)}
.rafters .sec-head a:hover{color:var(--ink)}
.banners{display:flex;gap:22px;list-style:none;margin:0;padding:12px 4px 26px;align-items:flex-start;overflow-x:auto}
.banner{flex:none;width:132px;position:relative;padding-top:34px}
.banner::before{content:"";position:absolute;top:0;left:24px;right:24px;height:34px;border-left:4px solid #8D939B;border-right:4px solid #8D939B}
.banner .rod{display:block;height:8px;background:#AEB4BB;margin:0 -8px;box-shadow:0 4px 0 #6E747C}
.cloth{display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px;min-height:224px;padding:12px 10px 40px;background:var(--gold);color:var(--black);
clip-path:polygon(0 0,100% 0,100% 100%,84% 100%,84% calc(100% - 8px),68% calc(100% - 8px),68% calc(100% - 16px),56% calc(100% - 16px),56% calc(100% - 24px),44% calc(100% - 24px),44% calc(100% - 16px),32% calc(100% - 16px),32% calc(100% - 8px),16% calc(100% - 8px),16% 100%,0 100%);
box-shadow:inset 0 0 0 4px var(--black),inset 0 0 0 8px var(--gold-lt)}
.cloth .what{font-family:var(--label);font-size:.62rem;text-transform:uppercase;line-height:1.25;padding-top:4px}
.cloth .team{font-family:var(--display);font-size:1.45rem;line-height:.9;overflow-wrap:anywhere}
.cloth .year{margin-top:auto;font-family:var(--display);font-size:3.4rem;line-height:.8}
.banner.cream{width:108px;padding-top:22px}
.banner.cream::before{height:22px;left:18px;right:18px}
.banner.cream .cloth{background:var(--paper);min-height:180px;box-shadow:inset 0 0 0 4px var(--black),inset 0 0 0 8px #D9E6F2}
.banner.cream .year{font-size:2.6rem}
.banner.cream .team{font-size:1.2rem}
.banner.pending .cloth{background:repeating-linear-gradient(90deg,#2A2D35 0 8px,#24272E 8px 16px);color:#A9AFB7;box-shadow:inset 0 0 0 4px #4A4F59}
.banner a{display:block;text-decoration:none;color:inherit}
.banner a:hover{background:none}
.banner a:hover .team{text-decoration:underline}
.small{padding-top:0}
.small .banner{width:104px;padding-top:0}
.small .banner::before{display:none}
.small .cloth{min-height:170px}
.small .cloth .year{font-size:2.6rem}
.small .cloth .team{font-size:1.2rem}
.small .banner.cream{width:92px}
.small .banner.cream .cloth{min-height:150px}
.small .banner.cream .year{font-size:2.1rem}
.rink{height:84px;position:relative;overflow:hidden;border-top:8px solid #6E747C;box-shadow:inset 0 4px 0 var(--paper),inset 0 8px 0 var(--gold);
background:linear-gradient(var(--red),var(--red)) 50% 0/8px 100% no-repeat,linear-gradient(var(--blue),var(--blue)) 30% 0/6px 100% no-repeat,linear-gradient(var(--blue),var(--blue)) 70% 0/6px 100% no-repeat,#E4EEF5}
.zam{position:absolute;bottom:4px;left:24px;width:112px;height:56px;background:url("@@sprites/resurfacer.svg@@") 0 0/224px 56px no-repeat}
.zam::before{content:"";position:absolute;right:calc(100% - 8px);bottom:0;width:100vw;height:60px;background:rgba(252,252,252,.55)}
@media (prefers-reduced-motion:no-preference){
.zam{left:0;animation:drive 24s steps(240) infinite,bob .5s steps(2) infinite}
@keyframes drive{from{transform:translateX(-120px)}to{transform:translateX(100vw)}}
@keyframes bob{to{background-position:-224px 0}}
}
@media (prefers-reduced-motion:reduce){.zam::before{display:none}}

/* level select */
.levels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:calc(var(--u)*3)}
.level{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;align-items:start;background:var(--black);color:var(--paper);padding:16px;text-decoration:none;box-shadow:inset 0 0 0 4px var(--char-2);min-height:44px}
.band.dark a.level:hover,.level:hover{background:var(--black);color:var(--paper);box-shadow:inset 0 0 0 4px var(--gold)}
.level .ico{grid-row:span 3}
.level b{font-family:var(--display);font-weight:400;font-size:1.9rem;line-height:.8;color:var(--gold)}
.level span{font-size:.95rem;color:#C9CDD2}
.level em{font-style:normal;font-family:var(--label);font-size:.66rem;text-transform:uppercase;color:var(--led);grid-column:2}

/* playoff bracket */
.bracket{display:grid;grid-template-columns:repeat(var(--rounds,3),minmax(190px,1fr));gap:24px;align-items:center;min-width:620px}
.bracket.r1{--rounds:1;min-width:0}.bracket.r2{--rounds:2;min-width:420px}.bracket.r4{--rounds:4;min-width:820px}
.round{display:grid;gap:18px;align-content:center}
.round h3{margin:0;font-family:var(--label);font-size:.68rem;text-transform:uppercase;color:var(--muted);font-weight:400}
.match{background:var(--paper);box-shadow:0 -3px 0 var(--ink),0 3px 0 var(--ink),-3px 0 0 var(--ink),3px 0 0 var(--ink);margin:3px}
.match div{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:center;padding:6px 10px;font-size:.95rem}
.match div+div{border-top:2px dotted var(--line)}
.match .w{font-weight:600}
.match .w .s{color:var(--blue)}
.match .seed{font-family:var(--label);font-size:.62rem;color:var(--muted);min-width:14px}
.match .s{font-family:var(--display);font-size:1.3rem;line-height:1}
.match.final{box-shadow:0 -4px 0 var(--ink),0 4px 0 var(--ink),-4px 0 0 var(--ink),4px 0 0 var(--ink),0 0 0 8px var(--gold)}

/* open-and-close lists: weeks, trades, drafts */
.acc details{background:var(--paper);margin:0 0 8px;box-shadow:0 0 0 2px var(--line)}
.acc details[open]{box-shadow:0 0 0 3px var(--ink)}
.acc summary{cursor:pointer;list-style:none;padding:10px 14px 10px 34px;position:relative;display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 12px;min-height:44px;align-items:center}
.acc summary::-webkit-details-marker{display:none}
.acc summary::before{content:"";position:absolute;left:14px;top:50%;margin-top:-5px;border:5px solid transparent;border-left:7px solid var(--ink)}
.acc details[open]>summary::before{border:5px solid transparent;border-top:7px solid var(--ink);margin-top:-3px;left:12px}
.acc summary:hover{background:var(--ice-2)}
.acc summary .k{font-family:var(--label);font-size:.75rem;text-transform:uppercase}
.acc summary .d{color:var(--muted);font-size:.95rem}
.acc .inner{padding:4px 14px 14px}
.win .acc details{box-shadow:0 0 0 2px var(--line)}
.tree,.tree ul{list-style:none;margin:6px 0 4px;padding-left:18px;border-left:3px solid var(--line)}
.tree{padding-left:12px}
.tree li{margin:5px 0}
.tree .out{color:var(--muted)}
.inner h3{font-family:var(--text);font-size:1.05rem;font-weight:600;margin:14px 0 4px}
.inner h3:first-child{margin-top:4px}
.retro{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:8px 20px;margin:0 0 12px}
.retro dt{font-family:var(--label);font-size:.66rem;text-transform:uppercase;color:var(--muted);padding-top:4px}
.retro dd{margin:0}

/* franchises */
.fhero{background:var(--black);color:var(--paper);border-bottom:8px solid var(--fc,var(--gold));box-shadow:0 4px 0 var(--fc2,var(--black))}
.fhero .in{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:16px 28px;align-items:center;padding-block:28px}
.fhero h1{font-family:var(--display);font-weight:400;font-size:clamp(3rem,7vw,4.6rem);line-height:.8;margin:0;color:var(--paper);text-shadow:4px 4px 0 var(--char-2)}
.fhero .sub{margin:10px 0 0;color:var(--soft)}
.fhero .logo-img{width:108px;height:108px;object-fit:contain;background:var(--char)}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.stats li{background:var(--char);padding:10px 12px;min-width:96px;box-shadow:inset 0 0 0 2px var(--char-2)}
.stats .k{font-family:var(--label);font-size:.62rem;text-transform:uppercase;color:var(--soft)}
.stats .v{font-family:var(--display);font-size:2rem;line-height:.85;color:var(--gold)}
.jerseys{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;list-style:none;margin:0;padding:0}
.jerseys a{display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--paper);color:var(--ink);text-decoration:none;box-shadow:inset 0 0 0 2px var(--line);font-size:.98rem;min-height:44px}
.band.dark .jerseys a:hover,.jerseys a:hover{background:var(--paper);color:var(--ink);box-shadow:inset 0 0 0 3px var(--gold)}
.jerseys a[aria-current]{box-shadow:inset 0 0 0 3px var(--gold);background:#FFF4D6}
.tlist{list-style:none;margin:0;padding:0;display:grid}
.tlist li{padding:10px 0;border-bottom:2px dotted var(--line)}
.tlist li:first-child{padding-top:0}
.tlist li:last-child{border-bottom:0;padding-bottom:0}
.t-top{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;margin-bottom:6px}
.tlist dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px;margin:0;font-size:.95rem}
.tlist dt{font-family:var(--label);font-size:.62rem;text-transform:uppercase;color:var(--muted);padding-top:4px}
.tlist dd{margin:0}

/* the Constitution: pixel headings, Pixelify Sans text with roomy spacing */
.con{background:var(--paper)}
.con-layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:calc(var(--u)*6);align-items:start;padding-block:calc(var(--u)*2) calc(var(--u)*6)}
.toc{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto;padding:16px;background:var(--ice);box-shadow:inset 0 0 0 3px var(--line)}
.toc h2{font-family:var(--label);font-size:.68rem;text-transform:uppercase;margin:0 0 10px;color:var(--muted);font-weight:400}
.toc ol,.toc-mobile ol{list-style:none;margin:0;padding:0;font-size:.92rem;line-height:1.35}
.toc a,.toc-mobile a{display:block;padding:6px 6px 6px 18px;text-decoration:none;position:relative;color:var(--ink)}
.toc a:hover{background:var(--ice-2)}
.toc a.on{background:var(--ink);color:var(--paper)}
.toc a.on::before{content:"";position:absolute;left:5px;top:50%;margin-top:-4px;border:4px solid transparent;border-left:6px solid var(--gold)}
.toc .no,.toc-mobile .no{font-family:var(--label);font-size:.62rem;display:block;color:var(--muted)}
.toc a.on .no{color:var(--gold)}
.toc-mobile{display:none}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0;padding:0;list-style:none}
.meta li{font-family:var(--label);font-size:.66rem;text-transform:uppercase;background:var(--ink);color:var(--paper);padding:6px 8px}
.doc{font-size:1.0625rem;line-height:1.7;max-width:70ch;color:var(--ink)}
.doc h2{margin:56px 0 18px;padding-top:12px;border-top:4px solid var(--ink);display:grid;gap:6px;scroll-margin-top:16px;font-weight:400}
.doc h2:first-child{margin-top:8px}
.doc h2 .art-no{font-family:var(--label);font-size:.72rem;text-transform:uppercase;color:var(--gold-dk);font-weight:700;letter-spacing:.04em}
.doc h2 .art-title{font-family:var(--display);font-size:2.4rem;line-height:.85;color:var(--ink)}
.doc h3{font-size:1.15rem;font-weight:600;margin:28px 0 8px}
.doc p{margin:0 0 14px}
.doc .sec-no{display:inline-block;font-family:var(--display);font-weight:400;font-size:1.2rem;line-height:1;background:var(--ink);color:var(--gold);padding:3px 6px 2px;margin-right:6px;vertical-align:1px}
.doc ul{padding-left:1.2em;margin:0 0 14px}
.doc li{margin:0 0 6px}
.doc blockquote{margin:16px 0;padding:12px 16px;background:var(--ice);box-shadow:inset 4px 0 0 var(--gold)}
.doc .scroll{margin:8px 0 20px}
.doc td{white-space:normal}
.doc code{font-size:.92em}
.qr{background:var(--ice);margin:4px 4px 28px;box-shadow:0 -4px 0 var(--ink),0 4px 0 var(--ink),-4px 0 0 var(--ink),4px 0 0 var(--ink)}
.qr ul{list-style:none;padding:14px 16px;margin:0;display:grid;gap:8px}
.qr li{margin:0;padding-bottom:8px;border-bottom:2px dotted var(--line)}
.qr li:last-child{border:0;padding:0}
.changelog{margin:0 0 28px}
.top-btn{position:sticky;bottom:16px;float:right;margin-top:-60px}

/* footer */
.site-foot{background:var(--black);color:var(--soft);border-top:8px solid var(--gold);font-size:.95rem}
.site-foot .cols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px;padding-block:28px 12px}
.site-foot h2{font-family:var(--label);font-size:.7rem;text-transform:uppercase;color:var(--gold);margin:0 0 10px;font-weight:700}
.site-foot ul{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.site-foot a{color:var(--paper);text-decoration:none;display:inline-block;padding:6px 0}
.site-foot a:hover{color:var(--ink)}
.site-foot .fine{border-top:2px dotted var(--char-2);padding-block:12px 24px;margin:0;font-size:.88rem}
.missing{padding-block:calc(var(--u)*8)}
.missing h1{margin-bottom:24px}

@media (max-width:880px){
.g-2-1,.g-1-1,.intro{grid-template-columns:minmax(0,1fr)}
.levels{grid-template-columns:repeat(2,minmax(0,1fr))}
.con-layout{grid-template-columns:minmax(0,1fr);gap:0}
.toc{display:none}
.toc-mobile{display:block;background:var(--ice);box-shadow:inset 0 0 0 3px var(--line);margin-bottom:16px}
.toc-mobile summary{padding:12px 16px;font-family:var(--label);font-size:.75rem;text-transform:uppercase;cursor:pointer;min-height:44px}
.toc-mobile ol{padding:0 16px 12px}
.toc-mobile a{padding:8px 0}
.site-foot .cols{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:560px){
.in{padding-inline:16px}
.status{margin-left:0;width:100%}
.menu a{padding:0 10px 0 20px;font-size:.72rem}
.levels{grid-template-columns:minmax(0,1fr)}
.fhero .in{grid-template-columns:auto minmax(0,1fr)}
.fhero .stats{grid-column:1/-1}
.pager{margin-left:0}
.sec-head h2{font-size:2rem}
.doc h2 .art-title{font-size:2rem}
.potamt{font-size:3.6rem}
.win .body{padding:12px}
td,th{padding-right:8px}
th.num,td.num{padding-left:8px}
}
"""


def franchise_css(colors: dict[str, list[str]]) -> str:
    rules = []
    for cls, pair in sorted(colors.items()):
        main = safe_color(pair[0] if pair else None, DEFAULT_COLORS[0])
        second = safe_color(pair[1] if len(pair) > 1 else None, main)
        rules.append(f".f-{cls}{{--fc:{main};--fc2:{second};--fc-ink:{ink_for(main)}}}")
    return "\n".join(rules)


def toc_css(anchors: list[str]) -> str:
    """Mark the article you jumped to in the Constitution's contents (CSS only, no script)."""
    return "\n".join(f'.con-layout:has(#{a}:target) .toc a[href="#{a}"]{{background:var(--ink);color:var(--paper)}}'
                     for a in anchors)


# --- site ----------------------------------------------------------------------------

@dataclass
class Game:
    season: int
    week: int
    playoff: bool
    away: str
    away_score: float
    home: str
    home_score: float

    @property
    def margin(self) -> float:
        return abs(self.away_score - self.home_score)

    @property
    def winner(self) -> str | None:
        if self.away_score == self.home_score:
            return None
        return self.away if self.away_score > self.home_score else self.home

    @property
    def loser(self) -> str | None:
        w = self.winner
        return None if w is None else (self.home if w == self.away else self.away)


class Site:
    def __init__(self, hist: LeagueHistory, out: Path, built: datetime, base_url: str = "") -> None:
        self.hist = hist
        self.out = out
        self.built = built
        self.base = base_url.rstrip("/")
        self.h2h = HeadToHead(hist)
        self.profiles = franchise_profiles(hist, self.h2h)
        self.versions: dict[str, str] = {}
        self.logos: dict[str, str] = {}
        self.pages: list[str] = []
        self.has_card = False
        self.has_pdf = False
        self.constitution: tuple[str, list[tuple[str, str, str]]] | None = None
        self._slugs: dict[str, str] = {}
        used: set[str] = set()
        for p in self.profiles:
            s = slug(p["key"])
            while s in used:
                s += "-x"
            used.add(s)
            self._slugs[p["key"]] = s
        self._pages = {p["key"] for p in self.profiles}
        self._games: dict[int, list[Game]] = {}

    # --- addresses ---------------------------------------------------------------------
    def fslug(self, key: str) -> str:
        if key not in self._slugs:
            self._slugs[key] = slug(key)
        return self._slugs[key]

    def asset(self, name: str) -> str:
        return f"/assets/{name}?v={self.versions.get(name, '0')}"

    def furl(self, key: str) -> str:
        return f"/franchises/{self.fslug(key)}/"

    def link(self, key: str | None) -> str:
        if not key:
            return '<span class="muted">—</span>'
        if key not in self._pages:  # a team the archive saw but no franchise page was built for
            return esc(self.hist.name(key))
        return f'<a href="{self.furl(key)}">{esc(self.hist.name(key))}</a>'

    def img(self, name: str, scale: int, rows: list[str], cls: str = "px") -> str:
        w, h = max(len(r) for r in rows) * scale, len(rows) * scale
        return f'<img class="{cls}" src="{self.asset(name)}" width="{w}" height="{h}" alt="">'

    def sprite(self, key: str, scale: int) -> str:
        return self.img(f"sprites/{key}.svg", scale, SPRITES[key])

    def jersey(self, key: str | None, scale: int = 1) -> str:
        name = f"sprites/jersey-{self.fslug(key)}.svg" if key and f"sprites/jersey-{self.fslug(key)}.svg" in self.versions \
            else "sprites/jersey.svg"
        return self.img(name, scale, SPRITES["jersey"])

    def who(self, key: str | None) -> str:
        if not key:
            return '<span class="muted">—</span>'
        return f'<span class="who">{self.jersey(key)}{self.link(key)}</span>'

    def coins(self, count: int, need: int) -> str:
        dots = "".join(self.sprite("coin" if i < count else "coinoff", 3) for i in range(max(need, count)))
        return f'<span class="coins" role="img" aria-label="{count} of {need} titles">{dots}</span>'

    # --- season helpers -----------------------------------------------------------------
    def label(self, season: int) -> str:
        return str(self.hist.archive.meta(season).get("season_label") or "")

    def is_test(self, season: int) -> bool:
        return bool(self.hist.archive.meta(season).get("test"))

    def honors(self, season: int) -> dict[str, str]:
        return {a: k for a, k in (self.hist.records.seasons.get(season) or {}).items() if a in AWARDS and k}

    def season_link(self, season: int) -> str:
        return f'<a href="/seasons/{season}/">Season {season}</a>'

    def all_seasons(self) -> list[int]:
        return sorted(set(self.hist.seasons) | set(self.hist.records.seasons))

    def games(self, season: int) -> list[Game]:
        if season not in self._games:
            out = []
            for key, week in self.hist.archive.results(season).items():
                if not week.get("played", True):
                    continue
                for m in week.get("matchups") or []:
                    a, b = m["away"], m["home"]
                    out.append(Game(season, int(week.get("period") or key), bool(week.get("playoff")),
                                    self.hist.franchise(a["team"]), float(a["score"]),
                                    self.hist.franchise(b["team"]), float(b["score"])))
            self._games[season] = out
        return self._games[season]

    def all_games(self) -> list[Game]:
        return [g for season in self.hist.seasons for g in self.games(season)]

    def weeks_played(self, season: int) -> tuple[int, int]:
        """(finished regular-season weeks, regular-season weeks on the schedule)."""
        regular = {int(w.get("period") or k): bool(w.get("played", True))
                   for k, w in self.hist.archive.results(season).items() if not w.get("playoff")}
        return sum(regular.values()), max(len(regular), REGULAR_WEEKS)

    def standings(self, season: int) -> tuple[list[dict[str, Any]], str]:
        """Rows {rank, key, record, pf} plus a note saying whether they are final."""
        saved = self.hist.archive.standings(season)
        if saved and saved.get("rows"):
            rows = [{"rank": int(r["rank"]), "key": self.hist.franchise(r["teamId"]), "record": str(r["record"]),
                     "pf": float(r["pointsFor"])} for r in saved["rows"]]
            return rows, f"Final regular-season standings after Week {saved.get('after_week')}."
        computed, through = computed_standings(self.hist, season)
        rows = [{"rank": i, "key": k, "record": r["text"], "pf": r["pf"]} for i, (k, r) in enumerate(computed, 1)]
        if not rows:
            return rows, ""
        if self.in_progress(season):
            return rows, f"Through Week {through}, worked out from final weekly scores. Not final."
        return rows, f"Regular-season standings worked out from the final weekly scores (through Week {through})."

    def in_progress(self, season: int) -> bool:
        return season == self.hist.archive.latest_season() and "champion" not in self.honors(season)

    def standings_table(self, rows: list[dict[str, Any]], *, final: bool) -> str:
        cut = final or len(rows) > PLAYOFF_TEAMS
        body = table(["#", "Franchise", "W-L-T", "Points for"],
                     [[f'<span class="rank">{esc(r["rank"])}</span>', self.who(r["key"]), esc(r["record"]), esc(score(r["pf"]))]
                      for r in rows], num={0, 3},
                     row_cls=["cut" if cut and r["rank"] == PLAYOFF_TEAMS and len(rows) > PLAYOFF_TEAMS else "" for r in rows])
        if len(rows) > PLAYOFF_TEAMS:
            body += (f'<p class="cut-note"><i></i>The top {PLAYOFF_TEAMS} make the playoffs; seeds 1 and 2 get byes.</p>')
        return body

    # --- writing -----------------------------------------------------------------------
    def leds(self) -> list[tuple[str, str]]:
        out = []
        pending = self.pending_season()
        latest = self.hist.archive.latest_season()
        season = pending if pending is not None else latest
        if season is not None:
            out.append(("Season", str(season)))
            if self.in_progress(season) and not self.is_test(season) and season == latest:
                done, total = self.weeks_played(season)
                out.append(("Week", f"{done:02d}/{total}"))
        out.append(("Pot", money(dynasty_summary(self.hist)["balance"])))
        return out

    def write(self, rel: str, title: str, body: str, *, section: str = "", description: str = "",
              home: bool = False, crumbs: list[tuple[str, str]] | None = None, before_main: str = "") -> None:
        url = "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
        home_link = f'<li><a href="/"{" aria-current=page" if home else ""}>Home</a></li>'
        nav = home_link + "".join(f'<li><a href="/{key}/"{" aria-current=page" if key == section else ""}>{esc(label)}</a></li>'
                                  for key, label in SECTIONS)
        full_title = f"{SITE_NAME} | {LEAGUE_NAME}" if home else f"{title} | {SITE_NAME}"
        desc = description or DESCRIPTION
        meta = [f'<meta name="description" content="{esc(desc)}">',
                '<meta property="og:type" content="website">',
                f'<meta property="og:site_name" content="{esc(SITE_NAME)}">',
                f'<meta property="og:title" content="{esc(SITE_NAME if home else title)}">',
                f'<meta property="og:description" content="{esc(desc)}">']
        if self.base and rel != "404.html":
            meta.insert(0, f'<link rel="canonical" href="{esc(self.base + url)}">')
            meta.append(f'<meta property="og:url" content="{esc(self.base + url)}">')
        if self.has_card:
            card = (self.base + "/assets/social-card.png") if self.base else self.asset("social-card.png")
            meta += [f'<meta property="og:image" content="{esc(card)}">', '<meta property="og:image:width" content="1200">',
                     '<meta property="og:image:height" content="630">',
                     '<meta property="og:image:alt" content="BLHA League History">',
                     '<meta name="twitter:card" content="summary_large_image">']
        meta_html = "\n".join(meta)
        leds = "".join(f'<div class="led"><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>' for k, v in self.leds())
        trail = ""
        if crumbs:
            items = [f'<li><a href="{esc(href)}">{esc(text)}</a></li>' for text, href in crumbs[:-1]]
            items.append(f'<li aria-current="page">{esc(crumbs[-1][0])}</li>')
            trail = f'<nav class="crumbs" aria-label="Breadcrumb"><div class="in"><ol>{"".join(items)}</ol></div></nav>\n'
        favicon = (f'<link rel="icon" type="image/png" href="{self.asset("favicon.png")}">\n'
                   if "favicon.png" in self.versions else "")
        touch = (f'<link rel="apple-touch-icon" href="{self.asset("apple-touch-icon.png")}">\n'
                 if "apple-touch-icon.png" in self.versions else "")
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
{meta_html}
<meta name="theme-color" content="{BLACK}">
{favicon}{touch}<link rel="preload" href="{self.asset('fonts/jersey10.woff')}" as="font" type="font/woff" crossorigin>
<link rel="preload" href="{self.asset('fonts/pixelifysans.woff')}" as="font" type="font/woff" crossorigin>
<link rel="stylesheet" href="{self.asset('site.css')}">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="sb"><div class="in">
<div class="sb-top">
<a class="logo" href="/">{self.sprite("b", 4)}<span><b>BLHA HISTORY</b><small>{esc(LEAGUE_NAME.upper())}</small></span></a>
<dl class="status" aria-label="League status">{leds}</dl>
</div>
<nav class="menu" aria-label="Main"><ul>{nav}</ul></nav>
</div></header>
{trail}{before_main}<main id="main">
{body}
</main>
<footer class="site-foot"><div class="in">
<div class="cols">
<div><h2>League</h2><ul><li><a href="/seasons/">Seasons</a></li><li><a href="/records/">Records</a></li><li><a href="/head-to-head/">Head-to-head</a></li></ul></div>
<div><h2>Franchises</h2><ul><li><a href="/franchises/">All franchises</a></li><li><a href="/#pot">Dynasty Pot</a></li></ul></div>
<div><h2>Transactions</h2><ul><li><a href="/trades/">Trades</a></li><li><a href="/drafts/">Drafts</a></li></ul></div>
<div><h2>Rulebook</h2><ul><li><a href="/constitution/">Constitution</a></li><li><a href="/constitution/#changelog">Changelog</a></li></ul></div>
</div>
<p class="fine">{esc(LEAGUE_NAME)}, founded 2026. Game results come from Fantrax; honors and the Dynasty Pot come from the Commissioner's records. Updated {esc(long_date(self.built))}.</p>
</div></footer>
</body>
</html>
"""
        target = self.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        self.pages.append(rel)

    def head(self, title: str, sub: str = "", *, pager: str = "", extra: str = "") -> str:
        sub_html = f'<p class="sub">{sub}</p>' if sub else ""
        return f'<div class="in"><div class="head"><div><h1>{esc(title)}</h1>{sub_html}{extra}</div>{pager}</div></div>'

    # --- assets -------------------------------------------------------------------------
    def put_asset(self, name: str, data: bytes) -> None:
        target = self.out / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.versions[name] = version(data)

    def assets(self) -> None:
        folder = self.out / "assets"
        folder.mkdir(parents=True, exist_ok=True)
        for name, source in FONT_FILES.items():
            self.put_asset(f"fonts/{name}", source.read_bytes())
        for key, rows in SPRITES.items():
            pal = {**PAL, "P": LEAGUE_JERSEY[0], "S": LEAGUE_JERSEY[1]} if key == "jersey" else PAL
            self.put_asset(f"sprites/{key}.svg", sprite_svg(rows, pal).encode())
        sheet = [a + b for a, b in zip(*RESURFACER)]
        self.put_asset("sprites/resurfacer.svg", sprite_svg(sheet, RESURFACER_PAL).encode())
        for name, source, width in IMAGES:
            if not source.exists():
                continue
            target = folder / name
            if not shrink(source, target, width):
                shutil.copyfile(source, target)
            self.versions[name] = version(target.read_bytes())
        colors: dict[str, list[str]] = {}
        for p in self.profiles:
            s = self.fslug(p["key"])
            colors[s] = p["colors"]
            main = safe_color(p["colors"][0] if p["colors"] else None, DEFAULT_COLORS[0])
            second = safe_color(p["colors"][1] if len(p["colors"]) > 1 else None, "#FCFCFC")
            self.put_asset(f"sprites/jersey-{s}.svg", sprite_svg(SPRITES["jersey"], {**PAL, "P": main, "S": second}).encode())
            logo = p.get("logo")
            if logo and (ROOT / logo).is_file():
                name = f"logos/{s}.png"
                (folder / "logos").mkdir(exist_ok=True)
                if not shrink(ROOT / logo, folder / name, 256, smooth=True):
                    shutil.copyfile(ROOT / logo, folder / name)
                self.versions[name] = version((folder / name).read_bytes())
                self.logos[p["key"]] = name
        if CONSTITUTION_PDF.exists():
            self.put_asset("BLHA_Constitution.pdf", CONSTITUTION_PDF.read_bytes())
            self.has_pdf = True
        self.has_card = social_card(folder / "social-card.png")
        if self.has_card:
            self.versions["social-card.png"] = version((folder / "social-card.png").read_bytes())
        if CONSTITUTION.exists():
            self.constitution = constitution_html()
        css = CSS
        for token in set(re.findall(r"@@([^@]+)@@", css)):
            css = css.replace(f"@@{token}@@", self.asset(token))
        anchors = [a for a, _, _ in self.constitution[1]] if self.constitution else []
        css = css.strip() + "\n" + franchise_css(colors) + "\n" + toc_css(anchors + ["changelog"]) + "\n"
        (folder / "site.css").write_text(css, encoding="utf-8")
        self.versions["site.css"] = version(css.encode())

    # --- banners ------------------------------------------------------------------------
    def banner(self, season: int, award: str | None, key: str | None) -> str:
        if award is None:
            return (f'<li class="banner pending"><span class="rod"></span><div class="cloth">'
                    f'<span class="what">BLHA Champions</span><span class="team">To be decided</span>'
                    f'<span class="year">{season}</span></div></li>')
        gold = award == "champion"
        what = "BLHA Champions" if gold else AWARDS[award]
        cup = self.sprite("cup", 3) if gold else ""
        name = esc(self.hist.name(key)) if key else ""
        return (f'<li class="banner{"" if gold else " cream"}"><span class="rod"></span>'
                f'<a href="/seasons/{season}/"><div class="cloth">{cup}<span class="what">{esc(what)}</span>'
                f'<span class="team">{name}</span><span class="year">{season}</span></div></a></li>')

    def rafters(self) -> str:
        items = []
        for season in sorted(self.hist.records.seasons):
            h = self.honors(season)
            if h.get("champion"):
                items.append(self.banner(season, "champion", h["champion"]))
            if h.get("presidents_trophy"):
                items.append(self.banner(season, "presidents_trophy", h["presidents_trophy"]))
        pending = self.pending_season()
        if pending is not None:
            items.append(self.banner(pending, None, None))
        rink = '<div class="rink" aria-hidden="true"><span class="zam"></span></div>'
        more = '<a class="more" href="/seasons/">Every season</a>'
        return (f'<section class="rafters" aria-labelledby="rafters"><div class="in">'
                f'{sec_head("In the rafters", "rafters", more)}'
                f'<ol class="banners">{"".join(items)}</ol></div>{rink}</section>')

    def pending_season(self) -> int | None:
        latest = self.hist.archive.latest_season()
        if latest is None:  # nothing archived yet: the first Season of the Dynasty Pot cycle
            first = dynasty_summary(self.hist)["cycle_started"]
            return int(first) if str(first).isdigit() and "champion" not in self.honors(int(first)) else None
        if self.is_test(latest) or "champion" in self.honors(latest):
            nxt = latest + 1
            return None if "champion" in self.honors(nxt) else nxt
        return latest

    # --- home ---------------------------------------------------------------------------
    def home(self) -> None:
        hist = self.hist
        pot = dynasty_summary(hist)
        need = pot["titles_to_win"]
        latest = hist.archive.latest_season()
        pending = self.pending_season()

        status = ""
        pills = []
        progress = ""
        if latest is not None and self.is_test(latest):
            status = f"The {self.label(latest) or str(latest)} season is a test run. Season {latest + 1} is the first that counts."
            pills.append(f"Season {latest + 1} <b>up next</b>")
        elif latest is not None and self.in_progress(latest):
            done, total = self.weeks_played(latest)
            status = f"Season {latest} is in progress."
            pills += [f"Season {latest} <b>in progress</b>", f"Week <b>{done}</b> of {total}"]
            progress = ('<div class="progress" aria-hidden="true">'
                        + "".join(f'<i class="on"></i>' if i < done else "<i></i>" for i in range(total)) + "</div>")
        elif pending is not None:
            pills.append(f"Season {pending} <b>up next</b>")
        pills.append(f"Updated <b>{esc(short_date(self.built))}</b>")
        pills_html = '<ul class="pills">' + "".join(f"<li>{p}</li>" for p in pills) + "</ul>"
        status_html = f'<p class="note">{esc(status)}</p>' if status else ""
        intro = (f'<div class="in intro"><div><h1>League history</h1>'
                 f'<p class="lead">Every champion, standing, trade and draft of the {esc(LEAGUE_NAME)}, '
                 f'a 12-franchise dynasty fantasy hockey league.</p>{pills_html}{progress}{status_html}</div>'
                 f'{self.latest_scores()}</div>')

        # standings, the Dynasty Pot and the latest champion
        left = ""
        current = next((s for s in sorted(hist.seasons, reverse=True) if self.standings(s)[0]), None)
        if current is not None:
            rows, note = self.standings(current)
            small = f"Season {current}" + (", in progress" if self.in_progress(current) else "")
            left = window("Standings", f'<p class="note">{esc(note)}</p>' + self.standings_table(rows, final=False),
                          small=small, foot=f'<a href="/seasons/{current}/">Season {current} in full</a>')
        else:
            left = window("Standings", empty("Standings appear here after the first week of the first Season."))
        leaders = [r for r in pot["rows"] if r["titles"]]
        race = ('<ul class="race">' + "".join(f"<li>{self.who(r['key'])}{self.coins(r['titles'], need)}</li>" for r in leaders)
                + "</ul>") if leaders else '<p class="muted">No championships yet in this cycle.</p>'
        cycle = (f"This cycle began in Season {esc(pot['cycle_started'])}." if hist.records.seasons
                 else f"The first cycle starts with Season {esc(pot['cycle_started'])}.")
        past = ""
        if pot["past"]:
            past = "<h3>Past winners</h3>" + table(
                ["Cycle", "Winner", "Payout"],
                [[esc(f"Seasons {c['started']}–{c['ended']}"), esc(c["winner"]), esc(money(c["payout"]))] for c in pot["past"]],
                num={2})
        pot_win = window("Dynasty Pot", f'<p class="potamt">{esc(money(pot["balance"]))}</p>'
                         f'<p class="note">The first franchise to win {need} BLHA Championships in one cycle takes the whole pot. '
                         f'{cycle}</p>{race}{past}', small="Article IV", ident="pot")
        right = [pot_win]
        champ_season = next((s for s in sorted(hist.records.seasons, reverse=True) if self.honors(s).get("champion")), None)
        if champ_season is not None:
            key = self.honors(champ_season)["champion"]
            prof = next((p for p in self.profiles if p["key"] == key), None)
            rows, _ = self.standings(champ_season)
            mine = next((r for r in rows if r["key"] == key), None)
            bits = [mine["record"] if mine else "", f"owner {prof['owner']}" if prof and prof.get("owner") else ""]
            sub = ", ".join(b for b in bits if b)
            right.append(window("Latest champion", f'<div class="champ">{self.jersey(key, 4)}<div><div class="big">'
                                f'{self.link(key)}</div><div class="sub">{esc(sub)}</div></div></div>',
                                small=f"Season {champ_season}",
                                foot=f'<a href="{self.furl(key)}">Franchise page</a>' if prof else ""))
        band1 = (f'<div class="band"><div class="in grid g-2-1"><div class="stack">{left}</div>'
                 f'<div class="stack">{"".join(right)}</div></div></div>')

        # records and the trophy room
        rows = []
        for season in sorted(set(hist.seasons) | set(hist.records.seasons), reverse=True):
            h = self.honors(season)
            if not h and self.in_progress(season) and not self.is_test(season):
                done, total = self.weeks_played(season)
                rows.append([self.season_link(season), f'<span class="muted">In progress, week {done} of {total}</span>', "", ""])
                continue
            rows.append([self.season_link(season), self.who(h.get("champion")),
                         self.link(h.get("presidents_trophy")), self.link(h.get("wooden_spoon"))])
        trophy = window("Trophy room", table(["Season", "Champion", "Presidents' Trophy", "Wooden Spoon"], rows)
                        if rows else empty("The first Season is still to come. Its results will appear here."),
                        small="Season by season", foot='<a href="/seasons/">Every season</a>')
        highs = self.high_scores()
        band2 = (f'<div class="band flush"><div class="in grid g-1-1">{highs}{trophy}</div></div>' if highs
                 else f'<div class="band flush"><div class="in">{trophy}</div></div>')
        self.write("index.html", "Home", intro + self.rafters() + band1 + band2 + self.level_select(), home=True)

    def latest_scores(self) -> str:
        season = next((s for s in sorted(self.hist.seasons, reverse=True) if self.games(s)), None)
        if season is None:
            return window("Final scores", empty("Weekly scores appear here once the first week is played."), small="This week")
        week = max(g.week for g in self.games(season))
        rows = []
        for g in [g for g in self.games(season) if g.week == week]:
            aw, hw = g.winner == g.away, g.winner == g.home
            rows.append(f'<div class="score"><span class="{"w" if aw else ""}">{self.link(g.away)}</span>'
                        f'<span class="s{" w" if aw else ""}">{esc(score(g.away_score))}</span>'
                        f'<span class="{"w" if hw else ""}">{self.link(g.home)}</span>'
                        f'<span class="s{" w" if hw else ""}">{esc(score(g.home_score))}</span></div>')
        playoff = any(g.playoff for g in self.games(season) if g.week == week)
        return window(f"Week {week} final scores", f'<div class="scores">{"".join(rows)}</div>',
                      small=f"Season {season}" + (", playoffs" if playoff else ""),
                      foot=f'<a href="/seasons/{season}/#week-{week}">Week {week} in full</a>')

    def high_scores(self) -> str:
        games = self.all_games()
        if not games:
            return ""
        sides = sorted([(g.away_score, g.away, g) for g in games] + [(g.home_score, g.home, g) for g in games],
                       key=lambda s: (-s[0], s[2].season, s[2].week))[:5]
        rows = [[f'<span class="rank">{esc(ordinal(i))}</span>', self.who(k), f'<span class="big{" hi" if i == 1 else ""}">{esc(score(v))}</span>',
                 self.when(g)] for i, (v, k, g) in enumerate(sides, 1)]
        return window("High scores", table(["Rank", "Franchise", "Score", "When"], rows, num={2}),
                      small="Single week", foot='<a href="/records/">Every league record</a>')

    def level_select(self) -> str:
        hist = self.hist
        articles = len([1 for _, n, _ in (self.constitution[1] if self.constitution else []) if n])
        levels = [("seasons", "calendar", "Seasons", "Standings, playoffs and every week", plural(len(self.all_seasons()), "season")),
                  ("franchises", "jersey", "Franchises", "The clubs, their banners and rivals", plural(len(self.profiles), "franchise")),
                  ("head-to-head", "net", "Head-to-head", "Every matchup, every rivalry", "Lifetime records"),
                  ("trades", "swap", "Trades", "Trade log and trade trees", plural(len(hist.trades()), "trade")),
                  ("drafts", "sticks", "Drafts", "Draft boards and retrospectives", plural(len(hist.drafts()), "draft")),
                  ("constitution", "scroll", "Constitution", "The rules and every change to them", plural(articles, "article"))]
        cards = "".join(f'<a class="level" href="/{href}/"><span class="ico">{self.sprite(icon, 4)}</span><b>{esc(t)}</b>'
                        f'<span>{esc(d)}</span><em>{esc(n)}</em></a>' for href, icon, t, d, n in levels)
        return (f'<section class="band dark" aria-labelledby="levels"><div class="in">{sec_head("Select a section", "levels")}'
                f'<div class="levels">{cards}</div></div></section>')

    def when(self, g: Game) -> str:
        return (f'<a href="/seasons/{g.season}/#week-{g.week}">Season {g.season}, Week {g.week}</a>'
                + ('<span class="tag">Playoffs</span>' if g.playoff else ""))

    # --- seasons ------------------------------------------------------------------------
    def seasons(self) -> None:
        rows = []
        all_seasons = sorted(self.all_seasons(), reverse=True)
        for season in all_seasons:
            h = self.honors(season)
            standings, _ = self.standings(season)
            leader = standings[0] if standings else None
            if self.is_test(season):
                status = "Test season"
            else:
                status = "Final" if h.get("champion") else ("In progress" if self.in_progress(season) else "")
            rows.append([self.season_link(season), esc(self.label(season)), self.who(h.get("champion")) if h.get("champion") else "—",
                         (self.link(leader["key"]) + f' <span class="muted">{esc(leader["record"])}</span>') if leader else "—",
                         esc(status)])
        body = self.head("Seasons", "Final standings, playoffs and every weekly result.")
        body += ('<div class="band flush"><div class="in">'
                 + window("Every season", table(["Season", "Years", "Champion", "Regular-season leader", "Status"], rows)
                          if rows else empty("No Season has been archived yet. Standings appear after the first archive run."),
                          small=plural(len(rows), "season"))
                 + "</div></div>")
        self.write("seasons/index.html", "Seasons", body, section="seasons", crumbs=[("Home", "/"), ("Seasons", "/seasons/")])
        for i, season in enumerate(all_seasons):
            newer = all_seasons[i - 1] if i > 0 else None
            older = all_seasons[i + 1] if i + 1 < len(all_seasons) else None
            self.season_page(season, older, newer)

    def season_page(self, season: int, older: int | None, newer: int | None) -> None:
        hist = self.hist
        h = self.honors(season)
        sub = self.label(season)
        if self.in_progress(season) and not self.is_test(season):
            sub = f"{sub}, in progress" if sub else "In progress"
        elif h.get("champion"):
            sub = f"{sub}, final. Champion: {hist.name(h['champion'])}." if sub else f"Final. Champion: {hist.name(h['champion'])}."
        prev_btn = (f'<a class="btn" href="/seasons/{older}/">&#9664; Season {older}</a>' if older
                    else '<span class="btn off">&#9664; Earlier</span>')
        next_btn = (f'<a class="btn" href="/seasons/{newer}/">Season {newer} &#9654;</a>' if newer
                    else '<span class="btn off">Later &#9654;</span>')
        pager = f'<nav class="pager" aria-label="Other seasons">{prev_btn}{next_btn}</nav>'
        jumps = []
        parts = []
        if h:
            items = []
            if h.get("champion"):
                items.append(self.banner(season, "champion", h["champion"]))
            if h.get("presidents_trophy"):
                items.append(self.banner(season, "presidents_trophy", h["presidents_trophy"]))
            banners = f'<ol class="banners small" aria-label="Banners">{"".join(items)}</ol>' if items else ""
            facts = "".join(f"<dt>{esc(label)}</dt><dd>{self.who(h[a])}</dd>" for a, label in AWARDS.items() if h.get(a))
            pot = (hist.records.seasons.get(season) or {}).get("dynasty_pot") or {}
            pot_note = (f'<p class="note">Dynasty Pot after this Season: {esc(money(pot["balance"]))}.</p>'
                        if pot.get("balance") is not None else "")
            honors = window("Honors", f'<dl class="facts">{facts}</dl>{pot_note}', small=f"Season {season}", ident="honors")
            parts.append(f'<div class="band tight flush"><div class="in grid g-1-1"><div>{banners}</div>{honors}'
                         f"</div></div>")
            jumps.append(("honors", "Honors"))
        rows, note = self.standings(season)
        stack = []
        if rows:
            final = not self.in_progress(season)
            stack.append(window("Final standings" if final and not self.is_test(season) else "Standings",
                                f'<p class="note">{esc(note)}</p>' + self.standings_table(rows, final=final),
                                small="Regular season", ident="standings"))
        else:
            stack.append(window("Standings", empty("No week of this Season has finished yet."), ident="standings"))
        jumps.append(("standings", "Standings"))
        bracket = self.bracket(season, rows)
        if bracket:
            stack.append(window("Playoffs", bracket, small="Bracket", ident="playoffs"))
            jumps.append(("playoffs", "Playoffs"))
        weeks = self.week_blocks(season)
        if weeks:
            stack.append(f'<section id="weeks">{sec_head("Week by week", "weeks-title")}<div class="acc">{weeks}</div></section>')
            jumps.append(("weeks", "Week by week"))
        jump = ('<ul class="jump" aria-label="On this page">' + "".join(f'<li><a href="#{i}">{esc(t)}</a></li>' for i, t in jumps)
                + "</ul>")
        body = (self.head(f"Season {season}", esc(sub), pager=pager) + f'<div class="in">{jump}</div>' + "".join(parts)
                + f'<div class="band flush"><div class="in stack">{"".join(stack)}</div></div>')
        self.write(f"seasons/{season}/index.html", f"Season {season}", body, section="seasons",
                   description=f"BLHA Season {season}: honors, standings and every weekly result.",
                   crumbs=[("Home", "/"), ("Seasons", "/seasons/"), (f"Season {season}", f"/seasons/{season}/")])

    def bracket(self, season: int, standings: list[dict[str, Any]]) -> str:
        """The playoff rounds, one column per playoff week. Games between two playoff seeds only (when seeds are known)."""
        seeds = {r["key"]: r["rank"] for r in standings}
        by_week: dict[int, list[Game]] = {}
        for g in self.games(season):
            if not g.playoff:
                continue
            if seeds and not (seeds.get(g.away, 99) <= PLAYOFF_TEAMS and seeds.get(g.home, 99) <= PLAYOFF_TEAMS):
                continue
            by_week.setdefault(g.week, []).append(g)
        if not by_week:
            return ""
        weeks = sorted(by_week)
        names = ["Championship", "Semifinals", "Quarterfinals"]
        h = self.honors(season)
        cols = []
        for i, week in enumerate(weeks):
            from_end = len(weeks) - 1 - i
            name = names[from_end] if from_end < len(names) else f"Round {i + 1}"
            games = by_week[week]
            last = from_end == 0
            if last:
                games = sorted(games, key=lambda g: 0 if h.get("champion") in (g.away, g.home) else 1)
            blocks = []
            for n, g in enumerate(games):
                title = ""
                if last and n == 1:
                    title = f'<h3>{"Third place" if h.get("third_place") in (g.away, g.home) or not h else "Also played"}</h3>'
                side = lambda k, s: (f'<div class="{"w" if g.winner == k else ""}"><span class="seed">{esc(seeds.get(k, ""))}</span>'  # noqa: E731
                                     f'<span>{self.link(k)}</span><span class="s">{esc(score(s))}</span></div>')
                final = " final" if last and n == 0 else ""
                blocks.append(f'{title}<div class="match{final}">{side(g.away, g.away_score)}{side(g.home, g.home_score)}</div>')
            cols.append(f'<div class="round"><h3>{esc(name)}, week {week}</h3>{"".join(blocks)}</div>')
        rounds = len(cols)
        cls = f" r{rounds}" if rounds in (1, 2, 4) else ""
        return f'<div class="scroll"><div class="bracket{cls}">{"".join(cols)}</div></div>'

    def week_blocks(self, season: int) -> str:
        by_week: dict[int, list[Game]] = {}
        playoff: dict[int, bool] = {}
        for g in self.games(season):
            by_week.setdefault(g.week, []).append(g)
            playoff[g.week] = playoff.get(g.week, False) or g.playoff
        out = []
        latest = max(by_week) if by_week else None
        for week in sorted(by_week, reverse=True):
            rows = []
            for g in by_week[week]:
                aw, hw = g.winner == g.away, g.winner == g.home
                rows.append([f'<span class="won">{self.who(g.away)}</span>' if aw else self.who(g.away),
                             f'<span class="big">{esc(score(g.away_score))}</span>' if aw else esc(score(g.away_score)),
                             f'<span class="big">{esc(score(g.home_score))}</span>' if hw else esc(score(g.home_score)),
                             f'<span class="won">{self.who(g.home)}</span>' if hw else self.who(g.home)])
            top_v, top_k = max(((g.away_score, g.away) for g in by_week[week]), key=lambda s: s[0])
            top_v2, top_k2 = max(((g.home_score, g.home) for g in by_week[week]), key=lambda s: s[0])
            if top_v2 > top_v:
                top_v, top_k = top_v2, top_k2
            title = f"Week {week}" + (", playoffs" if playoff[week] else "")
            opened = " open" if week == latest else ""
            out.append(f'<details id="week-{week}"{opened}><summary><span class="k">{esc(title)}</span>'
                       f'<span class="d">High score: {esc(self.hist.name(top_k))}, {esc(score(top_v))}</span></summary>'
                       f'<div class="inner">{table(["Away", "Score", "Score", "Home"], rows, num={1, 2})}</div></details>')
        return "\n".join(out)

    # --- franchises ---------------------------------------------------------------------
    def jersey_grid(self, current: str | None = None) -> str:
        items = "".join(f'<li><a href="{self.furl(p["key"])}"{" aria-current=page" if p["key"] == current else ""}>'
                        f'{self.jersey(p["key"], 2)}<span>{esc(p["name"])}</span></a></li>' for p in self.profiles)
        return f'<ul class="jerseys">{items}</ul>'

    def franchises(self) -> None:
        rows = []
        for p in self.profiles:
            rows.append([self.who(p["key"]), esc(p["owner"] or "To be announced"),
                         esc(f"Season {p['founded']}") if p.get("founded") else "—",
                         esc(len(p["titles"])), esc(p["lifetime"])])
        body = self.head("Franchises", "The franchises of the BLHA, their owners and their records.")
        if rows:
            body += (f'<div class="band flush"><div class="in">'
                     + window("Every franchise", table(["Franchise", "Owner", "Founded", "Titles", "Lifetime W-L-T"], rows, num={3}),
                              small=plural(len(rows), "franchise"))
                     + f'</div></div><section class="band dark" aria-labelledby="pick">'
                     f'<div class="in">{sec_head("Pick a jersey", "pick")}{self.jersey_grid()}</div></section>')
        else:
            body += f'<div class="band flush"><div class="in">{empty("No franchises recorded yet.")}</div></div>'
        self.write("franchises/index.html", "Franchises", body, section="franchises",
                   crumbs=[("Home", "/"), ("Franchises", "/franchises/")])
        for p in self.profiles:
            self.franchise_page(p)

    def franchise_page(self, p: dict[str, Any]) -> None:
        hist, key = self.hist, p["key"]
        s = self.fslug(key)
        owner = f"Owner {esc(p['owner'])}." if p["owner"] else "Owner to be announced."
        founded = f" Founded Season {esc(p['founded'])}." if p.get("founded") else ""
        art = (f'<img class="logo-img" src="{self.asset(self.logos[key])}" width="108" height="108" alt="">'
               if key in self.logos else self.jersey(key, 6))
        presidents = sum(1 for h in hist.records.seasons.values() if h.get("presidents_trophy") == key)
        finishes = []
        season_rows = []
        for season in sorted(hist.seasons, reverse=True):
            standings, _ = self.standings(season)
            mine = next((r for r in standings if r["key"] == key), None)
            if not mine:
                continue
            live = self.in_progress(season)
            if not live and not self.is_test(season):
                finishes.append(mine["rank"])
            won = [label for a, label in AWARDS.items() if self.honors(season).get(a) == key]
            season_rows.append([self.season_link(season), f'<span class="rank">{esc(ordinal(mine["rank"]))}</span>',
                                esc(mine["record"]) + ('<span class="tag">So far</span>' if live else ""),
                                esc(score(mine["pf"])), "".join(f'<span class="tag gold">{esc(w)}</span>' for w in won)])
        stats = [("Titles", str(len(p["titles"]))), ("Presidents'", str(presidents)), ("Lifetime", p["lifetime"]),
                 ("Best finish", ordinal(min(finishes)) if finishes else "—")]
        stats_html = '<ul class="stats">' + "".join(f'<li><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></li>'
                                                    for k, v in stats) + "</ul>"
        hero = (f'<section class="fhero f-{s}"><div class="in">{art}'
                f'<div><h1>{esc(p["name"])}</h1><p class="sub">{owner}{founded}</p></div>{stats_html}</div></section>\n')
        parts = []
        banners = []
        for season, h in sorted(hist.records.seasons.items()):
            if h.get("champion") == key:
                banners.append(self.banner(season, "champion", key))
            if h.get("presidents_trophy") == key:
                banners.append(self.banner(season, "presidents_trophy", key))
        banner_html = f'<ol class="banners small" aria-label="Banners">{"".join(banners)}</ol>' if banners else ""
        rival = (f"{esc(p['rival'])} ({esc(p['rival_record'])}, {esc(p['rival_kind'])})" if p.get("rival")
                 else '<span class="muted">To be decided</span>')
        honors = "; ".join(f"{label} {', '.join(map(str, years))}" for label, years in p["awards"].items()
                            if label not in ("BLHA Champion", "Presidents' Trophy"))
        facts = [("Lifetime", f"{esc(p['lifetime'])} in {esc(plural(p['games'], 'game'))}"),
                 ("Championships", esc(f"{len(p['titles'])} ({', '.join(map(str, p['titles']))})" if p["titles"] else "None yet")),
                 ("Dynasty Pot", f"{self.coins(p['dynasty_count'], p['titles_to_win'])} {esc(p['dynasty_count'])} of "
                                 f"{esc(p['titles_to_win'])} this cycle"),
                 ("Rival", rival)]
        if honors:
            facts.append(("Other honors", esc(honors)))
        facts_win = window("Franchise file", '<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>")
        top = f'<div class="grid g-1-1"><div>{banner_html}</div>{facts_win}</div>' if banner_html else facts_win
        parts.append(top)
        parts.append(window("Season by season", table(["Season", "Finish", "W-L-T", "Points for", "Honors"], season_rows, num={1, 3})
                            if season_rows else empty("No finished week yet.")))

        rows = []
        for other, rec in sorted(self.h2h.opponents(key).items(), key=lambda kv: (-kv[1].games, natural(hist.name(kv[0])))):
            if not rec.games:
                continue
            last = f"Season {rec.last[0]}, Week {rec.last[1]}" if rec.last else ""
            rows.append([self.who(other), esc(rec.text), esc(rec.games),
                         esc(f"{rec.points_for:.1f}–{rec.points_against:.1f}"), esc(last)])
        games = sum(r.games for r in self.h2h.opponents(key).values())
        h2h_win = window("Head-to-head", table(["Opponent", "W-L-T", "Games", "Points", "Last met"], rows, num={2})
                         if rows else empty("No games played yet."), small=plural(games, "game"),
                         foot='<a href="/head-to-head/">Every matchup</a>')

        trades = [t for t in reversed(hist.trades()) if any(hist.franchise(team) == key for team in t["teams"])]
        if trades:
            items = []
            for t in trades:
                mine = [team for team in t["teams"] if hist.franchise(team) == key]
                got = [hist.asset(a) for team in mine for a in t["received"].get(team, [])]
                gave = [hist.asset(a) for team in mine for a in t["sent"].get(team, [])]
                partners = [self.who(hist.franchise(team)) for team in t["teams"] if hist.franchise(team) != key]
                items.append(f'<li><div class="t-top"><a href="/trades/#{esc(t["id"])}">{esc(hist.event_date(t))}</a>'
                             f'<span>with {", ".join(partners)}</span></div><dl><dt>Received</dt><dd>{esc(", ".join(got) or "Nothing")}</dd>'
                             f'<dt>Sent</dt><dd>{esc(", ".join(gave) or "Nothing")}</dd></dl></li>')
            trades_body = f'<ol class="tlist">{"".join(items)}</ol>'
        else:
            trades_body = empty("No trades recorded yet.")
        trades_win = window("Trades", trades_body, small=f"{len(trades)} recorded", foot='<a href="/trades/">Trade trees</a>')
        parts += [h2h_win, trades_win]

        picks = []
        for year, d in sorted(hist.drafts().items(), reverse=True):
            for pk in d.get("picks") or []:
                if hist.franchise(pk["team"]) == key:
                    picks.append([f'<a href="/drafts/#draft-{esc(year)}">{esc(year)}</a>',
                                  esc(f"{pk['round']}.{int(pk['in_round']):02d}"), esc(pk["overall"]),
                                  esc(hist.player(pk["player"])) if pk.get("player") else '<span class="muted">Not made</span>'])
        parts.append(window("Draft picks", table(["Draft", "Pick", "Overall", "Player"], picks, num={2}) if picks
                            else empty("No completed draft recorded yet."), small=plural(len(picks), "pick")))
        body = (f'<div class="band"><div class="in stack">{"".join(parts)}</div></div>'
                f'<section class="band dark" aria-labelledby="others"><div class="in">{sec_head("All franchises", "others")}'
                f'{self.jersey_grid(key)}</div></section>')
        self.write(f"franchises/{s}/index.html", p["name"], body, section="franchises",
                   description=f"{p['name']} of the BLHA: championships, season-by-season record, head-to-head, trades and draft picks.",
                   crumbs=[("Home", "/"), ("Franchises", "/franchises/"), (p["name"], self.furl(key))], before_main=hero)

    # --- head-to-head -------------------------------------------------------------------
    def head_to_head(self) -> None:
        hist, h2h = self.hist, self.h2h
        parts = []
        declared = declared_rivals(hist)
        if declared:
            parts.append(window("Declared rivalries", table(
                ["Rivalry", "Record (first named)", "Games"],
                [[f"{self.who(a)} vs {self.who(b)}", esc(h2h.record(a, b).text), esc(h2h.record(a, b).games)] for a, b in declared],
                num={2})))
        keys = sorted(h2h.franchises(), key=lambda k: natural(hist.name(k)))
        played = [k for k in keys if h2h.lifetime(k).games]
        if played:
            rows = []
            for k in played:
                rival = h2h.earned_rival(k)
                rec = h2h.record(k, rival) if rival else None
                rows.append([self.who(k), self.link(rival) if rival else "—", esc(rec.text if rec else ""),
                             esc(rec.games if rec else 0), esc(h2h.lifetime(k).text)])
            parts.append(window("Earned rivals", table(["Franchise", "Rival", "Record vs rival", "Games", "Lifetime"], rows, num={3}),
                                small="Most-played opponent"))
            head = '<th scope="col">Franchise</th>' + "".join(
                f'<th scope="col"><abbr title="{esc(hist.name(k))}">{i}</abbr></th>' for i, k in enumerate(played, 1))
            body = ""
            for i, a in enumerate(played, 1):
                cells = "".join('<td class="self">—</td>' if a == b else
                                f"<td>{esc(h2h.record(a, b).text) if h2h.record(a, b).games else ''}</td>" for b in played)
                body += f"<tr><td>{i}. {self.link(a)}</td>{cells}</tr>"
            parts.append(window("Every matchup", '<p class="note">Each row is that franchise\'s record against the numbered '
                                "franchise in each column. Columns follow the same order as the rows.</p>"
                                f'<div class="scroll"><table class="matrix"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'))
            pairs = []
            for i, a in enumerate(played):
                for b in played[i + 1:]:
                    r = h2h.record(a, b)
                    if r.games:
                        last = f"Season {r.last[0]}, Week {r.last[1]}" if r.last else ""
                        pairs.append((r.games, [f"{self.link(a)} vs {self.link(b)}", esc(r.games), esc(r.text),
                                                esc(f"{r.points_for:.1f}–{r.points_against:.1f}"), esc(last)]))
            pairs.sort(key=lambda p: -p[0])
            parts.append(window("Most-played pairings", table(["Pairing", "Games", "Record (first named)", "Points", "Last met"],
                                                             [p[1] for p in pairs], num={1})))
        else:
            parts.append(window("Earned rivals", empty("No week has finished yet, so there are no head-to-head records.")))
        body = (self.head("Head-to-head", "Lifetime records from every finished week, regular season and playoffs. A franchise's "
                          "earned rival is the opponent it has played most, with the closest record breaking ties.")
                + f'<div class="band flush"><div class="in stack">{"".join(parts)}</div></div>')
        self.write("head-to-head/index.html", "Head-to-head", body, section="head-to-head",
                   crumbs=[("Home", "/"), ("Head-to-head", "/head-to-head/")])

    # --- trades -------------------------------------------------------------------------
    def tree_html(self, node: Node) -> str:
        def item(n: Node) -> str:
            kids = "<ul>" + "".join(item(c) for c in n.children) + "</ul>" if n.children else ""
            out = f' <span class="out">— {esc(n.outcome)}</span>' if n.outcome else ""
            return f"<li>{esc(n.label)}{out}{kids}</li>"

        kids = "".join(item(c) for c in node.children) or '<li class="out">Nothing recorded</li>'
        return f'<h3>{esc(node.label)} <span class="muted">{esc(node.outcome)}</span></h3><ul class="tree">{kids}</ul>'

    def trades(self) -> None:
        hist = self.hist
        trades = list(reversed(hist.trades()))
        if trades:
            blocks = []
            for t in trades:
                sides = "; ".join(f"{hist.name(hist.franchise(team))} received "
                                  f"{', '.join(hist.asset(a) for a in t['received'].get(team, [])) or 'nothing'}"
                                  for team in t["teams"])
                trees = "".join(self.tree_html(node) for node in trade_trees(hist, t["id"]).values())
                flag = ('<p class="note">One-sided: possibly a drop and a claim between two daily looks rather than a trade.</p>'
                        if t.get("one_sided") else "")
                blocks.append(f'<details id="{esc(t["id"])}"><summary><span class="k">{esc(hist.event_date(t))}</span>'
                              f'<span class="d">{esc(sides)}</span></summary><div class="inner">{flag}{trees}</div></details>')
            log = window("Trade log", f'<div class="acc">{"".join(blocks)}</div>', small=plural(len(trades), "trade"))
        else:
            log = window("Trade log", empty("No trades recorded yet."))
        moves = [e for e in hist.events() if e.get("type") in ("add", "drop")][-150:]
        if moves:
            rows = [[esc(hist.event_date(e)), self.who(hist.franchise(e["team"])), esc("Added" if e["type"] == "add" else "Dropped"),
                     esc(hist.player(e["player"]))] for e in reversed(moves)]
            adds = window("Adds and drops", table(["Seen", "Franchise", "Move", "Player"], rows), small="The latest 150 moves")
        else:
            adds = window("Adds and drops", empty("No adds or drops recorded yet."))
        body = (self.head("Trades", "Trades are recorded from a daily look at Fantrax and dated the day they were first seen. "
                          "Open a trade to follow its trade tree: what each side received and what those players and picks became.")
                + f'<div class="band flush"><div class="in stack">{log}{adds}</div></div>')
        self.write("trades/index.html", "Trades", body, section="trades", crumbs=[("Home", "/"), ("Trades", "/trades/")])

    # --- drafts -------------------------------------------------------------------------
    def drafts(self) -> None:
        hist = self.hist
        drafts = hist.drafts()
        parts = []
        if not drafts:
            parts.append(window("Draft boards", empty("No completed draft has been archived yet.")))
        for year in sorted(drafts, reverse=True):
            d = drafts[year]
            inner = ""
            retro = hist.archive.retro(int(d["season"]))
            if retro:
                from history.retro import highlight_lines

                as_of = hist.date(retro.get("as_of"))
                rows = "".join(f"<dt>{esc(label.capitalize())}</dt><dd>{inline(text)}</dd>" for label, text in highlight_lines(retro))
                inner += (f'<h3 class="sr">Retrospective</h3><p class="note">Retrospective, as of {esc(as_of)}.</p>'
                          f'<dl class="retro">{rows}</dl><p class="note">{esc(retro.get("measure", ""))}</p>')
            rows = [[esc(f"{p['round']}.{int(p['in_round']):02d}"), esc(p["overall"]), self.who(hist.franchise(p["team"])),
                     esc(hist.player(p["player"])) if p.get("player") else '<span class="muted">Not made</span>']
                    for p in d.get("picks") or []]
            inner += (f'<div class="acc"><details><summary><span class="k">Full draft board ({len(rows)} picks)</span></summary>'
                      f'<div class="inner">{table(["Pick", "Overall", "Franchise", "Player"], rows, num={1})}</div></details></div>')
            parts.append(window(f"{year} Draft", inner, ident=f"draft-{year}", small=plural(len(rows), "pick")))
        body = (self.head("Drafts", "Every draft board, and how each class turned out.")
                + f'<div class="band flush"><div class="in stack">{"".join(parts)}</div></div>')
        self.write("drafts/index.html", "Drafts", body, section="drafts", crumbs=[("Home", "/"), ("Drafts", "/drafts/")])

    # --- records ------------------------------------------------------------------------
    def records(self) -> None:
        games = self.all_games()
        head = self.head("League records", "The highs and lows of every finished week, regular season and playoffs. "
                         "When two are equal, the earlier one ranks first.")
        crumbs = [("Home", "/"), ("Records", "/records/")]
        if not games:
            body = head + (f'<div class="band flush"><div class="in">'
                           f'{window("Single week", empty("No week has finished yet, so there are no records."))}</div></div>')
            self.write("records/index.html", "Records", body, section="records", crumbs=crumbs)
            return
        sides = [(g.away_score, g.away, g.home, g) for g in games] + [(g.home_score, g.home, g.away, g) for g in games]

        def first(items: list, key: Callable, n: int = 5) -> list:
            return sorted(items, key=key)[:n]

        def ranked(rows: list[list[str]]) -> list[list[str]]:
            return [[f'<span class="rank">{esc(ordinal(i))}</span>', *r] for i, r in enumerate(rows, 1)]

        high = ranked([[self.who(k), f'<span class="big">{esc(score(v))}</span>', self.link(o), self.when(g)]
                       for v, k, o, g in first(sides, lambda s: (-s[0], s[3].season, s[3].week))])
        low = ranked([[self.who(k), f'<span class="big">{esc(score(v))}</span>', self.link(o), self.when(g)]
                      for v, k, o, g in first([s for s in sides if s[0] > 0], lambda s: (s[0], s[3].season, s[3].week))])
        week = [f'<div class="grid g-1-1">'
                f'{window("Highest scores", table(["#", "Franchise", "Score", "Opponent", "When"], high, num={0, 2}), small="Single week")}'
                f'{window("Lowest scores", table(["#", "Franchise", "Score", "Opponent", "When"], low, num={0, 2}), small="Single week")}</div>']
        decided = [g for g in games if g.winner]
        pair = []
        if decided:
            rows = ranked([[self.who(g.winner), f'<span class="big">{esc(score(g.margin))}</span>', self.link(g.loser),
                            f'{esc(score(max(g.away_score, g.home_score)))}–{esc(score(min(g.away_score, g.home_score)))}',
                            self.when(g)] for g in first(decided, lambda g: (-g.margin, g.season, g.week))])
            pair.append(window("Biggest wins", table(["#", "Winner", "Margin", "Loser", "Score", "When"], rows, num={0, 2}),
                               small="Single week"))
        rows = ranked([[f"{self.link(g.away)} vs {self.link(g.home)}", f'<span class="big">{esc(score(g.margin))}</span>',
                        f'{esc(score(g.away_score))}–{esc(score(g.home_score))}', self.when(g)]
                       for g in first(games, lambda g: (g.margin, g.season, g.week))])
        pair.append(window("Closest games", table(["#", "Game", "Margin", "Score", "When"], rows, num={0, 2}), small="Single week"))
        week.append(f'<div class="grid g-1-1">{"".join(pair)}</div>')

        totals = []
        for season in self.hist.seasons:
            if not self.games(season):
                continue
            rows_s, _ = self.standings(season)
            for r in rows_s:
                w, l, t = (int(x) for x in (r["record"].split("-") + ["0", "0"])[:3])
                n = w + l + t
                totals.append({"season": season, "key": r["key"], "pf": r["pf"], "pct": (w + 0.5 * t) / n if n else 0,
                               "record": r["record"], "final": not self.in_progress(season)})
        if totals:
            done = [t for t in totals if t["final"]] or totals
            most = ranked([[self.who(t["key"]), f'<span class="big">{esc(score(t["pf"]))}</span>', self.season_link(t["season"])]
                           for t in first(done, lambda t: (-t["pf"], t["season"]))])
            best = ranked([[self.who(t["key"]), esc(t["record"]), self.season_link(t["season"])]
                           for t in first(done, lambda t: (-t["pct"], -t["pf"], t["season"]))])
            note = ('<p class="note">No regular season has finished yet, so these use the Season in progress.</p>'
                    if not any(t["final"] for t in totals) else "")
            week.append(f'<div class="grid g-1-1">'
                        f'{window("Most points in a regular season", table(["#", "Franchise", "Points for", "Season"], most, num={0, 2}) + note, small="Single season")}'
                        f'{window("Best regular-season records", table(["#", "Franchise", "W-L-T", "Season"], best, num={0}), small="Single season")}</div>')
        body = head + f'<div class="band flush"><div class="in stack">{"".join(week)}</div></div>'
        self.write("records/index.html", "Records", body, section="records", crumbs=crumbs)

    # --- constitution -------------------------------------------------------------------
    def constitution_page(self) -> None:
        crumbs = [("Home", "/"), ("Constitution", "/constitution/")]
        if not self.constitution:
            body = (self.head("The Constitution", "The rules of the BLHA, and every change to them.")
                    + f'<div class="band flush"><div class="in">{empty("The Constitution has not been published yet.")}</div></div>')
            self.write("constitution/index.html", "Constitution", body, section="constitution", crumbs=crumbs)
            return
        text, items = self.constitution
        links = "".join(f'<li><a href="#{a}">' + (f'<span class="no">{esc(n)}</span>' if n else "") + f"{esc(t)}</a></li>"
                        for a, n, t in items)
        log = ""
        amendments = 0
        if CHANGELOG.exists():
            raw = CHANGELOG.read_text(encoding="utf-8")
            amendments = len(re.findall(r"^## Amended ", raw, re.M))
            log_html, _ = markdown(raw, shift=1)
            log_html = re.sub(r"<h2[^>]*>.*?</h2>", "", log_html, count=1)
            log = (f'<div class="acc changelog"><details id="changelog"><summary><span class="k">Changelog</span>'
                   f'<span class="d">Every amendment, newest first</span></summary><div class="inner doc">{log_html}</div></details></div>')
            links = '<li><a href="#changelog">Changelog</a></li>' + links
        articles = sum(1 for _, n, _ in items if n)
        meta = [plural(articles, "article"), plural(amendments, "amendment") if amendments else "No amendments yet"]
        extra = '<ul class="meta">' + "".join(f"<li>{esc(m)}</li>" for m in meta) + "</ul>"
        pdf = (f'<nav class="pager" aria-label="Download"><a class="btn" href="{self.asset("BLHA_Constitution.pdf")}">'
               f'&#9660; Download PDF</a></nav>' if self.has_pdf else "")
        body = (f'<div class="con">{self.head("The Constitution", "The rules of the " + esc(LEAGUE_NAME) + ", and every change to them.", pager=pdf, extra=extra)}'
                f'<div class="in"><div class="con-layout"><nav class="toc" aria-label="Contents"><h2>Contents</h2><ol>{links}</ol></nav>'
                f'<div><details class="toc-mobile"><summary>Contents</summary><ol>{links}</ol></details>'
                f'{log}<article class="doc">{text}</article>'
                f'<a class="btn top-btn" href="#main">&#9650; Top</a></div></div></div></div>')
        self.write("constitution/index.html", "Constitution", body, section="constitution",
                   description="The Constitution of the Beer League Hockey Association, with its changelog.", crumbs=crumbs)

    # --- the rest -----------------------------------------------------------------------
    def not_found(self) -> None:
        body = ('<section class="in missing"><h1>That page isn\'t in the record book</h1>'
                '<p class="lede">The address may have a typo, or the page may have moved.</p>'
                '<p><a class="btn" href="/">&#9664; League history home</a></p></section>')
        self.write("404.html", "Page not found", body)

    def extras(self) -> None:
        robots = "User-agent: *\nAllow: /\n"
        if self.base:
            robots += f"Sitemap: {self.base}/sitemap.xml\n"
            urls = "".join(f"<url><loc>{esc(self.base + '/' + p[: -len('index.html')])}</loc></url>"
                           for p in self.pages if p.endswith("index.html"))
            (self.out / "sitemap.xml").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
        (self.out / "robots.txt").write_text(robots, encoding="utf-8")
        # Cloudflare Pages reads _headers: long caching for versioned assets, strict security headers.
        (self.out / "_headers").write_text(
            "/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n"
            "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
            "  X-Frame-Options: DENY\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n"
            "  Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'\n", encoding="utf-8")

    def build(self) -> list[str]:
        self.out.mkdir(parents=True, exist_ok=True)
        self.assets()
        for step in (self.home, self.seasons, self.franchises, self.head_to_head, self.trades, self.drafts,
                     self.records, self.constitution_page, self.not_found):
            step()
        self.extras()
        return list(self.pages)


# --- data helpers --------------------------------------------------------------------

def computed_standings(hist: LeagueHistory, season: int) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Regular-season table from final weekly scores, for a season without saved final standings."""
    table_rows: dict[str, dict[str, Any]] = {}
    through = 0
    for key, week in hist.archive.results(season).items():
        if week.get("playoff") or not week.get("played", True):
            continue
        through = max(through, int(week.get("period") or key))
        for m in week.get("matchups") or []:
            for me, them in (("away", "home"), ("home", "away")):
                k = hist.franchise(m[me]["team"])
                row = table_rows.setdefault(k, {"w": 0, "l": 0, "t": 0, "pf": 0.0})
                a, b = m[me]["score"], m[them]["score"]
                row["w" if a > b else "l" if a < b else "t"] += 1
                row["pf"] += a
    for row in table_rows.values():
        games = row["w"] + row["l"] + row["t"]
        row["pct"] = (row["w"] + 0.5 * row["t"]) / games if games else 0
        row["text"] = f"{row['w']}-{row['l']}-{row['t']}"
    ordered = sorted(table_rows.items(), key=lambda kv: (-kv[1]["pct"], -kv[1]["pf"], hist.name(kv[0]).lower()))
    return ordered, through


def shrink(source: Path, target: Path, width: int | None, smooth: bool = False) -> bool:
    """Write a smaller copy with Pillow (False if Pillow is not installed). Pixel art is resized with
    nearest-neighbor so every art pixel stays a hard-edged square; franchise logos are smoothed."""
    try:
        from PIL import Image
    except ImportError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.convert("RGBA")
        if width and img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS if smooth else Image.NEAREST)
        img.save(target, optimize=True)
    return True


def social_card(target: Path) -> bool:
    """The 1200x630 picture shown when a link to the site is shared: the 8-bit title screen with the
    BLHA lockup, LEAGUE HISTORY and the ice resurfacer (False without Pillow)."""
    try:
        from PIL import Image
        sys.path.insert(0, str(ROOT / "tools"))
        import blha_pixel as px
    except ImportError:
        return False
    k, aw, ah = 5, 240, 126
    a = px.bg_plain(aw, ah, px.BLACK)
    px.dither(a, 0, 2, aw, 40, px.CHARCOAL, down=False)
    ice_h, top = 34, ah - 2 - 34 - 6
    iy = top + 6
    px.rect(a, 0, top, aw, 1, px.STEEL_DK)
    px.rect(a, 0, top + 1, aw, 1, px.STEEL)
    px.rect(a, 0, top + 2, aw, 3, px.PAPER)
    px.rect(a, 0, top + 5, aw, 1, px.GOLD)
    px.rect(a, 0, iy, aw, ice_h, px.ICE)
    px.rect(a, aw // 2 - 1, iy, 2, ice_h, px.RED)
    px.rect(a, round(aw * .3) - 1, iy, 2, ice_h, px.BLUE)
    px.rect(a, round(aw * .7) - 1, iy, 2, ice_h, px.BLUE)
    px.rect(a, 0, iy + ice_h - 6, 150, 6, (248, 251, 253))  # fresh ice behind the resurfacer
    pal = {ch: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for ch, c in RESURFACER_PAL.items()}
    for y, row in enumerate(RESURFACER[0]):
        for x, ch in enumerate(row):
            if ch in pal:
                a.putpixel((150 + x, iy + ice_h - 29 + y), pal[ch])
    px.rect(a, 0, 0, aw, 2, px.GOLD)
    px.rect(a, 0, ah - 2, aw, 2, px.GOLD)
    img = px.enlarge(a, k, (1200, 630))
    px.place(img, px.lockup(18, 3), 600, 150, snap=3)
    px.draw_text(img, "LEAGUE HISTORY", "silk-bold", 5, 600, 300, px.GOLD, align="c", shadow=px.BLACK)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(target, optimize=True)
    return True


def site_url(league: dict[str, Any]) -> str:
    """history_site.url from league.yaml: the site's own address, or "" until a domain is set."""
    url = str((league.get("history_site") or {}).get("url") or "").strip().rstrip("/")
    if url and not re.fullmatch(r"https://[a-z0-9.-]+\.[a-z]{2,}", url, re.IGNORECASE):
        raise ValueError(f"history_site.url must look like https://example.com (got {url!r})")
    return url


def build(archive: Path | None, out: Path, *, records: Records | None = None, league: dict[str, Any] | None = None,
          now: datetime | None = None) -> list[str]:
    if league is None:
        league = load_league()
    hist = LeagueHistory(Archive(archive or default_dir()), records=records, league=league)
    if out.exists():
        shutil.rmtree(out)
    return Site(hist, out, now or datetime.now(timezone.utc), site_url(league)).build()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=None, help="archive folder (default: $BLHA_ARCHIVE_DIR or archive/)")
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    pages = build(args.archive, args.out)
    archive = args.archive or default_dir()
    seasons = Archive(archive).all_seasons()
    print(f"Built {len(pages)} pages into {args.out} from {archive} "
          f"({len(seasons)} archived season{'s' if len(seasons) != 1 else ''}: {', '.join(map(str, seasons)) or 'none'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
