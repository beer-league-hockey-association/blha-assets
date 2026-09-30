# BLHA The Wire — Source Matrix

Research date: 2026-09-30

## Source philosophy
The Wire should favor primary and specialist hockey sources, not sheer volume. A source may be reputable but still be unsuitable for automatic Breaking News if it publishes rumors, analysis, fan commentary, or speculative pieces.

### Trust tiers
- **Tier 0** — official league/source; suitable for automatic Breaking News when the headline itself clearly supports it.
- **Tier 1** — established national or specialist hockey outlet with strong editorial reliability.
- **Tier 2** — reputable secondary/analysis outlet; suitable for normal feeds but not automatic Breaking News.
- **Tier 3** — community/discovery source; never authoritative on its own.

## Recommended active sources

| Source | Method | Tier | Primary use | Breaking? | Notes |
|---|---|---:|---|---|---|
| NHL.com Latest News | HTML | 0 | Breaking + general NHL news | Yes | Official NHL source. Primary authority for league announcements, status reports and major news. |
| Sportsnet NHL | RSS | 1 | Breaking + general NHL news | Yes | Strong national NHL newsroom; active NHL-specific RSS. |
| CBS Sports NHL | RSS | 1 | General NHL news + corroboration | Yes, high-impact only | Official CBS NHL RSS endpoint. Useful redundancy against Sportsnet/NHL.com. |
| PuckPedia | Native Discord integration | 1 | Trades, signings, waivers | N/A; transaction channel | Direct Discord integration is preferable to scraping. Use as the primary `nhl-transactions` machine feed. |
| Elite Prospects NHL Transactions | RSS | 1 | Transaction backup | No | Structured league transaction feed. Excellent for catching movement that news sites may not headline. |
| Elite Prospects Recalls/Reassignments | RSS | 1 | Recalls / assignments | No | High-value fantasy movement feed. |
| Elite Prospects Extensions | RSS | 1 | Contract extensions | No | Structured contract movement feed. |
| American Hockey League | RSS | 1 | AHL / development news | No | Official AHL feed; useful for prospect movement and development stories. |
| The Hockey Writers — Prospects | RSS | 2 | Prospect analysis | No | Dedicated prospect feed. Best used in `prospect-wire`, never as automatic Breaking News. |
| USCHO | RSS | 2 | NCAA prospect ecosystem | No | Long-running college-hockey outlet. Useful to dynasty managers for NCAA development. |
| r/hockey | RSS | 3 | Discovery only | Never | Useful for surfacing reporter posts and stories, but noisy and not authoritative. |

## Strong candidates requiring a feed probe or parser

| Source | Why it is valuable | Proposed treatment |
|---|---|---|
| Daily Faceoff Player News | Player-centric injuries, trades, signings, roster moves, waivers and goalie news. Very fantasy-relevant. | Build an HTML parser and route only selected update types to `injury-report` / `nhl-transactions`. |
| College Hockey News | Independent comprehensive NCAA reporting since 2005 and offers RSS feeds. | Use for `prospect-wire`; finalize exact feed endpoint or HTML parser. |
| DobberProspects | Dynasty/fantasy-focused prospect analysis and NHL organizational prospect coverage. | Probe `https://dobberprospects.com/feed/`; if stable, send to `prospect-wire`. |
| Pro Hockey Rumors | Focused on NHL trades, free agency and roster news. | Probe `https://www.prohockeyrumors.com/feed`; Tier 2 and never auto-breaking without corroboration. |
| The Hockey News | Major long-running hockey publication with broad NHL/prospect coverage. | Probe current RSS endpoint or scrape Latest News; use mostly `nhl-news` / `prospect-wire`. |
| Elite Prospects AHL/NCAA/OHL/WHL/QMJHL transaction feeds | Excellent structured development-league movement data. | Keep discovery-only unless we can filter for NHL-affiliated / draft-relevant players to prevent flooding. |
| USA Hockey / NTDP | Official U.S. national-team and development-program news; pages expose RSS subscriptions. | Excellent prospect source once exact SportsEngine RSS endpoints are captured. |

## Sources deliberately not promoted to primary

### ESPN NHL RSS
Retained only for periodic testing. The 2026-09-30 GitHub dry run returned no entries.

### Reddit
Discovery only. It can surface reporter posts quickly, but community posts, highlights and speculation make it unsuitable as a direct authoritative feed.

### Generic rumor sites
Do not use as Breaking News authorities. Rumor-specific items should either stay in general discussion/news or require corroboration from an official/Tier 1 source.

## Channel source plan

### 🚨 breaking-news
Primary: NHL.com, Sportsnet, CBS Sports.

Rules: only high-impact events; do not auto-post ordinary signings, depth transactions, opinion, predictions or rumors.

### 📰 nhl-news
NHL.com + Sportsnet + CBS Sports. The Hockey News may join after its feed is verified. General analysis sources should be deduplicated aggressively.

### 🏥 injury-report
Primary future source: Daily Faceoff Player News parser. Secondary: NHL.com Status Report and Tier 1 news headlines.

### 🔄 nhl-transactions
Primary: PuckPedia direct Discord integration. Backup/cross-check: Elite Prospects NHL Transactions, Recalls/Reassignments and Extensions. Pro Hockey Rumors may join as Tier 2 after feed validation.

### 🌱 prospect-wire
AHL official RSS, The Hockey Writers Prospects, USCHO. Add College Hockey News and DobberProspects after endpoint validation. Elite Prospects development-league feeds should remain filtered/discovery-only unless NHL relevance can be determined.

## Dedupe policy
A single event may be reported by several sources. Live automation should suppress duplicates for at least 48 hours by normalized URL, headline fingerprint, and eventually entity/event matching. Priority should favor official/Tier 0, then Tier 1, then Tier 2.
