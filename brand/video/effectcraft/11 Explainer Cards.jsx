// 11 Explainer Cards
// Full-screen cards for the explainers, timed to their scripts, plus card overlays for the hype
// videos and the cards the how-to videos cut to. Each SET becomes one composition (or, with
// separate: true, one composition per card).
//
// To build only one set, write its name in build, like build: "How Scoring Works".
// Leave build as "ALL" to build every set. Then run this file in EffectCraft
// (File > Scripts > Run Script File).
//
// Render: sets with alpha: true are see-through between cards, so render them as ProRes 4444
// (with alpha) and lay them over the footage on V2. Everything else renders as H.264.
//
// A card is shown from its "at" time (seconds) until the next card's "at", or until its own
// "until". Card kinds:
//   title  big title with an eyebrow, a sub line and the B
//   card   a header and up to six lines; "big" adds a large number on the right
//   tiles  a header and up to three big numbers with captions
//   big    one huge centered line and a sub line (the hype-video look)
//   end    the BLHA wordmark with a line and a sub line

#include "lib/blha.jsxinc"

var DATA = {
    build: "ALL",
    sets: [
        {
            name: "Constitution in 3 Minutes", length: 180, cards: [
                { at: 0, kind: "title", eyebrow: "THE SHORT VERSION", title: "THE CONSTITUTION IN 3 MINUTES", sub: "THE FULL TEXT IN THE CONSTITUTION CHANNEL ALWAYS WINS" },
                { at: 10, kind: "card", eyebrow: "ARTICLE VI", title: "ROSTER", lines: ["20 ACTIVE: 3 C, 3 LW, 3 RW, 3 F, 6 D, 2 G", "6 RESERVE", "10 MINORS", "UP TO 5 IR"], big: "36", bigLabel: "SPOTS, NOT COUNTING IR" },
                { at: 28, kind: "card", eyebrow: "ARTICLE VII", title: "MINORS", lines: ["25 OR YOUNGER ON NHL OPENING NIGHT", "SKATERS: 100 CAREER NHL GAMES OR FEWER", "GOALIES: 50 OR FEWER", "FLAGGED BY FANTRAX? 3 DAYS TO MOVE HIM"], big: "10", bigLabel: "MINOR-LEAGUE SPOTS" },
                { at: 45, kind: "card", eyebrow: "ARTICLE IX", title: "LINEUPS AND GOALIES", lines: ["DAILY LINEUPS", "PLAYERS LOCK ABOUT A MINUTE BEFORE THEIR GAME", "4 GOALIE STARTS COUNT EACH WEEK", "8 ACROSS THE TWO-WEEK CHAMPIONSHIP"], big: "4", bigLabel: "GOALIE STARTS A WEEK" },
                { at: 60, kind: "card", eyebrow: "ARTICLE X", title: "WAIVERS", lines: ["FAAB ONLY: $1,000 A SEASON", "HIDDEN BIDS, TIES GO TO THE EARLIEST BID", "CLAIMS RUN DAILY ABOUT 11 AM ET", "5 PICKUPS A WEEK"], big: "$1,000", bigLabel: "FAAB A SEASON" },
                { at: 78, kind: "card", eyebrow: "ARTICLE XI", title: "TRADES", lines: ["UNLIMITED, NO VOTES, NO VETOES", "PLAYERS, PICKS AND THIS SEASON'S FAAB", "DEADLINE: 11:59 PM ET, THE SUNDAY ENDING WEEK 20"] },
                { at: 94, kind: "card", eyebrow: "ONE RULE TO REMEMBER", title: "PAY FIRST, THEN TRADE", lines: ["TRADING AWAY A FUTURE 1ST OR 2ND?", "YOUR DUES MUST BE PAID THROUGH THAT PICK'S SEASON", "IF THEY AREN'T, THE TRADE IS REVERSED"] },
                { at: 108, kind: "card", eyebrow: "ARTICLE XVI", title: "PLAYOFFS", lines: ["6 TEAMS, THE TOP 2 GET BYES", "RESEEDED EVERY ROUND", "A TWO-WEEK CHAMPIONSHIP", "CONSOLATION BRACKET: +$50 FAAB"], big: "6", bigLabel: "PLAYOFF TEAMS" },
                { at: 125, kind: "card", eyebrow: "ARTICLE XIV", title: "DRAFT ORDER", lines: ["5 ROUNDS EVERY SUMMER", "NON-PLAYOFF TEAMS PICK FIRST", "ORDERED BY POTENTIAL POINTS", "BENCHING YOUR STARS WON'T MOVE YOU UP"] },
                { at: 140, kind: "card", eyebrow: "ARTICLE III", title: "MONEY", lines: ["$150 DUES A SEASON", "CHAMPION $650, RUNNER-UP $350", "THIRD $150, PRESIDENTS' TROPHY $200", "DYNASTY POT $200 A SEASON"], big: "$1,800", bigLabel: "A SEASON" },
                { at: 160, kind: "card", eyebrow: "ARTICLE XX", title: "CHANGING THE RULES", lines: ["OFFSEASON ONLY", "8 OF THE 12 FRANCHISE VOTES"], big: "8", bigLabel: "VOTES OF 12" },
                { at: 168, kind: "end", title: "THAT'S THE LEAGUE", sub: "READ THE WHOLE THING ONCE. IT'S SHORTER THAN YOU THINK." }
            ]
        },
        {
            name: "How Scoring Works", length: 60, cards: [
                { at: 0, kind: "title", eyebrow: "HEAD-TO-HEAD POINTS", title: "HOW SCORING WORKS", sub: "EVERY VALUE IS IN ARTICLE VIII" },
                { at: 4, kind: "card", eyebrow: "SKATERS", title: "EVERY VALUE", lines: ["GOAL  +5.00", "ASSIST  +2.95", "SHOT ON GOAL  +0.55", "BLOCK  +0.35", "HIT  +0.20", "PENALTY MINUTE  -0.54"] },
                { at: 20, kind: "card", eyebrow: "GOALIES", title: "EVERY VALUE", lines: ["GAME STARTED  +6.50", "SAVE  +0.49", "GOAL AGAINST  -5.00", "GOALIE GOAL  +5.00", "GOALIE ASSIST  +2.95"] },
                { at: 35, kind: "tiles", eyebrow: "WHAT A NIGHT LOOKS LIKE", title: "THREE NIGHTS", tiles: [["+15.90", "2 GOALS, AN ASSIST, 5 SHOTS, A HIT"], ["+11.20", "30 SAVES ON 32 SHOTS"], ["-14.19", "6 GOALS ON 25 SHOTS"]] },
                { at: 50, kind: "card", eyebrow: "NOT SCORED", title: "NO POINTS FOR", lines: ["WINS", "SHUTOUTS", "PLUS-MINUS", "POWER-PLAY BONUSES", "SHOTS, BLOCKS AND HITS ADD UP"] },
                { at: 58, kind: "end", title: "HOW SCORING WORKS", sub: "BEER LEAGUE HOCKEY ASSOCIATION" }
            ]
        },
        {
            name: "Where the Money Goes", length: 45, cards: [
                { at: 0, kind: "title", eyebrow: "$150 X 12 FRANCHISES", title: "WHERE THE MONEY GOES", sub: "$1,800 A SEASON, EVERY DOLLAR ACCOUNTED FOR" },
                { at: 8, kind: "card", eyebrow: "PRIZES", title: "WHO GETS PAID", lines: ["BLHA CHAMPION  $650", "RUNNER-UP  $350", "THIRD PLACE  $150", "PRESIDENTS' TROPHY  $200"], big: "$1,350", bigLabel: "IN PRIZES" },
                { at: 20, kind: "card", eyebrow: "THE LONG GAME", title: "DYNASTY POT", lines: ["$200 GOES IN EVERY SEASON", "FIRST TO 3 TITLES IN A CYCLE TAKES IT ALL"], big: "$200", bigLabel: "A SEASON" },
                { at: 30, kind: "card", eyebrow: "RUNNING THE LEAGUE", title: "RESERVE AND LEAGUE SERVICES", lines: ["$150: FANTRAX PREMIUM AND APPROVED COSTS", "WHAT'S LEFT JOINS THE DYNASTY POT", "$100: THE COMMISSIONER'S ALLOCATION"] },
                { at: 40, kind: "card", eyebrow: "EVERY DOLLAR", title: "THE LEDGER", lines: ["POSTED AFTER EACH SEASON", "IN THE LEAGUE LEDGER CHANNEL"] }
            ]
        },
        {
            name: "Annual Draft Order", length: 60, cards: [
                { at: 0, kind: "title", eyebrow: "EVERY SUMMER", title: "THE ANNUAL DRAFT ORDER", sub: "HOW THE ORDER IS SET" },
                { at: 6, kind: "big", title: "5 ROUNDS \u2022 LINEAR", sub: "YOUR ROUND 1 SPOT IS YOUR SPOT IN EVERY ROUND" },
                { at: 12, kind: "card", eyebrow: "PICKS 1.01 TO 1.06", title: "MISSED THE PLAYOFFS", lines: ["THE SIX NON-PLAYOFF TEAMS", "LOWEST POTENTIAL POINTS PICKS FIRST"] },
                { at: 20, kind: "card", eyebrow: "WHAT IT MEANS", title: "POTENTIAL POINTS", lines: ["YOUR BEST POSSIBLE LINEUP, EVERY WEEK", "FROM YOUR ACTIVE AND RESERVE PLAYERS"] },
                { at: 28, kind: "big", title: "BENCHING DOESN'T HELP", sub: "YOUR BEST LINEUP COUNTS EITHER WAY" },
                { at: 34, kind: "card", eyebrow: "PICKS 1.07 AND 1.08", title: "QUARTERFINAL LOSERS", lines: ["LOWER SEED PICKS FIRST"] },
                { at: 40, kind: "card", eyebrow: "PICKS 1.09 TO 1.12", title: "THE FINAL FOUR", lines: ["1.09  FOURTH PLACE", "1.10  THIRD PLACE", "1.11  RUNNER-UP", "1.12  CHAMPION"] },
                { at: 47, kind: "card", eyebrow: "THE OTHER BRACKET", title: "CONSOLATION", lines: ["DOESN'T CHANGE THE ORDER", "ITS WINNER GETS +$50 FAAB"] },
                { at: 53, kind: "end", title: "DRAFT ORDER", sub: "POSTED IN DRAFT-RESULTS ONCE THE CHAMPIONSHIP IS FINAL" }
            ]
        },
        {
            name: "Dynasty Pot Update", length: 30, cards: [
                { at: 0, kind: "title", eyebrow: "AFTER THE [YEAR] SEASON", title: "THE DYNASTY POT", sub: "FIRST TO THREE TITLES TAKES IT ALL" },
                { at: 4, kind: "card", eyebrow: "THE BALANCE", title: "IN THE POT", lines: ["$200 GOES IN EVERY SEASON", "PLUS WHAT THE RESERVE DIDN'T SPEND"], big: "$[BALANCE]", bigLabel: "AND GROWING" },
                { at: 12, kind: "card", eyebrow: "THIS CYCLE", title: "CHAMPIONSHIPS", lines: ["[TEAM]: [NUMBER]", "[TEAM]: [NUMBER]"] },
                { at: 20, kind: "big", title: "FIRST TO 3 TAKES IT ALL", sub: "THEY DON'T HAVE TO BE IN A ROW" },
                { at: 27, kind: "end", title: "WHO'S NEXT?", sub: "BEER LEAGUE HOCKEY ASSOCIATION" }
            ]
        },
        {
            name: "Rule Change Vote", length: 56, cards: [
                { at: 0, kind: "title", eyebrow: "CLOSED [DATE]", title: "RULE CHANGE VOTE", sub: "[PROPOSAL]" },
                { at: 5, kind: "big", title: "[YES]-[NO]", sub: "8 NEEDED \u2022 [PASSED / DID NOT PASS]" },
                { at: 12, kind: "card", eyebrow: "WHAT CHANGES", title: "BEFORE AND AFTER", lines: ["BEFORE: [OLD RULE]", "FROM [SEASON]: [NEW RULE]"] },
                { at: 30, kind: "card", eyebrow: "FROM THE PROPOSAL", title: "WHY", lines: ["[ONE SHORT LINE]", "[ANOTHER SHORT LINE]"] },
                { at: 42, kind: "big", title: "STARTS [SEASON]", sub: "NOTHING THAT ALREADY HAPPENED CHANGES" },
                { at: 50, kind: "end", title: "THE UPDATED CONSTITUTION", sub: "POSTED IN THE CONSTITUTION CHANNEL" }
            ]
        },
        {
            name: "Startup Draft Hype Cards", length: 45, alpha: true, cards: [
                { at: 8, until: 14, kind: "big", title: "12 FRANCHISES \u2022 36 ROUNDS", sub: "432 PICKS" },
                { at: 14, until: 21, kind: "big", title: "SNAKE \u2022 4-HOUR CLOCK", sub: "THE CLOCK SLEEPS FROM MIDNIGHT TO 8 AM ET" },
                { at: 27, until: 33, kind: "big", title: "QUEUE IT", sub: "TWO MISSED CLOCKS AND AUTO-DRAFT CAN TAKE OVER" },
                { at: 39, until: 45, kind: "end", title: "STARTUP DRAFT", sub: "[DATE] \u2022 [TIME] ET" }
            ]
        },
        {
            name: "Opening Night Cards", length: 45, alpha: true, cards: [
                { at: 8, until: 12, kind: "big", title: "WEEK 1", sub: "THE [YEAR] BLHA SEASON" },
                { at: 12, until: 19, kind: "big", title: "22 WEEKS", sub: "EVERY TEAM TWICE \u2022 THE TOP 6 MAKE THE PLAYOFFS" },
                { at: 19, until: 25, kind: "big", title: "SET YOUR LINEUP", sub: "PLAYERS LOCK ABOUT A MINUTE BEFORE THEIR GAME" },
                { at: 25, until: 31, kind: "big", title: "4 GOALIE STARTS \u2022 5 ADDS", sub: "EVERY WEEK" },
                { at: 37, until: 45, kind: "end", title: "PUCK DROP", sub: "[TIME] ET" }
            ]
        },
        {
            name: "Trade Deadline Cards", length: 45, alpha: true, cards: [
                { at: 0, until: 4, kind: "big", title: "TRADE DEADLINE", sub: "11:59 PM ET \u2022 THE SUNDAY ENDING WEEK 20" },
                { at: 4, until: 10, kind: "big", title: "[N] TRADES", sub: "THIS SEASON" },
                { at: 28, until: 34, kind: "big", title: "BUYERS \u2022 SELLERS", sub: "WHO WENT ALL IN AND WHO'S BUILDING" },
                { at: 34, until: 41, kind: "big", title: "TRADES REOPEN", sub: "THE DAY AFTER THE STANLEY CUP FINAL" },
                { at: 41, until: 45, kind: "end", title: "TWO WEEKS LEFT", sub: "IN THE REGULAR SEASON" }
            ]
        },
        {
            name: "Championship Hype Cards", length: 45, alpha: true, cards: [
                { at: 9, until: 14, kind: "big", title: "[SEED] VS [SEED]", sub: "[RECORD] \u2022 [RECORD]" },
                { at: 22, until: 29, kind: "big", title: "2 WEEKS \u2022 TOTAL POINTS", sub: "8 GOALIE STARTS AND 10 PICKUPS ACROSS BOTH WEEKS" },
                { at: 29, until: 37, kind: "big", title: "$650 \u2022 A BANNER", sub: "AND ONE STEP TOWARD THE DYNASTY POT" },
                { at: 42, until: 45, kind: "end", title: "THE BLHA CHAMPIONSHIP", sub: "STARTS TONIGHT" }
            ]
        },
        {
            name: "How-to Cards", separate: true, seconds: 6, cards: [
                { kind: "title", eyebrow: "HOW-TO", title: "MOVING A PLAYER TO MINORS", sub: "36 PLAYERS, A 26-PLAYER LIMIT" },
                { kind: "card", eyebrow: "MINORS", title: "WHO QUALIFIES", lines: ["25 OR YOUNGER ON NHL OPENING NIGHT", "100 CAREER NHL GAMES OR FEWER", "GOALIES: 50 OR FEWER"] },
                { kind: "card", eyebrow: "MINORS", title: "IF HE STOPS QUALIFYING", lines: ["3 DAYS TO PROMOTE, TRADE OR DROP HIM", "FIX AN ILLEGAL ROSTER WITHIN 24 HOURS"] },
                { kind: "title", eyebrow: "HOW-TO", title: "SETTING YOUR LINEUP", sub: "DAILY LINEUPS: ONLY ACTIVE PLAYERS SCORE" },
                { kind: "big", title: "3 C \u2022 3 LW \u2022 3 RW \u2022 3 F \u2022 6 D \u2022 2 G", sub: "THE F SLOTS TAKE ANY FORWARD" },
                { kind: "card", eyebrow: "LINEUPS", title: "LOCKS", lines: ["EACH PLAYER LOCKS ABOUT A MINUTE BEFORE HIS GAME", "PLAYERS WHO HAVEN'T STARTED CAN STILL MOVE"] },
                { kind: "card", eyebrow: "LINEUPS", title: "GOALIES", lines: ["4 GOALIE STARTS COUNT EACH WEEK", "PLAN YOUR STARTS"], big: "4", bigLabel: "A WEEK" },
                { kind: "title", eyebrow: "HOW-TO", title: "PAYING YOUR DUES", sub: "$150 A SEASON THROUGH FANTRAX TREASURER" },
                { kind: "card", eyebrow: "DUES", title: "WHEN IT COUNTS", lines: ["ONCE THE COMMISSIONER CONFIRMS IT", "AND RECORDS IT IN THE LEAGUE LEDGER"] },
                { kind: "card", eyebrow: "ONE RULE TO REMEMBER", title: "PAY FIRST, THEN TRADE", lines: ["TRADING A FUTURE 1ST OR 2ND?", "THOSE SEASONS HAVE TO BE PAID FIRST", "OPEN A TICKET TO SET IT UP"] },
                { kind: "title", eyebrow: "HOW-TO", title: "YOUR DRAFT QUEUE", sub: "36 ROUNDS, A 4-HOUR CLOCK" },
                { kind: "card", eyebrow: "THE DRAFT", title: "THE NIGHTLY PAUSE", lines: ["MIDNIGHT TO 8 AM ET", "YOU CAN STILL PICK. THE TIMER JUST STOPS."] },
                { kind: "card", eyebrow: "THE DRAFT", title: "TIMEOUTS", lines: ["TWO MISSED CLOCKS AND AUTO-DRAFT CAN TAKE OVER", "KEEP YOUR QUEUE CURRENT"] },
                { kind: "title", eyebrow: "HOW-TO", title: "FAAB BIDS", sub: "NO FIRST-COME, FIRST-SERVED" },
                { kind: "card", eyebrow: "FAAB", title: "$1,000 A SEASON", lines: ["IT DOESN'T ROLL OVER"], big: "$1,000", bigLabel: "A SEASON" },
                { kind: "card", eyebrow: "FAAB", title: "HOW BIDS WORK", lines: ["HIDDEN BIDS IN $1 STEPS", "$0 BIDS ARE ALLOWED", "A TIE GOES TO THE BID PLACED FIRST"] },
                { kind: "card", eyebrow: "FAAB", title: "WHEN CLAIMS RUN", lines: ["EVERY DAY ABOUT 11 AM ET", "5 PICKUPS A WEEK"] },
                { kind: "title", eyebrow: "HOW-TO", title: "MAKING A TRADE", sub: "UNLIMITED, NO VOTES, NO VETOES" },
                { kind: "card", eyebrow: "TRADES", title: "WHAT YOU CAN TRADE", lines: ["PLAYERS", "PICKS IN THE NEXT THREE ANNUAL DRAFTS", "THIS SEASON'S FAAB", "NO CONDITIONAL PICKS, NO SIDE DEALS"] },
                { kind: "card", eyebrow: "TRADES", title: "DEADLINE", lines: ["11:59 PM ET, THE SUNDAY ENDING WEEK 20", "REOPENS THE DAY AFTER THE STANLEY CUP FINAL"] },
                { kind: "title", eyebrow: "HOW-TO", title: "INJURED RESERVE", sub: "UP TO 5 IR SPOTS" },
                { kind: "card", eyebrow: "IR", title: "COMING BACK", lines: ["WHEN HE'S ACTIVATED, MAKE ROOM", "FIX AN ILLEGAL ROSTER WITHIN 24 HOURS"] },
                { kind: "title", eyebrow: "HOW-TO", title: "STAY IN THE LOOP", sub: "FANTRAX NOTIFICATIONS" },
                { kind: "title", eyebrow: "HOW-TO", title: "PRIVATE HELP", sub: "OPEN A TICKET" },
                { kind: "card", eyebrow: "TICKETS", title: "APPEALS", lines: ["OPEN AN APPEAL TICKET WITHIN 48 HOURS", "3 UNAFFECTED OWNERS, DRAWN AT RANDOM", "THEY DECIDE BY MAJORITY"] },
                { kind: "title", eyebrow: "MEET THE", title: "THE LEAGUE BOT", sub: "IT READS FANTRAX AND NEVER CHANGES ANYTHING" },
                { kind: "title", eyebrow: "OFFICIAL DRAW", title: "STARTUP DRAFT ORDER DRAW", sub: "[DATE] \u2022 [TIME] ET" }
            ]
        }
    ]
};

BLHA.run("11 Explainer Cards", function () {
    var B = BLHA, folder = B.folder("Explainer Cards"), found = false;

    function card(c, cd, t0, t1, ownBg) {
        var all = [];
        if (ownBg) all = all.concat(B.background(c, "charcoal"));
        var k = cd.kind || "card";
        if (k === "title") {
            var mark = B.image(c, "b-mark-12.png", 1464, 300);
            var title = String(cd.title || "");
            if (title.length > 16) title = B.twoLines(title);
            var h = B.header(c, cd.eyebrow || "", title, t0 + B.f(4), { x: 156, y: title.indexOf("\n") > 0 ? 270 : 330, k: 12, maxW: 1200 });
            var sub = B.text(c, cd.sub || "", { face: "silk", k: 5, color: "muted", x: 156, y: h.bottom + 50, maxW: 1200 });
            B.pop(mark, t0 + B.f(2));
            B.blinkIn(sub, t0 + B.f(20));
            all = all.concat(mark, h.bar, h.eyebrow, h.title, sub);
        } else if (k === "card") {
            var hc = B.header(c, cd.eyebrow || "", cd.title || "", t0, { x: 156, y: 120, k: 10, maxW: cd.big ? 1100 : 1600 });
            all = all.concat(hc.bar, hc.eyebrow, hc.title);
            var lines = cd.lines || [], step = lines.length > 4 ? 96 : 120;
            for (var i = 0; i < lines.length && i < 6; i++) {
                var y = 400 + i * step;
                var dot = B.box(c, "Bullet", 156, y + 14, 20, 20, "gold");
                var ln = B.text(c, lines[i], { face: "jersey", k: 5, color: "cream", x: 204, y: y, maxW: 1560 });
                B.slideIn(dot.concat(ln), t0 + 0.6 + i * 0.5, -300, 0, 3);
                all = all.concat(dot, ln);
            }
            if (cd.big) {
                var big = B.text(c, cd.big, { face: "jersey", k: 16, color: "gold", x: 1764, y: 96, align: "right", maxW: 560, shadow: "black" });
                var bl = B.text(c, cd.bigLabel || "", { face: "silk", k: 4, color: "muted", x: 1764, y: 280, align: "right", maxW: 560 });
                B.pop(big, t0 + B.f(10));
                B.blinkIn(bl, t0 + B.f(18));
                all = all.concat(big, bl);
            }
        } else if (k === "tiles") {
            var ht = B.header(c, cd.eyebrow || "", cd.title || "", t0, { x: 156, y: 120, k: 10 });
            all = all.concat(ht.bar, ht.eyebrow, ht.title);
            var tiles = cd.tiles || [];
            for (var j = 0; j < tiles.length && j < 3; j++) {
                var x = 120 + j * 570, neg = tiles[j][0].charAt(0) === "-";
                var p = B.panel(c, "Tile " + (j + 1), x, 380, 540, 440, "charDark", neg ? "red" : "gold", 6);
                var v = B.text(c, tiles[j][0], { face: "jersey", k: 12, color: neg ? "red" : "gold", x: x + 270, y: 470, align: "center", maxW: 480, shadow: "black" });
                var cap = B.text(c, tiles[j][1], { face: "silk", k: 4, color: "cream", x: x + 270, y: 700, align: "center", maxW: 490 });
                B.slideIn(p.concat(v, cap), t0 + 0.5 + j * 1.5, 0, 600, 4);
                all = all.concat(p, v, cap);
            }
        } else if (k === "big") {
            var bt = B.text(c, cd.title || "", { face: "jersey", k: 14, color: "cream", x: 960, y: 400, align: "center", maxW: 1700, shadow: "black" });
            var bs = B.text(c, cd.sub || "", { face: "silk", k: 6, color: "gold", x: 960, y: 620, align: "center", maxW: 1700 });
            var rule = B.box(c, "Rule", 660, 580, 600, 6, "gold");
            B.pop(bt, t0 + B.f(2));
            B.slideIn(rule, t0 + B.f(8), -1300, 0, 3);
            B.blinkIn(bs, t0 + B.f(14));
            all = all.concat(bt, rule, bs);
        } else if (k === "end") {
            var wm = B.image(c, "wordmark.png", 960, 330, { center: true });
            var et = B.text(c, cd.title || "", { face: "jersey", k: 8, color: "cream", x: 960, y: 650, align: "center", maxW: 1700, shadow: "black" });
            var es = B.text(c, cd.sub || "", { face: "silk", k: 5, color: "gold", x: 960, y: 780, align: "center", maxW: 1700 });
            B.pop(wm, t0 + B.f(2));
            B.slideIn(et, t0 + B.f(12), 0, 60, 4);
            B.blinkIn(es, t0 + B.f(24));
            all = all.concat(wm, et, es);
        } else {
            throw new Error("Unknown card kind \"" + k + "\"");
        }
        B.during(all, t0, t1);
        return all;
    }

    for (var s = 0; s < DATA.sets.length; s++) {
        var set = DATA.sets[s];
        if (DATA.build !== "ALL" && DATA.build !== set.name) continue;
        found = true;
        var cards = set.cards;
        if (set.separate) {
            for (var n = 0; n < cards.length; n++) {
                var sc = B.comp(B.folder("Explainer Cards"), "Card - " + cards[n].title, set.seconds || 6);
                card(sc, cards[n], 0, sc.duration, true);
                B.signoff(sc);
            }
            continue;
        }
        var c = B.comp(folder, set.name + (set.alpha ? " (alpha)" : ""), set.length);
        if (!set.alpha) B.background(c, "charcoal");
        for (var i = 0; i < cards.length; i++) {
            var t0 = cards[i].at, t1 = cards[i].until || (i + 1 < cards.length ? cards[i + 1].at : set.length);
            card(c, cards[i], t0, t1, set.alpha);
        }
        if (!set.alpha) B.signoff(c);
    }
    if (!found) throw new Error("No set is named \"" + DATA.build + "\". Check the spelling in build.");
});
