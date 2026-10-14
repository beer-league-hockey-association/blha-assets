// 05 Trade Alert
// An 8-second trade alert with its sound, for 🚨│completed-trades. Fill in the two sides, save,
// and run this file in EffectCraft (File > Scripts > Run Script File). Render it as an H.264
// movie with audio. Up to four lines a side; picks are written like "2028 2ND ROUND (TEAM X)".

#include "lib/blha.jsxinc"

var DATA = {
    teamA: "TEAM A",
    teamAGets: ["PLAYER ONE", "2028 2ND ROUND"],
    teamB: "TEAM B",
    teamBGets: ["PLAYER TWO", "$50 FAAB"],
    date: "OCT 14"
};

BLHA.run("05 Trade Alert", function () {
    var B = BLHA, D = DATA;
    var c = B.comp(B.folder("Trade Alerts"), "Trade Alert - " + D.teamA + " and " + D.teamB, 8);
    B.background(c, "dots");
    B.sound(c, "sfx-alert.wav", 0);

    // The alert band flashes red and gold with the siren.
    var red = B.box(c, "Alert red", 0, 96, B.W, 168, "red");
    var gold = B.box(c, "Alert gold", 0, 96, B.W, 168, "gold");
    var o = B.opacity(gold[0]);
    for (var i = 0; i < 6; i++) o.setValueAtTime(B.f(i * 6), i % 2 === 0 ? 0 : 100);
    o.setValueAtTime(1.2, 0);
    B.hold(o);
    var word = B.text(c, "TRADE ALERT", { face: "jersey", k: 12, color: "cream", x: 960, y: 120, align: "center", shadow: "black" });
    var when = B.text(c, D.date, { face: "silk", k: 4, color: "cream", x: 1800, y: 228, align: "right" });
    B.pop(word, 0);

    function side(x, team, gets, from, t) {
        var p = B.panel(c, team, x, 340, 760, 560, "charDark", "gold", 6);
        var head = B.text(c, team, { face: "jersey", k: 8, color: "gold", x: x + 380, y: 380, align: "center", maxW: 680 });
        var lab = B.text(c, "GETS", { face: "silk", k: 5, color: "muted", x: x + 380, y: 480, align: "center" });
        var items = [];
        for (var j = 0; j < gets.length && j < 4; j++) {
            items = items.concat(B.text(c, gets[j], { face: "jersey", k: 5, color: "cream", x: x + 380, y: 560 + j * 80, align: "center", maxW: 680 }));
        }
        B.slideIn(p.concat(head, lab, items), t, from, 0, 4);
        return p.concat(head, lab, items);
    }
    side(120, D.teamA, D.teamAGets, -1000, 1.2);
    side(1040, D.teamB, D.teamBGets, 1000, 1.2);
    var swap = B.text(c, "<>", { face: "jersey", k: 10, color: "gold", x: 960, y: 570, align: "center", shadow: "black" });
    B.pop(swap, 1.6);
    B.signoff(c, "BLHA TRADE CENTER \u2022 NO VOTES \u2022 NO VETOES");
});
