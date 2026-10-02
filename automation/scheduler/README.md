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
4. **Resource owner:** `diseasewheeze`.
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
   `https://api.github.com/repos/diseasewheeze/blha-assets/actions/workflows/blha-scheduler.yml/dispatches`
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

## If something goes wrong

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| cron-job.org shows 401 | Token expired, revoked, or pasted wrong | Create a new token and update the `Authorization` header |
| cron-job.org shows 403 | Token is missing **Actions: Read and write** or not scoped to `blha-assets` | Edit the token's permissions |
| cron-job.org shows 404 | Wrong URL, or the scheduler is not on `main` yet | Check the URL; merge the scheduler PR |
| cron-job.org shows 422 | Request body missing or not JSON | Body must be exactly `{"ref":"main"}` |
| Health alert: "BLHA Scheduler — Workflow appears stale" | External timer stopped; only GitHub's late backup cron is running | Check the cron-job.org job history |
| Scheduler log shows `ERROR … dispatch failed` | GitHub API problem, or a workflow lost its `mode` input | Read the error text in the log |
