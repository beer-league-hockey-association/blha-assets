# BLHA Voting Bot

An always-on Discord bot that runs league votes by the Constitution's rules: one vote per franchise, cast by the Franchise Owner. It stays off until owners join; the Constitution blocks amendment votes until the Offseason after Season 2027 (20.1).

## What it does

| Command | Who | Rule |
| --- | --- | --- |
| `/proposal new` | Franchise Owner or Commissioner | Posts a written proposal: affected rule, exact new text, Season it takes effect (20.2) |
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

## Setup (when owners have joined)

**1. Create the bot in Discord**
1. Go to discord.com/developers/applications, click **New Application** and name it "BLHA Voting".
2. In **Bot**, upload `brand/kit/02_avatars_icons/blha-bot-avatar-round-512.png`, click **Reset Token** and copy the token. Keep it private.
3. On the same page, turn on **Server Members Intent**. Panel draws need it to see who holds each franchise role.
4. In **OAuth2 > URL Generator**, tick the scopes `bot` and `applications.commands`. Then tick the permissions View Channels, Send Messages, Embed Links, Read Message History and Mention Everyone. Mention Everyone lets the bot ping franchise roles that aren't mentionable.
5. Open the generated URL and add the bot to the BLHA server.

**2. Fill in `bot/config.yaml`**
1. In Discord, go to **User Settings > Advanced** and turn on **Developer Mode**.
2. Copy these IDs into config.yaml: the server, **league-voting**, **rulings-log**, the Commissioner role, the Assistant Commissioner role (optional) and the Franchise Owner role.
3. Replace the 12 placeholder franchises with real names and each franchise's role ID. Mark your own franchise `commissioner: true`.
4. Set `amendment_votes_from` to the day after the Season 2027 Championship ends. Add each Season's dues deadline under `dues_deadlines`.
5. Check it with `BLHA_CHECK=1 python3 bot/main.py`. The check should report 0 warnings.

**3. Deploy on Railway (about $5 a month on the Hobby plan)**
1. In Railway, click **New Project > Deploy from GitHub repo** and pick `beer-league-hockey-association/blha-assets`.
2. In the service's **Settings**, set **Config file path** to `bot/railway.json`. That file sets the install command and `python bot/main.py` as the start command.
3. In **Variables**, add `DISCORD_TOKEN` (the token from step 1) and `BLHA_DB_PATH` = `/data/blha_votes.db`.
4. Right-click the service, choose **Attach Volume** and mount it at `/data`. Without a volume, votes are lost on every redeploy.
5. Deploy. The log should say "Logged in as BLHA Voting", and the slash commands appear in the server within a minute.

## Tests

`python bot/tests/test_bot.py` runs the rules, storage, embed and config tests offline. The two Discord command tests run where `discord.py` is installed, which includes the regression-tests workflow.
