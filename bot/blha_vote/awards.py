"""Annual Awards Ballot: owners vote 5-3-1 for the Season's awards after the BLHA Championship.

Just for fun, like Awards Night has always been: awards carry no money and
change nothing in the standings or the draft.

Awards (AWARDS):
  GM of the Year            every active franchise is on the ballot; owner-voted only
  Trade of the Year         the Commissioner lists the Season's trades
  Waiver Steal of the Year  the Commissioner lists the pickups
  Comeback Franchise        the biggest climbs in the regular-season standings since last
                            Season (proposed by the bot once it has last Season's final
                            standings), or listed by the Commissioner
  Bust of the Year          listed by the Commissioner; otherwise the biggest falls

Ballots: one per franchise, cast by the Franchise Owner like every league vote
(2.2). For each award a 1st, 2nd and 3rd choice worth 5, 3 and 1 points. No
owner may rank their own franchise for GM of the Year or Comeback Franchise,
their own pickup for Waiver Steal, or a trade they were part of for Trade of
the Year (either side), so nobody can give themselves points. Bust of the
Year allows it. A ballot can be changed until /awards close or the deadline.

Winner: the most points; a tie goes to the most first-place votes, and if it
is still tied the award is shared.

Recusal, in the spirit of 19.3: the Commissioner opens the ballot but can't
nominate their own franchise for an award whose nominees are chosen by hand
(Trade, Waiver Steal, Comeback, Bust). A neutral Assistant Commissioner can
add that nominee with /awards nominate. The Commissioner's ballot counts like
everyone else's.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import embeds as E
from .rules import Franchise

POINTS = {1: 5, 2: 3, 3: 1}
PLACES = (1, 2, 3)
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
MAX_NOMINEES = 25          # a Discord menu holds 25 options
DATA_NOMINEES = 3          # Comeback and Bust nominees proposed from the standings (ties at the cut included)
MAX_BALLOT_DAYS = 30
EXPORT_FORMAT = "blha-awards/1"
FOOTER = "BLHA RECORDS DEPARTMENT"
JUST_FOR_FUN = "Awards carry no money and change nothing in the standings or the draft."
RECUSAL = ("The Commissioner can't nominate their own franchise for Trade, Waiver Steal, Comeback or Bust; a neutral "
           "Assistant Commissioner adds it with `/awards nominate` (19.3). The Commissioner's ballot counts like "
           "everyone else's.")


@dataclass(frozen=True)
class Award:
    key: str
    name: str
    self_vote: bool   # may an owner rank their own franchise?
    listed: bool      # nominees chosen by hand (the Commissioner, or a neutral Assistant)
    blurb: str


AWARDS: tuple[Award, ...] = (
    Award("gm", "GM of the Year", False, False, "Every active franchise is on the ballot."),
    Award("trade", "Trade of the Year", False, True, "The Season's best trades."),
    Award("waiver", "Waiver Steal of the Year", False, True, "The Season's best pickups."),
    Award("comeback", "Comeback Franchise", False, True, "The biggest climbs in the standings since last Season."),
    Award("bust", "Bust of the Year", True, True, "All in good fun: the Season's biggest letdowns."),
)
BY_KEY = {a.key: a for a in AWARDS}
# Trade and Waiver Steal: what an owner may not vote for (refusals and the ballot note).
OWN = {"trade": "a trade your franchise was part of", "waiver": "your own franchise's pickup"}
UNLISTED = {"trade": "Trades your franchise was part of aren't listed",
            "waiver": "Your own franchise's pickups aren't listed"}


@dataclass(frozen=True)
class Nominee:
    id: str
    label: str
    franchises: tuple[str, ...] = ()
    detail: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Nominee":
        return cls(str(d["id"]), str(d["label"]), tuple(str(f) for f in d.get("franchises") or ()),
                   str(d.get("detail") or ""))

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "franchises": list(self.franchises), "detail": self.detail}

    @property
    def subtitle(self) -> str:
        """Franchises and detail for menus and posts, when the label doesn't already say it."""
        parts = []
        if self.franchises and self.label != " + ".join(self.franchises):
            parts.append(" + ".join(self.franchises))
        if self.detail:
            parts.append(self.detail)
        return " • ".join(parts)


Nominees = dict[str, list[Nominee]]   # award key -> nominees
Ballot = dict[str, dict[int, str]]    # award key -> place -> nominee id


def nominees_from_json(text: str | None) -> Nominees:
    raw = json.loads(text or "{}")
    return {k: [Nominee.from_dict(n) for n in v] for k, v in raw.items() if k in BY_KEY}


def nominees_to_json(nominees: Nominees) -> str:
    return json.dumps({k: [n.as_dict() for n in nominees[k]] for k in BY_KEY if nominees.get(k)})


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ----------------------------------------------------------------- nominees
SEPARATORS = re.compile(r"\s*[+,]\s*")


def match_franchises(text: str, names: Iterable[str]) -> list[str] | None:
    """Franchise names written before the colon ("Franchise 3 + Franchise 7"), or None if any is unknown."""
    known = {n.lower(): n for n in names}
    whole = text.strip().lower()
    if whole in known:
        return [known[whole]]
    parts = [p.strip().lower() for p in SEPARATORS.split(text) if p.strip()]
    if parts and all(p in known for p in parts):
        return list(dict.fromkeys(known[p] for p in parts))
    return None


def parse_nominees(award: Award, text: str, names: list[str], *, start: int = 1) -> tuple[list[Nominee], list[str]]:
    """Nominees typed by hand, one per line or separated by semicolons.

    Each starts with its franchise(s), then an optional colon and description:
    ``Franchise 3: Quinn Hughes off waivers`` or, for a trade,
    ``Franchise 3 + Franchise 7: Hughes for a 2029 1st``.
    """
    out: list[Nominee] = []
    errors: list[str] = []
    for raw in (e.strip() for e in re.split(r"[;\n]+", text or "")):
        if not raw:
            continue
        head, sep, tail = raw.partition(":")
        teams = match_franchises(head, names)
        if teams is None:
            errors.append(f"{E.clip(raw, 80)!r}: start with the franchise name, e.g. \"Franchise 3: ...\" "
                          "(\"Franchise 3 + Franchise 7: ...\" for a trade).")
            continue
        if award.key == "trade" and len(teams) < 2:
            errors.append(f"{E.clip(raw, 80)!r}: name both franchises in the trade, e.g. \"Franchise 3 + Franchise 7: ...\".")
            continue
        label = tail.strip() if sep and tail.strip() else " + ".join(teams)
        out.append(Nominee(f"{award.key}-{start + len(out)}", E.clip(label, 100), tuple(teams)))
    return out, errors


def gm_nominees(franchises: list[Franchise]) -> list[Nominee]:
    """GM of the Year: every active franchise."""
    return [Nominee(f"gm-{i}", f.name, (f.name,)) for i, f in enumerate((f for f in franchises if not f.orphaned), 1)]


def ranks_by_franchise(standings: list[dict[str, Any]], franchises: list[Franchise]) -> dict[str, int]:
    """Final regular-season rank per franchise name, from Fantrax standings (normalize_standings rows)."""
    by_team = {f.fantrax_team_id: f.name for f in franchises if f.fantrax_team_id}
    out = {}
    for row in standings:
        name = by_team.get(str(row.get("teamId") or ""))
        if name and int(row.get("rank") or 0) > 0:
            out[name] = int(row["rank"])
    return out


def _moves(previous: dict[str, int], current: dict[str, int], climb: bool, top: int) -> list[tuple[str, int]]:
    moves = [(name, previous[name] - rank) for name, rank in current.items() if name in previous]
    moves = [(n, m) for n, m in moves if (m > 0 if climb else m < 0)]
    moves.sort(key=lambda nm: (-abs(nm[1]), current[nm[0]] if climb else -current[nm[0]], nm[0]))
    if len(moves) > top:
        cut = abs(moves[top - 1][1])
        moves = [nm for nm in moves if abs(nm[1]) >= cut]  # ties at the cut stay in
    return moves


def comeback_nominees(previous: dict[str, int], current: dict[str, int], top: int = DATA_NOMINEES) -> list[Nominee]:
    """The franchises that climbed the most places in the final regular-season standings."""
    return [Nominee(f"comeback-{i}", name, (name,), f"{ordinal(previous[name])} to {ordinal(current[name])}, up {m}")
            for i, (name, m) in enumerate(_moves(previous, current, True, top), 1)]


def bust_nominees(previous: dict[str, int], current: dict[str, int], top: int = DATA_NOMINEES) -> list[Nominee]:
    """The franchises that fell the most places."""
    return [Nominee(f"bust-{i}", name, (name,), f"{ordinal(previous[name])} to {ordinal(current[name])}, down {-m}")
            for i, (name, m) in enumerate(_moves(previous, current, False, top), 1)]


def nomination_problems(award: Award, nominees: list[Nominee], nominator: set[str], *,
                        commissioner: bool) -> list[str]:
    """Why these hand-picked nominees can't be added by this person (19.3 recusal spirit)."""
    if not award.listed:
        return [f"{award.name} has no nominations: every active franchise is on the ballot."]
    problems = []
    for n in nominees:
        own = sorted(nominator & set(n.franchises))
        if not own:
            continue
        if commissioner:
            problems.append(f"{n.label}: the Commissioner can't nominate their own franchise ({', '.join(own)}) for "
                            f"{award.name}. A neutral Assistant Commissioner can add it with /awards nominate (19.3).")
        else:
            problems.append(f"{n.label}: you can't nominate your own franchise ({', '.join(own)}). Ask the "
                            "Commissioner or a neutral Assistant Commissioner.")
    return problems


def too_many(nominees: Nominees) -> list[str]:
    return [f"{BY_KEY[k].name} has {len(v)} nominees; the ballot menu holds {MAX_NOMINEES}."
            for k, v in nominees.items() if len(v) > MAX_NOMINEES]


def next_index(existing: list[Nominee]) -> int:
    """The number for the next hand-added nominee id (ids are never reused, so ballots stay valid)."""
    numbers = [int(n.id.rsplit("-", 1)[-1]) for n in existing if n.id.rsplit("-", 1)[-1].isdigit()]
    return max(numbers, default=0) + 1


def build_ballot(franchises: list[Franchise], texts: dict[str, str], previous: dict[str, int] | None,
                 current: dict[str, int] | None, nominator: set[str]) -> tuple[Nominees, list[str], list[str]]:
    """Nominees for /awards open: (nominees, errors that stop it, notes for the Commissioner).

    ``texts`` holds the Commissioner's hand-typed nominees per award key;
    ``previous`` and ``current`` are final regular-season ranks per franchise
    name (last Season and this one) for proposing Comeback and Bust;
    ``nominator`` is the Commissioner's own franchise(s).
    """
    names = [f.name for f in franchises]
    nominees: Nominees = {"gm": gm_nominees(franchises)}
    errors: list[str] = []
    notes: list[str] = []
    for award in AWARDS:
        if not award.listed:
            continue
        text = (texts.get(award.key) or "").strip()
        if text:
            found, bad = parse_nominees(award, text, names)
            errors += [f"{award.name}: {b}" for b in bad]
            errors += nomination_problems(award, found, nominator, commissioner=True)
            nominees[award.key] = found
        elif award.key in ("comeback", "bust") and previous and current:
            pick = comeback_nominees if award.key == "comeback" else bust_nominees
            nominees[award.key] = pick(previous, current)
            if not nominees[award.key]:
                moved = "climbed" if award.key == "comeback" else "fell"
                notes.append(f"No franchise {moved} in the standings since last Season, so {award.name} isn't on the "
                             "ballot.")
        else:
            why = ("last Season's final standings aren't on file" if award.key in ("comeback", "bust")
                   else "no nominees were listed")
            notes.append(f"{award.name} isn't on the ballot: {why}. Add nominees with /awards nominate.")
    errors += too_many(nominees)
    return {k: v for k, v in nominees.items() if v}, errors, notes


# ------------------------------------------------------------------ ballots
def options_for(award: Award, nominees: list[Nominee], voter: str) -> list[Nominee]:
    """Nominees this franchise may rank (never its own for GM, Comeback, Waiver Steal or Trade of the Year)."""
    return [n for n in nominees if award.self_vote or voter not in n.franchises]


def choose(current: dict[int, str], place: int, nominee_id: str, award: Award, nominees: list[Nominee],
           voter: str) -> tuple[dict[int, str], str | None]:
    """Put a nominee at 1st, 2nd or 3rd. A nominee holds one place: choosing it again moves it."""
    if place not in PLACES:
        return current, "Pick a 1st, 2nd or 3rd choice."
    nominee = next((n for n in nominees if n.id == nominee_id), None)
    if nominee is None:
        return current, f"That nominee isn't on the {award.name} ballot."
    if not award.self_vote and voter in nominee.franchises:
        if award.key in OWN:
            return current, f"You can't vote for {OWN[award.key]} for {award.name}."
        return current, f"You can't vote for your own franchise for {award.name}."
    out = {p: n for p, n in current.items() if n != nominee_id and p != place}
    out[place] = nominee_id
    return dict(sorted(out.items())), None


def ballot_problems(ballot: Ballot, nominees: Nominees, voter: str) -> list[str]:
    """Everything wrong with a stored ballot (empty when valid)."""
    problems = []
    for key, places in ballot.items():
        award = BY_KEY.get(key)
        if award is None:
            problems.append(f"Unknown award {key!r}.")
            continue
        ids = {n.id: n for n in nominees.get(key, [])}
        seen: set[str] = set()
        for place, nid in sorted(places.items()):
            nominee = ids.get(nid)
            if place not in PLACES:
                problems.append(f"{award.name}: place {place} isn't 1st, 2nd or 3rd.")
            elif nominee is None:
                problems.append(f"{award.name}: {nid} isn't a nominee.")
            elif not award.self_vote and voter in nominee.franchises:
                problems.append(f"{award.name}: {voter} can't vote for itself.")
            elif nid in seen:
                problems.append(f"{award.name}: {nominee.label} is ranked twice.")
            seen.add(nid)
    return problems


# -------------------------------------------------------------------- tally
@dataclass(frozen=True)
class Row:
    nominee: Nominee
    points: int
    firsts: int = 0
    seconds: int = 0
    thirds: int = 0


@dataclass(frozen=True)
class AwardResult:
    award: Award
    rows: list[Row]
    winners: list[Nominee] = field(default_factory=list)
    ballots: int = 0
    decided_by: str = ""   # "points", "first-place votes", "shared" or "" (no votes)

    @property
    def shared(self) -> bool:
        return len(self.winners) > 1


def tally(award: Award, nominees: list[Nominee], ballots: dict[str, dict[int, str]]) -> AwardResult:
    """5-3-1 points from ``ballots`` (voting franchise -> place -> nominee id) for one award.

    Entries that break the rules (unknown nominee, a self-vote where it isn't
    allowed, a nominee ranked twice) are skipped, never counted.
    """
    ids = {n.id: n for n in nominees}
    score = {n.id: [0, 0, 0, 0] for n in nominees}  # points, 1st, 2nd, 3rd
    counted = 0
    for voter, places in ballots.items():
        used: set[str] = set()
        for place in sorted(places):
            nid = places[place]
            nominee = ids.get(nid)
            if place not in POINTS or nominee is None or nid in used:
                continue
            if not award.self_vote and voter in nominee.franchises:
                continue
            used.add(nid)
            score[nid][0] += POINTS[place]
            score[nid][place] += 1
        counted += bool(used)
    rows = sorted((Row(ids[k], *v) for k, v in score.items()),
                  key=lambda r: (-r.points, -r.firsts, r.nominee.label.lower(), r.nominee.id))
    top = rows[0].points if rows else 0
    if top <= 0:
        return AwardResult(award, rows, [], counted, "")
    contenders = [r for r in rows if r.points == top]
    most_firsts = max(r.firsts for r in contenders)
    winners = [r.nominee for r in contenders if r.firsts == most_firsts]
    how = "points" if len(contenders) == 1 else "first-place votes" if len(winners) == 1 else "shared"
    return AwardResult(award, rows, winners, counted, how)


def tally_all(nominees: Nominees, ballots: dict[str, Ballot], voters: Iterable[str]) -> list[AwardResult]:
    """Every award on the ballot, counting only the given (active) franchises' ballots."""
    allowed = set(voters)
    out = []
    for award in AWARDS:
        if not nominees.get(award.key):
            continue
        per = {v: b.get(award.key, {}) for v, b in ballots.items() if v in allowed}
        out.append(tally(award, nominees[award.key], per))
    return out


def returned(ballots: dict[str, Ballot], voters: Iterable[str]) -> list[str]:
    """Active franchises that ranked at least one nominee."""
    allowed = set(voters)
    return sorted(v for v, b in ballots.items() if v in allowed and any(b.values()))


# ------------------------------------------------------------------- timing
def parse_deadline(text: str, now: datetime, tz: ZoneInfo) -> tuple[datetime | None, str | None]:
    """A deadline typed as 2028-04-20 (end of that day, league time) or 2028-04-20 21:00."""
    raw = (text or "").strip()
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None, "Write the deadline as a date like 2028-04-20, or a date and time like 2028-04-20 21:00."
    if dt.tzinfo is None:
        if len(raw) == 10:
            dt = dt.replace(hour=23, minute=59, second=59)
        dt = dt.replace(tzinfo=tz)
    dt = dt.astimezone(timezone.utc)
    if dt <= now:
        return None, "The deadline has to be in the future."
    if dt > now + timedelta(days=MAX_BALLOT_DAYS):
        return None, f"Keep the ballot open {MAX_BALLOT_DAYS} days or less."
    return dt, None


def open_problems(phase: str | None, season: int) -> list[str]:
    """Why /awards open can't run now. The ballot follows the Championship (Fantrax phase from blha.season)."""
    problems = []
    if not 2027 <= season <= 2200:
        problems.append("The Season must be a year from 2027 on, like 2027 for the first BLHA Season.")
    if phase in ("regular", "playoffs"):
        problems.append("The Awards Ballot opens after the BLHA Championship is final.")
    return problems


# ------------------------------------------------------------------- export
def season_payload(season: int, results: list[AwardResult], *, closed_at: datetime | None, ballots: int,
                   eligible: int, franchises: list[Franchise]) -> dict[str, Any]:
    """One Season's results in the export format documented in bot/README.md."""
    team_ids = {f.name: f.fantrax_team_id for f in franchises}

    def describe(n: Nominee) -> dict[str, Any]:
        return {"nominee": n.label, "franchises": list(n.franchises),
                "fantrax_team_ids": [team_ids.get(name, "") for name in n.franchises], "detail": n.detail}

    awards = []
    for r in results:
        rows = {row.nominee.id: row for row in r.rows}
        awards.append({
            "key": r.award.key,
            "name": r.award.name,
            "shared": r.shared,
            "decided_by": r.decided_by,
            "ballots": r.ballots,
            "winners": [{**describe(w), "points": rows[w.id].points, "first_place_votes": rows[w.id].firsts}
                        for w in r.winners],
            "results": [{**describe(row.nominee), "points": row.points, "first": row.firsts, "second": row.seconds,
                         "third": row.thirds} for row in r.rows],
        })
    return {
        "season": season,
        "closed_at": closed_at.astimezone(timezone.utc).isoformat() if closed_at else None,
        "ballots": ballots,
        "eligible_franchises": eligible,
        "points": {"first": POINTS[1], "second": POINTS[2], "third": POINTS[3]},
        "awards": awards,
    }


def merge_export(existing: Any, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Add or replace one Season in the export, keeping every other Season."""
    seasons = dict(existing.get("seasons") or {}) if isinstance(existing, dict) and \
        existing.get("format") == EXPORT_FORMAT else {}
    seasons[str(payload["season"])] = payload
    return {"format": EXPORT_FORMAT, "updated_at": now.astimezone(timezone.utc).isoformat(),
            "seasons": {k: seasons[k] for k in sorted(seasons)}}


def write_export(path: Path, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Merge into the JSON file at ``path`` (written atomically) and return the whole export."""
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
    merged = merge_export(existing, payload, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return merged


def default_export_path(db_path: str | None = None) -> Path:
    """Next to the bot's database on the Railway volume: /data/blha_awards.json."""
    db = db_path or os.environ.get("BLHA_DB_PATH") or "/data/blha_votes.db"
    return (Path(db).parent if db != ":memory:" else Path(".")) / "blha_awards.json"


# ---------------------------------------------------------------- rendering
def _nominee_line(n: Nominee) -> str:
    return f"{n.label} ({n.subtitle})" if n.subtitle else n.label


def ballot_embed(season: int, nominees: Nominees, closes_at: datetime) -> dict[str, Any]:
    """The public ballot post. Long nominee lists share what's left of Discord's 6,000 characters."""
    fixed = [
        ("HOW TO VOTE", "**Fill out my ballot** opens your private ballot. One ballot per franchise, cast by the "
                        "**Franchise Owner**: a 1st, 2nd and 3rd choice for each award, worth 5, 3 and 1 points. No "
                        "votes for your own franchise, your own pickup or a trade you were part of (Bust of the Year "
                        "excepted). Change it any time "
                        f"until **{E.stamp(closes_at)}** ({E.stamp(closes_at, 'R')})."),
        ("RESULTS", "Most points wins; a tie goes to the most first-place votes, then the award is shared. Winners "
                    "are announced in **🏆│hall-of-champions** and kept in the league records."),
        ("NOMINATIONS", RECUSAL),
        ("JUST FOR FUN", JUST_FOR_FUN),
    ]
    title, description = "BLHA AWARDS NIGHT", f"Season {season} ballots are open. Owners choose the winners."
    on_ballot = [a for a in AWARDS if nominees.get(a.key)]
    room = E.MESSAGE_MAX - 100 - E.counted(E.card(title, description, fixed, FOOTER))
    room -= sum(len(a.name) for a in on_ballot)
    each = max(40, min(E.FIELD_VALUE_MAX, room // max(1, len(on_ballot))))
    lists = [(a.name.upper(), E.clip("\n".join(_nominee_line(n) for n in nominees[a.key]), each)) for a in on_ballot]
    return E.card(title, description, lists + fixed, FOOTER)


def ballot_content(season: int, award: Award, nominees: list[Nominee], mine: dict[int, str], franchise: str,
                   closes_at: datetime, page: int, pages: int, *, can_rank: bool) -> str:
    by_id = {n.id: n for n in nominees}
    picks = " • ".join(f"{ORDINAL[p]} {by_id[nid].label}" for p, nid in sorted(mine.items()) if nid in by_id)
    text = (f"**Season {season} Awards • {award.name}** • {franchise}'s ballot • award {page + 1} of {pages} • "
            f"closes {E.stamp(closes_at, 'R')}\n{award.blurb} 1st = 5 points, 2nd = 3, 3rd = 1.\n"
            f"Your picks: {picks or 'none yet'}")
    if not can_rank:
        what = f"Every nominee is {OWN[award.key]}" if award.key in OWN else "Your franchise is the only nominee"
        text += f"\n{what}, so there's nothing for you to rank here."
    elif not award.self_vote:
        unlisted = UNLISTED.get(award.key, "Your own franchise isn't listed")
        text += f"\n{unlisted}: no self-votes for this award."
    return E.clip(text, 2000)


def _winner_text(r: AwardResult) -> str:
    if not r.winners:
        return "No votes."
    rows = {row.nominee.id: row for row in r.rows}
    lead = rows[r.winners[0].id]
    names = " and ".join(f"**{w.label}**" + (f" ({w.subtitle})" if w.subtitle else "") for w in r.winners)
    votes = f"{lead.firsts} first-place vote{'s' if lead.firsts != 1 else ''}"
    text = f"{names} • {lead.points} points, {votes}"
    if r.decided_by == "first-place votes":
        text += " • won the tie on first-place votes"
    elif r.shared:
        text += " • shared"
    others = [row for row in r.rows if row.nominee not in r.winners and row.points > 0][:3]
    if others:
        text += "\nAlso: " + ", ".join(f"{row.nominee.label} {row.points}" for row in others)
    return text


def results_embed(season: int, results: list[AwardResult], ballots: int, eligible: int) -> dict[str, Any]:
    return E.card(
        "BLHA AWARDS NIGHT: THE WINNERS",
        f"Season {season}, as voted by the owners: {ballots} of {eligible} franchises returned a ballot. 5 points for "
        "a first-place vote, 3 for second, 1 for third; a tie goes to the most first-place votes, then the award "
        "is shared.",
        [(r.award.name.upper(), _winner_text(r)) for r in results] + [("JUST FOR FUN", JUST_FOR_FUN)],
        FOOTER,
    )


def status_text(season: int, status: str, closes_at: datetime, done: list[str], waiting: list[str]) -> str:
    state = {"open": f"open until {E.stamp(closes_at)}", "closed": "closed", "posted": "closed, results posted"}
    return (f"**Season {season} Awards Ballot** ({state.get(status, status)})\n"
            f"Returned ({len(done)}): {', '.join(done) or 'none'}\nNot yet ({len(waiting)}): {', '.join(waiting) or 'none'}")
