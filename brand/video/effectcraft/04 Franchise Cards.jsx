// 04 Franchise Cards
// An 8-second intro card for each franchise, plus a reel of all of them back to back.
// Fill in one block per franchise as owners send their details, save, and run this file in
// EffectCraft (File > Scripts > Run Script File). Render each card as an H.264 movie.
//
// Colors are written like "#2457C5". For a logo, put a square PNG (1000 x 1000 or larger, with
// a transparent background) in Images/Logos/ and write its file name in logo, like "ABC.png".
// Leave logo as "" to show the abbreviation instead. Set build to false to skip a franchise.

#include "lib/blha.jsxinc"

var DATA = {
    reelTitle: "THE FOUNDING FRANCHISES",
    franchises: [
        { build: true, city: "CITY ONE", team: "TEAM ONE", abbr: "ONE", primary: "#2457C5", secondary: "#FFB81C", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: true, city: "CITY TWO", team: "TEAM TWO", abbr: "TWO", primary: "#C8241F", secondary: "#F4EFE4", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: true, city: "CITY THREE", team: "TEAM THREE", abbr: "THR", primary: "#0E0F12", secondary: "#FFB81C", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY FOUR", team: "TEAM FOUR", abbr: "FOR", primary: "#3FA34D", secondary: "#0E0F12", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY FIVE", team: "TEAM FIVE", abbr: "FIV", primary: "#2B2D31", secondary: "#EEF5FA", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY SIX", team: "TEAM SIX", abbr: "SIX", primary: "#F4EFE4", secondary: "#2457C5", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY SEVEN", team: "TEAM SEVEN", abbr: "SEV", primary: "#6E2C8F", secondary: "#FFB81C", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY EIGHT", team: "TEAM EIGHT", abbr: "EIG", primary: "#0B6E6E", secondary: "#F4EFE4", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY NINE", team: "TEAM NINE", abbr: "NIN", primary: "#E06D10", secondary: "#0E0F12", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY TEN", team: "TEAM TEN", abbr: "TEN", primary: "#1D2B53", secondary: "#C8241F", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY ELEVEN", team: "TEAM ELEVEN", abbr: "ELV", primary: "#7A1E2C", secondary: "#9AA1A9", owner: "OWNER", founded: "SEASON 2027", logo: "" },
        { build: false, city: "CITY TWELVE", team: "TEAM TWELVE", abbr: "TWL", primary: "#9AA1A9", secondary: "#0E0F12", owner: "OWNER", founded: "SEASON 2027", logo: "" }
    ]
};

BLHA.run("04 Franchise Cards", function () {
    var B = BLHA, folder = B.folder("Franchise Cards"), cards = [];

    for (var i = 0; i < DATA.franchises.length; i++) {
        var f = DATA.franchises[i];
        if (!f.build) continue;
        var ink = B.inkOn(f.primary), accent = f.secondary;
        var c = B.comp(folder, "Franchise Card - " + f.abbr, 8);
        B.box(c, "Primary", 0, 0, B.W, B.H, f.primary);
        var band = B.box(c, "Secondary band", 0, 860, B.W, 220, f.secondary);
        var line = B.box(c, "Band line", 0, 846, B.W, 14, "black");
        var mark = f.logo ? B.imageFit(c, "Logos/" + f.logo, 1440, 430, 560, 560, "Logo") : [];
        if (!mark.length) {
            var plate = B.panel(c, "Abbreviation plate", 1180, 170, 520, 520, f.primary, accent, 12);
            var ab = B.text(c, f.abbr, { face: "jersey", k: 16, color: accent, x: 1440, y: 350, align: "center", maxW: 440, shadow: "black" });
            mark = plate.concat(ab);
        }
        var from = B.text(c, "FROM " + f.city, { face: "silk", k: 6, color: ink, x: 156, y: 300, maxW: 960 });
        var name = B.text(c, "THE " + f.team, { face: "jersey", k: 12, color: ink, x: 156, y: 380, maxW: 980, shadow: ink === "cream" ? "black" : null });
        var meta = B.text(c, "OWNER " + f.owner + "  \u2022  FOUNDED " + f.founded,
            { face: "silk", k: 5, color: B.inkOn(f.secondary), x: 156, y: 950, maxW: 1600 });
        B.expose(c, name, "Team name");
        B.expose(c, from, "From");
        B.expose(c, meta, "Owner line");
        B.slideIn(band.concat(line), 0.1, -B.W, 0, 4);
        B.pop(mark, 0.5);                                    // lands with the sting's hit
        B.slideIn(from, 0.9, -800, 0, 4);
        B.typeOn(name, 1.2, 2);
        B.blinkIn(meta, 2.2);
        B.sound(c, "sting-intro.wav", 0);
        cards.push(c);
    }

    if (cards.length > 1) {
        var reel = B.comp(folder, "Franchise Cards - All", 4 + cards.length * 8);
        B.background(reel, "charcoal");
        var t = B.text(reel, DATA.reelTitle, { face: "jersey", k: 12, color: "cream", x: 960, y: 420, align: "center", maxW: 1700, shadow: "black" });
        var s = B.text(reel, "BEER LEAGUE HOCKEY ASSOCIATION \u2022 EST. 2026", { face: "silk", k: 5, color: "gold", x: 960, y: 600, align: "center" });
        B.pop(t, 0.3);
        B.blinkIn(s, 0.9);
        B.during(t.concat(s), 0, 4);
        for (var j = 0; j < cards.length; j++) {
            var L = reel.layers.add(cards[j]);
            L.startTime = 4 + j * 8;
        }
    }
});
