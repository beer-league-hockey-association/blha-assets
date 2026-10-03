"""Capture raw Fantrax endpoint responses and a shape summary (read-only).

Usage: python tools/fantrax_probe.py [--out DIR] [--period N]
Run from the manual workflow because the response shapes are unverified.
No credentials are used or stored.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation"))

from blha.fantrax import Fantrax  # noqa: E402


def shape(value, depth=0):
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in list(value.items())[:25]}
    if isinstance(value, list):
        return [f"list[{len(value)}]", shape(value[0], depth + 1)] if value else ["list[0]"]
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fantrax-probe")
    ap.add_argument("--period", type=int, default=1)
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "automation" / "league.yaml").read_text())
    fx = Fantrax(str(cfg["league_id"]))
    calls = {
        "getLeagueInfo": fx.league_info,
        "getStandings": lambda: fx.get("getStandings"),
        "getTeamRosters": fx.rosters,
        "getTeamRosters_period": lambda: fx.rosters(args.period),
        "getDraftPicks": fx.draft_picks,
        "getDraftResults": fx.draft_results,
        "getAdp": fx.adp,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, call in calls.items():
        try:
            data = call()
            (out / f"{name}.json").write_text(json.dumps(data, indent=2))
            summary[name] = {"ok": True, "shape": shape(data)}
        except Exception as exc:  # report every endpoint, never stop early
            summary[name] = {"ok": False, "error": str(exc)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
