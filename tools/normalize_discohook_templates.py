#!/usr/bin/env python3
"""Normalize and verify every BLHA Discohook template (templates/**/*.json).

Each template is one Discord message. The rules live in discohook_format.py:
- One message per send: the header banner embed (if the channel has one) plus
  ONE text embed. Extra text sections merge into it as bold divider fields.
- The header banner (charcoal #2B2D31, header image) keeps an invisible
  footer so Discohook accepts it.
- Only the final embed has footer text and the shared gold footer-divider
  image. No other embed has either.
- Discord limits are enforced (25 fields, 1,024 per field, 4,096 per
  description, 6,000 per message). Content that does not fit fails here and
  is never split, except the listed MULTI_SECTION_EXCEPTIONS.
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
    data["embeds"] = fmt.apply(data["embeds"], fmt.header_url(rel), rel)
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if rendered == path.read_text(encoding="utf-8"):
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def verify_file(path: Path) -> list[str]:
    rel = path.relative_to(TEMPLATES).as_posix()
    return [f"{rel}: {p}" for p in fmt.problems(load(path)["embeds"], fmt.header_url(rel), rel)]


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
