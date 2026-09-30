# BLHA The Wire — Routing Rules

## General principles
1. One story normally goes to one automated channel.
2. Higher-priority routes win.
3. Headlines are posted with a link and source attribution; the automation should not republish full articles.
4. Rumors, opinion pieces, predictions, game recaps and generic analysis should not trigger specialty channels.
5. Reddit may supplement the feed but cannot auto-trigger Breaking News in the MVP.

## Route priority
`breaking-news` → `injury-report` → `nhl-transactions` → `prospect-wire` → `nhl-news`

## 🚨 breaking-news
Requires a Tier 1 source plus a high-impact phrase.

Candidate phrases:
- traded / blockbuster trade / acquired
- suspended
- out indefinitely
- season-ending / out for season
- retires / retirement
- fired / dismissed / named general manager / named head coach
- major schedule change / league announces

Do not automatically classify ordinary contract signings, depth trades or minor roster moves as Breaking News.

## 🏥 injury-report
Candidate phrases:
- injured / injury
- out / unavailable
- day-to-day / week-to-week / month-to-month
- injured reserve / IR / LTIR
- surgery / concussion
- activated from IR / returns / cleared to play

Major indefinite or season-ending injuries may be promoted to Breaking News if the source is Tier 1.

## 🔄 nhl-transactions
Candidate phrases:
- traded / trade / acquired
- signed / signs / contract / extension
- waived / waivers / claimed
- recalled / call-up
- assigned / reassigned / loaned
- placed on IR / activated (unless injury route wins)

## 🌱 prospect-wire
Candidate phrases:
- prospect / rookie
- AHL
- NCAA / college hockey
- CHL / OHL / WHL / QMJHL
- junior / juniors
- development camp
- NHL Draft / draft prospect
- entry-level contract when clearly prospect-focused
- World Juniors / WJC

## 📰 nhl-news
Default route for relevant NHL stories that do not match a specialty desk.

Examples:
- interviews
- team previews
- game recaps
- awards
- league features
- analysis

## Duplicate suppression design
Phase 2D.2 will suppress repeats using both:
- normalized canonical URL
- normalized headline fingerprint

The target duplicate window is 48 hours. A story found on multiple feeds should be posted only once unless a materially new development occurs.
