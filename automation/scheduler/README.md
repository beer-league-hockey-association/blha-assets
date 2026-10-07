# BLHA Scheduler

One dispatcher that decides when every BLHA automation runs.

## Why this exists

GitHub's built-in `schedule:` cron is best-effort. In this repository's first
days it ran the 15-minute Wire only every 3–7 hours, ran daily jobs up to
7 hours late, and skipped some days entirely. Every automation was affected.

Instead of each workflow keeping its own cron, the **BLHA Scheduler** workflow
runs every 15 minutes and starts whatever is due, always in `live` mode:

- **Primary trigger:** an external timer (cron-job.org) calls GitHub's API
  every 15 minutes. This is reliable to the minute.
- **Backup trigger:** GitHub's own cron on the scheduler workflow. If the
  external timer ever stops, things keep running, just late.

The scheduler works out what is due from each workflow's **last live run**, not
from the current minute. A late or missed check never causes a job to be
skipped; it simply runs at the next check. Duplicate checks are harmless.

## Changing when something runs

Edit `schedule.yaml`. Nothing else needs to change.

- `every_minutes: 15` — run when the last live run is at least 15 minutes old.
- `daily_at: ["08:00"]` — run once after each listed time (Eastern, DST-safe).
- `retry_failures: 3` — for daily jobs, if the run failed, try again at the
  next check, up to 3 more times.
- `phases: [regular, playoffs]` — only run during these parts of the season.
  Phases are `preseason`, `regular`, `playoffs` and `offseason`, worked out
  from Fantrax's own week dates for the league in `automation/league.yaml`.
  If Fantrax cannot be reached, the scheduler runs the job anyway rather than
  silently skipping it.

The log for each scheduler run starts with the current season phase, then
lists every job as `STARTED`, `WAIT`, or `OFF` (not active this phase).

Manual runs from the Actions tab still work exactly as before and still
default to preview/shadow. Only runs named `… — live` count as the job having
run, so testing never delays the real schedule.

## One-time setup: the external timer

You need two things: a GitHub token that can only start workflows in this
repository, and a free cron-job.org job that uses it.

### 1. Create the GitHub token

1. On GitHub, open your profile picture → **Settings** → **Developer settings**
   (bottom of the left sidebar) → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. **Token name:** `BLHA Scheduler timer`.
3. **Expiration:** the longest offered (up to 1 year). Put a reminder on your
   calendar a week before it expires. If it lapses, the health monitor will
   report "BLHA Scheduler — Workflow appears stale".
4. **Resource owner:** `beer-league-hockey-association` (the organization).
5. **Repository access:** **Only select repositories** → `blha-assets`.
6. **Permissions** → **Repository permissions** → **Actions** → **Read and write**.
   Leave everything else as is (GitHub adds read-only Metadata automatically).
7. Click **Generate token** and copy it. GitHub only shows it once.

This token can start and read workflow runs in `blha-assets` and nothing
else: no code, no secrets, no other repositories. You can revoke it from the
same page at any time.

### 2. Create the cron-job.org job

1. Sign in at https://cron-job.org and choose **Create cronjob**.
2. **Title:** `BLHA Scheduler`.
3. **URL:**
   `https://api.github.com/repos/beer-league-hockey-association/blha-assets/actions/workflows/blha-scheduler.yml/dispatches`
4. **Execution schedule:** every 15 minutes.
5. Open the **Advanced** tab:
   - **Request method:** `POST`
   - **Headers** (add each one):
     - `Accept` = `application/vnd.github+json`
     - `Authorization` = `Bearer YOUR_TOKEN_HERE`
     - `X-GitHub-Api-Version` = `2022-11-28`
     - `Content-Type` = `application/json`
   - **Request body:** `{"ref":"main"}`
6. Turn on the option to notify you when the job fails.
7. Save, then use **Test run**. A working setup returns **HTTP 204** with an
   empty body. (Before the scheduler is merged into `main`, the test returns
   404 because the workflow does not exist there yet.)

### 3. Confirm it is working

In the repository's **Actions** tab, **BLHA Scheduler** should show a run
named `BLHA Scheduler — live` every 15 minutes. Open one. The log lists every
job as `STARTED` or `WAIT` with the reason, for example:

```
STARTED wire-engine: last live run 15m ago (2026-10-02 16:00 UTC)
WAIT    standings: slot Fri 07:30 EDT already ran
```

## Protection against GitHub's 60-day rule

GitHub switches off scheduled workflows in a public repository after 60 days
with no repository activity. The scheduler has a `schedule:` backup trigger, so
it could be switched off in a quiet stretch such as the offseason. The **BLHA
Dormancy Guard** workflow has no `schedule:` trigger, so GitHub cannot switch it
off that way. It re-enables any workflow GitHub disabled for inactivity and
warns the Commissioner Desk when `main` has had no commit for 45 days.

The scheduler starts the guard daily. In case the scheduler itself is the thing
that was switched off, add a second cron-job.org job (same token as above):

- **Title:** `BLHA Dormancy Guard`
- **URL:** `https://api.github.com/repos/beer-league-hockey-association/blha-assets/actions/workflows/blha-dormancy-guard.yml/dispatches`
- **Schedule:** once a day
- **Method and headers:** as for the scheduler job
- **Request body:** `{"ref":"main","inputs":{"mode":"live"}}`

## Outside check-in (Healthchecks.io)

Everything above alerts you through GitHub or Discord. If GitHub Actions or the
cron-job.org timer stops altogether, nothing inside the system notices. A free
Healthchecks.io check covers that gap: every live scheduler run pings it, and if
the pings stop it emails you (and optionally posts in Discord).

1. Sign up at https://healthchecks.io (free plan: 20 checks, no card).
2. **Add Check**. Name it `BLHA Scheduler`.
   - **Schedule:** Simple. **Period** 15 minutes, **Grace time** 1 hour. You are
     alerted after about 75 minutes with no run, which rides out GitHub's
     occasional late starts without crying wolf.
3. Copy the check's ping URL (`https://hc-ping.com/...`).
4. GitHub: Settings > Secrets and variables > Actions > New repository secret
   named `BLHA_HEALTHCHECK_PING_URL`, value = that URL.
5. Healthchecks: **Integrations**. Email to your sign-up address is on by
   default. Optionally add **Discord** and pick `⚙️│automation-health`.
6. Wait 15 minutes. The check should turn green ("up"). The scheduler log ends
   with `Checked in (success)`; a failed scheduler run pings `/fail`, which
   alerts you straight away.

Without the secret the step just logs that it skipped.

## Repository home

The repository lives in the `beer-league-hockey-association` organization at
`beer-league-hockey-association/blha-assets`, so a future Commissioner can take
over the automation without a personal account (Constitution 19.6). It moved
there from the previous personal-account address in October 2026; code,
history, pull requests, Actions history, repository secrets and webhooks moved
with it, and every template, tool and doc now uses the organization address.

If you set up the timer before the move, check these:

- **Timer token.** A fine-grained token owned by a personal account cannot start
  workflows in an organization repository. Create one with **Resource owner** =
  `beer-league-hockey-association` (steps under "Create the GitHub token"
  above) and put it in both cron-job.org jobs.
- **cron-job.org URLs.** Both jobs must use the organization address shown in
  the steps above; **Test run** each (expect HTTP 204).
- **Claude's GitHub access.** The Claude GitHub app needs access to the
  organization's repository.

Never create a new repository called `blha-assets` under the old personal
account; that would break GitHub's redirect for any old link still in use.

## If something goes wrong

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| cron-job.org shows 401 | Token expired, revoked, or pasted wrong | Create a new token and update the `Authorization` header |
| cron-job.org shows 403 | Token is missing **Actions: Read and write** or not scoped to `blha-assets` | Edit the token's permissions |
| cron-job.org shows 404 | Wrong URL, or the scheduler is not on `main` yet | Check the URL; merge the scheduler PR |
| cron-job.org shows 422 | Request body missing or not JSON | Body must be exactly `{"ref":"main"}` |
| Health alert: "BLHA Scheduler — Workflow appears stale" | External timer stopped; only GitHub's late backup cron is running | Check the cron-job.org job history |
| Scheduler log shows `ERROR … dispatch failed` | GitHub API problem, or a workflow lost its `mode` input | Read the error text in the log |
| Healthchecks.io says the check is down | No live scheduler run for over an hour | Check cron-job.org history and the Actions tab; a GitHub outage clears itself |
