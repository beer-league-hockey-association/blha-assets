# BLHA Automation Health

Private commissioner-facing monitoring for the BLHA automation stack.

## Purpose

The health monitor watches production GitHub Actions workflows and reports only meaningful state changes. Quiet successful operation produces no Discord message.

It currently monitors:

- BLHA Wire Engine
- BLHA League Office Automation
- BLHA Fantrax Scoreboard
- BLHA Fantrax Standings
- BLHA Fantrax Weekly Recap
- BLHA Fantrax Playoff Race
- BLHA Fantrax Playoffs

## What triggers an alert

- latest completed scheduled run failed, timed out, was cancelled, or otherwise ended abnormally
- a scheduled workflow has not run within its configured grace period
- GitHub returns no scheduled run for an expected production workflow
- the latest Wire run logged a Discord delivery problem
- the Wire flood guard suppressed posts
- the same Wire source produced a `SOURCE ERROR` in three consecutive scheduled runs

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

Scheduled checks run hourly at minute 27.

Manual modes:

- `preview` — inspect current health in the Actions log only; no Discord delivery and no state change
- `test` — send one controlled webhook test; no health state change
- `live` — evaluate health, post only new/recovered issues, and persist issue state

## Monitoring thresholds

Thresholds are intentionally generous enough to tolerate normal GitHub schedule delays while still catching missing runs:

- Wire Engine: 75 minutes
- League Office: 150 minutes
- Scoreboard: 20 hours
- Standings: 36 hours
- Weekly Recap: 36 hours
- Playoff Race: 36 hours
- Playoffs: 3 hours

These values are configured in `health_config.yaml` and can be tuned without changing the monitor engine.

## Design notes

The health workflow can detect problems in the other GitHub Actions workflows, but no workflow hosted on GitHub can reliably alert Discord during a complete GitHub Actions outage because the monitor itself would also be unable to run. Native GitHub Actions notifications remain the fallback for that platform-level failure mode.
