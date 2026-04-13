"""Migrate financial_data (2022-2026) from SQLite to Hetzner PostgreSQL."""

import io, os, csv, time, sqlite3, psycopg2

HETZNER_URL = "postgresql://leadpeek:${HETZNER_PG_PASS}@62.238.14.150:5432/leadpeek"
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000
MIN_YEAR = 2022

def main():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(HETZNER_URL, keepalives=1, keepalives_idle=30)
    pg_conn.autocommit = False

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM financial_data WHERE fiscal_year >= {MIN_YEAR}").fetchone()[0]
    print(f"Financial_data (>= {MIN_YEAR}): {total:,} rows")

    # Resume from where we left off (don't truncate)
    pg_conn.autocommit = True
    cur = pg_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM financial_data")
    existing = cur.fetchone()[0]
    if existing >= total:
        print(f"Already complete ({existing:,} rows). Skipping.")
        return
    if existing > 0:
        print(f"Resuming from {existing:,} rows (skipping already loaded)...")
    pg_conn.autocommit = False

    columns = ["enterprise_number", "deposit_key", "fiscal_year", "deposit_date",
               "filing_model", "rubric_code", "period", "value"]
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY financial_data ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    start = time.time()
    offset = existing  # Resume from where we left off
    copied = 0

    while offset < total:
        rows = sqlite_conn.execute(
            f"SELECT * FROM financial_data WHERE fiscal_year >= {MIN_YEAR} LIMIT {CHUNK} OFFSET {offset}"
        ).fetchall()
        if not rows: break

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(["\\N" if v is None else v for v in row])
        buf.seek(0)
        pg_conn.cursor().copy_expert(copy_sql, buf)
        pg_conn.commit()

        copied += len(rows)
        offset += CHUNK
        elapsed = time.time() - start
        rate = copied / elapsed if elapsed > 0 else 0
        print(f"  {copied:,}/{total:,} ({copied/total*100:.0f}%) -- {rate:,.0f} rows/s", flush=True)

    elapsed = time.time() - start
    print(f"\nDone: {copied:,} rows in {elapsed:.0f}s")

    pg_conn.autocommit = True
    pg_conn.cursor().execute("ANALYZE financial_data")
    print("ANALYZE complete")
    pg_conn.close()
    sqlite_conn.close()

if __name__ == "__main__":
    main()
