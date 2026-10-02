"""League-wide configuration (automation/league.yaml) and shared constants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AUTOMATION_ROOT.parent
LEAGUE_PATH = AUTOMATION_ROOT / "league.yaml"

AVATAR = (
    "https://raw.githubusercontent.com/diseasewheeze/blha-assets/main/"
    "discord/webhooks/avatar/blha-webhook-avatar-512.png"
)
DEFAULT_LEAGUE_NAME = "Beer League Hockey Association"


def load_league(path: Path = LEAGUE_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not str(data.get("league_id") or "").strip():
        raise ValueError(f"league_id missing from {path}")
    data.setdefault("timezone", "America/New_York")
    data.setdefault("competition", {})
    return data


def timezone_of(cfg: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(str(cfg.get("timezone") or "America/New_York"))


def color_value(raw: Any, default: int = 0xFFB81C) -> int:
    if raw is None:
        return default
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return value if isinstance(value, type(default)) else default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
