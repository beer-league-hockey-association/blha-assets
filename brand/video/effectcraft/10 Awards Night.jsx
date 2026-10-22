// 10 Awards Night
// Every graphic for Awards Night, in the program's order: the title, the season's honors, how the
// owners vote, the five owners' awards, the Dynasty Pot and what's next. Tally the 5-3-1 votes,
// fill in DATA, save, and run this file in EffectCraft (File > Scripts > Run Script File).
// Render each composition as an H.264 movie with audio.
//
// Each owners' award lists its top three in any order, with points. The script reveals them
// third, second, first, then the winner with sfx-reveal at 10 seconds. If the top two are still
// tied after first-place votes, set shared: true and both are shown as winners.
// Comeback Franchise starts with the league's second season: set include: false until then.

#include "lib/blha.jsxinc"

var DATA = {
    season: "2027-28",
    honors: [
        { label: "CONSOLATION CHAMPION", prize: "+$50 FAAB NEXT SEASON", team: "TEAM K" },
        { label: "PRESIDENTS' TROPHY", prize: "$250", team: "TEAM A" },
        { label: "THIRD PLACE", prize: "$200", team: "TEAM D" },
        { label: "RUNNER-UP", prize: "$450", team: "TEAM C" },
        { label: "BLHA CHAMPION", prize: "$850 AND A BANNER", team: "TEAM B" }
    ],
    awards: [
        { include: true, name: "BUST OF THE YEAR", about: "THE SEASON'S BIGGEST LETDOWN", shared: false,
          top3: [["NOMINEE ONE", 31], ["NOMINEE TWO", 22], ["NOMINEE THREE", 14]] },
        { include: false, name: "COMEBACK FRANCHISE", about: "THE BIGGEST CLIMB SINCE LAST SEASON", shared: false,
          top3: [["NOMINEE ONE", 31], ["NOMINEE TWO", 22], ["NOMINEE THREE", 14]] },
        { include: true, name: "WAIVER STEAL OF THE YEAR", about: "THE BEST PICKUP OFF THE WIRE", shared: false,
          top3: [["PLAYER (TEAM)", 31], ["PLAYER (TEAM)", 22], ["PLAYER (TEAM)", 14]] },
        { include: true, name: "TRADE OF THE YEAR", about: "THE SEASON'S BEST DEAL", shared: false,
          top3: [["TEAM A AND TEAM B", 31], ["TEAM C AND TEAM D", 22], ["TEAM E AND TEAM F", 14]] },
        { include: true, name: "GM OF THE YEAR", about: "THE BEST JOB RUNNING A FRANCHISE", shared: false,
          top3: [["NOMINEE ONE", 31], ["NOMINEE TWO", 22], ["NOMINEE THREE", 14]] }
    ],
    dynastyPot: { balance: "$400", closest: "TEAM B: 1 CHAMPIONSHIP" },
    next: [
        ["SEASON LEDGER", "WITHIN 30 DAYS"],
        ["TRADING REOPENS", "THE DAY AFTER THE CUP FINAL"],
        ["ANNUAL DRAFT", "[DATES]"],
        ["DUES", "DUE BEFORE THE DRAFT"]
    ]
};

BLHA.run("10 Awards Night", function () {
    var B = BLHA, D = DATA, folder = B.folder("Awards Night");

    // ---- title
    var c = B.comp(folder, "Awards Night - Title", 8);
    B.background(c, "arena");
    var eb = B.text(c, "SEASON " + D.season, { face: "silk", k: 6, color: "gold", x: 960, y: 330, align: "center" });
    var ebp = B.plateFor(c, "Eyebrow plate", eb, 24, 14, "black");
    var a = B.text(c, "AWARDS", { face: "jersey", k: 18, color: "cream", x: 960, y: 420, align: "center", shadow: "black" });
    var n = B.text(c, "NIGHT", { face: "jersey", k: 18, color: "gold", x: 960, y: 640, align: "center", shadow: "black" });
    B.blinkIn(eb.concat(ebp), 0.2);
    B.pop(a, 0.5);
    B.pop(n, 0.9);
    B.sound(c, "sting-intro.wav", 0);

    // ---- the season's honors
    for (var i = 0; i < D.honors.length; i++) {
        var h = D.honors[i], champ = h.label === "BLHA CHAMPION";
        var hc = B.comp(folder, "Honor - " + h.label, 8);
        B.background(hc, champ ? "arena" : "dots");
        B.awardCard(hc, 0, 8, h.label, h.team, h.prize, { y: champ ? 360 : 300, k: champ ? 14 : 12 });
        if (champ) {
            var cup = B.image(hc, "trophy.png", 960, 250, { center: true, scale: 100 });
            B.pop(cup, 0.4);
        }
        B.sound(hc, "sfx-reveal.wav", 0.4);
    }

    // ---- how the owners vote
    var v = B.comp(folder, "Owners' Awards - How the Vote Works", 10);
    B.background(v, "dots");
    var vh = B.header(v, "VOTED BY THE OWNERS", "THE OWNERS' AWARDS", 0, { x: 156, y: 120, k: 10 });
    var rules = ["ONE BALLOT PER FRANCHISE", "1ST, 2ND AND 3RD CHOICES: 5, 3 AND 1 POINTS",
        "NO SELF-VOTES (BUST OF THE YEAR EXCEPTED)", "BRAGGING RIGHTS ONLY: NO MONEY, NO PICKS"];
    for (var r = 0; r < rules.length; r++) {
        var row = B.row(v, 380 + r * 130, rules[r], "", { h: 100, k: 5, leftMaxW: 1560 });
        B.slideIn(row, 0.6 + r * 0.6, -1920, 0, 4);
    }

    // ---- the owners' awards
    for (var w = 0; w < D.awards.length; w++) {
        var aw = D.awards[w];
        if (!aw.include) continue;
        var list = aw.top3.slice(0, 3).sort(function (x, y) { return x[1] - y[1]; });   // third, second, first
        var ac = B.comp(folder, "Award - " + aw.name, 16);
        B.background(ac, "dots");
        var ah = B.header(ac, aw.about, aw.name, 0, { x: 156, y: 100, k: 10, maxW: 1600 });
        for (var j = 0; j < list.length; j++) {
            var y = 340 + (list.length - 1 - j) * 150;           // the first-place nominee sits on top
            var isWin = j === list.length - 1 || (aw.shared && j === list.length - 2);
            var t = 2 + j * 1.5;
            var plate = B.panel(ac, "Nominee " + (j + 1), 120, y, 1680, 120, "charDark", "steel", 4);
            var nm = B.text(ac, list[j][0], { face: "jersey", k: 6, color: "cream", x: 168, y: y + 30, maxW: 1200 });
            B.slideIn(plate.concat(nm), t, 1920, 0, 4);
            B.during(plate.concat(nm), t, 16);
            // the reveal at 10 s: winners go gold, everyone's points appear
            if (isWin) {
                var glow = B.panel(ac, "Winner " + (j + 1), 120, y, 1680, 120, "charcoal", "gold", 8);
                var wn = B.text(ac, list[j][0], { face: "jersey", k: 6, color: "gold", x: 168, y: y + 30, maxW: 1200 });
                B.during(glow.concat(wn), 10, 16);
            }
            var pts = B.text(ac, list[j][1] + " PTS", { face: "jersey", k: 6, color: isWin ? "gold" : "muted", x: 1752, y: y + 30, align: "right" });
            B.blinkIn(pts, 10.2);
        }
        var tag = B.text(ac, aw.shared ? "SHARED" : "WINNER", { face: "jersey", k: 10, color: "gold", x: 960, y: 860, align: "center", shadow: "black" });
        B.pop(tag, 10);
        B.sound(ac, "sfx-reveal.wav", 10);
    }

    // ---- the Dynasty Pot
    var dp = B.comp(folder, "Dynasty Pot", 8);
    B.background(dp, "dots");
    var dh = B.header(dp, "FIRST TO THREE TITLES TAKES IT ALL", "THE DYNASTY POT", 0, { x: 156, y: 120, k: 10 });
    var bal = B.text(dp, D.dynastyPot.balance, { face: "jersey", k: 20, color: "gold", x: 960, y: 400, align: "center", shadow: "black" });
    var cl = B.text(dp, "CLOSEST: " + D.dynastyPot.closest, { face: "silk", k: 6, color: "cream", x: 960, y: 700, align: "center", maxW: 1700 });
    B.pop(bal, 0.6);
    B.blinkIn(cl, 1.4);

    // ---- what's next
    var wx = B.comp(folder, "What's Next", 10);
    B.background(wx, "dots");
    var wh = B.header(wx, "THE OFFSEASON", "WHAT'S NEXT", 0, { x: 156, y: 120, k: 10 });
    for (var q = 0; q < D.next.length && q < 4; q++) {
        var nr = B.row(wx, 360 + q * 130, D.next[q][0], D.next[q][1], { h: 100, k: 5, leftMaxW: 700, rightMaxW: 860 });
        B.slideIn(nr, 0.6 + q * 0.6, 1920, 0, 4);
    }
    var see = B.text(wx, "SEE YOU AT THE DRAFT", { face: "jersey", k: 8, color: "gold", x: 960, y: 920, align: "center", shadow: "black" });
    B.pop(see, 4);
});
