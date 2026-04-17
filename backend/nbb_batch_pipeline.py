"""NBB Batch Pipeline — downloads daily ZIP extracts and loads into PostgreSQL.

Uses the /extracts/batch/{date}/accountingData endpoint to download ALL filings
published on a given date as a single ZIP. Much faster than per-company loading.

Run daily at 1am via cron:
  0 1 * * * cd /opt/leadpeek/backend && python nbb_batch_pipeline.py >> /var/log/nbb_batch.log 2>&1

Modes:
  python nbb_batch_pipeline.py                    # Process yesterday's filings
  python nbb_batch_pipeline.py --date 2024-01-15  # Process specific date
  python nbb_batch_pipeline.py --backfill 30      # Backfill last N days
  python nbb_batch_pipeline.py --backfill-from 2023-04-04 --backfill-to 2024-12-31
"""

import argparse
import io
import json
import logging
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from db import get_connection, put_connection, execute, fetch_one, fetch_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nbb_batch")

# NBB API config
NBB_BASE_URL = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")
NBB_EXTRACT_KEY = os.getenv("NBB_EXTRACT_KEY", "")
NBB_AUTHENTIC_KEY = os.getenv("NBB_AUTHENTIC_KEY", "")


def _nbb_headers(key: str) -> dict:
    import uuid
    return {
        "NBB-CBSO-Subscription-Key": key,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence)",
    }


def download_daily_zip(target_date: str) -> bytes | None:
    """Download the daily ZIP of all JSON filings for a date.

    Uses: GET /extracts/batch/{date}/accountingData
    Accept: application/x.zip+jsonxbrl
    """
    import requests

    url = f"{NBB_BASE_URL}/extracts/batch/{target_date}/accountingData"
    headers = _nbb_headers(NBB_EXTRACT_KEY)
    headers["Accept"] = "application/x.zip+jsonxbrl"

    log.info("Downloading daily extract for %s...", target_date)
    try:
        resp = requests.get(url, headers=headers, timeout=120, stream=True)
        if resp.status_code == 404:
            log.info("No filings for %s (404)", target_date)
            return None
        if resp.status_code != 200:
            log.error("NBB extract failed for %s: HTTP %d — %s", target_date, resp.status_code, resp.text[:200])
            return None
        content = resp.content
        log.info("Downloaded %s: %.1f KB", target_date, len(content) / 1024)
        return content
    except Exception as e:
        log.error("Download failed for %s: %s", target_date, e)
        return None


def download_daily_refs(target_date: str) -> list[dict]:
    """Download the daily references ZIP for metadata (fiscal year, model type, etc.)."""
    import requests

    url = f"{NBB_BASE_URL}/extracts/batch/{target_date}/references"
    headers = _nbb_headers(NBB_EXTRACT_KEY)
    headers["Accept"] = "application/x.zip+json"

    try:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            return []
        refs = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                with zf.open(name) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        refs.extend(data)
                    elif isinstance(data, dict):
                        refs.append(data)
        return refs
    except Exception as e:
        log.warning("Refs download failed for %s: %s", target_date, e)
        return []


def parse_filing(filing_json: dict, ref_metadata: dict | None = None) -> tuple[str, str, int | None, str, str, list[tuple]]:
    """Parse a single filing JSON into rubric rows.

    Returns: (cbe, deposit_key, fiscal_year, deposit_date, filing_model, rows)
    where rows is a list of (cbe, deposit_key, fiscal_year, deposit_date, filing_model, rubric_code, period, value).
    """
    # Extract CBE from filing (try multiple key patterns)
    cbe = (
        filing_json.get("EnterpriseNumber")
        or filing_json.get("enterpriseNumber")
        or filing_json.get("LegalEntity", {}).get("EnterpriseNumber", "")
        or ""
    ).replace(".", "").strip()

    deposit_key = (
        filing_json.get("ReferenceNumber")
        or filing_json.get("referenceNumber")
        or filing_json.get("DepositKey", "")
        or ""
    )

    # Get metadata from reference if available
    fiscal_year = None
    deposit_date = ""
    filing_model = ""

    if ref_metadata:
        exercise = ref_metadata.get("ExerciseDates", {})
        end_date = exercise.get("endDate", "")
        fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None
        deposit_date = ref_metadata.get("DepositDate", "")
        filing_model = ref_metadata.get("ModelType", "")
    else:
        # Try to extract from filing itself
        exercise = filing_json.get("ExerciseDates", filing_json.get("exerciseDates", {}))
        end_date = exercise.get("endDate", exercise.get("EndDate", ""))
        fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None
        deposit_date = filing_json.get("DepositDate", filing_json.get("depositDate", ""))
        filing_model = filing_json.get("ModelType", filing_json.get("modelType", ""))

    # Parse rubrics
    rows = []
    for rubric in filing_json.get("Rubrics", filing_json.get("rubrics", [])):
        code = rubric.get("Code", rubric.get("code", ""))
        value = rubric.get("Value", rubric.get("value"))
        period = rubric.get("Period", rubric.get("period", "N"))

        if code and value is not None:
            rows.append((
                cbe, deposit_key, fiscal_year, deposit_date,
                filing_model, code, period, float(value),
            ))

    return cbe, deposit_key, fiscal_year, deposit_date, filing_model, rows


def process_daily_extract(target_date: str, dry_run: bool = False) -> dict:
    """Download and process all filings for a single date.

    Returns: {"date": str, "filings": int, "rubrics": int, "skipped": int, "errors": int}
    """
    # Check if already processed
    already = fetch_one(
        "SELECT 1 FROM meta WHERE variable = %s",
        (f"nbb_batch_{target_date}",),
    )
    if already:
        log.info("Date %s already processed — skipping", target_date)
        return {"date": target_date, "filings": 0, "rubrics": 0, "skipped": 0, "errors": 0, "status": "already_done"}

    # Download references (for metadata) and filings ZIP
    refs_list = download_daily_refs(target_date)
    ref_map = {}
    for r in refs_list:
        key = r.get("ReferenceNumber", r.get("referenceNumber", ""))
        if key:
            ref_map[key] = r

    zip_bytes = download_daily_zip(target_date)
    if not zip_bytes:
        return {"date": target_date, "filings": 0, "rubrics": 0, "skipped": 0, "errors": 0, "status": "no_data"}

    if dry_run:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            log.info("[dry-run] ZIP contains %d files for %s", len(zf.namelist()), target_date)
        return {"date": target_date, "filings": len(zf.namelist()), "rubrics": 0, "skipped": 0, "errors": 0, "status": "dry_run"}

    # Process filings
    conn = get_connection()
    cur = conn.cursor()
    filings_loaded = 0
    total_rubrics = 0
    skipped = 0
    errors = 0

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            file_count = len(zf.namelist())
            log.info("Processing %d filings for %s...", file_count, target_date)

            for name in zf.namelist():
                try:
                    with zf.open(name) as f:
                        filing_json = json.load(f)

                    cbe, deposit_key, fiscal_year, deposit_date, filing_model, rows = parse_filing(
                        filing_json, ref_map.get(deposit_key if 'deposit_key' in dir() else "", None)
                    )

                    if not cbe or not deposit_key or not rows:
                        skipped += 1
                        continue

                    # Re-lookup metadata from ref_map using deposit_key
                    ref_meta = ref_map.get(deposit_key)
                    if ref_meta:
                        cbe_r, deposit_key_r, fiscal_year_r, deposit_date_r, filing_model_r, rows = parse_filing(
                            filing_json, ref_meta
                        )
                        if fiscal_year_r:
                            fiscal_year = fiscal_year_r
                        if deposit_date_r:
                            deposit_date = deposit_date_r
                        if filing_model_r:
                            filing_model = filing_model_r

                    # Check if already loaded
                    cur.execute(
                        "SELECT 1 FROM nbb_load_log WHERE enterprise_number = %s AND deposit_key = %s",
                        (cbe, deposit_key),
                    )
                    if cur.fetchone():
                        skipped += 1
                        continue

                    # Insert rubrics
                    psycopg2.extras.execute_batch(
                        cur,
                        """INSERT INTO financial_data
                           (enterprise_number, deposit_key, fiscal_year, deposit_date,
                            filing_model, rubric_code, period, value)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        rows,
                    )

                    # Log
                    cur.execute(
                        "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (cbe, deposit_key, len(rows)),
                    )
                    conn.commit()

                    total_rubrics += len(rows)
                    filings_loaded += 1

                except Exception as e:
                    conn.rollback()
                    errors += 1
                    log.warning("Error processing %s: %s", name, e)

        # Mark date as processed
        execute(
            "INSERT INTO meta (variable, value) VALUES (%s, %s) ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
            (f"nbb_batch_{target_date}", f"{filings_loaded} filings, {total_rubrics} rubrics"),
        )

        log.info(
            "Date %s: %d filings loaded, %d rubrics, %d skipped, %d errors",
            target_date, filings_loaded, total_rubrics, skipped, errors,
        )

    finally:
        cur.close()
        put_connection(conn)

    return {
        "date": target_date,
        "filings": filings_loaded,
        "rubrics": total_rubrics,
        "skipped": skipped,
        "errors": errors,
        "status": "ok",
    }


def rebuild_materialized_tables():
    """Rebuild financial_latest, company_info, and financial_by_year."""
    log.info("Rebuilding materialized tables...")
    t0 = time.time()

    conn = get_connection()
    cur = conn.cursor()
    try:
        # financial_latest
        cur.execute("DELETE FROM financial_latest")
        cur.execute("""
            INSERT INTO financial_latest
            SELECT enterprise_number, fiscal_year, filing_model,
                   revenue, ebit, da, ebitda, net_profit,
                   equity, lt_financial_debt, st_financial_debt, cash,
                   total_assets, fixed_assets, fte_total, personnel_costs
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY enterprise_number
                    ORDER BY fiscal_year DESC, deposit_key DESC
                ) AS rn
                FROM financial_summary
            ) sub WHERE rn = 1
        """)
        conn.commit()

        # company_info (only update existing rows + add new ones from financial_latest)
        cur.execute("""
            INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
            SELECT
                fl.enterprise_number,
                MAX(d.denomination),
                MAX(a.municipality_nl),
                MAX(a.zipcode),
                MAX(act.nace_code)
            FROM financial_latest fl
            LEFT JOIN denomination d ON d.entity_number = fl.enterprise_number
                AND d.type_of_denomination = '001' AND d.language IN ('2', '1')
            LEFT JOIN address a ON a.entity_number = fl.enterprise_number
                AND a.type_of_address = 'REGO'
            LEFT JOIN activity act ON act.entity_number = fl.enterprise_number
                AND act.classification = 'MAIN'
            WHERE NOT EXISTS (SELECT 1 FROM company_info ci WHERE ci.enterprise_number = fl.enterprise_number)
            GROUP BY fl.enterprise_number
        """)
        conn.commit()

        # financial_by_year
        cur.execute("DROP TABLE IF EXISTS financial_by_year")
        cur.execute("""
            CREATE TABLE financial_by_year AS
            SELECT enterprise_number, fiscal_year, filing_model,
                   revenue, ebit, da, ebitda, net_profit,
                   equity, lt_financial_debt, st_financial_debt, cash,
                   total_assets, fte_total, personnel_costs
            FROM financial_summary
        """)
        cur.execute("CREATE INDEX idx_fby_ent ON financial_by_year(enterprise_number)")
        cur.execute("CREATE INDEX idx_fby_year ON financial_by_year(fiscal_year)")
        conn.commit()

        fl = cur.execute("SELECT COUNT(*) FROM financial_latest")
        fl_count = cur.fetchone()[0]
        log.info("Materialized tables rebuilt in %.1fs — financial_latest: %d rows", time.time() - t0, fl_count)

    finally:
        cur.close()
        put_connection(conn)


def main():
    parser = argparse.ArgumentParser(description="NBB Batch Pipeline — daily ZIP extract loader")
    parser.add_argument("--date", help="Process a specific date (YYYY-MM-DD). Default: yesterday.")
    parser.add_argument("--backfill", type=int, help="Backfill last N days")
    parser.add_argument("--backfill-from", help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--backfill-to", help="Backfill end date (YYYY-MM-DD, default: yesterday)")
    parser.add_argument("--dry-run", action="store_true", help="Download but don't insert")
    parser.add_argument("--no-rebuild", action="store_true", help="Skip materialized table rebuild")
    args = parser.parse_args()

    if not NBB_EXTRACT_KEY:
        log.error("NBB_EXTRACT_KEY not set — cannot download extracts")
        sys.exit(1)

    t0 = time.time()
    total_filings = 0
    total_rubrics = 0
    dates_processed = 0

    if args.backfill or args.backfill_from:
        # Backfill mode: iterate date range
        if args.backfill_from:
            start = datetime.strptime(args.backfill_from, "%Y-%m-%d").date()
        else:
            start = date.today() - timedelta(days=args.backfill)
        end = datetime.strptime(args.backfill_to, "%Y-%m-%d").date() if args.backfill_to else date.today() - timedelta(days=1)

        log.info("=" * 60)
        log.info("NBB Batch Backfill: %s to %s (%d days)", start, end, (end - start).days + 1)
        log.info("=" * 60)

        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            # Skip weekends (no filings published)
            if current.weekday() < 5:
                result = process_daily_extract(date_str, dry_run=args.dry_run)
                total_filings += result["filings"]
                total_rubrics += result["rubrics"]
                if result["status"] not in ("already_done", "no_data"):
                    dates_processed += 1
                time.sleep(1)  # Be polite to NBB
            current += timedelta(days=1)

    else:
        # Single date mode
        target = args.date or str(date.today() - timedelta(days=1))
        log.info("=" * 60)
        log.info("NBB Batch Pipeline: %s", target)
        log.info("=" * 60)

        result = process_daily_extract(target, dry_run=args.dry_run)
        total_filings = result["filings"]
        total_rubrics = result["rubrics"]
        dates_processed = 1 if result["status"] == "ok" else 0

    # Rebuild materialized tables if data was loaded
    if total_filings > 0 and not args.dry_run and not args.no_rebuild:
        rebuild_materialized_tables()

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("Done in %.0fs — %d dates, %d filings, %d rubrics", elapsed, dates_processed, total_filings, total_rubrics)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
