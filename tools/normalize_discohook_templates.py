#!/usr/bin/env python3
"""Normalize and verify every BLHA Discohook template (templates/**/*.json).

Each template is one Discord message. The rules live in discohook_format.py:
- One message per send: up to 10 embeds and 6,000 counted characters. A
  template over either limit fails here; it is never split automatically.
- Channel intros (and the welcome message) start with the header banner embed:
  charcoal #2B2D31 side color and the header image, with no footer.
- Only the final embed has a footer: its footer text and the shared gold
  footer-divider image. Every other embed has neither.
- Message text, fields and semantic colors are preserved. The frozen divider
  URL keeps its version query so Discord cannot serve an older cached image.

Run with --check to verify without rewriting files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discohook_format as fmt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("embeds"), list):
        raise ValueError(f"{path}: root must be an object with an embeds list")
    return data


def normalize_file(path: Path) -> bool:
    data = load(path)
    rel = path.relative_to(TEMPLATES).as_posix()
    data["embeds"] = fmt.apply(data["embeds"], fmt.header_url(rel))
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if rendered == path.read_text(encoding="utf-8"):
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def verify_file(path: Path) -> list[str]:
    rel = path.relative_to(TEMPLATES).as_posix()
    return [f"{rel}: {p}" for p in fmt.problems(load(path)["embeds"], fmt.header_url(rel))]


def main() -> None:
    check_only = "--check" in sys.argv
    paths = sorted(TEMPLATES.rglob("*.json"))
    changed = 0 if check_only else sum(int(normalize_file(p)) for p in paths)
    errors = [e for p in paths for e in verify_file(p)]
    if errors:
        print("DISCOHOOK FORMAT: problems found:", *errors, sep="\n  ")
        sys.exit(1)
    done = "" if check_only else f" Changed {changed}."
    print(f"DISCOHOOK FORMAT: verified {len(paths)} templates.{done}")
    print("DISCOHOOK FORMAT: one message per send, footer and divider on the final embed only.")


if __name__ == "__main__":
    main()
