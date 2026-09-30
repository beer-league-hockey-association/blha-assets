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

### 🔄 nhl-transactions
- **PuckPedia native Discord integration is preferred for live trades, signings and waivers.**
- Elite Prospects transaction feeds stay discovery/cross-check only to avoid bookkeeping noise and duplicate posts.

### 🌱 prospect-wire
- American Hockey League official RSS.
- The Hockey Writers Prospects.
- DobberProspects.
- USCHO.

## Dedupe behavior

The engine keeps mode-specific persistent state for 72 hours and suppresses repeats for 48 hours using:

1. source/external ID,
2. canonical URL,
3. normalized headline fingerprint,
4. near-duplicate title similarity within the same target channel.

Sources are processed by trust tier so official/Tier 0 material is considered before lower-tier coverage in the same run.

## Shadow mode

Scheduled runs execute every 15 minutes in `shadow` mode. Shadow mode:

- fetches all enabled sources,
- classifies and routes live-candidate stories,
- prints what **would** be sent,
- never calls Discord webhooks,
- records dedupe state so repeated stories disappear from later shadow runs,
- prints discovery-only sources separately without treating them as live posts.

## Live safety rail

The first invocation of `engine.py --mode live` establishes a baseline and sends **zero** Discord messages. This prevents the server from being flooded with whatever happens to be present in each feed at activation time.

Only later new stories are eligible for delivery.

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

The transaction webhook can remain unused by the GitHub engine while PuckPedia native delivery is preferred, but keeping the secret/mapping available gives us a fallback for future non-PuckPedia transaction sources.

## PuckPedia native integration

For `🔄│nhl-transactions`:

1. Discord → channel settings / Server Settings → Integrations → Webhooks.
2. Create a webhook dedicated to PuckPedia in `🔄│nhl-transactions`.
3. Copy the webhook URL.
4. In PuckPedia, open the Discord webhook notification setup page.
5. Paste the webhook URL and add it.
6. Confirm the PuckPedia welcome/test post appears in `🔄│nhl-transactions`.

PuckPedia currently sends league-wide NHL trades, contract signings and waiver activity. Keep this native integration separate from the BLHA News Wire webhook identity.

## Rollout sequence

1. Run scheduled shadow mode for at least several cycles.
2. Inspect routing, especially Daily Faceoff injuries and prospect volume.
3. Create the five Discord webhooks and store them as GitHub Actions Secrets.
4. Configure PuckPedia native delivery for `🔄│nhl-transactions`.
5. Manually run **BLHA Wire Engine** with mode `live` once. It will baseline and send nothing.
6. Wait for a genuinely new event, then run live manually again to verify one-message delivery.
7. After validation, change the scheduled workflow from shadow to live.

## Why no Discord bot yet

The Wire is a one-way ingestion and delivery problem. Webhooks require no bot process, gateway connection, intents, or always-on bot hosting. A custom bot should be introduced later only when the BLHA needs interactive Discord behavior such as slash commands, role workflows, buttons, league queries, draft interaction, or moderation.
