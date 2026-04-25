"""Daily pipeline orchestrator — KBO update + NBB financial data ingest.

Designed to run via Windows Task Scheduler or cron.

Steps:
  1. Find and apply any new KBO update ZIPs in the data/ folder
  2. Download and ingest NBB JSON filings published yesterday (daily extract)
  3. Log a summary

Usage:
    python src/pipeline.py                    # run full daily pipeline
    python src/pipeline.py --kbo-only         # KBO update only
    python src/pipeline.py --nbb-only         # NBB ingest only
    python src/pipeline.py --nbb-date 2024-01-15   # specific NBB date
    python src/pipeline.py --dry-run          # log without writing
"""

import argparse
import glob
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

DEFAULT_DB  = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
DEFAULT_DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def section(title):
    log(f"{'='*60}")
    log(f"  {title}")
    log(f"{'='*60}")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# ---------------------------------------------------------------------------
# KBO update step
# ---------------------------------------------------------------------------

def find_update_zips(data_dir):
    """Find KBO update ZIPs in data/, sorted by extract number."""
    pattern = os.path.join(data_dir, "KboOpenData_*_Update.zip")
    zips = glob.glob(pattern)

    def extract_num(path):
        m = re.search(r"KboOpenData_(\d+)_", os.path.basename(path))
        return int(m.group(1)) if m else 0

    return sorted(zips, key=extract_num)


def run_kbo_update(conn, data_dir, dry_run=False):
    section("KBO Update")

    zips = find_update_zips(data_dir)
    if not zips:
        log("No KBO update ZIPs found in data/")
        return 0

    # Filter to only unapplied extracts
    applied = {
        row[0] for row in
        conn.execute("SELECT extract_number FROM kbo_extract_log").fetchall()
    }

    pending = []
    for z in zips:
        m = re.search(r"KboOpenData_(\d+)_", os.path.basename(z))
        num = int(m.group(1)) if m else None
        if num and num not in applied:
            pending.append(z)

    if not pending:
        log("All KBO update ZIPs already applied")
        return 0

    log(f"Applying {len(pending)} update ZIP(s)")

    if dry_run:
        for z in pending:
            log(f"  [dry-run] Would apply {os.path.basename(z)}")
        return len(pending)

    sys.path.insert(0, os.path.dirname(__file__))
    from kbo_updater import process_zip

    applied_count = 0
    for z in pending:
        log(f"Applying {os.path.basename(z)}")
        try:
            if process_zip(conn, z):
                applied_count += 1
        except Exception as e:
            log(f"  ERROR: {e}")

    log(f"KBO update done — {applied_count}/{len(pending)} applied")
    return applied_count


# ---------------------------------------------------------------------------
# NBB daily extract step
# ---------------------------------------------------------------------------

def run_nbb_extract(conn, target_date, dry_run=False):
    section(f"NBB Daily Extract — {target_date}")

    sys.path.insert(0, os.path.dirname(__file__))
    from nbb_client import NBBClient, NBBError
    from nbb_loader import load_daily_extract

    client = NBBClient()
    try:
        load_daily_extract(conn, client, target_date, dry_run=dry_run)
    except NBBError as e:
        log(f"NBB API error: {e} — check NBB_API_KEY in .env")
    except Exception as e:
        log(f"NBB extract failed: {e}")


# ---------------------------------------------------------------------------
# NBB catch-up: load financials for companies missing from financial_data
# ---------------------------------------------------------------------------

def run_nbb_catchup(conn, limit=100, since_year=None, dry_run=False, workers=5):
    """Load financials for active companies that have no NBB data yet.

    Useful after the initial KBO load to bootstrap financial coverage.
    Processes `limit` companies per run using `workers` parallel threads.
    """
    section(f"NBB Catch-up (up to {limit} companies, {workers} workers)")

    sys.path.insert(0, os.path.dirname(__file__))
    from nbb_client import NBBClient, NBBError
    from nbb_loader import load_company

    db_path = conn.execute("PRAGMA database_list").fetchone()[2]

    # Active companies without financial data — target commercial legal forms
    # that must file annual accounts with the NBB:
    #   610 = BV (new form since 2019 CCA)
    #   014 = NV (naamloze vennootschap)
    #   015 = BVBA (old form of BV, pre-2019)
    #   016 = CV (coöperatieve vennootschap, old)
    #   008 = CVBA, 006 = CVOA
    #   612 = CommV (commanditaire vennootschap)
    # Exclude companies incorporated after 2022 — too recent for XBRL filings.
    sql = """
        SELECT e.enterprise_number
        FROM enterprise e
        WHERE e.status = 'AC'
          AND e.juridical_form IN ('610','014','015','016','008','006','612')
          AND (e.start_date IS NULL OR e.start_date < '2023-01-01')
          AND NOT EXISTS (
              SELECT 1 FROM financial_data f
              WHERE f.enterprise_number = e.enterprise_number
          )
          AND NOT EXISTS (
              SELECT 1 FROM nbb_load_log l
              WHERE l.enterprise_number = e.enterprise_number
          )
        ORDER BY e.enterprise_number ASC
        LIMIT ?
    """
    rows = conn.execute(sql, (limit,)).fetchall()

    if not rows:
        log("No companies without financial data found")
        return

    log(f"Loading financials for {len(rows)} companies")
    ok = errors = 0
    abort = [False]

    def _process(cbe):
        """Worker: own connection + client per thread."""
        if abort[0]:
            return cbe, "abort", None
        wconn = sqlite3.connect(db_path, timeout=60)
        wconn.execute("PRAGMA journal_mode=WAL")
        wclient = NBBClient()
        try:
            load_company(wconn, wclient, cbe, since_year=since_year, dry_run=dry_run)
            return cbe, "ok", None
        except NBBError as e:
            return cbe, "nbb_err", e
        except Exception as e:
            return cbe, "err", e
        finally:
            wconn.close()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_process, cbe): cbe for (cbe,) in rows}
        for future in as_completed(futures):
            cbe, status, exc = future.result()
            if status == "ok":
                ok += 1
            elif status == "abort":
                pass
            elif status == "nbb_err":
                if exc.status_code in (401, 403):
                    log(f"  AUTH ERROR: {exc} — aborting catch-up")
                    abort[0] = True
                else:
                    errors += 1
            else:
                log(f"  ERROR {cbe}: {exc}")
                errors += 1

    log(f"Catch-up done — {ok} loaded, {errors} errors")


# ---------------------------------------------------------------------------
# Rebuild materialized tables
# ---------------------------------------------------------------------------

def rebuild_materialized_tables(conn):
    """Rebuild financial_latest and company_info from live data."""
    section("Rebuilding materialized tables")

    log("  Rebuilding financial_latest ...")
    conn.execute("DELETE FROM financial_latest")
    conn.execute("""
        INSERT INTO financial_latest
        SELECT enterprise_number, fiscal_year, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash,
               total_assets, fixed_assets, fte_total, personnel_costs
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY enterprise_number
                       ORDER BY fiscal_year DESC, deposit_key DESC
                   ) AS rn
            FROM financial_summary
        )
        WHERE rn = 1
    """)
    conn.commit()

    log("  Rebuilding company_info ...")
    conn.execute("DELETE FROM company_info")
    # Denomination ranking: NL > FR > unspecified > DE > EN. NACE source:
    # prefer activity_group='006' (RSZ — what employees do) over '001' (VAT
    # filing) because RSZ reflects the real business activity. Keep this
    # in lockstep with refresh_company_info() in kbo_daily_update.py.
    conn.execute("""
        INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
        SELECT DISTINCT ON (fl.enterprise_number)
            fl.enterprise_number,
            d.denomination,
            a.municipality_nl,
            a.zipcode,
            act.nace_code
        FROM financial_latest fl
        LEFT JOIN denomination d
               ON d.entity_number = fl.enterprise_number
              AND d.type_of_denomination = '001'
        LEFT JOIN address a
               ON a.entity_number = fl.enterprise_number
              AND a.type_of_address = 'REGO'
        LEFT JOIN LATERAL (
            SELECT nace_code FROM activity
            WHERE entity_number = fl.enterprise_number
              AND classification = 'MAIN'
              AND activity_group IN ('006', '001')
            ORDER BY
                CASE activity_group WHEN '006' THEN 1 WHEN '001' THEN 2 ELSE 3 END,
                CASE nace_version  WHEN '2025' THEN 1 WHEN '2008' THEN 2
                                   WHEN '2003' THEN 3 ELSE 4 END
            LIMIT 1
        ) act ON TRUE
        ORDER BY fl.enterprise_number,
                 CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '0' THEN 3
                                 WHEN '3' THEN 4 WHEN '4' THEN 5 ELSE 6 END,
                 d.denomination NULLS LAST
    """)
    conn.commit()

    log("  Rebuilding financial_by_year ...")
    conn.execute("DROP TABLE IF EXISTS financial_by_year")
    conn.execute("""
        CREATE TABLE financial_by_year AS
        SELECT enterprise_number, fiscal_year, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash,
               total_assets, fte_total, personnel_costs
        FROM financial_summary
    """)
    conn.execute("CREATE INDEX idx_fby_ent  ON financial_by_year(enterprise_number)")
    conn.execute("CREATE INDEX idx_fby_year ON financial_by_year(fiscal_year)")
    conn.commit()

    fl_count  = conn.execute("SELECT COUNT(*) FROM financial_latest").fetchone()[0]
    ci_count  = conn.execute("SELECT COUNT(*) FROM company_info").fetchone()[0]
    fby_count = conn.execute("SELECT COUNT(*) FROM financial_by_year").fetchone()[0]
    log(f"  financial_latest:  {fl_count:,} rows")
    log(f"  company_info:      {ci_count:,} rows")
    log(f"  financial_by_year: {fby_count:,} rows")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(conn):
    section("Summary")
    stats = [
        ("Active enterprises",       "SELECT COUNT(*) FROM enterprise WHERE status='AC'"),
        ("Companies with financials", "SELECT COUNT(DISTINCT enterprise_number) FROM financial_data"),
        ("Total filings",             "SELECT COUNT(DISTINCT deposit_key) FROM financial_data"),
        ("KBO extract (latest)",      "SELECT MAX(extract_number) FROM kbo_extract_log"),
        ("NBB loads today",           "SELECT COUNT(*) FROM nbb_load_log WHERE loaded_at >= date('now')"),
    ]
    for label, sql in stats:
        val = conn.execute(sql).fetchone()[0]
        log(f"  {label:<35} {(val or 0):>10,}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Belgian company DB — daily pipeline")

    parser.add_argument("--kbo-only",   action="store_true", help="Run KBO update only")
    parser.add_argument("--nbb-only",   action="store_true", help="Run NBB extract only")
    parser.add_argument("--catchup",    action="store_true", help="NBB catch-up for companies with no financials")
    parser.add_argument("--catchup-limit", type=int, default=100,
                        help="Max companies to catch up per run (default 100)")
    parser.add_argument("--workers", type=int, default=5,
                        help="Parallel worker threads for catch-up (default 5)")
    parser.add_argument("--nbb-date",   help="NBB extract date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--since-year", type=int, help="Only load filings from this fiscal year onwards")
    parser.add_argument("--dry-run",    action="store_true", help="Parse and log without writing")
    parser.add_argument("--rebuild",    action="store_true", help="Rebuild materialized tables (financial_latest, company_info)")
    parser.add_argument("--data-dir",   default=DEFAULT_DATA, help="Directory with KBO ZIPs")
    parser.add_argument("--db",         default=DEFAULT_DB,   help="Path to SQLite database")

    args = parser.parse_args()

    db_path   = os.path.abspath(args.db)
    data_dir  = os.path.abspath(args.data_dir)

    if not os.path.exists(db_path):
        log(f"ERROR: database not found at {db_path}")
        log("Run scripts/init_db.py and src/kbo_loader.py first")
        sys.exit(1)

    t0 = time.time()
    log(f"Pipeline start — db: {db_path}")
    conn = connect(db_path)

    run_kbo  = not args.nbb_only
    run_nbb  = not args.kbo_only
    catchup  = args.catchup

    if run_kbo:
        run_kbo_update(conn, data_dir, dry_run=args.dry_run)

    if run_nbb:
        nbb_date = args.nbb_date or str(date.today() - timedelta(days=1))
        run_nbb_extract(conn, nbb_date, dry_run=args.dry_run)
        if not args.dry_run:
            rebuild_materialized_tables(conn)

    if catchup:
        run_nbb_catchup(
            conn,
            limit=args.catchup_limit,
            since_year=args.since_year,
            dry_run=args.dry_run,
            workers=args.workers,
        )
        if not args.dry_run:
            rebuild_materialized_tables(conn)

    if args.rebuild:
        rebuild_materialized_tables(conn)

    print_summary(conn)
    conn.close()

    elapsed = time.time() - t0
    log(f"Pipeline complete in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
