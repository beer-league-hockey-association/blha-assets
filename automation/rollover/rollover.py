#!/usr/bin/env python3
"""BLHA season rollover: check a new Fantrax league and prepare the automations for it.

Everything season-specific is read from Fantrax, so a rollover is: create the
new league on Fantrax, check it here, switch league.yaml to it, clear the saved
state that belongs to the old season, and date the new events.

Modes:
  check        read the new league from Fantrax and report what is right, wrong or still to do. Changes nothing.
  write-config rewrite league_id and season_label in automation/league.yaml (local edit; commit it yourself).
  reset-state  remove the old season's saved state from the automation-state branch (run by the workflow).

The check compares the new league with what the Constitution requires: 12
franchises, 22 regular-season weeks, a six-team playoff (15.1, 16.1) and a
future start date.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
sys.path.insert(0, str(AUTOMATION))

from blha import season  # noqa: E402
from blha.fantrax import Fantrax  # noqa: E402
from blha.league import load_json, load_league, timezone_of  # noqa: E402

LEAGUE_YAML = AUTOMATION / "league.yaml"
EVENTS_YAML = AUTOMATION / "league-office" / "events.yaml"
COMMISSIONER_STATE = AUTOMATION / "commissioner" / "state" / "commissioner.json"

EXPECTED_TEAMS = 12
EXPECTED_REGULAR_WEEKS = 22
EXPECTED_PLAYOFF_TEAMS = 6
EXPECTED_PLAYOFF_WEEKS = 3

# Saved state that belongs to one season. Wire, Automation Health, the
# minor-eligibility watch and the Trade Desk are not listed: they carry over
# between seasons (the Trade Desk saves a new baseline for a new league or
# season by itself and keeps its trades for their 6- and 12-month revisits).
SEASON_STATE = [
    "automation/playoffs/state/playoff.json",
    "automation/competition/state/competition.json",
    "automation/competition/state/scoreboard.json",
    "automation/league-office/state/league_ops.json",
    "automation/commissioner/state/commissioner.json",
    "automation/commissioner/state/picktrades.json",
]


@dataclass
class Finding:
    level: str  # OK | WARN | FAIL
    text: str


def check_league(info: dict[str, Any], standings: list[dict[str, Any]], now: datetime) -> list[Finding]:
    out: list[Finding] = []

    def add(ok: bool, good: str, bad: str, level: str = "FAIL") -> None:
        out.append(Finding("OK" if ok else level, good if ok else bad))

    teams = info.get("teamInfo") or {}
    add(len(teams) == EXPECTED_TEAMS, f"{len(teams)} franchises.", f"{len(teams)} franchises; the Constitution has {EXPECTED_TEAMS}.")
    last_regular, first_playoff, playoff_teams = season.playoff_settings(info)
    weeks = season.periods(info)
    add(last_regular == EXPECTED_REGULAR_WEEKS, f"{last_regular} regular-season weeks.",
        f"{last_regular} regular-season weeks; the Constitution has {EXPECTED_REGULAR_WEEKS} (15.1).")
    add(playoff_teams == EXPECTED_PLAYOFF_TEAMS, f"{playoff_teams} playoff teams.",
        f"{playoff_teams} playoff teams; the format needs {EXPECTED_PLAYOFF_TEAMS} (16.1).")
    playoff_weeks = len(weeks) - last_regular
    add(playoff_weeks == EXPECTED_PLAYOFF_WEEKS and first_playoff == last_regular + 1,
        f"{playoff_weeks} playoff weeks right after Week {last_regular}.",
        f"{playoff_weeks} playoff weeks starting Week {first_playoff}; expected {EXPECTED_PLAYOFF_WEEKS} straight after Week {last_regular}.")
    if weeks:
        start = weeks[0].start
        add(start > now, f"Week 1 starts {start.astimezone().strftime('%b %d %Y')}.",
            f"Week 1 start ({start.date()}) is in the past; check this is the new season's league.", "WARN")
    else:
        out.append(Finding("FAIL", "Fantrax returned no scoring periods."))
    played = [r["wins"] + r["losses"] + r["ties"] for r in standings]
    add(not played or max(played) == 0, "No games played yet.", "Standings already show games played; this looks like an old league.", "WARN")
    names = {t.get("name") for t in teams.values() if isinstance(t, dict)}
    add(not any(str(n).lower().startswith("test") for n in names), "Franchise names look real.",
        "Franchise names still say Test; fine until owners join.", "WARN")
    return out


def pending_prizes(state: dict[str, Any], now: datetime) -> str | None:
    """Message if the old season's 30-day prize and Ledger deadline is still running."""
    raw = (state.get("anchors") or {}).get("season_end_final")
    if not raw:
        return None
    ends = datetime.fromisoformat(raw) + timedelta(days=30)
    if now < ends:
        return f"The old season's prize and Season Ledger deadline runs until {ends.astimezone().strftime('%b %d %Y')}. Its Commissioner Desk countdown is saved in state that the reset removes. Roll over after that date."
    return None


def events_needing_dates(events: dict[str, Any], now: datetime, tz) -> list[str]:
    """Events that are disabled, undated or dated in the past: all need a decision for the new season."""
    out = []
    for e in events.get("events") or []:
        raw = e.get("starts_at")
        when = None
        if raw:
            try:
                when = datetime.fromisoformat(str(raw))
                when = when if when.tzinfo else when.replace(tzinfo=tz)
            except ValueError:
                when = None
        if not e.get("enabled") or when is None:
            out.append(f"{e.get('id')}: not enabled or no date yet")
        elif when < now:
            out.append(f"{e.get('id')}: dated {when.date()}, in the past")
    return out


def write_config(path: Path, league_id: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^league_id:.*$", f"league_id: {league_id}", text, count=1)
    new = re.sub(r'(?m)^season_label:.*$', f'season_label: "{label}"', new, count=1)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def run_check(league_id: str) -> int:
    cfg = load_league()
    tz = timezone_of(cfg)
    now = datetime.now(timezone.utc)
    fx = Fantrax(league_id, user_agent="BLHA-Rollover/1.0")
    info = fx.league_info()
    standings = fx.standings()  # already normalized; normalizing twice zeroes the W-L-T counts
    print(f"Checking Fantrax league {league_id}: {info.get('leagueName')} (season {info.get('seasonYear')})")
    fails = 0
    for f in check_league(info, standings, now):
        print(f"{f.level:5} {f.text}")
        fails += f.level == "FAIL"
    prizes = pending_prizes(load_json(COMMISSIONER_STATE, {}), now)
    print(("WARN  " + prizes) if prizes else "OK    No prize countdown from the old season is still running.")
    print("\nStill to do by hand:")
    for step in (
        f"Change league_id in automation/league.yaml to {league_id} and set season_label (use mode write-config).",
        "Run the workflow in reset-state mode to clear the old season's saved state.",
        "Date and enable each League Office event in events.yaml for the new season:",
    ):
        print("  " + step)
    for line in events_needing_dates(yaml.safe_load(EVENTS_YAML.read_text(encoding="utf-8")) or {}, now, tz):
        print("    " + line)
    for step in (
        "Run Commissioner Desk, Pick Trades and Playoffs in preview mode once; the first live runs record a baseline.",
        "Check Automation Health is quiet and the Scoreboard and weekly report previews show the new league.",
    ):
        print("  " + step)
    return 1 if fails else 0


def run_reset() -> int:
    script = AUTOMATION / "tools" / "state_branch.sh"
    result = subprocess.run(
        ["bash", str(script), "remove", "chore(rollover): clear previous season state", "BLHA Fantrax Automation", *SEASON_STATE],
        cwd=AUTOMATION.parent,
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("check", "write-config", "reset-state"), default="check")
    parser.add_argument("--league-id", default="")
    parser.add_argument("--season-label", default="")
    args = parser.parse_args()
    if args.mode == "reset-state":
        return run_reset()
    if not args.league_id:
        parser.error("--league-id is required")
    if args.mode == "write-config":
        if not args.season_label:
            parser.error("--season-label is required for write-config")
        changed = write_config(LEAGUE_YAML, args.league_id, args.season_label)
        print("league.yaml updated." if changed else "league.yaml already matches.")
        return 0
    return run_check(args.league_id)


if __name__ == "__main__":
    sys.exit(main())
