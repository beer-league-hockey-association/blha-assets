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

## Phase 2D.1 — The Wire Automation
Architecture, routing rules, source configuration, test plan, and the dry-run collector are stored at:
`automation/phase-2d1/`

A manual GitHub Actions dry-run workflow is stored at:
`.github/workflows/blha-wire-dry-run.yml`

Phase 2D.1 does not post anything to Discord. Live webhook delivery will be enabled only after dry-run routing is approved and webhook URLs are stored in GitHub Actions Secrets.

## Raw URL base
`https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/`
