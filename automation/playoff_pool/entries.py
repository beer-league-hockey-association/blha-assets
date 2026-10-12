"""Pool entries: automation/playoff_pool/entries.yaml.

The automation only reads this file. It is filled in one of two ways:

  - Before the League Bot is live: owners DM their 10 picks to the
    Commissioner, who types them in after the deadline, before the first
    standings post (the repository is public, so never earlier). A pick can
    be the option number shown in the boxes post, the NHL player id, or the
    player's name.
  - With the League Bot: owners use /pool pick; after the deadline the
    Commissioner runs /pool export, which returns this file ready to commit.

Format::

    year: 2027                      # the NHL playoffs these picks are for
    entries:
      - owner: "Franchise 1"        # shown in the standings
        entered: "2027-04-16T21:05:00-04:00"   # optional, for the final tiebreak
        picks:
          1: 3                      # box 1, option 3
          2: 8478402                # box 2, NHL player id
          3: "Auston Matthews"      # box 3, by name

Rules: one entry per owner (a repeated owner is ignored), picks must be in
their box (others are skipped and listed as problems; a missing box scores 0),
and an entry ``entered`` after the deadline (the first puck drop) is late and
left out. ``entered`` without a time zone is league time. Entries without
``entered`` rank after timed ones on the last tiebreak, in file order. A file
for another year is ignored, so last year's picks never carry over.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .boxes import Boxes

ENTRIES_PATH = Path(__file__).resolve().parent / "entries.yaml"


@dataclass
class Entry:
    owner: str
    picks: dict[int, int]            # box number -> NHL player id
    entered: datetime | None = None  # aware, UTC
    order: int = 0


@dataclass
class Parsed:
    entries: list[Entry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    late: list[str] = field(default_factory=list)


def _when(value: Any, tz: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def _box_number(key: Any) -> int | None:
    match = re.fullmatch(r"(?:box\s*)?(\d+)", str(key).strip().lower())
    return int(match.group(1)) if match else None


def parse(raw: Any, boxes: Boxes, tz: ZoneInfo) -> Parsed:
    out = Parsed()
    if not isinstance(raw, dict):
        return out
    year = raw.get("year")
    rows = raw.get("entries") or []
    if year is None or str(year).strip() != str(boxes.year):
        if rows:
            out.problems.append(f"entries.yaml is for year {year!r}, not {boxes.year}; no entry was read")
        return out
    if not isinstance(rows, list):
        out.problems.append("entries must be a list")
        return out
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"entry {index + 1}"
        if not isinstance(row, dict):
            out.problems.append(f"{where}: must be a mapping with owner and picks")
            continue
        owner = str(row.get("owner") or "").strip()
        if not owner:
            out.problems.append(f"{where}: owner is missing")
            continue
        where = f"{owner}"
        if owner.lower() in seen:
            out.problems.append(f"{where}: listed twice; the later entry is ignored")
            continue
        seen.add(owner.lower())
        try:
            entered = _when(row.get("entered"), tz)
        except ValueError:
            out.problems.append(f"{where}: entered {row.get('entered')!r} is not a date and time; treated as missing")
            entered = None
        if entered is not None and boxes.deadline is not None and entered > boxes.deadline:
            out.late.append(owner)
            out.problems.append(f"{where}: entered after the deadline; left out")
            continue
        picks: dict[int, int] = {}
        raw_picks = row.get("picks") or {}
        if not isinstance(raw_picks, dict):
            out.problems.append(f"{where}: picks must map box numbers to players")
            raw_picks = {}
        for key, ref in raw_picks.items():
            number = _box_number(key)
            box = boxes.box(number) if number is not None else None
            if box is None:
                out.problems.append(f"{where}: there is no box {key!r}")
                continue
            player = box.find(ref)
            if player is None:
                out.problems.append(f"{where}: {ref!r} is not in box {number}; that box scores 0")
                continue
            picks[number] = player.id
        missing = [b.number for b in boxes.boxes if b.number not in picks]
        if missing:
            out.problems.append(f"{where}: no pick for box {', '.join(map(str, missing))} (scores 0)")
        if not picks:
            continue
        out.entries.append(Entry(owner, picks, entered, index))
    return out


def check_structure(raw: Any, box_count: int = 10) -> list[str]:
    """Problems with entries.yaml's layout, without the boxes (the regression tests run this
    on every change, so a typo shows up before the pool reads the file)."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["entries.yaml must be a mapping with year and entries"]
    problems = [f"unknown top-level key {k!r} (allowed: year, entries)" for k in sorted(set(raw) - {"year", "entries"})]
    year = raw.get("year")
    if year is not None and not (isinstance(year, int) and 2000 <= year <= 2200):
        problems.append(f"year must be a year such as 2027, not {year!r}")
    rows = raw.get("entries") or []
    if not isinstance(rows, list):
        return problems + ["entries must be a list"]
    if rows and year is None:
        problems.append("set year to the NHL playoff year these picks are for")
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not str(row.get("owner") or "").strip():
            problems.append(f"entry {index}: needs an owner")
            continue
        for extra in sorted(set(row) - {"owner", "entered", "picks"}):
            problems.append(f"{row['owner']}: unknown field {extra!r}")
        picks = row.get("picks") or {}
        if not isinstance(picks, dict):
            problems.append(f"{row['owner']}: picks must map box numbers to players")
            continue
        for key in picks:
            number = _box_number(key)
            if number is None or not 1 <= number <= box_count:
                problems.append(f"{row['owner']}: {key!r} is not a box number 1-{box_count}")
    return problems


def load(path: Path, boxes: Boxes, tz: ZoneInfo) -> Parsed:
    if not path.exists():
        return Parsed()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Parsed(problems=[f"entries.yaml is not valid YAML: {exc}"])
    return parse(raw, boxes, tz)


def dump(boxes: Boxes, rows: list[dict[str, Any]]) -> str:
    """entries.yaml text for ``rows`` ({owner, entered, picks: box -> player id}).

    Used by the League Bot's /pool export. Player names go in comments so the
    file can be checked by eye; the ids are what count.
    """
    lines = [
        "# BLHA Playoff Pool entries, exported by the League Bot (/pool export).",
        "# Commit this file as automation/playoff_pool/entries.yaml. Picks are NHL player ids.",
        f"year: {boxes.year}",
        "entries:" if rows else "entries: []",
    ]
    for row in rows:
        lines.append(f"  - owner: {json.dumps(str(row['owner']), ensure_ascii=False)}")
        entered = row.get("entered")
        if isinstance(entered, datetime):
            lines.append(f"    entered: \"{entered.astimezone(timezone.utc).isoformat()}\"")
        picks = row.get("picks") or {}
        lines.append("    picks:" if picks else "    picks: {}")
        for number in sorted(picks):
            player = boxes.player(int(picks[number]))
            note = f"  # {player.name}, {player.team}" if player else ""
            lines.append(f"      {int(number)}: {int(picks[number])}{note}")
    return "\n".join(lines) + "\n"
