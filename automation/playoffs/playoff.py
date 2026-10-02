#!/usr/bin/env python3
"""BLHA playoffs: live bracket for Fantrax's six-team H2H playoff format.

  Round 1: 3 vs 6 and 4 vs 5; Seeds 1 and 2 receive byes.
  Round 2: reseed. Seed 1 plays the lowest-ranked survivor, Seed 2 the highest.
  Round 3: championship.

Runs only during the playoff weeks (see automation/scheduler/schedule.yaml).

- Seeds are saved automatically once Fantrax has counted the final regular
  season week, so later playoff results can never reshuffle them.
- Each round gets one bracket message (members are notified when a new round
  starts). Within a round the same message is edited as scores change.

Fantrax reads are anonymous and read-only. Discord delivery is webhook-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from blha import season  # noqa: E402
from blha.fantrax import Fantrax, games_counted  # noqa: E402
from blha.league import AVATAR, color_value, load_json, load_league, save_json, timezone_of  # noqa: E402
from discord_webhook import send_discord_webhook, upsert_discord_message  # noqa: E402

STATE_PATH = ROOT / "state" / "playoff.json"


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




def seeds_ready(info: dict[str, Any], standings: list[dict[str, Any]]) -> bool:
    """True once Fantrax standings include every regular-season week."""
    last_regular, _, _ = season.playoff_settings(info)
    counted = games_counted(standings)
    return counted is not None and counted >= last_regular


def build_rounds(
    fx: Fantrax,
    info: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
    current: int | None,
    now: datetime,
    tz: ZoneInfo,
    *,
    simulate: bool = False,
) -> tuple[dict[int, dict[str, Any]], str]:
    """Assemble the three bracket rounds from Fantrax playoff matchup scores."""
    _, first, _ = season.playoff_settings(info)
    weeks = {p.number: p for p in season.periods(info)}

    if current is None or current < first:
        r1 = expected_round1(seeds)
        rounds = {
            1: {"matchups": [{"pair": r1[0]}, {"pair": r1[1]}]},
            2: {"matchups": [{"pair": (seeds.get(1), None)}, {"pair": (seeds.get(2), None)}]},
            3: {"matchups": [{"pair": (None, None)}]},
        }
        return rounds, "PLAYOFFS NOT STARTED"

    scores_by: dict[int, list[dict[str, Any]]] = {}
    results_by: dict[int, list[dict[str, Any]]] = {}
    for number in (first, first + 1, first + 2):
        if number > current or number not in weeks:
            break
        scores = fx.matchup_scores(number)
        complete = False if simulate else season.is_final(weeks[number], now, tz)
        scores_by[number] = scores
        results_by[number] = period_results(scores, seeds, complete)
        print(f"week={number} matchups={len(scores)} final={complete}")

    def attach(pairs: list[tuple], number: int, by_seed: bool) -> list[dict[str, Any]]:
        scores = scores_by.get(number, [])
        items = []
        for pair in pairs:
            if by_seed:
                target = {seed_of(pair[0], seeds), seed_of(pair[1], seeds)}
                score = next((m for m in scores
                              if {seed_of(m["away"], seeds), seed_of(m["home"], seeds)} == target), None)
            else:
                target = {t["teamId"] for t in pair if t is not None}
                score = next((m for m in scores
                              if {m["away"]["teamId"], m["home"]["teamId"]} == target), None)
            items.append({"pair": pair, "score": score, "winner": None})
        for result in results_by.get(number, []):
            winner = result["winner"]
            if not winner:
                continue
            for item in items:
                s = item.get("score")
                if s and winner["teamId"] in (s["away"]["teamId"], s["home"]["teamId"]):
                    item["winner"] = winner
        return items

    r1_items = attach(expected_round1(seeds), first, True)
    r2_items = attach(expected_semis(seeds, winners_from(results_by.get(first, []))), first + 1, False)
    r3_pairs = expected_final(winners_from(results_by.get(first + 1, [])))
    r3_scores = scores_by.get(first + 2, [])
    r3_results = results_by.get(first + 2, [])
    r3_items = [{
        "pair": r3_pairs[0],
        "score": r3_scores[0] if len(r3_scores) == 1 else None,
        "winner": r3_results[0]["winner"] if r3_results else None,
    }]
    names = {first: "QUARTERFINALS", first + 1: "SEMIFINALS", first + 2: "CHAMPIONSHIP"}
    status = "CHAMPION CROWNED" if r3_items[0]["winner"] else names.get(current, f"PLAYOFF WEEK {current}")
    return {1: {"matchups": r1_items}, 2: {"matchups": r2_items}, 3: {"matchups": r3_items}}, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "baseline", "live"), default="preview")
    parser.add_argument("--week", "--period", dest="week", type=int,
                        help="Render as if this playoff week were current (preview/test only).")
    parser.add_argument("--force", action="store_true", help="Live: post a new bracket message even if unchanged.")
    args = parser.parse_args()

    league = load_league()
    tz = timezone_of(league)
    comp = league.get("competition") or {}
    cfg = {"season_label": league.get("season_label") or "", "color": league.get("color"), "channel_label": "PLAYOFFS"}
    secret = str((comp.get("webhooks") or {}).get("playoffs") or "BLHA_WEBHOOK_PLAYOFFS")
    fx = Fantrax(str(league["league_id"]), user_agent="BLHA-Playoffs/2.0")
    now = datetime.now(timezone.utc)

    try:
        info = fx.league_info()
        last_regular, first, cutoff = season.playoff_settings(info)
        standings = fx.standings()
    except Exception as exc:
        print(f"ERROR: Fantrax read failed: {exc}")
        return 1

    active = season.active_period(info, now)
    detected = active.number if active else None
    if detected is None and season.phase(info, now) == season.OFFSEASON and season.periods(info):
        detected = season.periods(info)[-1].number
    current = args.week if args.week is not None else detected

    state = load_json(STATE_PATH, {})
    stored = state.get("seeds") if isinstance(state.get("seeds"), dict) else None
    if stored and len(stored) >= cutoff:
        seeds = {int(k): v for k, v in stored.items() if str(k).isdigit()}
        seed_source = "saved final regular-season seeds"
    else:
        stored = None
        seeds = standings_seed_map(standings, cutoff)
        seed_source = "current Fantrax standings"

    print(f"BLHA PLAYOFFS mode={args.mode.upper()} season={season.describe(info, now)} "
          f"current_week={current} seeds_from={seed_source}")

    if args.mode in ("baseline", "live") and not stored:
        if not seeds_ready(info, standings):
            print(f"RESULT: waiting for Fantrax to count all {last_regular} regular-season weeks "
                  f"(counted {games_counted(standings)}); seeds not saved yet.")
            return 0
        if detected is not None and detected > first:
            print("ERROR: playoff seeds were never saved and the playoffs are past round 1; "
                  "refusing to infer seeds from playoff-era standings.")
            return 1
        state["seeds"] = {str(k): v for k, v in sorted(seeds.items())}
        state["recorded_at"] = now.isoformat()
        save_json(STATE_PATH, state)
        print("SEEDS SAVED from final regular-season standings:")
        for seed in sorted(seeds):
            print(f"  {seed}. {seeds[seed]['teamName']} ({seeds[seed].get('record', '')})")
        if args.mode == "baseline":
            return 0
    elif args.mode == "baseline":
        print("RESULT: seeds were already saved; nothing to do.")
        return 0

    rounds, status = build_rounds(fx, info, seeds, current, now, tz, simulate=args.week is not None)
    payload = build_payload(info, seeds, rounds, cfg, status, test=args.mode == "test")
    fp = semantic_fingerprint(payload)

    if args.mode == "preview":
        print(json.dumps(payload, indent=2))
        print(f"RESULT: preview only; fingerprint={fp[:12]}")
        return 0

    if args.mode == "test":
        ok, detail, _ = send_discord_webhook(secret, payload)
        print(f"{'POSTED' if ok else 'ERROR'} test bracket: {detail}")
        return 0 if ok else 1

    if current is None or current < first:
        print("RESULT: playoffs have not started; nothing posted.")
        return 0
    new_round = state.get("message_week") != current
    if not new_round and state.get("fingerprint") == fp and not args.force:
        print("RESULT: bracket unchanged.")
        return 0
    message_id = None if (new_round or args.force) else state.get("message_id")
    ok, detail, new_id, how = upsert_discord_message(secret, payload, message_id)
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1
    state.update({"fingerprint": fp, "message_id": new_id, "message_week": current, "updated_at": now.isoformat()})
    save_json(STATE_PATH, state)
    print(f"RESULT: bracket {how} for week {current} ({status}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
