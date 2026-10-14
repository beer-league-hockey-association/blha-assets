// 08 Champion Banner
// The champion's banner drops into the rafters (12 seconds, with its sound). Fill in DATA once
// the Championship is final in Fantrax, save, and run this file in EffectCraft
// (File > Scripts > Run Script File). Render it as an H.264 movie with audio.

#include "lib/blha.jsxinc"

var DATA = {
    year: "2028",
    city: "CITY",
    team: "TEAM A",
    bannerName: "TEAM A",          // shorter name for the banner itself; "\n" starts a second line
    finalScore: "TEAM A 312.40 - TEAM B 298.15",
    titlesThisCycle: 1             // this franchise's championships in the current Dynasty Pot cycle
};

BLHA.run("08 Champion Banner", function () {
    var B = BLHA, D = DATA;
    var c = B.comp(B.folder("Playoffs"), "Champion Banner - " + D.year, 12);
    B.background(c, "arena");

    var eb = B.text(c, "THE BLHA CHAMPIONSHIP \u2022 " + D.year, { face: "silk", k: 6, color: "gold", x: 960, y: 60, align: "center" });
    var ebPlate = B.plateFor(c, "Eyebrow plate", eb, 24, 14, "black");
    B.blinkIn(eb.concat(ebPlate), 0.2);

    var banner = B.image(c, "banner.png", 960, 140, { center: false, name: "Banner" });
    if (banner.length) B.pos(B.main(banner)).setValue([960, 140 + 296]);
    var b1 = B.text(c, "BLHA", { face: "silk", k: 6, color: "gold", x: 960, y: 210, align: "center" });
    var b2 = B.text(c, "CHAMPIONS", { face: "silk", k: 4, color: "gold", x: 960, y: 260, align: "center" });
    var bn = B.text(c, D.bannerName, { face: "jersey", k: 5, color: "cream", x: 960, y: 330, align: "center", maxW: 270 });
    var by = B.text(c, D.year, { face: "jersey", k: 8, color: "gold", x: 960, y: 510, align: "center", maxW: 270 });
    var drop = banner.concat(b1, b2, bn, by);
    B.slideIn(drop, 1.0, 0, -900, 6);
    B.sound(c, "sfx-reveal.wav", 1.4);         // the hit lands with the banner

    var name = B.text(c, D.city + " " + D.team, { face: "jersey", k: 10, color: "cream", x: 960, y: 790, align: "center", maxW: 1700, shadow: "black" });
    var fin = B.text(c, "FINAL: " + D.finalScore, { face: "silk", k: 5, color: "cream", x: 960, y: 930, align: "center", maxW: 1700 });
    var three = D.titlesThisCycle >= 3;
    var cyc = B.text(c, three ? "THREE TITLES. THE DYNASTY POT IS THEIRS." : "CHAMPIONSHIP " + D.titlesThisCycle + " OF 3 THIS DYNASTY POT CYCLE",
        { face: "silk", k: 4, color: "gold", x: 960, y: 990, align: "center", maxW: 1700 });
    B.pop(name, 2.0);
    B.blinkIn(fin, 2.8);
    B.blinkIn(cyc, 3.4);
    B.expose(c, name, "Champion");

    // gold sparkles around the banner
    var spots = [[640, 220], [1270, 260], [700, 520], [1220, 600], [610, 380], [1300, 430], [760, 150], [1160, 170]];
    for (var i = 0; i < spots.length; i++) {
        var sp = B.box(c, "Sparkle " + (i + 1), spots[i][0], spots[i][1], 12, 12, i % 2 ? "goldLight" : "gold");
        B.blinkIn(sp, 1.5 + i * 0.25, 6, 4);
        B.during(sp, 1.5 + i * 0.25, 1.5 + i * 0.25 + 3);
    }
});
