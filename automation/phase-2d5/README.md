# BLHA Phase 2D.5 — Playoffs

This module provides the Discord playoff-bracket view for the BLHA league-competition area.

## Verified Fantrax data

The test league schema probe established:

- lastRegularSeasonPeriod = 22
- numPlayoffTeams = 6
- firstPlayoffPeriod = 23
- mergePlayoffPeriods = false
- playoff periods are 23, 24, and 25
- public getMatchupScores returns playoff matchup objects
- the private fxpa VIEW=PLAYOFFS request returns WARNING_NOT_LOGGED_IN without a Fantrax session

The automation therefore does not depend on the private authenticated playoff view.

## Bracket logic

For the six-team Fantrax H2H format:

- Round 1: Seed 3 vs Seed 6
- Round 1: Seed 4 vs Seed 5
- Seeds 1 and 2 receive byes
- Round 2 reseeds: Seed 1 faces the lowest-ranked remaining team, meaning the surviving team with the largest seed number
- Round 2 reseeds: Seed 2 faces the highest-ranked remaining team, meaning the surviving team with the smallest seed number
- Example: if Seeds 3 and 6 advance, the semifinals are Seed 1 vs Seed 6 and Seed 2 vs Seed 3
- Round 3: Championship
- A tied playoff matchup is awarded to the higher seed

The final regular-season seed baseline is preserved in `state/playoff.json` so playoff results cannot accidentally change the original seeding.

## Architecture

- GitHub Actions = brain
- Discord webhooks = delivery
- Fantrax = authoritative read-only league data
- Discord bot = deferred to the later interactive phase

Discord delivery uses the shared retry helper in `automation/discord_webhook.py`, which handles transient network failures, Discord rate limits, and common temporary HTTP failures with bounded retries.

## Modes

- preview — render the current bracket payload; no Discord delivery or state change
- test — send a clearly labeled test embed
- baseline — record final regular-season seeds once the regular season is complete
- live — post only when the bracket/scores materially change

The live fingerprint ignores the embed render timestamp, so repeated checks of an unchanged bracket do not create duplicate Discord posts.

The workflow checks every six hours at minute 7. Outside the playoff window it performs the read-only check without posting.

## Rollout

1. Schema discovery — complete.
2. Build public-endpoint playoff bracket — complete.
3. Run preview and verify the Discord payload.
4. Run test to verify webhook delivery.
5. Establish the final seed baseline after Period 22.
6. Let scheduled live checks publish playoff changes.

## Format requirement

Use the approved BLHA competition format:

- `BLHA Competition Desk` sender identity
- gold Competition Desk accent
- no decorative emoji
- no ASCII tables
- clean readable team/matchup blocks
- concise metadata
- same visual structure as the approved scoreboard, standings, weekly recap, and playoff-race messages
