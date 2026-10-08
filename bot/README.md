# BLHA League Bot

An always-on Discord bot for the league. It runs league votes by the Constitution's rules (one vote per franchise, cast by the Franchise Owner), answers rules and eligibility questions, shows each franchise its own Fantrax picture, checks trades for compliance, and runs three just-for-fun games: a weekly Pick'em, the BLHA Bucks play-money sportsbook and the annual Awards Ballot. It stays off until owners join; the Constitution blocks amendment votes until the Offseason after Season 2027 (20.1).

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

### BLHA Bucks

A play-money sportsbook in **🏒│game-day** (`book_channel_id`). Owners bet against the spread on the matchups their own franchise isn't playing in.

**Just for fun.** Bucks are not money. They never affect FAAB, draft picks, lineups, standings or any fantasy result, and they can't be traded, sold or converted into anything (Article XI lists the only assets that change hands). Because nobody can bet on their own matchup, a bet never gives anyone a reason to play a Week differently, and there is nothing to collude over (Article XVII).

| Command | Who | What it does |
| --- | --- | --- |
| `/book lines` | Anyone | This Week's lines, and whether bets are open, locked or settled (private) |
| `/book bet` | Players (`book.players`) | Pick a matchup and a side from the menus and an amount. Betting again on the same matchup replaces the bet; amount 0 removes it. Your own franchise's matchup is never offered and is refused if typed |
| `/book mybets` | Players | Your bets this Week, Bucks left, and your season profit and rank (private) |
| `/book leaderboard` | Anyone | Season profit standings |

1. **Lines** post with the Week's matchups, on the Pick'em calendar: when the previous Week is final (Monday morning), and 3 days before Week 1. Each team's line comes from its average score over its last 3 final Weeks, the same recent-form window the Power Rankings use (`automation/competition/weekly.py`). The spread is the difference between the two averages, rounded to the nearest half point (halves round away from zero). A team with no final Week yet, such as everyone in Week 1, makes the matchup a pick'em (0).
2. **Bucks:** every player has **100 Bucks** for each regular-season Week. Bets for that Week can total 100 at most. Unused Bucks don't carry over; next Week starts at 100 again whatever happened.
3. **Lock:** bets lock when the Week's scoring period starts in Fantrax.
4. **Settle:** when the Week is final (and Fantrax has every score, or a day later regardless), each bet is graded against the spread at even money: a win adds the stake to your season profit, a loss subtracts it, and a push (the score lands exactly on the line, including an exact tie on a pick'em) returns it. A matchup Fantrax has no result for is returned too. An exact tie with a spread means the underdog covers. The bot posts the Week's results against the spread, everyone's net for the Week and the season profit leaderboard (no post if nobody bet).
5. **The Sharp role:** after the last regular-season Week is settled, the season profit leader gets the role named in `book.sharp_role` (default **💸 Sharp**), and last Season's holder loses it. Tied leaders share it. Players with no settled bets aren't ranked.

Regular-season Weeks only. Bets, lines and results are stored on the Railway volume, and every bet is in the audit table.

### Awards Ballot

After the BLHA Championship, owners vote on the Season's awards with a ranked ballot.

| Command | Who | What it does |
| --- | --- | --- |
| `/awards open` | Commissioner | Opens the ballot for a Season (refused while the regular season or playoffs are running). Lists the hand-picked nominees, proposes the rest, and posts the ballot with a **Fill out my ballot** button in `awards_ballot_channel_id` (default **🗳️│league-voting**). `deadline` sets when it closes (default `awards.ballot_days`) |
| `/awards nominate` | Commissioner or Assistant Commissioner | Adds a nominee while the ballot is open, never one involving your own franchise |
| `/awards close` | Commissioner | Closes the ballot now. It also closes by itself at the deadline |
| `/awards results` | Commissioner | After the close: posts the winners in **🏆│hall-of-champions** and writes the JSON export (below), also attached to the reply. `again: True` posts them a second time |
| `/awards status` | Anyone | Which franchises have returned a ballot (never how they voted) |

**The awards and their nominees**

| Award | Nominees |
| --- | --- |
| GM of the Year | Every active franchise. Owner-voted only: nobody picks the field |
| Trade of the Year | The Season's trades, listed by the Commissioner: `Franchise 3 + Franchise 7: Hughes for a 2029 1st; Franchise 2 + Franchise 9: ...` |
| Waiver Steal of the Year | Listed by the Commissioner: `Franchise 3: Quinn Hughes; Franchise 5: ...` |
| Comeback Franchise | The franchises that climbed the most places in the final regular-season standings since last Season (top 3, ties included), or a list from the Commissioner. Needs last Season's final standings, which the bot saves from Fantrax at each `/awards open`, so it starts with the second Season |
| Bust of the Year | Listed by the Commissioner (`Franchise 3: the player`); left blank, the biggest falls in the standings since last Season (top 3, ties included) |

An award without nominees is left off the ballot; the Commissioner's reply says why. Each nominee names its franchise(s) before a colon so the bot can apply the rules below. Up to 25 nominees per award.

**Voting.** One ballot per franchise, cast by the Franchise Owner (2.2); Co-Owners and orphaned franchises don't vote. For each award, a 1st, 2nd and 3rd choice from private menus: 5, 3 and 1 points. An owner can't rank their own franchise for GM of the Year or Comeback Franchise; it isn't offered, and a crafted vote is refused and never counted. Your own trade or pickup is fine. Ballots can be changed until `/awards close` or the deadline.

**Winners.** Most points wins. A tie goes to the franchise with the most first-place votes; if it's still tied, the award is shared.

**The Commissioner's own franchise (19.3, recusal spirit).** The Commissioner opens the ballot but can't nominate their own franchise for an award with hand-picked nominees (Trade, Waiver Steal, Comeback, Bust); `/awards open` refuses the list until it's removed. A neutral Assistant Commissioner, one whose franchise isn't involved, can add that nominee with `/awards nominate`. Nominees the bot proposes from the standings, and GM of the Year's full field, include every franchise. The Commissioner's ballot counts exactly like everyone else's. This is in the command help and on the ballot post.

Awards carry no money and change nothing in the standings or the draft.

**Export for the history site.** `/awards results` writes `awards.export_path` (default `blha_awards.json` next to `BLHA_DB_PATH`, so `/data/blha_awards.json` on Railway) and attaches the same file to the Commissioner's reply, ready to commit for a future trophy case. The file keeps every Season; posting a Season again replaces only that Season.

```json
{
  "format": "blha-awards/1",
  "updated_at": "2028-04-20T15:00:00+00:00",
  "seasons": {
    "2027": {
      "season": 2027,
      "closed_at": "2028-04-20T03:59:59+00:00",
      "ballots": 11,
      "eligible_franchises": 12,
      "points": {"first": 5, "second": 3, "third": 1},
      "awards": [
        {
          "key": "gm",
          "name": "GM of the Year",
          "shared": false,
          "decided_by": "points",
          "ballots": 11,
          "winners": [
            {"nominee": "Franchise 3", "franchises": ["Franchise 3"], "fantrax_team_ids": ["mvh0gxh2mumuxoo4"],
             "detail": "", "points": 41, "first_place_votes": 6}
          ],
          "results": [
            {"nominee": "Franchise 3", "franchises": ["Franchise 3"], "fantrax_team_ids": ["mvh0gxh2mumuxoo4"],
             "detail": "", "points": 41, "first": 6, "second": 3, "third": 2}
          ]
        }
      ]
    }
  }
}
```

- `seasons` is keyed by Season year as text. `awards` lists only the awards that were on the ballot, in ballot order; `key` is `gm`, `trade`, `waiver`, `comeback` or `bust`.
- `winners` is empty when nobody ranked anyone, and has more than one entry when the award is shared. `decided_by` is `points`, `first-place votes`, `shared`, or empty for no votes.
- `results` is every nominee, best first. `nominee` is the ballot label (a trade's description, a player, or the franchise name); `franchises` are config names and `fantrax_team_ids` the matching Fantrax IDs at the time, which map to franchise keys through `team_ids` in `automation/history/history.yaml`. `detail` is set for proposed Comeback and Bust nominees, e.g. `10th to 2nd, up 8`.
- `ballots` counts franchises that ranked at least one nominee (per award inside each award).

## Setup (when owners have joined)

**1. Create the bot in Discord**
1. Go to discord.com/developers/applications, click **New Application** and name it "BLHA League Bot".
2. In **Bot**, upload `brand/kit/02_avatars_icons/blha-bot-avatar-round-512.png`, click **Reset Token** and copy the token. Keep it private.
3. On the same page, turn on **Server Members Intent**. Panel draws need it to see who holds each franchise role.
4. In **OAuth2 > URL Generator**, tick the scopes `bot` and `applications.commands`. Then tick the permissions View Channels, Send Messages, Send Messages in Threads, Embed Links, Attach Files, Read Message History, Manage Threads, Manage Roles and Mention Everyone. Mention Everyone lets the bot ping franchise roles that aren't mentionable; Manage Threads lets it tag suggestion threads; Manage Roles lets it move the **💸 Sharp** role; Attach Files sends the Awards export.
5. Open the generated URL and add the bot to the BLHA server.

**2. Fill in `bot/config.yaml`**
1. In Discord, go to **User Settings > Advanced** and turn on **Developer Mode**.
2. Copy these IDs into config.yaml: the server, **🗳️│league-voting**, **⚖️│rulings-log**, the Commissioner role, the Assistant Commissioner role (optional), the Franchise Owner role and the Co-Owner role.
3. Copy the IDs of the Pick'em channel (`pickem_channel_id`) and the **💡│league-suggestions** forum (`suggestions_forum_id`).
4. For BLHA Bucks and the Awards Ballot, copy **🏒│game-day** into `book_channel_id` and **🏆│hall-of-champions** into `hall_of_champions_channel_id`. `awards_ballot_channel_id` is optional (blank posts the ballot in **🗳️│league-voting**). Create a role named exactly **💸 Sharp** (or change `book.sharp_role`) and drag the bot's own role above it in **Server Settings > Roles**, or Discord won't let the bot assign it.
5. Optional: `scheduled_for_vote_tag_id`, the ID of the forum's **🗳️ SENT TO VOTE** tag, added to a suggestion when it becomes a proposal. Discord can't copy a tag's ID, so start the bot once with `suggestions_forum_id` set: its log lists the forum's tags as `Name (ID)`.
6. Replace the 12 placeholder franchises with real names, each franchise's role ID and its `fantrax_team_id`. The IDs in the file are the 2026-27 test league's; when the real league exists, run the **BLHA Pick Trades** workflow in preview mode to list them. Mark your own franchise `commissioner: true`.
7. Set `amendment_votes_from` to the day after the Season 2027 Championship ends. Add each Season's dues deadline under `dues_deadlines`.
8. Optional settings: `book.players` (who bets: `owner`, `co_owner` or both; default owners only), `book.sharp_role`, `awards.ballot_days` (default 7, at most 30) and `awards.export_path`.
9. Check it with `BLHA_CHECK=1 python3 bot/main.py`. The check should report 0 warnings. At startup the bot also warns if a `fantrax_team_id` isn't a team in the Fantrax league.

**3. Deploy on Railway (about $5 a month on the Hobby plan)**
1. In Railway, click **New Project > Deploy from GitHub repo** and pick `beer-league-hockey-association/blha-assets`.
2. In the service's **Settings**, set **Config file path** to `bot/railway.json`. That file sets the install command and `python bot/main.py` as the start command.
3. In **Variables**, add:
   - `DISCORD_TOKEN`: the token from step 1
   - `BLHA_DB_PATH` = `/data/blha_votes.db`
   - `BLHA_LEDGER_CLEARANCE_CSV`: the published-CSV link of the League Ledger's Pick Clearance tab, the same value as the GitHub secret of that name. It powers "Paid through" in `/myteam` and the prepayment check in `/tradecheck`.
4. Right-click the service, choose **Attach Volume** and mount it at `/data`. Without a volume, votes, Pick'em picks, BLHA Bucks bets, Awards ballots and the Awards export are lost on every redeploy.
5. Deploy. The log should say "BLHA League Bot logged in as …", and the slash commands appear in the server within a minute.

## How it reads league data

- **Fantrax** (read-only): the season calendar and schedule (`getLeagueInfo`), rosters (`getTeamRosters`), draft picks (`getDraftPicks`), player names (`getPlayerIds`), live and final scores (`getMatchupScores`, also for BLHA Bucks lines and settlement) and standings (`getStandings`, for the Awards Ballot's Comeback and Bust), through the shared client in `automation/blha/`. Reads are cached for 3 to 30 minutes (player names for 12 hours) and run off the event loop, so a slow Fantrax never freezes the bot.
- **Power Rankings math:** BLHA Bucks reuses the recent-form window and placeholder-week handling of `automation/competition/weekly.py`.
- **NHL stats API:** player search and career totals for `/minor`, through `automation/commissioner/minors.py`, cached for hours.
- **League Calendar:** `automation/league-office/events.yaml`, read the same way as the League Office automation.
- The bot's league logic lives in plain modules next to `app.py` (`constitution`, `deadlines`, `minor`, `team`, `trade`, `pickem`, `book`, `awards`), so it is tested without Discord.

## Tests

- `python bot/tests/test_bot.py` runs the voting rules, storage, embed and config tests offline. The Discord command tests (every command registers, ballot and Pick'em views build) run where `discord.py` is installed, which includes the regression-tests workflow.
- `python bot/tests/test_league_features.py` tests `/rule`, `/deadlines`, `/minor`, `/myteam`, `/tradecheck`, Pick'em and the data caching against the Fantrax samples in `automation/tests/fixtures/`, with no network.
- `python bot/tests/test_book_awards.py` tests BLHA Bucks (line math, locking, the own-matchup ban, settlement with pushes and ties, the weekly reset, the leaderboard, the Sharp role) and the Awards Ballot (nominations and the Commissioner's recusal, ballot rules and the self-vote ban, 5-3-1 tallies and tie-breaks, closing, the results post and export). Its Discord flow tests run a whole BLHA Bucks season and Awards Ballot through the slash commands where `discord.py` is installed.
