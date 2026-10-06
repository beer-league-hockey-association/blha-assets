"""/rule: look up the Constitution by section, article or keyword.

The text comes from tools/constitution_source.py and the numbering from
tools/build_constitution.py itself (article_lines), so a section number here
is always the number in the published Constitution: the article's number plus
the count of its ("p", ...) paragraphs. Tables (allocation, scoring, dates,
history) are not numbered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from . import embeds as E
from .shared import build_constitution

FOOTER = "BLHA CONSTITUTION"
MAX_RESULTS = 3
SECTION_LINE = re.compile(r"^\*\*(\d+)\.(\d+)\*\* (.*)$", re.S)
SECTION_QUERY = re.compile(r"^(?:section|sec\.?|§|rule)?\s*(\d{1,2})\s*\.\s*(\d{1,2})$", re.I)
ARTICLE_QUERY = re.compile(r"^(?:(article|art\.?)\s*)?([ivxlc]+|\d{1,2})$", re.I)
ROMAN = re.compile(r"^(?=[ivxlc])(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)
STOP = {
    "a", "an", "the", "of", "and", "or", "to", "in", "on", "for", "is", "are", "be", "by", "it", "its",
    "what", "when", "how", "does", "do", "can", "i", "my", "we", "our", "with", "about", "if", "rule",
    "rules", "section", "article", "blha",
}


@dataclass(frozen=True)
class Section:
    article: int
    numeral: str
    article_title: str
    number: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.article}.{self.number}"


@dataclass(frozen=True)
class Article:
    number: int
    numeral: str
    title: str
    lines: tuple[str, ...]          # published lines: callout, sections and tables
    sections: tuple[Section, ...]


@dataclass
class Answer:
    embeds: list[dict[str, Any]] = field(default_factory=list)
    message: str | None = None      # plain reply when nothing matched


@lru_cache(maxsize=1)
def articles() -> tuple[Article, ...]:
    """Every article with its numbered sections, exactly as the build publishes them."""
    build = build_constitution()
    out = []
    for art in build.S.ARTICLES:
        lines = build.article_lines(art, "discord")
        offset = 1 if art["callout"] else 0
        number = build.art_num(art)
        sections, shown = [], list(lines[:offset])
        for block, line in zip(art["blocks"], lines[offset:], strict=True):
            if block[0] == "history":
                continue  # edition record, not a rule
            shown.append(line)
            if block[0] != "p":
                continue
            match = SECTION_LINE.match(line)
            if not match or int(match.group(1)) != number:
                raise ValueError(f"Unexpected Constitution line: {line[:60]}")
            sections.append(Section(number, art["num"], art["title"], int(match.group(2)), match.group(3)))
        out.append(Article(number, art["num"], art["title"], tuple(shown), tuple(sections)))
    return tuple(out)


def section(ref: str) -> Section | None:
    match = SECTION_QUERY.match(ref.strip())
    if not match:
        return None
    a, n = int(match.group(1)), int(match.group(2))
    return next((s for art in articles() if art.number == a for s in art.sections if s.number == n), None)


def plain(text: str) -> str:
    return text.replace("**", "")


def _stem(word: str) -> str:
    for suffix, keep in (("ing", 5), ("ed", 5)):
        if word.endswith(suffix) and len(word) - len(suffix) >= keep - 2:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", query.lower())
    return list(dict.fromkeys(_stem(w) for w in words if w not in STOP and len(w) > 1))


def search(query: str, limit: int = MAX_RESULTS) -> list[Section]:
    """Best keyword matches: sections matching the most terms, then the most often."""
    wanted = terms(query)
    if not wanted:
        return []
    phrase = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
    scored = []
    for art in articles():
        title_words = re.findall(r"[a-z0-9]+", art.title.lower())
        for s in art.sections:
            text = plain(s.text).lower()
            words = re.findall(r"[a-z0-9]+", text)
            matched, score = 0, 0
            for t in wanted:
                hits = sum(1 for w in words if w.startswith(t))
                in_title = any(w.startswith(t) for w in title_words)
                if hits or in_title:
                    matched += 1
                score += min(hits, 4) + (3 if in_title else 0)
            if len(wanted) > 1 and phrase and phrase in " ".join(words):
                score += 6
            if matched:
                scored.append((matched, score, s))
    if not scored:
        return []
    best = max(m for m, _, _ in scored)
    top = [x for x in scored if x[0] == best]
    top.sort(key=lambda x: (-x[1], x[2].article, x[2].number))
    return [s for _, _, s in top[:limit]]


def find_article(query: str) -> tuple[Article | None, str | None]:
    """(article, None), (None, error) or (None, None) when the query isn't an article reference."""
    match = ARTICLE_QUERY.match(query.strip())
    if not match:
        return None, None
    prefixed, token = bool(match.group(1)), match.group(2).lower()
    if token.isdigit():
        art = next((a for a in articles() if a.number == int(token)), None)
        label = token
    else:
        if not prefixed and not ROMAN.match(token):
            return None, None  # an ordinary word such as "civil"
        art = next((a for a in articles() if a.numeral.lower() == token), None)
        label = token.upper()
    if art is None:
        return None, f"There is no Article {label}. The Constitution has Articles I to {articles()[-1].numeral}."
    return art, None


# ------------------------------------------------------------------ rendering
def section_embed(s: Section) -> dict[str, Any]:
    return E.card(f"SECTION {s.ref}", f"**Article {s.numeral} — {s.article_title}**\n\n{s.text}", [], FOOTER)


def article_embeds(art: Article) -> list[dict[str, Any]]:
    """The whole article, split across embeds if needed and kept under 6,000 characters."""
    build = build_constitution()
    chunks = build.split_for_embeds(list(art.lines), 3900)
    title = f"ARTICLE {art.numeral} — {art.title.upper()}"
    budget = E.MESSAGE_MAX - 300
    kept: list[str] = []
    used = 0
    for chunk in chunks:
        if used + len(chunk) + len(title) + 20 > budget:
            last = art.sections[-1].ref if art.sections else ""
            kept.append(f"…the rest of Article {art.numeral} is too long to show here. Use `/rule {last}` "
                        "or a section number for the remaining sections.")
            break
        kept.append(chunk)
        used += len(chunk) + len(title) + 20
    out = [E.card(title if i == 0 else f"{title} (CONTINUED)", chunk, [], FOOTER) for i, chunk in enumerate(kept)]
    return E.finish(out)


def search_embed(query: str, found: list[Section]) -> dict[str, Any]:
    fields = [(f"{s.ref} • Article {s.numeral}: {s.article_title}", s.text) for s in found]
    shown = E.clip(query.strip(), 100)
    return E.card("CONSTITUTION SEARCH",
                  f"Best {'match' if len(found) == 1 else f'{len(found)} matches'} for **{shown}**. "
                  "Use `/rule` with a section number, like `/rule 12.4`, for one section.",
                  fields, FOOTER)


def answer(query: str) -> Answer:
    """Turn a /rule query into embeds, or a short message when nothing matches."""
    query = (query or "").strip()
    if not query:
        return Answer(message="Give a section (12.4), an article (XII) or a keyword (prepayment).")
    match = SECTION_QUERY.match(query)
    if match:
        found = section(query)
        if found:
            return Answer([section_embed(found)])
        a = int(match.group(1))
        art = next((x for x in articles() if x.number == a), None)
        if art is None:
            return Answer(message=f"There is no Section {a}.{match.group(2)}. The Constitution has "
                                  f"Articles 1 to {len(articles())}.")
        return Answer(message=f"There is no Section {a}.{match.group(2)}. Article {art.numeral} has sections "
                              f"{art.sections[0].ref} to {art.sections[-1].ref}.")
    art, error = find_article(query)
    if error:
        return Answer(message=error)
    if art:
        return Answer(article_embeds(art))
    found = search(query)
    if not found:
        return Answer(message=f"No section mentions “{E.clip(query, 100)}”. Try a section number like 12.4, "
                              "an article like XII, or a different word.")
    return Answer([search_embed(query, found)])
