#!/usr/bin/env python3
"""BLHA prospect board: NHL Central Scouting's ranked draft prospects, for the commissioner only.

Reads the newest published NHL Central Scouting rankings (midterm and final
ranks, four lists: North American skaters, international skaters, North
American goalies, international goalies) and posts the top of each list to the
private Commissioner Desk channel. It posts only when something changed since
the last post: a new draft class, a new ranking release, or a player moving up
or down five or more places. The first live run posts the current board.

Nothing here touches the owner-facing channels.

Modes:
  preview  print the board and what would be posted; no Discord, no state change
  test     post one [TEST] board; no state change
  live     post when the rankings changed and save them
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from blha.league import load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402
from minors import NHL, _get, age_on  # noqa: E402

STATE_PATH = ROOT / "state" / "prospects.json"
CONFIG_PATH = ROOT / "prospects.yaml"
CATEGORIES = {
    1: "North American skaters",
    2: "International skaters",
    3: "North American goalies",
    4: "International goalies",
}
MOVE_MIN = 5


def load_config(path: Path = CONFIG_PATH) -> dict[int, int]:
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("top") or {}
    return {cid: int(raw.get(cid, raw.get(str(cid), 0))) for cid in CATEGORIES}


def player_key(p: dict[str, Any]) -> str:
    return f"{p.get('firstName', '')} {p.get('lastName', '')}|{p.get('birthDate', '')}"


def current_rank(p: dict[str, Any]) -> int | None:
    return p.get("finalRank") or p.get("midtermRank")


def fetch_board(session: requests.Session) -> dict[str, Any]:
    first = _get(session, f"{NHL}/draft/rankings/now")
    if not first or not first.get("rankings"):
        raise RuntimeError("NHL returned no draft rankings")
    year = int(first["draftYear"])
    lists = {int(first["categoryId"]): first["rankings"]}
    for cid in CATEGORIES:
        if cid not in lists:
            data = _get(session, f"{NHL}/draft/rankings/{year}/{cid}") or {}
            lists[cid] = data.get("rankings") or []
    return {"year": year, "lists": lists}


def ranked(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((p for p in players if current_rank(p)), key=lambda p: current_rank(p))


def snapshot(board: dict[str, Any]) -> dict[str, Any]:
    ranks = {}
    for cid, players in board["lists"].items():
        for p in ranked(players):
            ranks[f"{cid}|{player_key(p)}"] = current_rank(p)
    stamp = hashlib.sha256(json.dumps(sorted(ranks.items())).encode()).hexdigest()[:16]
    return {"year": board["year"], "ranks": ranks, "hash": stamp}


def movers(prev: dict[str, Any], board: dict[str, Any], top: dict[int, int]) -> list[str]:
    out = []
    for cid, players in board["lists"].items():
        for p in ranked(players)[: top.get(cid, 0)]:
            before = (prev.get("ranks") or {}).get(f"{cid}|{player_key(p)}")
            now = current_rank(p)
            if before and abs(before - now) >= MOVE_MIN:
                direction = "up" if now < before else "down"
                out.append(f"{p['firstName']} {p['lastName']} moved {direction} from {before} to {now} ({CATEGORIES[cid]}).")
    return out


def describe(p: dict[str, Any], today: date) -> str:
    age = age_on(p["birthDate"], today) if p.get("birthDate") else None
    where = p.get("lastAmateurClub", "").title()
    league = p.get("lastAmateurLeague", "")
    place = f"{where} ({league})" if league else where
    ranks = []
    if p.get("finalRank"):
        ranks.append(f"final {p['finalRank']}")
    if p.get("midtermRank"):
        ranks.append(f"midterm {p['midtermRank']}")
    bits = [p.get("positionCode", ""), place, f"age {age}" if age is not None else "", ", ".join(ranks)]
    return f"{current_rank(p)}. {p['firstName']} {p['lastName']}: " + ", ".join(b for b in bits if b)


def build_task(board: dict[str, Any], top: dict[int, int], today: date, moved: list[str] | None = None) -> dict[str, Any]:
    items = [
        f"NHL Central Scouting rankings for the {board['year']} draft class. These are NHL's own lists, not BLHA rankings. Use them for scouting only.",
    ]
    for cid, name in CATEGORIES.items():
        n = top.get(cid, 0)
        players = ranked(board["lists"].get(cid, []))[:n]
        if players:
            items.append(f"**{name}, top {len(players)}**\n" + "\n".join(describe(p, today) for p in players))
    if moved:
        items.append("**Biggest moves since the last post**\n" + "\n".join(moved))
    return {"title": f"Prospect board: {board['year']} draft class", "section": "Scouting", "items": items}


def run(mode: str, session: requests.Session | None = None, today: date | None = None) -> int:
    cfg = load_league()
    today = today or datetime.now(timezone.utc).astimezone(timezone_of(cfg)).date()
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "BLHA-Prospects/1.0")
    top = load_config()
    board = fetch_board(session)
    snap = snapshot(board)
    state = load_json(STATE_PATH, {})
    print(f"BLHA PROSPECTS mode={mode.upper()} year={board['year']} lists={ {CATEGORIES[c]: len(p) for c, p in board['lists'].items()} }")
    if state.get("hash") == snap["hash"]:
        print("Rankings have not changed since the last post.")
        return 0
    moved = movers(state, board, top) if state.get("year") == board["year"] else []
    task = build_task(board, top, today, moved)
    for line in task["items"]:
        print(line)
    if mode == "preview":
        return 0
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, now=datetime.now(timezone.utc)))
    if not ok:
        print(f"DELIVERY ERROR: {detail} (not saved, will retry next run)")
        return 1
    print("POSTED")
    save_json(STATE_PATH, snap)
    return 0


def test_post() -> int:
    cfg = load_league()
    session = requests.Session()
    session.headers["User-Agent"] = "BLHA-Prospects/1.0"
    task = build_task(fetch_board(session), {1: 3, 2: 2, 3: 1, 4: 1}, date.today())
    task["items"].insert(0, "Sample only. Real posts use the full lists.")
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, test=True))
    print(("PASS" if ok else "ERROR") + f" [prospects]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()
    return test_post() if args.mode == "test" else run(args.mode)


if __name__ == "__main__":
    sys.exit(main())
