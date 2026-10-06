#!/usr/bin/env python3
"""Generate the per-channel intro Discohook templates (one JSON per channel).

Channel names follow the live server. Rules references use the Constitution
article numbers in tools/constitution_source.py. Each intro is written
in the BLHA format from discohook_format.py: one message, header banner first,
footer text and divider on the final embed only. The normalizer re-checks it:

    python3 tools/build_channel_intros.py && python3 tools/normalize_discohook_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discohook_format as fmt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "templates"
GOLD = 16758812

NEWS = "BLHA NEWS DESK"
COMP = "BLHA COMPETITION DESK"
LO = "BLHA LEAGUE OFFICE"
GM = "BLHA GENERAL MANAGERS"
TC = "BLHA TRADE CENTER"
SD = "BLHA SCOUTING DEPARTMENT"
WW = "BLHA WAIVER WIRE"
CO = "BLHA COMMISSIONER'S OFFICE"
DC = "BLHA DRAFT CENTER"
HQ = "BLHA FRANCHISE HQ"

AUTO = ("Stories are posted by automation as a headline, a source name and a direct link. Full articles are never copied; "
        "open the link to read the source.")
FANTRAX = "Fantrax is the authoritative record. If a Discord post and Fantrax ever differ, Fantrax wins."

items: dict[str, dict] = {}


def card(path: str, title: str, desc: str, footer: str, fields: list[tuple[str, str]]) -> None:
    items[path] = {"embeds": [{
        "title": title,
        "description": desc,
        "color": GOLD,
        "footer": {"text": footer},
        "fields": [{"name": n, "value": v, "inline": False} for n, v in fields],
    }]}


def more(path: str, title: str, desc: str, footer: str, fields: list[tuple[str, str]]) -> None:
    """Add another card to the same message (still one send)."""
    items[path]["embeds"].append({
        "title": title,
        "description": desc,
        "color": GOLD,
        "footer": {"text": footer},
        "fields": [{"name": n, "value": v, "inline": False} for n, v in fields],
    })


# ------------------------------------------------------------------ League Office
card("league-office/01_constitution_channel_intro.json", "BLHA CONSTITUTION",
     "The Constitution is the controlling rules document of the Beer League Hockey Association. Every owner accepts it as a condition of joining and is responsible for knowing it.", LO,
     [("CURRENT DOCUMENT", "**Edition:** Charter Edition\n**Effective:** Season 2027 (inaugural season 2027–28)\n**Last amended:** Not yet amended"),
      ("HOW DATES WORK", "The Constitution defines deadlines by formula. Exact dates for each season are published in **league-calendar** within 14 days after the NHL releases its schedule."),
      ("CHANGING THE RULES", "Material Amendments need 8 of 12 franchise votes, are held only in the offseason, and must pass before the dues deadline of the season they first apply to (Article XX). The first amendment vote can happen after Season 2027."),
      ("HOW TO USE THIS CHANNEL", "The current Constitution, adopted amendments and the amendment history live here. Questions about what a rule means go to **rules-questions**."),
      ("AUTHORITY", "Fantrax controls gameplay records and transactions. The Constitution controls league rules and governance. The newest published version controls.")])
card("league-office/02_announcements_channel_intro.json", "OFFICIAL BLHA ANNOUNCEMENTS",
     "This channel is the official notice board of the Beer League Hockey Association. Managers are responsible for monitoring it.", LO,
     [("POSTED HERE", "Deadlines • Season notices • Calendar changes • Commissioner instructions • League-wide action items"),
      ("NOT POSTED HERE", "General discussion, trade talk, scouting chatter or routine questions."),
      ("RULES CHANGES", "Rules change only through the process in Article XX of the Constitution. An announcement never changes a rule by itself.")])
card("league-office/03_calendar_channel_intro.json", "BLHA LEAGUE CALENDAR",
     "Official dates and deadlines for the current BLHA season.", LO,
     [("TRACKED HERE", "Draft dates • Dues deadline • Trade deadline and reopening • Roster deadlines • Playoff weeks • Offseason milestones"),
      ("HOW DATES ARE SET", "The Constitution gives each date as a formula, such as \"end of Week 20\" or \"14 to 21 days after the NHL Entry Draft\". The calendar turns those formulas into exact dates. If the two ever disagree, the formula wins (Article V)."),
      ("CHANGES", "A published date changes only when the NHL schedule, a platform limitation or events outside the league's control require it, with at least 7 days' notice where possible. Deadlines may be extended but are not moved earlier unless the NHL schedule forces it."),
      ("TIME STANDARD", "Unless a post states otherwise, all times are **Eastern Time**.")])
# The Sesh reminder steps travel in the same message as the calendar intro.
more("league-office/03_calendar_channel_intro.json", "GET EVENT REMINDERS FROM SESH",
     "League events on this calendar run through **Sesh**. Sesh reminds you by direct message, so it only works if Discord lets Sesh message you. One-time setup, about a minute.",
     "BLHA LEAGUE CALENDAR",
     [("1. ALLOW DMS FROM THIS SERVER",
       "**Desktop:** click the server name at the top left, choose **Privacy Settings**, and turn on **Direct Messages**.\n"
       "**Phone:** tap your profile picture, then the gear, then **Messaging Permissions** (older apps: **Content & Social** or **Privacy & Safety**). "
       "Under server settings, pick this server and turn on **Direct messages**."),
      ("2. RSVP TO THE EVENT", "Press **Attending** (or your answer) on the event post in this channel. Sesh sends you a confirmation DM right away."),
      ("3. PICK YOUR REMINDER", "In that DM, choose when Sesh should remind you. Reminders are set one event at a time."),
      ("NO DM FROM SESH?",
       "Look in **Message Requests** (and its **Spam** tab) at the top of your DM list and accept Sesh. "
       "Still nothing? Send Sesh the command `/settings` in a DM, or open **sesh.fyi/dashboard**, click your name, then **Preferences**, "
       "and turn on **Event RSVP Confirmation DMs**. Sesh also needs you to stay in this server and not block it."),
      ("TO STOP", "Change your RSVP or the reminder in the Sesh DM. Turning off Event RSVP Confirmation DMs stops every Sesh reminder.")])
card("league-office/04_ledger_channel_intro.json", "BLHA LEAGUE LEDGER",
     "Public league-level accounting for dues, league expenses, prizes and the Dynasty Pot.", LO,
     [("POSTED HERE", "Payment confirmations • Dues status • Future-season prepayments • Prize payouts • Dynasty Pot balance • The Season Ledger"),
      ("A PAYMENT COUNTS WHEN", "The Commissioner has confirmed it and recorded it here (Article III). A future 1st- or 2nd-round pick trade made before the required prepayment is confirmed here is reversed (Article XII)."),
      ("SEASON LEDGER", "Within 30 days after the BLHA Championship concludes, the Commissioner posts dues received, prizes paid, operating reserve spending, the League Services Allocation and the Dynasty Pot balance."),
      ("PRIVACY", "Do **not** post payment credentials, account numbers, login details or sensitive personal financial information.")])
card("league-office/05_voting_channel_intro.json", "BLHA LEAGUE VOTING",
     "Formal franchise votes are recorded here.", LO,
     [("ONE FRANCHISE = ONE VOTE", "Each franchise casts one vote, whether it has one owner or several. Co-owners may discuss proposals but do not create an additional vote."),
      ("THE RULES OF A VOTE", "Material Amendments need **8 of 12** affirmative votes. Votes happen only in the offseason, last 7 days, and follow a proposal posted at least 7 days earlier. Non-votes are not affirmative votes (Article XX)."),
      ("A VALID VOTE POST STATES", "The proposal • Voting options • Opening time • Closing time • Threshold required • Final result"),
      ("DISCUSSION", "Debate proposals in **gm-lounge**. This channel is for the proposal and the recorded vote.")])
card("league-office/06_hall_of_champions_channel_intro.json", "BLHA HALL OF CHAMPIONS",
     "The permanent record of every BLHA champion.", LO,
     [("POSTED HERE", "Championship announcements • Champion history • Presidents' Trophy winners • Third-place finishers • Dynasty Pot standings"),
      ("DYNASTY POT", "The first franchise to win three BLHA Championships in the same active cycle wins the entire pot. Championships belong to the franchise, not the owner (Article IV)."),
      ("PERMANENT RECORD", "This channel is the lasting history of the league. Questions about an entry go to the League Office.")])
card("league-office/07_league_records_channel_intro.json", "BLHA LEAGUE RECORDS",
     "The permanent record of league history, milestones and achievements.", LO,
     [("POSTED HERE", "League records • Milestones • Season-by-season history • Constitution amendment history"),
      ("PERMANENT RECORD", "Records are posted by the League Office. Questions about an entry go to the League Office.")])

# ------------------------------------------------------------------------ The Wire
card("the-wire/01_breaking_news_channel_intro.json", "BLHA BREAKING NEWS",
     "High-impact NHL news that may change a roster decision right now. " + AUTO, NEWS,
     [("POSTED HERE", "Season-ending or indefinite injuries • Retirements • Indefinite suspensions • Firings • Major blockbuster trades"),
      ("HOW A STORY QUALIFIES", "It must come from a trusted primary source and describe a high-impact event. Ordinary signings, depth trades and routine roster moves go to other channels."),
      ("NOT POSTED HERE", "Rumors, opinion pieces, predictions, game threads or discussion. Talk it over in **news-desk**.")])
card("the-wire/02_nhl_news_channel_intro.json", "BLHA NHL NEWS",
     "The league-wide hockey news feed: reporting worth knowing that doesn't belong in a specialty channel. " + AUTO, NEWS,
     [("POSTED HERE", "Team and league developments • Coaching and front-office changes • Captaincy news • Interviews • Meaningful analysis"),
      ("FILTERED OUT", "Scores, routine highlights, daily discussion threads and feed-section labels."),
      ("LOOKING FOR SOMETHING ELSE?", "Injuries go to **injury-report**, signings and trades to **nhl-transactions**, prospects to **prospect-wire**, and major news to **breaking-news**.")])
card("the-wire/03_injury_report_channel_intro.json", "BLHA INJURY REPORT",
     "Injury updates across the NHL. " + AUTO, NEWS,
     [("POSTED HERE", "New injuries • Day-to-day, week-to-week and long-term updates • Injured reserve moves • Surgeries and concussions • Returns and activations"),
      ("OWNER ALERTS", "The wire checks injury stories against BLHA rosters. An owner who has opted in is mentioned when one of their own players appears, and only for their own players."),
      ("MAJOR INJURIES", "A season-ending or indefinite injury may be posted in **breaking-news** instead.")])
card("the-wire/04_nhl_transactions_channel_intro.json", "BLHA NHL TRANSACTIONS",
     "Real-NHL roster moves. These are not BLHA transactions. " + AUTO, NEWS,
     [("POSTED HERE", "Trades • Signings and extensions • Waivers and claims • Recalls and call-ups • Assignments and loans"),
      ("BLHA TRANSACTIONS", "Moves inside your BLHA franchise happen in Fantrax, and Fantrax is the official record. League trade talk belongs in the Trade Center."),
      ("ROUTINE MOVES", "Routine moves post here. Major trades and major news may appear in **breaking-news** instead.")])
card("the-wire/05_prospect_wire_channel_intro.json", "BLHA PROSPECT WIRE",
     "Development news for dynasty owners who look beyond this season. " + AUTO, NEWS,
     [("POSTED HERE", "AHL and rookie news • NCAA and college hockey • CHL, OHL, WHL and QMJHL • Junior and international events • Development camps • NHL Draft prospects • World Juniors"),
      ("DISCUSSION", "Use the **scouting** forum to talk about prospects, draft rankings and trade targets.")])
card("the-wire/06_news_desk_channel_intro.json", "BLHA NEWS DESK",
     "The discussion room for everything the wire posts. No automation posts here, so conversation stays readable.", NEWS,
     [("USE THIS ROOM FOR", "Reactions to news • Injury impact • Player outlook • General hockey talk"),
      ("FEEDS", "breaking-news • nhl-news • injury-report • nhl-transactions • prospect-wire"),
      ("GUIDELINES", "Link the story you're discussing. Keep rumors labeled as rumors. Anything official goes through the League Office.")])

# -------------------------------------------------------------- General Managers
card("general-managers/01_gm_lounge_channel_intro.json", "BLHA GM LOUNGE",
     "The clubhouse. This is where general managers talk hockey, discuss league business and enjoy the league.", GM,
     [("USE THIS ROOM FOR", "League talk • Proposal discussion before a vote • Hockey conversation • Getting to know your fellow owners"),
      ("OTHER ROOMS", "**game-day** for live games • **chirps-and-memes** for trash talk • **off-topic** for everything else • **media** for clips and photos"),
      ("NOT FOR OFFICIAL BUSINESS", "Votes, rulings, trades and deadlines belong in their own rooms. Nothing said in the lounge changes a rule or a result.")])
card("general-managers/02_game_day_channel_intro.json", "BLHA GAME DAY",
     "Live reaction for NHL game nights and BLHA matchups.", GM,
     [("USE THIS ROOM FOR", "Live game chat • Matchup swings • Goalie-start watching • Late-night lineup panic"),
      ("KEEP IT READABLE", "Spoiler courtesy goes a long way. Use **news-desk** for deeper discussion of a story.")])
card("general-managers/03_chirps_and_memes_channel_intro.json", "BLHA CHIRPS AND MEMES",
     "Friendly trash talk and hockey humor.", GM,
     [("KEEP IT GOOD", "Chirp the team, not the person. Keep it fun and respectful, and remember everyone here is a co-owner of the league."),
      ("NOT HERE", "Rule disputes, trade negotiations or anything that needs a ruling. Take those to the Commissioner's Office.")])
card("general-managers/04_off_topic_channel_intro.json", "BLHA OFF TOPIC",
     "Everything that isn't hockey or league business.", GM,
     [("USE THIS ROOM FOR", "Other sports • Food and drink • Movies, games and music • Life outside the league"),
      ("HOUSE RULES", "Server-wide conduct rules still apply. Keep it friendly.")])
card("general-managers/05_media_channel_intro.json", "BLHA MEDIA",
     "Clips, highlights, photos and graphics.", GM,
     [("POSTED HERE", "Highlight clips • Game photos • Franchise graphics and logos • Anything worth sharing visually"),
      ("PLEASE", "Credit the source where you can, and keep conversation in the matching discussion channel.")])

# ------------------------------------------------------------------- Trade Center
TRADE_RULES = ("TRADE RULES", "Trades are unlimited and are not subject to a league vote. The deadline is the end of Week 20 and trading reopens the day after the Stanley Cup Final (Article XI). Future 1st- and 2nd-round pick trades require prepayment (Article XII).")
OFFICIAL = ("OFFICIAL RECORD", "A trade is official only when it is processed in Fantrax. Posts here don't bind anyone.")
card("trade-center/01_trade_block_channel_intro.json", "BLHA TRADE BLOCK",
     "Players and picks you're willing to move.", TC,
     [("POST FORMAT", "Name the player or pick, say what you're hoping to get back, and note any deadline."),
      ("ALLOWED IN TRADES", "Rostered players, eligible draft picks and current-season FAAB. Cash, loans, rentals, predetermined tradebacks and conditional picks are prohibited."), OFFICIAL])
card("trade-center/02_looking_to_acquire_channel_intro.json", "BLHA LOOKING TO ACQUIRE",
     "Players, picks and positions you're hunting for.", TC,
     [("POST FORMAT", "Say what you want and what you can offer so owners can answer quickly."),
      ("TIP", "Check **trade-block** first, since the player you want may already be listed."), OFFICIAL])
card("trade-center/03_trade_discussion_channel_intro.json", "BLHA TRADE DISCUSSION",
     "Open talk about trade ideas, valuations and strategy.", TC,
     [("USE THIS ROOM FOR", "Negotiating • Comparing offers • Rebuild vs. contend strategy • Pick valuations"),
      TRADE_RULES, OFFICIAL])
card("trade-center/04_completed_trades_channel_intro.json", "BLHA COMPLETED TRADES",
     "The public record of trades that have been processed.", TC,
     [("POSTED HERE", "Completed trades only: the franchises involved and every player, pick and FAAB amount that moved."),
      ("BEFORE YOU POST", "Post after Fantrax has processed the trade. A future 1st- or 2nd-round pick trade needs the seller's prepayment confirmed in **league-ledger** first, or the Commissioner reverses it (Article XII)."), OFFICIAL])
card("trade-center/05_player_values_channel_intro.json", "BLHA PLAYER VALUES",
     "Dynasty values, rankings and trade-value discussion.", TC,
     [("USE THIS ROOM FOR", "Dynasty rankings • Value charts • Pick values • Risers and fallers"),
      ("REMEMBER", "Values are opinions. A trade isn't reversible just because someone believes one side received more value (Article XI).")])

# --------------------------------------------------------------------- Scouting
MINORS = ("MINOR-LEAGUE RULES", "Minor-league spots are for players 25 or younger on NHL opening day (per Fantrax's age calculation) with 100 or fewer career NHL games (50 for goalies). Details are in Article VII.")
card("scouting/01_scouting_channel_intro.json", "BLHA SCOUTING",
     "One forum for every prospect: college, juniors, Europe, the AHL, the NHL Draft and the BLHA draft.", SD,
     [("HOW IT WORKS", "Make one post per player or topic, and search before you post so each prospect keeps one thread. Add tags for the league, the player's status and position."),
      ("TAGS", "**League:** NCAA • CHL • AHL • EUROPE/INTL • NHL DRAFT\n**Status:** TOP PROSPECT • SLEEPER • RISER • FALLER • NHL READY • LONG SHOT\n**Position:** FORWARD • DEFENSE • GOALIE\n**BLHA draft:** BLHA DRAFT • RANKINGS • MOCK DRAFT"),
      MINORS,
      ("THE BLHA DRAFT", "5 rounds, linear order, starting 14 to 21 days after the NHL Entry Draft; the first Annual Draft is in 2028. The pool is any unowned player who qualifies for a minor-league spot, not just the NHL Draft class (Article XIV). Official draft notices are in the Draft Center."),
      ("NEWS FEED", "Automated prospect news appears in **prospect-wire**. Come here to talk about what it means.")])

# ------------------------------------------------------------------- Waiver Wire
card("waiver-wire/01_waiver_talk_channel_intro.json", "BLHA WAIVER TALK",
     "FAAB strategy, waiver timing and recently dropped players worth a claim.", WW,
     [("THE RULES", "$1,000 FAAB per season, $0 bids allowed, $1 increments, hidden bids, daily processing at about 11:00 AM ET (Article X). FAAB does not roll over."),
      ("CONSOLATION BONUS", "The consolation-bracket champion gets a $50 FAAB bonus next season. Current-season FAAB can be traded (Article XI)."),
      ("RECENTLY DROPPED", "Spot a useful player who just hit the pool? Post him here. Players worth a longer look get their own post in **waiver-watch**."),
      ("OFFICIAL CLAIMS", "Actual claims stay in Fantrax. Discord never submits or changes a claim.")])
card("waiver-wire/02_waiver_watch_channel_intro.json", "BLHA WAIVER WATCH",
     "Players worth watching before the next waiver run.", WW,
     [("USE THIS ROOM FOR", "Breakout candidates • Call-ups • Goalie opportunities • Streaming targets"),
      ("ACQUISITION LIMIT", "Up to 5 acquisitions per normal fantasy week. The two-week championship counts as two separate weeks (Article X).")])

# -------------------------------------------------------------- League Competition
DISCUSS = ("DISCUSSION", "Owners can react here but not post. Talk about it in **gm-lounge** or **chirps-and-memes**.")
card("league-competition/01_scoreboard_channel_intro.json", "BLHA SCOREBOARD",
     "Live matchup results for the current week, posted by the BLHA Competition Desk and read directly from Fantrax.", COMP,
     [("POSTED HERE", "Weekly matchup previews • Matchup scoreboards during the week • Final scoreboards when a week ends"),
      ("OFFICIAL RESULTS", FANTRAX), ("DISCUSSION", "Matchup talk and trash talk belong in **gm-lounge** and **chirps-and-memes**.")])
card("league-competition/02_standings_channel_intro.json", "BLHA STANDINGS",
     "League standings after each completed week, posted by the BLHA Competition Desk from Fantrax data.", COMP,
     [("POSTED HERE", "Weekly standings • Playoff cut line • Final regular-season standings"),
      ("TIEBREAKERS", "Points scored, then head-to-head among the tied teams, then the next Fantrax tiebreaker, then a recorded random draw (Article XV)."),
      ("OFFICIAL RESULTS", "Fantrax is the authoritative record. These posts are a convenient copy of it.")])
card("league-competition/04_weekly_recap_channel_intro.json", "BLHA WEEKLY RECAP",
     "The results of every completed matchup, posted after each fantasy week ends, normally on Monday morning.", COMP,
     [("POSTED HERE", "Completed matchup results for the week • Recap of how each week finished"),
      ("OFFICIAL RESULTS", "Results are pulled directly from Fantrax. Questions about a score go to the Commissioner's Office."),
      DISCUSS])
card("league-competition/05_playoff_race_channel_intro.json", "BLHA PLAYOFF RACE",
     "The late-season picture: who is in, who is on the bubble and what each team needs.", COMP,
     [("POSTED HERE", "Teams above and below the playoff cut line • Bubble teams • Updates through Week 22"),
      ("THE FIELD", "Six teams make the playoffs and the top two seeds get byes (Article XVI)."),
      ("WHEN IT STARTS", "These posts begin late in the regular season. Until then the channel stays quiet."),
      DISCUSS])
card("league-competition/06_playoffs_channel_intro.json", "BLHA PLAYOFFS",
     "Playoff matchups and results, posted by the BLHA Competition Desk.", COMP,
     [("THE FORMAT", "Quarterfinals and Semifinals are one week each, and the BLHA Championship is a two-week cumulative matchup. Brackets reseed after each round. The Semifinal losers play for third place (Article XVI)."),
      ("POSTED HERE", "Playoff matchups • Round results • Third-place game • Champion announcement"),
      ("OFFICIAL RESULTS", "Fantrax is the authoritative record. Rulings on playoff questions come from the League Office."),
      DISCUSS])
card("league-competition/07_consolation_bracket_channel_intro.json", "BLHA CONSOLATION BRACKET",
     "The bracket for the six franchises that miss the playoffs.", COMP,
     [("THE FORMAT", "Same structure as the playoffs, played in the same weeks, seeded by regular-season standings among non-playoff teams (Article XVI)."),
      ("THE PRIZE", "The consolation champion receives a **$50 FAAB bonus** for the following season (Article X)."),
      ("WHAT IT DOESN'T CHANGE", "Consolation results do not change annual draft order, standings or the Presidents' Trophy."),
      DISCUSS])

# --------------------------------------------------------------- Commissioner's Office
card("commissioners-office/01_commissioner_support_channel_intro.json", "BLHA COMMISSIONER SUPPORT",
     "Open a private ticket for anything that shouldn't be handled in public.", CO,
     [("USE THIS ROOM FOR", "Disputes • Complaints • Payment questions • Roster or platform problems"),
      ("TIMING", "A request to review a material Commissioner ruling must be made within 48 hours of the ruling (Article XIX)."),
      ("PRIVACY", "Never post passwords, payment credentials or account numbers.")])
card("commissioners-office/02_rules_questions_channel_intro.json", "BLHA RULES QUESTIONS",
     "Ask how a rule works. Check the Constitution first.", CO,
     [("HOW IT WORKS", "Ask here so the answer helps everyone. Include the situation and the Article you're looking at."),
      ("OFFICIAL RULINGS", "Binding answers are posted in **rulings-log**. A casual reply in this channel is not a ruling.")])
card("commissioners-office/03_league_suggestions_channel_intro.json", "BLHA LEAGUE SUGGESTIONS",
     "Ideas for improving the league.", CO,
     [("HOW IT WORKS", "Post an idea and discuss it. A suggestion can become a formal amendment proposal."),
      ("THE PROCESS", "Material Amendments are proposed in writing, posted at least 7 days before voting, and approved by 8 of 12 votes in the offseason (Article XX).")])
card("commissioners-office/04_rulings_log_channel_intro.json", "BLHA RULINGS LOG",
     "The permanent record of Commissioner rulings, recusals and appeal outcomes.", CO,
     [("POSTED HERE", "Official rulings • Recusal decisions • Appeal outcomes (Article XIX)"),
      ("APPEALS", "A directly affected franchise may request review within 48 hours by opening an Appeal ticket in **open-a-ticket** (Section 19.4). A panel of three unaffected owners, drawn at random, decides by majority within 7 days.")])

# ------------------------------------------------------------------- Draft Center
card("draft-center/01_draft_announcements_channel_intro.json", "BLHA DRAFT ANNOUNCEMENTS",
     "Official draft notices. Fantrax remains the authoritative platform for actual selections.", DC,
     [("POSTED HERE", "Draft date and start time • Order • Pick-clock and pause rules • Roster-compliance deadline"),
      ("DATES", "Drafts begin 14 to 21 days after the NHL Entry Draft and are announced at least 30 days ahead (Articles V, XIII and XIV)."),
      ("ON THE CLOCK", "Fantrax alerts each manager when it's their pick, so Discord doesn't repeat those alerts. Round results are posted in **draft-results**.")])
card("draft-center/03_draft_room_channel_intro.json", "BLHA DRAFT ROOM",
     "Live discussion while the draft runs.", DC,
     [("USE THIS ROOM FOR", "Reactions • Pick talk • Draft banter"),
      ("DRAFT QUEUES", "Maintain a Fantrax queue so a timeout never costs you a pick (Articles XIII and XIV).")])
card("draft-center/04_draft_day_trades_channel_intro.json", "BLHA DRAFT DAY TRADES",
     "Trades made while the draft is running.", DC,
     [("POSTED HERE", "Draft-day trades once processed in Fantrax"),
      ("PICK TRADES", "Future 1st- and 2nd-round pick trades require confirmed prepayment before they become final (Article XII).")])
card("draft-center/05_draft_results_channel_intro.json", "BLHA DRAFT RESULTS",
     "The pick-by-pick record and final board.", DC,
     [("POSTED HERE", "Pick results • Round summaries • Final draft board"),
      ("OFFICIAL RECORD", FANTRAX)])

# --------------------------------------------------------------------- Franchise HQ
card("franchise-hq/01_franchise_directory_channel_intro.json", "BLHA FRANCHISE DIRECTORY",
     "Every franchise, its owners and who holds its vote.", HQ,
     [("LISTED HERE", "Franchise name • Owner and co-owners • Which owner casts the franchise vote"),
      ("ONE FRANCHISE, ONE VOTE", "Co-owners share one dues obligation and one formal vote (Articles II and III).")])
card("franchise-hq/02_franchise_news_channel_intro.json", "BLHA FRANCHISE NEWS",
     "News from each franchise.", HQ,
     [("POSTED HERE", "Franchise announcements • Roster changes worth sharing • Branding and identity updates"),
      ("OFFICIAL BUSINESS", "Votes, trades and rulings stay in the League Office, the Trade Center and Fantrax.")])
card("franchise-hq/03_roster_showcase_channel_intro.json", "BLHA ROSTER SHOWCASE",
     "Show off your team and your prospect pipeline.", HQ,
     [("POSTED HERE", "Roster snapshots • Prospect stashes • Draft-pick hauls"),
      ("FANTRAX FIRST", "Fantrax is the live roster. Showcase posts are a snapshot.")])


def main() -> None:
    # remove superseded combined intros
    for rel in (
        "league-office/06_champions_channel_intro.json", "league-office/07_records_channel_intro.json",
        "trade-center/01_trade_center_channel_intro.json", "scouting/01_scouting_department_channel_intro.json",
        "waiver-wire/01_waiver_wire_channel_intro.json", "commissioners-office/01_commissioners_office_channel_intro.json",
        "franchise-hq/01_franchise_hq_channel_intro.json", "draft-center/06_draft_center_intro.json",
        "league-competition/03_weekly_recap_channel_intro.json", "league-competition/04_playoff_race_channel_intro.json",
        "league-competition/05_playoffs_channel_intro.json",
        # Oct 2026 channel consolidation: one Scouting forum, two Waiver Wire
        # channels, no power rankings or on-the-clock channel.
        "scouting/01_prospect_scouting_channel_intro.json", "scouting/02_ncaa_hockey_channel_intro.json",
        "scouting/03_chl_juniors_channel_intro.json", "scouting/04_international_prospects_channel_intro.json",
        "scouting/05_ahl_watch_channel_intro.json", "scouting/06_draft_board_channel_intro.json",
        "scouting/07_annual_draft_channel_intro.json", "waiver-wire/01_faab_talk_channel_intro.json",
        "waiver-wire/03_adds_and_drops_channel_intro.json", "waiver-wire/04_recently_dropped_channel_intro.json",
        "league-competition/03_power_rankings_channel_intro.json", "draft-center/02_on_the_clock_channel_intro.json",
        # Oct 2026: the Sesh reminder steps are part of the calendar intro message.
        "league-office/34_calendar_sesh_reminders.json",
    ):
        p = ROOT / rel
        if p.exists():
            p.unlink()
    for rel, data in items.items():
        banner = fmt.header_url(rel)
        data = {"embeds": fmt.apply(data["embeds"], banner, rel)}
        errors = fmt.problems(data["embeds"], banner, rel)
        assert not errors, (rel, errors)
        for e in data["embeds"]:
            assert len(e.get("description") or "") <= 4096, rel
            assert all(len(f["value"]) <= 1024 for f in e.get("fields") or []), rel
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(items)} channel intro templates.")


if __name__ == "__main__":
    main()
