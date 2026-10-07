"""Code shared with the rest of the repository.

The bot reuses the GitHub automation's read-only Fantrax client and season
calendar (automation/blha), the minor-eligibility and pick-trade helpers
(automation/commissioner), the League Office calendar (automation/league-office)
and the Constitution source (tools/). Railway deploys the whole repository, so
these folders are always next to the bot.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
AUTOMATION = REPO / "automation"
COMMISSIONER = AUTOMATION / "commissioner"
LEAGUE_OFFICE = AUTOMATION / "league-office"
TOOLS = REPO / "tools"
FIXTURES = AUTOMATION / "tests" / "fixtures"


def _on_path(folder: Path) -> None:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


_on_path(AUTOMATION)  # makes `blha` (Fantrax client, season calendar) importable


def _load(folder: Path, name: str) -> ModuleType:
    _on_path(folder)
    return importlib.import_module(name)


def minors() -> ModuleType:
    """automation/commissioner/minors.py (NHL lookups, age and games rules)."""
    return _load(COMMISSIONER, "minors")


def picktrades() -> ModuleType:
    """automation/commissioner/picktrades.py (Pick Clearance CSV, prepayment verdicts)."""
    return _load(COMMISSIONER, "picktrades")


def league_ops() -> ModuleType:
    """automation/league-office/league_ops.py (events.yaml reading)."""
    return _load(LEAGUE_OFFICE, "league_ops")


def build_constitution() -> ModuleType:
    """tools/build_constitution.py (the published section numbering)."""
    return _load(TOOLS, "build_constitution")
