# BLHA League Bot

An always-on Discord bot for the league. It runs league votes by the Constitution's rules (one vote per franchise, cast by the Franchise Owner), answers rules and eligibility questions, shows each franchise its own Fantrax picture, checks trades for compliance, runs a weekly Pick'em, and takes picks for the just-for-fun NHL Playoff Pool. It stays off until owners join; the Constitution blocks amendment votes until the Offseason after Season 2027 (20.1).

Fantrax is only ever read, never written. The bot posts nothing that Fantrax already sends (lineups, trades, waivers, draft picks).

## What it does

### Votes

| Command | Who | Rule |
| --- | --- | --- |
| `/proposal new` | Franchise Owner or Commissioner | Posts a written proposal: affected rule, exact new text, Season it takes effect (20.2) |
| `/proposal from-thread` | Commissioner | Used inside a **💡│league-suggestions** forum thread: opens the same proposal form with the thread title filled in. After posting, it replies in the thread with a link to the proposal and adds the **🗳️ SENT TO VOTE** tag if one is set |
| `/vote open` | Commissioner | Opens voting on a proposal once 7 days have passed, only in the Offseason, only before 20.1's date, and only if it closes before that Season's dues deadline (20.3, 20.4) |
| `/vote elect` | Any Franchise Owner | Interim or permanent Commissioner: majority of active franchises (19.5) |
| `/vote status` | Anyone | Which franchises have voted (never how) |
| `/vote cancel` | Commissioner | Withdraws an open amendment vote; election votes always run to the end |
| `/franchise orphan` | Commissioner | An orphaned franchise has no vote; the threshold stays 8 (2.3) |
| `/panel draw` | Commissioner or Assistant | Draws a three-owner Review Panel from unaffected franchises and posts it in rulings-log (19.4) |

- **Ballots** are buttons on the vote post (a menu for elections). Only the voter sees the confirmation, and a franchise can change its vote until it closes.
- **League Services Allocation changes** use the `services` proposal type: the Commissioner's franchise sits out and approval needs 8 of the other 11 (3.6).
- **Closing:** each vote closes on its own after 7 days and posts the result with the passed or failed stamp. With `publish_ballots: true` the result lists every franchise's ballot.
- **Reminder:** 24 hours before closing, the bot pings the franchise roles that haven't voted.
- **Offseason check:** it reads Fantrax (the same `automation/league.yaml` league). If Fantrax can't be reached, amendment votes refuse to open rather than guess.
- **Records:** every proposal, ballot, result, orphan change and panel draw is saved in an audit table on the Railway volume.

### League tools

| Command | Who | What it shows |
| --- | --- | --- |
| `/rule <query>` | Anyone | The Constitution by section (`12.4`), article (`XII`, `Article 12`) or keyword (`prepayment`, up to 3 best matches). Public by default; `ephemeral: True` shows it only to you |
| `/deadlines` | Anyone | The next 3 dates on the League Calendar (`automation/league-office/events.yaml`, enabled and dated events only), in each member's own time zone. Private Commissioner Desk reminders are never shown |
| `/minor <player>` | Anyone | Age on NHL opening day, career NHL regular-season games, the limit that applies (skaters 100, goalies 50) and **BLHA minor-eligible: YES/NO** (7.2, 7.3). Add `team: CAR` when two players share a name |
| `/myteam` | Franchise Owner or Co-Owner | Private. Roster counts against the 6.1 limits, future picks owned and traded away, paid-through Season from the League Ledger, this Week's opponent and score, and the next 2 deadlines. FAAB isn't in Fantrax's data feed, so it says "check Fantrax" |
| `/tradecheck` | Franchise Owner, Co-Owner or Commissioner | Compliance only, never value: future 1st and 2nd prepayment (12.2 to 12.4), roster limits after the trade (6.1), the trade window (11.6), and a reminder of what it can't detect (11.3, 11.4, 11.5). Private by default; `post: True` posts it in the channel |
| `/pickem leaderboard` | Anyone | Pick'em season standings |

- **Minor eligibility** uses the NHL's player search and stats, the same source as the nightly minor-eligibility watch. Age is measured on the first day of the NHL regular season, which is the start of Fantrax Week 1 (Article V). Before Fantrax has the next Season's calendar, October 1 is used and labeled as an estimate. Every answer says "By NHL data. Fantrax's age calculation is final (7.2)."
- **Trade check assumptions:** players are typed as names (`Quinn Hughes, Elias Pettersson`) and matched to the giving team's Fantrax roster; picks as `2029 1st, 2028 3rd`. Incoming players fill open active spots first, then reserve, unless listed in `to_minors`. The trade deadline is Sunday 11:59 PM ET at the end of Week 20, from the Fantrax calendar. The reopening date comes from the `commissioner-trading-reopens` event in events.yaml once it has a date.
- **Paid through** comes from the League Ledger's Pick Clearance tab (`BLHA_LEDGER_CLEARANCE_CSV`, the same link the Pick Trades alert uses). Without it, the bot says so and asks for a manual check.

### Pick'em

Each Fantrax Week, owners pick the winner of every matchup.

1. When a Week is final (Monday morning), the bot posts the next Week's matchups in the Pick'em channel with a **Make my picks** button. Week 1 is posted 3 days before it starts.
2. The button opens a private menu per matchup, four per page. Picks can be changed until they lock.
3. Picks lock when the Week's scoring period starts; the button is removed.
4. When the Week is final, each correct pick scores 1 point. An exact tie scores nobody. The bot posts the Week's results and the season leaderboard (skipped if nobody played).

Regular-season Weeks only; Fantrax's schedule has seeds, not teams, for playoff Weeks. Who plays is set by `pickem.players` in config.yaml (`owner`, `co_owner` or both). Picks are stored on the Railway volume.

### Playoff Pool

A free NHL playoff box pool after the fantasy season (no money, no effect on the league; the winner gets the Pool Shark role). The GitHub automation runs it: it builds and posts the boxes, scores the picks and posts standings (`automation/playoff_pool/README.md`). The bot only takes picks.

| Command | Who | What it does |
| --- | --- | --- |
| `/pool boxes` | Anyone | The 10 boxes and the pick deadline (private by default) |
| `/pool pick` | Franchise Owner or Co-Owner | Private menus, one per box, four boxes per page. One entry per franchise; picks can change until the first puck drop of the NHL playoffs |
| `/pool export` | Commissioner | The picks as `entries.yaml`, the file the automation reads |

- **Boxes** come from the automation's `automation/playoff_pool/state/boxes.json` on the public `automation-state` branch, re-read every 10 minutes (`BLHA_POOL_BOXES_URL` overrides the address).
- **Picks** are stored on the Railway volume. The automation can't read the bot's database, so after the deadline the Commissioner runs `/pool export` and commits the file as `automation/playoff_pool/entries.yaml`. Also set `playoff_pool.entries_via: bot` in `automation/league.yaml` so the boxes post points owners to `/pool pick`.
- An entry's time (the last tiebreak) is when its last box was first filled.

## Setup (when owners have joined)

**1. Create the bot in Discord**
1. Go to discord.com/developers/applications, click **New Application** and name it "BLHA League Bot".
2. In **Bot**, upload `brand/kit/02_avatars_icons/blha-bot-avatar-round-512.png`, click **Reset Token** and copy the token. Keep it private.
3. On the same page, turn on **Server Members Intent**. Panel draws need it to see who holds each franchise role.
4. In **OAuth2 > URL Generator**, tick the scopes `bot` and `applications.commands`. Then tick the permissions View Channels, Send Messages, Send Messages in Threads, Embed Links, Read Message History, Manage Threads and Mention Everyone. Mention Everyone lets the bot ping franchise roles that aren't mentionable; Manage Threads lets it tag suggestion threads.
5. Open the generated URL and add the bot to the BLHA server.

**2. Fill in `bot/config.yaml`**
1. In Discord, go to **User Settings > Advanced** and turn on **Developer Mode**.
2. Copy these IDs into config.yaml: the server, **🗳️│league-voting**, **⚖️│rulings-log**, the Commissioner role, the Assistant Commissioner role (optional), the Franchise Owner role and the Co-Owner role.
3. Copy the IDs of the Pick'em channel (`pickem_channel_id`) and the **💡│league-suggestions** forum (`suggestions_forum_id`).
4. Optional: `scheduled_for_vote_tag_id`, the ID of the forum's **🗳️ SENT TO VOTE** tag, added to a suggestion when it becomes a proposal. Discord can't copy a tag's ID, so start the bot once with `suggestions_forum_id` set: its log lists the forum's tags as `Name (ID)`.
5. Replace the 12 placeholder franchises with real names, each franchise's role ID and its `fantrax_team_id`. The IDs in the file are the 2026-27 test league's; when the real league exists, run the **BLHA Pick Trades** workflow in preview mode to list them. Mark your own franchise `commissioner: true`.
6. Set `amendment_votes_from` to the day after the Season 2027 Championship ends. Add each Season's dues deadline under `dues_deadlines`.
7. Check it with `BLHA_CHECK=1 python3 bot/main.py`. The check should report 0 warnings. At startup the bot also warns if a `fantrax_team_id` isn't a team in the Fantrax league.

**3. Deploy on Railway (about $5 a month on the Hobby plan)**
1. In Railway, click **New Project > Deploy from GitHub repo** and pick `beer-league-hockey-association/blha-assets`.
2. In the service's **Settings**, set **Config file path** to `bot/railway.json`. That file sets the install command and `python bot/main.py` as the start command.
3. In **Variables**, add:
   - `DISCORD_TOKEN`: the token from step 1
   - `BLHA_DB_PATH` = `/data/blha_votes.db`
   - `BLHA_LEDGER_CLEARANCE_CSV`: the published-CSV link of the League Ledger's Pick Clearance tab, the same value as the GitHub secret of that name. It powers "Paid through" in `/myteam` and the prepayment check in `/tradecheck`.
4. Right-click the service, choose **Attach Volume** and mount it at `/data`. Without a volume, votes and Pick'em picks are lost on every redeploy.
5. Deploy. The log should say "BLHA League Bot logged in as …", and the slash commands appear in the server within a minute.

## How it reads league data

- **Fantrax** (read-only): the season calendar and schedule (`getLeagueInfo`), rosters (`getTeamRosters`), draft picks (`getDraftPicks`), player names (`getPlayerIds`) and live scores (`getMatchupScores`), through the shared client in `automation/blha/`. Reads are cached for 3 to 30 minutes (player names for 12 hours) and run off the event loop, so a slow Fantrax never freezes the bot.
- **NHL stats API:** player search and career totals for `/minor`, through `automation/commissioner/minors.py`, cached for hours.
- **League Calendar:** `automation/league-office/events.yaml`, read the same way as the League Office automation.
- **Playoff Pool boxes:** the automation's `boxes.json` on the `automation-state` branch (`raw.githubusercontent.com`), cached for 10 minutes.
- The bot's league logic lives in plain modules next to `app.py` (`constitution`, `deadlines`, `minor`, `team`, `trade`, `pickem`, `pool`), so it is tested without Discord.

## Tests

- `python bot/tests/test_bot.py` runs the voting rules, storage, embed and config tests offline. The Discord command tests (every command registers, ballot and Pick'em views build) run where `discord.py` is installed, which includes the regression-tests workflow.
- `python bot/tests/test_pool.py` tests the Playoff Pool commands: reading the boxes, the picks menus' limits, storage, the deadline and the export the automation reads back.
- `python bot/tests/test_league_features.py` tests `/rule`, `/deadlines`, `/minor`, `/myteam`, `/tradecheck`, Pick'em and the data caching against the Fantrax samples in `automation/tests/fixtures/`, with no network.
