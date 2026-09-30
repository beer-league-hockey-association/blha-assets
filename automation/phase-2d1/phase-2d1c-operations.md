# BLHA Phase 2D.1C — Operations

## Locked architecture

**GitHub Actions = brain**  
**Discord webhooks = delivery**  
**Native integrations = use when superior**  
**Discord bot = save for a later interactive phase**

## What is implemented

- `wire.py` — source collectors + classifier.
- `engine.py` — source precedence, routing, persistent dedupe, shadow/live modes, Discord webhook delivery.
- `sources.yaml` — source registry and authority levels.
- `state/shadow.json` — persistent shadow-mode dedupe state.
- `state/live.json` — persistent live-mode dedupe state.
- `.github/workflows/blha-wire-engine.yml` — runs every 15 minutes in **shadow mode** until deliberately changed.
- Daily Faceoff dedicated injury parser.
- Live Discord delivery code using repository Actions Secrets.

## Current live candidates

### 🚨 breaking-news / 📰 nhl-news
- NHL.com — Tier 0 official.
- Sportsnet — Tier 1 national.

CBS Sports remains discovery/corroboration because its NHL RSS includes promotional/cross-sport noise.

### 🏥 injury-report
- Daily Faceoff dedicated Injury Report page — primary fantasy injury feed.
- NHL.com / Sportsnet can also classify injury headlines.
- NHL.com `Status Report:` headlines are treated as injury/status items.
- Phrases such as `not expected to play`, `will miss`, `expected to miss`, `ruled out`, and `unavailable` route to Injury Report.

The Daily Faceoff parser follows each player-news link in document order and reads the associated position, team, Injury label, status headline, source and timestamp until the next player card. This avoids relying on Daily Faceoff CSS classes or a specific card wrapper.

### 🔄 nhl-transactions
- **PuckPedia native Discord integration is the primary live delivery source for trades, signings and waivers.**
- The GitHub engine still classifies and dedupes NHL transaction stories for monitoring, but `nhl-transactions` is marked as a native-primary channel and the engine does not post those items live by default.
- Elite Prospects transaction feeds stay discovery/cross-check only to avoid bookkeeping noise and duplicate posts.
- The GitHub transaction webhook mapping remains available as a fallback if the native policy is deliberately changed later.

### 🌱 prospect-wire
- American Hockey League official RSS.
- The Hockey Writers Prospects.
- DobberProspects.

USCHO remains discovery-only until NHL-prospect/entity filtering is added; the raw feed is too broad for automatic dynasty posting.

## Dedupe behavior

The engine keeps mode-specific persistent state for **30 days**.

Exact repeats are suppressed for that full retention window using:

1. source/external ID,
2. canonical URL where appropriate,
3. normalized headline fingerprint.

Near-duplicate/fuzzy headline matching is limited to **48 hours** within the same target channel. This prevents repeated coverage of the same event from flooding Discord while still allowing a materially new development days later.

Daily Faceoff injury events intentionally do **not** dedupe by URL because multiple distinct injury updates can share the same player/profile URL. Their event ID uses player + update text + timestamp.

Sources are processed by trust tier so official/Tier 0 material is considered before lower-tier coverage in the same run.

## Shadow mode

Scheduled runs execute every 15 minutes in `shadow` mode. Scheduled runs fetch **live-candidate sources only** by default. Discovery/corroboration feeds are excluded from routine scheduled polling to reduce requests, noise and duplicate processing.

Manual workflow runs expose two extra controls:

- `reset_state` — clears the selected mode's dedupe state before that run; use only for testing/calibration.
- `include_discovery` — temporarily includes CBS, Elite Prospects, Pro Hockey Rumors, USCHO and Reddit discovery sources in the manual run.

Shadow mode:

- fetches enabled live-candidate sources,
- classifies and routes stories,
- prints what **would** be sent,
- never calls Discord webhooks,
- records dedupe state so repeated stories disappear from later shadow runs.

## Live safety rail

The first invocation of `engine.py --mode live` establishes a baseline and sends **zero** Discord messages. This prevents the server from being flooded with whatever happens to be present in each feed at activation time.

Only later new stories are eligible for delivery.

For channels handled by a native-primary integration, such as `nhl-transactions`, later live runs log those events as `NATIVE-PRIMARY SKIP`, record them in dedupe state, and do not send a competing GitHub webhook post.

## Discord webhook secrets

Create one Discord webhook per automated Wire channel, then add these under:

`GitHub → blha-assets → Settings → Secrets and variables → Actions → New repository secret`

Required secret names:

- `BLHA_WEBHOOK_BREAKING_NEWS`
- `BLHA_WEBHOOK_NHL_NEWS`
- `BLHA_WEBHOOK_INJURY_REPORT`
- `BLHA_WEBHOOK_NHL_TRANSACTIONS`
- `BLHA_WEBHOOK_PROSPECT_WIRE`

Never commit webhook URLs into repository files.

The transaction webhook is retained as a fallback. While PuckPedia is the native primary, the GitHub engine will not use it for ordinary transaction delivery.

## PuckPedia native integration

For `🔄│nhl-transactions`:

1. Discord → channel settings / Server Settings → Integrations → Webhooks.
2. Create a webhook dedicated to PuckPedia in `🔄│nhl-transactions`.
3. Copy the webhook URL.
4. In PuckPedia, open the Discord webhook notification setup page.
5. Paste the webhook URL and add it.
6. Confirm the PuckPedia welcome/test post appears in `🔄│nhl-transactions`.

Keep this native integration separate from the BLHA News Wire webhook identity.

## Rollout sequence

1. Confirm a fresh shadow baseline produces clean routing and formatting.
2. Confirm an immediate second shadow run produces zero new shadow posts and only duplicates.
3. Create the five Discord webhooks and store them as GitHub Actions Secrets.
4. Configure PuckPedia native delivery for `🔄│nhl-transactions`.
5. Manually run **BLHA Wire Engine** with mode `live` once. It will baseline and send nothing.
6. Wait for a genuinely new event, then run live manually again to verify one-message delivery.
7. After validation, change the scheduled workflow from shadow to live.

## Why no Discord bot yet

The Wire is a one-way ingestion and delivery problem. Webhooks require no bot process, gateway connection, intents, or always-on bot hosting. A custom bot should be introduced later only when the BLHA needs interactive Discord behavior such as slash commands, role workflows, buttons, league queries, draft interaction, or moderation.
