# BLHA Phase 2C.6 v2 — Discohook Asset Hosting

This directory is the canonical public hosting package for BLHA Discohook images.

## Visual standard
- Header canvas: **1600×300**
- Footer divider: **1600×120** (legacy 1600x90 filename retained so URLs do not break)
- Charcoal: **#2B2D31**
- Gold: **#FFB81C**
- Cream: **#F4EFE4**
- Compact header composition removes unnecessary vertical space in Discord.
- Right-side faceoff circle is fully inset so it cannot clip.
- BLHA banner lettering is white with black/gold keylines and no white logo card.
- Welcome, League Office, and Draft Center headers share one layout system.

## Hosting behavior
Existing template URLs remain stable. Rebuilding these files changes the art without requiring Discohook image URL edits.

Header-only Discohook embeds should contain only the image object; do not add a blank Unicode description/spacer.

See `BLHA_URL_MAP.txt` at repository root for copy/paste URLs.
