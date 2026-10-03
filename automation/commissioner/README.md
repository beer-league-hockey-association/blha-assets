# BLHA Commissioner Desk

Private reminders for the manual work that keeps the league on track, posted
to a commissioner-only Discord channel. It is the automated companion to the
Commissioner Season Checklists.

## What it sends

Two kinds of reminder share one channel:

**Fantrax-timed (this folder, `tasks.yaml`).** Each task fires once when an
anchor from the Fantrax season calendar plus an offset arrives. Dates move by
themselves when the real 2027-28 calendar is created.

| When | Reminder |
| --- | --- |
| 7 days and 1 day before Week 1 | Before Season essentials |
| Monday after the trade-deadline week | Confirm Fantrax blocks trades |
| Monday after Week 22 | Seed the playoffs, enter consolation round 1, record draft-order inputs |
| 6 hours before each playoff round | Consolation entry, reseeding, championship rules, third place |
| After the Championship | Close-out list, then countdowns at day 14, 25 and 29 for prizes and the Season Ledger |

**Date-based (`../league-office/events.yaml`, channel `commissioner-desk`).**
Things Fantrax cannot know: League Calendar due date, draft announcement,
dues notice, dues deadline and 7-day escalation, last day to open an amendment
vote, trading reopening, scheduler token renewal and Fantrax Premium payment.
They are disabled templates until you give each a `starts_at` and set
`enabled: true`.

Public deadline reminders for owners stay in League Office as before. This
channel is only for you.

## One-time setup

1. In Discord create a private channel visible only to you, for example
   `commissioner-desk`.
2. Channel settings > Integrations > Webhooks > New Webhook. Name it
   `BLHA Commissioner Desk` and copy the URL.
3. In GitHub: repository Settings > Secrets and variables > Actions > New
   repository secret named `BLHA_WEBHOOK_COMMISSIONER_DESK`.
4. Optional: put your Discord user ID (in quotes) in `ping_user_id` under
   `commissioner_desk` in `automation/league.yaml` to be @mentioned.
5. Actions > BLHA Commissioner Desk > Run workflow > mode `test`. You should
   see one `[TEST]` message.

## Checking it

- `preview` mode prints every task with its trigger time and whether it is
  early, due, already sent or too late. Add `at` (for example
  `2027-03-08T08:00`) to see what would post at that moment.
- The BLHA Scheduler starts the workflow hourly, so each reminder arrives
  within an hour of its trigger. Nothing is ever posted twice.
- **Late reminders are never silently dropped.** If GitHub or the scheduler
  was down, a reminder more than 36 hours late is still posted, titled
  `OVERDUE:` with "Was due" and the original time, for 7 days (30 for the
  close-out list, and until the due date for the prize countdowns). A
  countdown such as "Playoffs start in 6 hours" is dropped once that event
  has started, because it would only add noise.
- The first live run records anything already long past as handled, so
  turning this on mid-season does not flood the channel. Reminders that are
  on time at that moment still post.
- Automation Health reports a stale or failing Commissioner Desk run.

## Season rollover

Anchors are remembered in the saved state, so the 30-day prize countdown keeps
running even if you roll Fantrax into the next season before it finishes.
Nothing needs editing each year except dating the events in `events.yaml`.
