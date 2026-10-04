#!/usr/bin/env python3
"""BLHA minor-eligibility watch: tells the commissioner when a rostered player stops being minor-eligible.

Constitution Article VII: a minor-league player must be 25 or younger and have
at most 100 career NHL regular-season games (50 for goalies). Once a player
fails either test the franchise has three calendar days to remove him from the
minor slot (7.4).

Fantrax's data feed has no ages, no career games and does not say which players
are in minor slots, so this reads birth dates and career games from the NHL's
public stats API and matches players by name. It reports every rostered player
who crossed the line since the last run; the commissioner checks whether he is
actually in a minor slot. The first live run only saves a baseline.

Modes:
  preview  print what would be posted and every unmatched player; no Discord, no state change
  test     post one [TEST] sample alert; no state change
  live     post alerts and save eligibility
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from blha.fantrax import Fantrax, normalize_standings  # noqa: E402
from blha.league import load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402

STATE_PATH = ROOT / "state" / "minors.json"
NHL = "https://api-web.nhle.com/v1"
SEARCH = "https://search.d3.nhle.com/api/v1/search/player"
MAX_AGE = 25
MAX_GP = {"skater": 100, "goalie": 50}
TEAMS = (
    "ANA BOS BUF CGY CAR CHI COL CBJ DAL DET EDM FLA LAK MIN MTL NSH NJD NYI NYR OTT PHI PIT SEA SJS STL TBL TOR UTA VAN VGK WSH WPG"
).split()
TEAM_ALIAS = {"TB": "TBL", "NJ": "NJD", "LA": "LAK", "SJ": "SJS", "CLS": "CBJ", "WAS": "WSH", "VEG": "VGK"}
CACHE_HOURS = 20


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", text.lower())
    return re.sub(r"[^a-z]", "", text)


def fantrax_name(raw: str) -> tuple[str, str]:
    """'Hyman, Zach' -> ('Zach', 'Hyman')."""
    if "," in raw:
        last, first = raw.split(",", 1)
        return first.strip(), last.strip()
    parts = raw.split()
    return (" ".join(parts[:-1]), parts[-1]) if parts else ("", "")


def age_on(birth: str, today: date) -> int:
    y, m, d = (int(x) for x in birth.split("-"))
    return today.year - y - ((today.month, today.day) < (m, d))


def eligible(age: int, games: int, goalie: bool) -> bool:
    return age <= MAX_AGE and games <= MAX_GP["goalie" if goalie else "skater"]


class Index:
    """NHL players by normalised name, built from team rosters and prospect lists."""

    def __init__(self) -> None:
        self.by_full: dict[str, list[dict[str, Any]]] = {}
        self.by_last: dict[str, list[dict[str, Any]]] = {}

    def add(self, player: dict[str, Any]) -> None:
        self.by_full.setdefault(norm(player["first"] + player["last"]), []).append(player)
        self.by_last.setdefault(norm(player["last"]), []).append(player)

    def find(self, first: str, last: str, team: str) -> dict[str, Any] | None:
        team = TEAM_ALIAS.get(team, team)
        full = self.by_full.get(norm(first + last), [])
        if full:
            same = [p for p in full if p["team"] == team]
            return (same or full)[0]
        # Nickname first names (Zach/Zachary, Alex/Alexander): same last name, same initial, same team.
        cands = [p for p in self.by_last.get(norm(last), []) if norm(p["first"])[:1] == norm(first)[:1]]
        same = [p for p in cands if p["team"] == team]
        if len(same) == 1:
            return same[0]
        if len(cands) == 1:
            return cands[0]
        return None


MIN_GAP = 0.4  # seconds between NHL requests; the API answers 429 when hit too fast
_last_call = [0.0]


def _get(session: requests.Session, url: str, **params: Any) -> Any:
    last: Exception | None = None
    for attempt in range(5):
        wait = MIN_GAP - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            r = session.get(url, params=params or None, timeout=20)
            if r.status_code == 404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(min(2 ** (attempt + 1), 30))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # retry, then report
            last = exc
            time.sleep(1)
    raise RuntimeError(f"NHL request failed: {url} ({last})")


def build_index(session: requests.Session) -> Index:
    index = Index()
    for team in TEAMS:
        roster = _get(session, f"{NHL}/roster/{team}/current") or {}
        prospects = _get(session, f"{NHL}/prospects/{team}") or {}
        for group in ("forwards", "defensemen", "goalies"):
            for p in (roster.get(group) or []) + (prospects.get(group) or []):
                index.add({
                    "id": p["id"], "first": (p.get("firstName") or {}).get("default", ""),
                    "last": (p.get("lastName") or {}).get("default", ""),
                    "birthDate": p.get("birthDate"), "team": team,
                })
    return index


def search_player(session: requests.Session, first: str, last: str) -> dict[str, Any] | None:
    hits = _get(session, SEARCH, culture="en-us", limit=10, q=f"{first} {last}") or []
    for h in hits:
        if norm(h.get("name", "")) == norm(first + last):
            parts = h["name"].split(" ", 1)
            return {"id": int(h["playerId"]), "first": parts[0], "last": parts[-1], "birthDate": h.get("birthDate"), "team": h.get("teamAbbrev")}
    return None


def career_games(session: requests.Session, nhl_id: int) -> int:
    landing = _get(session, f"{NHL}/player/{nhl_id}/landing") or {}
    return int(((landing.get("careerTotals") or {}).get("regularSeason") or {}).get("gamesPlayed") or 0)


def evaluate(
    rostered: list[dict[str, Any]],
    index: Index,
    session: requests.Session,
    cache: dict[str, Any],
    today: date,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """fantraxId -> {name, team, franchise, age, games, eligible}; plus unmatched names."""
    out: dict[str, dict[str, Any]] = {}
    unmatched: list[str] = []
    for r in rostered:
        first, last = fantrax_name(r["name"])
        goalie = r["position"] == "G"
        found = index.find(first, last, r["nhl_team"]) or search_player(session, first, last)
        if not found:
            unmatched.append(r["name"])
            continue
        entry = cache.get(str(found["id"]))
        birth = found.get("birthDate") or (entry or {}).get("birthDate")
        if not birth:
            landing = _get(session, f"{NHL}/player/{found['id']}/landing") or {}
            birth = landing.get("birthDate")
        if not birth:
            unmatched.append(r["name"])
            continue
        age = age_on(birth, today)
        fresh = entry and (now - datetime.fromisoformat(entry["at"])).total_seconds() < CACHE_HOURS * 3600
        if age > MAX_AGE:
            games = int(entry["games"]) if entry else 0  # ineligible by age; games irrelevant
        elif fresh:
            games = int(entry["games"])
        else:
            games = career_games(session, found["id"])
            cache[str(found["id"])] = {"games": games, "birthDate": birth, "at": now.isoformat()}
        out[r["fantraxId"]] = {
            "name": r["name"], "nhlTeam": r["nhl_team"], "franchise": r["franchise"],
            "age": age, "games": games, "goalie": goalie, "eligible": eligible(age, games, goalie),
        }
    return out, unmatched


def crossed(prev: dict[str, bool], cur: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Players who were minor-eligible at the last run and are not now."""
    return sorted(
        ({**v, "id": k} for k, v in cur.items() if prev.get(k) is True and not v["eligible"]),
        key=lambda v: (v["franchise"], v["name"]),
    )


def reason(p: dict[str, Any]) -> str:
    limit = MAX_GP["goalie" if p["goalie"] else "skater"]
    parts = []
    if p["age"] > MAX_AGE:
        parts.append(f"now age {p['age']}")
    if p["games"] > limit:
        parts.append(f"{p['games']} career NHL games (limit {limit})")
    return " and ".join(parts)


def build_task(found: list[dict[str, Any]]) -> dict[str, Any]:
    title = "Minor eligibility: 1 player is now ineligible" if len(found) == 1 else f"Minor eligibility: {len(found)} players are now ineligible"
    items = [
        "If a player below is in a minor-league slot, his franchise has three calendar days from Fantrax flagging him to promote, trade, drop or otherwise remove him (7.4). Fantrax's own age is final (7.2).",
        *[f"{p['name']} ({p['nhlTeam']}) on {p['franchise']}: {reason(p)}." for p in found],
    ]
    return {"title": title, "section": "Article VII", "items": items}


def load_rostered(fx: Fantrax) -> list[dict[str, Any]]:
    names = {r["teamId"]: r["teamName"] for r in normalize_standings(fx.standings())}
    ids = fx.player_ids()
    out = []
    for team_id, team in (fx.rosters().get("rosters") or {}).items():
        for item in team.get("rosterItems") or []:
            info = ids.get(item["id"]) or {}
            if not info.get("name"):
                continue
            out.append({
                "fantraxId": item["id"], "name": info["name"], "position": item.get("position") or info.get("position"),
                "nhl_team": info.get("team") or "", "franchise": team.get("teamName") or names.get(team_id, team_id),
            })
    return out


def run(mode: str, today: date | None = None, session: requests.Session | None = None) -> int:
    cfg = load_league()
    now = datetime.now(timezone.utc)
    today = today or now.astimezone(timezone_of(cfg)).date()
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "BLHA-Minors/1.0")
    fx = Fantrax(str(cfg["league_id"]), user_agent="BLHA-Minors/1.0")
    rostered = load_rostered(fx)
    state = load_json(STATE_PATH, {})
    cache = state.setdefault("nhl", {})
    cur, unmatched = evaluate(rostered, build_index(session), session, cache, today, now)
    print(f"BLHA MINORS mode={mode.upper()} rostered={len(rostered)} matched={len(cur)} unmatched={len(unmatched)} ineligible={sum(not v['eligible'] for v in cur.values())}")
    if unmatched:
        print("Could not match to an NHL player: " + "; ".join(sorted(unmatched)[:40]))
    new_state = {**state, "nhl": cache, "eligible": {k: v["eligible"] for k, v in cur.items()}}
    prev = state.get("eligible")
    if not isinstance(prev, dict):
        print("No saved copy yet: recording eligibility as the baseline. No alert.")
        if mode == "live":
            save_json(STATE_PATH, {**new_state, "baselined": now.isoformat()})
        return 0
    found = crossed(prev, cur)
    if not found:
        print("No rostered player has become minor-ineligible.")
        if mode == "live":
            save_json(STATE_PATH, new_state)
        return 0
    task = build_task(found)
    for line in task["items"]:
        print("  " + line)
    if mode == "preview":
        return 0
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, now=now))
    if not ok:
        print(f"DELIVERY ERROR: {detail} (not saved, will retry next run)")
        return 1
    print("POSTED")
    save_json(STATE_PATH, new_state)
    return 0


def test_post() -> int:
    cfg = load_league()
    sample = [{"name": "Sample, Player", "nhlTeam": "EDM", "franchise": "Test 1", "age": 26, "games": 40, "goalie": False}]
    task = build_task(sample)
    task["items"].insert(0, "Sample only. No player has actually changed.")
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, test=True))
    print(("PASS" if ok else "ERROR") + f" [minors]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()
    return test_post() if args.mode == "test" else run(args.mode)


if __name__ == "__main__":
    sys.exit(main())
