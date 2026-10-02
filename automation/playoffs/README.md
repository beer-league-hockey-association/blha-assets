# BLHA Playoffs

Live playoff bracket for the league's six-team head-to-head format.

## Format

- Round 1 (Quarterfinals): Seed 3 vs Seed 6, Seed 4 vs Seed 5; Seeds 1 and 2 have byes
- Round 2 (Semifinals): reseed. Seed 1 plays the lowest-ranked survivor, Seed 2 the highest-ranked survivor
- Round 3: Championship
- A tied playoff matchup goes to the higher seed

Playoff weeks, number of playoff teams and the last regular-season week come from Fantrax (`getLeagueInfo`).

## How it runs

The BLHA Scheduler starts it **hourly during playoff weeks only** (`automation/scheduler/schedule.yaml`).

1. **Seeds save themselves.** On the first run after Fantrax has counted every regular-season week, the final standings are saved as the playoff seeds in `state/playoff.json`. Later playoff results can never reshuffle them. If seeds were somehow never saved and the playoffs are already past round 1, the run fails loudly (Automation Health reports it) instead of guessing.
2. **One message per round.** When a round starts, a new bracket message is posted so members are notified. During the round the same message is edited as scores change. Edits are silent.

## Manual modes (Actions tab)

- `preview` — print the bracket payload in the log
- `test` — post a `[TEST] BLHA Playoffs` bracket
- `baseline` — save seeds now (only allowed once Fantrax has counted the whole regular season)
- `live` — what the scheduler runs

`week` renders the bracket as if that playoff week were current, for previewing formats before the playoffs.
