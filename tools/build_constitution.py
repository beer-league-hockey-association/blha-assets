#!/usr/bin/env python3
"""Build every published copy of the BLHA Constitution from constitution_source.py.

Outputs
- templates/constitution/NN_*.json   Discohook messages (one JSON per Discord message)
- constitution/BLHA_Constitution.md
- constitution/CHANGELOG.md   every adopted amendment by date (from S.AMENDMENTS), newest first
- constitution/BLHA_Constitution_discohook_backup.json   all messages in one Discohook backup
- constitution/BLHA_Constitution.pdf   (when --pdf is given)

Usage: python3 tools/build_constitution.py [--pdf]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import constitution_source as S  # noqa: E402
import discohook_format as fmt  # noqa: E402
import posted_messages as posted  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_TEMPLATES = ROOT / "templates" / "constitution"
OUT_DOCS = ROOT / "constitution"

GOLD = 16758812
MAX_DESC = 3900          # stay under Discord's 4096 per-embed description limit
MAX_MESSAGE = 5600       # stay under Discord's 6000 per-message counted characters
MAX_EMBEDS = 9           # leave room for the frozen footer image embed rule


# ---------------------------------------------------------------- text helpers
def article_lines(art: dict, fmt: str) -> list[str]:
    """Return rendered paragraphs for one article. fmt: 'discord' or 'md'."""
    lines: list[str] = []
    n = 0
    if art["callout"]:
        label, text = art["callout"]
        lines.append(f"**{label}** — {text}" if fmt == "discord" else f"> **{label}** — {text}")
    for block in art["blocks"]:
        kind = block[0]
        if kind == "p":
            n += 1
            lines.append(f"**{art_num(art)}.{n}** {block[1]}" if fmt == "discord" else f"**{art_num(art)}.{n}** {block[1]}")
        elif kind == "allocation":
            rows = [f"• {k} — **${v:,}**" for k, v in S.ALLOCATION]
            rows.append(f"• **TOTAL — ${S.ALLOCATION_TOTAL:,}**")
            lines.append("\n".join(rows))
        elif kind == "scoring":
            sk = "\n".join(f"• {k} — **{v}**" for k, v in S.SKATERS)
            go = "\n".join(f"• {k} — **{v}**" for k, v in S.GOALIES)
            lines.append(f"**SKATERS**\n{sk}\n\n**GOALIES**\n{go}")
        elif kind == "dates":
            lines.append("\n".join(f"• **{k}:** {v}" for k, v in S.DATE_RULES))
        elif kind == "history":
            lines.append("**HISTORY**\n" + "\n".join(f"• **{v}** — {t}" for v, t in history_rows(block[1])))
    return lines


# ------------------------------------------------------------------ amendments
# Amendments are identified by their adoption date, never by a version number.
VOTES_NEEDED = 8          # Section 20.3
FRANCHISES = 12
_SECTION = re.compile(r"^\d{1,2}\.\d{1,2}$")
_ARTICLE = re.compile(r"^[IVXL]+$")
_VERSION_WORDS = re.compile(r"\b(?:v\d+(?:\.\d+)*|version\s+\d+(?:\.\d+)*)\b", re.IGNORECASE)
_AMENDMENT_KEYS = {"adopted", "articles", "sections", "old", "new", "vote", "effective_season", "summary"}


def nice_date(iso: str) -> str:
    from datetime import date

    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def check_amendments(amendments: list[dict]) -> list[dict]:
    """Validate S.AMENDMENTS and return them oldest first. Raises ValueError on any problem."""
    from datetime import date

    errors: list[str] = []
    out: list[dict] = []
    for i, a in enumerate(amendments, 1):
        where = f"AMENDMENTS entry {i}"
        if not isinstance(a, dict):
            errors.append(f"{where}: must be a dict")
            continue
        unknown = set(a) - _AMENDMENT_KEYS
        if unknown:
            errors.append(f"{where}: unknown keys {sorted(unknown)}")
        try:
            adopted = date.fromisoformat(str(a.get("adopted")))
        except ValueError:
            errors.append(f"{where}: adopted must be a date like 2028-06-20")
            continue
        where = f"Amendment adopted {adopted.isoformat()}"
        articles = [str(x) for x in a.get("articles") or []]
        sections = [str(x) for x in a.get("sections") or []]
        if not articles and not sections:
            errors.append(f"{where}: list the articles or sections it changes")
        errors += [f"{where}: article {x!r} is not a Roman numeral" for x in articles if not _ARTICLE.match(x)]
        errors += [f"{where}: section {x!r} must be cited as N.N" for x in sections if not _SECTION.match(x)]
        vote = a.get("vote") if isinstance(a.get("vote"), dict) else {}
        counts = {k: vote.get(k) for k in ("yes", "no", "not_voted")}
        if set(vote) - set(counts) or any(not isinstance(v, int) or v < 0 for v in counts.values()):
            errors.append(f"{where}: vote must be {{'yes': n, 'no': n, 'not_voted': n}} with whole numbers")
        else:
            if counts["yes"] < VOTES_NEEDED:
                errors.append(f"{where}: {counts['yes']} yes votes; an amendment needs at least {VOTES_NEEDED} (20.3)")
            if sum(counts.values()) > FRANCHISES:
                errors.append(f"{where}: {sum(counts.values())} votes counted; there are {FRANCHISES} franchises")
        season = a.get("effective_season")
        if not isinstance(season, int) or season < 2027 or season < adopted.year:
            errors.append(f"{where}: effective_season must be a Season year (2027 or later, not before the adoption year)")
        if not str(a.get("old") or "") and not str(a.get("new") or ""):
            errors.append(f"{where}: give the old text, the new text, or both")
        for key in ("old", "new", "summary"):
            if _VERSION_WORDS.search(str(a.get(key) or "")):
                errors.append(f"{where}: {key} mentions a version number; amendments are identified by date only")
        out.append({**a, "adopted": adopted.isoformat(), "articles": articles, "sections": sections, "vote": counts})
    if errors:
        raise ValueError("Invalid AMENDMENTS in tools/constitution_source.py:\n  " + "\n  ".join(errors))
    return sorted(out, key=lambda a: a["adopted"])


def cites(a: dict) -> str:
    parts = [f"Article {x}" for x in a["articles"]]
    if a["sections"]:
        parts.append(("Sections " if len(a["sections"]) > 1 else "Section ") + ", ".join(a["sections"]))
    return "; ".join(parts)


def vote_text(vote: dict) -> str:
    text = f"{vote['yes']} yes, {vote['no']} no"
    if vote["not_voted"]:
        text += f", {vote['not_voted']} not voted"
    return text


def amendment_rows(amendments: list[dict]) -> list[tuple[str, str]]:
    rows = []
    for a in check_amendments(amendments):
        text = f"{cites(a)}. "
        if a.get("summary"):
            text += f"{str(a['summary']).rstrip('.')}. "
        text += f"Vote {vote_text(a['vote'])}. Effective Season {a['effective_season']}."
        rows.append((f"Amended {nice_date(a['adopted'])}", text))
    return rows


def history_rows(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The Article XX history block: the Charter row, then every adopted amendment by date."""
    return list(rows) + amendment_rows(S.AMENDMENTS)


def build_changelog(amendments: list[dict]) -> str:
    """constitution/CHANGELOG.md: every change to the Constitution, newest first, by date."""
    md = [
        "<!-- Generated from tools/constitution_source.py (AMENDMENTS) by tools/build_constitution.py. Do not edit by hand. -->",
        "# BLHA Constitution — Changelog",
        "",
        "Every change to the Constitution, newest first. Amendments are identified by the date they were adopted.",
        "",
    ]
    for a in reversed(check_amendments(amendments)):
        md += [f"## Amended {nice_date(a['adopted'])}", ""]
        if a.get("summary"):
            md += [str(a["summary"]), ""]
        md += [
            f"- **Changes:** {cites(a)}",
            f"- **Vote:** {vote_text(a['vote'])} ({VOTES_NEEDED} yes votes required, Section 20.3)",
            f"- **Effective:** Season {a['effective_season']}",
            "",
        ]
        for label, key in (("Old text", "old"), ("New text", "new")):
            text = str(a.get(key) or "").strip()
            md += [f"**{label}:**", ""]
            md += [("> " + line) if line else ">" for line in text.splitlines()] if text else ["*(none)*"]
            md += [""]
    md += [
        "## Charter",
        "",
        "Adopted by owner acceptance. Effective Season 2027 (Section 20.1).",
        "",
    ]
    return "\n".join(md)


_ARTICLE_INDEX: dict[str, int] = {}


def art_num(art: dict) -> int:
    return _ARTICLE_INDEX[art["num"]]


for _i, _a in enumerate(S.ARTICLES, 1):
    _ARTICLE_INDEX[_a["num"]] = _i


def split_for_embeds(lines: list[str], limit: int = MAX_DESC) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for line in lines:
        add = (("\n\n" if cur else "") + line)
        if cur and len(cur) + len(add) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur += add
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------- Discord build
def embed_chars(e: dict) -> int:
    total = len(e.get("title", "")) + len(e.get("description", ""))
    total += len(e.get("footer", {}).get("text", ""))
    for f in e.get("fields", []):
        total += len(f["name"]) + len(f["value"])
    return total


def make_embeds() -> list[dict]:
    embeds: list[dict] = []
    # quick reference + allocation
    qr = "\n".join(f"• **{k}:** {v}" for k, v in S.QUICK_REFERENCE)
    embeds.append({
        "title": "BLHA CONSTITUTION — QUICK REFERENCE",
        "description": f"**{S.EDITION}**\n\n{qr}",
        "color": GOLD, "footer": {"text": S.FOOTER},
    })
    alloc = "\n".join(f"• {k} — **${v:,}**" for k, v in S.ALLOCATION)
    embeds.append({
        "title": "ANNUAL FINANCIAL ALLOCATION",
        "description": f"12 franchises × $150 = **${S.ALLOCATION_TOTAL:,}** annual league pool.\n\n{alloc}\n• **TOTAL — ${S.ALLOCATION_TOTAL:,}**",
        "color": GOLD, "footer": {"text": S.FOOTER},
    })
    for art in S.ARTICLES:
        chunks = split_for_embeds(article_lines(art, "discord"))
        for i, chunk in enumerate(chunks):
            title = f"ARTICLE {art['num']} — {art['title'].upper()}"
            if i:
                title += " (CONTINUED)"
            embeds.append({"title": title, "description": chunk, "color": GOLD, "footer": {"text": S.FOOTER}, "_article": art["num"]})
    return embeds


def pack_messages(embeds: list[dict]) -> list[list[dict]]:
    messages: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for e in embeds:
        c = embed_chars(e)
        # quick reference and allocation travel together; start a fresh message otherwise when full
        if cur and (size + c > MAX_MESSAGE or len(cur) >= MAX_EMBEDS):
            messages.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += c
    if cur:
        messages.append(cur)
    return messages


def message_name(idx: int, msg: list[dict]) -> str:
    arts = [e["_article"] for e in msg if "_article" in e]
    uniq = list(dict.fromkeys(arts))
    label = uniq[0] if len(uniq) == 1 else f"{uniq[0]}_to_{uniq[-1]}"
    if any("_article" not in e for e in msg):
        return f"{idx:02d}_quick_reference_and_article_{label.lower()}.json"
    return f"{idx:02d}_articles_{label.lower()}.json"


def build_discord() -> list[tuple[str, dict]]:
    packed = pack_messages(make_embeds())
    out: list[tuple[str, dict]] = []
    for idx, msg in enumerate(packed):
        clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in msg]
        name = message_name(idx, msg)
        # The messages go out back to back after the channel intro: only the last
        # one has the footer text and divider (fmt.SEQUENCES["constitution"]).
        clean = fmt.apply(clean, rel=f"constitution/{name}", cont=idx < len(packed) - 1)
        out.append((name, {"embeds": clean}))
    return out


# -------------------------------------------------------------------- Markdown
def build_markdown() -> str:
    md = [f"# BLHA Constitution — {S.EDITION}", "", f"*{S.TAGLINE}*", ""]
    md += ["## Quick Reference", ""] + [f"- **{k}:** {v}" for k, v in S.QUICK_REFERENCE] + [""]
    md += ["## Annual Financial Allocation", "", "| Allocation | Amount |", "|---|---:|"]
    md += [f"| {k} | ${v:,} |" for k, v in S.ALLOCATION] + [f"| **Total** | **${S.ALLOCATION_TOTAL:,}** |", ""]
    for art in S.ARTICLES:
        md += [f"## Article {art['num']} — {art['title']}", ""]
        for line in article_lines(art, "md"):
            md += [line, ""]
    md += ["*End of Constitution*", ""]
    return "\n".join(md)


# ------------------------------------------------------------------------- PDF
# The 8-bit league look, kept readable: Pixelify Sans for the text, Jersey 10 for headings and numbers,
# Silkscreen for small labels, pixel frames and the ice resurfacer on the cover.
RESURFACER = [
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
    "..KSMMMMMBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBK...",
    "..KSSSSSSBBBBKKKBBBBBBKKKBBBBBBBBBBBBBKKKBBBBBBKKKBBK...",
    "..KSMMMMMBBBKKKKKBBBBKKKKKBBBBBBBBBBBKKKKKBBBBKKKKKBK...",
    "..KSSSSSSKKKKKSKKKKKKKKSKKKKKKKKKKKKKKKSKKKKKKKKSKKKK...",
    "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK....",
    "CCCCCCK.....KKKKK....KKKKK...........KKKKK....KKKKK.....",
    "KCCCCCCK.....KKK......KKK.............KKK......KKK......",
    ".KKKKKK.................................................",
]
B_SPRITE = ["KKKKKKKKKK....", "KGGGGGGGGGK...", "KGWWWWWWWWGK..", "KGWWKKKKWWWGK.", "KGWWKGGKWWWGK.", "KGWWKKKKWWGK..",
            "KGWWWWWWWWGK..", "KGWWWWWWWWWGK.", "KGWWKKKKKWWWGK", "KGWWKGGGKWWWGK", "KGWWKKKKKWWWGK", "KGWWWWWWWWWWGK",
            "KGGGGGGGGGGGK.", "KKKKKKKKKKKK.."]
SPRITE_PAL = {"K": "#0E0F12", "W": "#FCFCFC", "G": "#FFB81C", "S": "#9AA1A9", "B": "#2F6FDB", "L": "#7FB7F0",
              "C": "#F4EFE4", "N": "#1F4FA8", "M": "#3A3D42"}


def build_pdf(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                    Spacer, Table, TableStyle, NextPageTemplate, CondPageBreak)

    fonts = ROOT / "brand" / "fonts"
    px = fonts / "pixelifysans"  # no italic in Pixelify Sans: italic text uses the upright face
    pdfmetrics.registerFont(TTFont("Body", str(px / "PixelifySans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Bold", str(px / "PixelifySans-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Italic", str(px / "PixelifySans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Body-BoldItalic", str(px / "PixelifySans-SemiBold.ttf")))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")
    pdfmetrics.registerFont(TTFont("Pix", str(fonts / "jersey10" / "Jersey10-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Label", str(fonts / "silkscreen" / "Silkscreen-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Label-Bold", str(fonts / "silkscreen" / "Silkscreen-Bold.ttf")))

    BLACK = colors.HexColor("#0E0F12")
    CHAR = colors.HexColor("#2B2D31")
    GOLDC = colors.HexColor("#FFB81C")
    CREAM = colors.HexColor("#F4EFE4")
    INK = colors.HexColor("#14161A")
    GRAY = colors.HexColor("#4C5563")
    SOFT = colors.HexColor("#B9BEC6")
    ICE = colors.HexColor("#EEF5FA")
    LINE = colors.HexColor("#C3CFDA")
    CALL = colors.HexColor("#FFF4D6")

    W, H = letter
    LM = RM = 0.9 * inch

    body = ParagraphStyle("body", fontName="Body", fontSize=10.2, leading=15, textColor=INK, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=9.3, leading=12.8, spaceAfter=0)
    h_sec = ParagraphStyle("hsec", fontName="Pix", fontSize=24, leading=24, textColor=INK, spaceBefore=4, spaceAfter=4)
    kick = ParagraphStyle("kick", fontName="Label-Bold", fontSize=7, leading=10, textColor=colors.HexColor("#8A5E00"))
    sub = ParagraphStyle("sub", fontName="Body", fontSize=11, leading=15.5, textColor=GRAY, spaceAfter=10)
    toc_s = ParagraphStyle("toc", fontName="Body-Bold", fontSize=10.2, leading=13.5, textColor=INK)
    callout_s = ParagraphStyle("callout", parent=body, fontName="Body-Bold", fontSize=10.2, spaceAfter=0)
    right = ParagraphStyle("r", parent=small, alignment=2)

    def md(t: str) -> str:
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

    def label(text: str, color: str = "#FFB81C", size: float = 7) -> str:
        return f'<font name="Label-Bold" size="{size}" color="{color}">{text.upper()}</font>'

    wordmark = ROOT / "brand" / "source" / "blha-wordmark-white.png"

    def sprite(c, rows, x, y, s):
        """Draw a pixel sprite with its bottom-left corner at (x, y), s points per pixel."""
        for r, row in enumerate(rows):
            i = 0
            while i < len(row):
                ch, j = row[i], i
                while j < len(row) and row[j] == ch:
                    j += 1
                if ch in SPRITE_PAL:
                    c.setFillColor(colors.HexColor(SPRITE_PAL[ch]))
                    c.rect(x + i * s, y + (len(rows) - 1 - r) * s, (j - i) * s, s, stroke=0, fill=1)
                i = j

    def pixel_frame(c, x, y, w, h, t, fill, edge):
        """A pixel window: filled box with a t-thick border whose corners are notched."""
        c.setFillColor(fill); c.rect(x, y, w, h, stroke=0, fill=1)
        c.setFillColor(edge)
        c.rect(x, y - t, w, t, stroke=0, fill=1); c.rect(x, y + h, w, t, stroke=0, fill=1)
        c.rect(x - t, y, t, h, stroke=0, fill=1); c.rect(x + w, y, t, h, stroke=0, fill=1)

    def on_cover(c, d):
        c.setFillColor(BLACK); c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(GOLDC); c.rect(0, H - 8, W, 8, stroke=0, fill=1); c.rect(0, 0, W, 8, stroke=0, fill=1)
        # dotted arena backdrop in the top half
        c.setFillColor(colors.HexColor("#1A1C22"))
        for yy in range(int(H * .42), int(H) - 8, 8):
            for xx in range((yy // 8 % 2) * 4, int(W), 8):
                c.rect(xx, yy, 1.6, 1.6, stroke=0, fill=1)
        if wordmark.exists():
            ww = 3.6 * inch
            c.drawImage(str(wordmark), 1.0 * inch, H - 3.55 * inch, width=ww, height=ww * 1086 / 1448, mask="auto")
        c.setFont("Pix", 76)
        c.setFillColor(GOLDC); c.drawString(1.0 * inch + 4, H - 5.0 * inch - 4, "CONSTITUTION")
        c.setFillColor(CREAM); c.drawString(1.0 * inch, H - 5.0 * inch, "CONSTITUTION")
        c.setFillColor(SOFT); c.setFont("Body", 13)
        c.drawString(1.0 * inch, H - 5.45 * inch, "A permanent framework for competition, governance,")
        c.drawString(1.0 * inch, H - 5.7 * inch, "and long-term franchise management.")
        pixel_frame(c, 1.0 * inch, H - 6.85 * inch, 4.0 * inch, 0.78 * inch, 4, colors.HexColor("#1A1C22"), GOLDC)
        c.setFillColor(GOLDC); c.setFont("Label-Bold", 10); c.drawString(1.0 * inch + 14, H - 6.42 * inch, S.EDITION.upper())
        c.setFillColor(SOFT); c.setFont("Body", 10)
        c.drawString(1.0 * inch + 14, H - 6.68 * inch, "Established 2026  •  Inaugural Season 2027–28")
        # the rink, with the ice resurfacer
        rink_y, rink_h = 1.25 * inch, 1.15 * inch
        c.setFillColor(colors.HexColor("#6E747C")); c.rect(0, rink_y + rink_h, W, 6, stroke=0, fill=1)
        c.setFillColor(GOLDC); c.rect(0, rink_y + rink_h - 3, W, 3, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#E4EEF5")); c.rect(0, rink_y, W, rink_h - 3, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#F8FBFD")); c.rect(0, rink_y, 2.3 * inch, rink_h - 12, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#2457C5")); c.rect(W * .3, rink_y, 5, rink_h - 3, stroke=0, fill=1); c.rect(W * .7, rink_y, 5, rink_h - 3, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#C8241F")); c.rect(W * .5 - 3, rink_y, 6, rink_h - 3, stroke=0, fill=1)
        sprite(c, RESURFACER, 2.15 * inch, rink_y + 4, 2.6)
        c.setFillColor(GOLDC); c.setFont("Label-Bold", 9); c.drawString(1.0 * inch, 0.82 * inch, "FANTRAX RUNS THE GAME.  DISCORD RUNS THE LEAGUE.")
        c.setFillColor(CREAM); c.setFont("Label", 7.5); c.drawString(1.0 * inch, 0.6 * inch, "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026")

    def on_page(c, d):
        c.setFillColor(BLACK); c.rect(0, H - 0.82 * inch, W, 0.82 * inch, stroke=0, fill=1)
        c.setFillColor(GOLDC); c.rect(0, H - 0.82 * inch - 4, W, 4, stroke=0, fill=1)
        sprite(c, B_SPRITE, LM, H - 0.66 * inch, 2)
        c.setFillColor(CREAM); c.setFont("Label-Bold", 7.5)
        c.drawString(LM + 40, H - 0.47 * inch, "BLHA  /  CONSTITUTION")
        c.setFillColor(GOLDC); c.drawRightString(W - RM, H - 0.47 * inch, S.EDITION.upper())
        for i in range(int((W - LM - RM) // 8)):  # a stepped pixel rule
            c.setFillColor(GOLDC if i % 2 == 0 else colors.HexColor("#FFD76A"))
            c.rect(LM + i * 8, 0.72 * inch, 8, 2.5, stroke=0, fill=1)
        c.setFillColor(GRAY); c.setFont("Label", 7)
        c.drawString(LM, 0.52 * inch, "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026")
        c.setFont("Pix", 14); c.setFillColor(INK)
        c.drawRightString(W - RM, 0.5 * inch, f"PAGE {d.page}")

    doc = BaseDocTemplate(str(path), pagesize=letter, leftMargin=LM, rightMargin=RM, topMargin=1.1 * inch, bottomMargin=0.95 * inch,
                          title="BLHA Constitution", author="Beer League Hockey Association")
    frame = Frame(LM, 0.95 * inch, W - LM - RM, H - 2.05 * inch, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=on_cover),
                          PageTemplate(id="page", frames=[frame], onPage=on_page)])
    cw = W - LM - RM

    story: list = [NextPageTemplate("page"), PageBreak()]

    def stat_bar():
        cells = [[Paragraph(f'<font name="Pix" size="30" color="#FFB81C">{a}</font>', ParagraphStyle("c", alignment=1, leading=30)) for a, _ in S.GLANCE_STATS],
                 [Paragraph(label(b, "#F4EFE4", 6.5), ParagraphStyle("c2", alignment=1, leading=9)) for _, b in S.GLANCE_STATS]]
        t = Table(cells, colWidths=[cw / 4] * 4, rowHeights=[0.5 * inch, 0.3 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LINEAFTER", (0, 0), (-2, -1), 2, CHAR), ("LINEBELOW", (0, -1), (-1, -1), 4, GOLDC)]))
        return t

    def heading_rule(text, kicker=None):
        out = []
        if kicker:
            out.append(Paragraph(kicker.upper(), kick))
        out += [Paragraph(text, h_sec)]
        t = Table([[""]], colWidths=[cw], rowHeights=[4])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), INK)]))
        out.append(t); out.append(Spacer(1, 8))
        return out

    def label_table(rows, left_w, pad=2.2):
        t = Table(rows, colWidths=[left_w, cw - left_w])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, ICE]),
                               ("LINEBELOW", (1, 0), (1, -1), 0.6, LINE),
                               ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
        return t

    # glance page
    story += heading_rule("Constitution at a Glance", "League reference")
    story += [Paragraph("Core settings, financial structure, and league architecture for the BLHA Constitution.", sub), stat_bar(), Spacer(1, 14)]
    story += [Paragraph("Quick Reference", h_sec)]
    story += [label_table([[Paragraph(label(k), small), Paragraph(md(v), small)] for k, v in S.QUICK_REFERENCE], 1.3 * inch), Spacer(1, 10)]
    al_head = [Paragraph("Annual Financial Allocation", h_sec),
               Paragraph(f"<b>12 franchises × $150 = ${S.ALLOCATION_TOTAL:,} annual league pool.</b>", ParagraphStyle("al", parent=small, textColor=GRAY, spaceAfter=5))]

    def alloc_table():
        data = [[Paragraph(label("Annual allocation"), small), Paragraph(label("Amount"), right)]]
        for k, v in S.ALLOCATION:
            data.append([Paragraph(k, small), Paragraph(f'<font name="Pix" size="13">${v:,}</font>', right)])
        data.append([Paragraph(label("Total", "#F4EFE4"), small), Paragraph(f'<font name="Pix" size="15" color="#FFB81C">${S.ALLOCATION_TOTAL:,}</font>', right)])
        t = Table(data, colWidths=[cw - 1.3 * inch, 1.3 * inch])
        st = [("BACKGROUND", (0, 0), (-1, 0), BLACK), ("BACKGROUND", (0, -1), (-1, -1), BLACK),
              ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ICE]), ("LINEBELOW", (0, 1), (-1, -2), 0.6, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        for i, (k, _) in enumerate(S.ALLOCATION, 1):
            if k == "Dynasty Pot":
                st.append(("BACKGROUND", (0, i), (-1, i), CALL))
        t.setStyle(TableStyle(st))
        return t

    story += [KeepTogether(al_head + [alloc_table()]), Spacer(1, 12)]

    # TOC
    story += heading_rule("Table of Contents")
    story += [Paragraph(f"{len(S.ARTICLES)} articles define the BLHA's competitive rules, financial structure, governance, and long-term franchise protections.", sub)]
    toc_rows = [[Paragraph(f'<font name="Pix" size="14" color="#FFB81C">{a["num"]}</font>', ParagraphStyle("tn", alignment=1, leading=13.5)),
                 Paragraph(a["title"], toc_s)] for a in S.ARTICLES]
    tt = Table(toc_rows, colWidths=[0.55 * inch, cw - 0.55 * inch])
    tt.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), BLACK), ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, ICE]),
                            ("LINEBELOW", (1, 0), (1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2), ("LEFTPADDING", (1, 0), (1, -1), 9)]))
    story += [tt, PageBreak()]

    def article_header(art):
        num = Paragraph(f'<font name="Pix" size="24" color="#0E0F12">{art["num"]}</font>', ParagraphStyle("n", alignment=1, leading=24))
        ttl = Paragraph(f'{label("Article " + art["num"], "#FFB81C", 6.5)}<br/><font name="Pix" size="20" color="#F4EFE4">{art["title"]}</font>',
                        ParagraphStyle("t", leading=19))
        t = Table([[num, ttl]], colWidths=[0.95 * inch, cw - 0.95 * inch], rowHeights=[0.62 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), GOLDC), ("BACKGROUND", (1, 0), (1, 0), BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (1, 0), (1, 0), 12), ("LINEBELOW", (0, 0), (-1, -1), 4, GOLDC)]))
        return t

    def simple_table(pairs, head_l, head_r):
        data = [[Paragraph(label(head_l), small), Paragraph(label(head_r), right)]]
        data += [[Paragraph(k, small), Paragraph(f'<font name="Pix" size="13">{v}</font>', right)] for k, v in pairs]
        t = Table(data, colWidths=[2.0 * inch, 1.0 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLACK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ICE]),
                               ("LINEBELOW", (0, 1), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
        return t

    for art in S.ARTICLES:
        story.append(CondPageBreak(1.9 * inch))
        story.append(Spacer(1, 10))
        story.append(KeepTogether([article_header(art), Spacer(1, 9)]))
        if art["callout"]:
            lab, text = art["callout"]
            ct = Table([[Paragraph(f'{label(lab, "#8A5E00", 7)}<br/>{md(text)}', callout_s)]], colWidths=[cw])
            ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ICE), ("LINEBEFORE", (0, 0), (0, -1), 4, GOLDC),
                                    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
            story += [ct, Spacer(1, 8)]
        n = 0
        for block in art["blocks"]:
            kind = block[0]
            if kind == "p":
                n += 1
                chip = f'<font name="Pix" size="12" color="#FFB81C" backColor="#14161A">&nbsp;{art_num(art)}.{n}&nbsp;</font>'
                story.append(Paragraph(f"{chip}&nbsp;&nbsp;{md(block[1])}", body))
            elif kind == "allocation":
                story += [KeepTogether([alloc_table()]), Spacer(1, 7)]
            elif kind == "scoring":
                left = simple_table(S.SKATERS, "Skaters", "Pts")
                right_t = simple_table(S.GOALIES, "Goalies", "Pts")
                two = Table([[left, right_t]], colWidths=[cw / 2, cw / 2])
                two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
                story += [two, Spacer(1, 7)]
            elif kind == "dates":
                story += [label_table([[Paragraph(label(k), small), Paragraph(md(v), small)] for k, v in S.DATE_RULES], 1.6 * inch, 3.5),
                          Spacer(1, 7)]
            elif kind == "history":
                entries = history_rows(block[1])
                head = "Edition" if entries == list(block[1]) else "Adopted"
                left_w = 0.9 * inch if entries == list(block[1]) else 1.45 * inch
                rows = [[Paragraph(label(head), small), Paragraph(label("Change"), small)]]
                rows += [[Paragraph(f"<b>{v}</b>", small), Paragraph(md(t), small)] for v, t in entries]
                ht = Table(rows, colWidths=[left_w, cw - left_w])
                ht.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLACK), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ICE]),
                                        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
                last = story.pop()
                story.append(KeepTogether([last, Spacer(1, 4), ht]))
    story += [Spacer(1, 16), Paragraph('<font name="Pix" size="16" color="#8A5E00">–  END OF CONSTITUTION  –</font>', ParagraphStyle("e", alignment=1, leading=18))]
    doc.build(story)


# ------------------------------------------------------------------------ main
def main() -> None:
    msgs = build_discord()
    for old in OUT_TEMPLATES.glob("*.json"):
        if not posted.is_posted(f"constitution/{old.name}"):
            old.unlink()
    OUT_TEMPLATES.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.mkdir(exist_ok=True)

    msgs = [(name, posted.keep_posted(f"constitution/{name}", data)) for name, data in msgs]
    for name, data in msgs:
        (OUT_TEMPLATES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        counted = fmt.message_chars(data["embeds"])
        errors = fmt.problems(data["embeds"], rel=f"constitution/{name}", cont=name != msgs[-1][0])
        assert not errors, (name, errors)
        for e in data["embeds"]:
            assert len(e.get("description", "")) <= 4096, (name, e.get("title"))
            assert len(e.get("title", "")) <= 256
        print(f"{name}: {len(data['embeds'])} embeds, {counted} chars")

    (OUT_DOCS / "BLHA_Constitution.md").write_text(build_markdown(), encoding="utf-8")
    (OUT_DOCS / "CHANGELOG.md").write_text(build_changelog(S.AMENDMENTS), encoding="utf-8")
    backup = {"messages": [{"data": d} for _, d in msgs]}
    (OUT_DOCS / "BLHA_Constitution_discohook_backup.json").write_text(json.dumps(backup, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if "--pdf" in sys.argv:
        build_pdf(OUT_DOCS / "BLHA_Constitution.pdf")
    print(f"Built {len(msgs)} Discord messages for the Constitution.")


if __name__ == "__main__":
    main()
