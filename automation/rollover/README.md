# BLHA Season Rollover

How to move the automations to a new Fantrax league (for example the real
2027-28 league after the 2026-27 test season). Everything about the season
itself (weeks, playoff weeks, number of playoff teams) is read from Fantrax, so
only a few things change.

## Order of steps

1. Create the new league on Fantrax and finish its settings.
2. Wait until the old season's prize payments and Season Ledger are done (30 days after the Championship). The check warns if that countdown is still running.
3. Actions > BLHA Season Rollover > mode `check`, with the new league ID. Fix anything marked FAIL; WARN lines are for you to judge.
4. Switch the league: ask Claude, or run `python automation/rollover/rollover.py --mode write-config --league-id <id> --season-label "2027-28"` and commit `automation/league.yaml`.
5. Actions > BLHA Season Rollover > mode `reset-state`. This removes the old season's saved playoff seeds, weekly report and scoreboard history, League Office reminder history, Commissioner Desk reminders and pick ownership from the `automation-state` branch. The Wire, Automation Health and the minor-eligibility watch carry over and are kept.
6. Date and enable the League Office events in `automation/league-office/events.yaml`. The check lists which ones need it.
7. Run Commissioner Desk, Pick Trades and Playoffs once in `preview` mode, then let the scheduler run. Each first live run saves a baseline instead of posting about old data.
8. Check Automation Health is quiet and the Scoreboard and weekly report previews show the new league.

The league archive (`archive/` on the `automation-state` branch) is never cleared: the new Fantrax season gets its own folder and its first archive run saves a baseline. A season labeled TEST drops out of league history by itself once the first real season is archived.

## What the check compares

12 franchises, 22 regular-season weeks, a six-team playoff with 3 playoff weeks right after Week 22, a future Week 1 start, and no games played yet. Franchise names that still start with "Test" only warn.
