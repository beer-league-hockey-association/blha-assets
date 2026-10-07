# BLHA Soundboard Sounds

These are original 8-bit chiptune sounds synthesized from scratch in Python (no samples, recordings or downloaded audio), and the BLHA owns them. They use the same console-style voices as the league's arcade brand: pulse waves with duty-cycle control, a 4-bit stepped triangle, a 15-bit LFSR noise channel and an 8-bit output crush.

All files are MP3, mono, 44.1 kHz, 192 kbps, loudness-matched to about -14 LUFS integrated with a true peak under -1 dBTP, so they all sound about the same volume. All of them fit Discord's soundboard limits (MP3/OGG, under 512 KB, 5.2 s max).

| File | Length | Size | Suggested name | Emoji | Starting volume |
|---|---|---|---|---|---|
| `blha-goal-horn.mp3` | 4.0 s | 96 KB | BLHA Goal Horn | 🚨 | 80% |
| `blha-gavel.mp3` | 1.2 s | 30 KB | BLHA Gavel | ⚖️ | 80% |
| `blha-draft-horn.mp3` | 3.0 s | 72 KB | BLHA Draft Horn | 📯 | 80% |
| `blha-on-the-clock.mp3` | 3.0 s | 72 KB | BLHA On The Clock | ⏰ | 80% |
| `blha-trade-alert.mp3` | 1.5 s | 37 KB | BLHA Trade Alert | 🤝🏻 | 80% |
| `blha-final-buzzer.mp3` | 2.5 s | 60 KB | BLHA Final Buzzer | 🏁 | 80% |

The sounds are already loudness-matched, so one starting volume works for all of them. Adjust to taste.

## What each one is

- **Goal horn:** a big arcade "GOAL!" fanfare: a sustained low square-wave horn chord with rising arpeggios on top and a noise-channel crowd swelling underneath.
- **Gavel:** three sharp knocks, each a metallic noise click over a low square thump, for commissioner rulings.
- **Draft horn:** a stately rising fanfare in pulse and triangle (D, G, A, then a held D chord with vibrato), for when the draft opens or a pick is in.
- **On the clock:** a noise-channel tick-tock every half second that ends in a rising two-tone pulse alarm.
- **Trade alert:** a quick "item get" chime: a rising pulse arpeggio into a held note, then a coin ding.
- **Final buzzer:** a harsh, long, detuned square-wave buzzer that cuts off cleanly.

## Adding them to Discord

You need the **Create Expressions** (or **Manage Expressions**) permission on the server.

1. Open the server, click the server name, then choose **Server Settings**.
2. Choose **Soundboard** in the left menu.
3. Click **Upload Sound**.
4. Click to choose a file and pick one of the `.mp3` files from this folder.
5. Set the **Sound Name** (2 to 32 characters; the suggested names above work).
6. Pick the **Related Emoji** from the table above (optional).
7. Set the **Volume** slider (the starting volumes above are a good start).
8. Click **Upload**. Repeat for each sound.

Members with the **Use Soundboard** permission can then play them from the soundboard button while they are in a voice channel.

**Slot limit:** a server without boosts gets **8 soundboard slots**. These 6 sounds leave 2 free. Server Boost levels add more slots (24 at Level 1, 36 at Level 2, 48 at Level 3).

## Regenerating

`generate_sounds.py` rebuilds every file the same way each time (fixed seeds and LFSR start states). It needs `numpy` and `ffmpeg` with MP3 (libmp3lame) support; loudness is set with ffmpeg's two-pass `loudnorm`.

```bash
python3 brand/sounds/generate_sounds.py                          # writes next to the script
python3 brand/sounds/generate_sounds.py some/dir                 # or into another folder
python3 brand/sounds/generate_sounds.py --preview preview.mp3    # also writes all six back to back, for auditioning
```

It prints a JSON check for each file (duration, size, sample rate, integrated loudness, true peak, clipped samples, and whether it fits the Discord limits).

## Emoji

`emoji/` holds a matching 8-bit emoji for each sound (128 x 128 PNG, drawn on a 16 x 16 pixel grid by `emoji/generate_emoji.py`). Upload them as server emoji with these names, then set each one as its sound's related emoji in Server Settings > Soundboard.

| Sound | Emoji file | Emoji name |
| --- | --- | --- |
| blha-goal-horn | `blha_goalhorn.png` | `blha_goalhorn` |
| blha-gavel | `blha_gavel.png` | `blha_gavel` |
| blha-draft-horn | `blha_drafthorn.png` | `blha_drafthorn` |
| blha-on-the-clock | `blha_onclock.png` | `blha_onclock` |
| blha-trade-alert | `blha_trade.png` | `blha_trade` |
| blha-final-buzzer | `blha_buzzer.png` | `blha_buzzer` |
