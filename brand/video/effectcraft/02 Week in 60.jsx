// 02 Week in 60
// The weekly 60-second recap, timed to the "Week in 60 Seconds" script. Every Monday, copy the
// numbers from the League Bot's posts in 📰│weekly-recap into DATA, save, and run this file in
// EffectCraft (File > Scripts > Run Script File). Render the result as an H.264 movie.
// Points are plain numbers (no quotes). Team names keep their quotes.

#include "lib/blha.jsxinc"

var DATA = {
    week: 5,
    dates: "OCT 26 - NOV 1",

    // All six results: [team, points, team, points]. The higher score is drawn as the winner.
    scores: [
        ["TEAM A", 123.45, "TEAM B", 98.10],
        ["TEAM C", 140.25, "TEAM D", 131.10],
        ["TEAM E", 128.40, "TEAM F", 112.75],
        ["TEAM G", 101.20, "TEAM H", 99.85],
        ["TEAM I", 117.60, "TEAM J", 121.05],
        ["TEAM K", 88.20, "TEAM L", 86.90]
    ],

    upset: { winner: "TEAM G", winnerPoints: 101.20, loser: "TEAM H", loserPoints: 99.85 },

    // The League Bot's Weekly Awards
    firstStar: ["TEAM C", 140.25],
    secondStar: ["TEAM D", 131.10],
    thirdStar: ["TEAM E", 128.40],
    toughLuck: { team: "TEAM D", points: 131.10, lostTo: "TEAM C" },
    luckyWin: { team: "TEAM K", points: 88.20, beat: "TEAM L" },

    // Standings movers: [team, new place, places moved (plus is up, minus is down)]
    movers: [
        ["TEAM C", "1ST", 2],
        ["TEAM G", "5TH", 3],
        ["TEAM H", "8TH", -3]
    ],
    leader: { team: "TEAM C", record: "4-1-0" },

    nextWeek: { label: "GAME OF THE WEEK", teamA: "TEAM C", teamB: "TEAM D" }
};

BLHA.run("02 Week in 60", function () {
    var B = BLHA, D = DATA;
    var wk = (D.week < 10 ? "0" : "") + D.week;
    var c = B.comp(B.folder("Week in 60"), "Week in 60 - Week " + wk, 60);
    B.background(c, "dots");

    function section(t0, t1, eyebrow, title) {
        var h = B.header(c, eyebrow, title, t0, { x: 156, y: 96, k: 8 });
        B.during(h.bar.concat(h.eyebrow, h.title), t0, t1);
        return h;
    }

    // ---- 0:00 open (the WEEK slam lands with the intro sting's hit at 0.5 s)
    var mark = B.image(c, "b-mark-8.png", 960, 300, { center: true });
    var eb = B.text(c, "BLHA WEEK IN 60", { face: "silk", k: 6, color: "gold", x: 960, y: 470, align: "center" });
    var big = B.text(c, "WEEK " + D.week, { face: "jersey", k: 18, color: "cream", x: 960, y: 540, align: "center", shadow: "black" });
    var dates = B.text(c, D.dates, { face: "silk", k: 6, color: "cream", x: 960, y: 760, align: "center" });
    B.pop(mark, B.f(3));
    B.blinkIn(eb, B.f(9));
    B.pop(big, B.f(15));
    B.typeOn(dates, 1.0, 2);
    B.during(mark.concat(eb, big, dates), 0, 5);

    // ---- 0:05 all six results, one every 2.5 seconds
    section(5, 22, "WEEK " + D.week + " \u2022 FINAL SCORES", "ALL SIX RESULTS");
    for (var i = 0; i < D.scores.length && i < 6; i++) {
        var s = D.scores[i], y = 300 + i * 112, t = 5 + i * 2.5;
        var aWon = s[1] >= s[3];
        var row = B.panel(c, "Result " + (i + 1), 120, y, 1680, 92, "charDark", aWon ? "gold" : "steel", 4);
        var a = B.text(c, s[0], { face: "jersey", k: 5, color: aWon ? "gold" : "cream", x: 168, y: y + 21, maxW: 560 });
        var as = B.text(c, B.pts(s[1]), { face: "jersey", k: 5, color: aWon ? "gold" : "muted", x: 900, y: y + 21, align: "right" });
        var dash = B.text(c, "-", { face: "jersey", k: 5, color: "muted", x: 960, y: y + 21, align: "center" });
        var bs = B.text(c, B.pts(s[3]), { face: "jersey", k: 5, color: aWon ? "muted" : "gold", x: 1020, y: y + 21 });
        var bt = B.text(c, s[2], { face: "jersey", k: 5, color: aWon ? "cream" : "gold", x: 1752, y: y + 21, align: "right", maxW: 560 });
        var all = row.concat(a, as, dash, bs, bt);
        B.slideIn(all, t, 1920, 0, 4);
        B.during(all, t, 22);
    }

    // ---- 0:22 upset of the week
    section(22, 28, "WEEK " + D.week, "UPSET OF THE WEEK");
    var stamp = B.image(c, "stamp-gold.png", 960, 560, { center: true });
    var uw = B.text(c, D.upset.winner, { face: "jersey", k: 9, color: "cream", x: 960, y: 440, align: "center", maxW: 680, shadow: "black" });
    var ul = B.text(c, "OVER " + D.upset.loser, { face: "silk", k: 5, color: "gold", x: 960, y: 556, align: "center", maxW: 680 });
    var us = B.text(c, B.pts(D.upset.winnerPoints) + " - " + B.pts(D.upset.loserPoints), { face: "jersey", k: 5, color: "muted", x: 960, y: 604, align: "center" });
    B.pop(stamp, 22.3);
    B.slideIn(uw, 22.6, 0, -80, 4);
    B.blinkIn(ul.concat(us), 23.2);
    B.during(stamp.concat(uw, ul, us), 22, 28);

    // ---- 0:28 three stars: third, second, then first
    section(28, 38, "WEEK " + D.week + " \u2022 WEEKLY AWARDS", "THREE STARS");
    var stars = [["THIRD STAR", D.thirdStar, 28.4, 120], ["SECOND STAR", D.secondStar, 31.0, 690], ["FIRST STAR", D.firstStar, 33.6, 1260]];
    for (var j = 0; j < 3; j++) {
        var st = stars[j], x = st[3], first = j === 2;
        var p = B.panel(c, st[0], x, 360, 540, 420, first ? "charcoal" : "charDark", first ? "gold" : "steel", first ? 8 : 4);
        var lab = B.text(c, st[0], { face: "silk", k: 5, color: first ? "gold" : "muted", x: x + 270, y: 410, align: "center" });
        var team = B.text(c, st[1][0], { face: "jersey", k: 6, color: "cream", x: x + 270, y: 500, align: "center", maxW: 480 });
        var pts = B.text(c, B.pts(st[1][1]), { face: "jersey", k: first ? 10 : 8, color: "gold", x: x + 270, y: 610, align: "center" });
        var ptsLab = B.text(c, "POINTS", { face: "silk", k: 4, color: "muted", x: x + 270, y: first ? 726 : 706, align: "center" });
        B.countUp(pts, st[2] + B.f(8), B.pts(st[1][1]), 14);
        var card = p.concat(lab, team, pts, ptsLab);
        B.slideIn(card, st[2], 0, 700, 4);
        B.during(card, st[2], 38);
    }

    // ---- 0:38 tough luck and lucky win
    section(38, 45, "WEEK " + D.week + " \u2022 WEEKLY AWARDS", "LUCK OF THE DRAW");
    var tl = B.row(c, 380, "TOUGH LUCK: " + D.toughLuck.team, B.pts(D.toughLuck.points) + " IN A LOSS", { h: 120, k: 6, edge: "red" });
    var tlSub = B.text(c, "LOST TO " + D.toughLuck.lostTo, { face: "silk", k: 4, color: "muted", x: 168, y: 516 });
    var lw = B.row(c, 620, "LUCKY WIN: " + D.luckyWin.team, B.pts(D.luckyWin.points) + " AND A WIN", { h: 120, k: 6, edge: "green" });
    var lwSub = B.text(c, "BEAT " + D.luckyWin.beat, { face: "silk", k: 4, color: "muted", x: 168, y: 756 });
    B.slideIn(tl.concat(tlSub), 38.3, -1920, 0, 4);
    B.slideIn(lw.concat(lwSub), 41.5, 1920, 0, 4);
    B.during(tl.concat(tlSub), 38.3, 45);
    B.during(lw.concat(lwSub), 41.5, 45);

    // ---- 0:45 standings movers
    section(45, 53, "AFTER WEEK " + D.week, "STANDINGS MOVERS");
    for (var m = 0; m < D.movers.length && m < 4; m++) {
        var mv = D.movers[m], up = mv[2] >= 0;
        var r = B.row(c, 330 + m * 130, mv[0] + " TO " + mv[1], (up ? "UP " : "DOWN ") + Math.abs(mv[2]),
            { h: 104, k: 6, edge: up ? "green" : "red", rightColor: up ? "green" : "red" });
        B.slideIn(r, 45.3 + m * 1.5, 1920, 0, 4);
        B.during(r, 45.3 + m * 1.5, 53);
    }
    var lead = B.text(c, "LEADER: " + D.leader.team + " \u2022 " + D.leader.record, { face: "silk", k: 5, color: "gold", x: 156, y: 900, maxW: 1600 });
    B.blinkIn(lead, 49);
    B.during(lead, 49, 53);

    // ---- 0:53 next week
    var nh = B.header(c, "NEXT WEEK", D.nextWeek.label, 53, { x: 156, y: 96, k: 8 });
    B.during(nh.bar.concat(nh.eyebrow, nh.title), 53, 60);
    var ta = B.text(c, D.nextWeek.teamA, { face: "jersey", k: 10, color: "cream", x: 860, y: 440, align: "right", maxW: 720, shadow: "black" });
    var vs = B.text(c, "VS", { face: "jersey", k: 8, color: "gold", x: 960, y: 450, align: "center" });
    var tb = B.text(c, D.nextWeek.teamB, { face: "jersey", k: 10, color: "cream", x: 1060, y: 440, maxW: 720, shadow: "black" });
    var see = B.text(c, "SEE YOU MONDAY", { face: "silk", k: 6, color: "gold", x: 960, y: 700, align: "center" });
    B.slideIn(ta, 53.3, -1000, 0, 4);
    B.slideIn(tb, 53.3, 1000, 0, 4);
    B.pop(vs, 53.7);
    B.blinkIn(see, 55);
    B.during(ta.concat(vs, tb, see), 53.3, 60);
    B.signoff(c);
});
