"""Trade detection: what moved straight from one BLHA team to another between two runs.

Fantrax's read-only feed has no transaction log, so a trade is inferred by
comparing two snapshots, the same way the league archive does
(automation/history/collect.py), only every 15 to 30 minutes instead of daily:

- Players: getTeamRosters, diffed with collect.player_changes. A player who
  left one BLHA team and is now on another moved in a trade. Adds from the
  free-agent pool and drops to it are ignored.
- Draft picks: getDraftPicks, snapshotted with the archive's
  collect.pick_snapshot (future picks, plus the current draft's picks while
  Fantrax has a draft set up, so a pick traded around the Annual Draft is
  seen) and diffed with the pick-trade alert's own functions
  (automation/commissioner/picktrades.py).
- Everything that moved in the same window and shares a team is one trade
  (collect.group_trades), so a three-team deal is one trade. Two separate
  trades that share a team and process minutes apart join the same way; the
  feed can't tell them apart.

A pick or player that moved with nothing coming back is kept as a trade and
flagged ``one_sided``: FAAB is not in Fantrax's feed, so a player-for-FAAB deal
looks exactly like that. A waiver drop by one team and a FAAB claim by another
also look like that when both fall between two good reads;
``hold_back_one_sided_players`` takes those player moves out when the caller
can't rule that out.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

AUTOMATION = Path(__file__).resolve().parents[1]
for folder in (AUTOMATION, AUTOMATION / "commissioner"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import picktrades  # noqa: E402  (automation/commissioner/picktrades.py)
from blha import draft as dr  # noqa: E402
from history.collect import (  # noqa: E402
    SnapshotError, check_sane, group_trades, pick_snapshot, player_changes, roster_names, roster_snapshot, season_of,
)

__all__ = ["SnapshotError", "detect", "group_trades", "hold_back_one_sided_players", "moves_between", "pick_moves",
           "read_snapshot", "reversal_of", "roster_names", "roster_snapshot", "season_of"]

REVERSAL_WINDOW = timedelta(days=14)
DEFAULT_TZ = ZoneInfo("America/New_York")
REBASELINE_HINT = ("If rosters were reset on purpose (the Commissioner emptied a team, a TEST draft was re-run), "
                   "run the BLHA Trade Desk workflow once with mode rebaseline")


def current_draft_year(fx: Any, tz: ZoneInfo) -> int | None:
    """Year of the draft Fantrax has set up (its date in league time), for currentDraftPicks rows without a year."""
    try:
        draft = dr.parse_results(fx.draft_results())
    except Exception as exc:  # noqa: BLE001 - only current-draft picks depend on it
        print(f"WARNING: could not read the draft date ({exc.__class__.__name__}); current-draft picks are left out this run.")
        return None
    moment = draft.date or draft.start
    return moment.astimezone(tz).year if moment else None


def read_picks(fx: Any, tz: ZoneInfo) -> dict[str, str] | None:
    """Pick key -> owner (future and current-draft picks), or None if getDraftPicks can't be read."""
    try:
        raw = fx.draft_picks()
        current = raw.get("currentDraftPicks") if isinstance(raw, dict) else None
        year = None
        if any(isinstance(row, dict) and not row.get("year") for row in current or []):
            year = current_draft_year(fx, tz)
        return pick_snapshot(raw, year)
    except Exception as exc:  # noqa: BLE001 - picks are optional for player trades
        print(f"WARNING: could not read draft-pick ownership ({exc.__class__.__name__}); keeping the saved copy.")
        return None


def read_snapshot(fx: Any, tz: ZoneInfo | None = None,
                  ) -> tuple[dict[str, dict[str, str]], dict[str, str] | None, dict[str, str]]:
    """(rosters, picks or None, team names) read from Fantrax now.

    Rosters keep only who is on which team (team id -> player id -> ""): daily
    ACTIVE/RESERVE lineup changes are not trades, and leaving them out keeps
    the saved copy unchanged between trades, adds and drops. Picks are
    optional: if getDraftPicks fails, the caller decides what to do (None).
    An error reading rosters is raised.
    """
    raw = fx.rosters()
    rosters = {team: {player: "" for player in roster} for team, roster in roster_snapshot(raw).items()}
    return rosters, read_picks(fx, tz or DEFAULT_TZ), roster_names(raw)


def pick_moves(prev: dict[str, str] | None, cur: dict[str, str] | None) -> list[dict[str, str]]:
    """Pick ownership changes as archive-style moves ({asset: pick:<year|round|original>, from, to})."""
    if prev is None or cur is None:
        return []
    return [{"asset": f"pick:{c['year']}|{c['round']}|{c['original']}", "from": c["from"], "to": c["to"]}
            for c in picktrades.changes(prev, cur) if c["from"] and c["to"]]


def sane(prev_rosters: dict[str, dict[str, str]], cur_rosters: dict[str, dict[str, str]]) -> None:
    """collect.check_sane, with the fix pointing to the Trade Desk's own rebaseline mode."""
    try:
        check_sane(prev_rosters, cur_rosters)
    except SnapshotError as exc:
        base = str(exc).split(". If rosters were reset", 1)[0].rstrip(". ")
        raise SnapshotError(f"{base}. {REBASELINE_HINT}") from None


def moves_between(prev_rosters: dict[str, dict[str, str]], cur_rosters: dict[str, dict[str, str]],
                  prev_picks: dict[str, str] | None, cur_picks: dict[str, str] | None) -> list[dict[str, str]]:
    """Every player and pick that went straight from one team to another. Raises SnapshotError like ``detect``."""
    sane(prev_rosters, cur_rosters)
    _, _, moves, _ = player_changes(prev_rosters, cur_rosters)
    return moves + pick_moves(prev_picks, cur_picks)


def hold_back_one_sided_players(moves: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(kept, held back): player moves out of a team that receives nothing in its trade are held back.

    That is what a waiver drop and a later FAAB claim of the same player look
    like. A pick moving the same way marks a real trade (picks can't be
    dropped), so those players stay; two-sided swaps always stay.
    """
    kept, held = list(moves), []
    while True:
        pick_pairs = {(m["from"], m["to"]) for m in kept if not m["asset"].startswith("player:")}
        out = []
        for trade in group_trades(kept):
            empty = {t for t in trade["teams"] if not trade["received"][t]}
            out += [m for m in trade["moves"] if m["from"] in empty and m["asset"].startswith("player:")
                    and (m["from"], m["to"]) not in pick_pairs]
        if not out:
            return kept, held
        held += out
        kept = [m for m in kept if m not in out]


def detect(prev_rosters: dict[str, dict[str, str]], cur_rosters: dict[str, dict[str, str]],
           prev_picks: dict[str, str] | None, cur_picks: dict[str, str] | None) -> list[dict[str, Any]]:
    """Trades between two snapshots: [{teams, received, sent, moves, one_sided?}].

    Raises SnapshotError when Fantrax's answer looks incomplete (mass drops,
    missing teams), so a hiccup is never reported as a trade.
    """
    return group_trades(moves_between(prev_rosters, cur_rosters, prev_picks, cur_picks))


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
