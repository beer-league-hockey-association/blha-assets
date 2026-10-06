"""automation/history/history.yaml: the league records the Fantrax feed cannot know.

The Commissioner maintains franchise identities, each Season's honours and the
Dynasty Pot money in that file. Everything here reads and validates it; the
regression tests run ``validate`` so a typo is caught before it reaches the
site or Discord.

Dynasty Pot (Article IV): the first franchise to win three Championships in
the same active cycle wins the whole pot; then the balance returns to zero,
every counter resets and a new cycle starts the next Season (4.3, 4.6). The
championship counts are worked out from each Season's champion, so they never
need editing by hand; if ``dynasty_pot.championships`` is filled in, it must
agree. The same goes for each Season's recorded ``balance``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from blha.league import REPO_ROOT

HISTORY_PATH = Path(__file__).resolve().parent / "history.yaml"

AWARDS = {
    "champion": "BLHA Champion",
    "runner_up": "Runner-Up",
    "third_place": "Third Place",
    "presidents_trophy": "Presidents' Trophy",
    "consolation_champion": "Consolation Champion",
    "wooden_spoon": "Wooden Spoon",
}
PODIUM = ("champion", "runner_up", "third_place")
TOP_KEYS = {"franchises", "seasons", "dynasty_pot"}
FRANCHISE_KEYS = {"name", "owner", "founded", "colors", "logo", "team_ids"}
SEASON_KEYS = set(AWARDS) | {"dynasty_pot", "notes"}
SEASON_POT_KEYS = {"dues", "unused_reserve", "balance"}
DYNASTY_KEYS = {"first_cycle", "titles_to_win", "championships"}
FIRST_CYCLE = 2027      # Section 4.1
TITLES_TO_WIN = 3       # Section 4.3
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_raw(path: Path = HISTORY_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return data if isinstance(data, dict) else {"_not_a_mapping": data}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _season_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2200 else None


def validate(data: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[str]:
    """Every problem in history.yaml (empty list = valid)."""
    errors: list[str] = []
    if "_not_a_mapping" in data:
        return ["history.yaml must be a mapping with franchises, seasons and dynasty_pot"]
    for key in sorted(set(data) - TOP_KEYS):
        errors.append(f"unknown top-level key {key!r} (allowed: {', '.join(sorted(TOP_KEYS))})")

    franchises = data.get("franchises") or {}
    if not isinstance(franchises, dict):
        return errors + ["franchises must be a mapping of franchise key -> details"]
    owners_of_id: dict[str, str] = {}
    for key, row in franchises.items():
        where = f"franchises.{key}"
        if not SLUG.match(str(key)):
            errors.append(f"{where}: key must be lower-case letters, digits and dashes (it never changes)")
        if not isinstance(row, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        for extra in sorted(set(row) - FRANCHISE_KEYS):
            errors.append(f"{where}: unknown field {extra!r}")
        if not str(row.get("name") or "").strip():
            errors.append(f"{where}: name is required")
        if "owner" in row and not isinstance(row["owner"], str):
            errors.append(f"{where}: owner must be text")
        if "founded" in row and _season_year(row["founded"]) is None:
            errors.append(f"{where}: founded must be a year such as 2027")
        colors = row.get("colors", [])
        if not isinstance(colors, list) or len(colors) > 3 or any(not COLOR.match(str(c)) for c in colors):
            errors.append(f"{where}: colors must be a list of up to 3 hex colours like \"#FFB81C\"")
        logo = row.get("logo")
        if logo is not None:
            if not isinstance(logo, str) or not logo.lower().endswith(".png"):
                errors.append(f"{where}: logo must be a .png path in this repository")
            elif not (repo_root / logo).is_file():
                errors.append(f"{where}: logo {logo} does not exist")
        ids = row.get("team_ids", [])
        if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
            errors.append(f"{where}: team_ids must be a list of Fantrax team IDs in quotes")
            ids = []
        for team_id in ids:
            if team_id in owners_of_id:
                errors.append(f"{where}: team id {team_id} is also listed under {owners_of_id[team_id]}")
            owners_of_id[team_id] = str(key)

    seasons = data.get("seasons") or {}
    if not isinstance(seasons, dict):
        return errors + ["seasons must be a mapping of Season year -> honours"]
    for year, row in seasons.items():
        where = f"seasons.{year}"
        if _season_year(year) is None:
            errors.append(f"{where}: key must be a Season year such as 2027")
        if not isinstance(row, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        for extra in sorted(set(row) - SEASON_KEYS):
            errors.append(f"{where}: unknown field {extra!r} (allowed: {', '.join(sorted(SEASON_KEYS))})")
        for award in AWARDS:
            value = row.get(award)
            if value is not None and str(value) not in franchises:
                errors.append(f"{where}.{award}: {value!r} is not a franchise key under franchises")
        podium = [str(row[a]) for a in PODIUM if row.get(a)]
        if len(set(podium)) != len(podium):
            errors.append(f"{where}: champion, runner_up and third_place must be different franchises")
        pot = row.get("dynasty_pot")
        if pot is not None:
            if not isinstance(pot, dict):
                errors.append(f"{where}.dynasty_pot: must be a mapping with dues, unused_reserve, balance")
            else:
                for extra in sorted(set(pot) - SEASON_POT_KEYS):
                    errors.append(f"{where}.dynasty_pot: unknown field {extra!r}")
                for k in SEASON_POT_KEYS & set(pot):
                    if not _number(pot[k]):
                        errors.append(f"{where}.dynasty_pot.{k}: must be a dollar amount (0 or more)")

    dyn = data.get("dynasty_pot") or {}
    if not isinstance(dyn, dict):
        return errors + ["dynasty_pot must be a mapping"]
    for extra in sorted(set(dyn) - DYNASTY_KEYS):
        errors.append(f"dynasty_pot: unknown field {extra!r}")
    if "first_cycle" in dyn and _season_year(dyn["first_cycle"]) is None:
        errors.append("dynasty_pot.first_cycle must be a Season year")
    if "titles_to_win" in dyn and (not isinstance(dyn["titles_to_win"], int) or dyn["titles_to_win"] < 1):
        errors.append("dynasty_pot.titles_to_win must be a whole number")
    counts = dyn.get("championships")
    if counts is not None and (not isinstance(counts, dict) or any(
            str(k) not in franchises or not isinstance(v, int) or v < 0 for k, v in counts.items())):
        errors.append("dynasty_pot.championships must map franchise keys to whole numbers")
        counts = None

    if not errors:
        dynasty, problems = derive_dynasty(seasons, dyn)
        errors += problems
        if counts is not None:
            derived = {k: v for k, v in dynasty.active.titles.items() if v}
            given = {str(k): v for k, v in counts.items() if v}
            if derived != given:
                errors.append(f"dynasty_pot.championships {given} does not match the champions recorded "
                              f"since Season {dynasty.active.started}: {derived}")
    return errors


@dataclass
class Cycle:
    started: int
    titles: dict[str, int] = field(default_factory=dict)
    seasons: list[int] = field(default_factory=list)
    balance: float = 0.0
    ended: int | None = None
    winner: str | None = None
    payout: float | None = None


@dataclass
class Dynasty:
    active: Cycle
    past: list[Cycle]
    titles_to_win: int
    last_added: dict[str, Any] | None = None   # the latest Season's contribution {season, dues, unused_reserve}


def derive_dynasty(seasons: dict[Any, Any], settings: dict[str, Any] | None = None) -> tuple[Dynasty, list[str]]:
    """Replay every Season since the first cycle: balances, title counts, payouts and resets."""
    settings = settings or {}
    first = int(settings.get("first_cycle") or FIRST_CYCLE)
    need = int(settings.get("titles_to_win") or TITLES_TO_WIN)
    errors: list[str] = []
    past: list[Cycle] = []
    cur = Cycle(started=first)
    last_added = None
    for year in sorted(int(y) for y in seasons if _season_year(y) is not None):
        if year < first:
            continue
        row = seasons.get(year, seasons.get(str(year))) or {}
        pot = row.get("dynasty_pot") or {}
        dues, reserve = float(pot.get("dues") or 0), float(pot.get("unused_reserve") or 0)
        cur.balance += dues + reserve
        cur.seasons.append(year)
        if pot:
            last_added = {"season": year, "dues": dues, "unused_reserve": reserve}
        if "balance" in pot and abs(float(pot["balance"]) - cur.balance) > 0.005:
            errors.append(f"seasons.{year}.dynasty_pot.balance is {pot['balance']} but the contributions since "
                          f"Season {cur.started} add up to {cur.balance:g}")
        champ = row.get("champion")
        if champ:
            cur.titles[str(champ)] = cur.titles.get(str(champ), 0) + 1
            if cur.titles[str(champ)] >= need:
                cur.ended, cur.winner, cur.payout = year, str(champ), cur.balance
                past.append(cur)
                cur = Cycle(started=year + 1)
    return Dynasty(active=cur, past=past, titles_to_win=need, last_added=last_added), errors


class Records:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.data = data
        self.franchises: dict[str, dict[str, Any]] = {str(k): v for k, v in (data.get("franchises") or {}).items()}
        self.seasons: dict[int, dict[str, Any]] = {int(k): v or {} for k, v in (data.get("seasons") or {}).items()}
        self._by_team = {str(t): k for k, row in self.franchises.items() for t in row.get("team_ids") or []}
        self._by_name = {str(row.get("name") or "").strip().lower(): k for k, row in self.franchises.items()}

    @classmethod
    def load(cls, path: Path = HISTORY_PATH) -> "Records":
        data = load_raw(path)
        errors = validate(data)
        if errors:
            raise ValueError(f"{path} has problems:\n  " + "\n  ".join(errors))
        return cls(data)

    def franchise_for(self, team_id: str, team_name: str | None = None) -> str | None:
        """Franchise key for a Fantrax team id (or its name if no id is listed)."""
        if str(team_id) in self._by_team:
            return self._by_team[str(team_id)]
        if team_name:
            return self._by_name.get(team_name.strip().lower())
        return None

    def resolve(self, text: str) -> str | None:
        """A franchise key from a key, a listed Fantrax team id or a franchise name."""
        text = str(text or "").strip()
        if text in self.franchises:
            return text
        return self._by_team.get(text) or self._by_name.get(text.lower())

    def name(self, key: str) -> str | None:
        row = self.franchises.get(str(key))
        return str(row["name"]) if row else None

    def awards_of(self, key: str) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for year, row in sorted(self.seasons.items()):
            for award in AWARDS:
                if str(row.get(award) or "") == key:
                    out.setdefault(award, []).append(year)
        return out

    def titles(self, key: str) -> list[int]:
        return self.awards_of(key).get("champion", [])

    def dynasty(self) -> Dynasty:
        return derive_dynasty(self.seasons, self.data.get("dynasty_pot") or {})[0]


def money(value: float | int | None) -> str:
    value = float(value or 0)
    return f"${value:,.0f}" if value == int(value) else f"${value:,.2f}"
