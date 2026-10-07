"""How BLHA Discord messages lay out on every screen.

Discord wraps text to the width it has, so the same message can look different
on a wide desktop, on desktop with the member list open, on a tablet and on a
phone. These checks keep the parts that should never break looking the same
everywhere:

- No inline fields. Phones ignore "inline" and stack the fields, so side-by-side
  columns only exist on desktop. Lists go in one field instead.
- Section dividers ("━━━ TITLE ━━━") and field names fit on one line on a
  phone, the narrowest screen.
- Embed titles fit on one line on desktop with the member list open and on a
  tablet. On a phone a long title or footer may take two lines (reported as
  a note, not an error).

Widths are in Inter 14 px units, calibrated against a real Discord screenshot
(desktop with the member list open wrapped exactly where this model predicts).
Discord's own font (gg sans) is about 10% narrower than Inter, so the model errs
toward wrapping. Embed titles are 16 px, field names 14 px, both semibold.
"""

from __future__ import annotations

import re
import unicodedata

SCREENS = {
    "desktop": 540,
    "desktop with member list": 457,
    "tablet": 457,
    "phone": 240,
}
PHONE = SCREENS["phone"]
NARROW_DESKTOP = SCREENS["desktop with member list"]

# Advance width per character, as a fraction of the font size (Inter; DejaVu
# Sans where Inter has no glyph). Generated with Chromium's canvas measureText.
_WIDTH = {
    400: {
    " ": 0.2812, "!": 0.2876, "\"": 0.4658, "#": 0.6333, "$": 0.6416, "%": 0.9819, "&": 0.644, "'": 0.2998,
    "(": 0.3647, ")": 0.3647, "*": 0.501, "+": 0.6616, ",": 0.2881, "-": 0.46, ".": 0.2881, "/": 0.3604,
    "0": 0.6309, "1": 0.4067, "2": 0.6099, "3": 0.6177, "4": 0.646, "5": 0.6079, "6": 0.6201, "7": 0.5659,
    "8": 0.6187, "9": 0.6201, ":": 0.2881, ";": 0.3018, "<": 0.6616, "=": 0.6616, ">": 0.6616, "?": 0.5112,
    "@": 0.9658, "A": 0.6899, "B": 0.6543, "C": 0.7305, "D": 0.7217, "E": 0.6011, "F": 0.5903, "G": 0.7461,
    "H": 0.7432, "I": 0.2686, "J": 0.5708, "K": 0.6719, "L": 0.5654, "M": 0.9033, "N": 0.7534, "O": 0.7646,
    "P": 0.6387, "Q": 0.7646, "R": 0.6436, "S": 0.6416, "T": 0.6455, "U": 0.7441, "V": 0.6899, "W": 0.9854,
    "X": 0.6821, "Y": 0.6787, "Z": 0.6289, "[": 0.3647, "\\": 0.3604, "]": 0.3647, "^": 0.4712, "_": 0.4561,
    "`": 0.3228, "a": 0.5615, "b": 0.6123, "c": 0.5713, "d": 0.6123, "e": 0.583, "f": 0.3701, "g": 0.6133,
    "h": 0.5913, "i": 0.2422, "j": 0.2422, "k": 0.5488, "l": 0.2422, "m": 0.876, "n": 0.5908, "o": 0.5996,
    "p": 0.6123, "q": 0.6123, "r": 0.3765, "s": 0.5278, "t": 0.3271, "u": 0.5913, "v": 0.562, "w": 0.8184,
    "x": 0.5459, "y": 0.562, "z": 0.5522, "{": 0.4263, "|": 0.3325, "}": 0.4263, "~": 0.6616, "—": 1,
    "–": 0.5, "•": 0.5625, "━": 0.6021, "’": 0.2607, "‘": 0.2607, "“": 0.4404, "”": 0.4404, "×": 0.6616,
    "≈": 0.6616, "÷": 0.6616, "→": 0.9541, "←": 0.9541, "−": 0.6616, "é": 0.583, "è": 0.583, "á": 0.5615,
    "í": 0.2422, "ó": 0.5996, "ú": 0.5913, "ñ": 0.5908, "ç": 0.5713, "ö": 0.5996, "ü": 0.5913, "ä": 0.5615,
    "É": 0.6011, "…": 0.8643, "·": 0.2881, "°": 0.4556, "½": 0.8472, "¼": 0.8022, "¾": 0.8818, "✓": 0.8843,
    "✔": 0.8379, "✕": 0.8379, "✗": 0.8862, "★": 1.0449, "☆": 1.0449, "№": 1.0923, "€": 0.6665, "£": 0.6108,
    "¢": 0.5713,
    },
    600: {
    " ": 0.252, "!": 0.3213, "\"": 0.5229, "#": 0.6436, "$": 0.6504, "%": 1.0044, "&": 0.6626, "'": 0.3257,
    "(": 0.373, ")": 0.373, "*": 0.5396, "+": 0.6729, ",": 0.3188, "-": 0.4653, ".": 0.3188, "/": 0.3789,
    "0": 0.6597, "1": 0.4229, "2": 0.623, "3": 0.6362, "4": 0.666, "5": 0.6289, "6": 0.6396, "7": 0.5762,
    "8": 0.6401, "9": 0.6396, ":": 0.3188, ";": 0.3291, "<": 0.6729, "=": 0.6729, ">": 0.6729, "?": 0.5435,
    "@": 0.999, "A": 0.7275, "B": 0.6592, "C": 0.7368, "D": 0.7222, "E": 0.6055, "F": 0.5879, "G": 0.749,
    "H": 0.7456, "I": 0.2769, "J": 0.5796, "K": 0.7031, "L": 0.5654, "M": 0.9224, "N": 0.7593, "O": 0.7686,
    "P": 0.645, "Q": 0.7729, "R": 0.6523, "S": 0.6504, "T": 0.6602, "U": 0.7358, "V": 0.7275, "W": 1.02,
    "X": 0.7197, "Y": 0.7134, "Z": 0.6523, "[": 0.373, "\\": 0.3789, "]": 0.373, "^": 0.4814, "_": 0.4692,
    "`": 0.3511, "a": 0.5742, "b": 0.624, "c": 0.5825, "d": 0.624, "e": 0.5913, "f": 0.3887, "g": 0.6255,
    "h": 0.6123, "i": 0.2617, "j": 0.2617, "k": 0.5693, "l": 0.2617, "m": 0.9004, "n": 0.6118, "o": 0.6089,
    "p": 0.624, "q": 0.624, "r": 0.397, "s": 0.5493, "t": 0.353, "u": 0.6123, "v": 0.5869, "w": 0.8394,
    "x": 0.5688, "y": 0.5884, "z": 0.5659, "{": 0.4546, "|": 0.3589, "}": 0.4546, "~": 0.6729, "—": 1,
    "–": 0.5, "•": 0.5034, "━": 0.6021, "’": 0.2939, "‘": 0.2939, "“": 0.5068, "”": 0.5015, "×": 0.6729,
    "≈": 0.6729, "÷": 0.6729, "→": 0.9541, "←": 0.9541, "−": 0.6729, "é": 0.5913, "è": 0.5913, "á": 0.5742,
    "í": 0.2617, "ó": 0.6089, "ú": 0.6123, "ñ": 0.6118, "ç": 0.5825, "ö": 0.6089, "ü": 0.6123, "ä": 0.5742,
    "É": 0.6055, "…": 0.9561, "·": 0.3188, "°": 0.458, "½": 0.8696, "¼": 0.8311, "¾": 0.9072, "✓": 0.8828,
    "✔": 0.8379, "✕": 0.8379, "✗": 0.8843, "★": 1.0449, "☆": 1.0449, "№": 1.0986, "€": 0.6787, "£": 0.6294,
    "¢": 0.5825,
    },
}
EMOJI_EM = 1.375   # Discord draws emoji at 1.375em
UNKNOWN_EM = 0.65


def _char_em(ch: str, weight: int) -> float:
    table = _WIDTH[weight]
    if ch in table:
        return table[ch]
    cp = ord(ch)
    if cp in (0x200B, 0x200D, 0xFE0F, 0xFE0E) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0.0
    if cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF:
        return EMOJI_EM
    return UNKNOWN_EM


def plain(text: str) -> str:
    """Text as Discord shows it: markdown markers removed, mentions as names."""
    text = re.sub(r"<a?:(\w+):\d+>", "\U0001F3D2", text)        # custom emoji
    text = re.sub(r"<@[!&]?\d+>", "@Franchise Owner", text)       # user/role mention
    text = re.sub(r"<#\d+>", "#channel-name", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\*\*|__|~~|`|\*", "", text).strip()


def width(text: str, size: int = 14, weight: int = 600) -> float:
    return sum(_char_em(ch, weight) for ch in plain(text)) * size


def problems(embeds: list[dict], rel: str | None = None) -> tuple[list[str], list[str]]:
    """(errors, notes) for one message. Notes are allowed but worth knowing."""
    errors: list[str] = []
    notes: list[str] = []
    for i, e in enumerate(embeds, 1):
        title = e.get("title") or ""
        if title:
            w = width(title, 16)
            if w > NARROW_DESKTOP:
                errors.append(f"embed {i}: title wraps on desktop with the member list and on tablets "
                              f"({w:.0f} of {NARROW_DESKTOP}): {title}")
            elif w > PHONE:
                notes.append(f"embed {i}: title takes two lines on phones: {title}")
        footer = ((e.get("footer") or {}).get("text") or "").strip("\u200b")
        if footer and width(footer, 12) > PHONE:
            notes.append(f"embed {i}: footer takes two lines on phones: {footer}")
        for f in e.get("fields") or []:
            name = f.get("name") or ""
            if f.get("inline"):
                errors.append(f"embed {i}: field '{plain(name)}' is inline; phones stack inline fields, so use one field")
            if name and plain(name) not in ("", "\u200b"):
                w = width(name, 14)
                if w > PHONE:
                    errors.append(f"embed {i}: field name wraps on phones ({w:.0f} of {PHONE}): {plain(name)}")
    return errors, notes


def main() -> None:
    """Print the phone notes for every template (python tools/discord_layout.py)."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "templates"
    total = 0
    for path in sorted(root.rglob("*.json")):
        errors, notes = problems(json.loads(path.read_text(encoding="utf-8"))["embeds"])
        for line in errors + notes:
            print(f"{path.relative_to(root).as_posix()}: {line}")
            total += 1
    print(f"{total} notes")


if __name__ == "__main__":
    main()
