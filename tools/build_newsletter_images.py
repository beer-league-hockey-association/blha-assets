"""Images for Last Call, the BLHA weekly email newsletter.

Email clients ignore web fonts, so the newsletter's pixel lettering comes from
these images: a masthead, one header per section and a footer band. Each is
drawn at twice the size it is shown (1200 px wide for a 600 px email column)
with the shared 8-bit toolkit, so it matches the channel headers.

Section headers sit on the email's cream paper (#F4EFE4) so they blend into
the body. Run `python tools/build_newsletter_images.py`; the files land in
brand/newsletter/.
"""

from __future__ import annotations

import blha_pixel as px
from blha_pixel import CHARCOAL, CREAM, GOLD, MUTED, STANDS, BLACK, CHAR_LT, CHAR_DK

OUT = px.ROOT / "brand" / "newsletter"

SECTIONS = {
    "week": "THE WEEK IN 60 SECONDS",
    "ahead": "THE WEEK AHEAD",
    "clubhouse": "AROUND THE CLUBHOUSE",
    "spotlight": "OWNER SPOTLIGHT",
    "prospects": "PROSPECT WATCH",
    "nhl": "AROUND THE NHL",
    "corner": "BEER LEAGUE CORNER",
    "commissioner": "FROM THE COMMISSIONER",
}


def masthead():
    """1200 x 300: the channel-header look with LAST CALL as the title."""
    k = 8
    a = px.art(150, 38, CHARCOAL)
    px.grain(a, [CHAR_LT, CHAR_DK], .02, 211)
    px.dither(a, 0, 29, 150, 7, STANDS)
    px.rect(a, 9, 6, 2, 26, GOLD)
    px.put(a, px.B32(), 113, 3)
    px.rect(a, 0, 36, 150, 2, GOLD)
    img = px.enlarge(a, k, (1200, 300), offset=(0, 4))
    x = 16 * k
    px.draw_text(img, "THE BLHA WEEKLY", "silk", 3, x, 52, GOLD)
    px.draw_text(img, "LAST CALL", "jersey", 12, x, 92, CREAM, shadow=BLACK)
    px.draw_text(img, "BEER LEAGUE HOCKEY ASSOCIATION • EST. 2026", "silk", 2, x, 240, MUTED)
    return img


def section(title: str):
    """1200 x 96 on cream: a gold pixel, the title in Silkscreen, a dashed gold rule."""
    a = px.art(300, 24, CREAM)
    px.rect(a, 0, 7, 5, 5, GOLD)
    for x in range(0, 300, 4):
        px.rect(a, x, 20, 2, 2, GOLD)
    img = px.enlarge(a, 4, (1200, 96))
    px.draw_text(img, title, "silk-bold", 6, 40, 24, CHARCOAL)
    return img


def footer():
    """1200 x 120 charcoal band: the small B and the sign-off."""
    a = px.art(150, 15, CHARCOAL)
    px.grain(a, [CHAR_LT, CHAR_DK], .02, 97)
    px.rect(a, 0, 0, 150, 1, GOLD)
    px.put(a, "b", 8, 1)
    img = px.enlarge(a, 8, (1200, 120))
    px.draw_text(img, "LAST CALL • THE BLHA WEEKLY", "silk", 3, 200, 36, CREAM)
    px.draw_text(img, "BEER LEAGUE HOCKEY ASSOCIATION", "silk", 2, 200, 76, MUTED)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"last-call-masthead.png": masthead(), "last-call-footer.png": footer()}
    files.update({f"last-call-section-{key}.png": section(title) for key, title in SECTIONS.items()})
    for name, img in files.items():
        img.convert("RGB").save(OUT / name, optimize=True)
    print(f"{len(files)} newsletter images in {OUT.relative_to(px.ROOT)}")


if __name__ == "__main__":
    main()
