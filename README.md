# BLHA Assets

Official static asset repository for the Beer League Hockey Association.

This repository is public so Discord and Discohook can load the images directly.

## Rules
- Keep the repository public.
- Keep the default branch named `main`.
- Do not rename live image files after webhook templates are in use.
- The approved BLHA primary logo is the master. Supporting assets must not redraw or reinterpret it.
- Webhook templates use the shared BLHA footer divider as a second embed after every message, or as the bottom image of the content embed where full-width alignment is preferred.

## Constitution
A working Version 1.1 Constitution draft is stored at:
`constitution/BLHA_Constitution_v1.1_WORKING_DRAFT.md`

Discord-ready Constitution section templates are stored in:
`templates/constitution/`

These are working drafts and may be replaced when the Constitution is finalized.

## Phase 2D.1C — The Wire Automation
Locked architecture:

- **GitHub Actions = brain**
- **Discord webhooks = delivery**
- **Native integrations = use when superior**
- **Discord bot = save for a later interactive phase**

Source collectors, routing, Daily Faceoff injury parsing, persistent dedupe state, and webhook delivery code are stored in:
`automation/phase-2d1/`

The scheduled engine workflow is:
`.github/workflows/blha-wire-engine.yml`

It currently runs every 15 minutes in **shadow mode**. Shadow mode never posts to Discord. Live delivery is implemented but remains opt-in and requires Discord webhook URLs to be stored as GitHub Actions Secrets.

Operational and rollout instructions:
`automation/phase-2d1/phase-2d1c-operations.md`

PuckPedia native Discord integration is the preferred live transaction feed for NHL trades, signings, and waivers.

## Raw URL base
`https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/`
