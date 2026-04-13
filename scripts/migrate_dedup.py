"""Migrate tables with duplicate PKs via staging table + dedup."""

import io
import os
import csv
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv
load_dotenv()
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000


def migrate_dedup(table, pk_cols, columns):
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(
        DATABASE_URL, keepalives=1, keepalives_idle=30,
        keepalives_interval=10, keepalives_count=5,
    )
    pg_conn.autocommit = True
    cur = pg_conn.cursor()
    cur.execute("SET default_transaction_read_only = off")

    # Truncate target
    cur.execute(f'TRUNCATE "{table}"')

    # Create staging
    cur.execute(f"DROP TABLE IF EXISTS _staging_{table}")
    cur.execute(f'CREATE UNLOGGED TABLE _staging_{table} (LIKE "{table}")')
    pg_conn.autocommit = False

    # COPY into staging
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY _staging_{table} ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    print(f"Loading {table} into staging ({total:,} rows)...")

    offset = 0
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
        cur.copy_expert(copy_sql, buf)
        pg_conn.commit()
        offset += CHUNK
        print(f"  {min(offset, total):,}/{total:,}", flush=True)

    # Dedup into final table
    pk_str = ", ".join(pk_cols)
    print(f"Deduplicating into {table}...")
    cur.execute(f"""
        INSERT INTO "{table}"
        SELECT DISTINCT ON ({pk_str}) *
        FROM _staging_{table}
        ORDER BY {pk_str}
        ON CONFLICT DO NOTHING
    """)
    pg_conn.commit()

    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    final = cur.fetchone()[0]
    print(f"Final: {final:,} rows ({total - final:,} duplicates removed)")

    # Cleanup
    pg_conn.autocommit = True
    cur.execute(f"DROP TABLE _staging_{table}")
    cur.execute(f'ANALYZE "{table}"')
    print("Done.")

    pg_conn.close()
    sqlite_conn.close()


if __name__ == "__main__":
    table = sys.argv[1] if len(sys.argv) > 1 else "financial_by_year"

    TABLES = {
        "financial_by_year": {
            "pk": ["enterprise_number", "fiscal_year"],
            "cols": [
                "enterprise_number", "fiscal_year", "filing_model", "revenue",
                "ebit", "da", "ebitda", "net_profit", "equity",
                "lt_financial_debt", "st_financial_debt", "cash",
                "total_assets", "fte_total", "personnel_costs",
            ],
        },
    }

    if table not in TABLES:
        print(f"Unknown table: {table}")
        sys.exit(1)

    t = TABLES[table]
    migrate_dedup(table, t["pk"], t["cols"])
