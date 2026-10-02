# BLHA The Wire — Routing Rules

## General principles
1. One story normally goes to one automated channel.
2. Higher-priority routes win.
3. Headlines are posted with a link and source attribution; the automation does not republish full articles.
4. Rumors, opinion pieces, predictions, game-thread chatter, score/highlight posts, and generic feed-navigation items should not trigger specialty channels.
5. `r/hockey` is **discovery-only** in the MVP. It may help surface attributed reporting or clearly classifiable news, but it will not post directly to Discord in the live version.
6. Tier 1 sources currently intended for direct posting are NHL.com and Sportsnet.
7. ESPN RSS is retained but disabled after returning no entries during the 2026-09-30 dry run.

## Route priority
`breaking-news` → `injury-report` → `nhl-transactions` → `prospect-wire` → `nhl-news`

## 🚨 breaking-news
Requires a Tier 1 source plus a high-impact phrase.

Candidate phrases:
- out indefinitely
- season-ending / out for the season
- suspended indefinitely
- retirement
- fired / dismissed
- explicitly described blockbuster trade

Ordinary signings, extensions, depth trades, recalls, waivers, and routine roster moves do **not** automatically become Breaking News.

## 🏥 injury-report
Candidate phrases:
- injured / injury
- day-to-day / week-to-week / month-to-month
- injured reserve / LTIR
- surgery / concussion / fracture
- activated from IR / returns from injury / cleared to play

Major indefinite or season-ending injuries may be promoted to Breaking News when the source is Tier 1.

## 🔄 nhl-transactions
Candidate phrases:
- traded / trade / acquired
- signed / signs / re-signs / contract / extension / agrees to
- waived / waivers / claimed
- recalled / call-up
- assigned / reassigned / loaned

## 🌱 prospect-wire
Candidate phrases are matched as words/phrases rather than loose substrings to avoid false positives.

Examples:
- prospect / rookie
- AHL
- NCAA / college hockey
- CHL / OHL / WHL / QMJHL
- junior / juniors
- development camp
- NHL Draft / draft prospect
- World Juniors / WJC

## 📰 nhl-news
Default route for relevant hockey reporting that does not match a specialty desk.

Examples:
- interviews
- team/league developments
- meaningful analysis
- captaincy/coaching/front-office developments
- other relevant NHL reporting

Pure score posts, routine highlights, daily discussion threads, and feed-section labels are filtered rather than posted.

## Reddit discovery behavior
- Reddit cannot trigger `breaking-news`.
- General unattributed Reddit chatter is filtered.
- Score/highlight-formatted posts and Daily/Game/Post Game threads are filtered.
- Attributed reporter posts may appear in dry-run output as `discovery->CHANNEL`.
- Clearly classifiable injury, transaction, or prospect items may also appear as discovery items.
- Discovery items are for evaluation only and are not eligible for live automatic posting in Phase 2D.1.

## Duplicate suppression design
Phase 2D.2 will suppress repeats using both:
- normalized canonical URL
- normalized headline fingerprint

The target duplicate window is 48 hours. A story found on multiple feeds should be posted only once unless a materially new development occurs.
