"""Migrate financial_data from SQLite to PostgreSQL, filtered to 2022-2026 only."""

import io
import os
import csv
import time
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv
load_dotenv()

import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000
MIN_YEAR = 2022


def main():
    print(f"Migrating financial_data (fiscal_year >= {MIN_YEAR})")
    print(f"Source: {SQLITE_PATH}")
    print()

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(
        DATABASE_URL, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=5,
    )
    pg_conn.autocommit = True
    cur = pg_conn.cursor()
    cur.execute("SET default_transaction_read_only = off")
    cur.execute("SET statement_timeout = 0")

    # Check current PG count
    cur.execute("SELECT COUNT(*) FROM financial_data")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"financial_data already has {existing:,} rows. Truncating...")
        cur.execute("TRUNCATE financial_data")

    pg_conn.autocommit = False

    # Count filtered rows in SQLite
    total = sqlite_conn.execute(
        f"SELECT COUNT(*) FROM financial_data WHERE fiscal_year >= {MIN_YEAR}"
    ).fetchone()[0]
    print(f"Rows to migrate: {total:,}")

    columns = [
        "enterprise_number", "deposit_key", "fiscal_year", "deposit_date",
        "filing_model", "rubric_code", "period", "value"
    ]
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY financial_data ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    start = time.time()
    offset = 0
    total_copied = 0

    while offset < total:
        rows = sqlite_conn.execute(
            f"SELECT * FROM financial_data WHERE fiscal_year >= {MIN_YEAR} "
            f"LIMIT {CHUNK} OFFSET {offset}"
        ).fetchall()

        if not rows:
            break

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(["\\N" if v is None else v for v in row])

        buf.seek(0)
        cur.copy_expert(copy_sql, buf)
        pg_conn.commit()

        total_copied += len(rows)
        offset += CHUNK

        elapsed = time.time() - start
        rate = total_copied / elapsed if elapsed > 0 else 0
        pct = total_copied / total * 100
        print(f"  {total_copied:,}/{total:,} ({pct:.0f}%) -- {rate:,.0f} rows/s", flush=True)

    elapsed = time.time() - start
    rate = total_copied / elapsed if elapsed > 0 else 0
    print(f"\nDone: {total_copied:,} rows in {elapsed:.0f}s ({rate:,.0f} rows/s)")

    # Verify
    cur.execute("SELECT COUNT(*) FROM financial_data")
    pg_count = cur.fetchone()[0]
    print(f"Verified: {pg_count:,} rows in PostgreSQL")

    # ANALYZE
    pg_conn.rollback()
    pg_conn.autocommit = True
    cur.execute("ANALYZE financial_data")
    print("ANALYZE complete.")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
