#!/usr/bin/env python3
"""BLHA pick-trade alert: tells the commissioner when a draft pick changes owner.

Constitution Article XII: a franchise may not trade away a future 1st- or
2nd-round pick unless it is paid through the Season of that pick (12.2, 12.3).
Fantrax processes trades without Commissioner approval and its data feed only
shows a pick after the trade has gone through, so a trade made before payment
is reversed by the Commissioner (12.5). This alert is the fast prompt to do it.

Each run compares Fantrax's future-pick ownership with the last saved copy and
posts one private message to the Commissioner Desk channel listing every pick
that moved. The first live run only saves a baseline.

When the secret BLHA_LEDGER_CLEARANCE_CSV holds the published-CSV link of the
League Ledger's "Pick Clearance" tab (Fantrax team ID, franchise, paid-through
Season), each 1st- or 2nd-round move gets a verdict: PAID (no action) or NOT
PAID (reverse the trade). Without it, or if the sheet can't be read, the alert
asks you to check the ledger by hand. A pick that goes straight back to the
team that had it before a recent alert is treated as the reversal, not a trade.

Modes:
  preview  print what would be posted; no Discord, no state change
  test     post one [TEST] sample alert; no state change
  live     post alerts and save the new ownership
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from blha.fantrax import Fantrax, normalize_standings  # noqa: E402
from blha.league import load_json, load_league, save_json  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402

STATE_PATH = ROOT / "state" / "picktrades.json"
PREPAY_ROUNDS = (1, 2)
CLEARANCE_ENV = "BLHA_LEDGER_CLEARANCE_CSV"
REVERSAL_WINDOW = timedelta(days=14)


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


def mark_reversals(found: list[dict[str, Any]], recent: list[dict[str, Any]], now: datetime) -> None:
    """Flag moves that send a pick straight back to the team that had it before a recent alert."""
    for c in found:
        key = f"{c['year']}|{c['round']}|{c['original']}"
        for r in recent:
            try:
                when = datetime.fromisoformat(str(r.get("at")))
            except ValueError:
                continue
            if (r.get("key") == key and r.get("to") == c["from"] and r.get("from") == c["to"]
                    and now - when <= REVERSAL_WINDOW):
                c["reversal"] = True
                break


def parse_clearance(text: str) -> dict[str, dict[str, Any]] | None:
    """team id -> {franchise, paid_through} from the ledger's Pick Clearance CSV, or None if it isn't that sheet."""
    rows = list(csv.reader(io.StringIO(text)))
    for i, row in enumerate(rows):
        norm = [c.strip().lower() for c in row]
        if "fantrax team id" not in norm or "paid through" not in norm:
            continue
        id_col, paid_col = norm.index("fantrax team id"), norm.index("paid through")
        name_col = norm.index("franchise") if "franchise" in norm else None
        out: dict[str, dict[str, Any]] = {}
        for r in rows[i + 1:]:
            if len(r) <= max(id_col, paid_col) or not r[id_col].strip():
                continue
            try:
                paid: int | None = int(float(r[paid_col].strip()))
            except ValueError:
                paid = None
            name = r[name_col].strip() if name_col is not None and len(r) > name_col else ""
            out[r[id_col].strip()] = {"franchise": name, "paid_through": paid}
        return out
    return None


def load_clearance() -> dict[str, dict[str, Any]] | None:
    url = os.environ.get(CLEARANCE_ENV, "").strip()
    if not url:
        return None
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"LEDGER WARNING: could not read the Pick Clearance sheet ({exc.__class__.__name__}). Asking for a manual check.")
        return None
    table = parse_clearance(response.text)
    if table is None:
        print("LEDGER WARNING: the Pick Clearance link did not return the expected columns. Asking for a manual check.")
    return table


def report_clearance(names: dict[str, str]) -> None:
    """Preview only: show whether the ledger's Pick Clearance tab can be read and matches Fantrax."""
    if not os.environ.get(CLEARANCE_ENV, "").strip():
        print(f"Ledger check: {CLEARANCE_ENV} is not set, so alerts ask for a manual check.")
        return
    table = load_clearance()
    if table is None:
        print("Ledger check: FAILED. The secret is set but the Pick Clearance tab could not be read.")
        return
    found = [t for t in names if t in table]
    print(f"Ledger check: OK. Read {len(table)} franchises from the Pick Clearance tab; "
          f"{len(found)} of {len(names)} Fantrax teams are on it.")
    missing = sorted(names[t] for t in names if t not in table)
    if missing:
        print("  Not on the tab (add their Fantrax team IDs on the Settings tab): " + ", ".join(missing))
    for team_id in found:
        paid = table[team_id].get("paid_through")
        print(f"  {names[team_id]}: paid through {paid if paid is not None else 'no Season yet'}")


def verdict(change: dict[str, Any], clearance: dict[str, dict[str, Any]] | None) -> tuple[str, int | None]:
    """'paid', 'unpaid' or 'unknown' for the team giving the pick up."""
    entry = (clearance or {}).get(change["from"])
    if entry is None:
        return "unknown", None
    paid = entry.get("paid_through")
    return ("paid" if isinstance(paid, int) and paid >= change["year"] else "unpaid"), paid


def describe(change: dict[str, Any], names: dict[str, str]) -> str:
    def name(team_id: str) -> str:
        return names.get(team_id, team_id or "unknown team")

    original = name(change["original"])
    origin = "" if change["original"] == change["from"] else f" (originally {original}'s)"
    return f"{change['year']} round {change['round']} pick{origin}: {name(change['from'])} to {name(change['to'])}"


def build_items(found: list[dict[str, Any]], names: dict[str, str],
                clearance: dict[str, dict[str, Any]] | None = None) -> list[str]:
    def name(team_id: str) -> str:
        return names.get(team_id, team_id or "unknown team")

    needs = [c for c in found if c["round"] in PREPAY_ROUNDS and not c.get("reversal")]
    back = [c for c in found if c.get("reversal")]
    free = [c for c in found if c["round"] not in PREPAY_ROUNDS and not c.get("reversal")]
    items: list[str] = []
    if needs:
        verdicts = [verdict(c, clearance) for c in needs]
        if clearance is None:
            items.append("Check the League Ledger now. These are 1st or 2nd round picks, so the team giving each one up must be paid through the Season of that pick, and through every Season before it (12.2, 12.3).")
        else:
            items.append("Checked against the League Ledger's Pick Clearance tab. The team giving up a 1st or 2nd round pick must be paid through that pick's Season and every Season before it (12.2, 12.3).")
        for c, (status, paid) in zip(needs, verdicts):
            seller = name(c["from"])
            if status == "paid":
                items.append(f"PAID: {describe(c, names)}. {seller} is paid through Season {paid}. No action needed.")
            elif status == "unpaid":
                have = f"Season {paid}" if paid is not None else "no Season yet"
                items.append(f"NOT PAID: {describe(c, names)}. {seller} is paid through {have} but needs Season {c['year']}.")
            else:
                note = " This team is not on the Pick Clearance tab, so check it by hand." if clearance is not None else ""
                items.append(f"{describe(c, names)}. Seller must be paid through Season {c['year']}.{note}")
        statuses = {v[0] for v in verdicts}
        if "unpaid" in statuses:
            items.append("Reverse the entire trade in Fantrax and tell the franchises involved. They can make it again once the payment is confirmed (12.4, 12.5).")
        elif "unknown" in statuses:
            items.append("If the seller is not paid, reverse the entire trade in Fantrax and tell the franchises involved (12.4, 12.5).")
    if back:
        items.append("These picks went straight back to the team that had them before a recent alert, so this looks like a reversal. No prepayment check needed:")
        for c in back:
            items.append(describe(c, names) + ".")
    if free:
        items.append("Rounds 3 to 5 need no extra prepayment (12.7), listed for your records:")
        for c in free:
            items.append(describe(c, names) + ".")
    return items


def build_task(found: list[dict[str, Any]], names: dict[str, str],
               clearance: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    needs = [c for c in found if c["round"] in PREPAY_ROUNDS and not c.get("reversal")]
    statuses = {verdict(c, clearance)[0] for c in needs}
    if "unpaid" in statuses:
        label = "reverse, prepayment missing"
    elif "unknown" in statuses:
        label = "confirm prepayment"
    elif needs:
        label = "prepayment confirmed"
    elif all(c.get("reversal") for c in found):
        label = "reversal recorded"
    else:
        label = "recorded"
    title = f"Pick trade: {label}" if needs else ("Pick trade reversed" if label == "reversal recorded" else "Pick trade recorded")
    if len(found) > 1:
        title = f"{len(found)} pick moves: {label}"
    return {"title": title, "section": "Article XII", "items": build_items(found, names, clearance)}


def run(mode: str) -> int:
    cfg = load_league()
    fx = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Pick-Trades/1.0")
    cur = snapshot(fx.draft_picks())
    names = {r["teamId"]: r["teamName"] for r in normalize_standings(fx.standings())}
    state = load_json(STATE_PATH, {})
    prev = state.get("owners")
    print(f"BLHA PICK TRADES mode={mode.upper()} picks={len(cur)}")
    if mode == "preview":
        print("Fantrax team IDs (copy into the ledger's Settings tab):")
        for team_id, team_name in sorted(names.items(), key=lambda kv: kv[1].lower()):
            print(f"  {team_id}  {team_name}")
        report_clearance(names)
    if not isinstance(prev, dict):
        print("No saved copy yet: recording the current ownership as the baseline. No alert.")
        if mode == "live":
            save_json(STATE_PATH, {"owners": cur, "baselined": datetime.now(timezone.utc).isoformat()})
        return 0
    found = changes(prev, cur)
    now = datetime.now(timezone.utc)
    recent = [r for r in state.get("recent", []) if isinstance(r, dict)]
    mark_reversals(found, recent, now)
    if not found:
        print("No pick has changed owner.")
        if mode == "live" and len(cur) != len(prev):
            save_json(STATE_PATH, {**state, "owners": cur})
        return 0
    clearance = load_clearance() if any(c["round"] in PREPAY_ROUNDS and not c.get("reversal") for c in found) else None
    task = build_task(found, names, clearance)
    for line in task["items"]:
        print("  " + line)
    if mode == "preview":
        return 0
    payload = desk.build_payload(task, None, cfg, now=now)
    ok, detail = post_discord_webhook(desk.secret_name(cfg), payload)
    if not ok:
        print(f"DELIVERY ERROR: {detail} (not saved, will retry next run)")
        return 1
    print("POSTED")
    keep = [r for r in recent if _age_ok(r, now)]
    keep += [{"key": f"{c['year']}|{c['round']}|{c['original']}", "from": c["from"], "to": c["to"], "at": now.isoformat()}
             for c in found if not c.get("reversal")]
    save_json(STATE_PATH, {**state, "owners": cur, "recent": keep})
    return 0


def _age_ok(record: dict[str, Any], now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(str(record.get("at"))) <= REVERSAL_WINDOW
    except ValueError:
        return False


def test_post() -> int:
    cfg = load_league()
    names = {"a": "Test 1", "b": "Test 2", "c": "Test 3"}
    sample = [
        {"year": 2029, "round": 1, "original": "a", "from": "a", "to": "b"},
        {"year": 2030, "round": 4, "original": "c", "from": "c", "to": "a"},
    ]
    clearance = {"a": {"franchise": "Test 1", "paid_through": 2028}}
    task = build_task(sample, names, clearance)
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
