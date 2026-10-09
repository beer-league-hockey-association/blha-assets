#!/usr/bin/env python3
"""Build the BLHA Send Console: one HTML page with a Discohook link per message.

Reads discohook-backups/links.json (from build_news_templates.py) and writes
discohook-backups/BLHA_Send_Console.html.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_channels as channels  # noqa: E402
import posted_messages as posted  # noqa: E402
import base64  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LINKS = json.loads((ROOT / "discohook-backups" / "links.json").read_text(encoding="utf-8"))

CHANNEL_NAMES = {
    "calendar": "league-calendar", "ledger": "league-ledger", "voting": "league-voting",
}
CATEGORIES = [
    ("league-office", "League Office"), ("the-wire", "The Wire"), ("general-managers", "General Managers"),
    ("trade-center", "Trade Center"), ("scouting", "Scouting Department"), ("waiver-wire", "Waiver Wire"),
    ("league-competition", "League Competition"), ("commissioners-office", "Commissioner's Office"),
    ("draft-center", "Draft Center"), ("franchise-hq", "Franchise HQ"),
]
CONSTITUTION_LABELS = {
    "00_quick_reference_and_article_i": "Quick Reference, Financial Allocation and Article I",
    "01_articles_ii_to_iii": "Articles II to III",
    "02_articles_iv_to_v": "Articles IV to V",
    "03_articles_vi_to_x": "Articles VI to X",
    "04_articles_xi_to_xiii": "Articles XI to XIII",
    "05_articles_xiv_to_xvi": "Articles XIV to XVI",
    "06_articles_xvii_to_xix": "Articles XVII to XIX",
    "07_articles_xx": "Article XX",
}
BUNDLES = [
    ("01_Announcements", "announcements", "Standard notice, action required, urgent deadline, season opening, season closing, Commissioner correction"),
    ("02_Calendar", "league-calendar", "Calendar event, deadline reminder, calendar published, date change, Winter Meetings, calendar sync"),
    ("03_Ledger", "league-ledger", "Season ledger, dues status, prize pool, payment confirmed, prize paid, Dynasty Pot update"),
    ("04_Voting", "league-voting", "Amendment proposal, official vote, vote result"),
    ("05_Constitution_and_Rulings", "constitution and rulings-log", "Constitution updated, amendment, rule ruling, recusal notice, appeal outcome"),
    ("06_Honors_and_Records", "hall-of-champions", "Champion crowned, Presidents' Trophy, Dynasty Pot won"),
    ("07_Ownership", "announcements", "New owner, franchise seeking an owner, Commissioner transition"),
    ("08_Trades", "completed-trades", "Trade completed"),
    ("09_Community_and_Traditions", "announcements, gm-lounge and hall-of-champions", "Awards Night ballots and winners, Wooden Spoon proposal and award, League Bot launch"),
    ("10_Deadline_Day_Trade_Center", "trade-block and league-calendar", "Trade deadline day: the Trade Bait board (forum post) and the Deadline Day Trade Center Sesh event. The live tracker, report cards and polls are automated"),
]


def channel_from_file(rel: str) -> str:
    stem = Path(rel).name.replace("_channel_intro.json", "")
    stem = re.sub(r"^\d+_", "", stem)
    return CHANNEL_NAMES.get(stem, stem.replace("_", "-"))


def shown(channel: str) -> str:
    """The row's channel as the server shows it: every channel slug becomes its full name."""
    return re.sub(r"[a-z]+(?:-[a-z]+)*", lambda m: channels.name(m.group(0)) if m.group(0) in channels.EMOJI else m.group(0), channel)


AUDITED = "2026-10-07"         # when the server was last checked against these templates
POSTED = posted.load()          # live in Discord and current
UPDATE = posted.to_update()     # live in Discord but out of date: edit in place
COUNTS = {"posted": 0, "pin": 0, "update": 0, "send": 0}

# Forum channels: an intro goes out as a forum post, which needs a thread name and Pin Post.
FORUMS = {"trade-block", "looking-to-acquire", "scouting", "waiver-watch", "commissioner-support",
          "rules-questions", "league-suggestions", "franchise-news", "roster-showcase"}
# Channels that had no webhook when the server was last checked (AUDITED): one has to exist before sending.
NO_WEBHOOK = {"completed-trades", "player-values", "waiver-watch", "consolation-bracket", "commissioner-support",
              "rules-questions", "rulings-log", "owner-handbook", "draft-room", "draft-day-trades",
              "franchise-news", "roster-showcase"}
# Old posts to clear out before the intro goes in, so the intro is the first message in the channel.
CLEAR_FIRST = {"draft-announcements": "Delete the 3 old [TEST] posts here first.",
               "draft-results": "Delete the old [TEST] post here first."}


def edit_link(rel: str) -> str:
    """A Discohook link that opens the template as an edit of the live message."""
    data = json.loads((ROOT / "templates" / rel).read_text(encoding="utf-8"))
    body = {"messages": [{"data": data, "reference": UPDATE[rel]["message"]}]}
    raw = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
    return "https://discohook.org/?data=" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def nice(day: str) -> str:
    y, m, d = (int(x) for x in day.split("-"))
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1] + f" {d}"


def row(key: str, channel: str, what: str, href: str, cta: str = "Open in Discohook", rel: str | None = None) -> str:
    state, box = "send", ""
    if rel in POSTED:
        entry = POSTED[rel]
        if entry.get("pinned") is False:
            state, what, cta = "pin", f"Posted {nice(entry['posted'])} and current. Still to do: pin it.", "Open copy"
        else:
            state, what, cta, box = "posted", f"Posted {nice(entry['posted'])} and current. Nothing to do.", "Open copy", " checked disabled"
    elif rel in UPDATE:
        state, cta, href = "update", "Edit in Discohook", edit_link(rel)
        what = ("Posted, but the template has changed since. This opens as an EDIT of the live message: "
                "paste this channel's webhook URL and press Edit. No deleting or reposting; it keeps its place and its pin.")
    elif rel is not None:
        before = [CLEAR_FIRST[channel]] if channel in CLEAR_FIRST else []
        if channel in NO_WEBHOOK:
            before.append("No webhook in this channel yet: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL.")
        what = " ".join(before + [what])
    if rel is not None:
        COUNTS[state] += 1
    return (
        f'<li class="row {state}" data-key="{html.escape(key)}">'
        f'<label class="tick"><input type="checkbox" id="c-{html.escape(key)}" aria-label="Done: {html.escape(what)}"{box}><span></span></label>'
        f'<div class="what"><span class="ch">{html.escape(shown(channel))}</span><span class="desc">{html.escape(what)}</span></div>'
        f'<a class="go" href="{href}" target="_blank" rel="noopener">{cta}</a></li>'
    )


# Templates that automation already posts for you in some cases.
AUTOMATED = {
    "CALENDAR EVENT": "Automation posts calendar milestones once their dates are filled in automation/league-office/events.yaml. Use this only for an extra one.",
    "DEADLINE REMINDER": "Automation posts reminders before each deadline in events.yaml. Use this only for an extra one.",
    "DYNASTY POT UPDATE": "Automation posts the Dynasty Pot graphic once the franchises are filled in. Use this only for a written update.",
    "BLHA DEADLINE DAY TRADE CENTER: TRADE BAIT": "Forum post in trade-block a few days before deadline day: fill in the deadline timestamp, send (the thread name is filled in), then pin the post.",
    "BLHA AWARDS NIGHT": "Announcement in announcements once /awards open has posted the ballot in league-voting. The League Bot runs the ballot itself.",
    "BLHA AWARDS NIGHT: THE WINNERS": "The League Bot posts the winners itself with /awards results. Use this only if the bot isn't running.",
    "BLHA DEADLINE DAY TRADE CENTER": "The Sesh event's text. In league-calendar run /create, name it BLHA Deadline Day Trade Center, set deadline day 9:00 AM to 11:59 PM ET, and paste this message's text as the description.",
}


# Templates in a bundle that spans channels: the channel each one goes to.
TEMPLATE_CHANNELS = {
    "BLHA DEADLINE DAY TRADE CENTER: TRADE BAIT": "trade-block",
    "BLHA AWARDS NIGHT": "announcements",
    "BLHA AWARDS NIGHT: THE WINNERS": "hall-of-champions",
    "BLHA DEADLINE DAY TRADE CENTER": "league-calendar",
}


def template_row(key: str, channel: str, label: str, note: str, href: str) -> str:
    return (
        f'<li class="row tmpl" data-key="{html.escape(key)}"><span></span>'
        f'<div class="what"><span class="ch">{html.escape(label)} → {html.escape(shown(channel))}</span><span class="desc">{html.escape(note)}</span></div>'
        f'<a class="go" href="{href}" target="_blank" rel="noopener">Open</a></li>'
    )


def section(title: str, note: str, rows: list[str], sid: str) -> str:
    return (f'<section id="{sid}"><header><h2>{html.escape(title)}</h2><p>{note}</p></header><ol class="rows">' + "".join(rows) + "</ol></section>")


def build() -> str:
    sections: list[str] = []
    n_rows = 0

    # League Office: welcome, constitution, then the rest in channel order
    lo_rows = [row("welcome", "welcome", "Welcome message (all six sections in one message)", LINKS["welcome"], rel="welcome/01_welcome.json")]
    intros = {k.split(":", 1)[1]: v for k, v in LINKS.items() if k.startswith("intro:")}
    lo_intro = {k: v for k, v in intros.items() if k.startswith("league-office/")}
    const_intro = "league-office/01_constitution_channel_intro.json"
    lo_rows.append(row("constitution-intro", "constitution", "Intro. Send this first, then pin it.", lo_intro[const_intro], rel=const_intro))
    for k, v in LINKS.items():
        if k.startswith("constitution:"):
            stem = k.split(":", 1)[1].replace(".json", "")
            idx = stem[:2]
            lo_rows.append(row(f"constitution-{idx}", "constitution", f"Message {int(idx) + 1} of 8: {CONSTITUTION_LABELS[stem]}", v, "Open in Discohook", rel=f"constitution/{stem}.json"))
    lo_rows.append(row("scoring-explained", "constitution", "How BLHA scoring works: the reasoning behind each value. A separate post with its own banner; send it after the Constitution, then pin it.", LINKS["scoring"], rel="league-office/16_scoring_explained.json"))
    for rel, v in lo_intro.items():
        if rel == const_intro:
            continue
        ch = channel_from_file(rel)
        what = "Channel intro. Send, then pin."
        if ch == "league-calendar":
            what = "Channel intro with the Sesh reminder steps, in one message. Send, then pin."
        lo_rows.append(row("intro-" + ch, ch, what, v, rel=rel))
    n_rows += len(lo_rows)
    sections.append(section("League Office", "Webhook channel: change it to each row's channel before you send. Send the constitution messages in order, top to bottom.", lo_rows, "league-office"))

    for folder, title in CATEGORIES[1:]:
        rows = []
        for rel, v in intros.items():
            if rel.startswith(folder + "/"):
                ch = channel_from_file(rel)
                what = "Channel intro. Send, then pin."
                if ch in FORUMS:
                    what = "Forum post. Fill in Discohook's Forum thread name, send, then right-click the post and Pin Post."
                rows.append(row("intro-" + ch, ch, what, v, rel=rel))
        n_rows += len(rows)
        extra = ""
        if folder == "general-managers":
            extra = " Voice channels do not need an intro."
        sections.append(section(title, "Set the webhook to each row's channel, send, then pin." + extra, rows, folder))

    # Reusable templates: one section per bundle, one button per message, so a single message
    # opens on its own. Nothing here is a one-time send, so these rows are never ticked or counted.
    sections.append('<section id="templates"><header><h2>Reusable templates</h2><p>Use these any time, as often as you need. Each button opens one message on its own: set the webhook to the channel shown, replace every placeholder in backticks, then send. Nothing below is automated unless its row says so.</p></header></section>')
    for name, ch, what in BUNDLES:
        msgs = json.loads((ROOT / "discohook-backups" / f"BLHA_Templates_{name}.json").read_text(encoding="utf-8"))["messages"]
        trows = []
        for i, m in enumerate(msgs):
            title = next((e.get("title") for e in reversed(m["data"]["embeds"]) if e.get("title")), f"Message {i + 1}")
            label = title.title().replace("Blha", "BLHA").replace("'S", "'s")
            body = {"messages": [{"data": m["data"]}]}
            raw = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
            href = "https://discohook.org/?data=" + base64.urlsafe_b64encode(raw).decode().rstrip("=")
            note = AUTOMATED.get(title, "Fill in every placeholder in backticks, then send.")
            trows.append(template_row(f"tmpl-{name}-{i}", TEMPLATE_CHANNELS.get(title, ch), label, note, href))
        sections.append(section(name.split("_", 1)[1].replace("_", " "), html.escape(what) + ".", trows, "tmpl-" + name))

    body = "\n".join(sections)
    summary = (f'<p class="status"><b>{COUNTS["posted"] + COUNTS["pin"]}</b> already posted and current'
               + (f' ({COUNTS["pin"]} still need pinning)' if COUNTS["pin"] else '')
               + f' · <b>{COUNTS["update"]}</b> to edit in place · <b>{COUNTS["send"]}</b> left to send. '
               f'Checked against the server on {nice(AUDITED)}.</p>')
    return TEMPLATE.replace("{{BODY}}", body).replace("{{TOTAL}}", str(n_rows)).replace("{{STATUS}}", summary)


TEMPLATE = r"""<title>BLHA Send Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<style>
/* Layout: one narrow column of checklist sections. Each row is a channel, what to send, and one button. */
:root {
  --bg: #EEF0F3; --surface: #FFFFFF; --ink: #1B1D22; --muted: #5B606B; --line: #D8DBE1;
  --accent: #FFB81C; --on-accent: #1B1D22; --accent-ink: #8A5A00; --done: #1F7A4D; --soft: #F6F7F9;
  --f-display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --f-body: "IBM Plex Sans", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #1E2024; --surface: #2B2D31; --ink: #F1EFE8; --muted: #A3A7AF; --line: #3B3E45;
  --accent-ink: #FFB81C; --done: #5CC48E; --soft: #25272B; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #1E2024; --surface: #2B2D31; --ink: #F1EFE8; --muted: #A3A7AF; --line: #3B3E45;
  --accent-ink: #FFB81C; --done: #5CC48E; --soft: #25272B; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font-family: var(--f-body); font-size: 15px; line-height: 1.5; }
main { max-width: 860px; margin-inline: auto; padding-inline: 16px; padding-block: 28px 56px; }
h1, h2 { font-family: var(--f-display); text-wrap: balance; margin: 0; letter-spacing: .01em; }
h1 { font-size: 2.6rem; line-height: 1; font-weight: 700; text-transform: uppercase; }
h2 { font-size: 1.55rem; font-weight: 700; text-transform: uppercase; }
.top { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 12px 24px; padding-bottom: 18px; border-bottom: 3px solid var(--accent); }
.top p { margin: 6px 0 0; color: var(--muted); max-width: 52ch; }
.progress { font-family: var(--f-mono); font-size: .85rem; color: var(--muted); display: flex; align-items: center; gap: 10px; }
.progress b { color: var(--ink); font-size: 1.1rem; font-variant-numeric: tabular-nums; }
.progress button { font: inherit; font-size: .8rem; color: var(--muted); background: none; border: 1px solid var(--line); border-radius: 4px; padding: 3px 8px; cursor: pointer; }
.steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); margin: 18px 0 8px; }
.steps div { background: var(--surface); padding: 10px 12px; font-size: .88rem; min-width: 0; }
.note { margin: 10px 0 0; font-size: .88rem; color: var(--muted); max-width: 80ch; } .note b { color: var(--ink); } .note code { font-family: var(--f-mono); font-size: .82rem; background: var(--soft); border: 1px solid var(--line); border-radius: 3px; padding: 0 4px; } .note a { color: var(--accent-ink); }
.steps b { display: block; font-family: var(--f-mono); font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: var(--accent-ink); margin-bottom: 2px; }
section { margin-top: 30px; }
section header { display: flex; flex-direction: column; gap: 2px; margin-bottom: 8px; }
section header p { margin: 0; color: var(--muted); font-size: .88rem; max-width: 70ch; }
.rows { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line); background: var(--surface); }
.row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 10px 12px; border-top: 1px solid var(--line); }
.row:first-child { border-top: 0; }
.what { display: flex; flex-direction: column; min-width: 0; }
.ch { font-family: var(--f-mono); font-size: .9rem; font-weight: 500; overflow-wrap: anywhere; }
.desc { color: var(--muted); font-size: .85rem; }
.go { background: var(--accent); color: var(--on-accent); text-decoration: none; font-weight: 600; font-size: .85rem; padding: 7px 12px; border-radius: 4px; white-space: nowrap; }
.go:hover { filter: brightness(.95); } .go:focus-visible, input:focus-visible + span { outline: 2px solid var(--ink); outline-offset: 2px; }
.tick { display: inline-flex; cursor: pointer; }
.tick input { position: absolute; opacity: 0; width: 22px; height: 22px; margin: 0; cursor: pointer; }
.tick span { width: 22px; height: 22px; border: 2px solid var(--muted); border-radius: 4px; display: inline-block; position: relative; background: var(--surface); }
.tick input:checked + span { background: var(--done); border-color: var(--done); }
.tick input:checked + span::after { content: ""; position: absolute; left: 5px; top: 1px; width: 6px; height: 11px; border: solid var(--surface); border-width: 0 2.5px 2.5px 0; transform: rotate(45deg); }
.row.done .ch, .row.done .desc { opacity: .5; }
.status { margin: 14px 0 0; padding: 10px 12px; background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--accent); font-size: .92rem; }
.row.update .desc, .row.pin .desc { color: var(--accent-ink); font-weight: 500; }
.row.update .go { background: var(--ink); color: var(--surface); }
.row.done .go { background: var(--soft); color: var(--muted); border: 1px solid var(--line); }
@media (max-width: 520px) { .row { grid-template-columns: auto minmax(0, 1fr); } .go { grid-column: 2; justify-self: start; } h1 { font-size: 2.1rem; } }
@media (prefers-reduced-motion: no-preference) { .go { transition: filter .15s; } }
</style>
<main>
  <div class="top">
    <div>
      <h1>BLHA Send Console</h1>
      <p>Each button opens Discohook with the message loaded. Tick a row once it is sent and pinned.</p>
    </div>
    <div class="progress"><span><b id="n-done">0</b> of {{TOTAL}} done</span><button type="button" id="reset">Reset ticks</button></div>
  </div>
  {{STATUS}}
  <div class="steps">
    <div><b>1 Channel</b>Set your webhook's channel in Discord to the row's channel and save.</div>
    <div><b>2 Open</b>Click the row's button. Paste your webhook URL if Discohook asks.</div>
    <div><b>3 Send</b>Check the banner preview, then click Send.</div>
    <div><b>4 Pin</b>Pin the message and delete Discord's "pinned a message" notice.</div>
  </div>
  <p class="note"><b>Dates and times:</b> replace each <code>[TIMESTAMP]</code> with a Discord timestamp such as <code>&lt;t:1791504000:F&gt;</code>, made at <a href="https://sesh.fyi/timestamp" target="_blank" rel="noopener">sesh.fyi/timestamp</a> (pick the full date and time). Delete the backticks around the placeholder. Discord shows the time in each owner's own time zone. For a deadline, add <code>(&lt;t:1791504000:R&gt;)</code> after it for a live countdown. A <code>[DATE STAMP]</code> is the date-only style, which ends in <code>:D</code>, for example <code>&lt;t:1791504000:D&gt;</code>.</p>
{{BODY}}
</main>
<script>
(function () {
  var KEY = "blha-send-console-v1", state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { state = {}; }
  var boxes = Array.prototype.slice.call(document.querySelectorAll(".row input[type=checkbox]"));
  var counter = document.getElementById("n-done");
  function paint() {
    var n = 0;
    boxes.forEach(function (b) {
      var row = b.closest(".row");
      row.classList.toggle("done", b.checked);
      if (b.checked) n++;
    });
    counter.textContent = n;
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  boxes.forEach(function (b) {
    b.checked = b.disabled || !!state[b.id];
    b.addEventListener("change", function () { state[b.id] = b.checked; save(); paint(); });
  });
  document.getElementById("reset").addEventListener("click", function () {
    state = {}; boxes.forEach(function (b) { b.checked = b.disabled; }); save(); paint();
  });
  paint();
})();
</script>
"""

if __name__ == "__main__":
    out = ROOT / "discohook-backups" / "BLHA_Send_Console.html"
    page = build()
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(page) // 1024} KB)")
