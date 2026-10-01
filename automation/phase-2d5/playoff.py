#!/usr/bin/env python3
"""BLHA Phase 2D.5 — Fantrax playoff bracket automation.

Fantrax reads are anonymous/read-only. Discord delivery is webhook-only.

The bracket follows Fantrax's six-team H2H format:
  Round 1: 3 vs 6 and 4 vs 5; 1 and 2 receive byes.
  Round 2: 1 vs lowest-ranked remaining seed; 2 vs highest-ranked.
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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

GENERAL_BASE = "https://www.fantrax.com/fxea/general"
ROOT = Path(__file__).resolve().parent
AUTOMATION_ROOT = ROOT.parent
if str(AUTOMATION_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_ROOT))

from discord_webhook import post_discord_webhook

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
    """Reseed so Seed 1 receives the lowest-ranked surviving opponent."""
    winners = list(round1_winners)
    winners.sort(
        key=lambda team: seed_of(team, seeds)
        if seed_of(team, seeds) is not None
        else 99
    )

    if len(winners) < 2:
        return [(seeds.get(1), None), (seeds.get(2), None)]

    # Numerically larger seed = lower-ranked team. With winners 3 and 6,
    # standard reseeding is therefore 1-v-6 and 2-v-3.
    return [
        (seeds.get(1), winners[-1]),
        (seeds.get(2), winners[0]),
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


def color_value(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def build_payload(
    info: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
    rounds: dict[int, dict[str, Any]],
    cfg: dict[str, Any],
    status: str,
    test: bool = False,
) -> dict[str, Any]:
    title = "[TEST] BLHA Playoffs" if test else "BLHA Playoffs"
    league = str(info.get("leagueName") or "Beer League Hockey Association")
    season_label = str(cfg.get("season_label") or "")

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

    description = f"**{league}**"
    if season_label:
        description += f" • {season_label}"
    description += "\n\n*Fantrax read-only playoff bracket.*"

    return {
        "username": "BLHA Competition Desk",
        "avatar_url": AVATAR,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "fields": fields,
                "color": color_value(cfg.get("color", "0xFFB81C")),
                "footer": {
                    "text": (
                        f"{cfg.get('channel_label', 'PLAYOFFS')} • {status} • "
                        "FANTRAX READ-ONLY DATA"
                    )
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def semantic_fingerprint(payload: dict[str, Any]) -> str:
    """Fingerprint bracket meaning while ignoring render-time metadata."""
    embeds = payload.get("embeds") or []
    embed = dict(embeds[0]) if embeds and isinstance(embeds[0], dict) else {}
    embed.pop("timestamp", None)
    text = json.dumps(
        embed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deliver(secret_name: str, body: dict[str, Any]) -> tuple[bool, str]:
    return post_discord_webhook(secret_name, body)


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
    current = args.period if args.period is not None else detected_period

    state = load_state()
    stored_seeds = state.get("seeds")
    if isinstance(stored_seeds, dict) and len(stored_seeds) >= cutoff:
        seeds = {
            int(key): value
            for key, value in stored_seeds.items()
            if str(key).isdigit()
        }
        seed_source = "saved final regular-season seeds"
    else:
        seeds = standings_seed_map(standings, cutoff)
        seed_source = "current Fantrax standings (no saved playoff seed baseline)"

    print(
        "BLHA FANTRAX PLAYOFFS "
        f"mode={args.mode.upper()} "
        f"detected_period={detected_period} "
        f"effective_period={current} "
        f"playoff_periods={pperiods}"
    )
    print(f"seed_source={seed_source}")
    print("SEEDS")
    for seed in sorted(seeds):
        team = seeds[seed]
        print(
            f"{seed}. {team['teamName']} "
            f"[{team.get('teamId', '')}] "
            f"{team.get('record', '')}"
        )

    if current is None or current < first:
        status = "PLAYOFFS NOT STARTED"
        r1_pairs = expected_round1(seeds)
        rounds = {
            1: {
                "matchups": [
                    {"pair": r1_pairs[0]},
                    {"pair": r1_pairs[1]},
                ]
            },
            2: {
                "matchups": [
                    {"pair": (seeds.get(1), None)},
                    {"pair": (seeds.get(2), None)},
                ]
            },
            3: {"matchups": [{"pair": (None, None)}]},
        }
    else:
        if (
            not isinstance(stored_seeds, dict)
            and current > first
            and args.mode == "live"
        ):
            print(
                "ERROR: final playoff seed baseline is missing and the "
                "regular season has already moved past the first playoff "
                "period; refusing to infer seeds from playoff-adjusted standings."
            )
            return 1

        status = f"PLAYOFF PERIOD {current}"
        scores_by_period: dict[int, list[dict[str, Any]]] = {}
        results_by_period: dict[int, list[dict[str, Any]]] = {}

        for number in pperiods:
            if args.period is None and number > current:
                break

            try:
                scores = normalize_scores(
                    get_json(
                        session,
                        "getMatchupScores",
                        league_id,
                        period=number,
                    )
                )
                complete = (
                    period_complete(info, number, now)
                    if args.period is None
                    else False
                )
                scores_by_period[number] = scores
                results_by_period[number] = period_results(
                    scores,
                    seeds,
                    complete,
                )
                print(
                    f"period={number} "
                    f"matchups={len(scores)} "
                    f"complete={complete}"
                )
            except Exception as exc:
                print(f"WARNING: period {number} scores failed: {exc}")

        r1_scores = scores_by_period.get(first, [])
        r1_results = results_by_period.get(first, [])
        r1_matchups: list[dict[str, Any]] = []

        for pair in expected_round1(seeds):
            target = {seed_of(pair[0], seeds), seed_of(pair[1], seeds)}
            score = next(
                (
                    matchup
                    for matchup in r1_scores
                    if {
                        seed_of(matchup["away"], seeds),
                        seed_of(matchup["home"], seeds),
                    }
                    == target
                ),
                None,
            )
            r1_matchups.append(
                {"pair": pair, "score": score, "winner": None}
            )

        for result in r1_results:
            winner = result["winner"]
            if not winner:
                continue
            for item in r1_matchups:
                score = item.get("score")
                if score and winner["teamId"] in (
                    score["away"]["teamId"],
                    score["home"]["teamId"],
                ):
                    item["winner"] = winner

        r1_winners = winners_from(r1_results)
        r2_pairs = expected_semis(seeds, r1_winners)

        r2_scores = scores_by_period.get(first + 1, [])
        r2_results = results_by_period.get(first + 1, [])
        r2_matchups: list[dict[str, Any]] = []

        for pair in r2_pairs:
            target = {
                team["teamId"]
                for team in pair
                if team is not None
            }
            score = next(
                (
                    matchup
                    for matchup in r2_scores
                    if {
                        matchup["away"]["teamId"],
                        matchup["home"]["teamId"],
                    }
                    == target
                ),
                None,
            )
            r2_matchups.append(
                {"pair": pair, "score": score, "winner": None}
            )

        for result in r2_results:
            winner = result["winner"]
            if not winner:
                continue
            for item in r2_matchups:
                score = item.get("score")
                if score and winner["teamId"] in (
                    score["away"]["teamId"],
                    score["home"]["teamId"],
                ):
                    item["winner"] = winner

        r2_winners = winners_from(r2_results)
        r3_pairs = expected_final(r2_winners)

        r3_scores = scores_by_period.get(first + 2, [])
        r3_results = results_by_period.get(first + 2, [])
        r3_matchups = [
            {
                "pair": r3_pairs[0],
                "score": (
                    r3_scores[0]
                    if len(r3_scores) == 1
                    else None
                ),
                "winner": (
                    r3_results[0]["winner"]
                    if r3_results
                    else None
                ),
            }
        ]

        rounds = {
            1: {"matchups": r1_matchups},
            2: {"matchups": r2_matchups},
            3: {"matchups": r3_matchups},
        }

    payload = build_payload(
        info,
        seeds,
        rounds,
        cfg,
        status,
        test=args.mode == "test",
    )

    fingerprint = semantic_fingerprint(payload)
    previous = str(state.get("fingerprint") or "")

    if args.mode == "preview":
        print(json.dumps(payload, indent=2))
        print(f"RESULT: preview only; fingerprint={fingerprint[:12]}")
        return 0

    if args.mode == "baseline":
        if detected_period is None or detected_period <= last_regular:
            print(
                "RESULT: baseline not recorded yet; "
                "wait until the regular season is complete."
            )
            return 0

        save_state(
            {
                "seeds": {
                    str(seed): team
                    for seed, team in sorted(seeds.items())
                },
                "fingerprint": fingerprint,
                "recorded_at": now.isoformat(),
            }
        )
        print("RESULT: playoff baseline recorded.")
        return 0

    if args.mode == "live" and previous == fingerprint and not args.force:
        print("RESULT: playoff snapshot unchanged; 0 Discord messages sent.")
        return 0

    secret = str(
        cfg.get("webhook_secret") or "BLHA_WEBHOOK_PLAYOFFS"
    )
    ok, detail = deliver(secret, payload)
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1

    if args.mode == "live":
        save_state(
            {
                "seeds": {
                    str(seed): team
                    for seed, team in sorted(seeds.items())
                },
                "fingerprint": fingerprint,
                "recorded_at": now.isoformat(),
            }
        )

    print(
        f"RESULT: Discord playoff message {detail}; "
        f"state_updated={args.mode == 'live'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
