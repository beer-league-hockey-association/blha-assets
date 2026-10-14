// 03 Monthly Awards
// The monthly awards video, timed to the "Monthly awards" script. Copy the winners from the
// League Bot's Monthly Awards post in 📰│weekly-recap into DATA, save, and run this file in
// EffectCraft (File > Scripts > Run Script File). Render it as an H.264 movie.
// For a shared award, write both names in one line: "TEAM A & TEAM B".

#include "lib/blha.jsxinc"

var DATA = {
    month: "OCTOBER",
    hardLuck: { team: "TEAM B", detail: "195.00 POINTS IN 2 LOSSES" },
    biggestWeek: { team: "TEAM D", detail: "140.00 POINTS IN WEEK 3" },
    bestRecord: { team: "TEAM C", detail: "3-0-1" },
    managerOfTheMonth: { team: "TEAM B", detail: "325.00 POINTS", owner: "OWNER NAME" }
};

BLHA.run("03 Monthly Awards", function () {
    var B = BLHA, D = DATA;
    var c = B.comp(B.folder("Monthly Awards"), "Monthly Awards - " + D.month, 60);
    B.background(c, "dots");

    // ---- 0:00 open (the title slams with the intro sting's hit at 0.5 s)
    var trophy = B.image(c, "trophy.png", 960, 300, { center: true, scale: 200 });
    var eb = B.text(c, "BLHA MONTHLY AWARDS", { face: "silk", k: 6, color: "gold", x: 960, y: 470, align: "center" });
    var big = B.text(c, D.month, { face: "jersey", k: 16, color: "cream", x: 960, y: 540, align: "center", maxW: 1600, shadow: "black" });
    B.pop(trophy, B.f(3));
    B.blinkIn(eb, B.f(9));
    B.pop(big, B.f(15));
    B.during(trophy.concat(eb, big), 0, 5);

    // ---- the four awards, ten seconds each
    B.awardCard(c, 5, 15, "HARD LUCK", D.hardLuck.team, D.hardLuck.detail, { edge: "steel" });
    B.awardCard(c, 15, 25, "BIGGEST SINGLE WEEK", D.biggestWeek.team, D.biggestWeek.detail);
    B.awardCard(c, 25, 35, "BEST RECORD OF THE MONTH", D.bestRecord.team, D.bestRecord.detail);
    var motm = B.awardCard(c, 35, 45, "MANAGER OF THE MONTH", D.managerOfTheMonth.team, D.managerOfTheMonth.detail);
    var cup = B.image(c, "trophy.png", 960, 200, { center: true, scale: 100 });
    B.pop(cup, 35.6);
    B.during(cup, 35.6, 45);

    // ---- 0:45 the role
    var h = B.header(c, "THE ROLE", "MANAGER OF THE MONTH", 45, { x: 156, y: 300, k: 10 });
    var who = B.text(c, D.managerOfTheMonth.owner + " WEARS IT", { face: "jersey", k: 8, color: "gold", x: 156, y: 520, maxW: 1600 });
    var until = B.text(c, "UNTIL NEXT MONTH'S AWARDS", { face: "silk", k: 6, color: "cream", x: 156, y: 640 });
    B.slideIn(who, 45.6, -1200, 0, 4);
    B.blinkIn(until, 46.4);
    B.during(h.bar.concat(h.eyebrow, h.title, who, until), 45, 52);

    // ---- 0:52 sign-off
    var a = B.text(c, "BRAGGING RIGHTS ONLY", { face: "jersey", k: 10, color: "cream", x: 960, y: 400, align: "center", shadow: "black" });
    var b = B.text(c, "NO MONEY \u2022 NO PICKS \u2022 STILL FEELS GOOD", { face: "silk", k: 5, color: "gold", x: 960, y: 560, align: "center" });
    var n = B.text(c, "SEE YOU NEXT MONTH", { face: "silk", k: 6, color: "cream", x: 960, y: 680, align: "center" });
    B.pop(a, 52.2);
    B.blinkIn(b, 53);
    B.blinkIn(n, 54);
    B.during(a.concat(b, n), 52, 60);
    B.signoff(c);
});
