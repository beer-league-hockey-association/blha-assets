#!/usr/bin/env python3
"""BLHA History Posts: post league-history graphics and reports to Discord (manual workflow).

Items:
  dynasty-pot      the Dynasty Pot graphic (balance and every franchise's titles this
                   cycle) in one 💰│league-ledger message, in the ledger's Dynasty Pot
                   update format (templates/league-office/45_ledger_dynasty_pot.json)
  franchise-cards  one card per franchise to 🏒│franchise-directory, one message each
  draft-retro      the retrospective of a saved draft to 📋│draft-results; reads NHL
                   stats, so it takes a few minutes for a 36-round draft

Modes:
  preview  build everything, write the images to --out and print the messages; posts nothing
  test     post one clearly labeled [TEST] message; saves nothing
  live     post everything; draft-retro also saves the report to archive/<season>/draft_retro.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(AUTOMATION.parent / "tools"))

import discohook_format as fmt  # noqa: E402
from blha.league import AVATAR, load_league  # noqa: E402
from discord_webhook import post_discord_webhook, post_discord_webhook_files  # noqa: E402
from history.context import LeagueHistory  # noqa: E402
from history.profiles import dynasty_summary, franchise_profiles  # noqa: E402
from history.records import money  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "out"
LEDGER_COLOR = 13012757      # the League Ledger's record gold (templates/league-office/4x_ledger_*.json)
GOLD = 16758812
DEFAULT_WEBHOOKS = {
    "dynasty_pot": "BLHA_WEBHOOK_LEAGUE_LEDGER",
    "franchise_directory": "BLHA_WEBHOOK_FRANCHISE_DIRECTORY",
}


def webhook(cfg: dict[str, Any], name: str) -> str:
    hooks = (cfg.get("history") or {}).get("webhooks") or {}
    return str(hooks.get(name) or DEFAULT_WEBHOOKS[name])


def wrap_message(username: str, embed: dict[str, Any]) -> dict[str, Any]:
    """One message in the BLHA format: the card, then the footer text and gold divider on the final embed."""
    return {"username": username, "avatar_url": AVATAR, "allowed_mentions": {"parse": []}, "embeds": fmt.apply([embed])}


def dynasty_message(summary: dict[str, Any], *, test: bool = False) -> dict[str, Any]:
    added = summary.get("last_added")
    if added:
        added_text = (f"{money(added['dues'])} dues + {money(added['unused_reserve'])} unused operating reserve "
                      f"(Season {added['season']})")
    else:
        added_text = "Nothing recorded yet."
    counts = [f"{r['name']}: {r['titles']}" for r in summary["rows"] if r["titles"]]
    embed = {
        "title": ("[TEST] " if test else "") + "DYNASTY POT UPDATE",
        "description": f"The pot stands at **{money(summary['balance'])}**.",
        "color": LEDGER_COLOR,
        "fields": [
            {"name": "THIS SEASON ADDED", "value": added_text, "inline": False},
            {"name": "CHAMPIONSHIP COUNTS THIS CYCLE", "value": "\n".join(counts) or "No championships yet this cycle.", "inline": False},
            {"name": "CYCLE STARTED", "value": f"Season {summary['cycle_started']}", "inline": False},
            {"name": "TO WIN", "value": f"{summary['titles_to_win']} BLHA Championships in the same active cycle (Article IV).", "inline": False},
        ],
        "image": {"url": "attachment://dynasty-pot.png"},
        "footer": {"text": "BLHA LEAGUE LEDGER"},
    }
    return wrap_message("BLHA League Ledger", embed)


def card_message(profile: dict[str, Any], filename: str, *, test: bool = False) -> dict[str, Any]:
    titles = profile["titles"]
    rival = f"{profile['rival']} (lifetime {profile['rival_record']})" if profile.get("rival") else "To be decided"
    lines = [
        f"**Owner:** {profile['owner'] or 'To be announced'}",
        f"**Founded:** Season {profile['founded']}" if profile.get("founded") else "**Founded:** To be announced",
        f"**Championships:** {len(titles)} ({', '.join(map(str, titles))})" if titles else "**Championships:** None yet",
        f"**Dynasty Pot:** {profile['dynasty_count']} of {profile['titles_to_win']} titles this cycle",
        f"**Rival:** {rival}",
    ]
    embed = {
        "title": ("[TEST] " if test else "") + profile["name"].upper(),
        "description": "\n".join(lines),
        "color": GOLD,
        "image": {"url": f"attachment://{filename}"},
        "footer": {"text": "BLHA FRANCHISE HQ"},
    }
    return wrap_message("BLHA Franchise HQ", embed)


def card_filename(profile: dict[str, Any]) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in profile["key"].lower()).strip("-") or "franchise"
    return f"franchise-{slug}.png"


def run_dynasty(mode: str, hist: LeagueHistory, cfg: dict[str, Any], out: Path) -> int:
    from history.graphics import dynasty_pot_png

    summary = dynasty_summary(hist)
    image = dynasty_pot_png(summary)
    message = dynasty_message(summary, test=mode == "test")
    print(f"Dynasty Pot: {money(summary['balance'])}, cycle began Season {summary['cycle_started']}, "
          f"{sum(r['titles'] for r in summary['rows'])} titles this cycle. Image rendered with Pillow ({len(image):,} bytes).")
    if mode == "preview":
        out.mkdir(parents=True, exist_ok=True)
        (out / "dynasty-pot.png").write_bytes(image)
        print(json.dumps(message, indent=2))
        print(f"PREVIEW: wrote {out / 'dynasty-pot.png'}; nothing posted.")
        return 0
    ok, detail = post_discord_webhook_files(webhook(cfg, "dynasty_pot"), message, [("dynasty-pot.png", image)])
    print(("POSTED" if ok else "ERROR") + f" [dynasty-pot]: {detail}")
    return 0 if ok else 1


def run_cards(mode: str, hist: LeagueHistory, cfg: dict[str, Any], out: Path) -> int:
    from history.graphics import franchise_card_png

    profiles = franchise_profiles(hist)
    if not profiles:
        print("No franchises in history.yaml or the archive yet; nothing to post.")
        return 0 if mode == "preview" else 1
    if mode == "test":
        profiles = profiles[:1]
    failed = 0
    for profile in profiles:
        name = card_filename(profile)
        image = franchise_card_png(profile)
        message = card_message(profile, name, test=mode == "test")
        if mode == "preview":
            out.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(image)
            print(f"{profile['name']}: {out / name} ({len(image):,} bytes, Pillow)")
            continue
        ok, detail = post_discord_webhook_files(webhook(cfg, "franchise_directory"), message, [(name, image)])
        print(("POSTED" if ok else "ERROR") + f" [{profile['name']}]: {detail}")
        failed += not ok
    if mode == "preview":
        print(f"PREVIEW: {len(profiles)} cards written to {out}; nothing posted.")
    return 1 if failed else 0


def pick_draft(hist: LeagueHistory, year: int | None) -> dict[str, Any] | None:
    drafts = hist.drafts()
    if not drafts:
        return None
    if year is None:
        return drafts[max(drafts)]
    return drafts.get(year)


def run_retro(mode: str, hist: LeagueHistory, cfg: dict[str, Any], year: int | None) -> int:
    from history import retro

    draft = pick_draft(hist, year)
    if not draft:
        have = ", ".join(map(str, sorted(hist.drafts()))) or "none"
        print(f"No saved draft for {year or 'any year'} (saved drafts: {have}). The archive saves a draft once it is complete.")
        return 1
    ids = [str(p["player"]) for p in draft.get("picks") or [] if p.get("player")]
    ids += [str(e["player"]) for e in retro.candidates_for_pickup(hist, draft)]
    print(f"Reading NHL stats for {len(ids)} players...")
    stats, unmatched = retro.fetch_stats(hist, ids)
    report = retro.build_report(hist, draft, stats, unmatched)
    print(retro.render_text(report))
    message = retro.payload(report, cfg, test=mode == "test")
    if mode == "preview":
        print(json.dumps(message, indent=2))
        print("PREVIEW: nothing posted or saved.")
        return 0
    secret = str(((cfg.get("draft_center") or {}).get("webhooks") or {}).get("results") or "BLHA_WEBHOOK_DRAFT_RESULTS")
    ok, detail = post_discord_webhook(secret, message)
    print(("POSTED" if ok else "ERROR") + f" [draft-retro]: {detail}")
    if ok and mode == "live":
        hist.archive.write(int(draft["season"]), "draft_retro.json", report)
        print(f"SAVED archive/{draft['season']}/draft_retro.json")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", choices=("dynasty-pot", "franchise-cards", "draft-retro"), required=True)
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    parser.add_argument("--draft-year", type=int, default=None, help="draft-retro: the year the draft was held (default: latest)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="preview: where to write images")
    args = parser.parse_args()
    cfg = load_league()
    hist = LeagueHistory(league=cfg)
    if args.item == "dynasty-pot":
        return run_dynasty(args.mode, hist, cfg, args.out)
    if args.item == "franchise-cards":
        return run_cards(args.mode, hist, cfg, args.out)
    return run_retro(args.mode, hist, cfg, args.draft_year)


if __name__ == "__main__":
    sys.exit(main())
