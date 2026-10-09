"""Discord payloads for the Playoff Pool (🏒│game-day).

House style (automation/DISCORD_AUTOMATION_STYLE.md): BLHA Competition Desk
sender, gold accent, league and season line first, vertical fields, no emoji,
short source footer.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

COMPETITION = Path(__file__).resolve().parents[1] / "competition"
if str(COMPETITION) not in sys.path:
    sys.path.insert(0, str(COMPETITION))

import render  # noqa: E402  (competition/render.py)

from .boxes import Boxes, Settings  # noqa: E402
from .scoring import Row, fmt, tie_note  # noqa: E402

FOOTER = "BLHA PLAYOFF POOL"
SOURCE = "NHL STATS DATA"
SHOWN = 12  # one field per owner
MESSAGE_MAX = 6000  # Discord's limit for all embed text in one message

FUN = "Just for fun: no money and no effect on the league."
SCORING = ("**Scoring** (BLHA points on NHL playoff games): skaters goal 5, assist 2.95, shot 0.55, block 0.35, "
           "hit 0.20, penalty minute -0.54; goalies start 6.5, save 0.49, goal against -5, goal 5, assist 2.95.")
TIES = "Ties: most points from the goalie (box 10), then the earliest entry."


def context(year: int, color: int, test: bool) -> render.Context:
    return render.Context(league_name="", season_label=f"{year} NHL Playoffs", color=color, test=test)


def _stamp(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


def _day(d: date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}"


def how_to_enter(settings: Settings) -> str:
    if settings.entries_via == "bot":
        return ("**How to enter** Use `/pool pick` and choose one player from each box. `/pool boxes` shows "
                "this list. You can change picks until the deadline.")
    return ("**How to enter** DM your 10 picks to the Commissioner, one per box: the option number or the "
            "player's name, for example \"Box 1: 3, Box 2: 5\". You can change them until the deadline.")


def deadline_line(boxes: Boxes) -> str:
    if boxes.deadline is None:
        return ("**Deadline** The first puck drop of the playoffs. The NHL hasn't published the time yet; "
                "this post shows it once it has.")
    return f"**Deadline** {_stamp(boxes.deadline)} ({_stamp(boxes.deadline, 'R')}), the first puck drop of the playoffs."


def _short(name: str) -> str:
    """'Connor McDavid' -> 'C. McDavid'."""
    first, _, rest = name.partition(" ")
    return f"{first[:1]}. {rest}" if rest else name


def box_fields(boxes: Boxes, *, stats: bool = True, short: bool = False) -> list[dict[str, Any]]:
    fields = []
    for box in boxes.boxes:
        lines = [f"{i}. {_short(p.name) if short else p.name}, {p.team}" + (f" — {p.stat}" if stats else "")
                 for i, p in enumerate(box.players, 1)]
        fields.append({"name": box.title.upper(), "value": render._clip("\n".join(lines) or "—"), "inline": False})
    return fields


def boxes_payload(ctx: render.Context, boxes: Boxes, settings: Settings) -> dict[str, Any]:
    rules = boxes.rules or {}
    tiers = (f"Boxes 1-8: skaters tiered by regular-season points per game ({rules.get('min_games', 20)}+ games). "
             "Box 9: dark horses from further down the list. Box 10: each team's likely starting goalie "
             "(most starts).")
    description = (
        f"{render._header(ctx)}\n\n"
        f"{FUN} Pick **one player from each box**; your 10 players score BLHA points in every NHL playoff game. "
        "The most points after the Stanley Cup Final wins the **Pool Shark** role for next season and a line "
        f"in the league history. {TIES}\n\n{tiers}\n\n{SCORING}\n{how_to_enter(settings)}\n{deadline_line(boxes)}"
    )
    title = f"{boxes.year} Playoff Pool: The Boxes"
    # Very long names: drop the stat column, then shorten first names, to stay in one message.
    for stats, short in ((True, False), (False, False), (False, True)):
        body = render._payload(ctx, title, description, box_fields(boxes, stats=stats, short=short),
                               FOOTER, source=SOURCE)
        if message_size(body) <= MESSAGE_MAX:
            break
    return body


def _owner_field(rank: int, row: Row, rows: list[Row], index: int, boxes: Boxes) -> dict[str, Any]:
    goalie_box = boxes.boxes[-1].number
    best = boxes.player(row.picks.get(row.best_box, 0)) if row.best_box else None
    goalie = boxes.player(row.picks.get(goalie_box, 0))
    lines = []
    if best is not None:
        lines.append(f"Best pick: {best.name} ({best.team}) {fmt(row.points.get(row.best_box, 0))}")
    goalie_text = f"{goalie.name} {fmt(row.goalie)}" if goalie else "no pick"
    lines.append(f"Goalie: {goalie_text} • Players out: {row.out} of {len(row.picks)}")
    note = tie_note(rows, index)
    if note:
        lines.append(f"*Tied on points; {note}.*")
    return {"name": f"{rank}. {row.owner} — {fmt(row.total)} pts", "value": render._clip("\n".join(lines)),
            "inline": False}


def standings_fields(rows: list[Row], boxes: Boxes) -> list[dict[str, Any]]:
    fields = [_owner_field(i + 1, row, rows, i, boxes) for i, row in enumerate(rows[:SHOWN])]
    if len(rows) > SHOWN:
        rest = [f"{i}. {r.owner} — {fmt(r.total)}" for i, r in enumerate(rows[SHOWN:], SHOWN + 1)]
        fields.append({"name": "ALSO ENTERED", "value": render._clip("\n".join(rest)), "inline": False})
    return fields


def standings_payload(ctx: render.Context, boxes: Boxes, rows: list[Row], games: int, through: date | None,
                      today: date) -> dict[str, Any]:
    counted = f"{games} playoff game{'s' if games != 1 else ''} counted"
    if through is not None:
        counted += f", through {_day(through)}"
    description = f"{render._header(ctx)}\n\n{FUN} BLHA scoring on NHL playoff games: {counted}. {TIES}"
    return render._payload(ctx, f"Playoff Pool Standings — {_day(today)}", description,
                           standings_fields(rows, boxes), FOOTER, source=SOURCE)


def final_payload(ctx: render.Context, boxes: Boxes, rows: list[Row], games: int, champion: str) -> dict[str, Any]:
    winner = rows[0]
    note = tie_note(rows, 0)
    decided = f" ({note})" if note else ""
    description = (
        f"{render._header(ctx)}\n\n**{champion} won the Stanley Cup.** **{winner.owner}** wins the {boxes.year} "
        f"Playoff Pool with {fmt(winner.total)} points{decided} and holds the **Pool Shark** role next season. "
        f"The title goes into the league history.\n\nFinal standings after {games} playoff games. {TIES}"
    )
    return render._payload(ctx, f"{boxes.year} Playoff Pool Final: {winner.owner} is the Pool Shark", description,
                           standings_fields(rows, boxes), FOOTER, source=SOURCE)


def message_size(payload: dict[str, Any]) -> int:
    """Characters Discord counts toward its 6,000 per-message embed limit."""
    total = 0
    for e in payload.get("embeds") or []:
        total += len(e.get("title", "")) + len(e.get("description", "")) + len((e.get("footer") or {}).get("text", ""))
        total += sum(len(f["name"]) + len(f["value"]) for f in e.get("fields") or [])
    return total
