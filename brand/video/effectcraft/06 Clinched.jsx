// 06 Clinched
// A 6-second stamp for 🏁│playoff-race when a franchise clinches or is eliminated. Pick the kind,
// save, and run this file in EffectCraft (File > Scripts > Run Script File). Render it as an H.264
// movie with audio. Only post a clinch once it's certain in the standings, tiebreakers included.
//
// kind is one of: "playoff", "bye", "presidents", "eliminated"

#include "lib/blha.jsxinc"

var DATA = {
    team: "TEAM A",
    kind: "playoff"
};

BLHA.run("06 Clinched", function () {
    var B = BLHA, D = DATA;
    var KINDS = {
        playoff: ["CLINCHED", "A PLAYOFF SPOT", "stamp-green.png", "green"],
        bye: ["CLINCHED", "A FIRST-ROUND BYE", "stamp-green.png", "green"],
        presidents: ["CLINCHED", "THE PRESIDENTS' TROPHY", "stamp-gold.png", "gold"],
        eliminated: ["ELIMINATED", "FROM PLAYOFF CONTENTION", "stamp-red.png", "red"]
    };
    var k = KINDS[D.kind];
    if (!k) throw new Error("kind must be \"playoff\", \"bye\", \"presidents\" or \"eliminated\"");
    var c = B.comp(B.folder("Playoff Race"), (D.kind === "eliminated" ? "Eliminated - " : "Clinched - ") + D.team, 6);
    B.background(c, "dots");
    B.sound(c, "sfx-clinch.wav", 0);

    var team = B.text(c, D.team, { face: "jersey", k: 12, color: "cream", x: 960, y: 150, align: "center", maxW: 1700, shadow: "black" });
    var stamp = B.image(c, k[2], 960, 600, { center: true });
    var word = B.text(c, k[0], { face: "jersey", k: 12, color: k[3], x: 960, y: 500, align: "center", maxW: 700 });
    var sub = B.text(c, k[1], { face: "silk", k: 5, color: k[3], x: 960, y: 646, align: "center", maxW: 720 });
    var race = B.text(c, "BLHA PLAYOFF RACE", { face: "silk", k: 5, color: "muted", x: 960, y: 900, align: "center" });
    B.slideIn(team, 0.05, 0, -300, 4);
    B.pop(stamp.concat(word), 0.45);           // lands on the effect's hit
    B.blinkIn(sub, 0.9);
    B.blinkIn(race, 1.3);
});
