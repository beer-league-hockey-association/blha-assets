#!/usr/bin/env python3
"""Build the BLHA league history website into site/.

A standalone static site (HTML and CSS, no JavaScript): every page, image and
font is served from the site's own address and nothing points anywhere else.
It reads the league archive (the automation-state branch's archive/ folder),
automation/history/history.yaml, automation/league.yaml (history_site) and the
Constitution (constitution/BLHA_Constitution.md and CHANGELOG.md), and builds
cleanly from an empty archive. The BLHA History Site workflow publishes the
folder to Cloudflare Pages.

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
from history.context import LeagueHistory, initials, natural, ordinal  # noqa: E402
from history.profiles import DEFAULT_COLORS, dynasty_summary, franchise_profiles  # noqa: E402
from history.records import AWARDS, Records, money  # noqa: E402
from history.rivals import HeadToHead, declared_rivals  # noqa: E402
from history.store import Archive, default_dir  # noqa: E402
from history.trades import Node, trade_trees  # noqa: E402

CONSTITUTION = ROOT / "constitution" / "BLHA_Constitution.md"
CHANGELOG = ROOT / "constitution" / "CHANGELOG.md"
FONTS = ROOT / "brand" / "fonts" / "archivo"
KIT = ROOT / "brand" / "kit"
# (output name, source, width to shrink to)
IMAGES = [
    ("favicon.png", KIT / "02_avatars_icons" / "blha-favicon-256.png", 64),
    ("apple-touch-icon.png", KIT / "01_logos" / "blha-b-icon-charcoal-1024.png", 180),
    ("b-mark.png", KIT / "01_logos" / "blha-b-mark-transparent-1024.png", 160),
]
FONT_FILES = ["archivo.woff", "archivo-italic.woff"]
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


# --- small helpers -----------------------------------------------------------------

def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "section"


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def long_date(when: datetime) -> str:
    return f"{when.strftime('%B')} {when.day}, {when.year}"


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


def table(head: list[str], rows: list[list[str]], *, num: Iterable[int] = (), cls: str = "", caption: str = "") -> str:
    """Rows are already-escaped HTML cells."""
    num = set(num)
    th = "".join(f'<th scope="col" class="num">{esc(h)}</th>' if i in num else f'<th scope="col">{esc(h)}</th>'
                 for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="num">{c}</td>' if i in num else f"<td>{c}</td>"
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    cls_attr = f' class="{cls}"' if cls else ""
    return f'<div class="scroll"><table{cls_attr}>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def empty(text: str) -> str:
    return f'<p class="empty">{esc(text)}</p>'


def pips(count: int, need: int) -> str:
    dots = "".join('<i class="on"></i>' if i < count else "<i></i>" for i in range(max(need, count)))
    return f'<span class="pips" role="img" aria-label="{count} of {need}">{dots}</span>'


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


# --- stylesheet --------------------------------------------------------------------

CSS = """
@font-face{font-family:"Archivo";src:url("{font_upright}") format("woff");font-weight:100 900;font-stretch:62% 125%;font-style:normal;font-display:swap}
@font-face{font-family:"Archivo";src:url("{font_italic}") format("woff");font-weight:100 900;font-stretch:62% 125%;font-style:italic;font-display:swap}
:root{--ice:#F2F5F7;--ice-2:#E5EBEF;--boards:#2B2D31;--boards-2:#3A3D43;--gold:#FFB81C;--cream:#F4EFE4;--line:#C9D3DA;--ink:#2B2D31;--muted:#545B64;--steel:#9AA1A9}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:16px}
body{margin:0;background:var(--ice);color:var(--ink);font-family:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:1.0625rem;line-height:1.55;font-weight:400;font-stretch:100%}
img{max-width:100%}
a{color:inherit;text-decoration-line:underline;text-decoration-color:var(--gold);text-decoration-thickness:2px;text-underline-offset:3px}
a:hover{text-decoration-color:currentColor}
:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.boards :focus-visible,.rafters :focus-visible,.fhero :focus-visible{outline-color:var(--gold)}
.skip{position:absolute;left:-9999px;top:8px;background:var(--gold);color:var(--boards);padding:8px 12px;font-weight:700;z-index:9}
.skip:focus{left:16px}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
.measure{max-width:68ch}
h1,h2,h3{font-weight:800;line-height:1.05;margin:0}
h1{font-stretch:62%;font-size:clamp(2.6rem,7vw,4.25rem);letter-spacing:-.005em}
h2{font-stretch:70%;font-size:clamp(1.65rem,3.4vw,2.15rem);margin:2.4rem 0 .9rem}
h3{font-stretch:85%;font-size:1.2rem;font-weight:700;margin:1.6rem 0 .5rem}
p{margin:0 0 1rem}
.lead{font-size:1.2rem;line-height:1.5;max-width:60ch}
.note{color:var(--muted);font-size:.95rem;max-width:68ch}
.subtitle{color:var(--muted);font-size:1.15rem;margin:.6rem 0 0}
.page-head{padding:2.6rem 0 .6rem}

/* the boards: site header, with the yellow kick plate along the bottom */
.boards{background:var(--boards);color:var(--cream);border-bottom:5px solid var(--gold)}
.boards.over-rafters{border-bottom:0}
.boards .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:4px 32px;padding-top:12px;padding-bottom:6px}
.brand{display:flex;align-items:center;gap:12px;color:var(--cream);text-decoration:none;padding:4px 0}
.brand img{width:44px;height:44px;display:block}
.brand b{display:block;font-stretch:62%;font-weight:800;font-size:1.7rem;line-height:1}
.brand span span{display:block;font-size:.8rem;color:#C4C8CE;line-height:1.3}
.nav{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
.nav ul{display:flex;gap:0 20px;list-style:none;margin:0;padding:0;white-space:nowrap}
.nav a{display:block;padding:10px 0 8px;color:var(--cream);text-decoration:none;font-weight:600;font-stretch:85%;border-bottom:3px solid transparent}
.nav a:hover{border-bottom-color:var(--steel)}
.nav a[aria-current]{border-bottom-color:var(--gold)}
@media (max-width:760px){.nav ul{flex-wrap:wrap;gap:0 16px;white-space:normal}.nav a{padding:6px 0 5px}}
@media (max-width:760px){td{white-space:nowrap}.page-head{padding-top:1.8rem}}

/* the rafters: championship banners */
.rafters{background:var(--boards);border-bottom:5px solid var(--gold);padding:0 0 34px}
.truss{height:34px;background:linear-gradient(var(--boards-2),var(--boards-2)) top/100% 4px no-repeat,linear-gradient(var(--boards-2),var(--boards-2)) bottom/100% 4px no-repeat,repeating-linear-gradient(45deg,transparent 0 21px,var(--boards-2) 21px 23px),repeating-linear-gradient(-45deg,transparent 0 21px,var(--boards-2) 21px 23px)}
.banners{display:flex;align-items:flex-start;gap:26px;list-style:none;margin:0;padding:0 2px 6px;overflow-x:auto;scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch}
.banner{flex:none;width:152px;position:relative;padding-top:40px;scroll-snap-align:start;transform-origin:50% 0}
.banner::before{content:"";position:absolute;top:0;left:26px;right:26px;height:40px;border-left:2px solid var(--steel);border-right:2px solid var(--steel)}
.rod{display:block;height:7px;border-radius:4px;background:#AEB4BB;margin:0 -7px}
.cloth{display:flex;flex-direction:column;align-items:center;text-align:center;gap:10px;min-height:268px;padding:16px 12px 54px;background:var(--gold);color:var(--boards);clip-path:polygon(0 0,100% 0,100% 100%,50% 86%,0 100%)}
.cloth img{width:46px;height:46px}
.cloth .what{font-stretch:62%;font-weight:800;font-size:1rem;line-height:1.05;text-transform:uppercase;letter-spacing:.07em;padding-bottom:9px;border-bottom:2px solid currentColor}
.cloth .team{font-stretch:75%;font-weight:750;font-size:1.15rem;line-height:1.08}
.cloth .year{margin-top:auto;font-stretch:62%;font-weight:900;font-size:3.5rem;line-height:.85}
.banner.cream{width:124px;padding-top:28px}
.banner.cream::before{height:28px;left:22px;right:22px}
.banner.cream .cloth{background:var(--cream);min-height:214px}
.banner.cream .year{font-size:2.6rem}
.banner.cream .team{font-size:1rem}
.banner.pending .cloth{background:repeating-linear-gradient(135deg,#35383D 0 10px,#303338 10px 20px);color:#C4C8CE}
.banner.pending .team{font-weight:500;font-stretch:85%}
.banner a{color:inherit;text-decoration:none;display:block}
.banner a:hover .team{text-decoration:underline;text-decoration-thickness:2px}
@media (prefers-reduced-motion:no-preference){
.rafters .banner{animation:hang 1.8s cubic-bezier(.25,.8,.3,1) both}
.rafters .banner:nth-child(2){animation-delay:.07s}.rafters .banner:nth-child(3){animation-delay:.14s}.rafters .banner:nth-child(4){animation-delay:.21s}
.rafters .banner:nth-child(5){animation-delay:.28s}.rafters .banner:nth-child(6){animation-delay:.35s}.rafters .banner:nth-child(n+7){animation-delay:.42s}
@keyframes hang{0%{transform:rotate(2.4deg)}40%{transform:rotate(-1.3deg)}70%{transform:rotate(.5deg)}100%{transform:rotate(0)}}
}
.banners.small{padding:0;gap:18px;overflow:visible;flex-wrap:wrap;margin:1.4rem 0 .4rem}
.banners.small .banner{width:112px;padding-top:0}
.banners.small .banner::before{display:none}
.banners.small .rod{margin:0 -5px}
.banners.small .cloth{min-height:176px;padding:12px 8px 40px;gap:7px}
.banners.small .cloth .what{font-size:.82rem}
.banners.small .cloth .team{font-size:1rem}
.banners.small .cloth .year{font-size:2.4rem}
.banners.small .banner.cream{width:96px}
.banners.small .banner.cream .cloth{min-height:150px;background:#E7DFCC}
.banners.small .banner.cream .year{font-size:2rem}
.banners.small .banner.cream .team{font-size:.9rem}

/* home */
.intro{padding:2.4rem 0 .4rem}
.home-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.9fr);gap:8px 56px;align-items:start}
.pot-amount{font-stretch:62%;font-weight:900;font-size:clamp(3.6rem,9vw,5.4rem);line-height:.85;margin:.2rem 0 .8rem;font-variant-numeric:tabular-nums}
.race{list-style:none;margin:1rem 0 0;padding:0}
.race li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--line)}
.more{font-weight:600}
@media (max-width:820px){.home-grid{grid-template-columns:minmax(0,1fr)}}

/* tables */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 0 1.6rem}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:1rem}
caption{text-align:left;font-weight:750;font-stretch:80%;font-size:1.15rem;padding:0 0 .5rem}
th{text-align:left;font-weight:700;font-stretch:85%;font-size:.9rem;color:var(--muted);padding:8px 14px 7px 0;border-bottom:2px solid var(--ink);white-space:nowrap;vertical-align:bottom}
td{padding:9px 14px 9px 0;border-bottom:1px solid var(--line);vertical-align:middle}
th:last-child,td:last-child{padding-right:0}
.num{text-align:right}
td a{text-decoration-color:var(--line);white-space:nowrap}
td a:hover{text-decoration-color:var(--gold)}
th.num,td.num{width:1%}
.nowrap{white-space:nowrap}
.tag{white-space:nowrap}
.match td:first-child{text-align:right}
.match th:first-child{text-align:right}
th.num{padding-left:14px}
td.num{padding-left:14px;white-space:nowrap}
.won{font-weight:700}
.muted{color:var(--muted)}
.tag{display:inline-block;font-size:.85rem;font-weight:600;color:var(--muted);margin-left:.45rem}
.matrix{width:auto}
.matrix th,.matrix td{text-align:center;padding:7px 9px;white-space:nowrap}
.matrix th:first-child,.matrix td:first-child{text-align:left;position:sticky;left:0;background:var(--ice);padding-left:0}
.matrix td.self{color:var(--steel)}
abbr[title]{text-decoration:none}

/* franchises */
.badge{display:inline-grid;place-items:center;flex:none;width:2.1rem;height:2.1rem;border-radius:50%;background:var(--fc,var(--gold));color:var(--fc-ink,var(--ink));box-shadow:inset 0 0 0 3px var(--fc2,transparent);font-weight:800;font-stretch:75%;font-size:.8rem;line-height:1;overflow:hidden}
.badge img{width:100%;height:100%;object-fit:contain;background:var(--boards)}
.badge.big{width:5.5rem;height:5.5rem;font-size:1.9rem;box-shadow:inset 0 0 0 5px var(--fc2,transparent),0 0 0 3px var(--fc-ink,var(--ink))}
.who{display:inline-flex;align-items:center;gap:.65rem}
.fhero{background:var(--fc,var(--boards));color:var(--fc-ink,var(--cream));border-bottom:6px solid var(--fc2,var(--gold))}
.fhero .wrap{display:flex;align-items:center;gap:22px;padding-top:2.2rem;padding-bottom:2rem}
.fhero .subtitle{color:inherit;opacity:.88}
.facts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:9px 24px;margin:1.8rem 0 0;max-width:680px}
.facts dt{font-weight:700;font-stretch:85%;color:var(--muted)}
.facts dd{margin:0}
.facts+.note{margin-top:1rem}
.record-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,500px),1fr));gap:0 48px}
.pips{display:inline-flex;gap:6px;vertical-align:middle}
.pips i{width:14px;height:14px;border-radius:50%;border:2px solid var(--steel);display:inline-block}
.pips i.on{background:var(--gold);border-color:#C68A00}

/* weeks, trades, drafts */
details{border-top:1px solid var(--line)}
details:last-of-type{border-bottom:1px solid var(--line)}
summary{cursor:pointer;padding:12px 0;font-weight:650;font-stretch:90%}
summary:hover{text-decoration:underline;text-decoration-color:var(--gold);text-decoration-thickness:2px}
details>.inner{padding:0 0 1rem}
.tree,.tree ul{list-style:none;margin:6px 0 4px;padding-left:18px;border-left:2px solid var(--line)}
.tree{padding-left:12px}
.tree li{margin:5px 0}
.tree .out{color:var(--muted)}
.retro{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:6px 22px;margin:0 0 1.2rem;max-width:860px}
.retro dt{font-weight:700;font-stretch:85%}
.retro dd{margin:0}
.empty{border:2px dashed var(--line);padding:16px 18px;color:var(--muted);max-width:68ch}

/* constitution */
.doc-layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:56px;align-items:start;margin-top:1.4rem}
.toc{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto;font-size:.93rem;padding:4px 0}
.toc ol,.toc-mobile ol{list-style:none;margin:0;padding:0}
.toc li,.toc-mobile li{margin:0 0 7px}
.toc a{text-decoration:none}
.toc a:hover{text-decoration:underline}
.toc-mobile{display:none}
.doc{max-width:72ch}
.doc h2{margin-top:2.6rem}
.doc h3{margin-top:1.4rem}
.doc blockquote{margin:1rem 0;padding:10px 16px;background:var(--ice-2);border-left:4px solid var(--gold)}
.doc code{font-size:.92em}
.changelog{margin:0 0 2rem}
@media (max-width:900px){.doc-layout{grid-template-columns:minmax(0,1fr);gap:0}.toc{display:none}.toc-mobile{display:block;margin:0 0 1.4rem}}

/* footer */
.foot{border-top:1px solid var(--line);margin-top:3.5rem;padding:22px 0 44px;color:var(--muted);font-size:.9rem}
.foot p{margin:0;max-width:72ch}
.missing{padding:4rem 0}
"""


def franchise_css(colors: dict[str, list[str]]) -> str:
    rules = []
    for cls, pair in sorted(colors.items()):
        main = safe_color(pair[0] if pair else None, DEFAULT_COLORS[0])
        second = safe_color(pair[1] if len(pair) > 1 else None, main)
        rules.append(f".f-{cls}{{--fc:{main};--fc2:{second};--fc-ink:{ink_for(main)}}}")
    return "\n".join(rules)


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
        self._slugs: dict[str, str] = {}
        used: set[str] = set()
        for p in self.profiles:
            s = slug(p["key"])
            while s in used:
                s += "-x"
            used.add(s)
            self._slugs[p["key"]] = s
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
        if key not in self._slugs:  # a team the archive saw but no franchise page was built for
            return esc(self.hist.name(key))
        return f'<a href="{self.furl(key)}">{esc(self.hist.name(key))}</a>'

    def badge(self, key: str, big: bool = False) -> str:
        cls = "badge big" if big else "badge"
        logo = self.logos.get(key)
        if logo:
            return f'<span class="{cls} f-{self.fslug(key)}"><img src="{self.asset(logo)}" alt=""></span>'
        return f'<span class="{cls} f-{self.fslug(key)}" aria-hidden="true">{esc(initials(self.hist.name(key)))}</span>'

    def who(self, key: str) -> str:
        return f'<span class="who">{self.badge(key)}{self.link(key)}</span>'

    # --- season helpers -----------------------------------------------------------------
    def label(self, season: int) -> str:
        return str(self.hist.archive.meta(season).get("season_label") or "")

    def is_test(self, season: int) -> bool:
        return bool(self.hist.archive.meta(season).get("test"))

    def honours(self, season: int) -> dict[str, str]:
        return {a: k for a, k in (self.hist.records.seasons.get(season) or {}).items() if a in AWARDS and k}

    def season_link(self, season: int) -> str:
        return f'<a href="/seasons/{season}/">Season {season}</a>'

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
        return season == self.hist.archive.latest_season() and "champion" not in self.honours(season)

    # --- writing -----------------------------------------------------------------------
    def write(self, rel: str, title: str, body: str, *, section: str = "", description: str = "",
              home: bool = False, before_main: str = "") -> None:
        url = "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
        nav = "".join(f'<li><a href="/{key}/"{" aria-current=page" if key == section else ""}>{esc(label)}</a></li>'
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
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
{meta_html}
<meta name="theme-color" content="{BOARDS}">
<link rel="icon" type="image/png" href="{self.asset('favicon.png')}">
<link rel="apple-touch-icon" href="{self.asset('apple-touch-icon.png')}">
<link rel="preload" href="{self.asset('fonts/archivo.woff')}" as="font" type="font/woff" crossorigin>
<link rel="stylesheet" href="{self.asset('site.css')}">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="boards{' over-rafters' if home else ''}"><div class="wrap">
<a class="brand" href="/"><img src="{self.asset('b-mark.png')}" alt="" width="44" height="44"><span><b>BLHA History</b><span>{esc(LEAGUE_NAME)}</span></span></a>
<nav class="nav" aria-label="Sections"><ul>{nav}</ul></nav>
</div></header>
{before_main}<main id="main" class="wrap">
{body}
</main>
<footer class="foot"><div class="wrap"><p>{esc(LEAGUE_NAME)}, founded 2026. Game results come from Fantrax; honours and the Dynasty Pot come from the Commissioner's records. Updated {esc(long_date(self.built))}.</p></div></footer>
</body>
</html>
"""
        target = self.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        self.pages.append(rel)

    # --- assets -------------------------------------------------------------------------
    def assets(self) -> None:
        folder = self.out / "assets"
        (folder / "fonts").mkdir(parents=True, exist_ok=True)
        for name in FONT_FILES:
            data = (FONTS / name).read_bytes()
            (folder / "fonts" / name).write_bytes(data)
            self.versions[f"fonts/{name}"] = version(data)
        for name, source, width in IMAGES:
            if not source.exists():
                continue
            target = folder / name
            if not shrink(source, target, width):
                shutil.copyfile(source, target)
            self.versions[name] = version(target.read_bytes())
        colors: dict[str, list[str]] = {}
        for p in self.profiles:
            colors[self.fslug(p["key"])] = p["colors"]
            logo = p.get("logo")
            if logo and (ROOT / logo).is_file():
                name = f"logos/{self.fslug(p['key'])}.png"
                (folder / "logos").mkdir(exist_ok=True)
                if not shrink(ROOT / logo, folder / name, 256):
                    shutil.copyfile(ROOT / logo, folder / name)
                self.versions[name] = version((folder / name).read_bytes())
                self.logos[p["key"]] = name
        self.has_card = social_card(folder / "social-card.png")
        if self.has_card:
            self.versions["social-card.png"] = version((folder / "social-card.png").read_bytes())
        css = (CSS.replace("{font_upright}", self.asset("fonts/archivo.woff"))
               .replace("{font_italic}", self.asset("fonts/archivo-italic.woff")).strip()
               + "\n" + franchise_css(colors) + "\n")
        (folder / "site.css").write_text(css, encoding="utf-8")
        self.versions["site.css"] = version(css.encode())

    # --- banners ------------------------------------------------------------------------
    def banner(self, season: int, award: str | None, key: str | None, *, small: bool = False) -> str:
        if award is None:
            return (f'<li class="banner pending"><span class="rod"></span><div class="cloth">'
                    f'<span class="what">BLHA Champions</span><span class="team">To be decided</span>'
                    f'<span class="year">{season}</span></div></li>')
        gold = award == "champion"
        what = "BLHA Champions" if gold else AWARDS[award]
        mark = "" if small or not gold else f'<img src="{self.asset("b-mark.png")}" alt="">'
        name = esc(self.hist.name(key)) if key else ""
        return (f'<li class="banner{"" if gold else " cream"}"><span class="rod"></span>'
                f'<a href="/seasons/{season}/"><div class="cloth">{mark}<span class="what">{esc(what)}</span>'
                f'<span class="team">{name}</span><span class="year">{season}</span></div></a></li>')

    def rafters(self) -> str:
        items = []
        for season in sorted(self.hist.records.seasons):
            h = self.honours(season)
            if h.get("champion"):
                items.append(self.banner(season, "champion", h["champion"]))
            if h.get("presidents_trophy"):
                items.append(self.banner(season, "presidents_trophy", h["presidents_trophy"]))
        pending = self.pending_season()
        if pending is not None:
            items.append(self.banner(pending, None, None))
        return (f'<section class="rafters" aria-label="Banners in the rafters"><div class="truss"></div>'
                f'<div class="wrap"><ol class="banners">{"".join(items)}</ol></div></section>\n')

    def pending_season(self) -> int | None:
        latest = self.hist.archive.latest_season()
        if latest is None:  # nothing archived yet: the first Season of the Dynasty Pot cycle
            first = dynasty_summary(self.hist)["cycle_started"]
            return int(first) if str(first).isdigit() and "champion" not in self.honours(int(first)) else None
        if self.is_test(latest) or "champion" in self.honours(latest):
            nxt = latest + 1
            return None if "champion" in self.honours(nxt) else nxt
        return latest

    # --- home ---------------------------------------------------------------------------
    def home(self) -> None:
        hist = self.hist
        pot = dynasty_summary(hist)
        need = pot["titles_to_win"]
        leaders = [r for r in pot["rows"] if r["titles"]]
        race = ('<ol class="race">' + "".join(f"<li>{self.who(r['key'])}{pips(r['titles'], need)}</li>" for r in leaders)
                + "</ol>") if leaders else '<p class="muted">No championships yet in this cycle.</p>'
        past = ""
        if pot["past"]:
            past = "<h3>Past winners</h3>" + table(
                ["Cycle", "Winner", "Payout"],
                [[esc(f"Seasons {c['started']}–{c['ended']}"), esc(c["winner"]), esc(money(c["payout"]))] for c in pot["past"]],
                num={2})
        latest = hist.archive.latest_season()
        status = ""
        if latest is not None:
            if self.is_test(latest):
                status = f" The {self.label(latest) or str(latest)} season is a test run. Season {latest + 1} is the first that counts."
            elif self.in_progress(latest):
                status = f" Season {latest} is in progress."
        rows = []
        for season in sorted(set(hist.seasons) | set(hist.records.seasons), reverse=True):
            h = self.honours(season)
            if not h and self.in_progress(season) and not self.is_test(season):
                rows.append([self.season_link(season), '<span class="muted">In progress</span>', "", "", ""])
                continue
            rows.append([self.season_link(season), self.link(h.get("champion")), self.link(h.get("runner_up")),
                         self.link(h.get("presidents_trophy")), self.link(h.get("wooden_spoon"))])
        seasons_html = (table(["Season", "Champion", "Runner-up", "Presidents' Trophy", "Wooden Spoon"], rows)
                        if rows else empty("The first Season is still to come. Its results will appear here."))
        cycle = (f"This cycle began in Season {esc(pot['cycle_started'])}." if hist.records.seasons
                 else f"The first cycle starts with Season {esc(pot['cycle_started'])}.")
        body = f"""
<section class="intro"><h1>League history</h1>
<p class="lead">Every champion, standing, trade and draft of the {esc(LEAGUE_NAME)}, a 12-franchise dynasty fantasy hockey league.</p>
<p class="note">Updated {esc(long_date(self.built))}.{esc(status)}</p></section>
<div class="home-grid">
<section aria-labelledby="pot"><h2 id="pot">Dynasty Pot</h2>
<p class="pot-amount">{esc(money(pot['balance']))}</p>
<p class="note">The first franchise to win {need} BLHA Championships in one cycle takes the whole pot (Article IV). {cycle}</p>
{race}{past}</section>
<section aria-labelledby="by-season"><h2 id="by-season">Season by season</h2>{seasons_html}
{self.record_highlights()}</section>
</div>
"""
        self.write("index.html", "Home", body, home=True, before_main=self.rafters())

    def record_highlights(self) -> str:
        games = self.all_games()
        if not games:
            return ""
        sides = [(g.away_score, g.away, g) for g in games] + [(g.home_score, g.home, g) for g in games]
        top = min(sides, key=lambda s: (-s[0], s[2].season, s[2].week))
        decided = [g for g in games if g.winner]
        rows = [["Highest weekly score", f"{self.link(top[1])}, {esc(score(top[0]))}", self.when(top[2])]]
        if decided:
            blow = min(decided, key=lambda g: (-g.margin, g.season, g.week))
            rows.append(["Biggest win", f"{self.link(blow.winner)}, by {esc(score(blow.margin))}", self.when(blow)])
        return ("<h2>League records</h2>" + table(["Record", "Holder", "When"], rows)
                + '<p><a class="more" href="/records/">See every league record</a></p>')

    def when(self, g: Game) -> str:
        return (f'<a href="/seasons/{g.season}/#week-{g.week}">Season {g.season}, Week {g.week}</a>'
                + ('<span class="tag">Playoffs</span>' if g.playoff else ""))

    # --- seasons ------------------------------------------------------------------------
    def seasons(self) -> None:
        hist = self.hist
        rows = []
        all_seasons = sorted(set(hist.seasons) | set(hist.records.seasons), reverse=True)
        for season in all_seasons:
            h = self.honours(season)
            standings, _ = self.standings(season)
            leader = standings[0] if standings else None
            if self.is_test(season):
                status = "Test season"
            else:
                status = "Final" if h.get("champion") else ("In progress" if self.in_progress(season) else "")
            rows.append([self.season_link(season), esc(self.label(season)), self.link(h.get("champion")),
                         (self.link(leader["key"]) + f' <span class="muted">{esc(leader["record"])}</span>') if leader else "—",
                         esc(status)])
        body = ['<div class="page-head"><h1>Seasons</h1>'
                '<p class="subtitle">Final standings, playoffs and every weekly result.</p></div>']
        body.append(table(["Season", "Years", "Champion", "Regular-season leader", "Status"], rows) if rows
                    else empty("No Season has been archived yet. Standings appear after the first archive run."))
        self.write("seasons/index.html", "Seasons", "\n".join(body), section="seasons")
        for season in all_seasons:
            self.season_page(season)

    def season_page(self, season: int) -> None:
        hist = self.hist
        h = self.honours(season)
        sub = self.label(season)
        if self.in_progress(season) and not self.is_test(season):
            sub = f"{sub}, in progress" if sub else "In progress"
        parts = [f'<div class="page-head"><h1>Season {season}</h1>'
                 + (f'<p class="subtitle">{esc(sub)}</p>' if sub else "") + "</div>"]
        if h:
            items = []
            if h.get("champion"):
                items.append(self.banner(season, "champion", h["champion"], small=True))
            if h.get("presidents_trophy"):
                items.append(self.banner(season, "presidents_trophy", h["presidents_trophy"], small=True))
            if items:
                parts.append(f'<ol class="banners small" aria-label="Banners">{"".join(items)}</ol>')
            facts = "".join(f"<dt>{esc(label)}</dt><dd>{self.link(h[a])}</dd>" for a, label in AWARDS.items() if h.get(a))
            parts.append(f'<h2>Honours</h2><dl class="facts">{facts}</dl>')
            pot = (hist.records.seasons.get(season) or {}).get("dynasty_pot") or {}
            if pot.get("balance") is not None:
                parts.append(f'<p class="note">Dynasty Pot after this Season: {esc(money(pot["balance"]))}.</p>')
        rows, note = self.standings(season)
        parts.append("<h2>Standings</h2>")
        if rows:
            parts.append(f'<p class="note">{esc(note)}</p>')
            parts.append(table(["Rank", "Franchise", "W-L-T", "Points for"],
                               [[esc(r["rank"]), self.who(r["key"]), esc(r["record"]), esc(score(r["pf"]))] for r in rows],
                               num={0, 3}))
        else:
            parts.append(empty("No week of this Season has finished yet."))
        weeks = self.week_blocks(season)
        if weeks:
            parts.append("<h2>Week by week</h2>" + weeks)
        self.write(f"seasons/{season}/index.html", f"Season {season}", "\n".join(parts), section="seasons",
                   description=f"BLHA Season {season}: honours, standings and every weekly result.")

    def week_blocks(self, season: int) -> str:
        by_week: dict[int, list[Game]] = {}
        playoff: dict[int, bool] = {}
        for g in self.games(season):
            by_week.setdefault(g.week, []).append(g)
            playoff[g.week] = playoff.get(g.week, False) or g.playoff
        out = []
        for week in sorted(by_week, reverse=True):
            rows = []
            for g in by_week[week]:
                aw, hw = g.winner == g.away, g.winner == g.home
                rows.append([("<strong>" + self.link(g.away) + "</strong>") if aw else self.link(g.away),
                             f'<span class="won">{esc(score(g.away_score))}</span>' if aw else esc(score(g.away_score)),
                             f'<span class="won">{esc(score(g.home_score))}</span>' if hw else esc(score(g.home_score)),
                             ("<strong>" + self.link(g.home) + "</strong>") if hw else self.link(g.home)])
            title = f"Week {week}" + (", playoffs" if playoff[week] else "")
            opened = " open" if playoff[week] else ""
            out.append(f'<details id="week-{week}"{opened}><summary>{esc(title)}</summary><div class="inner">'
                       f'{table(["Away", "Score", "Score", "Home"], rows, num={1, 2}, cls="match")}</div></details>')
        return "\n".join(out)

    # --- franchises ---------------------------------------------------------------------
    def franchises(self) -> None:
        rows = []
        for p in self.profiles:
            rows.append([self.who(p["key"]), esc(p["owner"] or "To be announced"),
                         esc(f"Season {p['founded']}") if p.get("founded") else "—",
                         esc(len(p["titles"])), esc(p["lifetime"])])
        body = ['<div class="page-head"><h1>Franchises</h1>'
                '<p class="subtitle">The franchises of the BLHA, their owners and their records.</p></div>']
        body.append(table(["Franchise", "Owner", "Founded", "Titles", "Lifetime W-L-T"], rows, num={3})
                    if rows else empty("No franchises recorded yet."))
        self.write("franchises/index.html", "Franchises", "\n".join(body), section="franchises")
        for p in self.profiles:
            self.franchise_page(p)

    def franchise_page(self, p: dict[str, Any]) -> None:
        hist, key = self.hist, p["key"]
        s = self.fslug(key)
        owner = esc(p["owner"]) if p["owner"] else "Owner to be announced"
        founded = f", founded in Season {esc(p['founded'])}" if p.get("founded") else ""
        hero = (f'<section class="fhero f-{s}"><div class="wrap">{self.badge(key, big=True)}'
                f'<div><h1>{esc(p["name"])}</h1><p class="subtitle">{owner}{founded}</p></div></div></section>\n')
        parts = []
        banners = []
        for season, h in sorted(hist.records.seasons.items()):
            if h.get("champion") == key:
                banners.append(self.banner(season, "champion", key, small=True))
            if h.get("presidents_trophy") == key:
                banners.append(self.banner(season, "presidents_trophy", key, small=True))
        if banners:
            parts.append(f'<ol class="banners small" aria-label="Banners">{"".join(banners)}</ol>')
        rival = (f"{esc(p['rival'])} ({esc(p['rival_record'])}, {esc(p['rival_kind'])})" if p.get("rival")
                 else '<span class="muted">To be decided</span>')
        honours = "; ".join(f"{label} {', '.join(map(str, years))}" for label, years in p["awards"].items()
                            if label not in ("BLHA Champion", "Presidents' Trophy"))
        facts = [("Lifetime", f"{esc(p['lifetime'])} in {esc(plural(p['games'], 'game'))}"),
                 ("Championships", esc(f"{len(p['titles'])} ({', '.join(map(str, p['titles']))})" if p["titles"] else "None yet")),
                 ("Dynasty Pot", f"{pips(p['dynasty_count'], p['titles_to_win'])} {esc(p['dynasty_count'])} of "
                                 f"{esc(p['titles_to_win'])} this cycle"),
                 ("Rival", rival)]
        if honours:
            facts.append(("Other honours", esc(honours)))
        parts.append('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>")

        rows = []
        for season in sorted(hist.seasons, reverse=True):
            standings, _ = self.standings(season)
            mine = next((r for r in standings if r["key"] == key), None)
            if not mine:
                continue
            won = [label for a, label in AWARDS.items() if self.honours(season).get(a) == key]
            finish = esc(ordinal(mine["rank"])) + (' <span class="muted">so far</span>' if self.in_progress(season) else "")
            rows.append([self.season_link(season), finish, esc(mine["record"]), esc(score(mine["pf"])), esc(", ".join(won))])
        parts.append("<h2>Season by season</h2>")
        parts.append(table(["Season", "Finish", "W-L-T", "Points for", "Honours"], rows, num={3}) if rows
                     else empty("No finished week yet."))

        rows = []
        for other, rec in sorted(self.h2h.opponents(key).items(), key=lambda kv: (-kv[1].games, natural(hist.name(kv[0])))):
            if not rec.games:
                continue
            last = f"Season {rec.last[0]}, Week {rec.last[1]}" if rec.last else ""
            rows.append([self.link(other), esc(rec.text), esc(rec.games),
                         esc(f"{rec.points_for:.1f}–{rec.points_against:.1f}"), esc(last)])
        parts.append("<h2>Head-to-head</h2>")
        parts.append(table(["Opponent", "W-L-T", "Games", "Points", "Last met"], rows, num={2}) if rows
                     else empty("No games played yet."))

        trades = [t for t in reversed(hist.trades()) if any(hist.franchise(team) == key for team in t["teams"])]
        parts.append("<h2>Trades</h2>")
        if trades:
            items = []
            for t in trades:
                mine = [team for team in t["teams"] if hist.franchise(team) == key]
                got = [hist.asset(a) for team in mine for a in t["received"].get(team, [])]
                gave = [hist.asset(a) for team in mine for a in t["sent"].get(team, [])]
                partners = [self.link(hist.franchise(team)) for team in t["teams"] if hist.franchise(team) != key]
                items.append([f'<a href="/trades/#{esc(t["id"])}">{esc(hist.event_date(t))}</a>', ", ".join(partners),
                              esc(", ".join(got) or "Nothing"), esc(", ".join(gave) or "Nothing")])
            parts.append(table(["Seen", "With", "Received", "Sent"], items))
        else:
            parts.append(empty("No trades recorded yet."))

        picks = []
        for year, d in sorted(hist.drafts().items(), reverse=True):
            for pk in d.get("picks") or []:
                if hist.franchise(pk["team"]) == key:
                    picks.append([f'<a href="/drafts/#draft-{esc(year)}">{esc(year)}</a>',
                                  esc(f"{pk['round']}.{int(pk['in_round']):02d}"), esc(pk["overall"]),
                                  esc(hist.player(pk["player"])) if pk.get("player") else '<span class="muted">Not made</span>'])
        parts.append("<h2>Draft picks</h2>")
        parts.append(table(["Draft", "Pick", "Overall", "Player"], picks, num={2}) if picks
                     else empty("No completed draft recorded yet."))
        self.write(f"franchises/{s}/index.html", p["name"], "\n".join(parts), section="franchises",
                   description=f"{p['name']} of the BLHA: championships, season-by-season record, head-to-head, trades and draft picks.",
                   before_main=hero)

    # --- head-to-head -------------------------------------------------------------------
    def head_to_head(self) -> None:
        hist, h2h = self.hist, self.h2h
        parts = ['<div class="page-head"><h1>Head-to-head</h1>'
                 '<p class="subtitle measure">Lifetime records from every finished week, regular season and playoffs. '
                 "A franchise's earned rival is the opponent it has played most, with the closest record breaking ties.</p></div>"]
        declared = declared_rivals(hist)
        if declared:
            parts.append("<h2>Declared rivalries</h2>")
            parts.append(table(["Rivalry", "Record (first named)", "Games"],
                               [[f"{self.link(a)} vs {self.link(b)}", esc(h2h.record(a, b).text), esc(h2h.record(a, b).games)]
                                for a, b in declared], num={2}))
        keys = sorted(h2h.franchises(), key=lambda k: natural(hist.name(k)))
        played = [k for k in keys if h2h.lifetime(k).games]
        parts.append("<h2>Earned rivals</h2>")
        if played:
            rows = []
            for k in played:
                rival = h2h.earned_rival(k)
                rec = h2h.record(k, rival) if rival else None
                rows.append([self.who(k), self.link(rival) if rival else "—", esc(rec.text if rec else ""),
                             esc(rec.games if rec else 0), esc(h2h.lifetime(k).text)])
            parts.append(table(["Franchise", "Rival", "Record vs rival", "Games", "Lifetime"], rows, num={3}))
            parts.append('<h2>Every matchup</h2><p class="note">Each row is that franchise\'s record against the numbered '
                         "franchise in each column. Columns follow the same order as the rows.</p>")
            head = '<th scope="col">Franchise</th>' + "".join(
                f'<th scope="col"><abbr title="{esc(hist.name(k))}">{i}</abbr></th>' for i, k in enumerate(played, 1))
            body = ""
            for i, a in enumerate(played, 1):
                cells = "".join('<td class="self">—</td>' if a == b else
                                f"<td>{esc(h2h.record(a, b).text) if h2h.record(a, b).games else ''}</td>" for b in played)
                body += f"<tr><td>{i}. {self.link(a)}</td>{cells}</tr>"
            parts.append(f'<div class="scroll"><table class="matrix"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            parts.append("<h2>Most-played pairings</h2>")
            pairs = []
            for i, a in enumerate(played):
                for b in played[i + 1:]:
                    r = h2h.record(a, b)
                    if r.games:
                        last = f"Season {r.last[0]}, Week {r.last[1]}" if r.last else ""
                        pairs.append((r.games, [f"{self.link(a)} vs {self.link(b)}", esc(r.games), esc(r.text),
                                                esc(f"{r.points_for:.1f}–{r.points_against:.1f}"), esc(last)]))
            pairs.sort(key=lambda p: -p[0])
            parts.append(table(["Pairing", "Games", "Record (first named)", "Points", "Last met"], [p[1] for p in pairs], num={1}))
        else:
            parts.append(empty("No week has finished yet, so there are no head-to-head records."))
        self.write("head-to-head/index.html", "Head-to-head", "\n".join(parts), section="head-to-head")

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
        parts = ['<div class="page-head"><h1>Trades</h1>'
                 '<p class="subtitle measure">Trades are recorded from a daily look at Fantrax and dated the day they were first seen. '
                 "Open a trade to follow its trade tree: what each side received and what those players and picks became.</p></div>"]
        trades = list(reversed(hist.trades()))
        if trades:
            for t in trades:
                sides = "; ".join(f"{hist.name(hist.franchise(team))} received "
                                  f"{', '.join(hist.asset(a) for a in t['received'].get(team, [])) or 'nothing'}"
                                  for team in t["teams"])
                trees = "".join(self.tree_html(node) for node in trade_trees(hist, t["id"]).values())
                flag = ('<p class="note">One-sided: possibly a drop and a claim between two daily looks rather than a trade.</p>'
                        if t.get("one_sided") else "")
                parts.append(f'<details id="{esc(t["id"])}"><summary>{esc(hist.event_date(t))}: {esc(sides)}</summary>'
                             f'<div class="inner">{flag}{trees}</div></details>')
        else:
            parts.append(empty("No trades recorded yet."))
        moves = [e for e in hist.events() if e.get("type") in ("add", "drop")][-150:]
        parts.append("<h2>Adds and drops</h2>")
        if moves:
            rows = [[esc(hist.event_date(e)), self.link(hist.franchise(e["team"])), esc("Added" if e["type"] == "add" else "Dropped"),
                     esc(hist.player(e["player"]))] for e in reversed(moves)]
            parts.append('<p class="note">The latest 150 moves.</p>' + table(["Seen", "Franchise", "Move", "Player"], rows))
        else:
            parts.append(empty("No adds or drops recorded yet."))
        self.write("trades/index.html", "Trades", "\n".join(parts), section="trades")

    # --- drafts -------------------------------------------------------------------------
    def drafts(self) -> None:
        hist = self.hist
        parts = ['<div class="page-head"><h1>Drafts</h1>'
                 '<p class="subtitle">Every draft board, and how each class turned out.</p></div>']
        drafts = hist.drafts()
        if not drafts:
            parts.append(empty("No completed draft has been archived yet."))
        for year in sorted(drafts, reverse=True):
            d = drafts[year]
            parts.append(f'<h2 id="draft-{year}">{esc(year)} Draft</h2>')
            retro = hist.archive.retro(int(d["season"]))
            if retro:
                from history.retro import highlight_lines

                as_of = hist.date(retro.get("as_of"))
                rows = "".join(f"<dt>{esc(label.capitalize())}</dt><dd>{inline(text)}</dd>" for label, text in highlight_lines(retro))
                parts.append(f'<h3>Retrospective, as of {esc(as_of)}</h3><dl class="retro">{rows}</dl>'
                             f'<p class="note">{esc(retro.get("measure", ""))}</p>')
            rows = [[esc(f"{p['round']}.{int(p['in_round']):02d}"), esc(p["overall"]), self.link(hist.franchise(p["team"])),
                     esc(hist.player(p["player"])) if p.get("player") else '<span class="muted">Not made</span>']
                    for p in d.get("picks") or []]
            parts.append(f'<details><summary>Full draft board ({len(rows)} picks)</summary><div class="inner">'
                         f"{table(['Pick', 'Overall', 'Franchise', 'Player'], rows, num={1})}</div></details>")
        self.write("drafts/index.html", "Drafts", "\n".join(parts), section="drafts")

    # --- records ------------------------------------------------------------------------
    def records(self) -> None:
        games = self.all_games()
        parts = ['<div class="page-head"><h1>League records</h1>'
                 '<p class="subtitle measure">The highs and lows of every finished week, regular season and playoffs. '
                 "When two are equal, the earlier one ranks first.</p></div>"]
        if not games:
            parts.append(empty("No week has finished yet, so there are no records."))
            self.write("records/index.html", "Records", "\n".join(parts), section="records")
            return
        sides = [(g.away_score, g.away, g.home, g) for g in games] + [(g.home_score, g.home, g.away, g) for g in games]

        def first(items: list, key: Callable, n: int = 5) -> list:
            return sorted(items, key=key)[:n]

        parts.append('<h2>Single week</h2><div class="record-grid">')
        rows = [[self.link(k), esc(score(v)), self.link(o), self.when(g)]
                for v, k, o, g in first(sides, lambda s: (-s[0], s[3].season, s[3].week))]
        parts.append(table(["Franchise", "Score", "Opponent", "When"], rows, num={1}, caption="Highest scores"))
        rows = [[self.link(k), esc(score(v)), self.link(o), self.when(g)]
                for v, k, o, g in first([s for s in sides if s[0] > 0], lambda s: (s[0], s[3].season, s[3].week))]
        parts.append(table(["Franchise", "Score", "Opponent", "When"], rows, num={1}, caption="Lowest scores") + "</div>")
        decided = [g for g in games if g.winner]
        if decided:
            rows = [[self.link(g.winner), esc(score(g.margin)), self.link(g.loser),
                     f'<span class="nowrap">{esc(score(max(g.away_score, g.home_score)))}–{esc(score(min(g.away_score, g.home_score)))}</span>',
                     self.when(g)]
                    for g in first(decided, lambda g: (-g.margin, g.season, g.week))]
            parts.append(table(["Winner", "Margin", "Loser", "Score", "When"], rows, num={1}, caption="Biggest wins"))
        rows = [[f"{self.link(g.away)} vs {self.link(g.home)}", esc(score(g.margin)),
                 f'<span class="nowrap">{esc(score(g.away_score))}–{esc(score(g.home_score))}</span>', self.when(g)]
                for g in first(games, lambda g: (g.margin, g.season, g.week))]
        parts.append(table(["Game", "Margin", "Score", "When"], rows, num={1}, caption="Closest games"))

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
            parts.append('<h2>Single season</h2><div class="record-grid">')
            rows = [[self.link(t["key"]), esc(score(t["pf"])), self.season_link(t["season"])]
                    for t in first(done, lambda t: (-t["pf"], t["season"]))]
            parts.append(table(["Franchise", "Points for", "Season"], rows, num={1}, caption="Most points in a regular season"))
            rows = [[self.link(t["key"]), esc(t["record"]), self.season_link(t["season"])]
                    for t in first(done, lambda t: (-t["pct"], -t["pf"], t["season"]))]
            parts.append(table(["Franchise", "W-L-T", "Season"], rows, caption="Best regular-season records") + "</div>")
            if not any(t["final"] for t in totals):
                parts.append('<p class="note">No regular season has finished yet, so these use the Season in progress.</p>')
        self.write("records/index.html", "Records", "\n".join(parts), section="records")

    # --- constitution -------------------------------------------------------------------
    def constitution(self) -> None:
        parts = ['<div class="page-head"><h1>The Constitution</h1>'
                 '<p class="subtitle">The rules of the BLHA, and every change to them.</p></div>']
        if CONSTITUTION.exists():
            text, anchors = markdown(CONSTITUTION.read_text(encoding="utf-8"), shift=0)
            text = re.sub(r"<h1[^>]*>.*?</h1>", "", text, count=1)
            links = "".join(f'<li><a href="#{a}">{esc(t)}</a></li>' for a, t in anchors)
            log = ""
            if CHANGELOG.exists():
                log_html, _ = markdown(CHANGELOG.read_text(encoding="utf-8"), shift=1)
                log_html = re.sub(r"<h2[^>]*>.*?</h2>", "", log_html, count=1)
                log = (f'<details class="changelog" id="changelog"><summary>Changelog: every amendment, newest first</summary>'
                       f'<div class="inner doc">{log_html}</div></details>')
                links = '<li><a href="#changelog">Changelog</a></li>' + links
            parts.append(f'<div class="doc-layout"><nav class="toc" aria-label="Constitution contents"><ol>{links}</ol></nav>'
                         f'<div><details class="toc-mobile"><summary>Contents</summary><ol>{links}</ol></details>'
                         f'{log}<div class="doc">{text}</div></div></div>')
        else:
            parts.append(empty("The Constitution has not been published yet."))
        self.write("constitution/index.html", "Constitution", "\n".join(parts), section="constitution",
                   description="The Constitution of the Beer League Hockey Association, with its changelog.")

    # --- the rest -----------------------------------------------------------------------
    def not_found(self) -> None:
        body = ('<section class="missing"><h1>That page isn\'t in the record book</h1>'
                '<p class="lead">The address may have a typo, or the page may have moved.</p>'
                '<p><a href="/">Go to the league history home page</a></p></section>')
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
                     self.records, self.constitution, self.not_found):
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


def shrink(source: Path, target: Path, width: int | None) -> bool:
    """Write a smaller copy with Pillow (False if Pillow is not installed)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.convert("RGBA")
        if width and img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        img.save(target, optimize=True)
    return True


def social_card(target: Path) -> bool:
    """The 1200x630 picture shown when a link to the site is shared (False without Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BOARDS)
    d = ImageDraw.Draw(img)
    steel = (58, 61, 67)
    d.rectangle([0, 0, w, 5], fill=steel)
    d.rectangle([0, 46, w, 51], fill=steel)
    for x in range(-60, w + 60, 46):
        d.line([(x, 51), (x + 46, 0)], fill=steel, width=3)
        d.line([(x, 0), (x + 46, 51)], fill=steel, width=3)
    d.rectangle([0, h - 12, w, h], fill=GOLD)
    mark = KIT / "01_logos" / "blha-wordmark-white-transparent.png"
    if mark.exists():
        with Image.open(mark) as wm:
            wm = wm.convert("RGBA")
            wm = wm.resize((600, round(wm.height * 600 / wm.width)), Image.LANCZOS)
            img.paste(wm, (70, (h - wm.height) // 2 + 20), wm)
    bx, bw, bottom = 820, 270, 560
    d.line([(bx + 40, 51), (bx + 40, 92)], fill=(154, 161, 169), width=3)
    d.line([(bx + bw - 40, 51), (bx + bw - 40, 92)], fill=(154, 161, 169), width=3)
    d.rounded_rectangle([bx - 12, 92, bx + bw + 12, 104], radius=6, fill=(174, 180, 187))
    d.polygon([(bx, 104), (bx + bw, 104), (bx + bw, bottom), (bx + bw // 2, bottom - 60), (bx, bottom)], fill=GOLD)
    try:
        big = ImageFont.truetype(str(FONTS / "archivo.woff"), 104)
        big.set_variation_by_axes([850, 62])
        small = ImageFont.truetype(str(FONTS / "archivo.woff"), 34)
        small.set_variation_by_axes([800, 62])
    except Exception:
        big = small = ImageFont.load_default(size=60)
    cx = bx + bw // 2
    d.text((cx, 150), "BLHA", font=small, fill=BOARDS, anchor="mt")
    d.line([(bx + 50, 200), (bx + bw - 50, 200)], fill=BOARDS, width=3)
    d.text((cx, 240), "LEAGUE", font=big, fill=BOARDS, anchor="mt")
    d.text((cx, 350), "HISTORY", font=big, fill=BOARDS, anchor="mt")
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target, optimize=True)
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
