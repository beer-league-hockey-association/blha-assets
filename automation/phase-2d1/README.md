# BLHA Phase 2D.1 — The Wire Automation Architecture

## Goal
Build a reliable, low-noise NHL news pipeline for the Beer League Hockey Association Discord server.

## Platform choice
The initial automation backbone is **GitHub Actions** because the BLHA repository is public, standard GitHub-hosted Actions are free for public repositories, and scheduled workflows can later run as often as every five minutes.

Phase 2D.1 is intentionally **dry-run only**. Nothing posts to Discord until routing is tested and the Discord webhook URLs are stored as GitHub Actions secrets.

## Discord destinations
- `🚨│breaking-news` — only major, time-sensitive NHL developments.
- `📰│nhl-news` — broader national NHL news that does not fit a more specific desk.
- `🏥│injury-report` — injury, IR/LTIR, surgery, return and availability updates.
- `🔄│nhl-transactions` — trades, signings, waivers, recalls, assignments and contract moves.
- `🌱│prospect-wire` — prospects, AHL, NCAA, CHL, international development and draft-related updates.
- `💬│news-desk` — human discussion only; no automation.

## Initial source stack
### Tier 1 — primary automatic sources
1. **ESPN NHL RSS** — `https://www.espn.com/espn/rss/nhl/news`
2. **Sportsnet NHL RSS** — `https://www.sportsnet.ca/hockey/nhl/feed/`

### Tier 2 — discovery source
3. **Reddit r/hockey RSS** — `https://www.reddit.com/r/hockey/.rss`

Reddit is discovery-only in the first release. It may route to `nhl-news`, `injury-report`, `nhl-transactions`, or `prospect-wire`, but it is not allowed to trigger `breaking-news` automatically until we have proven source validation.

## Planned second-stage sources
- NHL.com Latest News / Status Report
- Daily Faceoff injury report
- Official team transaction/news pages where practical
- X/Twitter only if a stable, compliant and reasonably priced feed method is available

## Routing priority
Each item should normally post to **one** channel only, using this priority:

1. Breaking News
2. Injury Report
3. NHL Transactions
4. Prospect Wire
5. NHL News

This avoids flooding multiple channels with the same story.

## Breaking-news standard
Breaking News is intentionally hard to trigger. Examples include:
- major NHL trade involving an established fantasy asset
- season-ending or indefinite injury to a significant player
- major suspension
- retirement of a significant active player
- head coach / general manager firing or hiring with league-wide impact
- major league rule or schedule development

Routine signings, recalls, minor injuries, daily lineup notes, rumors, analysis, opinion and game recaps do **not** belong in Breaking News.

## Security
Discord webhook URLs are credentials. They must be stored only in GitHub Actions **Secrets** and never committed to this public repository.

Planned secret names:
- `BLHA_WEBHOOK_BREAKING_NEWS`
- `BLHA_WEBHOOK_NHL_NEWS`
- `BLHA_WEBHOOK_INJURY_REPORT`
- `BLHA_WEBHOOK_NHL_TRANSACTIONS`
- `BLHA_WEBHOOK_PROSPECT_WIRE`

## Workflow phases
### 2D.1 — Architecture + dry run
- source list
- route rules
- dry-run collector
- no Discord posting

### 2D.2 — Live Wire MVP
- add webhook secrets
- persistent deduplication
- manual live test
- enable schedule

### 2D.3 — Source expansion
- NHL.com
- Daily Faceoff
- official teams
- optional social feeds

### 2D.4 — Fantrax integration
- league transactions
- waiver results
- trades
- draft events where technically feasible

## Maintenance warning
GitHub automatically disables scheduled workflows in public repositories after 60 days with no repository activity. The BLHA repo should be checked periodically during the offseason.