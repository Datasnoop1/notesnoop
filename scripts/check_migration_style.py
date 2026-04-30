#!/usr/bin/env python3
"""Lint DataSnoop migration files for the Week-1c safety contract."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import migrate  # noqa: E402


def header_values(path: Path) -> list[str]:
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines()[:20]:
        match = migrate.HEADER_RE.match(line)
        if match:
            values.append(match.group("value").strip())
    return values


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    values = header_values(path)
    lower_values = [value.lower() for value in values]

    if not any(value in {"tx", "no-tx"} for value in lower_values):
        errors.append("missing `-- @migration: tx` or `-- @migration: no-tx` header")
    if not any(value.startswith("lock_timeout=") for value in lower_values):
        errors.append("missing `-- @migration: lock_timeout=...` header")
    if not any(value.startswith("statement_timeout=") for value in lower_values):
        errors.append("missing `-- @migration: statement_timeout=...` header")

    try:
        migrate.parse_migration(path)
    except SystemExit as exc:
        errors.append(str(exc))

    return errors


def main() -> int:
    failures: list[tuple[Path, list[str]]] = []
    for path in migrate.migration_files():
        errors = lint_file(path)
        if errors:
            failures.append((path, errors))

    if failures:
        for path, errors in failures:
            rel = path.relative_to(REPO_ROOT)
            for error in errors:
                print(f"{rel}: {error}", file=sys.stderr)
        return 1

    print("Migration style check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
