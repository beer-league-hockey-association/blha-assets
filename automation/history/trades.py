"""Trade trees: follow what a franchise received in a trade, and what those assets became.

For one side of a trade, every asset it received is followed forward through
the archive's events:

  traded again   -> the node lists what came back, and each of those is followed in turn
  dropped        -> the branch ends
  a draft pick   -> used in a saved draft: the drafted player is followed
  nothing yet    -> "still on the roster" (players) or "not used yet" (picks)

Assets are followed per franchise (history.yaml ``team_ids``), so a tree keeps
going across a league renewal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from history.context import LeagueHistory
from history.store import parse_asset

MAX_DEPTH = 12


@dataclass
class Node:
    label: str
    outcome: str = ""
    asset: str = ""
    franchise: str = ""
    event: str | None = None
    children: list["Node"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label, "outcome": self.outcome}
        if self.asset:
            out["asset"] = self.asset
        if self.event:
            out["event"] = self.event
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)


def find_trade(hist: LeagueHistory, trade_id: str) -> tuple[int, dict[str, Any]]:
    for index, event in enumerate(hist.events()):
        if event.get("id") == trade_id and event.get("type") == "trade":
            return index, event
    raise KeyError(f"no trade with id {trade_id}")


def _index_after(events: list[dict[str, Any]], when: str | None) -> int:
    """Index of the last event at or before ``when`` (an ISO time), so following resumes after it."""
    if not when:
        return len(events) - 1
    try:
        moment = datetime.fromisoformat(when)
    except ValueError:
        return len(events) - 1
    last = -1
    for i, e in enumerate(events):
        try:
            if datetime.fromisoformat(str(e.get("at"))) <= moment:
                last = i
        except ValueError:
            continue
    return last


def follow(hist: LeagueHistory, asset: str, holder: str, after: int, depth: int = 0,
           seen: set[tuple[str, int]] | None = None) -> Node:
    """What became of ``asset`` held by franchise ``holder`` after event index ``after``."""
    seen = seen if seen is not None else set()
    node = Node(label=hist.asset(asset), asset=asset, franchise=holder)
    if depth >= MAX_DEPTH or (asset, after) in seen:
        node.outcome = "…"
        return node
    seen.add((asset, after))
    kind, value = parse_asset(asset)
    events = hist.events()
    for i in range(after + 1, len(events)):
        e = events[i]
        if e.get("type") == "trade":
            move = next((m for m in e.get("moves") or [] if m["asset"] == asset), None)
            if move is None:
                continue
            if hist.franchise(move["from"]) != holder:
                node.outcome = f"Left {hist.name(holder)} before the archive saw it; later moved {hist.event_date(e)}"
                return node
            to = hist.name(hist.franchise(move["to"]))
            node.outcome = f"Traded {hist.event_date(e)} to {to}"
            node.event = e.get("id")
            node.children = [follow(hist, got, holder, i, depth + 1, seen) for got in e["received"].get(move["from"], [])]
            if not node.children:
                node.outcome += " for nothing recorded"
            return node
        if e.get("type") == "drop" and kind == "player" and str(e.get("player")) == value:
            if hist.franchise(e.get("team", "")) == holder:
                node.outcome = f"Dropped {hist.event_date(e)}"
                node.event = e.get("id")
            else:
                node.outcome = f"Left {hist.name(holder)} before the archive saw it"
            return node
    if kind == "pick":
        selection = hist.pick_selection(value)
        if selection:
            used_by = hist.franchise(str(selection.get("team") or ""))
            slot = f"{selection['round']}.{int(selection['in_round']):02d}"
            pid = str(selection.get("player") or "")
            if used_by != holder:
                node.outcome = f"Used at {slot} by {hist.name(used_by)}"
                return node
            node.outcome = f"Used at {slot}"
            if pid:
                draft = hist.drafts().get(int(value.split("|")[0])) or {}
                start = _index_after(events, draft.get("end") or draft.get("date"))
                node.children = [follow(hist, f"player:{pid}", holder, start, depth + 1, seen)]
            return node
        node.outcome = "Not used yet"
        return node
    owner = hist.current_owner(value)
    if owner and owner[0] == holder:
        node.outcome = "Still on the roster" + (f" ({owner[1].title()})" if owner[1] else "")
    elif owner:
        node.outcome = f"Now with {hist.name(owner[0])} (moved between archive runs)"
    else:
        node.outcome = "No longer rostered"
    return node


def trade_tree(hist: LeagueHistory, trade_id: str, team_id: str) -> Node:
    """One side of a trade: what it received and everything that came of it."""
    index, trade = find_trade(hist, trade_id)
    holder = hist.franchise(team_id)
    gave = [hist.asset(a) for a in trade["sent"].get(team_id, [])] if trade.get("sent") else []
    root = Node(label=f"{hist.name(holder)}: trade of {hist.event_date(trade)}",
                outcome=("Gave " + ", ".join(gave)) if gave else "Gave nothing recorded",
                franchise=holder, event=trade_id)
    root.children = [follow(hist, a, holder, index) for a in trade["received"].get(team_id, [])]
    return root


def trade_trees(hist: LeagueHistory, trade_id: str) -> dict[str, Node]:
    _, trade = find_trade(hist, trade_id)
    return {team: trade_tree(hist, trade_id, team) for team in trade["teams"]}


def asset_path(hist: LeagueHistory, asset: str) -> list[dict[str, Any]]:
    """Every recorded move of one asset, oldest first: [{date, type, from, to, event}]."""
    kind, value = parse_asset(asset)
    out = []
    for e in hist.events():
        if e.get("type") == "trade":
            for m in e.get("moves") or []:
                if m["asset"] == asset:
                    out.append({"date": hist.event_date(e), "type": "trade", "from": hist.name(hist.franchise(m["from"])),
                                "to": hist.name(hist.franchise(m["to"])), "event": e.get("id")})
        elif kind == "player" and str(e.get("player")) == value and e.get("type") in ("add", "drop"):
            team = hist.name(hist.franchise(e.get("team", "")))
            out.append({"date": hist.event_date(e), "type": e["type"],
                        "from": "" if e["type"] == "add" else team, "to": team if e["type"] == "add" else "",
                        "event": e.get("id")})
    return out


def render_text(node: Node) -> str:
    """A plain-text tree, for logs and Discord code-free posts."""
    lines = [f"{node.label}" + (f" — {node.outcome}" if node.outcome else "")]

    def walk(n: Node, prefix: str) -> None:
        for i, child in enumerate(n.children):
            last = i == len(n.children) - 1
            lines.append(f"{prefix}{'└─ ' if last else '├─ '}{child.label}" + (f" — {child.outcome}" if child.outcome else ""))
            walk(child, prefix + ("   " if last else "│  "))

    walk(node, "")
    return "\n".join(lines)
