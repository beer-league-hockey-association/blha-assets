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

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
SECTION_PAGES = [f"{key}/index.html" for key, _ in build_site.SECTIONS]
OWN_SITE = "https://blhahockey.com"


def read(out: Path) -> dict[str, str]:
    """Every HTML page in the built site, by path."""
    return {str(f.relative_to(out)): f.read_text(encoding="utf-8") for f in sorted(out.rglob("*.html"))}


class SiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.out = self.base / "site"

    def build(self, archive: Path, records: Records, league: dict | None = None) -> dict[str, str]:
        pages = build_site.build(archive, self.out, records=records, league=league or {"rivals": []}, now=NOW)
        for page in ["index.html", *SECTION_PAGES, "404.html"]:
            self.assertIn(page, pages)
        for asset in ("site.css", "favicon.png", "apple-touch-icon.png", "social-card.png", "BLHA_Constitution.pdf",
                      "fonts/jersey10.woff", "fonts/silkscreen.woff", "fonts/pixelifysans.woff",
                      "sprites/b.svg", "sprites/jersey.svg", "sprites/resurfacer.svg"):
            self.assertTrue((self.out / "assets" / asset).is_file(), asset)
        for extra in ("robots.txt", "_headers"):
            self.assertTrue((self.out / extra).is_file(), extra)
        return read(self.out)

    def standalone_checks(self, pages: dict[str, str]) -> None:
        """The site stands alone: nothing names or loads from GitHub or any other address, and every link works."""
        for f in self.out.rglob("*"):
            if f.is_file() and f.suffix in ("", ".html", ".css", ".txt", ".xml"):
                self.assertNotIn("github", f.read_text(encoding="utf-8").lower(), str(f))
        css = (self.out / "assets" / "site.css").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"url\((?!\"?/assets/)", css))                     # fonts are served by the site
        for name, text in pages.items():
            self.assertTrue(text.startswith("<!doctype html>"), name)
            self.assertNotIn("<script", text, name)                                    # no JavaScript at all
            self.assertNotIn(" style=", text, name)                                    # allowed by the strict CSP
            self.assertIn('name="viewport"', text)
            self.assertIsNone(re.search(r"\bNone\b(?! yet)|\bnan\b", re.sub(r"<[^>]+>", " ", text)), name)
            for attr, target in re.findall(r'\b(src|href)="([^"]*)"', text):
                if target.startswith("#"):
                    continue
                if target.startswith(OWN_SITE):                                        # canonical links to its own domain
                    target = target[len(OWN_SITE):]
                self.assertTrue(target.startswith("/"), f"{name}: {attr}={target} points outside the site")
                path = target.split("#")[0].split("?")[0]
                file = self.out / path.lstrip("/")
                if path.endswith("/"):
                    file = file / "index.html"
                self.assertTrue(file.is_file(), f"{name}: broken link {target}")
            for key, _ in build_site.SECTIONS:
                if name == f"{key}/index.html":
                    self.assertIn(f'href="/{key}/" aria-current=page', text)

    def test_builds_from_an_empty_archive(self) -> None:
        pages = self.build(self.base / "no-archive", Records({}))
        self.standalone_checks(pages)
        home = pages["index.html"]
        self.assertIn('class="banner pending"', home)                                  # an empty banner waits in the rafters
        self.assertIn("The first Season is still to come", home)
        self.assertIn("$0", home)
        self.assertIn("No Season has been archived yet", pages["seasons/index.html"])
        self.assertIn("No trades recorded yet", pages["trades/index.html"])
        self.assertIn("No completed draft", pages["drafts/index.html"])
        self.assertIn("no records", pages["records/index.html"])
        con = pages["constitution/index.html"]
        self.assertIn('<span class="art-no">Article XX</span>', con)                 # pixel article headings
        self.assertIn('<strong class="sec-no">1.1</strong>', con)                      # section number chips
        self.assertIn('<div class="qr"><ul>', con)                                     # the Quick Reference panel
        self.assertIn('href="/assets/BLHA_Constitution.pdf?v=', con)
        self.assertIn('<span class="zam"></span>', home)                               # the ice resurfacer on the rink
        css = (self.out / "assets" / "site.css").read_text()
        self.assertIn(":has(#article-i-league-identity-and-purpose:target)", css)
        sheet = (self.out / "assets" / "sprites" / "resurfacer.svg").read_text()
        self.assertIn('viewBox="0 0 112 28"', sheet)                                   # two 56 x 28 frames side by side
        self.assertIn("Adopted by owner acceptance. Effective Season 2027", pages["constitution/index.html"])
        self.assertNotIn("Do not edit", pages["constitution/index.html"])
        self.assertIn("isn't in the record book", pages["404.html"])
        self.assertNotIn("canonical", home)                                            # no domain set yet
        self.assertFalse((self.out / "sitemap.xml").exists())
        headers = (self.out / "_headers").read_text()
        self.assertIn("default-src 'none'", headers)
        self.assertIn("immutable", headers)

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
        self.standalone_checks(pages)
        self.assertIn("2026-27 TEST", pages["seasons/2026/index.html"])
        self.assertIn("Through Week 3", pages["seasons/2026/index.html"])
        self.assertIn("Season 2027 is the first that counts", pages["index.html"])
        self.assertIn('<span class="year">2027</span>', pages["index.html"])        # the first real Season's banner
        self.assertIn("2028 1st round pick (Test 3)", pages["trades/index.html"])
        self.assertIn("Not used yet", pages["trades/index.html"])
        self.assertIn("Jack Hughes (C, NJD)", pages["trades/index.html"])
        self.assertIn("Declared rivalries", pages["head-to-head/index.html"])
        self.assertIn('class="matrix"', pages["head-to-head/index.html"])
        self.assertIn("Full draft board (24 picks)", pages["drafts/index.html"])
        self.assertIn("Connor McDavid (C, EDM)", pages["drafts/index.html"])
        franchise_pages = [p for p in pages if p.startswith("franchises/") and p != "franchises/index.html"]
        self.assertEqual(len(franchise_pages), 12)
        index = pages["franchises/index.html"]
        self.assertLess(index.index(">Test 2<"), index.index(">Test 10<"))
        self.assertIn("Highest scores", pages["records/index.html"])

    def test_builds_a_multi_season_history(self) -> None:
        root = self.base / "archive"
        th.build_archive(root)
        Archive(root).write(2028, "draft_retro.json", {
            "measure": "How it is measured.", "as_of": "2030-07-01T16:00:00+00:00",
            "steal": {"name": "Test Player13 (C, EDM)", "round": 2, "in_round": 3, "overall": 7, "franchise": "North Stars",
                      "value": 300.0, "gp": 100, "points": 60, "rank": 1}, "miss": None, "pickup": None, "development": None})
        records = Records(th.HISTORY)
        pages = self.build(root, records, {"rivals": [["north", "west"]], "history_site": {"url": "https://blhahockey.com"}})
        self.standalone_checks(pages)
        home = pages["index.html"]
        self.assertIn("$435", home)
        self.assertIn('aria-label="2 of 3 titles"', home)
        self.assertEqual(home.count('<li class="banner"><span class="rod"></span><a href="/seasons/'), 2)  # two titles
        self.assertIn('<li class="banner cream">', home)                                # a Presidents' Trophy banner
        self.assertNotIn("seasons/2026", "".join(pages))                               # test season hidden once real ones exist
        self.assertIn("Week 4, playoffs", pages["seasons/2027/index.html"])
        self.assertIn("Used at 2.03", pages["trades/index.html"])
        self.assertIn("Retrospective, as of Jul 1, 2030", pages["drafts/index.html"])
        self.assertIn("<strong>Test Player13 (C, EDM)</strong>", pages["drafts/index.html"])
        north = pages["franchises/north/index.html"]
        self.assertIn("/assets/logos/north.png?v=", north)
        self.assertIn("Presidents&#x27; Trophy", pages["franchises/south/index.html"])
        self.assertIn("Championships</dt><dd>2 (2027, 2028)", north)
        self.assertIn('<link rel="canonical" href="https://blhahockey.com/franchises/north/">', north)
        self.assertIn('content="https://blhahockey.com/assets/social-card.png"', north)
        sitemap = (self.out / "sitemap.xml").read_text()
        self.assertIn("<loc>https://blhahockey.com/seasons/2027/</loc>", sitemap)
        self.assertNotIn("404", sitemap)
        self.assertIn("Sitemap: https://blhahockey.com/sitemap.xml", (self.out / "robots.txt").read_text())
        css = (self.out / "assets" / "site.css").read_text()
        self.assertIn(".f-north{--fc:#1D4E89;--fc2:#F4EFE4;--fc-ink:#F4EFE4}", css)
        jersey = (self.out / "assets" / "sprites" / "jersey-north.svg").read_text()   # team colours live on the jersey
        self.assertIn('fill="#1D4E89"', jersey)
        self.assertIn('fill="#F4EFE4"', jersey)
        self.assertIn('/assets/sprites/jersey-north.svg?v=', north)
        self.assertIn('class="fhero f-north"', north)                                  # and the stripe under the header
        self.assertIn('class="bracket', pages["seasons/2027/index.html"])

    def test_site_address_must_be_a_plain_https_domain(self) -> None:
        for bad in ("http://blhahockey.com", "https://blhahockey.com/history", "blhahockey.com"):
            with self.assertRaises(ValueError, msg=bad):
                build_site.site_url({"history_site": {"url": bad}})
        self.assertEqual(build_site.site_url({"history_site": {"url": "https://www.blhahockey.com/"}}), "https://www.blhahockey.com")
        self.assertEqual(build_site.site_url({}), "")

    def test_text_is_escaped(self) -> None:
        root = self.base / "archive"
        th.build_archive(root)
        data = json.loads(json.dumps(th.HISTORY))
        data["franchises"]["north"]["name"] = "<script>alert(1)</script> & Co"
        pages = self.build(root, Records(data))
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co", pages["franchises/index.html"])
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

    def test_readable_text_on_franchise_colours(self) -> None:
        self.assertEqual(build_site.ink_for("#FFB81C"), build_site.INK)
        self.assertEqual(build_site.ink_for("#1D4E89"), build_site.CREAM)


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
