"""Reading Fantrax draft data (getDraftResults / getDraftPicks).

Shape verified against the test league's automated 36-round snake draft:

  getDraftResults -> {
    draftDate:  "2026-10-03T20:00:00.0-0400"   scheduled start
    draftState: "completed"                     (other values handled generically)
    startDate / endDate: actual start / finish
    draftOrder: [teamId, ...]                   round 1 order
    draftPicks: [{round, pick, pickInRound, teamId, time (ms), playerId}, ...]
  }

  getDraftPicks -> {currentDraftPicks: [...], futureDraftPicks: [...]}

Fields for a draft still in progress (unmade or skipped picks) are read
defensively: a pick counts as made only when it has a playerId.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .season import parse_dt

COMPLETED_STATES = {"completed", "complete", "finished", "done"}


@dataclass
class Pick:
    round: int
    overall: int
    in_round: int
    team_id: str
    player_id: str = ""
    time: datetime | None = None

    @property
    def made(self) -> bool:
        return bool(self.player_id)

    @property
    def label(self) -> str:
        return f"{self.round}.{self.in_round:02d}"


@dataclass
class Draft:
    date: datetime | None
    state: str
    start: datetime | None
    end: datetime | None
    order: list[str]
    picks: list[Pick] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identifies one scheduled draft (changes when the date is moved)."""
        return self.date.isoformat() if self.date else "undated"

    @property
    def rounds(self) -> int:
        return max((p.round for p in self.picks), default=0)

    @property
    def completed(self) -> bool:
        if self.state.lower() in COMPLETED_STATES:
            return True
        return bool(self.picks) and all(p.made for p in self.picks)

    def status(self, now: datetime) -> str:
        """pre (not started), live (running) or done."""
        if self.completed:
            return "done"
        if any(p.made for p in self.picks):
            return "live"
        if self.start and now >= self.start:
            return "live"
        if self.date and now >= self.date:
            return "live"
        return "pre"

    def round_picks(self, number: int) -> list[Pick]:
        return sorted((p for p in self.picks if p.round == number), key=lambda p: p.overall)

    def round_complete(self, number: int) -> bool:
        picks = self.round_picks(number)
        return bool(picks) and all(p.made for p in picks)

    def on_the_clock(self) -> Pick | None:
        """The pick currently being waited on: the first unmade pick after the
        last pick made. Earlier unmade picks were skipped (see ``skipped``)."""
        ordered = sorted(self.picks, key=lambda p: p.overall)
        last_made = max((p.overall for p in ordered if p.made), default=0)
        return next((p for p in ordered if not p.made and p.overall > last_made), None)

    def skipped(self) -> list[Pick]:
        """Unmade picks that the draft has already moved past."""
        ordered = sorted(self.picks, key=lambda p: p.overall)
        last_made = max((p.overall for p in ordered if p.made), default=0)
        return [p for p in ordered if not p.made and p.overall < last_made]

    def last_pick_time(self) -> datetime | None:
        times = [p.time for p in self.picks if p.made and p.time]
        return max(times) if times else None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_results(raw: Any) -> Draft:
    raw = raw if isinstance(raw, dict) else {}
    picks: list[Pick] = []
    for row in raw.get("draftPicks") or []:
        if not isinstance(row, dict):
            continue
        ms = row.get("time")
        when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if isinstance(ms, (int, float)) and ms > 0 else None
        picks.append(Pick(
            round=_int(row.get("round")),
            overall=_int(row.get("pick")),
            in_round=_int(row.get("pickInRound")),
            team_id=str(row.get("teamId") or ""),
            player_id=str(row.get("playerId") or ""),
            time=when,
        ))
    picks.sort(key=lambda p: p.overall)
    return Draft(
        date=parse_dt(raw.get("draftDate")),
        state=str(raw.get("draftState") or ""),
        start=parse_dt(raw.get("startDate")),
        end=parse_dt(raw.get("endDate")),
        order=[str(t) for t in raw.get("draftOrder") or [] if t],
        picks=picks,
    )


def traded_slots(raw_picks: Any) -> list[dict[str, Any]]:
    """Current-draft picks whose owner is not the original team (getDraftPicks)."""
    rows = raw_picks.get("currentDraftPicks") if isinstance(raw_picks, dict) else None
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        original = str(row.get("originalOwnerTeamId") or "")
        current = str(row.get("currentOwnerTeamId") or "")
        if original and current and original != current:
            out.append({
                "round": _int(row.get("round")),
                "pick": _int(row.get("pick") or row.get("pickInRound")),
                "original": original,
                "current": current,
            })
    out.sort(key=lambda r: (r["round"], r["pick"], r["original"]))
    return out


def window_start(draft: Draft, now: datetime, lead: timedelta, linger: timedelta) -> datetime | None:
    """When the Draft Center's active window opened, or None if it is closed.

    Opens ``lead`` before the scheduled draft date and stays open while the
    draft runs, then for ``linger`` after it finishes (so the recap and
    completion posts go out). A scheduled date more than a week in the past
    with no picks made is treated as stale.
    """
    if draft.date is None:
        return None
    opens = draft.date - lead
    if now < opens:
        return None
    if draft.completed:
        finished = draft.end or draft.last_pick_time() or draft.date
        return opens if now <= finished + linger else None
    if not any(p.made for p in draft.picks) and now > draft.date + timedelta(days=7):
        return None
    return opens
