#!/usr/bin/env python3
"""BLHA dormancy guard: keeps GitHub from silently switching the schedules off.

GitHub disables scheduled workflows in a public repository after 60 days with
no repository activity. This guard (which has no schedule of its own, so it
cannot be disabled that way) does two things each day:

1. Re-enables any workflow GitHub has disabled for inactivity (state
   `disabled_inactivity`) using GitHub's documented enable-workflow API, and
   tells the commissioner. It never touches a workflow someone disabled by hand.
2. Warns the commissioner when the default branch has had no commit for 45
   days, then again every 7 days, so a quiet stretch never reaches the limit
   unnoticed. It does not create fake commits.

Alerts go to the private Commissioner Desk channel.

Modes:
  preview  print what it found and would do; changes nothing
  test     post one [TEST] message; changes nothing
  live     re-enable workflows, post alerts, save warning state
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
AUTOMATION = ROOT.parent
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(AUTOMATION / "commissioner"))

from blha.league import load_json, load_league, save_json  # noqa: E402
from discord_webhook import post_discord_webhook  # noqa: E402
import desk  # noqa: E402

STATE_PATH = ROOT / "state" / "dormancy.json"
API = "https://api.github.com"
WARN_AFTER_DAYS = 45
REPEAT_DAYS = 7


class GitHub:
    def __init__(self, repo: str, token: str, session: requests.Session | None = None) -> None:
        self.repo = repo
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path: str, **params: Any) -> Any:
        r = self.session.get(f"{API}/repos/{self.repo}{path}", params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()

    def workflows(self) -> list[dict[str, Any]]:
        return self.get("/actions/workflows", per_page=100).get("workflows") or []

    def enable(self, workflow_id: int) -> None:
        r = self.session.put(f"{API}/repos/{self.repo}/actions/workflows/{workflow_id}/enable", timeout=30)
        r.raise_for_status()

    def last_commit_at(self) -> datetime:
        branch = self.get("").get("default_branch") or "main"
        commit = self.get("/commits", sha=branch, per_page=1)[0]
        return datetime.fromisoformat(commit["commit"]["committer"]["date"].replace("Z", "+00:00"))


def inactive_workflows(workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [w for w in workflows if w.get("state") == "disabled_inactivity"]


def manually_disabled(workflows: list[dict[str, Any]]) -> list[str]:
    return [w.get("name", "?") for w in workflows if w.get("state") == "disabled_manually"]


def should_warn(last_commit: datetime, now: datetime, last_warned: str | None) -> bool:
    if now - last_commit < timedelta(days=WARN_AFTER_DAYS):
        return False
    if last_warned and now - datetime.fromisoformat(last_warned) < timedelta(days=REPEAT_DAYS):
        return False
    return True


def build_task(reenabled: list[str], failed: list[str], quiet_days: int | None) -> dict[str, Any]:
    items: list[str] = []
    if reenabled:
        items.append("GitHub had switched these workflows off for inactivity. They are on again: " + ", ".join(reenabled) + ".")
    if failed:
        items.append("Could not re-enable these. Turn them on in the Actions tab: " + ", ".join(failed) + ".")
    if quiet_days is not None:
        left = max(60 - quiet_days, 0)
        items.append(
            f"The repository's main branch has had no commit for {quiet_days} days. GitHub switches scheduled workflows off after 60 days of no repository activity, which is about {left} days away. Any commit or merge to main resets it."
        )
    title = "GitHub schedules were switched off" if reenabled or failed else "GitHub may switch schedules off soon"
    return {"title": title, "section": "Reliability", "items": items}


def run(mode: str, gh: GitHub | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if gh is None:
        gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    cfg = load_league()
    state = load_json(STATE_PATH, {})
    workflows = gh.workflows()
    off = inactive_workflows(workflows)
    by_hand = manually_disabled(workflows)
    last_commit = gh.last_commit_at()
    quiet = (now - last_commit).days
    print(f"BLHA DORMANCY mode={mode.upper()} workflows={len(workflows)} disabled_for_inactivity={len(off)} last_main_commit={last_commit.date()} ({quiet} days ago)")
    if by_hand:
        print("Disabled by hand (left alone): " + ", ".join(by_hand))
    reenabled: list[str] = []
    failed: list[str] = []
    for w in off:
        if mode == "live":
            try:
                gh.enable(w["id"])
                reenabled.append(w["name"])
                print(f"RE-ENABLED {w['name']}")
            except Exception as exc:
                failed.append(w["name"])
                print(f"ERROR could not re-enable {w['name']}: {exc}")
        else:
            reenabled.append(w["name"])
            print(f"WOULD RE-ENABLE {w['name']}")
    warn = should_warn(last_commit, now, state.get("last_warned"))
    if not reenabled and not failed and not warn:
        print("Nothing to report.")
        return 0
    task = build_task(reenabled, failed, quiet if warn else None)
    for line in task["items"]:
        print("  " + line)
    if mode != "live":
        return 0
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, now=now))
    if not ok:
        print(f"DELIVERY ERROR: {detail}")
        return 1
    print("POSTED")
    if warn:
        save_json(STATE_PATH, {**state, "last_warned": now.isoformat()})
    return 1 if failed else 0


def test_post() -> int:
    cfg = load_league()
    task = build_task(["Sample workflow"], [], 46)
    task["items"].insert(0, "Sample only. Nothing was switched off.")
    ok, detail = post_discord_webhook(desk.secret_name(cfg), desk.build_payload(task, None, cfg, test=True))
    print(("PASS" if ok else "ERROR") + f" [dormancy]: {detail}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "live"), default="preview")
    args = parser.parse_args()
    return test_post() if args.mode == "test" else run(args.mode)


if __name__ == "__main__":
    sys.exit(main())
