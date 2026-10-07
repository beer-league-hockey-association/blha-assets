"""The league archive: what the daily archive run keeps, and how everything else reads it.

The archive lives on the ``automation-state`` branch under ``archive/`` and is
restored into ``archive/`` at the repository root (git-ignored on main) when a
workflow runs. One folder per Fantrax season, keyed by Fantrax's
``seasonYear`` (BLHA Season 2027 = 2027-28 = seasonYear 2027), so renewing the
league in Fantrax never overwrites an earlier season:

  archive/players.json               Fantrax player id -> name, position, NHL team
                                     (only players the archive mentions)
  archive/<season>/meta.json         league id and label, team names, week dates,
                                     playoff settings, when snapshots were taken
  archive/<season>/rosters.json      latest roster snapshot: team id -> player id -> status
  archive/<season>/picks.json        latest draft-pick ownership: pick key -> owner team id
  archive/<season>/events.jsonl      append-only transactions inferred from snapshot changes
  archive/<season>/results.json      final matchup scores per scoring period
  archive/<season>/standings.json    final regular-season standings
  archive/<season>/draft.json        draft results, once the draft is complete
  archive/<season>/draft_retro.json  draft retrospective, saved when it is posted

Pick keys are ``<draft year>|<round>|<original owner team id>``. Assets in
events are ``player:<fantrax id>`` or ``pick:<pick key>``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from blha.league import REPO_ROOT, load_json, save_json

ARCHIVE_ENV = "BLHA_ARCHIVE_DIR"
DEFAULT_DIR = REPO_ROOT / "archive"


def default_dir() -> Path:
    raw = os.environ.get(ARCHIVE_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_DIR


def is_test_label(label: str) -> bool:
    """A season whose label says TEST (for example "2026-27 TEST")."""
    return bool(re.search(r"\btest\b", str(label or ""), re.IGNORECASE))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


class Archive:
    """Read access to the archive (and the small writes the run makes)."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else default_dir()

    # --- layout ---------------------------------------------------------------------
    def season_dir(self, season: int) -> Path:
        return self.root / str(int(season))

    def path(self, season: int, name: str) -> Path:
        return self.season_dir(season) / name

    def has(self, season: int, name: str) -> bool:
        return self.path(season, name).exists()

    # --- seasons --------------------------------------------------------------------
    def all_seasons(self) -> list[int]:
        if not self.root.is_dir():
            return []
        return sorted(int(p.name) for p in self.root.iterdir()
                      if p.is_dir() and p.name.isdigit() and (p / "meta.json").exists())

    def seasons(self) -> list[int]:
        """Seasons that count as league history.

        A season labeled TEST counts only until the first real season is
        archived, so the test league shows on the site while it is all there
        is and then drops out of lifetime records by itself.
        """
        every = self.all_seasons()
        real = [s for s in every if not self.meta(s).get("test")]
        return real or every

    def latest_season(self) -> int | None:
        seasons = self.seasons()
        return seasons[-1] if seasons else None

    # --- files ----------------------------------------------------------------------
    def meta(self, season: int) -> dict[str, Any]:
        return load_json(self.path(season, "meta.json"), {})

    def rosters(self, season: int) -> dict[str, dict[str, str]]:
        return load_json(self.path(season, "rosters.json"), {})

    def picks(self, season: int) -> dict[str, str]:
        return load_json(self.path(season, "picks.json"), {})

    def results(self, season: int) -> dict[str, Any]:
        return load_json(self.path(season, "results.json"), {})

    def standings(self, season: int) -> dict[str, Any] | None:
        return load_json(self.path(season, "standings.json"), {}) or None

    def draft(self, season: int) -> dict[str, Any] | None:
        return load_json(self.path(season, "draft.json"), {}) or None

    def retro(self, season: int) -> dict[str, Any] | None:
        return load_json(self.path(season, "draft_retro.json"), {}) or None

    def season_events(self, season: int) -> list[dict[str, Any]]:
        return read_jsonl(self.path(season, "events.jsonl"))

    def events(self) -> list[dict[str, Any]]:
        """Every event of every counted season, oldest first."""
        out: list[dict[str, Any]] = []
        for season in self.seasons():
            out += self.season_events(season)
        return out

    def players(self) -> dict[str, dict[str, Any]]:
        return load_json(self.root / "players.json", {})

    def team_names(self) -> dict[str, str]:
        """Fantrax team id -> its most recent name across every archived season."""
        names: dict[str, str] = {}
        for season in self.all_seasons():
            names.update({str(k): str(v) for k, v in (self.meta(season).get("teams") or {}).items()})
        return names

    # --- writes ---------------------------------------------------------------------
    def write(self, season: int, name: str, value: Any) -> None:
        save_json(self.path(season, name), value)

    def write_players(self, value: dict[str, Any]) -> None:
        save_json(self.root / "players.json", value)

    def append_events(self, season: int, events: list[dict[str, Any]]) -> None:
        append_jsonl(self.path(season, "events.jsonl"), events)


def parse_asset(asset: str) -> tuple[str, str]:
    """'player:04bdb' -> ('player', '04bdb'); 'pick:2028|1|abc' -> ('pick', '2028|1|abc')."""
    kind, _, value = str(asset).partition(":")
    return kind, value


def parse_pick(key: str) -> tuple[int, int, str] | None:
    parts = str(key).split("|")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), parts[2]
    except ValueError:
        return None
