# BLHA Morning Skate

Code: `morning.py` · Workflow: `.github/workflows/blha-morning-skate.yml` ·
Channel: `📸│media` (webhook secret `BLHA_WEBHOOK_MEDIA`, the same one the
Wire's podcast posts use) · Settings: `morning_skate` in `automation/league.yaml`

Every morning at about **8:30 AM ET**, after a night with NHL regular-season or
playoff games, the channel gets:

1. **LAST NIGHT IN THE NHL** — one line per final game, winner in bold, OT/SO
   marked, with **Recap** and **Condensed** links to NHL.com (a missing link
   is left out). A very long night splits into a second embed.
2. **THE BLHA GOAL REEL** — only when a player on a BLHA roster scored or
   assisted: one field per franchise, e.g.
   `McDavid (EDM) — goal [▶](clip), assist`. ▶ opens the goal on NHL.com.
   Nobody is mentioned.
3. Up to **3** YouTube highlight links (`max_youtube`), each on its own so
   Discord shows the playable video. Games with the most BLHA goals + assists
   go first, then overtime/shootout games, then the highest-scoring games.

Nights without NHL games post nothing. It runs all year, so the NHL playoffs
are covered after the BLHA season ends.

**Links only.** Nothing is downloaded or re-uploaded; Discord builds the
previews from NHL.com and YouTube.

## Data

- NHL score API, `https://api-web.nhle.com/v1/score/YYYY-MM-DD`: finals, links,
  goals with clip links and assists. Shootout goals are not counted.
- NHL YouTube channel feed (latest ~15 uploads): videos titled
  `Oilers vs. Ducks | NHL Highlights | Oct 7, 2026`. Shorts and other clips are
  ignored. On a busy night a game's video may already have scrolled out of the
  feed; the next-ranked game is used instead.
- Fantrax `getTeamRosters` + `getPlayerIds` for BLHA ownership, matched with
  the Wire's roster matching (`automation/wire/roster.py`): name, narrowed by
  NHL team. A name two NHL players share (the two Elias Petterssons in
  Vancouver) is skipped; wrong credit is worse than none. While every BLHA
  roster is empty, the Goal Reel is skipped and the player directory is not read.

The test fixtures (`automation/tests/fixtures/nhl_score_2026-10-07_synthetic.json`,
`nhl_youtube_feed_synthetic.xml`) are hand-built in those shapes, not captures.

## Posting once

State (`state/morning_skate.json`, saved on the `automation-state` branch) is
keyed by NHL date and records each message as it goes out. A re-run never
repeats a message. If a post fails, or the YouTube feed cannot be read, the run
fails and the scheduler retries it (up to 3 times); the retry posts only what
is missing.

## Trying it

Actions → **BLHA Morning Skate** → Run workflow:

- `preview` prints every message in the log; nothing is posted or recorded.
- `test` posts `[TEST]` copies to 📸│media; nothing is recorded.
- `live` posts the night once (the scheduler uses this).
- `date` (optional, `YYYY-MM-DD`) picks another NHL night, for example a
  recent one to preview.

Locally: `python automation/media/morning.py --mode preview --date 2026-10-07`.
Tests: `python automation/media/test_morning.py`.
