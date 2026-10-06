#!/usr/bin/env python3
"""BLHA playoffs: live bracket for Fantrax's six-team H2H playoff format.

  Round 1: 3 vs 6 and 4 vs 5; Seeds 1 and 2 receive byes.
  Round 2: reseed. Seed 1 plays the lowest-ranked survivor, Seed 2 the highest.
  Round 3: championship (two weeks, cumulative).

Also shows the third-place race between the Semifinal losers (16.3, with
the 16.4 points fallback) and the six-team consolation bracket (16.7).

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


def third_place_text(third: dict[str, Any], seeds: dict[int, dict[str, Any]]) -> str:
    status = third.get("status")
    pair = third.get("pair") or (None, None)
    if status == "waiting":
        return "The two Semifinal losers play for third place during the Championship."
    if status == "matchup":
        return matchup_text(pair, seeds, third.get("score"), third.get("winner"))
    if status == "fallback":
        a, b = third["totals"]
        lines = [
            f"**{label_team(pair[0], seeds)}** — {a:.2f}",
            f"**{label_team(pair[1], seeds)}** — {b:.2f}",
            "*No third-place matchup in Fantrax: the higher Championship-period total takes third.*",
        ]
        if third.get("winner"):
            lines.append(f"Third place: **{label_team(third['winner'], seeds)}**")
        return "\n".join(lines)
    text = matchup_text(pair, seeds)
    if status == "no_matchup":
        text += "\n*Waiting for the third-place matchup in Fantrax.*"
    return text


def round_value(items: list[dict[str, Any]], seeds: dict[int, dict[str, Any]]) -> str:
    return "\n\n".join(
        matchup_text(item["pair"], seeds, item.get("score"), item.get("winner"))
        for item in items
    ) or "TBD"


def consolation_fields(extras: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = extras.get("consolation")
    seeds = extras.get("consolation_seeds") or {}
    if not rounds:
        return []
    r1 = "**Seeds 1 and 2 — BYE**\n\n" + round_value(rounds[1]["matchups"], seeds)
    final = round_value(rounds[3]["matchups"], seeds)
    champ = rounds[3]["matchups"][0].get("winner")
    if champ:
        final += f"\n\n**{champ['teamName']}** wins the consolation bracket and a $50 FAAB bonus next Season."
    return [
        {"name": "CONSOLATION — ROUND 1", "value": r1, "inline": False},
        {"name": "CONSOLATION — SEMIFINALS", "value": round_value(rounds[2]["matchups"], seeds), "inline": False},
        {"name": "CONSOLATION — FINAL", "value": final, "inline": False},
    ]


def build_payload(
    info: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
    rounds: dict[int, dict[str, Any]],
    cfg: dict[str, Any],
    status: str,
    test: bool = False,
    extras: dict[str, Any] | None = None,
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

    extras = extras or {}
    if extras.get("third"):
        fields.append({
            "name": "THIRD PLACE",
            "value": third_place_text(extras["third"], seeds),
            "inline": False,
        })
    fields.extend(consolation_fields(extras))

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


def consolation_seed_map(
    standings: list[dict[str, Any]],
    cutoff: int,
) -> dict[int, dict[str, Any]] | None:
    """Non-playoff teams seeded 1 to 6 by regular-season rank (16.7)."""
    rest = standings[cutoff:cutoff + 6]
    if len(rest) < 6:
        return None
    return {
        i: {
            "teamId": row["teamId"],
            "teamName": row["teamName"],
            "record": row["record"],
            "pointsFor": row["pointsFor"],
        }
        for i, row in enumerate(rest, start=1)
    }


def seeds_ready(info: dict[str, Any], standings: list[dict[str, Any]]) -> bool:
    """True once Fantrax standings include every regular-season week."""
    last_regular, _, _ = season.playoff_settings(info)
    counted = games_counted(standings)
    return counted is not None and counted >= last_regular


def in_bracket(team: dict[str, Any] | None, seeds: dict[int, dict[str, Any]]) -> bool:
    return seed_of(team, seeds) is not None


def bracket_winners(
    results: list[dict[str, Any]],
    seeds: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Winners of this bracket's matchups only.

    A playoff week also holds consolation and third-place matchups, so
    results are filtered to games where both teams belong to ``seeds``.
    """
    return [
        r["winner"]
        for r in results
        if isinstance(r.get("winner"), dict)
        and in_bracket(r["matchup"]["away"], seeds)
        and in_bracket(r["matchup"]["home"], seeds)
    ]


def bracket_losers(
    results: list[dict[str, Any]],
    seeds: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        r["loser"]
        for r in results
        if isinstance(r.get("loser"), dict)
        and in_bracket(r["matchup"]["away"], seeds)
        and in_bracket(r["matchup"]["home"], seeds)
    ]


def find_score(
    scores: list[dict[str, Any]],
    pair: tuple[dict[str, Any] | None, dict[str, Any] | None],
) -> dict[str, Any] | None:
    ids = {str(t["teamId"]) for t in pair if t}
    if len(ids) != 2:
        return None
    return next(
        (m for m in scores if {m["away"]["teamId"], m["home"]["teamId"]} == ids),
        None,
    )


def bracket_rounds(
    seeds: dict[int, dict[str, Any]],
    scores_by: dict[int, list[dict[str, Any]]],
    final_by: dict[int, bool],
    first: int,
) -> dict[int, dict[str, Any]]:
    """Three rounds of a six-team bracket (byes for 1 and 2, reseeding).

    Used for the playoffs and, with its own seeds, the consolation bracket
    (16.7). Weeks missing from ``scores_by`` have not started.
    """
    def results(number: int) -> list[dict[str, Any]]:
        return period_results(scores_by.get(number, []), seeds, final_by.get(number, False))

    def items(pairs: list[tuple], number: int) -> list[dict[str, Any]]:
        scores = scores_by.get(number, [])
        done = results(number)
        out = []
        for pair in pairs:
            score = find_score(scores, pair)
            winner = None
            if score:
                for r in done:
                    if r["matchup"] is score:
                        winner = r["winner"]
            out.append({"pair": pair, "score": score, "winner": winner})
        return out

    r1 = items(expected_round1(seeds), first)
    r2 = items(expected_semis(seeds, bracket_winners(results(first), seeds)), first + 1)
    r3 = items(expected_final(bracket_winners(results(first + 1), seeds)), first + 2)
    return {1: {"matchups": r1}, 2: {"matchups": r2}, 3: {"matchups": r3}}


def third_place(
    seeds: dict[int, dict[str, Any]],
    scores_by: dict[int, list[dict[str, Any]]],
    final_by: dict[int, bool],
    first: int,
) -> dict[str, Any]:
    """The third-place race between the two Semifinal losers (16.3, 16.4).

    Preferred: the third-place matchup the Commissioner enters in Fantrax.
    Fallback (16.4): the loser with more points over the championship period.
    An exact tie goes to the higher playoff seed (16.5).
    """
    semis = period_results(scores_by.get(first + 1, []), seeds, final_by.get(first + 1, False))
    losers = bracket_losers(semis, seeds)
    if len(losers) < 2:
        return {"status": "waiting", "pair": (None, None)}
    losers.sort(key=lambda t: seed_of(t, seeds) or 99)
    pair = (losers[0], losers[1])
    if first + 2 not in scores_by:
        return {"status": "set", "pair": pair}
    scores = scores_by[first + 2]
    final = final_by.get(first + 2, False)
    score = find_score(scores, pair)
    if score:
        winner = completed_result(score, seeds)[0] if final else None
        return {"status": "matchup", "pair": pair, "score": score, "winner": winner}

    totals: dict[str, float] = {}
    for m in scores:
        for side in ("away", "home"):
            if m[side]["teamId"] in {pair[0]["teamId"], pair[1]["teamId"]}:
                totals[m[side]["teamId"]] = m[side]["score"]
    if len(totals) < 2:
        return {"status": "no_matchup", "pair": pair}
    a, b = (totals[pair[0]["teamId"]], totals[pair[1]["teamId"]])
    winner = None
    if final:
        winner = pair[0] if a >= b else pair[1]  # pair[0] is the higher seed
    return {"status": "fallback", "pair": pair, "totals": (a, b), "winner": winner}


def build_rounds(
    fx: Fantrax,
    info: dict[str, Any],
    seeds: dict[int, dict[str, Any]],
    current: int | None,
    now: datetime,
    tz: ZoneInfo,
    *,
    simulate: bool = False,
    consolation: dict[int, dict[str, Any]] | None = None,
) -> tuple[dict[int, dict[str, Any]], str, dict[str, Any]]:
    """Assemble the playoff rounds, third place and consolation from Fantrax."""
    _, first, _ = season.playoff_settings(info)
    weeks = {p.number: p for p in season.periods(info)}

    scores_by: dict[int, list[dict[str, Any]]] = {}
    final_by: dict[int, bool] = {}
    started = current is not None and current >= first
    if started:
        for number in (first, first + 1, first + 2):
            if number > current or number not in weeks:
                break
            scores_by[number] = fx.matchup_scores(number)
            final_by[number] = False if simulate else season.is_final(weeks[number], now, tz)
            print(f"week={number} matchups={len(scores_by[number])} final={final_by[number]}")

    rounds = bracket_rounds(seeds, scores_by, final_by, first)
    extras: dict[str, Any] = {"third": third_place(seeds, scores_by, final_by, first)}
    if consolation and len(consolation) >= 6:
        extras["consolation"] = bracket_rounds(consolation, scores_by, final_by, first)
        extras["consolation_seeds"] = consolation

    if not started:
        return rounds, "PLAYOFFS NOT STARTED", extras
    names = {first: "QUARTERFINALS", first + 1: "SEMIFINALS", first + 2: "CHAMPIONSHIP"}
    champion = rounds[3]["matchups"][0].get("winner")
    status = "CHAMPION CROWNED" if champion else names.get(current, f"PLAYOFF WEEK {current}")
    return rounds, status, extras


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
    stored_cons = state.get("consolation_seeds") if isinstance(state.get("consolation_seeds"), dict) else None
    if stored and len(stored) >= cutoff:
        seeds = {int(k): v for k, v in stored.items() if str(k).isdigit()}
        consolation = ({int(k): v for k, v in stored_cons.items() if str(k).isdigit()}
                       if stored_cons else None)
        seed_source = "saved final regular-season seeds"
    else:
        stored = None
        seeds = standings_seed_map(standings, cutoff)
        consolation = consolation_seed_map(standings, cutoff)
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
        if consolation:
            state["consolation_seeds"] = {str(k): v for k, v in sorted(consolation.items())}
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

    rounds, status, extras = build_rounds(fx, info, seeds, current, now, tz,
                                          simulate=args.week is not None, consolation=consolation)
    payload = build_payload(info, seeds, rounds, cfg, status, test=args.mode == "test", extras=extras)
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
