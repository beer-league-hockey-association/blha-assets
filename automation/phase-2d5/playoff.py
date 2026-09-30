#!/usr/bin/env python3
"""BLHA Phase 2D.5 — Fantrax playoff bracket automation.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.

The bracket follows Fantrax's six-team H2H format:
  Round 1: 3 vs 6 and 4 vs 5; 1 and 2 receive byes.
  Round 2: 1 vs lowest-numbered remaining seed; 2 vs highest-numbered.
  Round 3: championship.

The private Fantrax PLAYOFFS view is deliberately not used because it
requires an authenticated session. Public getLeagueInfo, getStandings, and
getMatchupScores are sufficient for this bracket once final regular-season
seeds have been established.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

GENERAL_BASE = "https://www.fantrax.com/fxea/general"
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "playoff_config.yaml"
STATE_PATH = ROOT / "state" / "playoff.json"
AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def compact(value: Any, max_chars: int = 1200) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= max_chars else text[:max_chars] + "...<truncated>"


def get_json(
    session: requests.Session,
    endpoint: str,
    league_id: str,
    **params: Any,
) -> Any:
    response = session.get(
        f"{GENERAL_BASE}/{endpoint}",
        params={"leagueId": league_id, **params},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def scoring_periods(info: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = info.get("scoringPeriods")
    periods: dict[int, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return periods

    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item["number"])
        except (KeyError, TypeError, ValueError):
            continue
        periods[number] = item
    return periods


def current_period(
    info: dict[str, Any],
    now: datetime,
) -> int | None:
    periods = scoring_periods(info)
    if not periods:
        return None

    for number, item in sorted(periods.items()):
        start = parse_iso(item.get("startDate"))
        end = parse_iso(item.get("endDate"))
        if start and end and start <= now <= end:
            return number

    starts = [
        parse_iso(item.get("startDate"))
        for item in periods.values()
        if parse_iso(item.get("startDate"))
    ]
    if starts and now < min(starts):
        return min(periods)

    return max(periods)


def period_complete(
    info: dict[str, Any],
    number: int,
    now: datetime,
) -> bool:
    item = scoring_periods(info).get(number)
    if not item:
        return False
    end = parse_iso(item.get("endDate"))
    return bool(end and now > end)


def playoff_periods(info: dict[str, Any]) -> list[int]:
    playoffs = info.get("playoffs")
    if not isinstance(playoffs, dict):
        raise ValueError("getLeagueInfo did not expose playoff configuration")

    first = playoffs.get("firstPlayoffPeriod")
    last_regular = playoffs.get("lastRegularSeasonPeriod")
    if not isinstance(first, int) or not isinstance(last_regular, int):
        raise ValueError("invalid Fantrax playoff configuration")

    periods = scoring_periods(info)
    last_period = max(periods) if periods else first + 2
    return list(range(first, last_period + 1))


def normalize_standings(
    raw: Any,
    cutoff: int,
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("getStandings did not return a list")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            continue

        try:
            rank = int(row.get("rank") or index)
        except (TypeError, ValueError):
            rank = index

        try:
            points_for = float(row.get("totalPointsFor") or 0.0)
        except (TypeError, ValueError):
            points_for = 0.0

        rows.append(
            {
                "rank": rank,
                "teamId": str(row.get("teamId") or ""),
                "teamName": str(row.get("teamName") or "Unknown Team"),
                "record": str(row.get("points") or "0-0-0"),
                "pointsFor": points_for,
            }
        )

    rows.sort(key=lambda row: (row["rank"], row["teamName"].lower()))
    return rows[:cutoff]


def normalize_scores(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("getMatchupScores did not return a dict")

    if isinstance(raw.get("pageError"), dict):
        raise RuntimeError(
            f"getMatchupScores pageError: {compact(raw['pageError'])}"
        )

    matchups = raw.get("matchups")
    if not isinstance(matchups, list):
        return []

    normalized: list[dict[str, Any]] = []

    def team(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}

        try:
            score = float(value.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        try:
            games_played = int(value.get("gamesPlayed") or 0)
        except (TypeError, ValueError):
            games_played = 0

        return {
            "teamId": str(value.get("teamId") or ""),
            "teamName": str(value.get("teamName") or "Unknown Team"),
            "score": score,
            "gamesPlayed": games_played,
        }

    for matchup in matchups:
        if not isinstance(matchup, dict):
            continue
        normalized.append(
            {
                "away": team(matchup.get("away")),
                "home": team(matchup.get("home")),
            }
        )

    return normalized


def seed_of(team: dict[str, Any] | None, seeds: dict[int, dict[str, Any]]) -> int | None:
    if not team:
        return None

    team_id = str(team.get("teamId") or "")
    for seed, seeded_team in seeds.items():
        if str(seeded_team.get("teamId") or "") == team_id:
            return seed
    return None


def completed_result(
    matchup: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    away = matchup["away"]
    home = matchup["home"]

    if away["score"] > home["score"]:
        return away, away, home
    if home["score"] > away["score"]:
        return home, away, home

    # Fantrax's six-team H2H playoff rules use the higher seed as the
    # matchup tiebreaker.
    away_seed = seed_of(away, seeds)
    home_seed = seed_of(home, seeds)
    if away_seed is not None and home_seed is not None:
        return (away if away_seed < home_seed else home), away, home

    return None, away, home


def period_results(
    scores: list[dict[str, Any]],
    seeds: dict[int, dict[str, Any]],
    complete: bool,
) -> list[dict[str, Any]]:
    if not complete:
        return []

    results: list[dict[str, Any]] = []
    for matchup in scores:
        winner, away, home = completed_result(matchup, seeds)
        loser = None
        if winner is not None:
            loser = home if winner["teamId"] == away["teamId"] else away

        results.append(
            {
                "matchup": matchup,
                "winner": winner,
                "loser": loser,
            }
        )
    return results


def winners_from(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        result["winner"]
        for result in results
        if isinstance(result.get("winner"), dict)
    ]


def expected_round1(
    seeds: dict[int, dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    return [
        (seeds.get(3), seeds.get(6)),
        (seeds.get(4), seeds.get(5)),
    ]


def expected_semis(
    seeds: dict[int, dict[str, Any]],
    round1_winners: list[dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    winners = list(round1_winners)
    winners.sort(
        key=lambda team: seed_of(team, seeds)
        if seed_of(team, seeds) is not None
        else 99
    )

    if len(winners) < 2:
        return [(seeds.get(1), None), (seeds.get(2), None)]

    return [
        (seeds.get(1), winners[0]),
        (seeds.get(2), winners[-1]),
    ]


def expected_final(
    round2_winners: list[dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    if len(round2_winners) >= 2:
        return [(round2_winners[0], round2_winners[1])]
    return [(None, None)]


def label_team(
    team: dict[str, Any] | None,
    seeds: dict[int, dict[str, Any]],
) -> str:
    if not team:
        return "TBD"

    seed = seed_of(team, seeds)
    if seed is not None:
        return f"Seed {seed} — {team['teamName']}"
    return str(team.get("teamName") or "Unknown Team")


def matchup_text(
    pair: tuple[dict[str, Any] | None, dict[str, Any] | None],
    seeds: dict[int, dict[str, Any]],
    score: dict[str, Any] | None = None,
    winner: dict[str, Any] | None = None,
) -> str:
    if score:
        away = score["away"]
        home = score["home"]
        lines = [
            f"**{label_team(away, seeds)}** — {away['score']:.2f}",
            f"**{label_team(home, seeds)}** — {home['score']:.2f}",
        ]
        if winner:
            lines.append(f"Winner: **{label_team(winner, seeds)}**")
        return "\n".join(lines)

    return (
        f"**{label_team(pair[0], seeds)}**\n"
        "vs\n"
        f"**{label_team(pair[1], seeds)}**"
    )


def build_payload(
    info: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
    rounds: dict[int, dict[str, Any]],
    season_label: str,
    status: str,
    test: bool = False,
) -> dict[str, Any]:
    title = "[TEST] BLHA Playoffs" if test else "BLHA Playoffs"
    league = str(info.get("leagueName") or "Beer League Hockey Association")

    fields: list[dict[str, Any]] = []

    r1 = rounds.get(1, {})
    r1_matchups = r1.get("matchups", [])
    r1_value = "**Seeds 1 and 2 — BYE**"
    if r1_matchups:
        r1_value += "\n\n" + "\n\n".join(
            matchup_text(
                item["pair"],
                seeds,
                item.get("score"),
                item.get("winner"),
            )
            for item in r1_matchups
        )
    fields.append({"name": "ROUND 1", "value": r1_value, "inline": False})

    r2 = rounds.get(2, {})
    r2_matchups = r2.get("matchups", [])
    fields.append(
        {
            "name": "ROUND 2 — SEMIFINALS",
            "value": (
                "\n\n".join(
                    matchup_text(
                        item["pair"],
                        seeds,
                        item.get("score"),
                        item.get("winner"),
                    )
                    for item in r2_matchups
                )
                or "TBD"
            ),
            "inline": False,
        }
    )

    r3 = rounds.get(3, {})
    r3_matchups = r3.get("matchups", [])
    fields.append(
        {
            "name": "ROUND 3 — CHAMPIONSHIP",
            "value": (
                "\n\n".join(
                    matchup_text(
                        item["pair"],
                        seeds,
                        item.get("score"),
                        item.get("winner"),
                    )
                    for item in r3_matchups
                )
                or "TBD"
            ),
            "inline": False,
        }
    )

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": (
                    f"**{league}** • {season_label}\n\n"
                    "*Fantrax read-only playoff bracket.*"
                ),
                "fields": fields,
                "footer": {"text": f"{status} • FANTRAX READ-ONLY DATA"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def deliver(secret_name: str, body: dict[str, Any]) -> tuple[bool, str]:
    url = os.getenv(secret_name, "").strip()
    if not url:
        return False, f"missing secret {secret_name}"

    try:
        response = requests.post(
            url,
            params={"wait": "true"},
            json=body,
            timeout=25,
        )
    except Exception as exc:
        return False, f"Discord request failed: {exc}"

    if response.status_code not in (200, 204):
        return (
            False,
            f"Discord returned {response.status_code}: "
            f"{response.text[:250]}",
        )

    return True, "delivered"


def standings_seed_map(
    standings: list[dict[str, Any]],
    cutoff: int,
) -> dict[int, dict[str, Any]]:
    return {
        row["rank"]: {
            "teamId": row["teamId"],
            "teamName": row["teamName"],
            "record": row["record"],
            "pointsFor": row["pointsFor"],
        }
        for row in standings[:cutoff]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("preview", "test", "baseline", "live"),
        default="preview",
    )
    parser.add_argument(
        "--period",
        type=int,
        help="Override current period for bracket-format testing only.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    league_id = str(cfg.get("league_id") or "").strip()
    if not league_id:
        print("ERROR: league_id missing from playoff_config.yaml")
        return 1

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "BLHA-Fantrax-Playoffs/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    try:
        info = get_json(session, "getLeagueInfo", league_id)
        playoffs = info.get("playoffs") or {}
        cutoff = int(playoffs.get("numPlayoffTeams") or 6)
        standings = normalize_standings(
            get_json(session, "getStandings", league_id),
            cutoff,
        )
        pperiods = playoff_periods(info)
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    now = datetime.now(timezone.utc)
    first = int(playoffs.get("firstPlayoffPeriod") or 0)
    last_regular = int(playoffs.get("lastRegularSeasonPeriod") or 0)
    detected_period = current_period(info, now)
    effective_period = args.period if args.period is not None else detected_period

    if effective_period is None:
        print("ERROR: unable to determine scoring period")
        return 1

    if args.period is not None and args.period not in pperiods:
        print(f"ERROR: --period must be one of playoff periods {pperiods}")
        return 1

    state = load_state()
    saved_seeds = state.get("seeds")
    baseline_ready = (
        isinstance(saved_seeds, dict)
        and len(saved_seeds) >= cutoff
        and bool(state.get("baseline_recorded_at"))
    )

    if baseline_ready:
        seeds = {
            int(seed): team
            for seed, team in saved_seeds.items()
            if str(seed).isdigit() and isinstance(team, dict)
        }
        seed_source = "saved playoff seed baseline"
    else:
        seeds = standings_seed_map(standings, cutoff)
        seed_source = "current Fantrax standings (no saved playoff seed baseline)"

    scores_by_period: dict[int, list[dict[str, Any]]] = {}
    complete_by_period: dict[int, bool] = {}
    for number in pperiods:
        try:
            scores_by_period[number] = normalize_scores(
                get_json(session, "getMatchupScores", league_id, period=number)
            )
        except Exception as exc:
            print(f"ERROR: Fantrax playoff score read failed for period {number}: {exc}")
            return 1
        complete_by_period[number] = period_complete(info, number, now)

    # A manual period override is a bracket-format test aid. It must not trick
    # the system into marking future rounds complete.
    if args.period is not None:
        for number in pperiods:
            complete_by_period[number] = False

    r1_results = period_results(
        scores_by_period.get(pperiods[0], []),
        seeds,
        complete_by_period.get(pperiods[0], False),
    )
    r1_winners = winners_from(r1_results)
    r2_results = period_results(
        scores_by_period.get(pperiods[1], []) if len(pperiods) > 1 else [],
        seeds,
        complete_by_period.get(pperiods[1], False) if len(pperiods) > 1 else False,
    )
    r2_winners = winners_from(r2_results)

    rounds: dict[int, dict[str, Any]] = {
        1: {
            "period": pperiods[0],
            "matchups": [],
        },
        2: {
            "period": pperiods[1] if len(pperiods) > 1 else None,
            "matchups": [],
        },
        3: {
            "period": pperiods[2] if len(pperiods) > 2 else None,
            "matchups": [],
        },
    }

    r1_pairs = expected_round1(seeds)
    r1_scores = scores_by_period.get(pperiods[0], [])
    for index, pair in enumerate(r1_pairs):
        score = r1_scores[index] if index < len(r1_scores) else None
        winner = r1_results[index]["winner"] if index < len(r1_results) else None
        rounds[1]["matchups"].append(
            {"pair": pair, "score": score, "winner": winner}
        )

    r2_pairs = expected_semis(seeds, r1_winners)
    r2_scores = scores_by_period.get(pperiods[1], []) if len(pperiods) > 1 else []
    for index, pair in enumerate(r2_pairs):
        score = r2_scores[index] if index < len(r2_scores) else None
        winner = r2_results[index]["winner"] if index < len(r2_results) else None
        rounds[2]["matchups"].append(
            {"pair": pair, "score": score, "winner": winner}
        )

    r3_pairs = expected_final(r2_winners)
    r3_scores = scores_by_period.get(pperiods[2], []) if len(pperiods) > 2 else []
    r3_results = period_results(
        r3_scores,
        seeds,
        complete_by_period.get(pperiods[2], False) if len(pperiods) > 2 else False,
    )
    for index, pair in enumerate(r3_pairs):
        score = r3_scores[index] if index < len(r3_scores) else None
        winner = r3_results[index]["winner"] if index < len(r3_results) else None
        rounds[3]["matchups"].append(
            {"pair": pair, "score": score, "winner": winner}
        )

    canonical = {
        "effective_period": effective_period,
        "seeds": seeds,
        "rounds": rounds,
    }
    current_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    previous_hash = str(state.get("fingerprint") or "")

    print(
        f"BLHA FANTRAX PLAYOFFS mode={args.mode.upper()} "
        f"detected_period={detected_period} effective_period={effective_period} "
        f"playoff_periods={pperiods}"
    )
    print(f"seed_source={seed_source}")
    print("SEEDS")
    for seed in sorted(seeds):
        team = seeds[seed]
        print(
            f"  {seed}. {team.get('teamName')} [{team.get('teamId')}] "
            f"{team.get('record')}"
        )
    for number in pperiods:
        print(
            f"period={number} matchups={len(scores_by_period.get(number, []))} "
            f"complete={complete_by_period.get(number, False)}"
        )

    season_label = str(cfg.get("season_label") or "")
    status = f"PLAYOFF PERIOD {effective_period}"
    body = build_payload(
        info,
        seeds,
        rounds,
        season_label,
        status,
        test=args.mode == "test",
    )

    if args.mode == "preview":
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"RESULT: preview only; fingerprint={current_hash[:12]}")
        return 0

    if args.mode == "baseline":
        if detected_period is None or detected_period <= last_regular:
            print(
                "ERROR: baseline can only be recorded after the regular season "
                f"(last regular period={last_regular}, detected={detected_period})"
            )
            return 1

        if baseline_ready:
            print("RESULT: playoff seed baseline already exists; no change.")
            return 0

        state.update(
            {
                "seeds": {str(seed): team for seed, team in seeds.items()},
                "baseline_recorded_at": now.isoformat(),
                "baseline_period": detected_period,
            }
        )
        save_state(state)
        print("RESULT: final regular-season playoff seed baseline recorded.")
        return 0

    if args.mode == "live":
        if detected_period is None or detected_period < first:
            print(
                "RESULT: outside playoff window; no Discord message sent and "
                "no playoff state changed."
            )
            return 0

        if not baseline_ready:
            print(
                "RESULT: playoff window reached but no seed baseline exists; "
                "run baseline after the regular season before enabling live posts."
            )
            return 0

        if previous_hash == current_hash and not args.force:
            print("RESULT: playoff bracket unchanged; 0 Discord messages sent.")
            return 0

    secret = str(cfg.get("webhook_secret") or "BLHA_WEBHOOK_PLAYOFFS")
    ok, detail = deliver(secret, body)
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    state_updated = False
    if args.mode == "live":
        state.update(
            {
                "fingerprint": current_hash,
                "last_posted_at": now.isoformat(),
                "last_posted_period": effective_period,
            }
        )
        save_state(state)
        state_updated = True

    print(
        f"RESULT: Discord playoff message {detail}; "
        f"state_updated={state_updated}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
