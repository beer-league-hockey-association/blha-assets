"""Messages already posted in Discord, so nothing changes them by accident.

discohook-backups/posted.json lists every template that is live in a channel,
with a fingerprint of its text. While a template is listed:

- the builders keep the posted version instead of writing a new one, so a
  rebuild can never make a posted message out of date;
- the normalizer fails if the file no longer matches what was posted;
- the Send Console shows the row as already posted.

To change a posted message on purpose: move its entry from "posted" to
"update_in_place" (keep the message link), change the template and rebuild.
The Send Console then opens it in Discohook as an edit of the live message:
paste that channel's webhook URL and press Edit (the message keeps its place
and its pin). Then record it again with
`python3 tools/posted_messages.py add <template path> <channel>`.

The fingerprint is the same one the Discord audit computes from a live
message (title, description, fields, footer and image name of every embed),
so "posted and current" can be checked against the server.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
POSTED = ROOT / "discohook-backups" / "posted.json"


def fingerprint(embeds: list[dict]) -> int:
    """FNV-1a over the message's visible parts (matches the audit's in-browser hash)."""
    parts = []
    for e in embeds:
        p = [(e.get("title") or "").strip(), (e.get("description") or "").strip()]
        for f in e.get("fields") or []:
            p.append((f.get("name") or "").strip() + "\u0002" + (f.get("value") or "").strip())
        p.append(((e.get("footer") or {}).get("text") or "").strip())
        p.append(((e.get("image") or {}).get("url") or "").split("/")[-1])
        parts.append("\u0001".join(p))
    h = 0x811C9DC5
    data = "\u0003".join(parts).encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _file() -> dict:
    if not POSTED.exists():
        return {}
    return json.loads(POSTED.read_text(encoding="utf-8"))


def load() -> dict[str, dict]:
    """Templates posted in Discord and current: rel -> {channel, posted, fingerprint, message?}."""
    return _file().get("posted", {})


def to_update() -> dict[str, dict]:
    """Templates posted in Discord but out of date: edit them in place (Discohook "Edit")."""
    return _file().get("update_in_place", {})


def save(entries: dict[str, dict], update: dict[str, dict] | None = None) -> None:
    body = {"about": "Templates live in Discord. See tools/posted_messages.py.",
            "posted": dict(sorted(entries.items())),
            "update_in_place": dict(sorted((to_update() if update is None else update).items()))}
    POSTED.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_posted(rel: str) -> bool:
    return rel in load()


def keep_posted(rel: str, data: dict) -> dict:
    """The data to write for rel: the posted file when rel is posted and would change."""
    entry = load().get(rel)
    path = TEMPLATES / rel
    if entry and path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if fingerprint(data.get("embeds") or []) != entry["fingerprint"] and \
                fingerprint(current.get("embeds") or []) == entry["fingerprint"]:
            print(f"KEPT AS POSTED: {rel} (posted {entry['posted']}; see tools/posted_messages.py)")
            return current
    return data


def problems() -> list[str]:
    errs = []
    for rel, entry in load().items():
        path = TEMPLATES / rel
        if not path.exists():
            errs.append(f"{rel}: listed as posted but the template is missing")
            continue
        fp = fingerprint(json.loads(path.read_text(encoding="utf-8")).get("embeds") or [])
        if fp != entry["fingerprint"]:
            errs.append(f"{rel}: changed after it was posted in Discord. Resend it and update "
                        f"discohook-backups/posted.json, or revert the change")
    return errs


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "add":
        rel, channel = sys.argv[2], sys.argv[3]
        entries, update = load(), to_update()
        data = json.loads((TEMPLATES / rel).read_text(encoding="utf-8"))
        entries[rel] = {"channel": channel, "posted": sys.argv[4] if len(sys.argv) > 4 else date.today().isoformat(),
                        "fingerprint": fingerprint(data["embeds"])}
        if rel in update and update[rel].get("message"):
            entries[rel]["message"] = update[rel]["message"]
        update.pop(rel, None)
        save(entries, update)
        print(f"Recorded {rel} as posted in {channel}.")
        return
    errs = problems()
    print("\n".join(errs) if errs else f"POSTED: {len(load())} templates match what is in Discord.")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
