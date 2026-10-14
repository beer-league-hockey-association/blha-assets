// 01 Brand Kit
// The league's everyday graphics: a lower third, a section title, a title card, an end card and
// a corner bug. Change the words in DATA, save, then run this file in EffectCraft with
// File > Scripts > Run Script File. Keep the quotes around every piece of text.

#include "lib/blha.jsxinc"

var DATA = {
    lowerThird: {
        eyebrow: "COMMISSIONER",          // the small gold label
        name: "YOUR NAME",                // the big line
        seconds: 6
    },
    sectionTitle: {
        eyebrow: "SERVER TOUR",
        title: "LEAGUE OFFICE",
        seconds: 4
    },
    titleCard: {
        eyebrow: "BLHA VIDEO",
        title: "TITLE GOES HERE",
        sub: "ONE LINE ABOUT THIS VIDEO",
        seconds: 5
    },
    endCard: {
        line1: "FOUNDING OWNERS WANTED",
        line2: "$150 A SEASON",
        line3: "STARTUP DRAFT - SUMMER 2027",
        seconds: 7
    },
    cornerBug: {
        seconds: 10
    }
};

BLHA.run("01 Brand Kit", function () {
    var B = BLHA, folder = B.folder("Brand Kit"), d, c, t;

    // ---- Lower third (render with alpha: ProRes 4444)
    d = DATA.lowerThird;
    c = B.comp(folder, "Lower Third - " + d.name, d.seconds);
    var name = B.text(c, d.name, { face: "jersey", k: 6, color: "cream", x: 168, y: 852, name: "Name" });
    var namePlate = B.plateFor(c, "Name plate", name, 30, 24, "charcoal");
    var bar = B.box(c, "Gold bar", 126, 828, 12, 108, "gold");
    var eyebrow = B.text(c, d.eyebrow, { face: "silk", k: 4, color: "black", x: 168, y: 792, name: "Eyebrow" });
    var tab = B.plateFor(c, "Eyebrow tab", eyebrow, 12, 10, "gold");
    B.expose(c, name, "Name");
    B.expose(c, eyebrow, "Eyebrow");
    t = d.seconds - 0.6;
    B.slideIn(bar, 0.2, 0, 120, 3);
    B.slideIn(name.concat(namePlate), 0.3, -900, 0, 4);
    B.blinkIn(eyebrow.concat(tab), 0.7);
    B.slideOut(name.concat(namePlate, eyebrow, tab), t, -1100, 0, 4);
    B.slideOut(bar, t + B.f(4), 0, 120, 3);

    // ---- Section title (alpha)
    d = DATA.sectionTitle;
    c = B.comp(folder, "Section Title - " + d.title, d.seconds);
    var band = B.box(c, "Band", 0, 430, B.W, 220, "charcoal");
    var top = B.box(c, "Band top", 0, 424, B.W, 6, "gold");
    var bottom = B.box(c, "Band bottom", 0, 650, B.W, 6, "gold");
    var sEye = B.text(c, d.eyebrow, { face: "silk", k: 5, color: "gold", x: 960, y: 466, align: "center", name: "Eyebrow" });
    var sTitle = B.text(c, d.title, { face: "jersey", k: 10, color: "cream", x: 960, y: 518, align: "center", maxW: 1680, shadow: "black", name: "Title" });
    B.expose(c, sTitle, "Title");
    B.expose(c, sEye, "Eyebrow");
    B.slideIn(band.concat(top, bottom), 0, -B.W, 0, 4);
    B.blinkIn(sEye, B.f(10));
    B.pop(sTitle, B.f(12));
    B.slideOut(band.concat(top, bottom, sEye, sTitle), d.seconds - 0.5, B.W, 0, 4);

    // ---- Title card (full screen)
    d = DATA.titleCard;
    c = B.comp(folder, "Title Card - " + d.title, d.seconds);
    B.background(c, "charcoal");
    var mark = B.image(c, "b-mark-12.png", 1464, 276);
    var h = B.header(c, d.eyebrow, d.title, B.f(6), { x: 156, y: 330, k: 12, maxW: 1200 });
    var sub = B.text(c, d.sub, { face: "silk", k: 5, color: "muted", x: 156, y: 540, maxW: 1200, name: "Sub" });
    B.signoff(c);
    B.expose(c, h.title, "Title");
    B.expose(c, h.eyebrow, "Eyebrow");
    B.expose(c, sub, "Sub line");
    B.pop(mark, B.f(2));
    B.blinkIn(sub, B.f(24));

    // ---- End card (full screen)
    d = DATA.endCard;
    c = B.comp(folder, "End Card", d.seconds);
    B.background(c, "charcoal");
    var wm = B.image(c, "wordmark.png", 960, 330, { center: true });
    var l1 = B.text(c, d.line1, { face: "jersey", k: 8, color: "cream", x: 960, y: 640, align: "center", maxW: 1680, shadow: "black", name: "Line 1" });
    var l2 = B.text(c, d.line2, { face: "jersey", k: 6, color: "gold", x: 960, y: 760, align: "center", maxW: 1680, name: "Line 2" });
    var l3 = B.text(c, d.line3, { face: "silk", k: 5, color: "cream", x: 960, y: 860, align: "center", maxW: 1680, name: "Line 3" });
    B.expose(c, l1, "Line 1");
    B.expose(c, l2, "Line 2");
    B.expose(c, l3, "Line 3");
    B.pop(wm, B.f(3));
    B.slideIn(l1, B.f(18), 0, 60, 4);
    B.slideIn(l2, B.f(30), 0, 60, 4);
    B.blinkIn(l3, B.f(42));

    // ---- Corner bug (alpha)
    d = DATA.cornerBug;
    c = B.comp(folder, "Corner Bug", d.seconds);
    var bug = B.image(c, "b-small-6.png", B.W - 96 - 84, B.H - 60 - 84, { name: "B" });
    if (bug.length) B.opacity(B.main(bug)).setValue(85);
    B.blinkIn(bug, 0);
});
