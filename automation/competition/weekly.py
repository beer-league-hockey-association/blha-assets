"""Results-only weekly numbers for the Monday report: all-play, power rankings, awards.

Everything here is computed from Fantrax matchup scores (getMatchupScores), so
any owner can check it by hand:

- All-play: each team's record if it had played all 11 other teams that week
  (a win for every lower score, a loss for every higher one, a tie for equal).
- Power Rankings: 50% season points-for + 30% points-for over the last 3
  final weeks + 20% season all-play win %. Both points-for figures are scaled
  0 to 1 across the league (lowest team 0, highest 1).
- Weekly Awards: three stars (top three scores), Tough Luck (highest score in
  a loss), Lucky Win (lowest winning score), Closest Game, Biggest Blowout.

Weeks where every team scored 0 (placeholder weeks, such as a test league with
no games) are ignored throughout, and so are 0-0 matchups.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = (0.5, 0.3, 0.2)  # season PF, recent PF, season all-play win %
RECENT_WEEKS = 3


@dataclass
class Record:
    wins: int = 0
    losses: int = 0
    ties: int = 0

    def add(self, other: "Record") -> "Record":
        return Record(self.wins + other.wins, self.losses + other.losses, self.ties + other.ties)

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def pct(self) -> float:
        return (self.wins + 0.5 * self.ties) / self.games if self.games else 0.0

    def text(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ties}"


def teams(rows: list[dict]) -> list[dict]:
    return [row[side] for row in rows for side in ("away", "home")]


def is_placeholder(rows: list[dict]) -> bool:
    """True when no team scored (an empty or 0-0 placeholder week)."""
    return not any(t["score"] for t in teams(rows))


def real_matchups(rows: list[dict]) -> list[dict]:
    """Matchups that were actually played (not 0-0)."""
    return [r for r in rows if r["away"]["score"] or r["home"]["score"]]


def real_weeks(weeks: dict[int, list[dict]]) -> dict[int, list[dict]]:
    return {w: rows for w, rows in sorted(weeks.items()) if not is_placeholder(rows)}


# --- All-play -----------------------------------------------------------------

def all_play(rows: list[dict]) -> dict[str, Record]:
    """Each team's record that week against all other teams."""
    if is_placeholder(rows):
        return {}
    scores = {t["teamId"]: t["score"] for t in teams(rows)}
    result: dict[str, Record] = {}
    for team_id, score in scores.items():
        others = [s for other, s in scores.items() if other != team_id]
        result[team_id] = Record(
            wins=sum(1 for s in others if score > s),
            losses=sum(1 for s in others if score < s),
            ties=sum(1 for s in others if score == s),
        )
    return result


def season_all_play(weeks: dict[int, list[dict]]) -> dict[str, Record]:
    total: dict[str, Record] = {}
    for rows in real_weeks(weeks).values():
        for team_id, record in all_play(rows).items():
            total[team_id] = total.get(team_id, Record()).add(record)
    return total


# --- Season totals --------------------------------------------------------------

def head_to_head(weeks: dict[int, list[dict]]) -> dict[str, Record]:
    """Actual W-L-T from the matchups themselves."""
    total: dict[str, Record] = {}
    for rows in real_weeks(weeks).values():
        for row in real_matchups(rows):
            away, home = row["away"], row["home"]
            a = total.setdefault(away["teamId"], Record())
            h = total.setdefault(home["teamId"], Record())
            if away["score"] > home["score"]:
                a.wins += 1
                h.losses += 1
            elif home["score"] > away["score"]:
                h.wins += 1
                a.losses += 1
            else:
                a.ties += 1
                h.ties += 1
    return total


def points_for(weeks: dict[int, list[dict]]) -> dict[str, float]:
    total: dict[str, float] = {}
    for rows in real_weeks(weeks).values():
        for t in teams(rows):
            total[t["teamId"]] = total.get(t["teamId"], 0.0) + t["score"]
    return total


def scaled(values: dict[str, float]) -> dict[str, float]:
    """Min-max scale to 0..1 (lowest 0, highest 1). All equal -> all 0."""
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high - low < 1e-9:
        return {k: 0.0 for k in values}
    return {k: (v - low) / (high - low) for k, v in values.items()}


# --- Power rankings ---------------------------------------------------------------

@dataclass
class RankRow:
    rank: int
    team_id: str
    team_name: str
    score: float
    record: Record
    points_for: float
    recent_points_for: float
    all_play: Record
    previous_rank: int | None = None

    @property
    def change(self) -> int | None:
        """Places gained since last week (positive = moved up)."""
        return None if self.previous_rank is None else self.previous_rank - self.rank


def latest_names(weeks: dict[int, list[dict]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for _, rows in sorted(weeks.items()):
        for t in teams(rows):
            names[t["teamId"]] = t["teamName"]
    return names


def power_rankings(
    weeks: dict[int, list[dict]],
    previous: dict[str, int] | None = None,
    *,
    recent: int = RECENT_WEEKS,
    weights: tuple[float, float, float] = WEIGHTS,
) -> list[RankRow]:
    """Rank every team from the given final weeks' matchup scores.

    ``weeks`` maps week number -> normalized matchup rows for every final week
    of the season so far. ``previous`` maps teamId -> last week's rank.
    """
    played = real_weeks(weeks)
    if not played:
        return []
    recent_weeks = dict(list(played.items())[-recent:])
    season_pf = points_for(played)
    recent_pf = points_for(recent_weeks)
    for team_id in season_pf:
        recent_pf.setdefault(team_id, 0.0)
    ap = season_all_play(played)
    records = head_to_head(played)
    names = latest_names(weeks)
    pf_scaled, recent_scaled = scaled(season_pf), scaled(recent_pf)

    rows = []
    for team_id in season_pf:
        score = (
            weights[0] * pf_scaled[team_id]
            + weights[1] * recent_scaled[team_id]
            + weights[2] * ap.get(team_id, Record()).pct
        )
        rows.append(RankRow(
            rank=0,
            team_id=team_id,
            team_name=names.get(team_id, "Unknown Team"),
            score=round(score, 6),
            record=records.get(team_id, Record()),
            points_for=season_pf[team_id],
            recent_points_for=recent_pf[team_id],
            all_play=ap.get(team_id, Record()),
        ))
    # Ties: higher season points-for, then name, so the order is stable.
    rows.sort(key=lambda r: (-r.score, -r.points_for, r.team_name.lower()))
    for index, row in enumerate(rows, start=1):
        row.rank = index
        if previous and row.team_id in previous:
            row.previous_rank = int(previous[row.team_id])
    return rows


def ranks_of(rows: list[RankRow]) -> dict[str, int]:
    return {r.team_id: r.rank for r in rows}


# --- Weekly awards ----------------------------------------------------------------

@dataclass
class Result:
    winner: dict
    loser: dict

    @property
    def margin(self) -> float:
        return abs(self.winner["score"] - self.loser["score"])


@dataclass
class Awards:
    stars: list[dict] = field(default_factory=list)
    tough_luck: Result | None = None
    lucky_win: Result | None = None
    closest: Result | None = None
    blowout: Result | None = None

    @property
    def empty(self) -> bool:
        return not self.stars


def _result(row: dict) -> Result:
    away, home = row["away"], row["home"]
    return Result(away, home) if away["score"] >= home["score"] else Result(home, away)


def weekly_awards(rows: list[dict]) -> Awards:
    """Awards for one week. Empty for a placeholder week."""
    if is_placeholder(rows):
        return Awards()
    played = real_matchups(rows)
    scorers = sorted(
        (t for r in played for t in (r["away"], r["home"]) if t["score"] > 0),
        key=lambda t: (-t["score"], t["teamName"].lower()),
    )
    results = [_result(r) for r in played]
    decided = [r for r in results if r.margin > 0]
    awards = Awards(stars=scorers[:3])
    if decided:
        awards.tough_luck = max(decided, key=lambda r: (r.loser["score"], -r.margin))
        awards.lucky_win = min(decided, key=lambda r: (r.winner["score"], r.margin))
    if results:
        awards.closest = min(results, key=lambda r: (r.margin, -r.winner["score"]))
        awards.blowout = max(results, key=lambda r: (r.margin, r.winner["score"]))
    return awards
