# BLHA The Wire — Discord Webhook Plan

## Webhook identity
Use the existing **News Bot** visual identity for automated public hockey feeds.

Recommended webhook name:
`BLHA News Desk`

Use the finalized BLHA webhook avatar or a future dedicated News Bot avatar.

## Required channel webhooks
Create one webhook in each automated channel:

- `🚨│breaking-news`
- `📰│nhl-news`
- `🏥│injury-report`
- `🔄│nhl-transactions`
- `🌱│prospect-wire`

Do not create an automation webhook in `💬│news-desk`.

## GitHub Actions secret names
Store each URL at:
**Repository → Settings → Secrets and variables → Actions → New repository secret**

Use these exact names:

- `BLHA_WEBHOOK_BREAKING_NEWS`
- `BLHA_WEBHOOK_NHL_NEWS`
- `BLHA_WEBHOOK_INJURY_REPORT`
- `BLHA_WEBHOOK_NHL_TRANSACTIONS`
- `BLHA_WEBHOOK_PROSPECT_WIRE`

Never paste the actual webhook URLs into a committed file, issue, README, screenshot, or public chat.

## Automated post style
Each automated story should contain:
- source name
- headline
- direct article/post link
- routing label
- publication time when available

Avoid copying article bodies. The purpose is discovery and league discussion, not republishing source content.
