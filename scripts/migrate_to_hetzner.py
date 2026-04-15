"""Migrate from local SQLite directly to Hetzner PostgreSQL."""

import io
import os
import csv
import time
import sqlite3
import sys

import psycopg2

HETZNER_URL = "postgresql://datasnoop:${HETZNER_PG_PASS}@62.238.14.150:5432/datasnoop"
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000

TABLES = [
    "meta", "enterprise", "establishment", "denomination", "address",
    "contact", "branch", "code", "kbo_extract_log",
    "nbb_load_log", "staatsblad_publication",
    "shareholder", "participating_interest",
    "financial_latest", "financial_by_year", "company_info", "nace_lookup",
]

# Administrator has no PK constraint (duplicates in source)
TABLES_NO_PK = ["administrator"]


def get_columns(sqlite_conn, table):
    cur = sqlite_conn.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cur.fetchall()]


def migrate_table(sqlite_conn, pg_conn, table):
    pg_cur = pg_conn.cursor()

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    if total == 0:
        print(f"  SKIP {table} (empty)")
        return 0

    # Check if already loaded
    pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    existing = pg_cur.fetchone()[0]
    if existing >= total:
        print(f"  SKIP {table} (already {existing:,} rows)")
        return existing

    if existing > 0:
        pg_conn.rollback()
        pg_conn.autocommit = True
        pg_cur.execute(f'TRUNCATE "{table}" CASCADE')
        pg_conn.autocommit = False

    columns = get_columns(sqlite_conn, table)
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY "{table}" ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    print(f"  COPY {table}: {total:,} rows", end="", flush=True)
    start = time.time()
    offset = 0
    copied = 0

    while offset < total:
        rows = sqlite_conn.execute(
            f"SELECT * FROM [{table}] LIMIT {CHUNK} OFFSET {offset}"
        ).fetchall()
        if not rows:
            break

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(["\\N" if v is None else v for v in row])

        buf.seek(0)
        pg_cur.copy_expert(copy_sql, buf)
        pg_conn.commit()

        copied += len(rows)
        offset += CHUNK
        elapsed = time.time() - start
        rate = copied / elapsed if elapsed > 0 else 0
        print(f"\r  COPY {table}: {copied:,}/{total:,} ({copied/total*100:.0f}%) -- {rate:,.0f} rows/s   ", end="", flush=True)

    elapsed = time.time() - start
    rate = copied / elapsed if elapsed > 0 else 0
    print(f"\r  COPY {table}: {copied:,} rows in {elapsed:.1f}s ({rate:,.0f} rows/s)          ")
    return copied


def main():
    print("=" * 50)
    print("SQLite -> Hetzner PostgreSQL Migration")
    print("=" * 50)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(HETZNER_URL, keepalives=1, keepalives_idle=30)
    pg_conn.autocommit = False

    total_start = time.time()

    for table in TABLES + TABLES_NO_PK:
        try:
            migrate_table(sqlite_conn, pg_conn, table)
        except Exception as e:
            pg_conn.rollback()
            print(f"\n  ERROR {table}: {e}")

    print(f"\nDone in {time.time() - total_start:.0f}s")

    # ANALYZE
    pg_conn.autocommit = True
    pg_cur = pg_conn.cursor()
    print("Running ANALYZE...")
    pg_cur.execute("ANALYZE")
    print("ANALYZE complete.")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
