#!/usr/bin/env python3
"""BLHA League Archive: one daily snapshot that builds the league's permanent history.

Fantrax's read-only feed has no transaction log, so each run compares today's
rosters and draft-pick ownership with the last saved snapshot and writes what
changed to an append-only events file:

  add     a player joined a roster from the unowned pool (players taken in a
          draft since the last run are not adds; the draft results record them)
  drop    a player left every roster (back to the pool)
  trade   players and picks that moved straight from one team to another in the
          same run. Everything connected in one run is one trade, so a
          three-team deal is one event listing what each side received. Two
          separate trades between overlapping teams on the same day are joined.
  status  moves into or out of a MINORS or IR slot (daily ACTIVE/RESERVE
          lineup changes are not recorded)

It also keeps the latest roster snapshot and pick ownership, the final scores
of every finished week (re-read for three days in case of stat corrections),
the final regular-season standings, and the draft results once a draft is
complete. Everything is filed under the Fantrax season (seasonYear), so
renewing the league never overwrites history. The first run of each season
saves a baseline only and records no events.

Limits of inferring from daily snapshots: a player dropped by one team and
claimed by another between two runs looks like a one-sided trade (flagged
``one_sided``); a player added and dropped between runs is never seen.

Modes:
  preview  read Fantrax, compare with the restored archive and print what would be saved; writes nothing
  live     save snapshots, new events, results, standings and draft results under archive/
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))

from blha import draft as dr  # noqa: E402
from blha import season as cal  # noqa: E402
from blha.fantrax import Fantrax, games_counted  # noqa: E402
from blha.league import load_league, timezone_of  # noqa: E402
from history.store import Archive, is_test_label, parse_asset  # noqa: E402

TRACKED_STATUSES = {"MINORS", "IR"}
RESULT_RECHECK = timedelta(days=3)
MAX_VANISHED_SHARE = 0.4


class SnapshotError(RuntimeError):
    """Fantrax returned something that cannot be a real roster snapshot."""


# --- snapshots ---------------------------------------------------------------------

def season_of(info: dict[str, Any]) -> int:
    try:
        return int(info.get("seasonYear"))
    except (TypeError, ValueError):
        start = str(info.get("startDate") or "")[:4]
        if start.isdigit():
            return int(start)
        raise ValueError("getLeagueInfo has neither seasonYear nor startDate") from None


def roster_snapshot(raw: Any) -> dict[str, dict[str, str]]:
    """team id -> {player id: status} from getTeamRosters."""
    rosters = raw.get("rosters") if isinstance(raw, dict) else None
    if not isinstance(rosters, dict):
        raise SnapshotError("getTeamRosters returned no rosters object")
    out: dict[str, dict[str, str]] = {}
    for team_id, team in rosters.items():
        items = team.get("rosterItems") if isinstance(team, dict) else None
        out[str(team_id)] = {
            str(item["id"]): str(item.get("status") or "").upper()
            for item in items or []
            if isinstance(item, dict) and item.get("id")
        }
    return out


def roster_names(raw: Any) -> dict[str, str]:
    rosters = raw.get("rosters") if isinstance(raw, dict) else {}
    return {str(t): str(v.get("teamName")) for t, v in (rosters or {}).items() if isinstance(v, dict) and v.get("teamName")}


def pick_snapshot(raw: Any, draft_year: int | None = None) -> dict[str, str]:
    """pick key -> current owner, for future picks and (during a draft) current-draft picks."""
    if not isinstance(raw, dict) or not isinstance(raw.get("futureDraftPicks"), list):
        raise SnapshotError("getDraftPicks has no futureDraftPicks list")
    out: dict[str, str] = {}
    for source in ("futureDraftPicks", "currentDraftPicks"):
        for row in raw.get(source) or []:
            if not isinstance(row, dict):
                continue
            year = row.get("year") or (draft_year if source == "currentDraftPicks" else None)
            original, owner = row.get("originalOwnerTeamId"), row.get("currentOwnerTeamId")
            if not (year and row.get("round") and original and owner):
                continue
            out[f"{int(year)}|{int(row['round'])}|{original}"] = str(owner)
    return out


def check_sane(prev: dict[str, dict[str, str]], cur: dict[str, dict[str, str]]) -> None:
    """Refuse a snapshot that would turn a Fantrax hiccup into mass drops."""
    before = {p for roster in prev.values() for p in roster}
    after = {p for roster in cur.values() for p in roster}
    if len(before) >= 24 and len(before - after) > MAX_VANISHED_SHARE * len(before):
        raise SnapshotError(
            f"{len(before - after)} of {len(before)} rostered players vanished in one run; "
            "treating Fantrax's answer as incomplete and saving nothing")
    missing = set(prev) - set(cur)
    if prev and len(missing) > len(prev) / 2:
        raise SnapshotError(f"{len(missing)} of {len(prev)} teams are missing from Fantrax's rosters; saving nothing")


# --- diffing -----------------------------------------------------------------------

def owners(rosters: dict[str, dict[str, str]]) -> dict[str, str]:
    return {player: team for team, roster in rosters.items() for player in roster}


def player_changes(prev: dict[str, dict[str, str]], cur: dict[str, dict[str, str]],
                   drafted: set[str] = frozenset()) -> tuple[list, list, list, list]:
    """(adds, drops, moves, status changes) between two roster snapshots."""
    was, now = owners(prev), owners(cur)
    adds, drops, moves, statuses = [], [], [], []
    for player in sorted(set(was) | set(now)):
        a, b = was.get(player), now.get(player)
        if a and not b:
            drops.append({"team": a, "player": player})
        elif b and not a:
            if player not in drafted:
                adds.append({"team": b, "player": player, "status": cur[b][player]})
        elif a != b:
            moves.append({"asset": f"player:{player}", "from": a, "to": b})
        else:
            old, new = prev[a][player], cur[b][player]
            if old != new and {old, new} & TRACKED_STATUSES:
                statuses.append({"team": b, "player": player, "from": old, "to": new})
    return adds, drops, moves, statuses


def pick_changes(prev: dict[str, str], cur: dict[str, str]) -> list[dict[str, str]]:
    """Picks whose owner changed. New or vanished keys (the window rolling, a draft using them) are ignored."""
    return [
        {"asset": f"pick:{key}", "from": prev[key], "to": owner}
        for key, owner in sorted(cur.items())
        if key in prev and prev[key] != owner
    ]


def group_trades(moves: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Join moves that share a team into trades; each lists what every side received and sent."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in moves:
        ra, rb = find(m["from"]), find(m["to"])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[str, list[dict[str, str]]] = {}
    for m in moves:
        groups.setdefault(find(m["from"]), []).append(m)
    trades = []
    for _, group in sorted(groups.items()):
        teams = sorted({m["from"] for m in group} | {m["to"] for m in group})
        received = {t: sorted(m["asset"] for m in group if m["to"] == t) for t in teams}
        sent = {t: sorted(m["asset"] for m in group if m["from"] == t) for t in teams}
        trade = {"teams": teams, "received": received, "sent": sent,
                 "moves": sorted(group, key=lambda m: (m["from"], m["asset"]))}
        if any(not received[t] for t in teams):
            trade["one_sided"] = True
        trades.append(trade)
    return trades


def drafted_since(draft: dr.Draft | None, since: datetime | None) -> set[str]:
    """Players taken in a draft after the previous snapshot (they join rosters by draft, not as adds)."""
    if draft is None:
        return set()
    out = set()
    fallback = draft.end or draft.start or draft.date
    for pick in draft.picks:
        if not pick.made:
            continue
        when = pick.time or fallback
        if since is None or when is None or when >= since - timedelta(hours=1):
            out.add(pick.player_id)
    return out


def build_events(season: int, at: datetime, since: datetime | None, tz: ZoneInfo,
                 adds: list, drops: list, statuses: list, trades: list) -> list[dict[str, Any]]:
    stamp = at.strftime("%Y%m%dT%H%M%S")
    base = {"season": season, "at": at.isoformat(), "date": at.astimezone(tz).date().isoformat()}
    if since:
        base["since"] = since.isoformat()
    rows = ([{"type": "trade", **t} for t in trades] + [{"type": "drop", **d} for d in drops]
            + [{"type": "add", **a} for a in adds] + [{"type": "status", **s} for s in statuses])
    return [{"id": f"{season}-{stamp}-{i:03d}", **base, **row} for i, row in enumerate(rows, 1)]


# --- results, standings, draft -----------------------------------------------------

def capture_results(fx: Any, info: dict[str, Any], saved: dict[str, Any], now: datetime,
                    tz: ZoneInfo) -> tuple[dict[str, Any], list[int]]:
    """Final scores for every finished week not saved yet (or still inside the stat-correction window)."""
    last_regular, _, _ = cal.playoff_settings(info)
    out = dict(saved)
    changed = []
    for p in cal.periods(info):
        if not cal.is_final(p, now, tz):
            continue
        key = str(p.number)
        if key in saved and now - cal.final_at(p, tz) > RESULT_RECHECK:
            continue
        rows = fx.matchup_scores(p.number)
        matchups = [
            {side: {"team": m[side]["teamId"], "score": round(m[side]["score"], 2)} for side in ("away", "home")}
            for m in rows if m["away"]["teamId"] and m["home"]["teamId"]
        ]
        entry = {
            "period": p.number,
            "start": p.start.isoformat(),
            "end": p.end.isoformat(),
            "playoff": p.number > last_regular,
            "played": any(m[s]["score"] or m[s]["gamesPlayed"] for m in rows for s in ("away", "home")),
            "matchups": matchups,
        }
        if saved.get(key) != entry:
            out[key] = entry
            changed.append(p.number)
    return out, changed


def capture_standings(fx: Any, info: dict[str, Any], saved: dict[str, Any] | None, now: datetime,
                      tz: ZoneInfo) -> dict[str, Any] | None:
    """Final regular-season standings, once Fantrax has counted the last regular week."""
    if saved:
        return None
    last_regular, _, _ = cal.playoff_settings(info)
    last = cal.period(info, last_regular)
    if last is None or not cal.is_final(last, now, tz):
        return None
    rows = fx.standings()   # Fantrax.standings() returns normalized rows
    counted = games_counted(rows)
    if counted is None or counted < last_regular:
        return None
    keep = ("rank", "teamId", "teamName", "record", "wins", "losses", "ties", "pointsFor")
    return {"after_week": last_regular, "saved_at": now.isoformat(), "rows": [{k: r[k] for k in keep} for r in rows]}


def capture_draft(draft: dr.Draft | None, saved: dict[str, Any] | None, tz: ZoneInfo) -> dict[str, Any] | None:
    """Draft results once the draft is complete (and again if Fantrax reschedules a new one)."""
    if draft is None or not draft.completed or not draft.picks:
        return None
    if saved and saved.get("key") == draft.key:
        return None
    when = draft.date or draft.start or draft.end
    return {
        "key": draft.key,
        "year": when.astimezone(tz).year if when else None,
        "date": draft.date.isoformat() if draft.date else None,
        "start": draft.start.isoformat() if draft.start else None,
        "end": draft.end.isoformat() if draft.end else None,
        "state": draft.state,
        "order": draft.order,
        "picks": [{"round": p.round, "overall": p.overall, "in_round": p.in_round, "team": p.team_id,
                   "player": p.player_id} for p in draft.picks],
    }


def refresh_players(cache: dict[str, Any], ids: dict[str, Any], wanted: set[str]) -> dict[str, Any]:
    """Keep names for every player the archive mentions (small file, not the whole Fantrax pool)."""
    out = dict(cache)
    for pid in wanted:
        row = ids.get(pid) if isinstance(ids, dict) else None
        if isinstance(row, dict) and row.get("name"):
            out[pid] = {k: row.get(k) for k in ("name", "position", "team") if row.get(k)}
    return out


def mentioned_players(rosters: dict[str, dict[str, str]], events: list[dict[str, Any]],
                      draft: dict[str, Any] | None) -> set[str]:
    out = {p for roster in rosters.values() for p in roster}
    for e in events:
        if e.get("player"):
            out.add(str(e["player"]))
        for m in e.get("moves") or []:
            kind, value = parse_asset(m["asset"])
            if kind == "player":
                out.add(value)
    for pick in (draft or {}).get("picks") or []:
        if pick.get("player"):
            out.add(str(pick["player"]))
    return out


def season_meta(info: dict[str, Any], cfg: dict[str, Any], names: dict[str, str], prev: dict[str, Any],
                now: datetime) -> dict[str, Any]:
    last_regular, first_playoff, playoff_teams = cal.playoff_settings(info)
    teams = {str(t): str((row or {}).get("name") or names.get(t) or t) for t, row in (info.get("teamInfo") or {}).items()}
    for team_id, name in names.items():
        teams.setdefault(team_id, name)
    label = str(cfg.get("season_label") or "")
    return {
        **prev,
        "season": season_of(info),
        "league_id": str(cfg.get("league_id") or ""),
        "league_name": str(info.get("leagueName") or ""),
        "season_label": label,
        "test": is_test_label(label),
        "teams": teams,
        "periods": [{"number": p.number, "start": p.start.isoformat(), "end": p.end.isoformat()} for p in cal.periods(info)],
        "last_regular": last_regular,
        "first_playoff": first_playoff,
        "playoff_teams": playoff_teams,
        "first_run": prev.get("first_run") or now.isoformat(),
    }


# --- run ---------------------------------------------------------------------------

def describe(event: dict[str, Any], teams: dict[str, str], players: dict[str, Any]) -> str:
    def team(t: str) -> str:
        return teams.get(t, t)

    def asset(a: str) -> str:
        kind, value = parse_asset(a)
        if kind == "player":
            return str((players.get(value) or {}).get("name") or value)
        year, rnd, original = (value.split("|") + ["", "", ""])[:3]
        return f"{year} round {rnd} pick ({team(original)})"

    kind = event["type"]
    if kind == "trade":
        sides = "; ".join(f"{team(t)} gets {', '.join(asset(a) for a in event['received'][t]) or 'nothing'}"
                          for t in event["teams"])
        return f"TRADE   {sides}" + (" (one-sided: may be a drop and claim between runs)" if event.get("one_sided") else "")
    if kind == "status":
        return f"STATUS  {team(event['team'])}: {asset('player:' + event['player'])} {event['from']} -> {event['to']}"
    return f"{kind.upper():7} {team(event['team'])}: {asset('player:' + event['player'])}"


def run(mode: str, *, now: datetime | None = None, fx: Any = None, archive: Archive | None = None,
        cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or load_league()
    tz = timezone_of(cfg)
    now = now or datetime.now(timezone.utc)
    fx = fx or Fantrax(str(cfg["league_id"]), user_agent="BLHA-Archive/1.0")
    archive = archive or Archive()

    info = fx.league_info()
    season = season_of(info)
    meta = archive.meta(season)
    roster_raw = fx.rosters()
    rosters = roster_snapshot(roster_raw)

    try:
        draft = dr.parse_results(fx.draft_results())
    except Exception as exc:  # the draft feed is optional for the archive
        print(f"WARNING: could not read draft results ({exc}); skipping draft checks this run.")
        draft = None
    draft_year = None
    when = draft and (draft.date or draft.start)
    if when:
        draft_year = when.astimezone(tz).year
    try:
        picks: dict[str, str] | None = pick_snapshot(fx.draft_picks(), draft_year)
    except Exception as exc:
        print(f"WARNING: could not read draft-pick ownership ({exc}); keeping the saved copy.")
        picks = None

    label = cfg.get("season_label") or ""
    print(f"BLHA ARCHIVE mode={mode.upper()} season={season} ({label}) teams={len(rosters)} "
          f"rostered={sum(len(r) for r in rosters.values())} picks={len(picks) if picks is not None else 'n/a'}")

    since = cal.parse_dt(meta.get("last_snapshot"))
    prev_rosters = archive.rosters(season) if archive.has(season, "rosters.json") else None
    prev_picks = archive.picks(season) if archive.has(season, "picks.json") else None
    events: list[dict[str, Any]] = []
    if prev_rosters is None:
        print(f"No saved snapshot for season {season} yet: saving a baseline. No events recorded this run.")
    else:
        check_sane(prev_rosters, rosters)
        adds, drops, moves, statuses = player_changes(prev_rosters, rosters, drafted_since(draft, since))
        if picks is not None and prev_picks is not None:
            moves += pick_changes(prev_picks, picks)
        events = build_events(season, now, since, tz, adds, drops, statuses, group_trades(moves))

    results, changed = capture_results(fx, info, archive.results(season), now, tz)
    standings = capture_standings(fx, info, archive.standings(season), now, tz)
    draft_saved = capture_draft(draft, archive.draft(season), tz)

    names = {**roster_names(roster_raw)}
    new_meta = season_meta(info, cfg, names, meta, now)
    new_meta["last_snapshot"] = now.isoformat()
    if prev_rosters is None:
        new_meta["baseline_at"] = now.isoformat()

    try:
        ids = fx.player_ids()
    except Exception as exc:
        print(f"WARNING: could not read Fantrax player names ({exc}); keeping saved names.")
        ids = {}
    players = refresh_players(archive.players(), ids, mentioned_players(rosters, events, draft_saved or archive.draft(season)))

    for e in events:
        print("  " + describe(e, new_meta["teams"], players))
    print(f"Events: {len(events)}. Final weeks saved or corrected: {changed or 'none'}. "
          f"Final standings: {'saved now' if standings else ('already saved' if archive.standings(season) else 'not final yet')}. "
          f"Draft results: {'saved now' if draft_saved else ('already saved' if archive.draft(season) else 'no completed draft')}.")

    if mode != "live":
        print("PREVIEW: nothing written.")
        return 0
    archive.write(season, "rosters.json", rosters)
    if picks is not None:
        archive.write(season, "picks.json", picks)
    archive.append_events(season, events)
    if changed or not archive.has(season, "results.json"):
        archive.write(season, "results.json", results)
    if standings:
        archive.write(season, "standings.json", standings)
    if draft_saved:
        archive.write(season, "draft.json", draft_saved)
    archive.write_players(players)
    archive.write(season, "meta.json", new_meta)
    print(f"SAVED archive/{season}/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "live"), default="preview")
    args = parser.parse_args()
    try:
        return run(args.mode)
    except SnapshotError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
