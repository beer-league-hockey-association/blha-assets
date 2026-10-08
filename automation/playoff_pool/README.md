# BLHA Playoff Pool

A free NHL playoff pool for the 12 owners, run in **🏒│game-day** during the NHL
playoffs (mid-April to June), after the fantasy season is over.

**Just for fun:** no money, no dues, no effect on the fantasy league. The
winner gets the **🦈 Pool Shark** role for the next season and a line in the
league history. Both are cosmetic.

## How it works

It is a **box pool**, so there is no draft order and nobody gains anything from
pick position.

1. **The boxes.** When the NHL playoff bracket has all 16 teams, the pool posts
   10 boxes built from the playoff teams' regular-season stats:
   - **Boxes 1-8:** skaters with at least 20 games, ranked by points per game
     and split into tiers of 8 (box 1 is the top tier).
   - **Box 9, Dark Horses:** the next 8 skaters after skipping one more tier
     below box 8 (ranks 73-80 with the default settings).
   - **Box 10, Goalies:** each playoff team's likely starter (most games
     started).

   Each player has an option number in his box. Players traded away from a
   playoff team are left out (current NHL rosters). Once posted, the boxes never
   change.
2. **Picks.** Each owner picks **one player from each box**. Picks can change
   until the **deadline: the first puck drop of the playoffs** (shown in the
   boxes post; if the NHL hasn't published it yet, the post is edited to show
   it once it has).
3. **Scoring.** Every player scores **BLHA points** (Constitution Article VIII)
   in every NHL playoff game, from the game's boxscore:
   - Skaters: goal 5, assist 2.95, shot on goal 0.55, block 0.35, hit 0.20,
     penalty minute -0.54
   - Goalies: game started 6.5, save 0.49, goal against -5, goal 5, assist 2.95
4. **Standings** post every morning (from 07:30 ET, only when something
   changed): every owner's points, best pick, goalie points and how many of
   their players are already eliminated.
5. **The final post** names the **Pool Shark** the morning after the Stanley
   Cup Final ends.

**Ties:** most points from the goalie (box 10), then the earliest entry.

## Entries

The automation reads entries from one file only: `automation/playoff_pool/entries.yaml`
(format and rules at the top of that file and in `entries.py`).

**Before the League Bot is live (now):** owners DM their picks to the
Commissioner, for example "Box 1: 3, Box 2: Auston Matthews, ...". The
Commissioner adds each owner to `entries.yaml` with the DM's time as `entered`
and commits it before the first standings post (picks are locked at the first
puck drop; an entry `entered` after it is left out). A pick can be the option
number from the boxes post, the player's name or his NHL player id. The run log
lists any pick that isn't in its box.

**Once the League Bot is live:** set `playoff_pool.entries_via: bot` in
`automation/league.yaml` so the boxes post tells owners to use the bot.

- `/pool boxes` shows the boxes and the deadline.
- `/pool pick` (Franchise Owner or Co-Owner): one private menu per box, four
  boxes per page. Picks can change until the deadline, then the bot refuses
  changes. An entry's time is when its last box was first filled.
- `/pool export` (Commissioner): returns `entries.yaml` with every franchise's
  picks. **After the deadline**, commit it as `automation/playoff_pool/entries.yaml`
  on `main` (GitHub: open the file, then the pencil to replace its contents, or
  **Add file > Upload files**). The next pool run reads it.

How the two sides share data, and why there is one manual step: the bot reads
the boxes the automation posted from the public `automation-state` branch
(`automation/playoff_pool/state/boxes.json`). Nothing carries data the other
way: the bot has no GitHub token and the automation can't read the bot's
database, which is how every other bot feature already works (the bot only
reads repository files). Picks are locked at the first puck drop, so one export
after the deadline is all the automation needs.

## Prize

The final post names the Pool Shark. The Commissioner then:

1. gives that owner the **🦈 Pool Shark** role in Discord for the next season
   (and takes it from last year's winner), and
2. adds `pool_shark: <franchise key>` under that Season in
   `automation/history/history.yaml` (the Season the NHL playoffs ended; spring
   2028 is Season 2027). The history site shows it with the other honors.

## Running it

- **Schedule:** `automation/scheduler/schedule.yaml`, job `playoff-pool`: 07:45
  and 19:45 ET, only while `when: nhl-playoffs` holds (from 5 days before the
  NHL regular season's last day until 2 days after the NHL's last scheduled
  playoff date; read from the NHL schedule, see `automation/blha/nhl_playoffs.py`).
  Automation Health checks it only inside that window. After the final post the
  job does nothing.
- **Settings:** `playoff_pool` in `automation/league.yaml` (webhook, players
  per box, minimum games, Dark Horses gap, standings time, entries_via).
- **State:** `automation/playoff_pool/state/pool.json` (post ids, cached game
  stats for boxed players, what was posted) and `state/boxes.json` (the posted
  boxes and deadline, also read by the League Bot), both on the
  `automation-state` branch. Each NHL playoff year starts fresh, so nothing
  needs resetting.

### Preview and test

Actions > **BLHA Playoff Pool** > Run workflow:

- `preview`: prints the boxes post (and standings, after the deadline) in the
  log. Nothing is posted or saved.
- `test`: posts `[TEST]` copies in game-day. Nothing is saved.
- `live`: what the scheduler runs.

Out of season, set **year** to a past NHL playoff year (for example `2025`) with
`preview` or `test` to see the whole pool built from real data. To score a past
year, put an `entries.yaml` with that `year` on a branch and run the workflow
from it. Past-year runs skip the current-roster filter.

## Data and what is unverified

NHL web API (`https://api-web.nhle.com/v1`, read-only), endpoints from the
public reference https://github.com/Zmalski/NHL-API-Reference:

| Endpoint | Used for |
| --- | --- |
| `/playoff-bracket/{year}` | the 16 teams, eliminated teams, the Cup winner |
| `/club-stats/{team}/{season}/2` | regular-season points, games, goalie starts |
| `/roster/{team}/current` | leaving out players traded away |
| `/schedule/{date}` | the first puck drop, every playoff game, the season dates |
| `/gamecenter/{game-id}/boxscore` | each game's goals, assists, shots, blocks, hits, PIM, saves, goals against, starts |

Player game logs (`/player/{id}/game-log/{season}/3`) are not used because they
have no hits or blocked shots.

The reference lists paths but not response fields. The fields read are the ones
the NHL's public responses are known to use, but **they have not been checked
against a live response from this repository** (the build environment cannot
reach the NHL API). Every parser is tolerant (missing fields read as zero or
empty, older boxscore field names are accepted), and the tests use a synthetic
fixture (`automation/tests/fixtures/nhl_playoffs_synthetic.json`). Before the
first real pool, run `preview` with **year** `2025` and check the boxes look
right; if a field name differs, the log shows empty or zero stats rather than
an error.

## Tests

`python automation/playoff_pool/test_pool.py` (box building, scoring math,
tiebreaks, deadline locking, entries parsing, posts, and the whole job against
the fixture) and `python bot/tests/test_pool.py` (the bot's commands). The
scheduler condition is tested in `automation/scheduler/test_scheduler.py`.
