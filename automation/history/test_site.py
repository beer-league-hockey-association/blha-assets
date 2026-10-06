#!/usr/bin/env python3
"""Offline checks for the history website (tools/build_site.py) and the Constitution
changelog (tools/build_constitution.py)."""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

AUTOMATION = Path(__file__).resolve().parents[1]
REPO = AUTOMATION.parent
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_constitution as bc  # noqa: E402
import build_site  # noqa: E402
import constitution_source as cs  # noqa: E402
import test_history as th  # noqa: E402
from history import collect, testkit as kit  # noqa: E402
from history.records import Records  # noqa: E402
from history.store import Archive  # noqa: E402

PAGES = [name for name, _ in build_site.PAGES]
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def read(out: Path) -> dict[str, str]:
    return {name: (out / name).read_text(encoding="utf-8") for name in PAGES}


class SiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def build(self, archive: Path, records: Records, league: dict | None = None) -> dict[str, str]:
        out = self.base / "site"
        pages = build_site.build(archive, out, records=records, league=league or {"rivals": []}, now=NOW)
        self.assertEqual(pages, PAGES)
        for asset in ("site.css", "favicon.png", "b-mark.png", "wordmark.png"):
            self.assertTrue((out / "assets" / asset).is_file(), asset)
        return read(out)

    def common_checks(self, pages: dict[str, str]) -> None:
        for name, text in pages.items():
            self.assertTrue(text.startswith("<!doctype html>"), name)
            self.assertNotIn("<script", text, name)                       # no JavaScript at all
            self.assertIsNone(re.search(r'(src|href)="(https?:)?//', text), name)  # nothing loaded from elsewhere
            self.assertIsNone(re.search(r"\bNone\b(?! yet)|\bnan\b", re.sub(r"<[^>]+>", " ", text)), name)
            self.assertIn('name="viewport"', text)
            self.assertIn(f'href="{name}" aria-current=page', text)

    def test_builds_from_an_empty_archive(self) -> None:
        pages = self.build(self.base / "no-archive", Records({}))
        self.common_checks(pages)
        self.assertIn("No Season has finished yet", pages["index.html"])
        self.assertIn("$0", pages["index.html"])
        self.assertIn("No season has been archived yet", pages["standings.html"])
        self.assertIn("No trades recorded yet", pages["trades.html"])
        self.assertIn("No completed draft", pages["drafts.html"])
        self.assertIn("Article XX", pages["constitution.html"])
        self.assertIn("Adopted by owner acceptance. Effective Season 2027", pages["constitution.html"])
        self.assertNotIn("Do not edit", pages["constitution.html"])

    def test_builds_from_the_fantrax_fixtures(self) -> None:
        root = self.base / "archive"
        arch = Archive(root)
        raw = kit.rosters_raw()
        collect.run("live", now=datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc), fx=kit.FakeFantrax(rosters=raw),
                    archive=arch, cfg=kit.CFG)
        nxt = copy.deepcopy(raw)
        kit.move_player(nxt, "04lcs", "2tml63mumumuxoqh")
        picks = copy.deepcopy(kit.PICKS)
        kit.set_pick_owner(picks, 2028, 1, "2tml63mumumuxoqh", "gb4or3npmumb3mgv")
        kit.move_player(nxt, "04bdb", "gb4or3npmumb3mgv")
        collect.run("live", now=datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc),
                    fx=kit.FakeFantrax(rosters=nxt, picks=picks), archive=arch, cfg=kit.CFG)
        pages = self.build(root, Records({}), {"rivals": [["Test", "Test 3"]]})
        self.common_checks(pages)
        self.assertIn("Season 2026 (2026-27 TEST)", pages["standings.html"])
        self.assertIn("Through Week 3", pages["standings.html"])
        self.assertIn("2028 1st round pick (Test 3)", pages["trades.html"])
        self.assertIn("Not used yet", pages["trades.html"])
        self.assertIn("Jack Hughes (C, NJD)", pages["trades.html"])
        self.assertIn("Declared rivalries", pages["rivalries.html"])
        self.assertIn('class="matrix"', pages["rivalries.html"])
        self.assertIn("Full draft board (24 picks)", pages["drafts.html"])
        self.assertIn("Connor McDavid (C, EDM)", pages["drafts.html"])
        self.assertEqual(pages["franchises.html"].count('<article class="card"'), 12)
        self.assertLess(pages["franchises.html"].index(">Test 2<"), pages["franchises.html"].index(">Test 10<"))

    def test_builds_a_multi_season_history(self) -> None:
        root = self.base / "archive"
        th.build_archive(root)
        Archive(root).write(2028, "draft_retro.json", {
            "measure": "How it is measured.", "as_of": "2030-07-01T16:00:00+00:00",
            "steal": {"name": "Test Player13 (C, EDM)", "round": 2, "in_round": 3, "overall": 7, "franchise": "North Stars",
                      "value": 300.0, "gp": 100, "points": 60, "rank": 1}, "miss": None, "pickup": None, "development": None})
        records = Records(th.HISTORY)
        pages = self.build(root, records, {"rivals": [["north", "west"]]})
        self.common_checks(pages)
        home = pages["index.html"]
        self.assertIn("$435", home)
        self.assertIn("North Stars", home)
        self.assertIn('aria-label="2 of 3"', home)
        self.assertNotIn("2026-27 TEST", pages["standings.html"])               # test season hidden once real ones exist
        self.assertIn("Week 4 (playoffs)", pages["standings.html"])
        self.assertIn("Used at 2.03", pages["trades.html"])
        self.assertIn("Retrospective (as of Jul 1, 2030)", pages["drafts.html"])
        self.assertIn("<strong>Test Player13 (C, EDM)</strong>", pages["drafts.html"])
        self.assertIn("assets/logos/north.png", pages["franchises.html"])
        self.assertTrue((self.base / "site" / "assets" / "logos" / "north.png").is_file())
        self.assertIn("Presidents&#x27; Trophy 2027", pages["franchises.html"])

    def test_text_is_escaped(self) -> None:
        root = self.base / "archive"
        th.build_archive(root)
        data = json.loads(json.dumps(th.HISTORY))
        data["franchises"]["north"]["name"] = "<script>alert(1)</script> & Co"
        pages = self.build(root, Records(data))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co", pages["franchises.html"])
        self.assertNotIn("<script>", "".join(pages.values()))

    def test_markdown_subset(self) -> None:
        html, anchors = build_site.markdown(
            "<!-- hidden -->\n# Title\n\n## Article I — Start\n\n**1.1** Some *text* & more.\n\n"
            "> **NOTE** — quoted\n\n- one\n- two\n\n**HISTORY**\n• **Charter** — Adopted.\n\n"
            "| A | B |\n|---|---:|\n| x | **y** |")
        self.assertEqual(anchors, [("article-i-start", "Article I — Start")])
        self.assertNotIn("hidden", html)
        self.assertIn('<h2 id="article-i-start">', html)
        self.assertIn("<p><strong>1.1</strong> Some <em>text</em> &amp; more.</p>", html)
        self.assertIn("<blockquote><strong>NOTE</strong> — quoted</blockquote>", html)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", html)
        self.assertIn("<p><strong>HISTORY</strong></p>\n<ul><li><strong>Charter</strong> — Adopted.</li></ul>", html)
        self.assertIn("<td><strong>y</strong></td>", html)


SAMPLE = {
    "adopted": "2028-06-20", "articles": [], "sections": ["10.1"],
    "old": "Each franchise receives **$1,000 FAAB** at the beginning of each Season.",
    "new": "Each franchise receives **$1,200 FAAB** at the beginning of each Season.",
    "vote": {"yes": 9, "no": 2, "not_voted": 1}, "effective_season": 2028, "summary": "FAAB budget raised to $1,200.",
}


class ConstitutionChangelogTests(unittest.TestCase):
    def test_no_amendments_leaves_the_discord_templates_unchanged(self) -> None:
        self.assertEqual(cs.AMENDMENTS, [])
        for name, data in bc.build_discord():
            committed = (REPO / "templates" / "constitution" / name).read_text(encoding="utf-8")
            self.assertEqual(json.dumps(data, indent=2, ensure_ascii=False) + "\n", committed, name)
        self.assertEqual(bc.build_markdown(), (REPO / "constitution" / "BLHA_Constitution.md").read_text(encoding="utf-8"))

    def test_committed_changelog_is_current(self) -> None:
        self.assertEqual(bc.build_changelog(cs.AMENDMENTS), (REPO / "constitution" / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("## Charter\n\nAdopted by owner acceptance. Effective Season 2027", bc.build_changelog([]))

    def test_amendments_are_listed_by_date(self) -> None:
        with patch.object(cs, "AMENDMENTS", [SAMPLE]):
            log = bc.build_changelog(cs.AMENDMENTS)
            history = bc.build_markdown().split("**HISTORY**")[1]
            discord = json.dumps(bc.build_discord()[-1][1])
        self.assertIn("## Amended June 20, 2028", log)
        self.assertIn("- **Vote:** 9 yes, 2 no, 1 not voted", log)
        self.assertIn("> Each franchise receives **$1,200 FAAB**", log)
        self.assertLess(log.index("Amended June 20, 2028"), log.index("## Charter"))
        self.assertIn("• **Amended June 20, 2028** — Section 10.1. FAAB budget raised to $1,200. Vote 9 yes, 2 no, "
                      "1 not voted. Effective Season 2028.", history)
        self.assertIn("Amended June 20, 2028", discord)
        for text in (log, history):
            self.assertIsNone(re.search(r"\bv\d|\bversion \d", text, re.IGNORECASE))

    def test_bad_amendments_are_refused(self) -> None:
        bad = [{**SAMPLE, "vote": {"yes": 7, "no": 4, "not_voted": 1}},
               {**SAMPLE, "sections": ["X.1"]},
               {**SAMPLE, "adopted": "June 2028"},
               {**SAMPLE, "summary": "Version 2.0 of the rules"},
               {**SAMPLE, "effective_season": 2027},
               {**SAMPLE, "colour": "gold"}]
        for entry in bad:
            with self.assertRaises(ValueError, msg=entry):
                bc.check_amendments([entry])


if __name__ == "__main__":
    unittest.main(verbosity=2)
