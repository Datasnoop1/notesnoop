"""One-time migration: SQLite -> Supabase PostgreSQL.

Reads from the local SQLite database and bulk-loads into PostgreSQL
using COPY FROM for maximum throughput. Resumable — compares row counts
and re-migrates tables that are incomplete.

Usage:
    python scripts/migrate_sqlite_to_pg.py              # all tables
    python scripts/migrate_sqlite_to_pg.py --table activity  # single table
"""

import io
import os
import sys
import csv
import time
import sqlite3
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()

import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")

# Tables in foreign-key-safe order
TABLES = [
    "meta",
    "enterprise",
    "establishment",
    "denomination",
    "address",
    "activity",
    "contact",
    "branch",
    "code",
    "kbo_extract_log",
    "financial_data",
    "nbb_load_log",
    "staatsblad_publication",
    "administrator",
    "participating_interest",
    "shareholder",
    "financial_latest",
    "financial_by_year",
    "company_info",
    "nace_lookup",
    "favourite",
    "feedback",
]

CHUNK_SIZE = 50_000  # rows per COPY batch


def pg_connect():
    """Connect to PostgreSQL with TCP keepalive for long-running uploads."""
    conn = psycopg2.connect(
        DATABASE_URL,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = off")
    cur.close()
    conn.autocommit = False
    return conn


def get_columns(sqlite_conn, table):
    """Get column names for a SQLite table."""
    cur = sqlite_conn.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cur.fetchall()]


def migrate_table(sqlite_conn, pg_conn, table):
    """Migrate a single table from SQLite to PostgreSQL using COPY."""
    # Check if table exists in PG
    pg_cur = pg_conn.cursor()
    pg_cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s)",
        (table,),
    )
    if not pg_cur.fetchone()[0]:
        print(f"  SKIP {table} -- not in PostgreSQL schema")
        return 0

    # Count rows in SQLite
    total_rows = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    if total_rows == 0:
        print(f"  SKIP {table} -- empty in SQLite")
        return 0

    # Compare row counts — truncate + re-migrate if partial
    pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    existing = pg_cur.fetchone()[0]
    if existing == total_rows:
        print(f"  SKIP {table} -- already complete ({existing:,} rows)")
        return existing
    elif existing > 0:
        print(f"  TRUNCATE {table} -- partial ({existing:,}/{total_rows:,}), re-migrating...")
        pg_conn.rollback()
        pg_conn.autocommit = True
        pg_cur.execute(f'TRUNCATE "{table}" CASCADE')
        pg_conn.autocommit = False

    # Get columns from SQLite
    columns = get_columns(sqlite_conn, table)
    if not columns:
        print(f"  SKIP {table} -- no columns found in SQLite")
        return 0

    print(f"  COPY {table}: {total_rows:,} rows ...", end="", flush=True)
    start = time.time()

    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f'COPY "{table}" ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL \'\\N\')'

    # Stream from SQLite in chunks
    offset = 0
    total_copied = 0

    while offset < total_rows:
        rows = sqlite_conn.execute(
            f"SELECT * FROM [{table}] LIMIT {CHUNK_SIZE} OFFSET {offset}"
        ).fetchall()

        if not rows:
            break

        # Write to CSV buffer
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(
                ["\\N" if v is None else v for v in row]
            )

        buf.seek(0)
        pg_cur.copy_expert(copy_sql, buf)
        pg_conn.commit()

        total_copied += len(rows)
        offset += CHUNK_SIZE

        # Progress
        pct = total_copied / total_rows * 100
        elapsed = time.time() - start
        rate = total_copied / elapsed if elapsed > 0 else 0
        print(f"\r  COPY {table}: {total_copied:,}/{total_rows:,} ({pct:.0f}%) -- {rate:,.0f} rows/s   ", end="", flush=True)

    elapsed = time.time() - start
    rate = total_copied / elapsed if elapsed > 0 else 0
    print(f"\r  COPY {table}: {total_copied:,} rows in {elapsed:.1f}s ({rate:,.0f} rows/s)          ")

    return total_copied


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--table", help="Migrate only this table")
    args = parser.parse_args()

    print("=" * 60)
    print("SQLite -> Supabase PostgreSQL Migration")
    print("=" * 60)
    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {DATABASE_URL[:40]}...")
    if args.table:
        print(f"Table:  {args.table}")
    print()

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite file not found: {SQLITE_PATH}")
        sys.exit(1)

    # Connect to both databases
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = pg_connect()

    # Check which SQLite tables exist
    sqlite_tables = {
        r[0]
        for r in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    tables_to_migrate = [args.table] if args.table else TABLES

    total_start = time.time()
    total_migrated = 0

    for table in tables_to_migrate:
        if table not in sqlite_tables:
            print(f"  SKIP {table} -- not in SQLite")
            continue
        try:
            count = migrate_table(sqlite_conn, pg_conn, table)
            total_migrated += count
        except Exception as e:
            pg_conn.rollback()
            print(f"\n  ERROR on {table}: {e}")
            print("  Continuing with next table...")

    total_elapsed = time.time() - total_start

    print()
    print("=" * 60)
    print(f"Migration complete in {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print(f"Total rows migrated: {total_migrated:,}")
    print("=" * 60)

    # Verification: compare row counts
    print()
    print("Verifying row counts...")
    mismatches = 0
    for table in tables_to_migrate:
        if table not in sqlite_tables:
            continue
        try:
            sq_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            pg_cur = pg_conn.cursor()
            pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            pg_count = pg_cur.fetchone()[0]
            status = "OK" if sq_count == pg_count else "MISMATCH"
            if sq_count != pg_count:
                mismatches += 1
            if sq_count > 0:
                print(f"  {table}: SQLite={sq_count:,} PG={pg_count:,} [{status}]")
        except Exception as e:
            pg_conn.rollback()
            print(f"  {table}: ERROR -- {e}")

    if mismatches:
        print(f"\nWARNING: {mismatches} table(s) have row count mismatches!")
    else:
        print("\nAll row counts match!")

    # Run ANALYZE for query planning
    print("\nRunning ANALYZE on all tables...")
    try:
        pg_conn.rollback()  # clear any failed transaction state
        pg_conn.autocommit = True
        pg_cur = pg_conn.cursor()
        pg_cur.execute("ANALYZE")
        print("ANALYZE complete.")
    except Exception as e:
        print(f"ANALYZE failed (non-critical): {e}")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
