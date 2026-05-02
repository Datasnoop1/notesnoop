#!/usr/bin/env python3
"""Validate that every live public table has a staging scrub classification."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CLASSES = {
    "public_reference",
    "derived_rebuildable",
    "user_state",
    "secret",
    "business_state",
}

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRUB = REPO_ROOT / "scripts" / "staging_scrub.sql"


def parse_inventory(path: Path) -> dict[str, str]:
    in_block = False
    inventory: dict[str, str] = {}
    duplicates: list[str] = []
    invalid: list[str] = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "-- SCRUB_INVENTORY_BEGIN":
            in_block = True
            continue
        if line == "-- SCRUB_INVENTORY_END":
            in_block = False
            break
        if not in_block:
            continue

        match = re.match(r"--\s*([a-z_]+):\s*(.*)$", line)
        if not match:
            continue
        klass, rest = match.groups()
        if klass not in CLASSES:
            invalid.append(klass)
            continue
        for table in [part.strip() for part in rest.split(",") if part.strip()]:
            if not re.match(r"^[a-z][a-z0-9_]*$", table):
                invalid.append(f"{klass}:{table}")
                continue
            if table in inventory and inventory[table] != klass:
                duplicates.append(table)
            inventory[table] = klass

    if invalid:
        raise SystemExit(f"Invalid scrub inventory entries: {', '.join(sorted(set(invalid)))}")
    if duplicates:
        raise SystemExit(f"Tables classified more than once: {', '.join(sorted(set(duplicates)))}")
    if not inventory:
        raise SystemExit(f"No scrub inventory found in {path}")
    return inventory


def tables_from_database(database_url: str) -> set[str]:
    try:
        import psycopg2
    except ImportError as exc:
        raise SystemExit("psycopg2 is required when --database-url is used") from exc

    conn = psycopg2.connect(
        database_url,
        connect_timeout=10,
        application_name="datasnoop:check-scrub-inventory",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
                """
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def tables_from_schema(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {
        match.group(1)
        for match in re.finditer(
            r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:public\.)?([a-z][a-z0-9_]*)\b",
            text,
            flags=re.IGNORECASE,
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scrub-file", type=Path, default=DEFAULT_SCRUB)
    parser.add_argument("--database-url", help="Database URL to inspect; value is never printed")
    parser.add_argument("--schema-file", type=Path, help="Optional schema SQL fallback for local checks")
    args = parser.parse_args()

    inventory = parse_inventory(args.scrub_file)

    live_tables: set[str] = set()
    source = ""
    if args.database_url:
        live_tables = tables_from_database(args.database_url)
        source = "database"
    elif args.schema_file:
        live_tables = tables_from_schema(args.schema_file)
        source = str(args.schema_file)
    else:
        source = "inventory-only"

    missing = sorted(live_tables - set(inventory))
    if missing:
        print("Unclassified public tables:", file=sys.stderr)
        for table in missing:
            print(f"  {table}", file=sys.stderr)
        return 1

    print(f"scrub_inventory_tables={len(inventory)}")
    print(f"checked_source={source}")
    print(f"checked_tables={len(live_tables)}")
    print("scrub_inventory_status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
