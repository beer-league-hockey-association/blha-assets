# BLHA Phase 2D.4 — Playoff Race

The playoff-race automation provides a concise Fantrax-derived view of:

- current playoff positions
- the immediate bubble
- the gap between the playoff cut and the first team outside
- change detection so unchanged race snapshots do not create Discord spam

## Architecture

- **GitHub Actions = brain**
- **Discord webhooks = delivery**
- **Fantrax = authoritative read-only league data**
- **Discord bot = deferred to the later interactive phase**

## Discord destination

The existing:

- `🏁│playoff-race`

channel is the destination. This module does **not** create or rename a Discord channel.

## Secret

Add the playoff-race channel's Discord webhook URL to GitHub Actions Secrets as:

`BLHA_WEBHOOK_PLAYOFF_RACE`

The webhook should point to the existing `🏁│playoff-race` channel.

## Cadence

The scheduled workflow checks once per day at **12:15 UTC**. The standings workflow runs first at 11:30 UTC, giving the race check a later slot.

The workflow runs even when nothing changed, but the Python state fingerprint prevents an unchanged race view from being posted.

## Rollout

1. Add the `BLHA_WEBHOOK_PLAYOFF_RACE` secret.
2. Run the workflow manually in `preview` mode to verify Fantrax data.
3. Run it in `test` mode to verify Discord delivery.
4. Run it in `baseline` mode to establish the initial race state.
5. Scheduled runs then use `live` mode automatically.

## Important scope decision

The first implementation does **not** claim that a team has clinched or been eliminated. Those statements require proven remaining-matchup and tiebreaker semantics. The current view sticks to facts directly supported by the Fantrax standings feed.

The same clean vertical Discord format used by the approved scoreboard and standings is required here: no decorative emoji, no ASCII table, and no dense fixed-width layout.
