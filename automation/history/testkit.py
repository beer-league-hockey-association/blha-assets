"""Offline building blocks for the history tests: a fake Fantrax built from the live fixtures,
and helpers that write small archives directly. Not used by any workflow."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from blha.fantrax import normalize_standings, schedule_for
from history.store import Archive

AUTOMATION = Path(__file__).resolve().parents[1]
FIXTURES = AUTOMATION / "tests" / "fixtures"


def fixture(name: str) -> Any:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data.get("response", data) if isinstance(data, dict) and "_note" in data and "response" in data else data


INFO = fixture("league_info_2026_test.json")
TEAMS = sorted(INFO["teamInfo"])
NAMES = {t: INFO["teamInfo"][t]["name"] for t in TEAMS}
REAL_ROSTERS = fixture("team_rosters_sample_test.json")
PICKS = fixture("draft_picks_test.json")
DRAFT = fixture("draft_results_2026_test.json")
PLAYER_IDS = fixture("player_ids_sample.json")
STANDINGS = fixture("standings_week0.json")
SCORES_P2 = fixture("matchup_scores_period2_test.json")
CFG = {"league_id": "w02cjakmmumb3lur", "season_label": "2026-27 TEST", "timezone": "America/New_York",
       "color": 0xFFB81C, "rivals": []}


def rosters_raw() -> dict[str, Any]:
    """All 12 teams: the two real fixture rosters plus ten synthetic 36-player rosters (20/6/10)."""
    raw = copy.deepcopy(REAL_ROSTERS)
    for i, team in enumerate(TEAMS):
        if team in raw["rosters"]:
            continue
        items = []
        for n in range(36):
            status = "ACTIVE" if n < 20 else "RESERVE" if n < 26 else "MINORS"
            items.append({"id": f"s{i:02d}{n:02d}", "position": "C", "status": status})
        raw["rosters"][team] = {"teamName": NAMES[team], "rosterItems": items}
    return raw


def scores(period: int) -> list[dict[str, Any]]:
    """Deterministic final scores for a week, in normalize_scores' shape."""
    out = []
    for i, m in enumerate(schedule_for(INFO, period)):
        away = 80 + (period * 7 + i * 13) % 40
        home = 80 + (period * 11 + i * 5) % 40
        out.append({"away": {**m["away"], "score": float(away), "gamesPlayed": 30.0},
                    "home": {**m["home"], "score": float(home), "gamesPlayed": 31.0}})
    return out


class FakeFantrax:
    def __init__(self, *, info: dict | None = None, rosters: dict | None = None, picks: dict | None = None,
                 draft: dict | None = None, standings: list | None = None,
                 matchup: Callable[[int], list] | None = None) -> None:
        self.info = info or INFO
        self.raw_rosters = rosters or rosters_raw()
        self.raw_picks = picks if picks is not None else copy.deepcopy(PICKS)
        self.raw_draft = draft if draft is not None else copy.deepcopy(DRAFT)
        self.raw_standings = standings if standings is not None else copy.deepcopy(STANDINGS)
        self.matchup = matchup or scores
        self.calls: list[str] = []

    def league_info(self) -> dict:
        self.calls.append("info")
        return self.info

    def rosters(self) -> dict:
        self.calls.append("rosters")
        return self.raw_rosters

    def draft_picks(self) -> Any:
        self.calls.append("picks")
        if isinstance(self.raw_picks, Exception):
            raise self.raw_picks
        return self.raw_picks

    def draft_results(self) -> Any:
        self.calls.append("draft")
        return self.raw_draft

    def player_ids(self) -> dict:
        self.calls.append("ids")
        return PLAYER_IDS

    def standings(self) -> list:
        self.calls.append("standings")
        return normalize_standings(self.raw_standings)

    def matchup_scores(self, period: int) -> list:
        self.calls.append(f"scores:{period}")
        return self.matchup(period)


def move_player(raw: dict, player: str, to_team: str, status: str = "RESERVE") -> None:
    for team in raw["rosters"].values():
        team["rosterItems"] = [i for i in team["rosterItems"] if i["id"] != player]
    raw["rosters"][to_team]["rosterItems"].append({"id": player, "position": "C", "status": status})


def drop_player(raw: dict, player: str) -> None:
    for team in raw["rosters"].values():
        team["rosterItems"] = [i for i in team["rosterItems"] if i["id"] != player]


def set_pick_owner(raw: dict, year: int, rnd: int, original: str, owner: str) -> None:
    for row in raw["futureDraftPicks"]:
        if row["year"] == year and row["round"] == rnd and row["originalOwnerTeamId"] == original:
            row["currentOwnerTeamId"] = owner


# --- writing archives directly -----------------------------------------------------

def week(period: int, pairs: list[tuple[str, float, str, float]], playoff: bool = False, played: bool = True) -> dict:
    return {"period": period, "playoff": playoff, "played": played, "start": "", "end": "",
            "matchups": [{"away": {"team": a, "score": sa}, "home": {"team": b, "score": sb}} for a, sa, b, sb in pairs]}


def write_season(root: Path, season: int, *, teams: dict[str, str], label: str = "", results: dict | None = None,
                 events: list[dict] | None = None, rosters: dict | None = None, draft: dict | None = None,
                 standings: dict | None = None) -> Archive:
    arch = Archive(root)
    arch.write(season, "meta.json", {"season": season, "season_label": label, "test": "TEST" in label.upper(),
                                     "teams": teams, "last_snapshot": f"{season}-11-01T10:30:00+00:00"})
    arch.write(season, "results.json", results or {})
    if rosters is not None:
        arch.write(season, "rosters.json", rosters)
    if draft is not None:
        arch.write(season, "draft.json", draft)
    if standings is not None:
        arch.write(season, "standings.json", standings)
    arch.append_events(season, events or [])
    return arch


def trade(event_id: str, at: str, moves: list[tuple[str, str, str]]) -> dict:
    """A trade event from (asset, from, to) moves, shaped like collect.group_trades output."""
    teams = sorted({f for _, f, _ in moves} | {t for _, _, t in moves})
    return {"id": event_id, "type": "trade", "at": at, "date": at[:10], "season": int(at[:4]), "teams": teams,
            "received": {t: sorted(a for a, _, to in moves if to == t) for t in teams},
            "sent": {t: sorted(a for a, f, _ in moves if f == t) for t in teams},
            "moves": [{"asset": a, "from": f, "to": t} for a, f, t in moves]}


def simple(event_id: str, at: str, kind: str, team: str, player: str) -> dict:
    return {"id": event_id, "type": kind, "at": at, "date": at[:10], "season": int(at[:4]), "team": team, "player": player}
