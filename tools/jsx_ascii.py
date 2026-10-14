"""Escape non-ASCII characters in the code of the kit's .jsx files (comments are left alone).

After Effects reads a .jsx without a byte-order mark in the system's legacy encoding, so a bullet
or a curly quote typed straight into a string would come out garbled there. \\uXXXX escapes read
the same everywhere. usage: python3 jsx_ascii.py FILE... (rewrites in place; --check only reports)
"""
import sys
from pathlib import Path


def escape(text: str) -> str:
    out = []
    for line in text.split("\n"):
        i = line.find("//")
        code, com = (line, "") if i < 0 else (line[:i], line[i:])
        out.append("".join(ch if ord(ch) < 128 else "\\u%04x" % ord(ch) for ch in code) + com)
    return "\n".join(out)


if __name__ == "__main__":
    check = "--check" in sys.argv
    bad = 0
    for f in (a for a in sys.argv[1:] if a != "--check"):
        p = Path(f)
        s = p.read_text(encoding="utf-8")
        e = escape(s)
        if e != s:
            bad += 1
            if not check:
                p.write_text(e, encoding="utf-8")
            print(("needs escaping: " if check else "escaped: ") + f)
    sys.exit(1 if check and bad else 0)
