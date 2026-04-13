"""Migrate financial_data (2022-2026) from SQLite to Hetzner PostgreSQL.
Uses rowid-based pagination to avoid slow OFFSET at large row counts."""

import io, os, csv, time, sqlite3, psycopg2

HETZNER_URL = os.getenv("HETZNER_PG_URL", "postgresql://leadpeek:DatasnoopDB2026@62.238.14.150:5432/leadpeek")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000
MIN_YEAR = 2022

def main():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(HETZNER_URL, keepalives=1, keepalives_idle=30)
    pg_conn.autocommit = False

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM financial_data WHERE fiscal_year >= {MIN_YEAR}").fetchone()[0]

    # Check existing count
    pg_conn.autocommit = True
    cur = pg_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM financial_data")
    existing = cur.fetchone()[0]

    if existing >= total:
        print(f"Already complete ({existing:,} rows). Skipping.")
        return

    print(f"Financial_data (>= {MIN_YEAR}): {total:,} total, {existing:,} already loaded")
    print(f"Need to load: {total - existing:,} more rows")
    pg_conn.autocommit = False

    columns = ["enterprise_number", "deposit_key", "fiscal_year", "deposit_date",
               "filing_model", "rubric_code", "period", "value"]
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY financial_data ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    # Use rowid-based pagination — much faster than OFFSET
    # Get the rowid to start from by skipping `existing` rows
    start_rowid = 0
    if existing > 0:
        row = sqlite_conn.execute(
            f"SELECT rowid FROM financial_data WHERE fiscal_year >= {MIN_YEAR} ORDER BY rowid LIMIT 1 OFFSET {existing}"
        ).fetchone()
        if row:
            start_rowid = row[0]
        else:
            print("Could not find start rowid. Already complete?")
            return
        print(f"Resuming from rowid {start_rowid}")

    start = time.time()
    copied = 0
    last_rowid = start_rowid

    while True:
        rows = sqlite_conn.execute(
            f"SELECT enterprise_number, deposit_key, fiscal_year, deposit_date, "
            f"filing_model, rubric_code, period, value FROM financial_data "
            f"WHERE fiscal_year >= {MIN_YEAR} AND rowid > ? ORDER BY rowid LIMIT ?",
            (last_rowid, CHUNK)
        ).fetchall()

        if not rows:
            break

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(["\\N" if v is None else v for v in row])
        buf.seek(0)

        try:
            pg_conn.cursor().copy_expert(copy_sql, buf)
            pg_conn.commit()
        except Exception as e:
            pg_conn.rollback()
            print(f"\nCOPY error: {e}")
            break

        copied += len(rows)
        # Track the last rowid for next batch
        last_rowid = sqlite_conn.execute(
            f"SELECT rowid FROM financial_data WHERE fiscal_year >= {MIN_YEAR} AND rowid > ? ORDER BY rowid LIMIT 1 OFFSET {len(rows) - 1}",
            (last_rowid,)
        ).fetchone()[0]

        elapsed = time.time() - start
        rate = copied / elapsed if elapsed > 0 else 0
        total_loaded = existing + copied
        pct = total_loaded / total * 100
        print(f"  +{copied:,} ({total_loaded:,}/{total:,}, {pct:.0f}%) -- {rate:,.0f} rows/s", flush=True)

    elapsed = time.time() - start
    print(f"\nDone: +{copied:,} rows in {elapsed:.0f}s")

    pg_conn.autocommit = True
    pg_conn.cursor().execute("ANALYZE financial_data")
    print("ANALYZE complete")
    pg_conn.close()
    sqlite_conn.close()

if __name__ == "__main__":
    main()
