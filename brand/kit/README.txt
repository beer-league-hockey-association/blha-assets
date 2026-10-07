BLHA BRAND & GRAPHICS PACKAGE (8-BIT ARCADE)
============================================
Every file is pixel art: drawn on a small grid and enlarged with hard edges.
Banners, headers, dividers and stamps use an 8 px grid (one pixel = 8 px).
Built by tools/build_brand_package.py (drawing code in tools/blha_pixel.py).

Palette: black #0E0F12, charcoal #2B2D31, gold #FFB81C, cream #F4EFE4,
ice #EEF5FA, paper #FCFCFC, blue #2457C5, red #C8241F.
Status green #3FA34D appears on stamps only. Team colors appear only on small
jersey or stripe elements, never on league marks.
Type: Jersey 10 (BLHA, titles) and Silkscreen (labels), in brand/fonts with OFL.txt.
Official marks: BLHA in Jersey 10 with gold then black keylines, and the pixel B
traced from the official mark (white, gold, black).

01_logos                 Wordmarks (transparent white / black, textured cream) and the B mark
02_avatars_icons         Server icon, webhook/bot avatar, profile pic, emoji, favicon
03_server_social_banners Discord server banner/splash, social preview, X header, event cover
04_channel_headers       1600x533 (3:1) headers for every channel category + welcome + generic
05_dividers              Footer divider (transparent), thin rule, gold bar
06_seals_stamps          Round official seal (dark/cream) and status stamps (transparent PNG)

Discord notes
- Embed images display at ~400px wide; headers are 3:1 so text stays readable.
- Discord caches by URL: when you replace a file, bump the ?v= version in
  tools/discohook_format.py and run tools/normalize_discohook_templates.py.
- Server banner needs a boosted server; recommended 960x540 or larger (16:9).
- Avatars use the small 14 x 14 pixel B so they stay sharp at Discord's 40-48 px.
- Stamps are transparent PNGs: use as embed thumbnail or image in rulings, votes and ledger posts.
