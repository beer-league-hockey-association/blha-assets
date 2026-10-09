"""Playoff Pool entries in the League Bot: /pool boxes, /pool pick, /pool export.

The pool itself (boxes, scoring, standings, posts) is the GitHub automation in
automation/playoff_pool/. The two sides share data through files only:

  boxes   the automation saves the boxes it posted, with the pick deadline,
          to automation/playoff_pool/state/boxes.json on the public
          automation-state branch. The bot reads that file (BOXES_URL, or
          the BLHA_POOL_BOXES_URL variable) and re-reads it every 10 minutes.
  picks   the bot keeps each franchise's picks in its own database. The
          automation can't read that database, so after the deadline the
          Commissioner runs /pool export and commits the file it returns as
          automation/playoff_pool/entries.yaml, the only place the automation
          reads entries from (the same file the Commissioner fills by hand
          from DMs before the bot is live).

One entry per franchise; its Franchise Owner or Co-Owner picks one player per
box with menus, four boxes per page, and can change picks until the first
puck drop. An entry's time is when its last box was first filled; it breaks
the final tie (most goalie points first).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from . import embeds as E
from . import shared  # noqa: F401  (puts automation/ on sys.path)

from playoff_pool import entries as pool_entries  # noqa: E402
from playoff_pool.boxes import Box, Boxes, Player  # noqa: E402

BOXES_URL = ("https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/"
             "automation-state/automation/playoff_pool/state/boxes.json")
URL_ENV = "BLHA_POOL_BOXES_URL"
PER_PAGE = 4  # four menus per page; the fifth row holds the page buttons
FOOTER = "BLHA PLAYOFF POOL"
NOT_POSTED = ("The Playoff Pool boxes aren't posted yet. They go up in game-day once the NHL playoff "
              "field is set.")


def boxes_url() -> str:
    return os.environ.get(URL_ENV, "").strip() or BOXES_URL


def load_boxes(raw: Any) -> Boxes | None:
    """Boxes from boxes.json, or None if there are none (or the file is unreadable)."""
    if not isinstance(raw, dict) or not raw.get("boxes"):
        return None
    try:
        return Boxes.from_dict(raw)
    except (KeyError, TypeError, ValueError):
        return None


def pages(boxes: Boxes, per_page: int = PER_PAGE) -> list[list[Box]]:
    b = boxes.boxes
    return [b[i:i + per_page] for i in range(0, len(b), per_page)] or [[]]


def option(index: int, p: Player) -> tuple[str, str]:
    """(label, description) for a player's menu option."""
    return E.clip(f"{index}. {p.name} ({p.team})", 100), E.clip(p.stat, 100)


def deadline_text(boxes: Boxes) -> str:
    if boxes.deadline is None:
        return "Picks lock at the first puck drop (time not published yet)"
    return f"Picks lock at the first puck drop, {E.stamp(boxes.deadline)} ({E.stamp(boxes.deadline, 'R')})"


def picks_content(boxes: Boxes, franchise: str, mine: dict[int, int], page: int, page_count: int) -> str:
    made = sum(1 for b in boxes.boxes if b.number in mine)
    text = f"**{boxes.year} Playoff Pool: {franchise}** • {made} of {len(boxes.boxes)} boxes picked"
    if page_count > 1:
        text += f" • page {page + 1} of {page_count}"
    text += f"\n{deadline_text(boxes)}. You can change picks until then."
    if made == len(boxes.boxes):
        text += "\nAll set."
    return text


def boxes_embed(boxes: Boxes) -> dict[str, Any]:
    description = (f"Just for fun: no money and no effect on the league. Pick one player from each box with "
                   f"`/pool pick`. {deadline_text(boxes)}.")
    for stats in (True, False):
        fields = [(b.title.upper(), "\n".join(f"{i}. {p.name}, {p.team}" + (f" — {p.stat}" if stats else "")
                                               for i, p in enumerate(b.players, 1)))
                  for b in boxes.boxes]
        embed = E.card(f"{boxes.year} Playoff Pool: The Boxes", description, fields, FOOTER)
        if E.fits([embed]):
            break
    return embed


def valid_pick(boxes: Boxes, box_number: int, player_id: int) -> bool:
    box = boxes.box(box_number)
    return box is not None and any(p.id == player_id for p in box.players)


def export_text(boxes: Boxes, rows: list[tuple[str, dict[int, int], datetime | None]]) -> str:
    """entries.yaml for every franchise that picked (see automation/playoff_pool/entries.py)."""
    return pool_entries.dump(boxes, [{"owner": name, "entered": entered, "picks": picks}
                                     for name, picks, entered in rows])


def export_note(boxes: Boxes, rows: list[tuple[str, dict[int, int], datetime | None]], now: datetime) -> str:
    complete = sum(1 for _, picks, _ in rows if len(picks) == len(boxes.boxes))
    text = (f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} ({complete} complete). Commit this file as "
            "`automation/playoff_pool/entries.yaml` on main; the automation reads it at its next run.")
    if not boxes.locked(now):
        text += " Picks are still open, so export again after the deadline."
    return text
