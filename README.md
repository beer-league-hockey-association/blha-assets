# BLHA Assets

Official static asset and automation repository for the Beer League Hockey Association.

This repository is public so Discord and Discohook can load approved images directly.

## Rules
- Keep the repository public.
- Keep the default branch named `main`.
- Do not rename live image files after webhook templates are in use.
- The approved BLHA primary logo is the master. Supporting assets must not redraw or reinterpret it.
- Webhook templates use the shared BLHA footer divider as a second embed after every message, or as the bottom image of the content embed where full-width alignment is preferred.
- Discord webhook URLs belong in GitHub Actions Secrets and must never be committed to the repository.

## Constitution
A working Version 1.1 Constitution draft is stored at:
`constitution/BLHA_Constitution_v1.1_WORKING_DRAFT.md`

Discord-ready Constitution section templates are stored in:
`templates/constitution/`

These are working drafts and may be replaced when the Constitution is finalized.

## Automation architecture

The approved architecture is:

- **GitHub Actions = brain**, with timing owned by the **BLHA Scheduler**
- **Discord webhooks = delivery**
- **Fantrax = authoritative read-only league gameplay data where applicable**
- **Native integrations = use when superior**
- **Discord bot = save for a later interactive phase**

## League settings

League-wide settings live in one file: `automation/league.yaml` (Fantrax league ID, season label, report time, playoff race start week, webhook secret names). When the real 2027-28 Fantrax league is created, change `league_id` and `season_label` there; week dates, playoff weeks and playoff team count are read from Fantrax automatically.

## Scheduling and the season calendar

All automation timing lives in one file: `automation/scheduler/schedule.yaml`.

The **BLHA Scheduler** workflow (`.github/workflows/blha-scheduler.yml`) runs every 15 minutes, started by an external timer (cron-job.org) with GitHub cron as a backup. It starts each workflow in **live** mode when it is due and catches up after any delay, so a late check never skips a job.

Each job can be limited to parts of the season (preseason, regular season, playoffs, offseason). The current phase is worked out from Fantrax's own week dates, so the scoreboard and weekly report switch on when the season starts and the playoff bracket only runs during playoff weeks. Manual runs from the Actions tab ignore the calendar, so anything can be tested at any time. Setup and troubleshooting: `automation/scheduler/README.md`.

| Automation | When it runs |
| --- | --- |
| The Wire | Every 15 minutes, all year |
| League Office | Every 30 minutes, all year |
| Automation Health | Hourly, all year |
| Competition Desk (weekly report) | 08:00 and 20:00 ET, preseason through playoffs; posts only when something is due |
| Live scoreboard | Hourly, regular season and playoffs |
| Playoff bracket | Hourly, playoff weeks only |

Shared Discord delivery (`automation/discord_webhook.py`) retries transient network failures, Discord rate limits and temporary HTTP errors, and can edit a message it posted earlier so live views update in place. Shared Fantrax and season-calendar code lives in `automation/blha/`.

## Phase 2D.1C — The Wire Automation

Source collectors, routing, Daily Faceoff injury parsing, persistent dedupe state, flood protection, and webhook delivery code are stored in:
`automation/phase-2d1/`

The scheduled engine workflow is:
`.github/workflows/blha-wire-engine.yml`

The BLHA Scheduler starts the Wire every 15 minutes in **live mode**. When more stories arrive in one run than the flood guard allows as individual posts, the rest of each channel's stories are combined into one roundup post instead of being dropped. Manual workflow dispatch defaults to **shadow mode** for safe testing. Shadow mode never posts to Discord; live delivery requires the appropriate Discord webhook URLs in GitHub Actions Secrets.

Operational and rollout instructions:
`automation/phase-2d1/phase-2d1c-operations.md`

PuckPedia native Discord integration is the preferred live transaction feed for NHL trades, signings, and waivers.

## Phase 2D.2 — League Office

Commissioner-controlled dates and deadline reminders are stored in:
`automation/phase-2d2/`

The League Office uses `America/New_York` for DST-safe local scheduling. Reminders never post before their trigger, and a bounded catch-up window protects against delayed GitHub scheduled runs. Real league events remain disabled until their dates are finalized.

## Competition Desk — weekly report

Code: `automation/competition/desk.py` · Workflow: `.github/workflows/blha-competition-desk.yml`

Fantrax weeks end at the first NHL game on Monday evening, so by Monday morning every game of the week is final. At **8:00 AM ET** that morning the Competition Desk posts, in order:

1. `📰│weekly-recap` — results of the week that just finished
2. `📈│standings` — standings after that week (final standings after the last regular-season week)
3. `🏁│playoff-race` — from **Week 16** through the last regular-season week
4. Matchup preview for the week starting that evening (scoreboard channel)

If Fantrax has not yet counted the finished week in its standings at 8:00 AM, standings and the playoff race wait and go out at the 8:00 PM check. Nothing is ever posted twice for the same week, and a failed post is retried automatically.

## Live scoreboard

Code: `automation/competition/scoreboard.py` · Workflow: `.github/workflows/blha-fantrax-scoreboard.yml`

One scoreboard message per week in `📊│scoreboard`, posted when the week starts and **edited in place** every hour as scores change (edits do not notify members). Monday morning it gets a final update marked **Final** and stays in the channel as the record of that week.

## Playoffs

Code: `automation/playoffs/` · Workflow: `.github/workflows/blha-fantrax-playoffs.yml`

Runs only during the playoff weeks. Seeds are saved automatically once Fantrax has counted the final regular-season week, and six-team reseeding gives Seed 1 the lowest-ranked surviving opponent. Each round gets one bracket message (a new post when the round starts), edited in place as scores change.

All Competition Desk posts use the clean vertical embed standard in `automation/DISCORD_AUTOMATION_STYLE.md`.

## Regression checks

Automation regression tests cover the season calendar (against real Fantrax week dates), the weekly report, the live scoreboard, playoff seeding, scheduler due-time logic and retries, Wire routing and roundup posts, health-monitor run filtering, shared Discord retry behavior, League Office timing/catch-up behavior, playoff reseeding, and playoff semantic deduplication. The dedicated regression workflow compiles every automation module and runs these checks whenever relevant code or configuration changes.

## Raw URL base
`https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/`
