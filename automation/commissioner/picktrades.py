#!/usr/bin/env python3
"""BLHA pick-trade alert: tells the commissioner when a draft pick changes owner.

Constitution Article XII: a franchise may not trade a future 1st- or 2nd-round
pick unless it is paid through the Season of that pick, and the trade must not
become final until the Commissioner has confirmed the payment (12.2 to 12.5).
Fantrax's data feed only shows a pick after the trade has gone through, so this
alert is a fast check-and-reverse prompt, not a gate. Whether a franchise is
paid is kept in the League Ledger, which this tool cannot see.

Each run compares Fantrax's future-pick ownership with the last saved copy and
posts one private message to the Commissioner Desk channel listing every pick
that moved. The first live run only saves a baseline.

Modes:
  preview  print what would be posted; no Discord, no state change
  test     post one [TEST] sample alert; no state change
  live     post alerts and save the new ownership
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from blha.fantrax import Fantrax, normalize_standings  # noqa: E402
from blha.league import load_json, load_league, save_json  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402

STATE_PATH = ROOT / "state" / "picktrades.json"
PREPAY_ROUNDS = (1, 2)


def pick_key(pick: dict[str, Any]) -> str:
    return f"{pick.get('year')}|{pick.get('round')}|{pick.get('originalOwnerTeamId')}"


def snapshot(raw: Any) -> dict[str, str]:
    """pick key -> current owner team id, from getDraftPicks."""
    picks = raw.get("futureDraftPicks") if isinstance(raw, dict) else None
    if not isinstance(picks, list):
        raise ValueError("getDraftPicks has no futureDraftPicks list")
    return {pick_key(p): str(p.get("currentOwnerTeamId") or "") for p in picks if isinstance(p, dict)}


def changes(prev: dict[str, str], cur: dict[str, str]) -> list[dict[str, Any]]:
    """Picks whose owner differs from the saved copy. New or removed picks (a window rolling forward) are ignored."""
    out = []
    for key, owner in cur.items():
        before = prev.get(key)
        if before is None or before == owner:
            continue
        year, rnd, original = key.split("|")
        out.append({"year": int(year), "round": int(rnd), "original": original, "from": before, "to": owner})
    out.sort(key=lambda c: (c["year"], c["round"], c["original"]))
    return out


def describe(change: dict[str, Any], names: dict[str, str]) -> str:
    def name(team_id: str) -> str:
        return names.get(team_id, team_id or "unknown team")

    original = name(change["original"])
    origin = "" if change["original"] == change["from"] else f" (originally {original}'s)"
    return f"{change['year']} round {change['round']} pick{origin}: {name(change['from'])} to {name(change['to'])}"


def build_items(found: list[dict[str, Any]], names: dict[str, str]) -> list[str]:
    needs = [c for c in found if c["round"] in PREPAY_ROUNDS]
    free = [c for c in found if c["round"] not in PREPAY_ROUNDS]
    items: list[str] = []
    if needs:
        items.append("Check the League Ledger now. These are 1st or 2nd round picks, so the team giving each one up must be paid through the Season of that pick, and through every Season before it (12.2, 12.3).")
        for c in needs:
            items.append(f"{describe(c, names)}. Seller must be paid through Season {c['year']}.")
        items.append("If the seller is not paid, withhold approval or reverse the trade in Fantrax and tell both teams (12.4, 12.5).")
    if free:
        items.append("Rounds 3 to 5 need no extra prepayment (12.7), listed for your records:")
        for c in free:
            items.append(describe(c, names) + ".")
    return items


def build_task(found: list[dict[str, Any]], names: dict[str, str]) -> dict[str, Any]:
    needs = any(c["round"] in PREPAY_ROUNDS for c in found)
    title = "Pick trade: confirm prepayment" if needs else "Pick trade recorded"
    if len(found) > 1:
        title = f"{len(found)} pick moves: " + ("confirm prepayment" if needs else "recorded")
    return {"title": title, "section": "Article XII", "items": build_items(found, names)}


def run(mode: str) -> int:
    cfg = load_league()
    fx = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Pick-Trades/1.0")
    cur = snapshot(fx.draft_picks())
    names = {r["teamId"]: r["teamName"] for r in normalize_standings(fx.standings())}
    state = load_json(STATE_PATH, {})
    prev = state.get("owners")
    print(f"BLHA PICK TRADES mode={mode.upper()} picks={len(cur)}")
    if not isinstance(prev, dict):
        print("No saved copy yet: recording the current ownership as the baseline. No alert.")
        if mode == "live":
            save_json(STATE_PATH, {"owners": cur, "baselined": datetime.now(timezone.utc).isoformat()})
        return 0
    found = changes(prev, cur)
    if not found:
        print("No pick has changed owner.")
        if mode == "live" and len(cur) != len(prev):
            save_json(STATE_PATH, {**state, "owners": cur})
        return 0
    task = build_task(found, names)
    for line in task["items"]:
        print("  " + line)
    if mode == "preview":
        return 0
    payload = desk.build_payload(task, None, cfg, now=datetime.now(timezone.utc))
    ok, detail = post_discord_webhook(desk.secret_name(cfg), payload)
    if not ok:
        print(f"DELIVERY ERROR: {detail} (not saved, will retry next run)")
        return 1
    print("POSTED")
    save_json(STATE_PATH, {**state, "owners": cur})
    return 0


def test_post() -> int:
    cfg = load_league()
    names = {"a": "Test 1", "b": "Test 2", "c": "Test 3"}
    sample = [
        {"year": 2029, "round": 1, "original": "a", "from": "a", "to": "b"},
        {"year": 2030, "round": 4, "original": "c", "from": "c", "to": "a"},
    ]
    task = build_task(sample, names)
    task["items"].insert(0, "Sample only. No pick has actually moved.")
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, test=True))
    print(("PASS" if ok else "ERROR") + f" [pick-trades]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()
    return test_post() if args.mode == "test" else run(args.mode)


if __name__ == "__main__":
    sys.exit(main())
