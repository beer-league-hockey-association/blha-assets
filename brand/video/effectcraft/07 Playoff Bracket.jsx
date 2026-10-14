// 07 Playoff Bracket
// Builds three things from the final standings:
//   "Bracket Reveal"  60 seconds, timed to the "Bracket reveal" script
//   "Bracket"         8 seconds, the bracket as it stands (fill in results as rounds finish)
//   "Matchup - ..."   8 seconds per matchup in the preview round, for the round previews
// Fill in DATA, save, and run this file in EffectCraft (File > Scripts > Run Script File).
// Render each as an H.264 movie.

#include "lib/blha.jsxinc"

var DATA = {
    year: "2028",
    // Final regular-season standings, seeds 1 to 6: [team, record]
    seeds: [
        ["TEAM A", "15-6-1"],
        ["TEAM B", "14-7-1"],
        ["TEAM C", "13-9-0"],
        ["TEAM D", "12-9-1"],
        ["TEAM E", "12-10-0"],
        ["TEAM F", "11-11-0"]
    ],
    // Results as they come in: the winning team's name, or "" if not played yet.
    results: {
        quarterfinal3v6: "",
        quarterfinal4v5: "",
        semifinal1: "",        // the semifinal with seed 1
        semifinal2: "",        // the semifinal with seed 2
        championship: ""
    },
    // Round previews: which matchups to make cards for, and a line about each.
    preview: {
        round: "QUARTERFINALS",
        matchups: [
            { a: 3, b: 6, note: "SEASON SERIES SPLIT 1-1" },
            { a: 4, b: 5, note: "TEAM D WON BOTH MEETINGS" }
        ]
    }
};

BLHA.run("07 Playoff Bracket", function () {
    var B = BLHA, D = DATA, R = D.results;
    var folder = B.folder("Playoffs");
    function team(seed) { return D.seeds[seed - 1][0]; }
    function seedOf(name) { for (var i = 0; i < 6; i++) if (D.seeds[i][0] === name) return i + 1; return 0; }

    // Reseeding: seed 1 meets the lowest seed left, seed 2 the other quarterfinal winner.
    function semis() {
        var w1 = seedOf(R.quarterfinal3v6), w2 = seedOf(R.quarterfinal4v5);
        if (!w1 || !w2) return null;
        var low = Math.max(w1, w2), high = Math.min(w1, w2);
        return [[1, low], [2, high]];
    }

    // One bracket slot: seed box, team, record.
    function slot(c, x, y, seed, name, record, state) {
        var edge = state === "won" ? "gold" : state === "lost" ? "charLight" : state === "empty" ? "charLight" : "steel";
        var p = B.panel(c, "Slot " + name, x, y, 500, 84, state === "lost" ? "stands" : "charDark", edge, 4);
        if (state === "empty") return p.concat(B.text(c, name, { face: "silk", k: 4, color: "muted", x: x + 250, y: y + 32, align: "center" }));
        var box = B.box(c, "Seed box " + seed, x + 4, y + 4, 76, 76, state === "lost" ? "steel" : "gold");
        var num = B.text(c, String(seed), { face: "jersey", k: 5, color: "black", x: x + 42, y: y + 17, align: "center" });
        var t = B.text(c, name, { face: "jersey", k: 4, color: state === "lost" ? "muted" : state === "won" ? "gold" : "cream", x: x + 104, y: y + 12, maxW: 370 });
        var r = B.text(c, record || "", { face: "silk", k: 3, color: "muted", x: x + 104, y: y + 60 });
        return p.concat(box, num, t, r);
    }
    function heads(c) {
        var out = [];
        var cols = [["QUARTERFINALS", 120], ["SEMIFINALS", 720], ["CHAMPIONSHIP", 1320]];
        for (var i = 0; i < 3; i++) out = out.concat(B.text(c, cols[i][0], { face: "silk", k: 5, color: "gold", x: cols[i][1], y: 210 }));
        out = out.concat(B.text(c, "1 WEEK", { face: "silk", k: 3, color: "muted", x: 120, y: 250 }),
            B.text(c, "1 WEEK \u2022 RESEEDED", { face: "silk", k: 3, color: "muted", x: 720, y: 250 }),
            B.text(c, "2 WEEKS \u2022 TOTAL POINTS", { face: "silk", k: 3, color: "muted", x: 1320, y: 250 }));
        return out;
    }
    function band(c, t0, t1, big, small) {
        var p = B.box(c, "Band " + big, 0, 380, B.W, 320, "charcoal");
        var e1 = B.box(c, "Band top " + big, 0, 374, B.W, 6, "gold");
        var e2 = B.box(c, "Band bottom " + big, 0, 700, B.W, 6, "gold");
        var a = B.text(c, big, { face: "jersey", k: 10, color: "cream", x: 960, y: 450, align: "center", maxW: 1700, shadow: "black" });
        var b = B.text(c, small, { face: "silk", k: 5, color: "gold", x: 960, y: 610, align: "center", maxW: 1700 });
        B.slideIn(p.concat(e1, e2), t0, -B.W, 0, 4);
        B.pop(a, t0 + B.f(8));
        B.blinkIn(b, t0 + B.f(16));
        B.during(p.concat(e1, e2, a, b), t0, t1);
    }

    // ---------------- Bracket Reveal (60 s)
    var c = B.comp(folder, "Bracket Reveal - " + D.year, 60);
    B.background(c, "dots");
    var mark = B.image(c, "b-mark-8.png", 960, 300, { center: true });
    var eb = B.text(c, D.year + " POSTSEASON", { face: "silk", k: 6, color: "gold", x: 960, y: 470, align: "center" });
    var tt = B.text(c, "THE BLHA PLAYOFFS", { face: "jersey", k: 14, color: "cream", x: 960, y: 540, align: "center", maxW: 1700, shadow: "black" });
    B.pop(mark, B.f(3));
    B.blinkIn(eb, B.f(9));
    B.pop(tt, B.f(15));
    B.during(mark.concat(eb, tt), 0, 7);

    B.during(heads(c), 7, 60);
    var skeleton = [[120, 330, "3 SEED"], [120, 426, "6 SEED"], [120, 650, "4 SEED"], [120, 746, "5 SEED"],
        [720, 378, "1 SEED"], [720, 474, "LOWEST SEED LEFT"], [720, 698, "2 SEED"], [720, 794, "OTHER WINNER"],
        [1320, 538, "SEMIFINAL WINNER"], [1320, 634, "SEMIFINAL WINNER"]];
    for (var i = 0; i < skeleton.length; i++) B.during(slot(c, skeleton[i][0], skeleton[i][1], 0, skeleton[i][2], "", "empty"), 7, 60);
    var reveal = [[1, 720, 378, 7.3], [2, 720, 698, 14.0], [3, 120, 330, 20.0], [6, 120, 426, 20.6], [4, 120, 650, 27.0], [5, 120, 746, 27.6]];
    for (var r = 0; r < reveal.length; r++) {
        var v = reveal[r], s = slot(c, v[1], v[2], v[0], team(v[0]), D.seeds[v[0] - 1][1], "seed");
        B.slideIn(s, v[3], -600, 0, 4);
        B.during(s, v[3], 60);
        if (v[0] <= 2) {
            var bye = B.text(c, "BYE", { face: "jersey", k: 4, color: "gold", x: 1210, y: v[2] + 22, align: "right" });
            B.blinkIn(bye, v[3] + 0.6);
            B.during(bye, v[3] + 0.6, 60);
        }
    }
    band(c, 34, 41, "RESEEDED EVERY ROUND", "THE TOP SEED LEFT ALWAYS PLAYS THE LOWEST SEED LEFT");
    band(c, 41, 49, "QF 1 WEEK \u2022 SF 1 WEEK \u2022 FINAL 2 WEEKS", "THE CHAMPIONSHIP IS TWO WEEKS, TOTAL POINTS");
    band(c, 49, 55, "CONSOLATION BRACKET", "THE OTHER SIX PLAY FOR +$50 FAAB NEXT SEASON");
    band(c, 55, 60, "THE QUARTERFINALS START TONIGHT", "SET YOUR LINEUPS");

    // ---------------- Bracket (as it stands)
    var b = B.comp(folder, "Bracket - " + D.year, 8);
    B.background(b, "dots");
    var stage = !R.quarterfinal3v6 || !R.quarterfinal4v5 ? "QUARTERFINALS" : !R.semifinal1 || !R.semifinal2 ? "SEMIFINALS" :
        !R.championship ? "CHAMPIONSHIP" : "FINAL";
    var h = B.header(b, "THE BLHA PLAYOFFS \u2022 " + D.year, stage === "FINAL" ? "CHAMPION: " + R.championship : "NOW: THE " + stage, 0, { x: 156, y: 60, k: 6 });
    var items = heads(b);
    function st(name, winner) { return !winner ? "seed" : winner === name ? "won" : "lost"; }
    items = items.concat(slot(b, 120, 330, 3, team(3), D.seeds[2][1], st(team(3), R.quarterfinal3v6)),
        slot(b, 120, 426, 6, team(6), D.seeds[5][1], st(team(6), R.quarterfinal3v6)),
        slot(b, 120, 650, 4, team(4), D.seeds[3][1], st(team(4), R.quarterfinal4v5)),
        slot(b, 120, 746, 5, team(5), D.seeds[4][1], st(team(5), R.quarterfinal4v5)));
    var sf = semis();
    if (sf) {
        items = items.concat(slot(b, 720, 378, 1, team(1), D.seeds[0][1], st(team(1), R.semifinal1)),
            slot(b, 720, 474, sf[0][1], team(sf[0][1]), D.seeds[sf[0][1] - 1][1], st(team(sf[0][1]), R.semifinal1)),
            slot(b, 720, 698, 2, team(2), D.seeds[1][1], st(team(2), R.semifinal2)),
            slot(b, 720, 794, sf[1][1], team(sf[1][1]), D.seeds[sf[1][1] - 1][1], st(team(sf[1][1]), R.semifinal2)));
    } else {
        items = items.concat(slot(b, 720, 378, 1, team(1), D.seeds[0][1], "seed"), slot(b, 720, 474, 0, "LOWEST SEED LEFT", "", "empty"),
            slot(b, 720, 698, 2, team(2), D.seeds[1][1], "seed"), slot(b, 720, 794, 0, "OTHER WINNER", "", "empty"));
    }
    if (R.semifinal1 && R.semifinal2) {
        var f1 = seedOf(R.semifinal1), f2 = seedOf(R.semifinal2);
        items = items.concat(slot(b, 1320, 538, f1, R.semifinal1, D.seeds[f1 - 1][1], st(R.semifinal1, R.championship)),
            slot(b, 1320, 634, f2, R.semifinal2, D.seeds[f2 - 1][1], st(R.semifinal2, R.championship)));
    } else {
        items = items.concat(slot(b, 1320, 538, 0, "SEMIFINAL WINNER", "", "empty"), slot(b, 1320, 634, 0, "SEMIFINAL WINNER", "", "empty"));
    }
    if (R.championship) {
        var champ = B.text(b, "CHAMPION", { face: "silk", k: 5, color: "gold", x: 1570, y: 780, align: "center" });
        var cup = B.image(b, "trophy.png", 1570, 900, { center: true });
        B.pop(cup, 0.8);
        B.blinkIn(champ, 1.0);
    }
    B.blinkIn(items, 0.3, 2, 2);

    // ---------------- Matchup cards
    var P = D.preview;
    for (var m = 0; m < P.matchups.length; m++) {
        var mu = P.matchups[m], A = D.seeds[mu.a - 1], Bt = D.seeds[mu.b - 1];
        var mc = B.comp(folder, "Matchup - " + A[0] + " vs " + Bt[0], 8);
        B.background(mc, "dots");
        var mh = B.text(mc, P.round, { face: "silk", k: 6, color: "gold", x: 960, y: 140, align: "center" });
        var left = B.panel(mc, "Left", 120, 300, 760, 420, "charDark", "gold", 6);
        var right = B.panel(mc, "Right", 1040, 300, 760, 420, "charDark", "gold", 6);
        var ls = B.text(mc, mu.a + " SEED", { face: "silk", k: 5, color: "gold", x: 500, y: 350, align: "center" });
        var ln = B.text(mc, A[0], { face: "jersey", k: 9, color: "cream", x: 500, y: 430, align: "center", maxW: 680, shadow: "black" });
        var lr = B.text(mc, A[1], { face: "jersey", k: 5, color: "muted", x: 500, y: 600, align: "center" });
        var rs = B.text(mc, mu.b + " SEED", { face: "silk", k: 5, color: "gold", x: 1420, y: 350, align: "center" });
        var rn = B.text(mc, Bt[0], { face: "jersey", k: 9, color: "cream", x: 1420, y: 430, align: "center", maxW: 680, shadow: "black" });
        var rr = B.text(mc, Bt[1], { face: "jersey", k: 5, color: "muted", x: 1420, y: 600, align: "center" });
        var vs = B.text(mc, "VS", { face: "jersey", k: 8, color: "gold", x: 960, y: 470, align: "center", shadow: "black" });
        var note = B.text(mc, mu.note || "", { face: "silk", k: 5, color: "cream", x: 960, y: 820, align: "center", maxW: 1600 });
        B.slideIn(left.concat(ls, ln, lr), 0.1, -1000, 0, 4);
        B.slideIn(right.concat(rs, rn, rr), 0.1, 1000, 0, 4);
        B.pop(vs, 0.5);
        B.blinkIn(mh, 0.2);
        B.blinkIn(note, 1.2);
        B.signoff(mc);
    }
});
