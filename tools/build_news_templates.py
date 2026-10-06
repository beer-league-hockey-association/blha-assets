#!/usr/bin/env python3
"""Reusable League Office / Trade Center message templates and Discohook bundles.

1. Writes the reusable templates (placeholders in `backticks`) into templates/.
2. Builds one Discohook bundle per purpose in discohook-backups/ (messages array).
3. Builds discohook.org links for every channel-intro message, constitution
   message and bundle, written to discohook-backups/LINKS.md and links.json.

Every template and link is one Discord message in the BLHA format from
discohook_format.py (footer text and divider on the final embed only). Bundles
are libraries of separate one-message templates: open one, keep the message you
need, send it.

Build order: build_channel_intros.py, normalize_discohook_templates.py,
build_news_templates.py, build_send_console.py.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discohook_format as fmt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "templates"
OUT = ROOT / "discohook-backups"

GOLD, ALERT, RECORD = 16758812, 10697266, 13012757
LO = "BLHA LEAGUE OFFICE"


def tmpl(path: str, title: str, desc: str, footer: str, fields: list[tuple[str, str]], color: int = GOLD) -> None:
    data = {"embeds": fmt.apply([{
        "title": title, "description": desc, "color": color, "footer": {"text": footer},
        "fields": [{"name": n, "value": v, "inline": False} for n, v in fields],
    }])}
    p = T / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- announcements
tmpl("league-office/24_season_closing.json", "BLHA SEASON COMPLETE", "`[SEASON, for example 2027–28]` is officially in the books.", "BLHA RECORDS DEPARTMENT",
     [("CHAMPION", "\U0001F3C6 `[FRANCHISE]`"), ("RUNNER-UP", "`[FRANCHISE]`"), ("THIRD PLACE", "`[FRANCHISE]`"),
      ("PRESIDENTS' TROPHY", "\U0001F947 `[FRANCHISE]`"), ("CONSOLATION CHAMPION", "`[FRANCHISE]` — earns the $50 FAAB bonus next season"),
      ("DYNASTY POT", "`[BALANCE]` • `[LEADING FRANCHISE AND CHAMPIONSHIP COUNT, OR NONE]`"),
      ("NEXT", "`[OFFSEASON / TRADING REOPENS / DRAFT / DUES DEADLINE]`")], RECORD)
tmpl("league-office/13_clerical_correction.json", "COMMISSIONER CORRECTION", "A clerical, Fantrax configuration or platform correction under Section 2.5 of the Constitution.", f"{LO} • OFFICIAL NOTICE",
     [("WHAT WAS WRONG", "`[THE ERROR OR PLATFORM ISSUE]`"), ("RULE BEING APPLIED", "`[ARTICLE AND SECTION OF THE EXISTING RULE]`"),
      ("CORRECTION", "`[WHAT WAS FIXED]`"), ("INTENT PRESERVED", "This correction applies an existing rule. It does not create a new one.")])

# --------------------------------------------------------------------- calendar
tmpl("league-office/32_calendar_published.json", "LEAGUE CALENDAR PUBLISHED", "The League Calendar for **Season `[YEAR]`** is live. Every date comes from the formulas in Article V of the Constitution.", "BLHA LEAGUE CALENDAR",
     [("NHL SCHEDULE RELEASED", "`[DATE]`"), ("DUES DEADLINE", "**`[TIMESTAMP]`** (before the draft)"),
      ("DRAFT", "`[TIMESTAMP]` • 14 to 21 days after the NHL Entry Draft"),
      ("TRADE DEADLINE", "`[TIMESTAMP]` • Sunday 11:59 PM ET, end of Week 20"),
      ("PLAYOFFS", "Quarterfinals `[DATE STAMP]` • Semifinals `[DATE STAMP]` • Championship `[DATE STAMP]` to `[DATE STAMP]`"),
      ("IF A DATE LOOKS WRONG", "The formula in the Constitution controls. Tell the Commissioner.")])
tmpl("league-office/33_calendar_date_change.json", "CALENDAR DATE CHANGE", "`[EVENT]` has been updated.", "BLHA LEAGUE CALENDAR",
     [("PREVIOUS DATE", "`[OLD TIMESTAMP]`"), ("NEW DATE", "**`[NEW TIMESTAMP]`**"),
      ("REASON", "`[NHL SCHEDULE CHANGE / PLATFORM LIMITATION / OTHER]`"),
      ("NOTICE", "Changes get at least 7 days' notice where possible. Deadlines may be extended but are not moved earlier unless the NHL schedule forces it.")], ALERT)

# The Sesh reminder steps are part of the calendar intro (build_channel_intros.py).

# ----------------------------------------------------------------------- ledger
tmpl("league-office/40_ledger_season_summary.json", "SEASON LEDGER", "`[SEASON]` • Published within 30 days after the BLHA Championship.", "BLHA LEAGUE LEDGER",
     [("DUES RECEIVED", "`$[AMOUNT]` from `[12 / X]` franchises"), ("PRIZES PAID", "`$[AMOUNT]`"),
      ("OPERATING RESERVE", "Spent `$[AMOUNT]` on `[FANTRAX PREMIUM / OTHER]` • Unused `$[AMOUNT]` added to the Dynasty Pot"),
      ("LEAGUE SERVICES", "`$[AMOUNT]`"), ("DYNASTY POT", "`$[BALANCE]`")], RECORD)
tmpl("league-office/41_ledger_dues_status.json", "FRANCHISE DUES STATUS", "`[SEASON / DATE]`", "BLHA LEAGUE LEDGER • NO PAYMENT CREDENTIALS POSTED",
     [("PAID AND CONFIRMED", "`[LIST FRANCHISES]`"), ("PREPAID FUTURE SEASONS", "`[FRANCHISE: THROUGH SEASON YYYY]` or none"),
      ("OUTSTANDING", "`[LIST FRANCHISES / NONE]`"), ("DEADLINE", "`[TIMESTAMP]`")], RECORD)
tmpl("league-office/42_ledger_prize_pool.json", "BLHA PRIZE POOL", "`[SEASON]` • 12 franchises × $150 = $1,800", "BLHA LEAGUE LEDGER",
     [("BLHA CHAMPION", "$650"), ("RUNNER-UP", "$350"), ("THIRD PLACE", "$150"), ("PRESIDENTS' TROPHY", "$200"),
      ("DYNASTY POT CONTRIBUTION", "$200"), ("FANTRAX / LEAGUE OPERATING RESERVE", "$150"), ("LEAGUE SERVICES ALLOCATION", "$100")], RECORD)
tmpl("league-office/43_ledger_payment_confirmed.json", "PAYMENT CONFIRMED", "`[FRANCHISE]` is confirmed paid through **Season `[YEAR]`**.", "BLHA LEAGUE LEDGER • NO PAYMENT CREDENTIALS POSTED",
     [("COVERS", "`[SEASON DUES / FUTURE-SEASON PREPAYMENT THROUGH YEAR]`"), ("CONFIRMED", "`[DATE]`"),
      ("PICK TRADES", "`[FRANCHISE]` may now trade its 1st- and 2nd-round picks for drafts through **`[YEAR]`**. A pick trade made before payment is confirmed is reversed (Article XII).")], RECORD)
tmpl("league-office/44_ledger_prize_payout.json", "PRIZE PAID", "`[PRIZE]` for **Season `[YEAR]`** has been paid to `[FRANCHISE]`.", "BLHA LEAGUE LEDGER",
     [("AMOUNT", "`$[AMOUNT]`"), ("PAID", "`[DATE]`"), ("REMAINING THIS SEASON", "`[PRIZES STILL UNPAID, OR NONE]`")], RECORD)
tmpl("league-office/45_ledger_dynasty_pot.json", "DYNASTY POT UPDATE", "The pot stands at **`$[BALANCE]`**.", "BLHA LEAGUE LEDGER",
     [("THIS SEASON ADDED", "`$[DUES CONTRIBUTION]` + `$[UNUSED OPERATING RESERVE]`"),
      ("CHAMPIONSHIP COUNTS THIS CYCLE", "`[FRANCHISE: COUNT]`"),
      ("CYCLE STARTED", "`[SEASON]`"), ("TO WIN", "Three BLHA Championships in the same active cycle (Article IV).")], RECORD)

# ----------------------------------------------------------------------- voting
tmpl("league-office/50_vote_proposal_open.json", "AMENDMENT PROPOSAL — DISCUSSION", "`[PROPOSAL TITLE]`", "BLHA LEAGUE VOTING • DISCUSSION ONLY",
     [("AFFECTED RULE", "`[ARTICLE AND SECTION]`"), ("REPLACEMENT LANGUAGE", "`[EXACT NEW TEXT]`"),
      ("INTENDED EFFECTIVE DATE", "`[SEASON / DATE]`"), ("PROPOSED BY", "`[FRANCHISE OR COMMISSIONER]`"),
      ("VOTING OPENS", "**`[TIMESTAMP]`** • at least 7 days after this post (Article XX)")])
tmpl("league-office/51_vote_open.json", "OFFICIAL BLHA VOTE", "`[PROPOSAL TITLE]`", "BLHA LEAGUE VOTING • OFFICIAL",
     [("QUESTION", "`[EXACT QUESTION]`"), ("OPTIONS", "**Yes** — adopt the amendment\n**No** — keep the current rule"),
      ("VOTING CLOSES", "**`[TIMESTAMP]`** • 7-day window"),
      ("PASSAGE REQUIREMENT", "At least **8 affirmative votes out of 12**. Non-votes and abstentions are not affirmative."),
      ("WHO VOTES", "One formal vote per franchise, cast by the **Franchise Owner**."),
      ("EFFECTIVE", "`[NEXT SEASON / LATER DATE]` • must pass before that Season's dues deadline")])
tmpl("league-office/52_vote_result.json", "VOTE RESULT", "`[PROPOSAL TITLE]`", "BLHA LEAGUE VOTING • FINAL RESULT",
     [("RESULT", "**`[PASSED / FAILED]`**"), ("VOTE TOTAL", "Yes `[X]` • No `[Y]` • Not voted `[Z]` (8 of 12 required)"),
      ("EFFECTIVE", "`[SEASON / DATE / N/A]`"), ("NEXT STEP", "`[CONSTITUTION UPDATED / NO CHANGE]`")], RECORD)

# ----------------------------------------------------- constitution and rulings
tmpl("league-office/10_constitution_new_version.json", "CONSTITUTION UPDATED", "An updated BLHA Constitution has been published.", f"{LO} • OFFICIAL NOTICE",
     [("EFFECTIVE", "`[SEASON / DATE]`"), ("WHAT CHANGED", "`[SUMMARIZE CHANGES WITH ARTICLE NUMBERS]`"),
      ("APPROVED BY VOTE", "`[X]` of 12 on `[DATE]`"), ("ACTION REQUIRED", "`[NONE / REVIEW ARTICLES]`"),
      ("WHERE", "The current version is in **constitution**. Earlier versions are archived.")])
tmpl("league-office/11_constitution_amendment.json", "CONSTITUTION AMENDMENT", "A formally adopted amendment has been added to the BLHA Constitution.", f"{LO} • OFFICIAL NOTICE",
     [("AMENDMENT", "`[TITLE]` • Article `[ROMAN]` Section `[N.N]`"), ("APPROVED", "`[X]` of 12 on `[DATE]`"),
      ("EFFECTIVE", "`[SEASON / DATE]`"), ("TEXT", "`[NEW LANGUAGE OR CONCISE SUMMARY]`"),
      ("STATUS", "Now part of the current Constitution")])
tmpl("league-office/12_rules_ruling.json", "OFFICIAL RULE INTERPRETATION", "`[SHORT ISSUE TITLE]`", f"{LO} • OFFICIAL RULING",
     [("QUESTION", "`[RULE QUESTION]`"), ("RULING", "`[OFFICIAL INTERPRETATION]`"),
      ("BASIS", "`[ARTICLE AND SECTION / FANTRAX SETTING / PRIOR RULING]`"), ("EFFECTIVE", "`[IMMEDIATELY / DATE]`"),
      ("REVIEW", "A directly affected franchise may request review within 48 hours by opening an Appeal ticket in **open-a-ticket** (Section 19.4).")])
tmpl("league-office/14_recusal_notice.json", "COMMISSIONER RECUSAL", "The Commissioner's franchise is involved in `[MATTER]`. A neutral party will decide it.", f"{LO} • OFFICIAL NOTICE",
     [("DECIDED BY", "`[NEUTRAL ASSISTANT COMMISSIONER / TEMPORARY NEUTRAL REVIEWER / UNAFFECTED FRANCHISES]`"),
      ("TIMELINE", "Decision expected by `[DATE STAMP]`"), ("RECORD", "The outcome will be posted in **rulings-log**.")])
tmpl("league-office/15_appeal_outcome.json", "APPEAL OUTCOME", "Review of `[RULING TITLE]`", f"{LO} • OFFICIAL RULING",
     [("REQUESTED BY", "`[FRANCHISE]`"), ("REVIEW PANEL", "`[THREE UNAFFECTED FRANCHISES]`"),
      ("DECISION", "**`[UPHELD / MODIFIED / REVERSED]`**"), ("DETAILS", "`[WHAT CHANGES, IF ANYTHING]`"),
      ("FINAL", "The panel's decision is final for this matter (Article XIX).")], RECORD)

# -------------------------------------------------------------------- ownership
tmpl("league-office/60_owner_welcome.json", "NEW OWNER", "Welcome to the BLHA, `[OWNER]`. They are taking over **`[FRANCHISE]`**.", f"{LO} • OFFICIAL NOTICE",
     [("FRANCHISE", "`[FRANCHISE NAME]`"), ("PAID THROUGH", "Season `[YEAR]` (prepaid dues stay with the franchise)"),
      ("START HERE", "Read **welcome** and **constitution**, then check **league-calendar**.")])
tmpl("league-office/61_franchise_orphaned.json", "FRANCHISE SEEKING AN OWNER", "**`[FRANCHISE]`** is open and the league is looking for a replacement owner.", f"{LO} • OFFICIAL NOTICE",
     [("WHAT HAPPENS NOW", "The Commissioner may lock the franchise from transactions while a replacement is arranged. The Commissioner keeps the roster legal (Article XVIII)."),
      ("PREPAID DUES", "Any prepaid future seasons stay with the franchise and transfer to the new owner."),
      ("INCENTIVE", "`[NONE / DISCLOSED INCENTIVE]`"),
      ("INTERESTED?", "Contact the Commissioner. Please send names of qualified candidates.")], ALERT)
tmpl("league-office/62_commissioner_transition.json", "COMMISSIONER TRANSITION", "`[INTERIM COMMISSIONER]` is now Interim Commissioner.", f"{LO} • OFFICIAL NOTICE",
     [("REASON", "`[RESIGNATION / UNAVAILABLE 14 DAYS]`"), ("HOW CHOSEN", "`[DESIGNATED SUCCESSOR / MAJORITY OF ACTIVE FRANCHISES]`"),
      ("HANDOFF", "Funds, records, Fantrax access and Discord/automation administration transfer within 14 days (Article XIX)."),
      ("NEXT", "A permanent Commissioner is chosen by majority vote of active franchises.")], ALERT)

# ----------------------------------------------------------------------- honors
tmpl("league-office/70_champion_crowned.json", "THE BLHA CHAMPION", "\U0001F3C6 **`[FRANCHISE]`** wins the **Season `[YEAR]`** BLHA Championship.", "BLHA RECORDS DEPARTMENT",
     [("FINAL", "`[FRANCHISE]` `[SCORE]` over `[FRANCHISE]` `[SCORE]` (two-week cumulative)"),
      ("PRIZE", "$650"), ("RUNNER-UP", "`[FRANCHISE]` • $350"), ("THIRD PLACE", "`[FRANCHISE]` • $150"),
      ("CHAMPIONSHIP COUNT", "`[FRANCHISE]` now has `[N]` in the current Dynasty Pot cycle.")], RECORD)
tmpl("league-office/71_presidents_trophy.json", "PRESIDENTS' TROPHY", "\U0001F947 **`[FRANCHISE]`** finishes with the best regular-season record.", "BLHA RECORDS DEPARTMENT",
     [("RECORD", "`[W-L-T]` • `[POINTS FOR]`"), ("PRIZE", "$200"),
      ("TIEBREAKER USED", "`[NONE / POINTS SCORED / HEAD-TO-HEAD / FANTRAX / RANDOM DRAW]`")], RECORD)
tmpl("league-office/72_dynasty_pot_won.json", "DYNASTY POT WON", "**`[FRANCHISE]`** wins its third BLHA Championship in the active cycle and takes the entire Dynasty Pot.", "BLHA RECORDS DEPARTMENT",
     [("PAYOUT", "**`$[AMOUNT]`**"), ("CHAMPIONSHIPS", "`[SEASONS WON]`"),
      ("CYCLE RESET", "The pot returns to zero and every franchise's counter resets. A new cycle starts with Season `[YEAR]`.")], RECORD)

# ------------------------------------------------------------------ trade center
tmpl("trade-center/90_trade_completed.json", "TRADE COMPLETED", "Processed in Fantrax on `[DATE]`.", "BLHA TRADE CENTER",
     [("`[FRANCHISE A]` RECEIVES", "`[PLAYERS / PICKS / FAAB]`"), ("`[FRANCHISE B]` RECEIVES", "`[PLAYERS / PICKS / FAAB]`"),
      ("PREPAYMENT", "`[NOT REQUIRED / CONFIRMED IN LEAGUE-LEDGER ON DATE]`")])

# -------------------------------------------------------- community and traditions
tmpl("league-office/36_calendar_sync.json", "ADD THE LEAGUE CALENDAR TO YOUR PHONE", "Every BLHA date can live in the calendar you already use.", "BLHA LEAGUE CALENDAR",
     [("HOW", "Type `/link` in any channel. Sesh replies privately with a calendar feed link."),
      ("THEN", "Add that link to Google Calendar (Other calendars → From URL), Apple Calendar (File → New Calendar Subscription) or Outlook (Add calendar → From internet)."),
      ("WHAT YOU GET", "Draft night, deadlines and owners' meetings appear on your phone and update on their own when a date changes.")])
tmpl("league-office/35_winter_meetings.json", "BLHA WINTER MEETINGS", "The yearly owners' meeting, held in the Offseason before the amendment window opens.", "BLHA LEAGUE CALENDAR",
     [("WHEN", "**`[TIMESTAMP]`** • RSVP on the Sesh event in **league-calendar**"),
      ("WHERE", "`[VOICE CHANNEL]`"),
      ("AGENDA", "Season review • Ideas from **league-suggestions** that could become amendment proposals (Article XX) • Draft and calendar dates • Open floor"),
      ("CAN'T MAKE IT", "Notes are posted in **gm-lounge** afterward. Nothing is decided at the meeting itself: rule changes still go through a written proposal and a vote.")])
tmpl("league-office/26_awards_night.json", "BLHA AWARDS NIGHT", "Season `[YEAR]` ballots are open. Owners choose the winners.", "BLHA RECORDS DEPARTMENT",
     [("THE AWARDS", "**GM of the Year** • **Trade of the Year** • **Waiver Wire Award** (best pickup) • **Rookie GM of the Year** (first-season owners) • **Cold Beer Award** (the season's funniest moment)"),
      ("HOW TO VOTE", "One Discord poll per award in **gm-lounge**, open until **`[TIMESTAMP]`**. One vote per owner per award. Please don't vote for yourself."),
      ("RESULTS", "Winners are announced in **hall-of-champions** and kept in the league records."),
      ("JUST FOR FUN", "Awards carry no money and change nothing in the standings or the draft.")], RECORD)
tmpl("league-office/27_award_winners.json", "BLHA AWARDS NIGHT: THE WINNERS", "Season `[YEAR]`, as voted by the owners.", "BLHA RECORDS DEPARTMENT",
     [("GM OF THE YEAR", "`[FRANCHISE / OWNER]`"), ("TRADE OF THE YEAR", "`[TRADE AND DATE]`"),
      ("WAIVER WIRE AWARD", "`[PLAYER, FRANCHISE]`"), ("ROOKIE GM OF THE YEAR", "`[OWNER]`"),
      ("COLD BEER AWARD", "`[THE MOMENT]`")], RECORD)
tmpl("league-office/28_wooden_spoon_proposal.json", "NEW TRADITION? THE WOODEN SPOON", "A just-for-fun tradition for the last-place team. Owners decide whether we do it.", f"{LO} • DISCUSSION",
     [("THE IDEA", "The franchise that finishes last in the regular season holds the **Wooden Spoon** role for the Offseason and writes a short preview of the next Season, posted before Week 1."),
      ("WHAT IT ISN'T", "No money and no rule change. Draft order still comes from Potential Points (14.5), so the Spoon can't be chased."),
      ("HAVE YOUR SAY", "React 👍 or 👎 by **`[TIMESTAMP]`**, or reply in **gm-lounge**. It starts only if owners want it.")])
tmpl("league-office/29_wooden_spoon_awarded.json", "THE WOODEN SPOON", "**`[FRANCHISE]`** finishes last in Season `[YEAR]` and takes home the Spoon.", "BLHA RECORDS DEPARTMENT",
     [("THE TRADITION", "`[OWNER]` holds the Wooden Spoon role for the Offseason and writes the Season `[NEXT YEAR]` preview, posted before Week 1."),
      ("NO PENALTY", "Draft order is unaffected: it comes from Potential Points (14.5).")], RECORD)
tmpl("league-office/63_league_bot_launch.json", "MEET THE BLHA LEAGUE BOT", "League tools, right in Discord. Every command reads Fantrax and the Constitution; nothing here changes Fantrax.", f"{LO} • OFFICIAL NOTICE",
     [("YOUR TEAM", "`/myteam` shows your roster counts, picks you own, how far your dues are paid and this Week's matchup. Only you see it."),
      ("RULES", "`/rule 12.4` or `/rule prepayment` shows the Constitution's text. `/deadlines` lists the next dates."),
      ("PLAYERS AND TRADES", "`/minor` checks a player's minors eligibility. `/tradecheck` checks a trade against the rules (picks, prepayment, roster limits, the deadline). It never grades a trade."),
      ("PICK'EM", "Each Week the bot posts the matchups in **game-day**. Make your picks before the Week starts; a season leaderboard keeps score."),
      ("VOTING", "Proposals and official votes run through the bot in **league-voting**, one vote per franchise (Article XX).")])

# ------------------------------------------------------------------- bundles
BUNDLES = {
    "01_Announcements": ["league-office/20_announcement_standard.json", "league-office/21_announcement_action_required.json",
                         "league-office/22_announcement_urgent_deadline.json", "league-office/23_season_opening.json",
                         "league-office/24_season_closing.json", "league-office/13_clerical_correction.json"],
    "02_Calendar": ["league-office/30_calendar_event.json", "league-office/31_calendar_deadline_reminder.json",
                    "league-office/32_calendar_published.json", "league-office/33_calendar_date_change.json",
                    "league-office/35_winter_meetings.json", "league-office/36_calendar_sync.json"],
    "03_Ledger": ["league-office/40_ledger_season_summary.json", "league-office/41_ledger_dues_status.json",
                  "league-office/42_ledger_prize_pool.json", "league-office/43_ledger_payment_confirmed.json",
                  "league-office/44_ledger_prize_payout.json", "league-office/45_ledger_dynasty_pot.json"],
    "04_Voting": ["league-office/50_vote_proposal_open.json", "league-office/51_vote_open.json", "league-office/52_vote_result.json"],
    "05_Constitution_and_Rulings": ["league-office/10_constitution_new_version.json", "league-office/11_constitution_amendment.json",
                                    "league-office/12_rules_ruling.json", "league-office/14_recusal_notice.json", "league-office/15_appeal_outcome.json"],
    "06_Honors_and_Records": ["league-office/70_champion_crowned.json", "league-office/71_presidents_trophy.json", "league-office/72_dynasty_pot_won.json"],
    "07_Ownership": ["league-office/60_owner_welcome.json", "league-office/61_franchise_orphaned.json", "league-office/62_commissioner_transition.json"],
    "08_Trades": ["trade-center/90_trade_completed.json"],
    "09_Community_and_Traditions": ["league-office/26_awards_night.json", "league-office/27_award_winners.json",
                                    "league-office/28_wooden_spoon_proposal.json", "league-office/29_wooden_spoon_awarded.json",
                                    "league-office/63_league_bot_launch.json"],
}

def message(path: Path) -> dict:
    """Load one template and confirm it is a single message in the BLHA format."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rel = path.relative_to(T).as_posix()
    errors = fmt.problems(data["embeds"], fmt.header_url(rel), rel)
    if errors:
        raise SystemExit(f"{rel}: {'; '.join(errors)} (run normalize_discohook_templates.py first)")
    return data


def link(messages: list[dict]) -> str:
    raw = json.dumps({"messages": [{"data": m} for m in messages]}, ensure_ascii=True, separators=(",", ":")).encode()
    return "https://discohook.org/?data=" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    links: dict[str, str] = {}
    for name, files in BUNDLES.items():
        msgs = [message(T / f) for f in files]
        (OUT / f"BLHA_Templates_{name}.json").write_text(
            json.dumps({"messages": [{"data": m} for m in msgs]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        links[f"bundle:{name}"] = link(msgs)
    for p in sorted(T.rglob("*_channel_intro.json")):
        links[f"intro:{p.relative_to(T).as_posix()}"] = link([message(p)])
    welcome = message(T / fmt.WELCOME)
    (OUT / "BLHA_Welcome_Single_Message.json").write_text(json.dumps(welcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    links["welcome"] = link([welcome])
    for p in sorted((T / "constitution").glob("*.json")):
        links[f"constitution:{p.name}"] = link([message(p)])
    (OUT / "links.json").write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
    biggest = max(len(v) for v in links.values())
    print(f"{len(BUNDLES)} bundles, {len(links)} links, longest link {biggest} chars")


if __name__ == "__main__":
    main()
