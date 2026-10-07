#!/usr/bin/env python3
"""Single source of truth for the BLHA Constitution text.

Everything published from the constitution (Discohook messages, Markdown copy,
PDF) is generated from this file by tools/build_constitution.py. Edit the text
here, rebuild, and every format stays in sync.

Text conventions:
- **bold** is the only inline markup.
- Sections are numbered automatically (article.section) so rulings can cite
  them, for example "Section 12.3".
- Dates are written as formulas (anchor + offset). Exact dates live on the
  League Calendar each season; see Article V.
"""

from __future__ import annotations

EDITION = "Charter Edition"
TAGLINE = "A permanent framework for competition, governance, and long-term franchise management."
FOOTER = "BLHA CONSTITUTION • CHARTER EDITION"

# Adopted amendments, oldest first. Amendments are identified by the date they
# were adopted; never give them version numbers. When an amendment passes
# (Article XX), change the article text below AND add one entry here, then
# rebuild: tools/build_constitution.py writes constitution/CHANGELOG.md and
# adds the dated entry to the history block at the end of Article XX.
#
# Each entry:
#   adopted           date the vote closed and the amendment passed, "YYYY-MM-DD"
#   articles          Roman numerals of whole articles changed, e.g. ["X"] (may be empty)
#   sections          sections changed, cited as N.N, e.g. ["10.3"] (may be empty,
#                     but articles and sections cannot both be empty)
#   old               text before the amendment ("" for a new section)
#   new               text after the amendment ("" for a removed section)
#   vote              {"yes": 9, "no": 2, "not_voted": 1}; at least 8 yes (20.3), at most 12 in total
#   effective_season  first Season it applies to, e.g. 2028 (20.4)
#   summary           optional one line on what changed
#
# Example (commented out):
#   {
#       "adopted": "2028-06-20",
#       "articles": [],
#       "sections": ["10.1"],
#       "old": "Each franchise receives **$1,000 FAAB** at the beginning of each Season.",
#       "new": "Each franchise receives **$1,200 FAAB** at the beginning of each Season.",
#       "vote": {"yes": 9, "no": 2, "not_voted": 1},
#       "effective_season": 2028,
#       "summary": "FAAB budget raised to $1,200.",
#   },
AMENDMENTS: list[dict] = []

GLANCE_STATS = [
    ("12", "Franchises"),
    ("$150", "Annual dues"),
    ("22", "Regular-season weeks"),
    ("36", "Controlled spots (non-IR)"),
]

QUICK_REFERENCE = [
    ("League", "12-franchise dynasty fantasy hockey league hosted on Fantrax, with Discord serving as the league office and clubhouse."),
    ("Inaugural season", "2027–28 (Season 2027). Startup draft is held in the 2027 offseason."),
    ("Format", "Head-to-Head Points, daily lineups, 22-week regular season, each opponent twice, no divisions."),
    ("Roster", "20 active (3 C, 3 LW, 3 RW, 3 F, 6 D, 2 G), 6 reserve, 10 minors, 5 IR. 36 controlled spots excluding IR."),
    ("Minors", "Age 25 or younger on NHL opening day, as calculated by Fantrax; skaters ≤100 career NHL regular-season GP; goalies ≤50."),
    ("FAAB", "$1,000 per season; no rollover; $0 bids allowed; hidden bids; daily processing; no FCFS."),
    ("Acquisitions", "Maximum 5 per normal fantasy week; the two-week championship uses two separate five-acquisition weekly limits."),
    ("Goalies", "Maximum 4 credited starts per normal fantasy week; 8 total across the two-week championship."),
    ("Trades", "Unlimited, no vote or veto. Deadline: Sunday 11:59 PM ET at the end of Week 20. Reopens the day after the Stanley Cup Final."),
    ("Annual draft", "5 rounds, linear; begins 14–21 days after the NHL Entry Draft."),
    ("Playoffs", "6 teams; top 2 byes; reseeding; 1-week quarterfinals and semifinals; 2-week cumulative championship. Non-playoff teams play a consolation bracket."),
    ("Dues", "$150 per franchise per season, due before that season's draft."),
    ("Future picks", "Future 1st- and 2nd-round picks cannot be traded until all required future-season dues are paid and confirmed through the pick's season."),
    ("Dates", "Defined by formula in this Constitution; exact dates are published each season on the League Calendar."),
]

ALLOCATION = [
    ("BLHA Champion", 650),
    ("Runner-Up", 350),
    ("Third Place", 150),
    ("Presidents' Trophy", 200),
    ("Dynasty Pot", 200),
    ("Fantrax / League Operating Reserve", 150),
    ("League Services Allocation", 100),
]
ALLOCATION_TOTAL = 1800
assert sum(a for _, a in ALLOCATION) == ALLOCATION_TOTAL == 12 * 150

SKATERS = [("Goal", "+5.00"), ("Assist", "+2.95"), ("Shot on Goal", "+0.55"), ("Block", "+0.35"), ("Hit", "+0.20")]
GOALIES = [("Game Started", "+6.50"), ("Save", "+0.49"), ("Goal Against", "-5.00"), ("Goalie Goal", "+5.00"), ("Goalie Assist", "+2.95")]

DATE_RULES = [
    ("Week 1", "Begins with the first Fantrax scoring period of the Season, aligned with the NHL regular-season opening."),
    ("Dues deadline", "Set by the Commissioner with at least 30 days' notice, and always before that Season's draft (Article III)."),
    ("Startup Draft and Annual Draft", "Begin 14 to 21 days after the final day of the NHL Entry Draft, announced at least 30 days ahead (Articles XIII and XIV)."),
    ("Trade deadline", "Sunday 11:59 PM ET at the end of Week 20."),
    ("Trading reopens", "The day after the Stanley Cup Final ends, when the Commissioner renews the league in Fantrax for the next Season."),
    ("Regular season ends", "Sunday 11:59 PM ET at the end of Week 22."),
    ("Playoffs", "Four consecutive Weeks after Week 22: Quarterfinals, Semifinals, then the two-week Championship. Scheduled to end about six days before the NHL regular season ends where the NHL schedule permits."),
    ("Waiver processing", "Daily at about 11:00 AM ET; Fantrax system behavior controls."),
    ("Lineup locks", "About one minute before each player's NHL game; Fantrax system behavior controls."),
    ("Prizes and Season Ledger", "Within 30 days after the BLHA Championship concludes (Article III)."),
    ("Amendment votes", "Offseason only, and always before the dues deadline of the Season they first apply to (Article XX)."),
]

# Each article: num (roman), title, callout (label, text) or None, blocks.
# Block kinds:
#   ("p", text)                          numbered section
#   ("allocation",)                      financial allocation table
#   ("scoring",)                         scoring tables
#   ("dates",)                           date-rules table
#   ("history", rows)                    version history table
ARTICLES = [
    {
        "num": "I", "title": "League Identity and Purpose", "callout": None,
        "blocks": [
            ("p", "The Beer League Hockey Association (BLHA) is a 12-franchise dynasty fantasy hockey league established in 2026. Its inaugural season is 2027–28. It is designed around long-term roster construction, prospect development, active trading, daily competition, and permanent league history."),
            ("p", "Fantrax is the authoritative platform for gameplay, rosters, scoring, transactions, standings, draft results, and playoff results. Discord is the league's communication, governance, trade-market, scouting, recordkeeping, and community platform."),
            ("p", "The BLHA is intended to reward sustained franchise management. Rebuilding, prospect accumulation, veteran contention windows, and aggressive trading are legitimate strategies when conducted in good faith and within this Constitution."),
            ("p", "**Definitions.** **Season** means the NHL season a BLHA season covers, identified by its starting year (Season 2027 is 2027–28). **Active Season** runs from the first lineup lock of Week 1 through the final scoring period of the BLHA Championship; **Offseason** is every other time. **Week** means a Fantrax scoring week. **Annual Draft** means the draft held in an Offseason for the next Season, identified by the year it is held (the 2028 Annual Draft supplies Season 2028). **Franchise** means a team with one league vote; **Owner** means a person who manages it. **League Ledger** means the Commissioner's record of dues, prepayments, operating expenses, prizes, and the Dynasty Pot; its summary, the Season Ledger, is published in the league-ledger channel."),
            ("p", "**Material Amendment** means any change to dues, prizes, the financial allocation, scoring, roster or minor-league rules, trade, pick, or prepayment rules, playoff or draft-order formats, voting thresholds, or Commissioner powers, and any other change that alters franchise rights or obligations. Clerical corrections, platform-conformance fixes, and League Calendar dates are not Material Amendments."),
        ],
    },
    {
        "num": "II", "title": "Governance and League Authority",
        "callout": ("GOVERNANCE THRESHOLD", "Material Amendments require at least 8 affirmative franchise votes out of 12."),
        "blocks": [
            ("p", "The Commissioner administers the league, maintains Fantrax settings, publishes official rulings, enforces this Constitution, preserves the league record, and takes reasonable action necessary to protect competitive integrity and continuity. Assistant Commissioners perform duties delegated by the Commissioner as described in Article XIX."),
            ("p", "Each franchise receives one formal league vote regardless of whether it has one owner or multiple co-owners. Co-owners may fully participate in roster management and league discussion but do not create an additional franchise vote."),
            ("p", "An orphaned franchise (Article XVIII) has no vote while it is orphaned. The 8-vote threshold does not change."),
            ("p", "Material Amendments are made only as provided in Article XX: during the Offseason, with at least 8 of the 12 franchise votes, effective for the next Season unless the amendment states a later effective date."),
            ("p", "Substantive rules will not be changed during an Active Season. The Commissioner may correct a clerical error, Fantrax configuration error, or platform issue when the correction is necessary to apply an already-existing rule. A temporary operational measure may be used when a platform limitation makes literal enforcement impossible, but the measure must preserve the rule's original intent and be documented in Discord."),
            ("p", "The current published Constitution controls when it conflicts with old messages, prior drafts, informal discussions, or outdated documents. The League Calendar implements this Constitution and cannot override it (Article V)."),
        ],
    },
    {
        "num": "III", "title": "Franchise Ownership, Dues, Expenses, and Prizes", "callout": None,
        "blocks": [
            ("p", "Annual dues are **$150 per franchise**. A franchise is one dues obligation even when co-owners are present. The Commissioner pays the same annual franchise dues as every other franchise."),
            ("p", "The dues deadline for each Season is published on the League Calendar with at least 30 days' notice and falls before that Season's draft: the Startup Draft for Season 2027 and the Annual Draft for later Seasons. A franchise must be fully paid by that deadline to participate in the draft or begin the Season, unless the Commissioner has announced a league-wide alternative payment schedule."),
            ("p", "The Commissioner announces the accepted payment methods. A payment counts only when the Commissioner has confirmed it and recorded it in the League Ledger."),
            ("p", "If a franchise is not fully paid by the deadline, the Commissioner gives written notice in Discord and by direct message. If payment is still not confirmed 7 days after the deadline, the franchise may be treated as orphaned under Article XVIII, including replacement of the owner."),
            ("p", "The annual allocation of the $1,800 league pool (12 franchises × $150) is:"),
            ("allocation",),
            ("p", "The League Services Allocation is paid to the Commissioner for recurring league administration, setup, records, Discord infrastructure, automation maintenance, league communications, and related management duties. Any increase to the League Services Allocation is a Material Amendment. On any vote that changes the League Services Allocation, the Commissioner's franchise does not vote and approval requires at least 8 of the other 11 franchises."),
            ("p", "The League Operating Reserve may be used only for Fantrax Premium and other disclosed, authorized league operating costs. Any portion of the $150 reserve remaining after the Season's authorized expenses are settled is added to the Dynasty Pot."),
            ("p", "Guaranteed competitive prizes will not be reduced during an Active Season to cover an unanticipated operating overage. Any additional assessment or material change to the annual allocation requires league approval under this Constitution."),
            ("p", "Prizes are paid after the competition that earns them is final, and no later than 30 days after the BLHA Championship concludes. Within the same period the Commissioner publishes a Season Ledger in the League Ledger channel showing dues received, prizes paid, operating reserve spending, the League Services Allocation, and the Dynasty Pot balance."),
            ("p", "Annual dues are non-refundable once the Annual Draft has begun (the Startup Draft for Season 2027), except that if the league dissolves before the Season, Article XX requires a distribution or refund. Future-season prepayments attached to a franchise are non-refundable if an owner voluntarily leaves the league."),
        ],
    },
    {
        "num": "IV", "title": "Dynasty Pot",
        "callout": ("DYNASTY POT", "The first franchise to win three BLHA Championships in the same active cycle wins the entire accumulated pot."),
        "blocks": [
            ("p", "The BLHA maintains a rolling Dynasty Pot designed to reward sustained championship success across multiple Seasons. The first Dynasty Pot cycle begins with Season 2027."),
            ("p", "At least $200 from each Season's dues is added to the Dynasty Pot. Any unused portion of the annual League Operating Reserve is also added to the Dynasty Pot after the Season's authorized expenses are settled."),
            ("p", "The first franchise to win three BLHA Championships during the same active Dynasty Pot cycle wins the entire accumulated Dynasty Pot. Championships do not need to be consecutive."),
            ("p", "Championship credit belongs to the franchise, not the individual owner. An ownership change does not erase a franchise's championship count within the active cycle."),
            ("p", "The base Dynasty Pot contribution for the Season in which a franchise wins its third championship is added to the pot before the payout is calculated. The payout is made after the championship result is final and the Season's financial obligations are reconciled."),
            ("p", "After the Dynasty Pot is paid, the active balance returns to zero, every franchise's championship counter resets to zero, and a new cycle begins. Historical championships remain permanently recorded in BLHA history."),
            ("p", "The Dynasty Pot balance and each franchise's championship count are reported in the Season Ledger."),
            ("p", "If the BLHA permanently dissolves before the Dynasty Pot is won, remaining Dynasty Pot funds are distributed equally among the active, fully paid franchises after any authorized outstanding league expenses are satisfied."),
        ],
    },
    {
        "num": "V", "title": "League Format, Schedule, and Calendar", "callout": None,
        "blocks": [
            ("p", "The BLHA uses Head-to-Head Points scoring with daily lineups."),
            ("p", "The regular season consists of 22 fantasy Weeks. Each franchise plays every other franchise twice. The league does not use divisions or conferences."),
            ("p", "Individual players lock at approximately one minute before their NHL game begins, subject to Fantrax system behavior and the league's configured lineup settings."),
            ("p", "**Dates are set by formula.** NHL and Fantrax schedules change every Season, so this Constitution defines deadlines and key dates as an anchor event plus an offset rather than as fixed calendar dates. The League Calendar converts those formulas into exact dates and times each Season."),
            ("p", "**Publication.** The Commissioner publishes the League Calendar for each Season within 14 days after the NHL releases its regular-season schedule, and keeps it current."),
            ("p", "**Changes.** After a date is published it changes only when the NHL schedule, a platform limitation, or events outside the league's control require it. The Commissioner gives at least 7 days' notice of a change where possible. A published deadline may be extended but is not made earlier unless the NHL schedule forces it."),
            ("p", "**Formulas control.** If the League Calendar conflicts with a formula in this Constitution, the formula controls and the Commissioner corrects the Calendar. The League Calendar cannot create or change substantive rules."),
            ("p", "**Time.** All times are Eastern Time (ET), observing daylight saving time. A Week runs Monday through Sunday as configured in Fantrax."),
            ("p", "The key dates and how each is set:"),
            ("dates",),
        ],
    },
    {
        "num": "VI", "title": "Rosters and Positions", "callout": None,
        "blocks": [
            ("p", "Normal roster limits are 20 active players and 6 reserves, for 26 non-minor controlled roster spots, plus 10 minor-league spots and up to 5 IR spots. That is 36 controlled roster spots excluding IR, or 41 including IR."),
            ("p", "Active positions are 3 C, 3 LW, 3 RW, 3 F, 6 D, and 2 G. An F slot may be filled by any forward (C, LW, or RW)."),
            ("p", "Minor-league players do not count toward the normal 26-player roster limit. Players properly placed on IR do not count toward normal roster limitations while Fantrax recognizes them as IR-eligible."),
            ("p", "Managers are responsible for maintaining legal rosters. When a roster becomes illegal because of a transaction, eligibility change, or player activation, the manager must correct the violation within 24 hours of notice from Fantrax or the Commissioner, or within any shorter limit Fantrax enforces."),
        ],
    },
    {
        "num": "VII", "title": "Minor-League Eligibility", "callout": None,
        "blocks": [
            ("p", "The BLHA maintains 10 minor-league roster spots."),
            ("p", "A player must be age 25 or younger on the first day of the NHL regular season, as Fantrax calculates it. Age is measured on that date for the whole Season, so a birthday during the Season does not change a player's eligibility. Fantrax's age calculation is final."),
            ("p", "Skaters remain minor-eligible through 100 career NHL regular-season games played. Goalies remain minor-eligible through 50 career NHL regular-season games played. Career NHL games played continue to accumulate during the Season."),
            ("p", "Once Fantrax identifies a minor-league player as ineligible, the franchise has three calendar days to promote, trade, drop, or otherwise remove the player from the minor slot."),
            ("p", "Promotion does not permanently burn minor eligibility. A player who still satisfies the BLHA minor rules may later return to a minor slot where Fantrax permits."),
        ],
    },
    {
        "num": "VIII", "title": "Scoring", "callout": None,
        "blocks": [
            ("p", "The BLHA scoring system is intentionally compact. Categories not listed below are disabled unless this Constitution is formally amended."),
            ("scoring",),
            ("p", "Goalie wins, shutouts, plus/minus, penalty minutes, power-play bonuses, game-winning-goal bonuses, faceoff wins, and other unlisted scoring categories are not separately scored."),
        ],
    },
    {
        "num": "IX", "title": "Lineups and Goalie Starts", "callout": None,
        "blocks": [
            ("p", "Lineups are set daily. Managers are responsible for maintaining legal, reasonably competitive active lineups throughout the Season."),
            ("p", "A franchise may receive credit for a maximum of 4 goalie starts during a normal fantasy Week."),
            ("p", "The two-week BLHA Championship permits a maximum of 8 credited goalie starts across the full championship period. Any other Week longer than one calendar week, such as over an NHL break, uses the same rule: 4 credited goalie starts and 5 acquisitions for each calendar week it spans."),
            ("p", "Fantrax enforcement settings govern the technical application of the goalie-start limit. A manager may not intentionally exploit a platform timing or scoring behavior to obtain credit beyond the constitutional maximum."),
        ],
    },
    {
        "num": "X", "title": "Waivers, FAAB, and Acquisitions", "callout": None,
        "blocks": [
            ("p", "Each franchise receives **$1,000 FAAB** at the beginning of each Season. Standard FAAB does not roll over from Season to Season."),
            ("p", "$0 bids are permitted and bids use $1 increments. Bids are hidden. Vickrey or proxy bidding is not used."),
            ("p", "Unowned players are acquired through FAAB rather than first-come, first-served acquisition. Waivers are intended to process daily at approximately 11:00 AM ET, subject to Fantrax system behavior."),
            ("p", "Equal bids go to the bid submitted first, using Fantrax's Earliest Bid tie-breaker."),
            ("p", "A franchise may make up to **5 acquisitions per normal fantasy Week**. An acquisition is adding a player from the unowned player pool by FAAB claim, as counted by Fantrax. Trades, draft selections, and drops are not acquisitions. The two-week championship is treated as two separate acquisition weeks, permitting up to 5 acquisitions in each underlying Week, for a maximum of 10 across the full championship period."),
            ("p", "Waiver-churning protections and Fantrax waiver-period protections remain enabled where available."),
            ("p", "The consolation-bracket champion receives a **$50 FAAB bonus** for the following Season, giving that franchise $1,050 for that Season only. Fantrax resets every budget when the league renews, so the Commissioner adds the bonus by hand after renewal. The bonus expires with ordinary current-season FAAB and may be traded as current-season FAAB (Article XI)."),
        ],
    },
    {
        "num": "XI", "title": "Trades and Trade Deadline", "callout": None,
        "blocks": [
            ("p", "Trades are unlimited and are not subject to league vote or veto. A trade is not reversible merely because the Commissioner or another manager believes one side received more value."),
            ("p", "Commissioner intervention is limited to narrow circumstances such as collusion, prohibited outside consideration, clear misconduct, a credible misclick or platform error, or a transaction that violates an express constitutional rule. A misclick or platform error must be reported to the Commissioner promptly and no later than 48 hours after the trade processes. Collusion or misconduct discovered later may still be raised under Article XVII."),
            ("p", "Tradeable assets are rostered players, eligible draft picks, and current-season FAAB. Outside assets, cash consideration, loans, rentals, predetermined tradebacks, and other off-platform consideration are prohibited."),
            ("p", "Current-season FAAB is the FAAB balance for the Season in progress or, during the Offseason, for the next Season once Fantrax issues it (including the consolation bonus). FAAB for any later Season may not be traded."),
            ("p", "Conditional draft picks are prohibited."),
            ("p", "The trade deadline is the end of Week 20 (Article V). Trading reopens the day after the Stanley Cup Final ends. No trades, including draft picks, may be made between the deadline and the reopening. A trade must be fully processed in Fantrax before the deadline; Fantrax can still process a trade that was pending at the deadline, and any trade processed after the deadline is void and is reversed by the Commissioner."),
        ],
    },
    {
        "num": "XII", "title": "Future Draft Picks and Required Prepayment",
        "callout": ("PAYMENT FIRST", "Pay first, then trade. A future 1st- or 2nd-round pick trade made before the required dues are confirmed is reversed."),
        "blocks": [
            ("p", "Fantrax draft-pick trading is enabled for the next three Annual Drafts (the next Annual Draft and the two after it). Five rounds of annual draft picks are tradeable."),
            ("p", "A franchise may not trade away a future first- or second-round pick unless that franchise is fully paid through the Season associated with that pick (the Season supplied by that Annual Draft) before the trade is completed."),
            ("p", "Required prepayment is cumulative. Example: during Season 2027, a franchise that has paid for Season 2027 and wishes to trade its 2030 first- or second-round pick must first be paid for Seasons 2028, 2029, and 2030."),
            ("p", "The required payment must be received and confirmed by the Commissioner in the League Ledger before the trade processes in Fantrax. If multiple franchises in the same trade trigger this rule, each affected franchise must satisfy its own prepayment requirement."),
            ("p", "Fantrax processes trades without Commissioner approval and does not check this rule, and Fantrax acceptance does not override it. If a trade processes before every required payment is confirmed, the Commissioner reverses the entire trade in Fantrax and notifies the franchises involved. The same trade may be made again once the payment is confirmed."),
            ("p", "Prepaid dues attach to the franchise, not the individual owner. If an owner leaves the BLHA, those funds remain with the franchise and a replacement owner inherits the benefit of the paid Seasons."),
            ("p", "Trading a future third-, fourth-, or fifth-round pick does not trigger additional prepayment beyond any dues otherwise owed."),
        ],
    },
    {
        "num": "XIII", "title": "Startup Draft (Transitional)", "callout": None,
        "blocks": [
            ("p", "This Article applies only to the inaugural startup draft for Season 2027. It is a 36-round slow snake draft with a 4-hour pick clock."),
            ("p", "Startup draft order is set by a random draw conducted by the Commissioner and published in Discord before the draft."),
            ("p", "The Startup Draft follows the date formula in Article V. If all 12 franchises are not filled and fully paid in time, the Commissioner may postpone the draft with at least 14 days' notice, but it must be completed at least 14 days before Week 1. If the draft is not on pace to finish in time, the Commissioner may shorten the pick clock with 7 days' notice."),
            ("p", "A nightly clock pause runs from midnight through 8:00 AM ET. Picks may be made during the pause where Fantrax allows, but the active pick timer is suspended."),
            ("p", "Draft queues are strongly encouraged. After two timer expirations, the Commissioner may enable Fantrax auto-draft behavior or another announced timeout procedure until the manager returns."),
            ("p", "Managers are responsible for finishing the startup process with a legal organization under Articles VI and VII by the roster-compliance deadline announced before the draft."),
        ],
    },
    {
        "num": "XIV", "title": "Annual Draft and Draft Order", "callout": None,
        "blocks": [
            ("p", "The annual BLHA draft is 5 rounds and is linear rather than snake. Each franchise therefore holds the same draft position in every round unless a pick has been traded. The first Annual Draft is the 2028 Annual Draft."),
            ("p", "The Annual Draft begins 14 to 21 days after the final day of the NHL Entry Draft (Article V)."),
            ("p", "The draft uses an 8-hour pick clock with a midnight–8:00 AM ET pause. Managers are encouraged to maintain queues. Timeout handling may use Fantrax queue, auto-draft, or temporary-skip tools as announced before the draft."),
            ("p", "The player pool is not restricted to the current NHL draft class. Any unowned player in the Fantrax player pool who satisfies BLHA minor-league eligibility for the Season that Annual Draft supplies may be selected."),
            ("p", "Draft order is based on the results of the Season just completed. Picks 1.01 through 1.06 belong to the six non-playoff franchises and are ordered by ascending Potential Points / Max Points For, with the lowest total receiving 1.01. Potential Points is Fantrax's measure of the points a franchise would have scored with its best possible lineup each Week, using its active and reserve players; players in minor-league and IR slots are not counted. Ties are broken under Section 15.5."),
            ("p", "Picks 1.07 and 1.08 belong to the two Quarterfinal losers, with the lower regular-season seed selecting earlier. Pick 1.09 belongs to the fourth-place finisher. Pick 1.10 belongs to the third-place finisher. Pick 1.11 belongs to the Runner-Up. Pick 1.12 belongs to the BLHA Champion."),
            ("p", "The same order repeats in Rounds 2 through 5. The consolation bracket does not alter annual draft position."),
        ],
    },
    {
        "num": "XV", "title": "Regular Season, Standings, and Presidents' Trophy", "callout": None,
        "blocks": [
            ("p", "The regular season consists of 22 Weeks. Every franchise plays every other franchise twice."),
            ("p", "Regular-season standings and head-to-head results are recorded by Fantrax."),
            ("p", "The Presidents' Trophy is awarded to the franchise with the best regular-season Head-to-Head record after Week 22 and carries the annual $200 prize. It is independent of postseason results."),
            ("p", "**Standings tiebreakers.** These apply to every standings position, including the Presidents' Trophy, playoff qualification and seeding, and consolation seeding. If two or more franchises are tied: (1) regular-season fantasy points scored; (2) head-to-head record among the tied franchises; (3) the next configured Fantrax standings tiebreaker; (4) a random draw conducted by the Commissioner and recorded in Discord."),
            ("p", "**Draft-order ties.** If non-playoff franchises are tied on Potential Points / Max Points For, the franchise with fewer regular-season fantasy points scored selects earlier. If still tied, a random draw conducted by the Commissioner and recorded in Discord decides."),
        ],
    },
    {
        "num": "XVI", "title": "Playoffs, Third Place, and Consolation",
        "callout": ("POSTSEASON", "Six playoff teams. Top two seeds receive byes. The BLHA Championship is a two-week cumulative matchup."),
        "blocks": [
            ("p", "Six franchises qualify for the BLHA Championship Playoffs, ranked by final regular-season standings. Seeds 1 and 2 receive first-round byes."),
            ("p", "**Quarterfinals:** Seed 3 vs. Seed 6 and Seed 4 vs. Seed 5. **Semifinals:** Seed 1 and Seed 2 join the four-team field; the playoff bracket reseeds after each round, with the highest remaining seed facing the lowest remaining seed. Quarterfinals and Semifinals are one fantasy Week each. The **BLHA Championship** is a two-week cumulative matchup."),
            ("p", "The two Semifinal losers play a third-place matchup during the same two-week period as the BLHA Championship. The winner receives third place and the $150 third-place prize. The Commissioner enters this matchup in Fantrax once the Semifinals are final."),
            ("p", "If Fantrax cannot technically stage the third-place matchup, the fallback is the Semifinal loser who scores the most fantasy points during the same two-week championship period. If the fallback total is exactly tied, the higher playoff seed receives third place."),
            ("p", "If any playoff, third-place, or consolation matchup ends in an exact tie, the higher seed advances or wins."),
            ("p", "The playoff schedule should end approximately six days before the NHL regular season concludes to reduce late-season NHL lineup volatility where the NHL schedule permits (Article V)."),
            ("p", "**Consolation bracket.** The six non-playoff franchises play a consolation bracket during the same Weeks as the playoffs, using the same structure: seeded 1 through 6 by their regular-season standings rank among non-playoff franchises, top two seeds receive byes, reseeding after each round, and a two-week cumulative final. The consolation-bracket champion receives the next-Season $50 FAAB bonus described in Article X. Consolation results do not change annual draft order, standings, or the Presidents' Trophy."),
        ],
    },
    {
        "num": "XVII", "title": "Competitive Integrity and Anti-Tanking", "callout": None,
        "blocks": [
            ("p", "Managers are expected to compete in good faith and maintain legal, reasonably competitive lineups. Deliberate lineup sabotage, collusion, coordinated dumping of assets, or manipulation intended to distort standings, playoff qualification, or draft position is prohibited."),
            ("p", "Rebuilding is permitted. A franchise may trade productive veterans, accumulate prospects and draft picks, or accept short-term competitive decline as part of a legitimate long-term strategy."),
            ("p", "Non-playoff draft order is based on Potential Points / Max Points For rather than final standings so that intentionally benching productive players does not improve draft position."),
            ("p", "A lopsided-looking trade, unusual roster construction, or temporary rebuilding lineup does not by itself establish misconduct. Competitive-integrity enforcement requires evidence of conduct that violates an express rule or demonstrates bad-faith manipulation."),
            ("p", "Any owner may report suspected violations to the Commissioner. Enforcement follows Article XIX."),
        ],
    },
    {
        "num": "XVIII", "title": "Orphan Franchises and Ownership Changes", "callout": None,
        "blocks": [
            ("p", "A franchise is **orphaned** when its owner resigns, is removed under Article III, or is inactive (no lineup or transaction activity and no response to Commissioner contact) for 7 consecutive days during an Active Season or 14 consecutive days during the Offseason."),
            ("p", "If a franchise becomes orphaned, the Commissioner may recruit and approve a replacement owner and take reasonable temporary steps necessary to preserve the roster, schedule, and competitive integrity of the league."),
            ("p", "Prepaid future-Season dues remain attached to the franchise and transfer to the replacement owner. A departing owner is not entitled to a refund of prepaid future Seasons merely because that owner leaves the league."),
            ("p", "The Commissioner may offer a reasonable orphan incentive when necessary to recruit a qualified replacement owner, but any incentive that uses league funds or changes competitive assets must be disclosed to the league."),
            ("p", "The Commissioner may temporarily lock an abandoned franchise from transactions while replacement ownership is being arranged. The Commissioner should avoid making discretionary long-term roster moves for an orphan except where necessary to maintain a legal lineup or prevent an obvious competitive distortion."),
        ],
    },
    {
        "num": "XIX", "title": "Commissioner Authority, Conflicts, and Appeals", "callout": None,
        "blocks": [
            ("p", "The Commissioner may interpret and enforce this Constitution, correct administrative errors, and take reasonable action necessary to address situations not expressly anticipated by the rules. Such authority must be exercised to preserve the intent, competitive balance, and continuity of the league rather than to create new substantive rules during the Season."),
            ("p", "**Assistant Commissioners.** The Commissioner may appoint and remove Assistant Commissioners, who serve at the Commissioner's pleasure and perform duties the Commissioner delegates. An Assistant Commissioner is **neutral** for a matter when that person's franchise is not involved in it."),
            ("p", "**Conflicts.** When the Commissioner's own franchise is directly involved in a dispute, disciplinary matter, contested trade review, or other individualized ruling, the Commissioner shall recuse from the substantive decision. A neutral Assistant Commissioner will administer the matter where available. If none is available, the Commissioner may designate a temporary neutral reviewer from among unaffected franchise owners or submit the issue to the unaffected franchises for resolution."),
            ("p", "**Appeals.** A franchise directly affected by a material Commissioner ruling may request review within 48 hours of the ruling by opening an Appeal ticket in the open-a-ticket channel. The Commissioner records the request in the rulings-log channel. A Review Panel of three owners from unaffected franchises, drawn at random in a publicly recorded draw, decides by majority within 7 days. The Panel may uphold, modify, or reverse the ruling, and its decision is final for that matter. Routine scoring results, published Fantrax outcomes, ordinary roster locks, and matters controlled automatically by the platform are not subject to appeal merely because the result is unfavorable."),
            ("p", "**Vacancy.** The Commissioner's office is vacant if the Commissioner resigns or is unavailable for 14 consecutive days. The Assistant Commissioner the Commissioner has designated as successor serves as Interim Commissioner. If there is none, the active franchises choose an Interim Commissioner by majority vote within 14 days. The Interim Commissioner serves until the active franchises choose a permanent Commissioner by majority vote."),
            ("p", "**Transition.** A departing Commissioner must account for and transfer all league funds, records, Fantrax commissioner access, and Discord and automation administration to the successor within 14 days."),
            ("p", "All significant rulings, recusal decisions, and appeal outcomes are recorded in the rulings-log channel so that the league retains a permanent record."),
        ],
    },
    {
        "num": "XX", "title": "Amendments, Records, and Dissolution", "callout": None,
        "blocks": [
            ("p", "**Adoption.** The Commissioner finalizes this Constitution before any owner is invited to the league. Accepting a franchise is accepting this Constitution, and each owner agrees to be bound by it. The text as accepted (the Charter) is locked. No amendment vote may be held before the Offseason following Season 2027, and until then the Constitution changes only by clerical correction under Section 2.5."),
            ("p", "**Proposals.** Any franchise or the Commissioner may propose a Material Amendment in writing. A proposal must identify the affected rule, the proposed replacement language, and the intended effective date, and is posted in the voting channel at least 7 days before voting opens."),
            ("p", "**Voting.** Amendment votes are held only during the Offseason. The voting window is 7 days. Each franchise casts one vote through the league's designated voting channel or method. Approval requires at least 8 affirmative votes out of 12. Non-votes and abstentions are not affirmative votes. Votes to choose an Interim or permanent Commissioner under Article XIX are not amendment votes and may be held at any time."),
            ("p", "**Timing.** An approved amendment takes effect for the next Season, or on the later date it states. To apply to a Season it must be approved before that Season's dues deadline, so every owner knows the rules before paying."),
            ("p", "Amendments do not retroactively alter completed competition, previously earned prizes, or finalized transactions."),
            ("p", "**Records.** Official amendment results, effective dates, championship history, Presidents' Trophy winners, Dynasty Pot status, dues status, and other permanent league records are maintained in Discord and/or the league's designated archival system. Each adopted version of this Constitution is dated and posted, and prior versions are archived."),
            ("p", "**Dissolution.** If the BLHA permanently dissolves, authorized outstanding league expenses are settled first. Remaining prize funds or other Season-specific funds are distributed according to the results already earned where reasonably possible. Any remaining Dynasty Pot balance is distributed equally among active, fully paid franchises as provided in Article IV. If the BLHA dissolves before a Season's first lineup lock, that Season's dues not yet spent on authorized expenses are refunded to the franchises that paid them."),
            ("p", "The latest published version of this Constitution is the controlling league document. Upon adoption of the Charter, all prior working drafts are superseded except as historical records."),
            ("history", [("Charter", "Adopted by owner acceptance. Effective Season 2027.")]),
        ],
    },
]
