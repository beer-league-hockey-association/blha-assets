# BLHA Discohook graphics (8-bit arcade style)

Canonical hosted graphics for BLHA Discohook messages, drawn as pixel art by
tools/build_discord_assets.py (shared drawing code in tools/blha_pixel.py).

- Headers: 1600x533 (3:1) on a 200 x 67 pixel grid at 8 px per pixel, so each pixel
  is 2 px wide when Discord shows the image at 400 px.
- Header embed side color: #2B2D31.
- Footer: transparent 1600x180 PNG (legacy filename blha-footer-divider-1600x90.png kept).
- Palette: black #0E0F12, charcoal #2B2D31, gold #FFB81C, cream #F4EFE4, ice #EEF5FA,
  paper #FCFCFC, blue #2457C5, red #C8241F.
- Type: Jersey 10 for titles and Silkscreen for eyebrows and labels (brand/fonts).
- The right side of every header carries the pixel B traced from the official mark.
- Image URLs carry a cache-busting version (?v=8bit-1 on headers, ?v=8bit-1 on the footer),
  set in tools/discohook_format.py. Bump it whenever the artwork changes, then run
  tools/normalize_discohook_templates.py.
