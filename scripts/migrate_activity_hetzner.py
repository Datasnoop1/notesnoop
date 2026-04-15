"""Migrate activity table from SQLite to Hetzner PostgreSQL."""

import io, os, csv, time, sqlite3, psycopg2

HETZNER_URL = "postgresql://datasnoop:${HETZNER_PG_PASS}@62.238.14.150:5432/datasnoop"
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
CHUNK = 50_000

def main():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(HETZNER_URL, keepalives=1, keepalives_idle=30)
    pg_conn.autocommit = False

    total = sqlite_conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0]
    print(f"Activity: {total:,} rows")

    columns = ["entity_number", "activity_group", "nace_version", "nace_code", "classification"]
    cols_str = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"""COPY activity ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"""

    start = time.time()
    offset = 0
    copied = 0

    while offset < total:
        rows = sqlite_conn.execute(f"SELECT * FROM activity LIMIT {CHUNK} OFFSET {offset}").fetchall()
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
    pg_conn.cursor().execute("ANALYZE activity")
    print("ANALYZE complete")
    pg_conn.close()
    sqlite_conn.close()

if __name__ == "__main__":
    main()
