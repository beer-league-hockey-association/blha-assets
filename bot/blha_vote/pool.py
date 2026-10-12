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
  channel playoff_pool.entries_via in automation/league.yaml: "bot" takes
          picks here; "dm" (owners DM the Commissioner) turns /pool pick and
          /pool export off, because the export replaces entries.yaml and
          would drop the DM'd entries.

One entry per franchise; its Franchise Owner or Co-Owner picks one player per
box with menus, four boxes per page, and can change picks until the first
puck drop. An entry's time is when its last box was first filled; it breaks
the final tie (most goalie points first).

/pool export works only after the deadline: before it, the export would show
the Commissioner (an entrant too) every other franchise's picks. It counts
only picks made before the deadline (Store.pool_entries).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Sequence

from . import embeds as E
from . import shared  # noqa: F401  (puts automation/ on sys.path)

from playoff_pool import entries as pool_entries  # noqa: E402
from playoff_pool.boxes import Box, Boxes, Player, Settings  # noqa: E402

BOXES_URL = ("https://raw.githubusercontent.com/beer-league-hockey-association/blha-assets/"
             "automation-state/automation/playoff_pool/state/boxes.json")
URL_ENV = "BLHA_POOL_BOXES_URL"
PER_PAGE = 4  # four menus per page; the fifth row holds the page buttons
FOOTER = "BLHA PLAYOFF POOL"
NOT_POSTED = ("The Playoff Pool boxes aren't posted yet. They go up in game-day once the NHL playoff "
              "field is set.")
BOT, DM = "bot", "dm"  # playoff_pool.entries_via
RECHECK_SECONDS = 60  # a pick made while the cached boxes have no deadline re-reads boxes.json at most this old
DM_ENTRIES = ("This year, Playoff Pool entries go by DM to the Commissioner, not through the bot. Send your "
              "10 picks, one per box: the option number or the player's name, for example \"Box 1: 3, Box 2: 5\". "
              "`/pool boxes` shows the boxes and the deadline.")
DM_EXPORT = ("This year's Playoff Pool entries go by DM (`playoff_pool.entries_via: dm` in "
             "`automation/league.yaml`), so there's nothing to export: `/pool export` would replace "
             "`entries.yaml` and drop the DM'd entries. Add the DM'd picks to `entries.yaml` after the deadline, "
             "before the first standings post.")


def entries_via(league: Any) -> str:
    """playoff_pool.entries_via from automation/league.yaml (the automation's own reading and checks)."""
    raw = league.get("playoff_pool") if isinstance(league, dict) else None
    return Settings.from_cfg(raw).entries_via


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


def how_to_enter(via: str) -> str:
    if via == BOT:
        return "Pick one player from each box with `/pool pick`."
    return "DM your picks to the Commissioner, one player from each box."


def boxes_embed(boxes: Boxes, via: str = BOT) -> dict[str, Any]:
    description = (f"Just for fun: no money and no effect on the league. {how_to_enter(via)} "
                   f"{deadline_text(boxes)}.")
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


def export_refusal(boxes: Boxes, now: datetime) -> str | None:
    """Why /pool export must wait, or None once picks are locked.

    Before the deadline the file would show the Commissioner, who enters the
    pool too, everyone else's picks while their own can still change.
    """
    if boxes.locked(now):
        return None
    when = ("the NHL hasn't published the first puck drop yet" if boxes.deadline is None
            else f"they lock at the first puck drop, {E.stamp(boxes.deadline)} ({E.stamp(boxes.deadline, 'R')})")
    return (f"Picks are still open: {when}. The export works only after the deadline, so nobody, the "
            "Commissioner included, sees other entries while picks can change. Lock in your own picks with "
            "`/pool pick` first.")


def export_note(boxes: Boxes, rows: list[tuple[str, dict[int, int], datetime | None]],
                late: Sequence[tuple[str, int]] = ()) -> str:
    complete = sum(1 for _, picks, _ in rows if len(picks) == len(boxes.boxes))
    text = (f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} ({complete} complete). Commit this file as "
            "`automation/playoff_pool/entries.yaml` on main; the automation reads it at its next run.")
    if late:
        where = ", ".join(f"{name} box {number}" for name, number in late)
        text += (f" Ignored {len(late)} pick{'s' if len(late) != 1 else ''} made after the deadline ({where}): "
                 "the pick in place at the deadline counts, or the box is empty.")
    return E.clip(text, 2000)
