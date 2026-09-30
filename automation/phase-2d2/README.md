# BLHA Phase 2D.2 — League Office Automation

## Purpose

Automate commissioner-controlled calendar milestones and deadline reminders without a paid service or a Discord bot.

**GitHub Actions = scheduler/brain**  
**Discord webhooks = delivery**  
**Fantrax remains authoritative for league gameplay and transactions**

## Channels

- `📅│league-calendar` — primary destination for scheduled league milestones and reminders.
- `📢│league-announcements` — receives only selected high-priority reminder copies defined by `announcement_reminders`.

## Required GitHub Actions secrets

- `BLHA_WEBHOOK_LEAGUE_CALENDAR`
- `BLHA_WEBHOOK_LEAGUE_ANNOUNCEMENTS`

Never commit Discord webhook URLs to the repository.

## Event configuration

Events live in `events.yaml` and remain disabled until the actual league dates are finalized. This prevents placeholder dates from ever reaching Discord.

Each event can define:

- unique `id`
- `enabled`
- `title`
- `type`
- `starts_at` as ISO-8601 with explicit UTC offset
- `channel`
- `priority`
- `description`
- `reminders`
- `announcement_reminders`

Example:

```yaml
- id: trade-deadline-2028
  enabled: true
  title: "BLHA Trade Deadline"
  type: deadline
  starts_at: "2028-02-28T23:59:00-05:00"
  channel: league-calendar
  priority: high
  description: "The BLHA in-season trade window closes at this deadline."
  reminders: [14d, 7d, 3d, 1d, 3h, 1h, start]
  announcement_reminders: [7d, 1d, 3h, 1h, start]
```

The date above is an example only and is not a BLHA league date.

## Scheduling

`.github/workflows/blha-league-office.yml` checks every 30 minutes at `:07` and `:37`.

The automation uses `America/New_York` as the league timezone and Discord native timestamps in posts, so managers see the correct local rendering.

A reminder is eligible within a 20-minute run window. Persistent state prevents the same event/reminder/channel combination from posting more than once.

## Modes

### `dry-run`

Prints due reminders but does not call Discord and does not persist state.

### `test`

Sends a clearly labeled controlled test message to either `league-calendar` or `league-announcements`. It does not use a real league event and does not modify reminder state.

### `live`

Posts due reminders and persists delivery state to `state/league_ops.json`.

Scheduled runs use `live`. Because all initial events are disabled, nothing can post until an actual event is deliberately dated and enabled.

## Initial event templates

The repository currently contains disabled templates for:

- Startup Draft
- Annual Draft
- Trade Deadline
- Dues Deadline
- Opening Night
- Playoffs Begin

More can be added later for voting deadlines, roster cutdowns, keeper/minors deadlines, playoff rounds, offseason reopening, annual meetings, or commissioner-defined milestones.

## Rollout

1. Create a Discord webhook in `📅│league-calendar` named `BLHA League Office — Calendar`.
2. Create a Discord webhook in `📢│league-announcements` named `BLHA League Office — Announcements`.
3. Add the two webhook URLs to GitHub Actions Secrets using the exact secret names above.
4. Run `BLHA League Office Automation` in `test` mode once for each channel.
5. Leave every real event disabled until its actual date is finalized.
6. When a date is official, edit `events.yaml`, set the timestamp, and change `enabled` to `true`.

## Why this is the next module

The League Office calendar is deterministic, commissioner-controlled, useful year-round, and does not depend on a Fantrax API or a paid integration. It is therefore a cleaner second automation module than standings/scoreboard ingestion, which should be built only after the Fantrax data path is proven.
