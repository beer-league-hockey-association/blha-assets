"""BLHA print pieces: the Owner Welcome Packet, the Startup Draft cheat sheet and
the Awards Night program, ready to open and edit in DesignCraft.

    python tools/build_print_pieces.py              # brand/print/*.idml, *.pdf and art/
    python tools/build_print_pieces.py --package D  # also D/BLHA-Print-Pieces.zip with the fonts

Each piece is written as an IDML package (live text, paragraph styles, the
league swatches, art embedded) and as a PDF proof. Content follows the
Constitution; dates the Commissioner sets each season are left as [DATE].
The pixel fonts have no emoji, so channel emoji are small pictures set in the
line of text, and the art is drawn with the shared 8-bit toolkit.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import blha_pixel as px
import print_kit as pk
from discord_channels import EMOJI, LAYOUT
from print_kit import Box, CStyle, Doc, Frame, Inline, Page, Para, Pic, PStyle, Run

OUT = px.ROOT / "brand" / "print"
ART = OUT / "art"
EMOJI_FONT = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")

LETTER = (612.0, 792.0)
HALF = (396.0, 612.0)
M = 54.0            # Letter margin
CW = 504.0          # Letter content width
COL = 246.0         # Letter half column
COL2 = M + COL + 12

# ------------------------------------------------------------------ art
def art_path(name: str) -> Path:
    ART.mkdir(parents=True, exist_ok=True)
    return ART / name


def make_art() -> dict[str, Path]:
    art = {}
    splash = px.enlarge(px.bg_splash(240, 135), 8, (1920, 1080))
    art["splash"] = pk.png_with_dpi(splash.convert("RGB"), art_path("packet-cover-rink.png"), 630)

    a = px.art(208, 44, px.CHARCOAL)
    px.grain(a, [px.CHAR_LT, px.CHAR_DK], .02, 41)
    px.dither(a, 0, 33, 208, 9, px.STANDS)
    px.rect(a, 0, 42, 208, 2, px.GOLD)
    px.rect(a, 23, 11, 2, 22, px.GOLD)
    px.put(a, px.B32(), 160, 7)
    art["band"] = pk.png_with_dpi(px.enlarge(a, 8, (1664, 352)).convert("RGB"), art_path("draft-header-band.png"), 630)

    banner = px.enlarge(px.bg_banner(138, 210), 10, (1380, 2100))
    art["arena"] = pk.png_with_dpi(banner.convert("RGB"), art_path("awards-cover-arena.png"), 414)

    seal = px.seal(dark=True, k=2)
    art["seal"] = pk.png_with_dpi(seal, art_path("blha-seal-dark.png"), 120)
    mark = px.lockup(36, 6, "cream")
    art["logo"] = pk.png_with_dpi(mark, art_path("blha-wordmark-cream.png"), 220)
    art["logo_size"] = (220, 220 * mark.height / mark.width)
    art["bmark"] = px.ROOT / "brand" / "primary" / "blha-b-mark.png"
    return art


_EF = None


def emoji_png(e: str, bar: str | None) -> Path:
    """One emoji as a picture; with `bar` ("light" or "dark") it carries Discord's divider: 🏒│"""
    global _EF
    key = "-".join(f"{ord(c):x}" for c in e) + (f"-{bar}" if bar else "")
    path = art_path(f"emoji/{key}.png")
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if _EF is None:
        _EF = ImageFont.truetype(str(EMOJI_FONT), 109, layout_engine=ImageFont.Layout.RAQM)
    raw = Image.new("RGBA", (180, 160), (0, 0, 0, 0))
    ImageDraw.Draw(raw).text((10, 10), e, font=_EF, embedded_color=True)
    glyph = raw.crop(raw.getbbox())
    s = 120 / max(glyph.size)
    glyph = glyph.resize((round(glyph.width * s), round(glyph.height * s)), Image.LANCZOS)
    tile = Image.new("RGBA", (192 if bar else 128, 128), (0, 0, 0, 0))
    tile.alpha_composite(glyph, ((128 - glyph.width) // 2, 128 - glyph.height - 2))
    if bar:
        color = (160, 152, 136, 255) if bar == "light" else (120, 122, 128, 255)
        ImageDraw.Draw(tile).rectangle((150, 6, 155, 127), fill=color)
    tile.save(path, optimize=True)
    return path


# ------------------------------------------------------------------ styles
def styles(scale: float = 1.0) -> tuple[dict, dict]:
    S = lambda v: round(v * scale, 2)
    ps = [
        PStyle("Kicker", "Silkscreen", "Bold", S(8), S(10), "GoldDark", 80),
        PStyle("KickerGold", "Silkscreen", "Bold", S(8), S(10), "Gold", 80),
        PStyle("H1", "Jersey 10", "Regular", S(44), S(40)),
        PStyle("H1Light", "Jersey 10", "Regular", S(44), S(40), "Cream"),
        PStyle("H2", "Silkscreen", "Bold", S(8.5), S(12), "Charcoal", 60, before=S(12), after=S(5)),
        PStyle("Body", size=S(10.5), leading=S(15), after=S(6)),
        PStyle("BodyLight", size=S(10.5), leading=S(15), color="Cream", after=S(6)),
        PStyle("Letter", size=S(11.5), leading=S(17), after=S(9)),
        PStyle("Bullet", size=S(10), leading=S(14), left=S(11), first=S(-11), after=S(4), bullet=True),
        PStyle("BulletLight", size=S(10), leading=S(14), color="Cream", left=S(11), first=S(-11), after=S(4), bullet=True),
        PStyle("Small", size=S(8.5), leading=S(12), color="Muted", after=S(4)),
        PStyle("SmallLight", size=S(8.5), leading=S(12), color="Mist", after=S(4)),
        PStyle("Foot", "Silkscreen", "Regular", S(6.5), S(8), "Muted", 60),
        PStyle("FootRight", "Silkscreen", "Regular", S(6.5), S(8), "Muted", 60, "right"),
        PStyle("CoverKicker", "Silkscreen", "Bold", S(10), S(13), "Gold", 100),
        PStyle("CoverTitle", "Jersey 10", "Regular", S(80), S(66), "Cream"),
        PStyle("CoverSub", size=S(13), leading=S(19), color="Mist", after=S(6)),
        PStyle("CoverLine", "Silkscreen", "Regular", S(7.5), S(10), "Mist", 80),
        PStyle("TileNum", "Jersey 10", "Regular", S(38), S(32), "Gold", align="center"),
        PStyle("TileNote", size=S(8.5), leading=S(11.5), color="Mist", align="center"),
        PStyle("TileLabel", "Silkscreen", "Bold", S(6.5), S(8.5), "Cream", 60, "center"),
        PStyle("CalloutHead", "Silkscreen", "Bold", S(8), S(11), "Gold", 80, after=S(4)),
        PStyle("CalloutBody", size=S(10), leading=S(14.5), color="Cream", after=S(5)),
        PStyle("Check", size=S(10.5), leading=S(15), left=S(19), first=S(-19), after=S(7.5), tabs=((S(19), "left", ""),)),
        PStyle("DateLabel", "Silkscreen", "Bold", S(7), S(9), "GoldDark", 60),
        PStyle("DateTitle", "Pixelify Sans", "SemiBold", S(11.5), S(15)),
        PStyle("DateNote", size=S(9), leading=S(12), color="Muted"),
        PStyle("MapCat", "Silkscreen", "Bold", S(7.5), S(11), "GoldDark", 60, before=S(9), after=S(2)),
        PStyle("MapRow", size=S(9), leading=S(13)),
        PStyle("Sign", "Jersey 10", "Regular", S(24), S(24)),
        PStyle("Signoff", "Jersey 10", "Regular", S(30), S(28), "Cream"),
        PStyle("Num", "Jersey 10", "Regular", S(34), S(30), "GoldDark"),
        PStyle("ItemTitle", "Pixelify Sans", "SemiBold", S(12), S(15)),
        PStyle("ItemNote", size=S(9.5), leading=S(13), color="Muted"),
        PStyle("AwardName", "Jersey 10", "Regular", S(22), S(20)),
        PStyle("FieldLabel", "Silkscreen", "Bold", S(7), S(9), "Charcoal", 60),
        PStyle("FieldNote", "Silkscreen", "Regular", S(6.5), S(9), "Muted", 40, "right"),
        PStyle("TableHead", "Silkscreen", "Bold", S(6.5), S(8), "Cream", 60),
        PStyle("TableNum", "Pixelify Sans", "SemiBold", S(9), S(16), "Charcoal", align="center"),
        PStyle("Track", size=S(10), leading=S(16)),
        PStyle("CenterTitle", "Jersey 10", "Regular", S(72), S(60), "Cream", align="center"),
        PStyle("CenterKicker", "Silkscreen", "Bold", S(7.5), S(10), "Gold", 100, "center"),
        PStyle("CenterLabel", "Silkscreen", "Bold", S(10), S(14), "Gold", 120, "center"),
        PStyle("CenterSmall", size=S(11), leading=S(16), color="Mist", align="center"),
    ]
    cs = [
        CStyle("Strong", face="Bold", color="GoldDark"),
        CStyle("StrongLight", face="Bold", color="Gold"),
        CStyle("Channel", face="SemiBold"),
        CStyle("Muted", color="Muted"),
        CStyle("Mist", color="Mist"),
        CStyle("Accent", color="GoldDark"),
        CStyle("Gold", color="Gold"),
        CStyle("Label", font="Silkscreen", face="Bold", tracking=60),
    ]
    return {s.name: s for s in ps}, {s.name: s for s in cs}


def row_style(name: str, width: float, size: float = 10, leading: float = 16, color: str = "Charcoal", leader: str = ".",
              face: str = "Regular") -> PStyle:
    return PStyle(name, "Pixelify Sans", face, size, leading, color, tabs=((width, "right", leader),))


# ------------------------------------------------------------------ building
class Builder:
    def __init__(self, name: str, title: str, size: tuple[float, float], scale: float = 1.0):
        st, cs = styles(scale)
        self.doc = Doc(name, title, size[0], size[1], st, cs)

    def add_style(self, s: PStyle) -> str:
        self.doc.styles[s.name] = s
        return s.name

    def page(self) -> Page:
        p = Page()
        self.doc.pages.append(p)
        return p

    def P(self, style: str, text: str, marker: str | None = None) -> Para:
        return Para(style, pk.parse(self.doc, style, text, self._chan, self._emoji), marker)

    def _chan(self, slug: str, ps: PStyle) -> list:
        variant = "dark" if ps.color in pk.LIGHT_TEXT else "light"
        h = round(ps.size * 0.9, 2)
        return [Inline(round(h * 1.5, 2), h, emoji_png(EMOJI[slug], variant)), Run(slug, "Channel")]

    def _emoji(self, e: str, ps: PStyle) -> Inline:
        h = round(ps.size * 0.95, 2)
        return Inline(h, h, emoji_png(e, None))

    def T(self, pg: Page, x, y, w, h, *paras, inset=(0, 0, 0, 0)) -> None:
        pg.items.append(Frame(x, y, w, h, [p if isinstance(p, Para) else self.P(*p) for p in paras], inset))


def bg(pg: Page, size, color="Cream"):
    pg.items.append(Box(-9, -9, size[0] + 18, size[1] + 18, color))


def header(b: Builder, pg: Page, kicker: str, title: str, x=M, w=CW, y=46, h1="H1"):
    b.T(pg, x, y, w, 14, ("Kicker", kicker))
    b.T(pg, x, y + 12, w, 56, (h1, title))
    pg.items += [Box(x, y + 64, 8, 8, "Gold"), Box(x + 12, y + 67, w - 12, 2, "Gold")]


def footer(b: Builder, pg: Page, label: str, n: int, size=LETTER, m=M):
    w = size[0] - 2 * m
    y = size[1] - 38
    pg.items.append(Box(m, y - 6, w, 0.75, "CreamDark"))
    b.T(pg, m, y, w * 0.8, 12, ("Foot", label))
    b.T(pg, m + w * 0.8, y, w * 0.2, 12, ("FootRight", f"{n:02d}"))


def callout(b: Builder, pg: Page, x, y, w, h, head: str, *body, style="CalloutBody"):
    pg.items += [Box(x, y, w, h, "Charcoal"), Box(x, y, 4, h, "Gold")]
    b.T(pg, x + 4, y, w - 4, h, ("CalloutHead", head), *[(style, t) for t in body], inset=(12, 14, 10, 14))


def tile(b: Builder, pg: Page, x, y, w, h, big: str, label: str, note: str = ""):
    pg.items += [Box(x, y, w, h, "Charcoal"), Box(x, y + h - 3, w, 3, "Gold")]
    b.T(pg, x, y + 10, w, 46, ("TileNum", big))
    b.T(pg, x + 6, y + 46, w - 12, 20, ("TileLabel", label))
    if note:
        b.T(pg, x + 8, y + 58, w - 16, h - 62, ("TileNote", note))


# ------------------------------------------------------------------ Owner Welcome Packet
def welcome_packet(art) -> Doc:
    b = Builder("BLHA-Owner-Welcome-Packet", "BLHA Owner Welcome Packet", LETTER)
    rows = b.add_style(row_style("Row", COL))
    rows_b = b.add_style(row_style("RowTotal", COL, face="SemiBold"))
    foot = "BLHA • OWNER WELCOME PACKET"

    # 1 Cover
    pg = b.page()
    bg(pg, LETTER, "Charcoal")
    pg.items += [Pic(-9, 801 - 354.375, 630, 354.375, art["splash"]),
                 Pic(426, 70, 132, 152, art["bmark"]),
                 Box(M, 76, 5, 196, "Gold")]
    b.T(pg, 72, 62, 340, 18, ("CoverKicker", "BEER LEAGUE HOCKEY ASSOCIATION"))
    b.T(pg, 72, 82, 360, 228, ("CoverTitle", "OWNER"), ("CoverTitle", "WELCOME"), ("CoverTitle", "PACKET"))
    b.T(pg, 72, 306, 380, 70, ("CoverSub", "Everything a founding owner needs: how the league works, where the money goes, "
                                           "your first week and where to find it all in Discord."))
    b.T(pg, 72, 390, 480, 14, ("CoverLine", "SEASON 2027–28 • 12 FRANCHISES • EST. 2026"))

    # 2 Welcome letter
    pg = b.page()
    bg(pg, LETTER)
    lw, lh = art["logo_size"]
    pg.items.append(Pic((612 - lw) / 2, 140 - 12 - lh, lw, lh, art["logo"]))
    b.T(pg, 106, 150, 400, 14, ("Kicker", "FROM THE COMMISSIONER"))
    b.T(pg, 106, 162, 400, 56, ("H1", "WELCOME TO THE BLHA"))
    pg.items += [Box(106, 214, 8, 8, "Gold"), Box(118, 217, 388, 2, "Gold")]
    b.T(pg, 106, 232, 400, 380,
        ("Letter", "You're one of twelve founding owners in a dynasty league built to last: a Startup Draft in 2027, "
                   "an inaugural season in 2027–28, and a record book that starts with your name in it."),
        ("Letter", "The BLHA runs on two things. **Fantrax** is where the hockey happens: rosters, lineups, scoring, trades "
                   "and standings. **Discord** is the league office and the clubhouse: news, rulings, votes, trade talk and "
                   "a fair amount of chirping. The **Constitution** sits over both, and it's short enough to read in one sitting. "
                   "Please do."),
        ("Letter", "This packet is the quick version. It covers how the league works, where the money goes, what to do in "
                   "your first week and where everything lives in the server. When this packet and the Constitution "
                   "disagree, the Constitution wins."),
        ("Letter", "Build something you're proud of. Trade often. Set your lineup. Welcome to the league."),
        ("Sign", "The Commissioner"))
    pg.items += [Box(M, 608, CW, 118, "Charcoal"), Box(M, 608, 4, 118, "Gold")]
    b.T(pg, M + 18, 620, 200, 16, ("CalloutHead", "IN THIS PACKET"))
    cl = b.add_style(row_style("Contents", 210, 10, 15.5, "Cream", "."))
    b.T(pg, M + 18, 636, 210, 90, (cl, "The league at a glance\t03"), (cl, "Playing the season\t04"),
        (cl, "Scoring and the money\t05"), (cl, "Your first week\t06"))
    b.T(pg, M + 262, 636, 210, 90, (cl, "The Discord map\t07"), (cl, "Traditions and help\t08"))
    footer(b, pg, foot, 2)

    # 3 The league at a glance
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "01 • THE LEAGUE", "AT A GLANCE")
    tw = (CW - 24) / 3
    for i, (big, label) in enumerate([("12", "FRANCHISES"), ("$200", "DUES A SEASON"), ("22", "WEEKS • H2H POINTS"),
                                      ("6", "PLAYOFF TEAMS"), ("$1,000", "FAAB A SEASON"), ("36", "ROSTER SPOTS + 5 IR")]):
        tile(b, pg, M + (i % 3) * (tw + 12), 134 + (i // 3) * 82, tw, 70, big, label)
    b.T(pg, M, 290, COL, 420,
        ("H2", "FORMAT"),
        ("Body", "Head-to-Head Points with daily lineups. A 22-week regular season where every franchise plays every "
                 "other franchise twice. No divisions, no conferences."),
        ("Body", "Weeks run Monday to Sunday, and every league time is Eastern Time."),
        ("H2", "THE ROSTER"),
        (rows, "**Active**\t20"), ("Small", "3 C • 3 LW • 3 RW • 3 F • 6 D • 2 G. The F slot takes any forward."),
        (rows, "**Reserve**\t6"), (rows, "**Minors**\t10"), (rows, "**Injured reserve**\tup to 5"),
        (rows_b, "Controlled spots, not counting IR\t36"),
        ("Small", "An illegal roster has to be fixed within 24 hours of notice (6.4)."))
    b.T(pg, COL2, 290, COL, 330,
        ("H2", "MINORS"),
        ("Bullet", "Age 25 or younger on the first day of the NHL regular season, as Fantrax calculates it. A birthday "
                   "during the season doesn't change it."),
        ("Bullet", "Skaters qualify through 100 career NHL regular-season games. Goalies qualify through 50."),
        ("Bullet", "When Fantrax flags a minor as ineligible, you have 3 days to promote, trade or drop him."),
        ("Bullet", "Promotion doesn't burn eligibility. A player who still qualifies can go back down."),
        ("H2", "LINEUPS"),
        ("Body", "Set your lineup every day. Each player locks about one minute before his NHL game. Keep it legal and "
                 "reasonably competitive all season (9.1)."))
    callout(b, pg, COL2, 628, COL, 96, "THE CONSTITUTION CONTROLS",
            "This packet is the short version. When the two disagree, the Constitution wins (2.6). Read it in {ch:constitution}.")
    footer(b, pg, foot, 3)

    # 4 Playing the season
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "02 • THE SEASON", "PLAYING THE SEASON")
    b.T(pg, M, 128, COL, 600,
        ("H2", "WAIVERS AND FAAB"),
        ("Bullet", "$1,000 FAAB each season. It doesn't roll over."),
        ("Bullet", "Hidden bids in $1 steps, and $0 bids are allowed. A tie goes to the earliest bid."),
        ("Bullet", "Claims process daily around 11:00 AM ET. There are no first-come, first-served adds."),
        ("Bullet", "Up to 5 acquisitions per Week. Trades, draft picks and drops don't count."),
        ("H2", "GOALIE STARTS"),
        ("Body", "A maximum of **4 goalie starts** count each Week, and 8 across the two-week Championship. The live "
                 "scoreboard shows how many each team has used. Using a timing quirk to get credit past the maximum isn't "
                 "allowed (9.4)."),
        ("H2", "TRADES"),
        ("Bullet", "Unlimited, with no league vote and no veto."),
        ("Bullet", "Trade players, picks in the next three Annual Drafts (all five rounds) and current-season FAAB."),
        ("Bullet", "No conditional picks, cash, loans, rentals or side deals."),
        ("Bullet", "**Deadline:** Sunday 11:59 PM ET at the end of Week 20. Trading reopens the day after the Stanley Cup Final."),
        ("Bullet", "Report a misclick or platform error within 48 hours."))
    b.T(pg, COL2, 128, COL, 400,
        ("H2", "PLAYOFFS"),
        ("Bullet", "Six franchises make it. Seeds 1 and 2 get byes."),
        ("Bullet", "Quarterfinals are 3 vs. 6 and 4 vs. 5, and the bracket reseeds after each round."),
        ("Bullet", "Quarterfinals and Semifinals last one Week each. The Championship is a two-week cumulative matchup."),
        ("Bullet", "The Semifinal losers play for third place during the Championship."),
        ("Bullet", "The other six play a consolation bracket. Its champion gets a $50 FAAB bonus next season."),
        ("Bullet", "An exact tie goes to the higher seed."),
        ("H2", "STANDINGS TIEBREAKERS"),
        ("Body", "Points scored, then head-to-head among the tied teams, then Fantrax's next tiebreaker, then a random draw."))
    callout(b, pg, COL2, 546, COL, 180, "ANNUAL DRAFT ORDER",
            "**1.01 to 1.06** go to the six non-playoff teams, lowest Potential Points first: what your best possible "
            "lineup would have scored. Benching your stars won't move you up.",
            "**1.07–1.08** Quarterfinal losers • **1.09** fourth • **1.10** third • **1.11** runner-up • **1.12** champion. "
            "Five rounds, same order every round.")
    footer(b, pg, foot, 4)

    # 5 Scoring and the money
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "03 • POINTS AND DOLLARS", "SCORING AND THE MONEY")
    b.T(pg, M, 128, COL, 370,
        ("H2", "SKATERS"),
        (rows, "Goal\t+5.00"), (rows, "Assist\t+2.97"), (rows, "Shot on goal\t+0.53"), (rows, "Block\t+0.44"),
        (rows, "Hit\t+0.14"), (rows, "Penalty minute\t−0.36"),
        ("H2", "GOALIES"),
        (rows, "Game started\t+5.00"), (rows, "Save\t+0.56"), (rows, "Goal against\t−5.00"), (rows, "Goal\t+5.00"),
        (rows, "Assist\t+2.97"),
        ("Small", "Not scored: wins, shutouts, plus/minus, power-play bonuses, game-winning goals and faceoffs."))
    b.T(pg, COL2, 128, COL, 390,
        ("H2", "WHERE THE $2,400 GOES"),
        (rows, "BLHA Champion\t$850"), (rows, "Runner-Up\t$450"), (rows, "Third Place\t$200"),
        (rows, "Presidents' Trophy\t$250"), (rows, "Dynasty Pot\t$350"), (rows, "Operating Reserve\t$200"),
        (rows, "League Services\t$100"), (rows_b, "12 franchises × $200\t$2,400"),
        ("Small", "The Operating Reserve pays for Fantrax Premium and other approved costs, and whatever is left stays in the "
                  "reserve for future costs. League Services is the Commissioner's allocation for running the league (3.6)."),
        ("H2", "DUES"),
        ("Body", "$200 per franchise, due before each season's draft, paid through Fantrax Treasurer. A payment counts once "
                 "the Commissioner confirms it in the League Ledger. Prizes are paid within 30 days after the Championship, "
                 "with a Season Ledger in {ch:league-ledger}."))
    callout(b, pg, M, 466, COL, 124, "THE DYNASTY POT",
            "The first franchise to win **three BLHA Championships** in the same cycle takes the whole pot. They don't "
            "have to be in a row. It grows by at least $200 every season, then resets once it's won.")
    callout(b, pg, COL2, 466, COL, 124, "PAY FIRST, THEN TRADE",
            "To trade away a future 1st- or 2nd-round pick, your dues must be paid and confirmed through that pick's "
            "season first, or the whole trade is reversed (Article XII). Picks in rounds 3 to 5 need no prepayment.")
    b.T(pg, M, 604, CW, 18, ("H2", "SCORING IN ACTION"))
    tw = (CW - 36) / 4
    for i, (big, label, note) in enumerate([("+15.76", "A BIG NIGHT", "2 goals, 1 assist, 5 shots and a hit"),
                                            ("+3.05", "THE GRINDER", "3 shots, 4 blocks, 3 hits, 2 PIM"),
                                            ("+11.80", "A SOLID START", "30 saves, 2 goals against"),
                                            ("−14.36", "A ROUGH NIGHT", "19 saves, 6 goals against")]):
        tile(b, pg, M + i * (tw + 12), 626, tw, 100, big, label, note)
    footer(b, pg, foot, 5)

    # 6 Your first week
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "04 • GETTING STARTED", "YOUR FIRST WEEK")
    b.T(pg, M, 132, 280, 600,
        b.P("Check", "**Accept your Fantrax invite** and claim your franchise.", "box"),
        b.P("Check", "**Start in** {ch:welcome} and pick your notification roles under Channels & Roles.", "box"),
        b.P("Check", "**Read the Constitution** in {ch:constitution}. Joining the league means accepting it.", "box"),
        b.P("Check", "**Pay your $200 dues** through Fantrax Treasurer before the deadline on {ch:league-calendar}.", "box"),
        b.P("Check", "**Name your franchise:** a city and a team name, a short abbreviation and your colors. "
                     "It goes up in {ch:franchise-directory}.", "box"),
        b.P("Check", "**Turn on Fantrax app notifications** for trades, claims and lineup problems.", "box"),
        b.P("Check", "**Opt in to Lineup Alerts.** Ask the Commissioner, and {ch:lineup-alerts} will tell you when a "
                     "starter has no game but a reserve does.", "box"),
        b.P("Check", "**Watch your inbox** for Last Call, the league's weekly email.", "box"),
        b.P("Check", "**Say hello** in {ch:gm-lounge}.", "box"),
        b.P("Check", "**Build your draft queue** before the Startup Draft.", "box"))
    callout(b, pg, M, 590, 280, 136, "DRAFT DAY",
            "The Startup Draft cheat sheet has the draft rules, the scoring math and a board to fill in as you pick. "
            "Keep it next to you when the clock starts.")
    x = M + 300
    b.T(pg, x, 128, 204, 20, ("H2", "KEY DATES"))
    dates = [("Dues deadline", "At least 30 days' notice, and before the Startup Draft."),
             ("Startup Draft", "14 to 21 days after the NHL Entry Draft ends."),
             ("Roster compliance", "Announced before the draft."),
             ("Week 1", "With the NHL's opening night."),
             ("Trade deadline", "Sunday 11:59 PM ET, end of Week 20."),
             ("Regular season ends", "Sunday 11:59 PM ET, end of Week 22."),
             ("Playoffs", "Four Weeks: Quarterfinals, Semifinals and a two-week Championship."),
             ("Trading reopens", "The day after the Stanley Cup Final.")]
    y0, step = 152, 66
    pg.items.append(Box(x + 3, y0 + 4, 2, step * (len(dates) - 1), "CreamDark"))
    for i, (title, note) in enumerate(dates):
        y = y0 + i * step
        pg.items.append(Box(x, y + 1, 8, 8, "Gold"))
        b.T(pg, x + 18, y, 186, step, ("DateLabel", "[DATE]"), ("DateTitle", title), ("DateNote", note))
    b.T(pg, x, 690, 204, 30, ("Small", "Every date is posted on {ch:league-calendar}."))
    footer(b, pg, foot, 6)

    # 7 The Discord map
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "05 • THE SERVER", "THE DISCORD MAP")
    b.T(pg, M, 128, CW, 40, ("Body", "Discord is the league office and the clubhouse. Automated rooms post on their own; "
                                     "conversation happens in the rooms built for it."))
    what = {
        "welcome": "Start here", "constitution": "The rules, always current", "announcements": "Official notices",
        "league-calendar": "Every date and deadline", "league-ledger": "Dues, prizes and the Dynasty Pot",
        "league-voting": "Formal franchise votes", "hall-of-champions": "Every champion and award",
        "league-records": "League history and milestones",
        "breaking-news": "News that changes a decision now", "nhl-news": "The daily NHL feed",
        "injury-report": "Injury updates", "nhl-transactions": "Real NHL roster moves", "prospect-wire": "Prospect news",
        "news-desk": "Talk about the news",
        "gm-lounge": "The clubhouse", "game-day": "Live games, goalies, Pick'em", "chirps-and-memes": "Friendly trash talk",
        "off-topic": "Everything else", "media": "Clips, photos and graphics",
        "trade-block": "What you'll move", "looking-to-acquire": "What you're hunting for",
        "trade-discussion": "Ideas and valuations", "completed-trades": "The record of every trade",
        "player-values": "Dynasty values and rankings",
        "scouting": "Every prospect, one forum",
        "waiver-talk": "FAAB strategy and pickups", "waiver-watch": "Who to watch before claims run",
        "scoreboard": "Live scores for the Week", "standings": "After every Week", "weekly-recap": "Results and awards",
        "playoff-race": "Who's in, who's on the bubble", "playoffs": "Matchups and results",
        "consolation-bracket": "The other six", "lineup-alerts": "Daily heads-up (opt in)",
        "commissioner-support": "Private help from the Commissioner", "rules-questions": "Ask how a rule works",
        "league-suggestions": "Ideas, start to finish", "open-a-ticket": "Private tickets and appeals",
        "rulings-log": "Official rulings", "owner-handbook": "The week-to-week basics",
        "draft-announcements": "Official draft notices", "draft-room": "Live draft talk",
        "draft-day-trades": "Trades during the draft", "draft-results": "The pick-by-pick board",
        "franchise-directory": "Every franchise and owner", "franchise-news": "News from each franchise",
        "roster-showcase": "Show off your team",
    }
    cats = []
    for cat, chans in LAYOUT.items():
        emoji, _, name = cat.partition(" ")
        shown = [s for s in chans if s in what]
        paras = [b.P("MapCat", f"{{em:{emoji}}} {name}")]
        paras += [b.P("MapRow", f"{{ch:{s}}}  {{Muted:{what[s]}}}") for s in shown]
        cats.append(paras)
    missing = set(what) - {s for c in LAYOUT.values() for s in c}
    assert not missing, missing
    left = [p for c in cats[:4] for p in c]
    right = [p for c in cats[4:] for p in c]
    pg.items.append(Frame(M, 160, COL, 580, left))
    pg.items.append(Frame(COL2, 160, COL, 520, right))
    b.T(pg, COL2, 676, COL, 50, ("Small", "The Commissioner's Office also has private staff rooms, and owners can only "
                                          "react in automated rooms like {ch:lineup-alerts}."))
    footer(b, pg, foot, 7)

    # 8 Traditions and help
    pg = b.page()
    bg(pg, LETTER)
    header(b, pg, "06 • THE CLUBHOUSE", "TRADITIONS AND HELP")
    b.T(pg, M, 128, COL, 500,
        ("H2", "TRADITIONS AND SIDE GAMES"),
        ("Body", "**Awards Night.** After the Championship, owners vote 5-3-1 for GM of the Year, Trade of the Year, "
                 "Waiver Steal of the Year, Comeback Franchise and Bust of the Year."),
        ("Body", "**Monthly Awards.** Manager of the Month, Best Record, Biggest Single Week and Hard Luck, in {ch:weekly-recap}."),
        ("Body", "**Bounties.** One-time season goals. The first franchise to reach one takes the Bounty Hunter role."),
        ("Body", "**Pick'em.** Pick each Week's winners in {ch:game-day}. A season leaderboard keeps score."),
        ("Body", "**BLHA Bucks.** A play-money sportsbook on BLHA matchups. The season's top earner is the Sharp."),
        ("Body", "**NHL Playoff Pool.** A free box pool once the fantasy season ends. The winner is the Pool Shark."),
        ("Body", "**The Wooden Spoon (proposed).** Last place holds the Spoon for the offseason and writes the next "
                 "season's preview. Owners decide whether it happens."),
        ("Small", "All of it is for bragging rights: no money, no picks, no FAAB."))
    b.T(pg, COL2, 128, COL, 500,
        ("H2", "GETTING HELP"),
        ("Body", "**A rules question?** Ask in {ch:rules-questions}. Binding answers are posted in {ch:rulings-log}."),
        ("Body", "**Something private?** Open a ticket in {ch:open-a-ticket}."),
        ("Body", "**Disagree with a ruling?** An affected franchise can open an Appeal ticket within 48 hours. Three owners "
                 "from unaffected franchises, drawn at random, decide by majority (19.4)."),
        ("Body", "**An idea for the league?** Post it in {ch:league-suggestions}. Rule changes are voted on in the "
                 "offseason and need 8 of the 12 franchise votes."),
        ("Body", "**The week-to-week basics** live in {ch:owner-handbook}."),
        ("Body", "**Once the League Bot is live,** /myteam, /rule, /deadlines, /minor and /tradecheck answer right in Discord."))
    pg.items += [Box(-9, 640, 630, 161, "Charcoal"), Box(-9, 640, 630, 3, "Gold"), Pic(M, 664, 96, 96, art["seal"])]
    b.T(pg, M + 116, 672, 380, 40, ("Signoff", "SEE YOU AT THE DRAFT"))
    b.T(pg, M + 116, 708, 380, 40, ("SmallLight", "Beer League Hockey Association • Est. 2026. Questions before then? "
                                                  "Open a ticket any time."))
    return b.doc


# ------------------------------------------------------------------ Startup Draft cheat sheet
def draft_sheet(art) -> Doc:
    b = Builder("BLHA-Startup-Draft-Cheat-Sheet", "BLHA Startup Draft Cheat Sheet", LETTER)
    w3 = (CW - 24) / 3
    r3 = b.add_style(row_style("Row3", w3, 9.5, 14))
    r3b = b.add_style(row_style("Row3Total", w3, 9.5, 14, face="SemiBold"))
    for name, size in (("Bullet3", 9.5),):
        b.add_style(PStyle(name, size=size, leading=13.5, left=10, first=-10, after=4.5, bullet=True))
    b.add_style(PStyle("Body3", size=9.5, leading=14, after=5))
    b.add_style(PStyle("Small3", size=8, leading=11, color="Muted", after=3))
    c1, c2, c3 = M, M + w3 + 12, M + 2 * (w3 + 12)

    pg = b.page()
    bg(pg, LETTER)
    pg.items.append(Pic(-9, -9, 630, 630 * 352 / 1664, art["band"]))
    b.T(pg, 70, 32, 400, 14, ("KickerGold", "DRAFT-DAY CHEAT SHEET • SEASON 2027"))
    b.T(pg, 70, 42, 400, 56, ("H1Light", "STARTUP DRAFT"))
    b.T(pg, 70, 88, 400, 16, ("CoverLine", "36 ROUNDS • SLOW SNAKE • 12 FRANCHISES"))
    top = 140
    b.T(pg, c1, top, w3, 440,
        ("H2", "HOW IT WORKS"),
        ("Bullet3", "36 rounds, slow snake, with a 4-hour pick clock."),
        ("Bullet3", "The clock pauses every night from midnight to 8:00 AM ET. You can still pick; the timer just stops."),
        ("Bullet3", "Draft order comes from a random draw, posted in Discord before the draft."),
        ("Bullet3", "Set a queue. After two expired clocks the Commissioner may switch on auto-draft until you're back."),
        ("Bullet3", "Your dues must be paid by the deadline to draft."),
        ("Bullet3", "Finish with a legal roster by the roster-compliance deadline."),
        ("H2", "WHERE"),
        ("Body3", "Picks are made in **Fantrax**."),
        ("Body3", "{ch:draft-room} live talk"),
        ("Body3", "{ch:draft-day-trades} deals"),
        ("Body3", "{ch:draft-announcements} notices"),
        ("Body3", "{ch:draft-results} the board"))
    b.T(pg, c2, top, w3, 440,
        ("H2", "WHAT YOU'RE FILLING"),
        (r3, "C • LW • RW\t3 each"), (r3, "F (any forward)\t3"), (r3, "D\t6"), (r3, "G\t2"), (r3, "Reserve\t6"),
        (r3, "Minors\t10"), (r3b, "Rounds = spots\t36"),
        ("Small3", "Up to 5 IR spots sit on top and don't count."),
        ("H2", "MINORS"),
        ("Bullet3", "25 or younger on NHL opening day, as Fantrax calculates it."),
        ("Bullet3", "Skaters: 100 career NHL games or fewer. Goalies: 50."),
        ("H2", "SNAKE MATH"),
        ("Body3", "**Odd rounds:** pick = (round − 1) × 12 + slot."),
        ("Body3", "**Even rounds:** pick = round × 12 − slot + 1."),
        ("Small3", "Slots 1 and 12 pick back to back at the turns."))
    b.T(pg, c3, top, w3, 440,
        ("H2", "SCORING"),
        (r3, "Goal\t+5.00"), (r3, "Assist\t+2.97"), (r3, "Shot on goal\t+0.53"), (r3, "Block\t+0.44"),
        (r3, "Hit\t+0.14"), (r3, "Penalty minute\t−0.36"),
        (r3, "Goalie start\t+5.00"), (r3, "Save\t+0.56"), (r3, "Goal against\t−5.00"),
        ("H2", "WHAT DRIVES VALUE"),
        ("Bullet3", "A goal is worth about 1.7 assists."),
        ("Bullet3", "Five shots (2.65) nearly match an assist."),
        ("Bullet3", "3 blocks and 3 hits add 1.74 a night."),
        ("Bullet3", "A fighting major costs 1.80."),
        ("Bullet3", "30 saves on 32 shots: +11.80. A 19-save, 6-goal night: −14.36."),
        ("Bullet3", "Only 4 goalie starts count a Week."),
        ("Small3", "No wins, shutouts, plus/minus or power-play bonuses."))
    callout(b, pg, M, 584, COL, 128, "PICKS AND TRADES",
            "Trade freely, no vetoes. To trade away a future 1st or 2nd, your dues must be paid through that pick's "
            "season first, or the trade is reversed. No conditional picks.", style="CalloutBody")
    callout(b, pg, COL2, 584, COL, 128, "THE ANNUAL DRAFT AFTER THIS",
            "From 2028: 5 rounds, linear, an 8-hour clock, minors-eligible players only. Non-playoff teams pick first, "
            "by lowest Potential Points.", style="CalloutBody")
    footer(b, pg, "BLHA • STARTUP DRAFT CHEAT SHEET", 1)

    # Page 2: my draft board
    pg = b.page()
    bg(pg, LETTER)
    b.T(pg, M, 36, CW, 14, ("Kicker", "STARTUP DRAFT • SEASON 2027"))
    b.T(pg, M, 46, 300, 56, ("H1", "MY DRAFT BOARD"))
    fl = b.add_style(PStyle("Field", "Silkscreen", "Bold", 7, 9, "Charcoal", 60))
    b.T(pg, 330, 70, 60, 14, (fl, "FRANCHISE"))
    b.T(pg, 488, 70, 30, 14, (fl, "SLOT"))
    pg.items += [Box(388, 79, 94, 0.75, "Charcoal"), Box(516, 79, 42, 0.75, "Charcoal")]
    b.T(pg, M, 90, CW, 22, ("Track", "**C** {box}  {box}  {box}   **LW** {box}  {box}  {box}   **RW** {box}  {box}  {box}   "
                                    "**F** {box}  {box}  {box}   **D** {box}  {box}  {box}  {box}  {box}  {box}   **G** {box}  {box}"))
    b.T(pg, M, 110, CW, 22, ("Track", "**RES** {box}  {box}  {box}  {box}  {box}  {box}   "
                                     "**MINORS** {box}  {box}  {box}  {box}  {box}  {box}  {box}  {box}  {box}  {box}"))
    cols = [("RD", 28), ("PICK", 38), ("PLAYER", 190), ("POS", 40), ("NHL", 44), ("NOTES", 164)]
    ty, rh = 142, 16.0
    pg.items.append(Box(M, ty, CW, 18, "Charcoal"))
    x = M
    for label, w in cols:
        b.T(pg, x + 5, ty + 2, w - 6, 14, ("TableHead", label))
        x += w
    rows_top = ty + 18
    for i in range(36):
        if i % 2:
            pg.items.append(Box(M, rows_top + i * rh, CW, rh, "CreamDark"))
    x = M
    for label, w in cols[:-1]:
        x += w
        pg.items.append(Box(x, rows_top, 0.5, rh * 36, "Mist"))
    pg.items.append(Box(M, rows_top + rh * 36, CW, 1, "Charcoal"))
    pg.items.append(Frame(M, rows_top - 4.5, 28, rh * 36 + 6, [b.P("TableNum", str(i + 1)) for i in range(36)]))
    footer(b, pg, "BLHA • STARTUP DRAFT CHEAT SHEET", 2)
    return b.doc


# ------------------------------------------------------------------ Awards Night program
def awards_program(art) -> Doc:
    W, H = HALF
    m = 36.0
    cw = W - 2 * m
    b = Builder("BLHA-Awards-Night-Program", "BLHA Awards Night Program", HALF)
    b.add_style(PStyle("H1S", "Jersey 10", "Regular", 34, 32))
    b.add_style(PStyle("BulletS", size=9.5, leading=13.5, left=10, first=-10, after=4, bullet=True))
    b.add_style(PStyle("BodyS", size=9.5, leading=13.5, after=5))
    foot = "BLHA AWARDS NIGHT • SEASON [YEAR]"

    pg = b.page()
    bg(pg, HALF, "Charcoal")
    pg.items.append(Pic(-9, -9, W + 18, H + 18, art["arena"]))
    b.T(pg, m, 170, cw, 14, ("CenterKicker", "BEER LEAGUE HOCKEY ASSOCIATION"))
    b.T(pg, m, 184, cw, 146, ("CenterTitle", "AWARDS"), ("CenterTitle", "NIGHT"))
    b.T(pg, m, 326, cw, 20, ("CenterLabel", "SEASON [YEAR]"))
    pg.items.append(Pic((W - 112) / 2, 360, 112, 112, art["seal"]))
    b.T(pg, m, 490, cw, 44, ("CenterSmall", "[DATE] • [TIME] ET"), ("CenterSmall", "[WHERE]"))

    # 2 Order of the night and the season's honors
    pg = b.page()
    bg(pg, HALF)
    header(b, pg, "THE PROGRAM", "ORDER OF THE NIGHT", x=m, w=cw, y=34, h1="H1S")
    items = [("Welcome", "The Commissioner opens the night."),
             ("The season in review", "The standings, the playoffs and the best trades."),
             ("The season's honors", "From the Presidents' Trophy to the BLHA Champion."),
             ("The owners' awards", "Five awards voted 5-3-1, with GM of the Year last."),
             ("The Dynasty Pot", "The balance, and who's closest to three titles."),
             ("What's next", "The Annual Draft, dues and the day trading reopens.")]
    y = 116
    for i, (t, note) in enumerate(items, 1):
        b.T(pg, m, y - 4, 30, 44, ("Num", str(i)))
        b.T(pg, m + 34, y, cw - 34, 44, ("ItemTitle", t), ("ItemNote", note))
        y += 46
    y += 6
    b.T(pg, m, y, cw, 16, ("H2", "THE SEASON'S HONORS"))
    y += 24
    for label, note in [("BLHA CHAMPION", "$850"), ("RUNNER-UP", "$450"), ("THIRD PLACE", "$200"),
                        ("PRESIDENTS' TROPHY", "$250"), ("CONSOLATION CHAMPION", "+$50 FAAB")]:
        b.T(pg, m, y, 150, 14, ("FieldLabel", label))
        b.T(pg, m + cw - 70, y, 70, 14, ("FieldNote", note))
        pg.items.append(Box(m, y + 21, cw, 0.75, "Charcoal"))
        y += 27
    footer(b, pg, foot, 2, HALF, m)

    # 3 The owners' awards
    pg = b.page()
    bg(pg, HALF)
    header(b, pg, "VOTED BY THE OWNERS", "THE OWNERS' AWARDS", x=m, w=cw, y=34, h1="H1S")
    awards = [("Bust of the Year", "All in good fun: the season's biggest letdown. The one award you can vote your own franchise for."),
              ("Comeback Franchise", "The biggest climb in the standings since last season. From the league's second season on."),
              ("Waiver Steal of the Year", "The season's best pickup off the wire."),
              ("Trade of the Year", "The season's best deal. Neither trade partner could vote for it."),
              ("GM of the Year", "The best job running a franchise. Every active franchise is on the ballot.")]
    y = 118
    for name, note in awards:
        b.T(pg, m, y, cw, 28, ("AwardName", name))
        b.T(pg, m, y + 24, cw, 32, ("ItemNote", note))
        b.T(pg, m, y + 58, 60, 14, ("FieldLabel", "WINNER"))
        b.T(pg, m + cw - 60, y + 58, 60, 14, ("FieldNote", "PTS ____"))
        pg.items.append(Box(m + 52, y + 66, cw - 120, 0.75, "Charcoal"))
        y += 86
    footer(b, pg, foot, 3, HALF, m)

    # 4 How the owners vote, the Dynasty Pot, sign-off
    pg = b.page()
    bg(pg, HALF)
    header(b, pg, "THE BALLOT", "HOW THE OWNERS VOTE", x=m, w=cw, y=34, h1="H1S")
    b.T(pg, m, 118, cw, 200,
        ("BulletS", "One ballot per franchise, cast by the Franchise Owner in {ch:league-voting}."),
        ("BulletS", "A 1st, 2nd and 3rd choice for each award, worth 5, 3 and 1 points."),
        ("BulletS", "No self-votes: your own franchise, your own pickups and trades you were part of aren't on your ballot. "
                    "Bust of the Year is the exception."),
        ("BulletS", "Most points wins. A tie goes to the most first-place votes, and if it's still tied the award is shared."),
        ("BulletS", "Winners go up in {ch:hall-of-champions}. Awards carry no money and change nothing in the standings "
                    "or the draft."))
    b.T(pg, m, 318, cw, 16, ("H2", "THE DYNASTY POT"))
    b.T(pg, m, 338, cw, 36, ("ItemNote", "First franchise to three BLHA Championships in the same cycle takes the whole pot."))
    for i, label in enumerate(["BALANCE", "CLOSEST TO THREE"]):
        yy = 380 + i * 28
        b.T(pg, m, yy, 140, 14, ("FieldLabel", label))
        pg.items.append(Box(m + 120, yy + 8, cw - 120, 0.75, "Charcoal"))
    pg.items += [Box(-9, 452, W + 18, H - 452 + 9, "Charcoal"), Box(-9, 452, W + 18, 3, "Gold"),
                 Pic(m, 478, 56, 64.5, art["bmark"])]
    b.T(pg, m + 72, 478, cw - 72, 40, ("Signoff", "SEE YOU AT THE DRAFT"))
    b.T(pg, m + 72, 512, cw - 72, 40, ("SmallLight", "Trading reopens the day after the Stanley Cup Final."))
    return b.doc


# ------------------------------------------------------------------ fonts for the package
def install_fonts(dest: Path) -> list[Path]:
    """Copies of the three families for a `Document Fonts` folder, with Pixelify Sans' SemiBold and
    Bold given their own style names (the shipped files all call themselves "Regular", so an app
    asking for Regular could get the Bold, and a computer would install only one of the three)."""
    from fontTools.ttLib import TTFont as FT
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for fam in ("pixelifysans", "jersey10", "silkscreen"):
        for f in sorted((pk.FONTS / fam).glob("*.ttf")):
            target = dest / f.name
            if f.name.startswith("PixelifySans-") and "Regular" not in f.name:
                weight = f.stem.split("-")[1]
                t = FT(str(f))
                n = t["name"]
                bold = weight == "Bold"
                fam1 = "Pixelify Sans" if bold else f"Pixelify Sans {weight}"
                sub = "Bold" if bold else "Regular"
                for rec in list(n.names):
                    if rec.nameID in (1, 2, 3, 4, 6, 16, 17):
                        n.removeNames(nameID=rec.nameID)
                for nid, val in ((1, fam1), (2, sub), (3, f"PixelifySans-{weight}"), (4, f"Pixelify Sans {weight}"),
                                 (6, f"PixelifySans-{weight}"), (16, "Pixelify Sans"), (17, weight)):
                    n.setName(val, nid, 3, 1, 0x409)
                    n.setName(val, nid, 1, 0, 0)
                if bold:
                    t["head"].macStyle |= 1
                    t["OS/2"].fsSelection = (t["OS/2"].fsSelection | 0x20) & ~0x40
                else:
                    t["OS/2"].fsSelection = t["OS/2"].fsSelection & ~0x60
                t.save(str(target))
            else:
                shutil.copy2(f, target)
            out.append(target)
        lic = pk.FONTS / fam / "OFL.txt"
        (dest.parent / "Font Licenses").mkdir(exist_ok=True)
        shutil.copy2(lic, dest.parent / "Font Licenses" / f"OFL-{fam}.txt")
    return out


README = """BLHA PRINT PIECES

1. Unzip this folder and keep the "Document Fonts" folder next to the .idml
   files. DesignCraft loads the league fonts (Pixelify Sans, Jersey 10 and
   Silkscreen) from it automatically, so nothing needs installing.
2. In DesignCraft, choose File > Open and pick an .idml file. Text, styles,
   swatches and pictures are all live and editable.
3. The PDFs are print proofs of the same pages.

To use the fonts in other apps too, install the .ttf files in "Document Fonts".

Owner Welcome Packet       US Letter, 8 pages
Startup Draft Cheat Sheet  US Letter, 2 pages (rules on the front, your draft board on the back)
Awards Night Program       Half Letter (5.5 x 8.5 in), 4 pages

Fill in before printing: [DATE] on the Key Dates page of the packet, and
[YEAR], [DATE], [TIME] and [WHERE] in the Awards Night program.
Bleed is 0.125 in on every side.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, help="also write BLHA-Print-Pieces.zip with the fonts into this folder")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    art = make_art()
    docs = [welcome_packet(art), draft_sheet(art), awards_program(art)]
    for d in docs:
        pk.write_pdf(d, OUT / f"{d.name}.pdf")
        pk.write_idml(d, OUT / f"{d.name}.idml")
        stats = pk.check_idml(OUT / f"{d.name}.idml")
        print(f"{d.name}: {stats}")
    if args.package:
        stage = args.package / "BLHA-Print-Pieces"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        for d in docs:
            for ext in ("idml", "pdf"):
                shutil.copy2(OUT / f"{d.name}.{ext}", stage / f"{d.name}.{ext}")
        install_fonts(stage / "Document Fonts")
        (stage / "READ ME FIRST.txt").write_text(README)
        z = args.package / "BLHA-Print-Pieces.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(stage.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(args.package))
        print(f"package: {z}")


if __name__ == "__main__":
    main()
