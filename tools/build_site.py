#!/usr/bin/env python3
"""Build the BLHA history website (static HTML, no JavaScript) into site/.

Reads the league archive (the automation-state branch's archive/ folder),
automation/history/history.yaml, automation/league.yaml and the Constitution
(constitution/BLHA_Constitution.md and CHANGELOG.md). Builds cleanly from an
empty archive. site/ is git-ignored; the BLHA History Site workflow publishes
it to GitHub Pages.

Usage: python tools/build_site.py [--archive PATH] [--out site]
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))

from blha.league import load_league  # noqa: E402
from history.context import LeagueHistory, initials, natural  # noqa: E402
from history.profiles import dynasty_summary, franchise_profiles  # noqa: E402
from history.records import AWARDS, Records, money  # noqa: E402
from history.rivals import HeadToHead, declared_rivals  # noqa: E402
from history.store import Archive, default_dir  # noqa: E402
from history.trades import Node, trade_trees  # noqa: E402

CONSTITUTION = ROOT / "constitution" / "BLHA_Constitution.md"
CHANGELOG = ROOT / "constitution" / "CHANGELOG.md"
BRAND = {
    "favicon.png": ROOT / "brand" / "kit" / "02_avatars_icons" / "blha-favicon-256.png",
    "b-mark.png": ROOT / "brand" / "primary" / "blha-b-mark.png",
    "wordmark.png": ROOT / "brand" / "kit" / "01_logos" / "blha-wordmark-white-transparent.png",
}
PAGES = [
    ("index.html", "Home"),
    ("standings.html", "Standings"),
    ("rivalries.html", "Rivalries"),
    ("trades.html", "Trades"),
    ("drafts.html", "Drafts"),
    ("franchises.html", "Franchises"),
    ("constitution.html", "Constitution"),
]

CSS = """
:root{--charcoal:#2B2D31;--black:#0C0D0F;--gold:#FFB81C;--cream:#F4EFE4;--grey:#A3A5AB;--line:#3B3D43;--panel:#1C1D21;--panel2:#24262A}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--black);color:var(--cream);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
a{color:var(--gold);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
header.top{background:var(--charcoal);border-bottom:4px solid var(--gold)}
header.top .wrap{display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px;padding-top:10px;padding-bottom:10px}
.brand{display:flex;align-items:center;gap:10px;color:var(--cream);font-weight:800;letter-spacing:.08em;text-transform:uppercase}
.brand img{height:40px;width:auto}.brand em{color:var(--gold);font-style:normal}
nav{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.92rem}
nav a{color:var(--cream);padding:4px 0;border-bottom:2px solid transparent}
nav a[aria-current=page]{color:var(--gold);border-bottom-color:var(--gold)}
main{padding:28px 16px 48px}
h1,h2,h3{line-height:1.2;margin:1.6em 0 .5em}
h1{font-size:clamp(1.7rem,4vw,2.5rem);text-transform:uppercase;letter-spacing:.03em;margin-top:.2em}
h2{font-size:1.35rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:2px solid var(--gold);padding-bottom:6px}
h3{font-size:1.08rem;color:var(--gold)}
.kicker{color:var(--gold);font-weight:800;letter-spacing:.14em;text-transform:uppercase;font-size:.78rem;margin:0}
.lead{color:var(--grey);max-width:70ch}
.muted{color:var(--grey)}
.hero{display:flex;flex-wrap:wrap;align-items:center;gap:24px;background:var(--charcoal);border-left:8px solid var(--gold);padding:24px;margin-bottom:28px}
.hero img{width:min(340px,100%);height:auto}
.hero>div{flex:1 1 280px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.panel{background:var(--charcoal);padding:18px 20px;border-top:4px solid var(--gold)}
.panel h2,.panel h3{margin-top:0;border:0;padding:0}
.big{font-size:clamp(2.2rem,7vw,3.4rem);font-weight:800;color:var(--gold);line-height:1;margin:.15em 0}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 0 18px}
table{border-collapse:collapse;width:100%;font-size:.94rem}
th{color:var(--gold);text-transform:uppercase;letter-spacing:.06em;font-size:.74rem;text-align:left;padding:8px 10px;border-bottom:2px solid var(--gold);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:nth-child(even){background:var(--panel)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.matrix td,.matrix th{text-align:center;padding:6px 8px;white-space:nowrap}
.matrix th:first-child,.matrix td:first-child{text-align:left;position:sticky;left:0;background:var(--charcoal)}
.matrix .self{background:var(--panel2);color:var(--grey)}
.pips{display:inline-flex;gap:5px;vertical-align:middle}
.pips i{width:13px;height:13px;border-radius:50%;border:2px solid var(--grey);display:inline-block}
.pips i.on{background:var(--gold);border-color:var(--gold)}
.empty{border:1px dashed var(--line);padding:16px 18px;color:var(--grey);background:var(--panel)}
details{background:var(--panel);border-left:3px solid var(--line);margin:0 0 10px;padding:8px 14px}
details[open]{border-left-color:var(--gold)}
summary{cursor:pointer;font-weight:600}
.tree,.tree ul{list-style:none;margin:6px 0 4px;padding-left:18px;border-left:2px solid var(--line)}
.tree{padding-left:12px}
.tree li{margin:4px 0}
.tree .out{color:var(--grey)}
.card{background:var(--charcoal);border-top:8px solid var(--gold);display:flex;flex-direction:column}
.card .head{display:flex;gap:14px;align-items:center;padding:16px 18px 6px}
.card .logo{width:64px;height:64px;flex:none;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:1.3rem;overflow:hidden;border:3px solid var(--cream)}
.card .logo img{width:100%;height:100%;object-fit:contain;background:var(--black)}
.card h3{margin:0;color:var(--cream);font-size:1.2rem}
.card dl{margin:6px 18px 18px;display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:.93rem}
.card dt{color:var(--gold);text-transform:uppercase;font-size:.72rem;letter-spacing:.08em;padding-top:.25em}
.card dd{margin:0}
.swatches{display:flex;gap:6px}.swatches i{width:18px;height:18px;border:1px solid var(--grey);display:inline-block}
.doc{max-width:78ch}
.doc blockquote{margin:1em 0;padding:10px 16px;background:var(--panel);border-left:4px solid var(--gold)}
.doc table{margin:1em 0}
.toc{columns:2 260px;font-size:.92rem;padding-left:1.2em}
footer{color:var(--grey);font-size:.82rem;padding:22px 16px 40px;border-top:1px solid var(--line)}
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def table(head: list[str], rows: list[list[str]], *, num: set[int] = frozenset(), cls: str = "") -> str:
    """Rows are already-escaped HTML cells."""
    th = "".join(f'<th class="num">{esc(h)}</th>' if i in num else f"<th>{esc(h)}</th>" for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td class="num">{c}</td>' if i in num else f"<td>{c}</td>"
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def empty(text: str) -> str:
    return f'<p class="empty">{esc(text)}</p>'


def pips(count: int, need: int) -> str:
    dots = "".join('<i class="on"></i>' if i < count else "<i></i>" for i in range(max(need, count)))
    return f'<span class="pips" role="img" aria-label="{count} of {need}">{dots}</span>'


def page(name: str, title: str, body: str, built: str) -> str:
    nav = "".join(f'<a href="{href}"{" aria-current=page" if href == name else ""}>{esc(label)}</a>' for href, label in PAGES)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · BLHA History</title>
<meta name="description" content="Beer League Hockey Association league history: champions, standings, rivalries, trades, drafts and the Constitution.">
<link rel="icon" href="assets/favicon.png">
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header class="top"><div class="wrap"><a class="brand" href="index.html"><img src="assets/b-mark.png" alt="BLHA"><span>BLHA <em>History</em></span></a><nav aria-label="Sections">{nav}</nav></div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap">Beer League Hockey Association · Est. 2026 · Game data is read from Fantrax; honours and the Dynasty Pot come from the Commissioner's records. Built {esc(built)}.</footer>
</body>
</html>
"""


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


# --- pages -------------------------------------------------------------------------

class Site:
    def __init__(self, hist: LeagueHistory, out: Path, built: datetime) -> None:
        self.hist = hist
        self.out = out
        self.built = built
        self.h2h = HeadToHead(hist)
        self.profiles = franchise_profiles(hist, self.h2h)
        self.logos: dict[str, str] = {}

    def link(self, key: str) -> str:
        return f'<a href="franchises.html#f-{esc(slug(key))}">{esc(self.hist.name(key))}</a>'

    def season_title(self, season: int) -> str:
        label = self.hist.archive.meta(season).get("season_label") or ""
        text = f"Season {season}"
        return f"{text} ({label})" if label else text

    def write(self, name: str, title: str, body: str) -> None:
        stamp = f"{self.built.strftime('%b')} {self.built.day}, {self.built.year}"
        (self.out / name).write_text(page(name, title, body, stamp), encoding="utf-8")

    # assets
    def assets(self) -> None:
        folder = self.out / "assets"
        (folder / "logos").mkdir(parents=True, exist_ok=True)
        (folder / "site.css").write_text(CSS.strip() + "\n", encoding="utf-8")
        for name, source in BRAND.items():
            if not source.exists():
                continue
            if name == "wordmark.png" and not shrink(source, folder / name, 720):
                shutil.copyfile(source, folder / name)
            elif name != "wordmark.png":
                shutil.copyfile(source, folder / name)
        for p in self.profiles:
            logo = p.get("logo")
            if logo and (ROOT / logo).is_file():
                target = f"logos/{slug(p['key'])}.png"
                if not shrink(ROOT / logo, folder / target, 256):
                    shutil.copyfile(ROOT / logo, folder / target)
                self.logos[p["key"]] = "assets/" + target

    # home
    def home(self) -> None:
        hist, records = self.hist, self.hist.records
        pot = dynasty_summary(hist)
        need = pot["titles_to_win"]
        leaders = [r for r in pot["rows"] if r["titles"]]
        pot_rows = "".join(f"<tr><td>{self.link(r['key'])}</td><td>{pips(r['titles'], need)}</td></tr>" for r in leaders)
        pot_html = (f'<div class="scroll"><table><tbody>{pot_rows}</tbody></table></div>' if leaders
                    else '<p class="muted">No championships yet in this cycle.</p>')
        champs = []
        for year, row in sorted(records.seasons.items(), reverse=True):
            cells = [esc(year)] + [self.link(row[a]) if row.get(a) else '<span class="muted">—</span>' for a in AWARDS]
            champs.append(cells)
        champs_html = (table(["Season"] + list(AWARDS.values()), champs) if champs
                       else empty("No Season has finished yet. Champions are listed here once each Season is final."))
        past = pot["past"]
        past_html = ""
        if past:
            past_html = "<h2>Dynasty Pot winners</h2>" + table(
                ["Cycle", "Winner", "Payout"],
                [[esc(f"Seasons {c['started']}–{c['ended']}"), esc(c["winner"]), esc(money(c["payout"]))] for c in past],
                num={2})
        latest = hist.archive.latest_season()
        status = ""
        if latest is not None:
            meta = hist.archive.meta(latest)
            status = (f'<p class="muted">Archive: {esc(self.season_title(latest))}, last snapshot '
                      f'{esc(hist.date(meta.get("last_snapshot")))}. {len(hist.trades())} trade{"" if len(hist.trades()) == 1 else "s"} recorded.</p>')
        body = f"""
<section class="hero"><img src="assets/wordmark.png" alt="BLHA, Beer League Hockey Association">
<div><p class="kicker">The permanent league record</p><h1>BLHA History</h1>
<p class="lead">Champions, standings, rivalries, trades and drafts of the Beer League Hockey Association, a 12-franchise dynasty league.</p>{status}</div></section>
<div class="grid">
<section class="panel"><p class="kicker">Article IV</p><h2>Dynasty Pot</h2><p class="big">{esc(money(pot['balance']))}</p>
<p class="muted">Cycle began Season {esc(pot['cycle_started'])}. The first franchise to win {need} BLHA Championships in one cycle takes the whole pot.</p>{pot_html}</section>
<section class="panel"><p class="kicker">Explore</p><h2>Records</h2><ul>
<li><a href="standings.html">Standings and weekly results</a></li><li><a href="rivalries.html">Head-to-head and rivalries</a></li>
<li><a href="trades.html">Trade log and trade trees</a></li><li><a href="drafts.html">Drafts and retrospectives</a></li>
<li><a href="franchises.html">Franchises</a></li><li><a href="constitution.html">The Constitution and its changelog</a></li></ul></section>
</div>
<h2>Champions</h2>
{champs_html}
{past_html}
"""
        self.write("index.html", "Home", body)

    # standings
    def standings(self) -> None:
        hist = self.hist
        parts = ['<p class="kicker">League record</p><h1>Standings</h1>']
        if not hist.seasons:
            parts.append(empty("No season has been archived yet. Standings appear after the first archive run."))
        for season in reversed(hist.seasons):
            parts.append(f'<h2 id="s{season}">{esc(self.season_title(season))}</h2>')
            honours = hist.records.seasons.get(season) or {}
            if honours:
                bits = [f"{esc(label)}: {self.link(honours[a])}" for a, label in AWARDS.items() if honours.get(a)]
                parts.append("<p>" + " · ".join(bits) + "</p>")
            saved = hist.archive.standings(season)
            if saved:
                rows = [[esc(r["rank"]), self.link(hist.franchise(r["teamId"])), esc(r["record"]), esc(f"{r['pointsFor']:.2f}")]
                        for r in saved.get("rows") or []]
                parts.append(f'<p class="muted">Final regular-season standings after Week {esc(saved.get("after_week"))}.</p>')
                parts.append(table(["Rank", "Franchise", "W-L-T", "Points for"], rows, num={0, 3}))
            else:
                computed, through = computed_standings(hist, season)
                if computed:
                    parts.append(f'<p class="muted">Through Week {through}, worked out from final weekly scores (not final).</p>')
                    parts.append(table(["Rank", "Franchise", "W-L-T", "Points for"],
                                       [[esc(i), self.link(k), esc(r["text"]), esc(f"{r['pf']:.2f}")] for i, (k, r) in enumerate(computed, 1)],
                                       num={0, 3}))
                else:
                    parts.append(empty("No week of this season has finished yet."))
            parts.append(self.weeks(season))
        self.write("standings.html", "Standings", "\n".join(parts))

    def weeks(self, season: int) -> str:
        hist = self.hist
        results = hist.archive.results(season)
        out = []
        for key, week in sorted(results.items(), key=lambda kv: -int(kv[0])):
            if not week.get("played", True) or not week.get("matchups"):
                continue
            label = f"Week {week.get('period', key)}" + (" (playoffs)" if week.get("playoff") else "")
            rows = []
            for m in week["matchups"]:
                a, b = m["away"], m["home"]
                wa, wb = a["score"] > b["score"], b["score"] > a["score"]
                name = lambda side, won: (f"<strong>{self.link(hist.franchise(side['team']))}</strong>" if won  # noqa: E731
                                          else self.link(hist.franchise(side["team"])))
                rows.append([name(a, wa), esc(f"{a['score']:.2f}"), esc(f"{b['score']:.2f}"), name(b, wb)])
            out.append(f"<details><summary>{esc(label)}</summary>{table(['Away', 'Score', 'Score', 'Home'], rows, num={1, 2})}</details>")
        return "\n".join(out)

    # rivalries
    def rivalries(self) -> None:
        hist, h2h = self.hist, self.h2h
        parts = ['<p class="kicker">Head to head</p><h1>Rivalries</h1>',
                 '<p class="lead">Lifetime records from every finished week, regular season and playoffs. A franchise\'s earned rival is the opponent it has played most, with the closest record breaking ties.</p>']
        declared = declared_rivals(hist)
        if declared:
            parts.append("<h2>Declared rivalries</h2>")
            parts.append(table(["Rivalry", "Record", "Games"],
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
                rows.append([self.link(k), self.link(rival) if rival else "—", esc(rec.text if rec else ""),
                             esc(rec.games if rec else 0), esc(h2h.lifetime(k).text)])
            parts.append(table(["Franchise", "Rival", "Record vs rival", "Games", "Lifetime"], rows, num={3}))
            parts.append("<h2>Head-to-head matrix</h2><p class=\"muted\">Row franchise's record against each column. Columns are numbered in the same order as the rows.</p>")
            head = "<th>Franchise</th>" + "".join(f'<th title="{esc(hist.name(k))}">{i}</th>' for i, k in enumerate(played, 1))
            body = ""
            for i, a in enumerate(played, 1):
                cells = "".join('<td class="self">—</td>' if a == b else f"<td>{esc(h2h.record(a, b).text) if h2h.record(a, b).games else ''}</td>"
                                for b in played)
                body += f"<tr><td>{i}. {self.link(a)}</td>{cells}</tr>"
            parts.append(f'<div class="scroll"><table class="matrix"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            parts.append("<h2>Every pairing</h2>")
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
        self.write("rivalries.html", "Rivalries", "\n".join(parts))

    # trades
    def tree_html(self, node: Node) -> str:
        def item(n: Node) -> str:
            kids = "<ul>" + "".join(item(c) for c in n.children) + "</ul>" if n.children else ""
            out = f' <span class="out">— {esc(n.outcome)}</span>' if n.outcome else ""
            return f"<li>{esc(n.label)}{out}{kids}</li>"

        kids = "".join(item(c) for c in node.children) or '<li class="out">Nothing recorded</li>'
        return f'<p><strong>{esc(node.label)}</strong> <span class="muted">{esc(node.outcome)}</span></p><ul class="tree">{kids}</ul>'

    def trades(self) -> None:
        hist = self.hist
        parts = ['<p class="kicker">Transactions</p><h1>Trades</h1>',
                 '<p class="lead">Trades are recorded from a daily snapshot of Fantrax, dated the day they were first seen. Open a trade to see its trade tree: what each side received and what those assets later became.</p>']
        trades = list(reversed(hist.trades()))
        if trades:
            for t in trades:
                sides = " · ".join(f"{esc(hist.name(hist.franchise(team)))} received {esc(', '.join(hist.asset(a) for a in t['received'].get(team, [])) or 'nothing')}"
                                   for team in t["teams"])
                trees = "".join(self.tree_html(node) for node in trade_trees(hist, t["id"]).values())
                flag = ' <span class="muted">(one-sided: possibly a drop and a claim between two daily snapshots)</span>' if t.get("one_sided") else ""
                parts.append(f'<details id="{esc(t["id"])}"><summary>{esc(hist.event_date(t))}: {sides}</summary>{flag}{trees}</details>')
        else:
            parts.append(empty("No trades recorded yet."))
        moves = [e for e in hist.events() if e.get("type") in ("add", "drop")][-150:]
        parts.append("<h2>Adds and drops</h2>")
        if moves:
            rows = [[esc(hist.event_date(e)), self.link(hist.franchise(e["team"])), esc("Added" if e["type"] == "add" else "Dropped"),
                     esc(hist.player(e["player"]))] for e in reversed(moves)]
            parts.append(table(["Seen", "Franchise", "Move", "Player"], rows))
        else:
            parts.append(empty("No adds or drops recorded yet."))
        self.write("trades.html", "Trades", "\n".join(parts))

    # drafts
    def drafts(self) -> None:
        hist = self.hist
        parts = ['<p class="kicker">Draft Center</p><h1>Drafts</h1>']
        drafts = hist.drafts()
        if not drafts:
            parts.append(empty("No completed draft has been archived yet."))
        for year in sorted(drafts, reverse=True):
            d = drafts[year]
            parts.append(f'<h2 id="d{year}">{esc(year)} Draft</h2>')
            retro = hist.archive.retro(int(d["season"]))
            if retro:
                from history.retro import highlight_lines

                as_of = hist.date(retro.get("as_of"))
                rows = "".join(f"<dt>{esc(label.title())}</dt><dd>{inline(text)}</dd>" for label, text in highlight_lines(retro))
                parts.append(f'<section class="panel"><h3>Retrospective (as of {esc(as_of)})</h3><dl>{rows}</dl>'
                             f'<p class="muted">{esc(retro.get("measure", ""))}</p></section>')
            rows = [[esc(f"{p['round']}.{int(p['in_round']):02d}"), esc(p["overall"]), self.link(hist.franchise(p["team"])),
                     esc(hist.player(p["player"])) if p.get("player") else '<span class="muted">not made</span>']
                    for p in d.get("picks") or []]
            parts.append(f"<details><summary>Full draft board ({len(rows)} picks)</summary>"
                         f"{table(['Pick', 'Overall', 'Franchise', 'Player'], rows, num={1})}</details>")
        self.write("drafts.html", "Drafts", "\n".join(parts))

    # franchises
    def franchises(self) -> None:
        cards = []
        for p in self.profiles:
            colors = p["colors"]
            logo = self.logos.get(p["key"])
            badge = (f'<span class="logo"><img src="{esc(logo)}" alt=""></span>' if logo else
                     f'<span class="logo" style="background:{esc(colors[0])};color:{esc(colors[1] if len(colors) > 1 else "#F4EFE4")}">{esc(initials(p['name']))}</span>')
            titles = p["titles"]
            awards = "; ".join(f"{label} {', '.join(map(str, years))}" for label, years in p["awards"].items() if label != "BLHA Champion")
            rival = f"{esc(p['rival'])} ({esc(p['rival_record'])}, {esc(p['rival_kind'])})" if p.get("rival") else '<span class="muted">To be decided</span>'
            swatches = "".join(f'<i style="background:{esc(c)}"></i>' for c in colors)
            cards.append(f"""<article class="card" id="f-{esc(slug(p['key']))}" style="border-top-color:{esc(colors[0])}">
<div class="head">{badge}<div><h3>{esc(p['name'])}</h3><span class="muted">{esc(p['owner'] or 'Owner to be announced')}</span></div></div>
<dl><dt>Founded</dt><dd>{esc(f"Season {p['founded']}" if p.get('founded') else '—')}</dd>
<dt>Titles</dt><dd>{esc(f"{len(titles)} ({', '.join(map(str, titles))})" if titles else 'None yet')}</dd>
<dt>Dynasty Pot</dt><dd>{pips(p['dynasty_count'], p['titles_to_win'])} {esc(p['dynasty_count'])} of {esc(p['titles_to_win'])} this cycle</dd>
<dt>Rival</dt><dd>{rival}</dd>
<dt>Lifetime</dt><dd>{esc(p['lifetime'])} in {esc(p['games'])} games</dd>
{f'<dt>Honours</dt><dd>{esc(awards)}</dd>' if awards else ''}
<dt>Colours</dt><dd><span class="swatches">{swatches}</span></dd></dl></article>""")
        body = '<p class="kicker">Franchise HQ</p><h1>Franchises</h1>'
        body += f'<div class="grid">{"".join(cards)}</div>' if cards else empty("No franchises recorded yet.")
        self.write("franchises.html", "Franchises", body)

    # constitution
    def constitution(self) -> None:
        body = ['<p class="kicker">League Office</p><h1>The Constitution</h1>']
        if CHANGELOG.exists():
            log, _ = markdown(CHANGELOG.read_text(encoding="utf-8"), shift=1)
            log = re.sub(r"<h2[^>]*>.*?</h2>", "", log, count=1)
            body.append(f'<details open><summary>Changelog</summary><div class="doc">{log}</div></details>')
        if CONSTITUTION.exists():
            text, anchors = markdown(CONSTITUTION.read_text(encoding="utf-8"), shift=0)
            text = re.sub(r"<h1[^>]*>.*?</h1>", "", text, count=1)
            toc = "".join(f'<li><a href="#{a}">{esc(t)}</a></li>' for a, t in anchors)
            body.append(f'<h2>Contents</h2><ol class="toc">{toc}</ol><div class="doc">{text}</div>')
        else:
            body.append(empty("The Constitution has not been published yet."))
        self.write("constitution.html", "Constitution", "\n".join(body))

    def build(self) -> list[str]:
        self.out.mkdir(parents=True, exist_ok=True)
        self.assets()
        steps: list[Callable[[], None]] = [self.home, self.standings, self.rivalries, self.trades, self.drafts,
                                           self.franchises, self.constitution]
        for step in steps:
            step()
        return [name for name, _ in PAGES]


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


def shrink(source: Path, target: Path, width: int) -> bool:
    """Write a smaller copy with Pillow (False if Pillow is not installed)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.convert("RGBA")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        img.save(target, optimize=True)
    return True


def build(archive: Path | None, out: Path, *, records: Records | None = None, league: dict[str, Any] | None = None,
          now: datetime | None = None) -> list[str]:
    if league is None:
        league = load_league()
    hist = LeagueHistory(Archive(archive or default_dir()), records=records, league=league)
    if out.exists():
        shutil.rmtree(out)
    return Site(hist, out, now or datetime.now(timezone.utc)).build()


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
