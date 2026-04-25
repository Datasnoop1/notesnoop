"""One-shot rebrand sweep: indigo Tailwind classes -> teal brand tokens.

Runs across the frontend, applies a longest-match-first list of literal
swaps, prints the per-file change count. Excludes:

- showcase/page.tsx (deleted in Phase 4)
- globals.css (already migrated; remaining indigo is in a doc comment)
- network-graph.tsx (semantic colour encoding — handled separately)

Idempotent: re-runs are safe (already-migrated files match nothing).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

EXCLUDE = {
    "frontend/src/app/showcase/page.tsx",
    "frontend/src/app/globals.css",
}

# Order matters: composite patterns (longer matches) MUST come before
# their constituent shorter patterns to avoid double-rewrites.
REPLACEMENTS: list[tuple[str, str]] = [
    # Composite (focus + ring + border in one class)
    ("focus:ring-indigo-500/20 focus:border-indigo-400",
     "focus:ring-brand/20 focus:border-brand/60"),
    ("bg-indigo-100 text-indigo-700",
     "bg-brand-soft text-[color:var(--brand-ink)]"),
    ("bg-indigo-100 text-indigo-600",
     "bg-brand-soft text-brand"),
    ("bg-indigo-50 text-indigo-700",
     "bg-brand-soft text-[color:var(--brand-ink)]"),
    ("bg-indigo-50 text-indigo-600",
     "bg-brand-soft text-brand"),
    # Borders
    ("border-indigo-100", "border-brand/20"),
    ("border-indigo-200", "border-brand/30"),
    ("border-indigo-300", "border-brand/40"),
    ("border-indigo-400", "border-brand/60"),
    ("border-indigo-500", "border-brand"),
    ("border-indigo-600", "border-brand"),
    ("border-indigo-700", "border-[color:var(--brand-ink)]"),
    # Rings
    ("ring-indigo-500/20", "ring-brand/20"),
    ("ring-indigo-500", "ring-brand"),
    ("ring-indigo-400", "ring-brand/60"),
    ("ring-indigo-300", "ring-brand/40"),
    # Decoration
    ("decoration-indigo-200", "decoration-brand/30"),
    ("decoration-indigo-300", "decoration-brand/40"),
    # Hover variants
    ("hover:bg-indigo-50/30", "hover:bg-brand-soft/30"),
    ("hover:bg-indigo-50", "hover:bg-brand-soft/60"),
    ("hover:bg-indigo-100", "hover:bg-brand-soft"),
    ("hover:bg-indigo-200", "hover:bg-brand-soft"),
    ("hover:bg-indigo-500", "hover:bg-brand"),
    ("hover:bg-indigo-600", "hover:bg-brand"),
    ("hover:bg-indigo-700", "hover:bg-[color:var(--brand-ink)]"),
    ("hover:text-indigo-300", "hover:text-brand/40"),
    ("hover:text-indigo-400", "hover:text-brand/60"),
    ("hover:text-indigo-500", "hover:text-brand"),
    ("hover:text-indigo-600", "hover:text-brand"),
    ("hover:text-indigo-700", "hover:text-[color:var(--brand-ink)]"),
    ("hover:text-indigo-800", "hover:text-[color:var(--brand-ink)]"),
    ("hover:text-indigo-900", "hover:text-[color:var(--brand-ink)]"),
    ("hover:border-indigo-200", "hover:border-brand/30"),
    ("hover:border-indigo-300", "hover:border-brand/40"),
    ("hover:border-indigo-400", "hover:border-brand/60"),
    ("hover:border-indigo-500", "hover:border-brand"),
    # Focus
    ("focus:border-indigo-400", "focus:border-brand/60"),
    ("focus:border-indigo-500", "focus:border-brand"),
    ("focus:ring-indigo-500", "focus:ring-brand"),
    ("focus:ring-indigo-400", "focus:ring-brand/60"),
    # Group hover
    ("group-hover:text-indigo-600", "group-hover:text-brand"),
    ("group-hover:text-indigo-500", "group-hover:text-brand"),
    ("group-hover:bg-indigo-50", "group-hover:bg-brand-soft/60"),
    ("group-hover:bg-indigo-600", "group-hover:bg-brand"),
    # Standalone (shortest last)
    ("bg-indigo-50/30", "bg-brand-soft/30"),
    ("bg-indigo-50/60", "bg-brand-soft/60"),
    ("bg-indigo-50", "bg-brand-soft"),
    ("bg-indigo-100", "bg-brand-soft"),
    ("bg-indigo-200", "bg-brand-soft"),
    ("bg-indigo-300", "bg-brand/40"),
    ("bg-indigo-400", "bg-brand/60"),
    ("bg-indigo-500", "bg-brand"),
    ("bg-indigo-600", "bg-brand"),
    ("bg-indigo-700", "bg-[color:var(--brand-ink)]"),
    ("text-indigo-300", "text-brand/40"),
    ("text-indigo-400", "text-brand/60"),
    ("text-indigo-500", "text-brand"),
    ("text-indigo-600", "text-brand"),
    ("text-indigo-700", "text-[color:var(--brand-ink)]"),
    ("text-indigo-800", "text-[color:var(--brand-ink)]"),
    ("text-indigo-900", "text-[color:var(--brand-ink)]"),
    ("from-indigo-400", "from-brand/60"),
    ("from-indigo-500", "from-brand"),
    ("from-indigo-600", "from-brand"),
    ("to-indigo-400", "to-brand/60"),
    ("to-indigo-500", "to-brand"),
    ("to-indigo-600", "to-brand"),
    ("via-indigo-500", "via-brand"),
    # border directional
    ("border-l-indigo-500", "border-l-brand"),
    ("border-l-indigo-600", "border-l-brand"),
    ("border-r-indigo-500", "border-r-brand"),
    ("border-t-indigo-500", "border-t-brand"),
    ("border-b-indigo-500", "border-b-brand"),
    # ring 100/200 (added second pass)
    ("ring-2 ring-indigo-200", "ring-2 ring-brand/30"),
    ("ring-1 ring-indigo-100", "ring-1 ring-brand/20"),
    ("ring-indigo-200", "ring-brand/30"),
    ("ring-indigo-100", "ring-brand/20"),
    # gradient stops
    ("from-indigo-50", "from-brand-soft"),
    ("from-indigo-100", "from-brand-soft"),
    ("to-indigo-50/50", "to-brand-soft/50"),
    ("to-indigo-50", "to-brand-soft"),
    ("to-indigo-100", "to-brand-soft"),
    ("via-indigo-50", "via-brand-soft"),
    # focus ring 200
    ("focus:ring-indigo-200", "focus:ring-brand/30"),
    ("focus:ring-indigo-100", "focus:ring-brand/20"),
    # hover decoration
    ("hover:decoration-indigo-500", "hover:decoration-brand"),
    ("hover:decoration-indigo-600", "hover:decoration-brand"),
    ("hover:decoration-indigo-400", "hover:decoration-brand/60"),
]

# Sanity: any remaining indigo-* class after sweep is a miss.
INDIGO_RE = re.compile(r"\bindigo-\d+\b")


def transform(text: str) -> tuple[str, int]:
    total = 0
    for old, new in REPLACEMENTS:
        new_text, n = text, text.count(old)
        if n:
            new_text = text.replace(old, new)
            total += n
            text = new_text
    return text, total


def main() -> int:
    files = list(FRONTEND.rglob("*.tsx")) + list(FRONTEND.rglob("*.ts")) \
        + list(FRONTEND.rglob("*.css"))
    files = [f for f in files if "node_modules" not in f.parts]
    grand_total = 0
    grand_files = 0
    leftover_files: list[Path] = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if rel in EXCLUDE:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "indigo-" not in text:
            continue
        new_text, n = transform(text)
        if n:
            f.write_text(new_text, encoding="utf-8", newline="\n")
            print(f"{n:4d}  {rel}")
            grand_total += n
            grand_files += 1
        leftover = INDIGO_RE.findall(new_text)
        if leftover:
            leftover_files.append(f)
    print(f"\ntotal: {grand_total} replacements across {grand_files} files")
    if leftover_files:
        print(f"\nfiles with un-rewritten indigo classes ({len(leftover_files)}):")
        for f in leftover_files:
            rel = f.relative_to(ROOT).as_posix()
            misses = INDIGO_RE.findall(f.read_text(encoding="utf-8"))
            print(f"  {rel}: {sorted(set(misses))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
