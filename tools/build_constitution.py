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
        # One message each; footer text and divider on the final embed only.
        clean = fmt.apply(clean, rel=f"constitution/{name}")
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
def build_pdf(path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                    Spacer, Table, TableStyle, NextPageTemplate, CondPageBreak)

    fdir = "/usr/share/fonts/truetype/crosextra/"
    pdfmetrics.registerFont(TTFont("Body", fdir + "Carlito-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Bold", fdir + "Carlito-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Italic", fdir + "Carlito-Italic.ttf"))
    pdfmetrics.registerFont(TTFont("Body-BoldItalic", fdir + "Carlito-BoldItalic.ttf"))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")
    pdfmetrics.registerFont(TTFont("Head", "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Head-Med", "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"))

    CHAR = colors.HexColor("#2B2D31")
    GOLDC = colors.HexColor("#FFB81C")
    CREAM = colors.HexColor("#F4EFE4")
    INK = colors.HexColor("#1B1C1F")
    GREY = colors.HexColor("#6B6E75")
    BAND = colors.HexColor("#F3F3F1")
    CALL = colors.HexColor("#FFF6DD")

    W, H = letter
    LM = RM = 0.9 * inch

    body = ParagraphStyle("body", fontName="Body", fontSize=10.3, leading=14, textColor=INK, spaceAfter=5.5)
    small = ParagraphStyle("small", parent=body, fontSize=9.4, leading=12.5, spaceAfter=0)
    h_sec = ParagraphStyle("hsec", fontName="Head", fontSize=15, leading=19, textColor=INK, spaceBefore=4, spaceAfter=3)
    kick = ParagraphStyle("kick", fontName="Head", fontSize=7.5, leading=10, textColor=GOLDC)
    sub = ParagraphStyle("sub", fontName="Body", fontSize=11, leading=15, textColor=GREY, spaceAfter=10)
    toc_s = ParagraphStyle("toc", fontName="Body-Bold", fontSize=10.5, leading=14.5, textColor=INK)
    callout_s = ParagraphStyle("callout", parent=body, fontName="Body-Bold", fontSize=10.3, spaceAfter=0)

    def md(t: str) -> str:
        t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

    logo_black = str(ROOT / "brand" / "source" / "blha-wordmark-black.png")
    logo_white = str(ROOT / "brand" / "source" / "blha-wordmark-white.png")

    def on_cover(c, d):
        c.setFillColor(CHAR)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(GOLDC)
        c.rect(0.82 * inch, 0, 0.1 * inch, H, stroke=0, fill=1)
        c.rect(0, 0.62 * inch, W, 0.06 * inch, stroke=0, fill=1)
        c.drawImage(logo_white, W - 3.9 * inch, H - 3.0 * inch, width=3.2 * inch, height=3.2 * inch * 1086 / 1448, mask="auto")
        c.setFillColor(GOLDC); c.setFont("Head", 13); c.drawString(1.4 * inch, H - 3.35 * inch, "BEER LEAGUE HOCKEY ASSOCIATION")
        c.setFillColor(CREAM); c.setFont("Head", 40); c.drawString(1.4 * inch, H - 4.15 * inch, "CONSTITUTION")
        c.setFillColor(colors.HexColor("#B9BBC0")); c.setFont("Body", 13)
        c.drawString(1.4 * inch, H - 4.65 * inch, "A permanent framework for competition, governance,")
        c.drawString(1.4 * inch, H - 4.9 * inch, "and long-term franchise management.")
        c.setFillColor(colors.HexColor("#1F2023")); c.setStrokeColor(GOLDC); c.setLineWidth(1.6)
        c.roundRect(1.4 * inch, H - 6.35 * inch, 3.9 * inch, 0.85 * inch, 9, stroke=1, fill=1)
        c.setFillColor(CREAM); c.setFont("Head-Med", 11); c.drawString(1.62 * inch, H - 5.95 * inch, S.EDITION.upper())
        c.setFillColor(colors.HexColor("#B9BBC0")); c.setFont("Body", 9.5)
        c.drawString(1.62 * inch, H - 6.2 * inch, "Established 2026  •  Inaugural Season 2027–28")
        c.setFillColor(GOLDC); c.setFont("Head", 10); c.drawString(1.4 * inch, 1.15 * inch, "FANTRAX RUNS THE GAME.  DISCORD RUNS THE LEAGUE.")
        c.setFillColor(CREAM); c.setFont("Body", 8.5); c.drawString(1.4 * inch, 0.92 * inch, "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026")

    def on_page(c, d):
        c.setFillColor(GREY); c.setFont("Head", 7.5)
        c.drawString(LM, H - 0.6 * inch, "BLHA  /  CONSTITUTION")
        c.setFillColor(GOLDC); c.drawString(LM + 1.56 * inch, H - 0.6 * inch, S.EDITION.upper())
        c.drawImage(logo_black, W - RM - 1.1 * inch, H - 0.78 * inch, width=1.1 * inch, height=1.1 * inch * 1086 / 1448, mask="auto")
        c.setStrokeColor(GOLDC); c.setLineWidth(0.8); c.line(LM, 0.72 * inch, W - RM, 0.72 * inch)
        c.setFillColor(GREY); c.setFont("Body-Bold", 8)
        c.drawString(LM, 0.55 * inch, "BEER LEAGUE HOCKEY ASSOCIATION  •  EST. 2026")
        c.drawRightString(W - RM, 0.55 * inch, f"PAGE {d.page}")

    doc = BaseDocTemplate(str(path), pagesize=letter, leftMargin=LM, rightMargin=RM, topMargin=1.05 * inch, bottomMargin=0.95 * inch,
                          title="BLHA Constitution", author="Beer League Hockey Association")
    frame = Frame(LM, 0.95 * inch, W - LM - RM, H - 2.0 * inch, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=on_cover),
                          PageTemplate(id="page", frames=[frame], onPage=on_page)])
    cw = W - LM - RM

    story: list = [NextPageTemplate("page"), PageBreak()]

    def stat_bar():
        cells = [[Paragraph(f'<font name="Head" size="24" color="#FFB81C">{a}</font>', ParagraphStyle("c", alignment=1, leading=28)) for a, _ in S.GLANCE_STATS],
                 [Paragraph(f'<font name="Body-Bold" size="7.5" color="#F4EFE4">{b.upper()}</font>', ParagraphStyle("c2", alignment=1)) for _, b in S.GLANCE_STATS]]
        t = Table(cells, colWidths=[cw / 4] * 4, rowHeights=[0.5 * inch, 0.3 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CHAR), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#55575C"))]))
        return t

    def heading_rule(text, kicker=None):
        out = []
        if kicker:
            out.append(Paragraph(kicker.upper(), kick))
        out += [Paragraph(text.upper(), h_sec)]
        t = Table([[""]], colWidths=[cw], rowHeights=[2])
        t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.6, GOLDC)]))
        out.append(t); out.append(Spacer(1, 6))
        return out

    # glance page
    story += heading_rule("Constitution at a Glance", "League reference")
    story += [Paragraph("Core settings, financial structure, and league architecture for the BLHA Constitution.", sub), stat_bar(), Spacer(1, 12)]
    story += [Paragraph("QUICK REFERENCE", h_sec)]
    rows = [[Paragraph(f'<font name="Body-Bold" size="8" color="#FFB81C">{k.upper()}</font>', small), Paragraph(md(v), small)] for k, v in S.QUICK_REFERENCE]
    qt = Table(rows, colWidths=[1.25 * inch, cw - 1.25 * inch])
    qt.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), CHAR), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, BAND]),
                            ("TOPPADDING", (0, 0), (-1, -1), 1.7), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    story += [qt, Spacer(1, 8)]
    al_head = [Paragraph("ANNUAL FINANCIAL ALLOCATION", h_sec),
               Paragraph(f"<b>12 franchises \u00d7 $150 = ${S.ALLOCATION_TOTAL:,} annual league pool.</b>", ParagraphStyle("al", parent=small, textColor=GREY, spaceAfter=5))]

    def alloc_table():
        data = [[Paragraph('<font name="Body-Bold" color="#FFB81C" size="8.5">ANNUAL ALLOCATION</font>', small), Paragraph('<font name="Body-Bold" color="#FFB81C" size="8.5">AMOUNT</font>', ParagraphStyle("r", parent=small, alignment=2))]]
        for k, v in S.ALLOCATION:
            data.append([Paragraph(k, small), Paragraph(f"<b>${v:,}</b>", ParagraphStyle("r", parent=small, alignment=2))])
        data.append([Paragraph('<font name="Body-Bold" color="#F4EFE4">TOTAL</font>', small), Paragraph(f'<font name="Body-Bold" color="#FFB81C">${S.ALLOCATION_TOTAL:,}</font>', ParagraphStyle("r", parent=small, alignment=2))])
        t = Table(data, colWidths=[cw - 1.3 * inch, 1.3 * inch])
        st = [("BACKGROUND", (0, 0), (-1, 0), CHAR), ("BACKGROUND", (0, -1), (-1, -1), CHAR),
              ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]), ("TOPPADDING", (0, 0), (-1, -1), 2.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8)]
        for i, (k, _) in enumerate(S.ALLOCATION, 1):
            if k == "Dynasty Pot":
                st.append(("BACKGROUND", (0, i), (-1, i), CALL))
        t.setStyle(TableStyle(st))
        return t

    story += [KeepTogether(al_head + [alloc_table()]), Spacer(1, 12)]

    # TOC
    story += heading_rule("Table of Contents")
    story += [Paragraph(f"{len(S.ARTICLES)} articles define the BLHA's competitive rules, financial structure, governance, and long-term franchise protections.", sub)]
    toc_rows = [[Paragraph(f'<font name="Head" size="8" color="#FFB81C">{a["num"]}</font>&nbsp;&nbsp;{a["title"]}', toc_s)] for a in S.ARTICLES]
    tt = Table(toc_rows, colWidths=[cw])
    tt.setStyle(TableStyle([("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BAND]), ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]))
    story += [tt, PageBreak()]

    def article_header(art):
        num = Paragraph(f'<font name="Head" size="15" color="#2B2D31">{art["num"]}</font>', ParagraphStyle("n", alignment=1, leading=18))
        ttl = Paragraph(f'<font name="Head" size="6.5" color="#FFB81C">ARTICLE {art["num"]}</font><br/><font name="Head-Med" size="11.5" color="#F4EFE4">{art["title"].upper()}</font>', ParagraphStyle("t", leading=14))
        t = Table([[num, ttl]], colWidths=[0.95 * inch, cw - 0.95 * inch], rowHeights=[0.5 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), GOLDC), ("BACKGROUND", (1, 0), (1, 0), CHAR), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (1, 0), (1, 0), 10)]))
        return t

    def simple_table(pairs, head_l, head_r):
        data = [[Paragraph(f'<font name="Body-Bold" size="8.5">{head_l}</font>', small), Paragraph(f'<font name="Body-Bold" size="8.5">{head_r}</font>', ParagraphStyle("r", parent=small, alignment=2))]]
        data += [[Paragraph(k, small), Paragraph(f"<b>{v}</b>", ParagraphStyle("r", parent=small, alignment=2))] for k, v in pairs]
        t = Table(data, colWidths=[2.0 * inch, 1.0 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BAND), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                               ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
        return t

    for art in S.ARTICLES:
        story.append(CondPageBreak(1.9 * inch))
        story.append(Spacer(1, 10))
        story.append(KeepTogether([article_header(art), Spacer(1, 7)]))
        if art["callout"]:
            label, text = art["callout"]
            ct = Table([[Paragraph(f'<font name="Body-Bold" size="8" color="#FFB81C">{label}</font><br/>{md(text)}', callout_s)]], colWidths=[cw])
            ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CALL), ("LINEBEFORE", (0, 0), (0, -1), 3, GOLDC),
                                    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
            story += [ct, Spacer(1, 7)]
        n = 0
        for block in art["blocks"]:
            kind = block[0]
            if kind == "p":
                n += 1
                story.append(Paragraph(f'<font name="Body-Bold" color="#C98A00">{art_num(art)}.{n}</font>&nbsp;&nbsp;{md(block[1])}', body))
            elif kind == "allocation":
                story += [alloc_table(), Spacer(1, 7)]
            elif kind == "scoring":
                left = simple_table(S.SKATERS, "SKATERS", "PTS")
                right = simple_table(S.GOALIES, "GOALIES", "PTS")
                two = Table([[left, right]], colWidths=[cw / 2, cw / 2])
                two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
                story += [two, Spacer(1, 7)]
            elif kind == "dates":
                rows = [[Paragraph(f'<font name="Body-Bold" size="8" color="#FFB81C">{k.upper()}</font>', small), Paragraph(md(v), small)] for k, v in S.DATE_RULES]
                dt = Table(rows, colWidths=[1.55 * inch, cw - 1.55 * inch])
                dt.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), CHAR), ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, BAND]),
                                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
                story += [dt, Spacer(1, 7)]
            elif kind == "history":
                entries = history_rows(block[1])
                head = "EDITION" if entries == list(block[1]) else "ADOPTED"
                left = 0.9 * inch if entries == list(block[1]) else 1.45 * inch
                rows = [[Paragraph(f'<font name="Body-Bold" size="8.5" color="#FFB81C">{head}</font>', small), Paragraph('<font name="Body-Bold" size="8.5" color="#FFB81C">CHANGE</font>', small)]]
                rows += [[Paragraph(f"<b>{v}</b>", small), Paragraph(md(t), small)] for v, t in entries]
                ht = Table(rows, colWidths=[left, cw - left])
                ht.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), CHAR), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
                last = story.pop()
                story.append(KeepTogether([last, Spacer(1, 4), ht]))
    story += [Spacer(1, 14), Paragraph('<font name="Head" size="8" color="#FFB81C">–  END OF CONSTITUTION  –</font>', ParagraphStyle("e", alignment=1))]
    doc.build(story)


# ------------------------------------------------------------------------ main
def main() -> None:
    msgs = build_discord()
    for old in OUT_TEMPLATES.glob("*.json"):
        old.unlink()
    OUT_TEMPLATES.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.mkdir(exist_ok=True)

    for name, data in msgs:
        (OUT_TEMPLATES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        counted = fmt.message_chars(data["embeds"])
        errors = fmt.problems(data["embeds"], rel=f"constitution/{name}")
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
