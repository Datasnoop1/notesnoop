"""Fix collateral from rebrand_indigo_sweep.py shortest-last bug.

The original sweep listed `bg-indigo-50` and `hover:bg-indigo-50` BEFORE
`bg-indigo-500` and `hover:bg-indigo-50/40` in the standalone block, so:

  bg-indigo-500             -> bg-brand-soft0  (broken; Tailwind drops it)
  hover:bg-indigo-50/40     -> hover:bg-brand-soft/60/40 (multi-slash, broken)
  hover:bg-indigo-50/50     -> hover:bg-brand-soft/60/50 (multi-slash, broken)

This script restores the intent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

FIXES: list[tuple[str, str]] = [
    # bg-brand-soft0 was bg-indigo-500 -> bg-brand
    ("bg-brand-soft0", "bg-brand"),
    # multi-slash hovers
    ("hover:bg-brand-soft/60/40", "hover:bg-brand-soft/40"),
    ("hover:bg-brand-soft/60/50", "hover:bg-brand-soft/50"),
    ("hover:bg-brand-soft/60/30", "hover:bg-brand-soft/30"),
    ("hover:bg-brand-soft/60/60", "hover:bg-brand-soft/60"),
    # network-graph centered-node + depth fallback hex literals (security review)
    ('"#4f46e5"', '"#0a5659"'),
    ('"#c7d2fe"', '"#5cb1b3"'),
]


def main() -> int:
    files = list(FRONTEND.rglob("*.tsx")) + list(FRONTEND.rglob("*.ts")) \
        + list(FRONTEND.rglob("*.css"))
    files = [f for f in files if "node_modules" not in f.parts]
    grand_total = 0
    grand_files = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = text
        for old, new in FIXES:
            new_text = new_text.replace(old, new)
        if new_text != text:
            f.write_text(new_text, encoding="utf-8", newline="\n")
            n = sum(text.count(old) for old, _ in FIXES if old in text)
            print(f"{n:4d}  {f.relative_to(ROOT).as_posix()}")
            grand_total += n
            grand_files += 1
    print(f"\ntotal: {grand_total} fixups across {grand_files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
