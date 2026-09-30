#!/usr/bin/env python3
"""Probe all BLHA Wire source endpoints without posting to Discord."""

from __future__ import annotations

from pathlib import Path
import requests
import feedparser
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "sources.yaml"
UA = "BLHA-The-Wire-Source-Probe/0.1 (+https://github.com/diseasewheeze/blha-assets)"


def collect(cfg):
    out = []
    for section in ("sources", "planned_sources"):
        for src in cfg.get(section, []):
            if src.get("url") and src.get("type") in {"rss", "html", "html-or-rss"}:
                row = dict(src)
                row["section"] = section
                out.append(row)
    return out


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    sources = collect(cfg)
    print("BLHA The Wire — SOURCE PROBE")
    print("No Discord messages will be sent.\n")

    for src in sources:
        print(f"## {src['name']} [{src.get('type')}] enabled={src.get('enabled', False)}")
        print(src["url"])
        try:
            r = requests.get(src["url"], headers={"User-Agent": UA}, timeout=25, allow_redirects=True)
            ctype = r.headers.get("content-type", "")
            print(f"HTTP {r.status_code} | content-type={ctype} | final={r.url}")
            if src.get("type") == "rss" or "xml" in ctype or "rss" in ctype or "atom" in ctype:
                feed = feedparser.parse(r.content)
                print(f"entries={len(feed.entries)} | bozo={getattr(feed, 'bozo', None)}")
                if feed.entries:
                    for e in feed.entries[:3]:
                        print(f"  - {e.get('title', '(untitled)')}")
                if getattr(feed, "bozo", False):
                    print(f"  parser-warning={getattr(feed, 'bozo_exception', '')}")
            else:
                print(f"html-bytes={len(r.content)}")
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")
        print()


if __name__ == "__main__":
    main()
