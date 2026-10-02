# BLHA Automation Health

Private commissioner-facing monitoring for the BLHA automation stack.

## Purpose

The health monitor watches production GitHub Actions workflows and reports only meaningful state changes. Quiet successful operation produces no Discord message.

It currently monitors:

- BLHA Scheduler (which starts every workflow below)
- BLHA Wire Engine
- BLHA League Office Automation
- BLHA Fantrax Matchup Preview
- BLHA Fantrax Scoreboard
- BLHA Fantrax Standings
- BLHA Fantrax Weekly Recap
- BLHA Fantrax Playoff Race
- BLHA Fantrax Playoffs

## What triggers an alert

- latest completed live run failed, timed out, was cancelled, or otherwise ended abnormally
- a workflow has not had a live run within its configured threshold
- GitHub returns no live run for an expected production workflow
- the latest Wire run logged a Discord delivery problem (including a roundup that failed to post)
- the Wire had more overflow stories than fit in a roundup post in consecutive runs
- the same Wire source produced a `SOURCE ERROR` in three consecutive runs

A "live run" is either a GitHub cron run or a run the BLHA Scheduler started with `mode=live` (its run name ends in `— live`). Manual preview, test, shadow, and dry-run runs are ignored.

The monitor deduplicates active issues. A continuing problem is not reposted every hour. When a previously reported issue clears, one recovery message is sent.

## Discord setup

Create one private commissioner/staff channel for technical operations, recommended name:

`⚙️│automation-health`

Create a webhook in that channel named:

`BLHA Systems Desk — Automation Health`

Store the webhook URL in the repository Actions secret:

`BLHA_WEBHOOK_AUTOMATION_HEALTH`

The visible automated sender is standardized as `BLHA Systems Desk`.

## Workflow

`.github/workflows/blha-automation-health.yml`

The BLHA Scheduler starts a live health check every 60 minutes.

Manual modes:

- `preview` — inspect current health in the Actions log only; no Discord delivery and no state change
- `test` — send one controlled webhook test; no health state change
- `live` — evaluate health, post only new/recovered issues, and persist issue state

## Monitoring thresholds

Each threshold is the maximum age of the latest live run before a "Workflow appears stale" alert:

- Scheduler: 45 minutes (a stale scheduler usually means the external cron-job.org timer stopped)
- Wire Engine: 60 minutes
- League Office: 3 hours
- Matchup Preview: 10 hours
- Playoffs: 10 hours
- Scoreboard: 20 hours
- Standings: 36 hours
- Weekly Recap: 36 hours
- Playoff Race: 36 hours

These values are configured in `health_config.yaml` and can be tuned without changing the monitor engine.

## Design notes

The health workflow can detect problems in the other GitHub Actions workflows, but no workflow hosted on GitHub can reliably alert Discord during a complete GitHub Actions outage because the monitor itself would also be unable to run. Native GitHub Actions notifications remain the fallback for that platform-level failure mode.

The health check is itself started by the BLHA Scheduler. If the external timer stops, the scheduler's backup GitHub cron still starts it, just less often, and the first check that runs reports the stale scheduler.
