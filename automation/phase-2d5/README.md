# BLHA Phase 2D.5 — Playoffs

This module will provide the Discord playoff-bracket view for the existing BLHA league-competition area.

## Architecture

- GitHub Actions = brain
- Discord webhooks = delivery
- Fantrax = authoritative read-only league data
- Discord bot = deferred to the later interactive phase

## Phase start

The first step is schema discovery only. The probe reads Fantrax playoff configuration and the website's read-only playoff standings view. It does not post to Discord and does not modify Fantrax.

## Rollout

1. Run the schema snapshot with the test league ID.
2. Confirm the playoff structure and matchup/round fields exposed by Fantrax.
3. Build the clean Discord playoff format using the same approved format as scoreboard, standings, weekly recap, and playoff race.
4. Test webhook delivery.
5. Establish a baseline.
6. Enable scheduled live checks once the data-change semantics are proven.

## Format requirement

Use the approved BLHA competition format:

- no decorative emoji
- no ASCII tables
- clean readable team/matchup blocks
- concise metadata
- same visual structure as the approved scoreboard/standings/recap/playoff-race messages
