// 09 Countdown
// An 8-second scoreboard clock counting down to a league event, for the hype videos. Set the
// event and how long is left at the moment the video is posted, save, and run this file in
// EffectCraft (File > Scripts > Run Script File). Render it as an H.264 movie.

#include "lib/blha.jsxinc"

var DATA = {
    event: "STARTUP DRAFT",
    when: "SATURDAY, JULY 17 - 8:00 PM ET",
    // time left when the clip starts
    days: 3,
    hours: 12,
    minutes: 0,
    seconds: 5
};

BLHA.run("09 Countdown", function () {
    var B = BLHA, D = DATA;
    var c = B.comp(B.folder("Countdowns"), "Countdown - " + D.event, 8);
    B.background(c, "arena");

    var plate = B.text(c, "COUNTDOWN TO", { face: "silk", k: 6, color: "gold", x: 960, y: 120, align: "center" });
    var platePlate = B.plateFor(c, "Eyebrow plate", plate, 24, 14, "black");
    var ev = B.text(c, D.event, { face: "jersey", k: 12, color: "cream", x: 960, y: 300, align: "center", maxW: 1700, shadow: "black" });
    var board = B.panel(c, "Scoreboard", 240, 500, 1440, 340, "black", "gold", 8);
    var units = ["DAYS", "HRS", "MIN", "SEC"], digits = [];
    for (var i = 0; i < 4; i++) {
        var x = 300 + i * 340;
        B.box(c, "Cell " + units[i], x, 540, 300, 220, "charDark");
        digits.push(B.text(c, "00", { face: "jersey", k: 16, color: "gold", x: x + 150, y: 570, align: "center", name: units[i] }));
        B.text(c, units[i], { face: "silk", k: 5, color: "muted", x: x + 150, y: 780, align: "center" });
    }
    for (var j = 0; j < 3; j++) B.text(c, ":", { face: "jersey", k: 12, color: "gold", x: 300 + (j + 1) * 340 - 20, y: 600, align: "center" });
    var when = B.text(c, D.when, { face: "silk", k: 6, color: "cream", x: 960, y: 900, align: "center", maxW: 1700 });

    // one tick a second
    var total = ((D.days * 24 + D.hours) * 60 + D.minutes) * 60 + D.seconds;
    function two(n) { return (n < 10 ? "0" : "") + n; }
    for (var t = 0; t < 8; t++) {
        var left = Math.max(0, total - t);
        var parts = [Math.floor(left / 86400), Math.floor(left / 3600) % 24, Math.floor(left / 60) % 60, left % 60];
        for (var p = 0; p < 4; p++) {
            var prop = B.textProp(B.main(digits[p])), d = prop.value;
            d.text = two(parts[p]);
            prop.setValueAtTime(t, d);
        }
    }
    B.blinkIn(plate.concat(platePlate), 0.1);
    B.pop(ev, 0.3);
    B.blinkIn(when, 0.9);
});
