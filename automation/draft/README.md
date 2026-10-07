# BLHA Draft Center

Discord coverage for the Startup Draft (Article XIII) and the Annual Draft
(Article XIV), driven by Fantrax's own draft data.

## What it posts, and what it deliberately does not

Fantrax already notifies each owner when they are on the clock and shows every
pick live in the draft room, so the Draft Center **never posts on-the-clock or
per-pick messages** (decided Oct 2, 2026). It covers what Fantrax does not:

| Post | Channel | When |
| --- | --- | --- |
| Announcement (date, format, pick clock, nightly pause, draft room) | `📢│draft-announcements` | 30 days before the Fantrax draft date. If the date is set later than that, the announcement goes out at the next countdown step. |
| Countdown | `📢│draft-announcements` | 7 days, 1 day and 1 hour before, then "underway" at the start |
| Official draft order, with traded picks | `📢│draft-announcements` | 7 days before, or on demand (see below) |
| Date changed / order updated | `📢│draft-announcements` | If the Fantrax date or order changes after it was posted |
| Round results | `📋│draft-results` | Each round as soon as all its picks are made |
| Draft Complete summary | `📢│draft-announcements` | When Fantrax marks the draft completed |
| Pick clock ran out / pick skipped | Commissioner Desk (private) | During the draft, once per pick, with the team's timeout count |

If a check runs late and several countdown posts are due at once, only the
most recent one is posted. Nothing is posted twice.

## Where the information comes from

- **Fantrax** (`getDraftResults`, `getDraftPicks`): draft date, state, order,
  rounds, every pick, and traded current-draft picks.
- **`automation/league.yaml` → `draft_center`:** the pick clock (4 hours for
  the Startup Draft, 8 for the Annual Draft) and the nightly pause
  (midnight to 8:00 AM ET), because Fantrax's data feed does not include them.
  The startup/annual choice is automatic: more than 5 rounds is the Startup
  Draft.

## When it runs

Every 15 minutes, but only from 31 days before the Fantrax draft date until a
day after the draft finishes (`when: draft-window` in
`automation/scheduler/schedule.yaml`). The rest of the year it does not run,
and Automation Health does not expect it to.

The first live run after this was installed found the test league's automated
draft already finished, so it recorded that draft and posted nothing.

## One-time setup: two webhooks

Private alerts use the existing Commissioner Desk webhook. The two public
channels each need one:

1. In Discord, open **`📢│draft-announcements`** → the gear icon (**Edit Channel**)
   → **Integrations** → **Webhooks** → **New Webhook**. Name it
   `BLHA Draft Center` and click **Copy Webhook URL**.
2. On GitHub: **blha-assets** → **Settings** → **Secrets and variables** →
   **Actions** → **New repository secret**. Name: `BLHA_WEBHOOK_DRAFT_ANNOUNCEMENTS`,
   value: the URL you copied. **Add secret**.
3. Repeat for **`📋│draft-results`** with the name `BLHA_WEBHOOK_DRAFT_RESULTS`.
4. Check it: **Actions** → **BLHA Draft Center** → **Run workflow** with mode
   `test`. You should see clearly labeled `[TEST]` posts: an announcement and
   the draft order in `📢│draft-announcements`, Round 1 in `📋│draft-results`, a
   completion post, and a sample timeout alert in Commissioner Desk.

## Manual runs (Actions tab → BLHA Draft Center)

- `preview`: prints in the log what a live run would post right now.
- `test`: posts `[TEST]` samples of each post type. Nothing is recorded.
- `live` + item `order` + `force`: posts the official draft order now instead
  of waiting for the 7-day reveal, for example right after the random draw
  (13.2). It will not post again unless the order changes.

## Testing with a slow draft in the test league

1. Reset the test-league rosters in Fantrax.
2. Set up a slow (Live Online Standard) draft in Fantrax with a short pick
   clock, a start time, and the draft order.
3. Set `draft_center.test_pick_clock_minutes` in `automation/league.yaml` to
   the same number of minutes, so the private timeout alert knows the clock.
   If the Fantrax test draft has no overnight pause, also set `pause: null`.
4. Watch `📢│draft-announcements`, `📋│draft-results` and Commissioner Desk. Checks
   run every 15 minutes, so a timeout alert can arrive up to 15 minutes after
   the clock actually runs out.
5. Afterwards, set `test_pick_clock_minutes` back to `null` and `pause` back to
   `["00:00", "08:00"]`.

## Files

- `center.py`: planning, rendering and the live/test/preview runner
- `test_center.py`: offline tests built on the test league's real draft data
- `../blha/draft.py`: reading Fantrax draft data and the active window
- State: `automation/draft/state/draft.json` on the `automation-state` branch
