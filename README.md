# BLHA Assets

Official static asset and automation repository for the Beer League Hockey Association.

This repository is public so Discord and Discohook can load approved images directly.

## Rules
- Keep the repository public.
- Keep the default branch named `main`.
- Do not rename live image files after webhook templates are in use.
- The approved BLHA primary logo is the master. Supporting assets must not redraw or reinterpret it.
- Webhook templates use the shared BLHA footer divider as a second embed after every message, or as the bottom image of the content embed where full-width alignment is preferred.
- Discord webhook URLs belong in GitHub Actions Secrets and must never be committed to the repository.

## Constitution
A working Version 1.1 Constitution draft is stored at:
`constitution/BLHA_Constitution_v1.1_WORKING_DRAFT.md`

Discord-ready Constitution section templates are stored in:
`templates/constitution/`

These are working drafts and may be replaced when the Constitution is finalized.

## Automation architecture

The approved architecture is:

- **GitHub Actions = scheduler/brain**
- **Discord webhooks = delivery**
- **Fantrax = authoritative read-only league gameplay data where applicable**
- **Native integrations = use when superior**
- **Discord bot = save for a later interactive phase**

Shared resilient Discord webhook delivery for League Office, Fantrax competition, matchup previews, playoffs, and automation health is implemented in:
`automation/discord_webhook.py`

The helper retries transient network failures, Discord rate limits, and common temporary HTTP failures with bounded backoff. The Wire retains its specialized delivery path because it already has source-specific retry and flood-control behavior.

## Phase 2D.1C — The Wire Automation

Source collectors, routing, Daily Faceoff injury parsing, persistent dedupe state, flood protection, and webhook delivery code are stored in:
`automation/phase-2d1/`

The scheduled engine workflow is:
`.github/workflows/blha-wire-engine.yml`

Scheduled runs execute every 15 minutes in **live mode** at minutes 3, 18, 33, and 48. Manual workflow dispatch defaults to **shadow mode** for safe testing. Shadow mode never posts to Discord; live delivery requires the appropriate Discord webhook URLs in GitHub Actions Secrets.

Operational and rollout instructions:
`automation/phase-2d1/phase-2d1c-operations.md`

PuckPedia native Discord integration is the preferred live transaction feed for NHL trades, signings, and waivers.

## Phase 2D.2 — League Office

Commissioner-controlled dates and deadline reminders are stored in:
`automation/phase-2d2/`

The League Office uses `America/New_York` for DST-safe local scheduling. Reminders never post before their trigger, and a bounded catch-up window protects against delayed GitHub scheduled runs. Real league events remain disabled until their dates are finalized.

## Phase 2D.3 — Fantrax League Competition

Fantrax read-only automation covers:

- `📊│scoreboard` — current matchup scores
- `📈│standings` — current league standings
- `📰│weekly-recap` — completed scoring-period recaps
- weekly matchup previews delivered through the Competition Desk

All Discord-facing competition posts use the clean vertical embed standard in `automation/DISCORD_AUTOMATION_STYLE.md`.

## Phase 2D.4 — Playoff Race

The playoff-race workflow is:
`.github/workflows/blha-fantrax-playoff-race.yml`

It checks daily after the standings workflow and posts only when the tracked playoff picture materially changes. It uses the existing `🏁│playoff-race` channel; no Discord channel is created by the automation.

Clinching and elimination claims are intentionally deferred until remaining-matchup and tiebreaker semantics are proven rather than inferred.

## Phase 2D.5 — Playoffs

The playoff module is stored in:
`automation/phase-2d5/`

It preserves final regular-season seeds, applies six-team reseeding so Seed 1 faces the lowest-ranked surviving opponent, and fingerprints semantic bracket content rather than render timestamps. The scheduled playoff workflow checks every six hours and remains a no-op outside the playoff window.

## Regression checks

Automation regression tests cover shared Discord retry behavior, League Office timing/catch-up behavior, playoff reseeding, and playoff semantic deduplication. The dedicated regression workflow compiles the affected automation modules and runs these checks whenever relevant code or configuration changes.

## Raw URL base
`https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/`
