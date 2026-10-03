"""End-of-season report for the commissioner (Constitution Articles XIV to XVI).

Pure functions: given final regular-season standings, work out the playoff
field, the Presidents' Trophy, the consolation bracket and every tie that
needs a human decision. Nothing here talks to Discord or Fantrax.

Fantrax's standings do not include Potential Points / Max Points For, so the
draft-order ranking (14.5) must still be copied from Fantrax by hand.
"""

from __future__ import annotations

from typing import Any


def _tied_with_next(rows: list[dict[str, Any]], i: int) -> bool:
    return i + 1 < len(rows) and rows[i]["record"] == rows[i + 1]["record"]


def _line(row: dict[str, Any], seed: int | None = None) -> str:
    label = f"{seed}. " if seed is not None else ""
    return f"{label}{row['teamName']} ({row['record']}, {row['pointsFor']:.1f} PF)"


def find_ties(rows: list[dict[str, Any]]) -> list[str]:
    """Plain-language notes about neighbouring teams with identical records (15.4)."""
    notes: list[str] = []
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1]["record"] == rows[i]["record"]:
            j += 1
        if j > i:
            group = rows[i : j + 1]
            names = ", ".join(r["teamName"] for r in group)
            pf = [round(r["pointsFor"], 2) for r in group]
            where = f"ranks {rows[i]['rank']} to {rows[j]['rank']}"
            if len(set(pf)) < len(pf):
                notes.append(
                    f"{names} ({where}, {group[0]['record']}) are also level on points scored. "
                    "Use head-to-head, then a recorded random draw (15.4)."
                )
            else:
                notes.append(
                    f"{names} ({where}, {group[0]['record']}) are level on record. "
                    "Fantrax ordered them; confirm it used points scored first (15.4)."
                )
        i = j + 1
    return notes


def build_report(rows: list[dict[str, Any]], playoff_teams: int = 6) -> dict[str, Any]:
    """rows: normalised Fantrax standings sorted by rank."""
    rows = sorted(rows, key=lambda r: r["rank"])
    field = rows[:playoff_teams]
    rest = rows[playoff_teams:]
    boundary: list[str] = []
    if len(rows) > playoff_teams and rows[playoff_teams - 1]["record"] == rows[playoff_teams]["record"]:
        boundary.append(
            f"The last playoff spot is decided by a tiebreak: {rows[playoff_teams - 1]['teamName']} "
            f"over {rows[playoff_teams]['teamName']}. Check this one first."
        )

    def pair(group: list[dict[str, Any]], a: int, b: int) -> str:
        return f"{group[a - 1]['teamName']} v {group[b - 1]['teamName']}"

    sections: list[tuple[str, list[str]]] = []
    if rows:
        sections.append((
            "Presidents' Trophy (15.3)",
            [_line(rows[0]) + (" Tied on record, check the tiebreak." if _tied_with_next(rows, 0) else "")],
        ))
    if len(field) >= 6:
        sections.append((
            "Playoff field and round 1",
            [_line(r, i) for i, r in enumerate(field, 1)]
            + [f"Round 1: {pair(field, 3, 6)} and {pair(field, 4, 5)}. Seeds 1 and 2 have byes."],
        ))
    else:
        sections.append(("Playoff field", [_line(r, i) for i, r in enumerate(field, 1)]))
    if len(rest) >= 6:
        sections.append((
            "Consolation bracket: enter by hand in Fantrax (16.7)",
            [_line(r, i) for i, r in enumerate(rest, 1)]
            + [f"Round 1: {pair(rest, 3, 6)} and {pair(rest, 4, 5)}. Seeds 1 and 2 have byes."],
        ))
    if rest:
        sections.append((
            "Draft order picks 1.01 to 1.06 (14.5)",
            [
                "Copy each team's Potential Points / Max Points For from Fantrax (it is not in the data feed). Lowest gets 1.01. A tie goes to the team with fewer points scored, then a recorded draw (15.5).",
                "Teams: " + "; ".join(f"{r['teamName']} ({r['pointsFor']:.1f} PF)" for r in rest),
            ],
        ))
    ties = boundary + find_ties(rows)
    if ties:
        sections.append(("Ties to check", ties))
    return {"sections": sections, "has_ties": bool(ties)}


def render(report: dict[str, Any]) -> str:
    parts = []
    for title, lines in report["sections"]:
        parts.append(f"**{title}**\n" + "\n".join(lines))
    return "\n\n".join(parts)
