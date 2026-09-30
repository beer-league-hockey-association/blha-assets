# BLHA Phase 2D.1 Test Plan

## Dry-run acceptance test
Before any Discord webhook is activated, the collector must:

1. Fetch ESPN NHL RSS successfully.
2. Fetch Sportsnet NHL RSS successfully.
3. Attempt r/hockey RSS with a descriptive User-Agent.
4. Print each new headline with its source and intended BLHA channel.
5. Never send a Discord message in dry-run mode.
6. Never expose webhook secrets in logs.

## Routing test cases
Expected outcomes:

- `Star player out indefinitely after surgery` → `breaking-news` from Tier 1; otherwise `injury-report`
- `Player listed day-to-day` → `injury-report`
- `Team recalls prospect from AHL` → `nhl-transactions` because transaction priority is above prospect
- `Top prospect dominates World Juniors` → `prospect-wire`
- `Team signs depth forward to one-year deal` → `nhl-transactions`
- `NHL game recap` → `nhl-news`
- `Reddit rumor: superstar trade imminent` → never `breaking-news`; default/suppress depending on future trust filter

## Live-test sequence for Phase 2D.2
1. Create a private temporary Discord test channel or use a temporary webhook.
2. Add only one test webhook secret.
3. Run the workflow manually.
4. Confirm formatting and source links.
5. Confirm no duplicates.
6. Add remaining channel secrets.
7. Run manual full-routing test.
8. Enable scheduling only after all tests pass.

## Offseason check
Scheduled workflows in a public GitHub repository can be disabled after 60 days with no repository activity. Check Actions before each season.