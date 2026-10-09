"""Trade detection: what moved straight from one BLHA team to another between two runs.

Fantrax's read-only feed has no transaction log, so a trade is inferred by
comparing two snapshots, the same way the league archive does
(automation/history/collect.py), only every 15 to 30 minutes instead of daily:

- Players: getTeamRosters, diffed with collect.player_changes. A player who
  left one BLHA team and is now on another moved in a trade. Adds from the
  free-agent pool and drops to it are ignored.
- Draft picks: getDraftPicks, snapshotted and diffed with the pick-trade
  alert's own functions (automation/commissioner/picktrades.py).
- Everything that moved in the same window and shares a team is one trade
  (collect.group_trades), so a three-team deal is one trade.

A pick or player that moved with nothing coming back is kept as a trade and
flagged ``one_sided``: FAAB is not in Fantrax's feed, so a player-for-FAAB deal
looks exactly like that.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

AUTOMATION = Path(__file__).resolve().parents[1]
for folder in (AUTOMATION, AUTOMATION / "commissioner"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import picktrades  # noqa: E402  (automation/commissioner/picktrades.py)
from history.collect import (  # noqa: E402
    SnapshotError, check_sane, group_trades, player_changes, roster_names, roster_snapshot, season_of,
)

__all__ = ["SnapshotError", "detect", "pick_moves", "read_snapshot", "reversal_of", "roster_names",
           "roster_snapshot", "season_of"]

REVERSAL_WINDOW = timedelta(days=14)


def read_snapshot(fx: Any) -> tuple[dict[str, dict[str, str]], dict[str, str] | None, dict[str, str]]:
    """(rosters, picks or None, team names) read from Fantrax now.

    Rosters keep only who is on which team (team id -> player id -> ""): daily
    ACTIVE/RESERVE lineup changes are not trades, and leaving them out keeps
    the saved copy unchanged between trades, adds and drops. Picks are
    optional: if getDraftPicks fails, players are still checked and the saved
    pick ownership is kept.
    """
    raw = fx.rosters()
    rosters = {team: {player: "" for player in roster} for team, roster in roster_snapshot(raw).items()}
    try:
        picks: dict[str, str] | None = picktrades.snapshot(fx.draft_picks())
    except Exception as exc:  # noqa: BLE001 - picks are optional for player trades
        print(f"WARNING: could not read draft-pick ownership ({exc.__class__.__name__}); keeping the saved copy.")
        picks = None
    return rosters, picks, roster_names(raw)


def pick_moves(prev: dict[str, str] | None, cur: dict[str, str] | None) -> list[dict[str, str]]:
    """Pick ownership changes as archive-style moves ({asset: pick:<year|round|original>, from, to})."""
    if prev is None or cur is None:
        return []
    return [{"asset": f"pick:{c['year']}|{c['round']}|{c['original']}", "from": c["from"], "to": c["to"]}
            for c in picktrades.changes(prev, cur) if c["from"] and c["to"]]


def detect(prev_rosters: dict[str, dict[str, str]], cur_rosters: dict[str, dict[str, str]],
           prev_picks: dict[str, str] | None, cur_picks: dict[str, str] | None) -> list[dict[str, Any]]:
    """Trades between two snapshots: [{teams, received, sent, moves, one_sided?}].

    Raises SnapshotError when Fantrax's answer looks incomplete (mass drops,
    missing teams), so a hiccup is never reported as a trade.
    """
    check_sane(prev_rosters, cur_rosters)
    _, _, moves, _ = player_changes(prev_rosters, cur_rosters)
    moves = moves + pick_moves(prev_picks, cur_picks)
    return group_trades(moves)


def _signature(received: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    return {team: tuple(sorted(assets)) for team, assets in received.items() if assets}


def reversal_of(trade: dict[str, Any], recorded: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The recent recorded trade this one exactly undoes (each team gets back what it sent), if any.

    The Commissioner reverses a trade that breaks a rule (Article XII
    prepayment, 11.6 deadline); that is not a new trade to vote on.
    """
    mine = _signature(trade.get("received") or {})
    for old in reversed(recorded):
        try:
            when = datetime.fromisoformat(str(old.get("at")))
        except ValueError:
            continue
        if old.get("reversed") or now - when > REVERSAL_WINDOW:
            continue
        if mine and _signature(old.get("sent") or {}) == mine:
            return old
    return None
