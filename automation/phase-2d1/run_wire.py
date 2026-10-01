#!/usr/bin/env python3
"""Production entry point for BLHA The Wire.

Keeps compatibility/enrichment adapters isolated from the core delivery engine
while preserving the existing engine.main() behavior.
"""

from __future__ import annotations

import re
import sys

import engine
import roster_enrichment
import wire

# Replace the legacy inline enrichment implementation with the validated public
# Fantrax roster-ID resolver. Keeping this adapter explicit lets the core engine
# stay stable while the public Fantrax schema remains loosely documented.
engine.enrich_injury_ownership = roster_enrichment.enrich_injury_ownership

# National-news feeds sometimes describe a concrete absence without using a
# conventional injury keyword, e.g. "Dylan Larkin out for Red Wings' first two
# games". Treat a bounded "out for ... <duration>" phrase as an injury event.
_original_is_injury_event = wire.is_injury_event
_OUT_FOR_DURATION = re.compile(
    r"\bout for\b(?:\s+[a-z0-9][a-z0-9'\-]*){1,8}\s+"
    r"(?:games?|days?|weeks?|months?)\b",
    re.I,
)


def _is_injury_event_with_duration(title: str) -> bool:
    if _original_is_injury_event(title):
        return True
    return _OUT_FOR_DURATION.search(wire.normalize(title)) is not None


wire.is_injury_event = _is_injury_event_with_duration


if __name__ == "__main__":
    sys.exit(engine.main())
