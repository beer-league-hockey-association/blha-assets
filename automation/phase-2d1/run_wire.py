#!/usr/bin/env python3
"""Production entry point for BLHA The Wire.

Keeps roster-ownership enrichment isolated from the core delivery engine while
preserving the existing engine.main() behavior.
"""

from __future__ import annotations

import sys

import engine
import roster_enrichment

# Replace the legacy inline enrichment implementation with the validated public
# Fantrax roster-ID resolver. Keeping this adapter explicit lets the core engine
# stay stable while the public Fantrax schema remains loosely documented.
engine.enrich_injury_ownership = roster_enrichment.enrich_injury_ownership


if __name__ == "__main__":
    sys.exit(engine.main())
