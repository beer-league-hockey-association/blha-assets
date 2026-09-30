# BLHA Discord Automation Style Standard

This is the default presentation standard for all BLHA automated Discord posts unless a channel has a specific reason to differ.

## Core rules

- Use clean vertical Discord embed fields instead of wide ASCII/code-block tables.
- Do not use decorative emoji in automated competition or league-office data posts.
- Keep the BLHA Competition Desk / League Office identity consistent.
- Put the league/season context near the top of the embed.
- Use concise labels and natural Discord formatting rather than fixed-width alignment.
- Bold only information that needs emphasis, such as the current matchup leader.
- Use one logical section per embed field when possible.
- Keep source/provenance text short and place it near the bottom or in the footer.
- Preserve the BLHA gold embed accent unless a channel has an established semantic accent.
- Avoid clutter, repeated labels, excessive icons, and dense walls of text.

## Competition-data pattern

Scoreboards, standings, recaps, power/race views, and future Fantrax competition feeds should follow the approved scoreboard presentation:

- clear title
- league and season line
- short explanatory note
- vertically stacked fields
- no emoji
- BLHA Competition Desk webhook identity
- concise source footer

The GitHub Actions log may still use compact fixed-width tables for diagnostics; this restriction applies to Discord-facing output.
