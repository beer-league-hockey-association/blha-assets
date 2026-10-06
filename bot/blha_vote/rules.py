"""League voting rules from the BLHA Constitution, with no Discord code.

Everything the bot decides (who may vote, whether a vote may open, and
whether it passed) lives here so it can be tested without Discord.

Constitution references:
  2.2   one vote per franchise, co-owners do not add votes
  2.3   an orphaned franchise has no vote; the 8-vote threshold does not change
  3.6   League Services Allocation votes: Commissioner's franchise does not
        vote; approval needs 8 of the other 11
  19.4  Interim / permanent Commissioner chosen by majority vote
  19.5  Commissioner removal: 8 of the other 11, Commissioner not voting
  20.1  no amendment vote before the Offseason after Season 2027
  20.2  proposal posted at least 7 days before voting opens
  20.3  amendment votes: Offseason only, 7-day window, 8 of 12 affirmative;
        non-votes and abstentions are not affirmative
  20.4  must be approved before the dues deadline of the Season it applies to
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

YES, NO, ABSTAIN = "yes", "no", "abstain"
YES_NO = (YES, NO, ABSTAIN)

# Phases from automation/blha/season.py. The Constitution's Offseason is
# every time outside the Active Season, which runs from Week 1's first
# lineup lock through the last Championship scoring period.
OFFSEASON_PHASES = {"preseason", "offseason"}


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    offseason_only: bool
    needs_proposal: bool
    excludes_commissioner: bool
    rule: str  # "supermajority" (8 affirmative) or "majority" (election)
    who_opens: str  # "commissioner" or "owner"


KINDS: dict[str, Kind] = {
    "amendment": Kind("amendment", "Material Amendment", True, True, False, "supermajority", "commissioner"),
    "services": Kind("services", "League Services Allocation change", True, True, True, "supermajority", "commissioner"),
    "removal": Kind("removal", "Commissioner removal for cause", False, False, True, "supermajority", "owner"),
    "interim": Kind("interim", "Interim Commissioner", False, False, False, "majority", "owner"),
    "commissioner": Kind("commissioner", "Permanent Commissioner", False, False, False, "majority", "owner"),
}


@dataclass(frozen=True)
class Franchise:
    name: str
    role_id: int
    commissioner: bool = False
    orphaned: bool = False
    fantrax_team_id: str = ""


@dataclass(frozen=True)
class Settings:
    threshold: int = 8           # affirmative votes needed (2.1 callout, 20.3)
    notice_days: int = 7         # 20.2
    window_days: int = 7         # 20.3
    amendment_votes_from: datetime | None = None   # 20.1
    dues_deadlines: dict[int, datetime] | None = None  # Season -> deadline (20.4)


def eligible(franchises: Iterable[Franchise], kind: Kind) -> list[Franchise]:
    """Franchises that cast a vote in this kind of vote."""
    out = []
    for f in franchises:
        if f.orphaned:
            continue
        if kind.excludes_commissioner and f.commissioner:
            continue
        out.append(f)
    return out


def threshold_text(kind: Kind, settings: Settings, franchises: list[Franchise]) -> str:
    if kind.rule == "majority":
        n = len(eligible(franchises, kind))
        return f"A majority of the {n} active franchises (at least {n // 2 + 1})."
    if kind.excludes_commissioner:
        others = sum(1 for f in franchises if not f.commissioner)
        return (f"At least **{settings.threshold} affirmative votes of the other {others}**. "
                "The Commissioner's franchise does not vote.")
    return (f"At least **{settings.threshold} affirmative votes out of {len(franchises)}**. "
            "Non-votes and abstentions are not affirmative.")


def open_problems(
    kind: Kind,
    *,
    now: datetime,
    phase: str | None,
    proposal_posted_at: datetime | None,
    effective_season: int | None,
    settings: Settings,
    next_season_start: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """Reasons a vote can't open now (blocking) and warnings to show.

    ``phase`` comes from Fantrax via blha.season.phase. None means Fantrax
    could not be read; an Offseason-only vote then refuses to open rather
    than guess.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    closes = now + timedelta(days=settings.window_days)

    if kind.offseason_only:
        if phase is None:
            blocking.append("Fantrax could not be read, so the bot can't confirm it is the Offseason. Try again later.")
        elif phase not in OFFSEASON_PHASES:
            blocking.append("Amendment votes are held only during the Offseason (20.3).")
        elif next_season_start is not None and closes > next_season_start:
            blocking.append("The 7-day window would run into the Active Season (20.3). Open it at least "
                            f"{settings.window_days} days before Week 1.")
        if settings.amendment_votes_from and now < settings.amendment_votes_from:
            blocking.append("No amendment vote may be held before the Offseason following Season 2027 (20.1).")

    if kind.needs_proposal:
        if proposal_posted_at is None:
            blocking.append("A written proposal must be posted first (20.2).")
        else:
            ready = proposal_posted_at + timedelta(days=settings.notice_days)
            if now < ready:
                blocking.append(f"Voting can open {settings.notice_days} days after the proposal was posted (20.2).")

        deadlines = settings.dues_deadlines or {}
        if effective_season is not None:
            deadline = deadlines.get(effective_season)
            if deadline is None:
                warnings.append(f"No dues deadline is set for Season {effective_season} in the bot config, "
                                "so the bot can't check 20.4. Confirm the vote closes before it.")
            elif closes > deadline:
                blocking.append(f"This vote would close after the Season {effective_season} dues deadline, so it "
                                f"could not apply to Season {effective_season} (20.4). Set the effective Season "
                                "to the next one, or open it earlier.")
    return blocking, warnings


@dataclass(frozen=True)
class Outcome:
    passed: bool
    counts: dict[str, int]
    not_voted: list[str]
    winner: str | None
    summary: str


def tally(
    kind: Kind,
    ballots: dict[str, str],
    franchises: list[Franchise],
    settings: Settings,
    options: list[str] | None = None,
) -> Outcome:
    """Count ballots (franchise name -> choice) for the eligible franchises only."""
    voters = eligible(franchises, kind)
    names = [f.name for f in voters]
    counted = {name: ballots[name] for name in names if name in ballots}
    not_voted = [name for name in names if name not in counted]

    if kind.rule == "supermajority":
        counts = {c: sum(1 for v in counted.values() if v == c) for c in YES_NO}
        passed = counts[YES] >= settings.threshold
        summary = (f"Yes {counts[YES]} • No {counts[NO]} • Abstain {counts[ABSTAIN]} • "
                   f"Not voted {len(not_voted)} ({settings.threshold} required)")
        return Outcome(passed, counts, not_voted, None, summary)

    opts = list(options or [])
    counts = {o: sum(1 for v in counted.values() if v == o) for o in opts}
    counts[ABSTAIN] = sum(1 for v in counted.values() if v == ABSTAIN)
    need = len(voters) // 2 + 1
    winner = next((o for o in opts if counts[o] >= need), None)
    parts = [f"{o} {counts[o]}" for o in opts] + [f"Abstain {counts[ABSTAIN]}", f"Not voted {len(not_voted)}"]
    summary = " • ".join(parts) + f" ({need} of {len(voters)} needed)"
    return Outcome(winner is not None, counts, not_voted, winner, summary)


def can_cast(member_role_ids: set[int], owner_role_id: int | None, franchises: list[Franchise],
             kind: Kind) -> tuple[Franchise | None, str | None]:
    """Which franchise a member votes for, or why they can't.

    Only the Franchise Owner role casts the franchise's vote; co-owners
    are read-only (welcome message, Discord Roles).
    """
    if owner_role_id and owner_role_id not in member_role_ids:
        return None, "Only a Franchise Owner can cast the franchise's vote."
    mine = [f for f in franchises if f.role_id in member_role_ids]
    if not mine:
        return None, "You don't have a franchise role, so you can't vote."
    if len(mine) > 1:
        return None, "You have more than one franchise role. Ask the Commissioner to fix your roles."
    franchise = mine[0]
    if franchise.orphaned:
        return None, f"{franchise.name} is orphaned and has no vote while orphaned (2.3)."
    if kind.excludes_commissioner and franchise.commissioner:
        return None, "The Commissioner's franchise does not vote on this (3.6, 19.5)."
    return franchise, None


def team_member(member_role_ids: set[int], allowed_role_ids: set[int], franchises: list[Franchise],
                *, needs_fantrax: bool = False) -> tuple[Franchise | None, str | None]:
    """Which franchise a Franchise Owner or Co-Owner belongs to, or why not.

    ``allowed_role_ids`` are the configured Franchise Owner and Co-Owner role
    IDs; the member needs one of them plus exactly one franchise role.
    """
    if not allowed_role_ids:
        return None, "The Franchise Owner and Co-Owner roles aren't set up in the bot yet. Ask the Commissioner."
    if not allowed_role_ids & member_role_ids:
        return None, "Only a Franchise Owner or Co-Owner can use this."
    mine = [f for f in franchises if f.role_id in member_role_ids]
    if not mine:
        return None, "You don't have a franchise role. Ask the Commissioner to add it."
    if len(mine) > 1:
        return None, "You have more than one franchise role. Ask the Commissioner to fix your roles."
    if needs_fantrax and not mine[0].fantrax_team_id:
        return None, f"{mine[0].name} isn't linked to a Fantrax team yet. Ask the Commissioner to set its fantrax_team_id."
    return mine[0], None


def fantrax_id_problems(franchises: list[Franchise], fantrax_teams: dict[str, str]) -> list[str]:
    """Config fantrax_team_ids that aren't teams in the Fantrax league (e.g. after a new league)."""
    if not fantrax_teams:
        return []
    return [f"{f.name}'s fantrax_team_id {f.fantrax_team_id} isn't a team in the Fantrax league."
            for f in franchises if f.fantrax_team_id and f.fantrax_team_id not in fantrax_teams]


def draw_panel(pool: dict[str, list[int]], excluded: set[str], rng, size: int = 3) -> list[tuple[str, int]]:
    """Review Panel draw (19.4): three owners from unaffected franchises.

    ``pool`` maps franchise name -> its Franchise Owner member IDs. Three
    distinct franchises are drawn, then one owner from each.
    """
    names = sorted(n for n, members in pool.items() if n not in excluded and members)
    if len(names) < size:
        raise ValueError(f"Only {len(names)} unaffected franchises have an owner; a panel needs {size}.")
    picked = rng.sample(names, size)
    return [(name, rng.choice(sorted(pool[name]))) for name in picked]
