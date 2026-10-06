# BLHA Soundboard Sounds

These are original sounds synthesized from scratch in Python (no samples, recordings or downloaded audio), and the BLHA owns them.

All files are MP3, mono, 48 kHz, 192 kbps, peak-normalized to about -1 dBFS. All of them fit Discord's soundboard limits (MP3/OGG, under 512 KB, 5.2 s max).

| File | Length | Size | Suggested name | Emoji | Starting volume |
|---|---|---|---|---|---|
| `blha-goal-horn.mp3` | 4.00 s | 95 KB | BLHA Goal Horn | 🚨 | 80% |
| `blha-gavel.mp3` | 1.50 s | 37 KB | BLHA Gavel | ⚖️ | 100% |
| `blha-draft-horn.mp3` | 2.50 s | 60 KB | BLHA Draft Horn | 📯 | 75% |
| `blha-on-the-clock.mp3` | 4.25 s | 101 KB | BLHA On The Clock | ⏰ | 100% |
| `blha-trade-alert.mp3` | 1.50 s | 37 KB | BLHA Trade Alert | 🤝 | 75% |
| `blha-final-buzzer.mp3` | 2.50 s | 60 KB | BLHA Final Buzzer | 🏁 | 75% |

The starting volumes roughly even out how loud the sounds seem (from measured loudness). Adjust them to taste.

## What each one is

- **Goal horn:** a deep arena horn chord (110 to 220 Hz), with a crowd roar swelling underneath.
- **Gavel:** three sharp wooden knocks, for commissioner rulings.
- **Draft horn:** a bright two-note brass fanfare (rising fifth), for when the draft opens or a pick is in.
- **On the clock:** a tick-tock every half second that ends in a short buzzer.
- **Trade alert:** an upbeat three-note "deal done" chime.
- **Final buzzer:** a harsh end-of-period arena buzzer.

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

`generate_sounds.py` rebuilds every file the same way each time. It needs `numpy`, `scipy`, and `ffmpeg` with MP3 (libmp3lame) support.

```bash
python3 brand/sounds/generate_sounds.py            # writes next to the script
python3 brand/sounds/generate_sounds.py some/dir   # or into another folder
```

It prints a JSON check for each file (duration, size, decoded peak, clipped samples, loudness).
