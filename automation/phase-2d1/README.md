# BLHA Phase 2D.1 — The Wire Automation Architecture

## Goal
Run a reliable, low-noise NHL news pipeline for the Beer League Hockey Association Discord server.

## Current production state
The Wire is **live** on GitHub Actions. Scheduled runs occur four times per hour at `:03`, `:18`, `:33`, and `:48` UTC-minute positions. Manual runs default to `shadow` mode for safe testing.

Production safeguards include:
- persistent deduplication with a 30-day / 5,000-item cap
- fuzzy duplicate suppression
- baseline-first live initialization
- per-run and per-channel flood guards
- source-level failures that do not crash the whole Wire
- limited parallel source collection
- one retry for transient source failures
- Discord retry handling for HTTP 429 and 5xx responses
- `allowed_mentions` disabled on automated posts
- Automation Health monitoring for stale runs, persistent source failures, and repeated flood-guard events
- resilient Git state persistence with pull/rebase/retry handling

## Discord destinations
- `🚨│breaking-news` — only major, time-sensitive NHL developments.
- `📰│nhl-news` — broader national NHL news that does not fit a more specific desk.
- `🏥│injury-report` — injury, IR/LTIR, surgery, return and availability updates. When an exact normalized Fantrax roster match exists, the post also identifies the BLHA team that owns the player.
- `🔄│nhl-transactions` — trades, signings, waivers, recalls, assignments and contract moves. **PuckPedia is the active primary live source for this channel.**
- `🌱│prospect-wire` — prospects, AHL, NCAA, CHL, international development and draft-related updates.
- `💬│news-desk` — human discussion only; no automation.

## Active source stack
### Primary live sources
- NHL.com Latest News
- Sportsnet NHL RSS
- Daily Faceoff Injury Report
- American Hockey League RSS
- The Hockey Writers Prospects RSS
- DobberProspects RSS

### Discovery / corroboration sources
- CBS Sports NHL
- Elite Prospects transaction feeds
- Pro Hockey Rumors
- USCHO
- r/hockey

ESPN NHL is currently disabled because repeated scheduled probes returned an empty feed.

## Native transaction integration
PuckPedia's Discord integration is active and is preferred for live NHL transaction posts. The Wire still classifies transaction events for dedupe/diagnostics but suppresses true transaction-event delivery to avoid duplicate posts. General analysis that merely mentions a trade or contract is routed back to NHL News instead of being silently discarded.

## Routing priority
Each item should normally post to one channel only:
1. Breaking News
2. Injury Report
3. NHL Transactions
4. Prospect Wire
5. NHL News

Transaction classification intentionally uses action-oriented patterns instead of broad words such as `trade`, `contract`, or `extension`, so analysis headlines are not incorrectly swallowed by the native transaction route.

## Breaking-news standard
Breaking News is intentionally hard to trigger. Examples include:
- major NHL trade involving an established fantasy asset
- season-ending or indefinite injury to a significant player
- major suspension
- retirement of a significant active player
- head coach / general manager firing or hiring with league-wide impact
- major league rule or schedule development

Routine signings, recalls, minor injuries, daily lineup notes, rumors, analysis, opinion and game recaps do not belong in Breaking News.

## Security
Discord webhook URLs are credentials and belong only in GitHub Actions Secrets. The repository should never contain webhook URLs, Fantrax passwords, session cookies, or other account credentials.

Current webhook secret names:
- `BLHA_WEBHOOK_BREAKING_NEWS`
- `BLHA_WEBHOOK_NHL_NEWS`
- `BLHA_WEBHOOK_INJURY_REPORT`
- `BLHA_WEBHOOK_NHL_TRANSACTIONS`
- `BLHA_WEBHOOK_PROSPECT_WIRE`

## Fantrax enrichment
The public read-only Fantrax endpoints are used only to enrich injury alerts with BLHA ownership when an exact normalized player-name match can be made. Failure to read Fantrax does not stop Wire delivery; enrichment simply falls back to no ownership tag.

League transaction history is authentication-gated by Fantrax and is not currently ingested by the Wire.

## Maintenance
GitHub scheduled workflows are best-effort rather than real-time. Automation Health uses deliberately tolerant stale thresholds so a single delayed cron event does not create noise.

GitHub may disable scheduled workflows in public repositories after long periods of repository inactivity, so the BLHA repository should still be checked during the offseason.
