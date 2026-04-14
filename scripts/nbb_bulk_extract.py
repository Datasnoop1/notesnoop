"""Bulk extract ALL financial data from NBB Extract API.

Downloads daily ZIP files containing all filings for each date,
parses rubrics + administrators + shareholders + participating interests,
and inserts into PostgreSQL.

Run on Hetzner: python3 nbb_bulk_extract.py [--start 2022-01-01] [--end 2026-04-14]

Each ZIP contains ~500-1000 JSON filings. ~1,100 days = ~600K filings total.
Estimated time: ~6 hours for full backfill.
"""

import os
import sys
import json
import time
import uuid
import zipfile
import logging
import argparse
import tempfile
from datetime import datetime, timedelta
from io import BytesIO

import requests
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
NBB_EXTRACT_KEY = os.getenv("NBB_EXTRACT_KEY")
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")
if not NBB_EXTRACT_KEY:
    raise RuntimeError("NBB_EXTRACT_KEY environment variable not set")
NBB_BASE = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")

BATCH_SIZE = 500  # rows per execute_batch


def download_daily_zip(date_str):
    """Download the JSON-XBRL ZIP for a given date. Returns bytes or None."""
    headers = {
        "Accept": "application/x.zip+jsonxbrl",
        "NBB-CBSO-Subscription-Key": NBB_EXTRACT_KEY,
        "X-Request-Id": str(uuid.uuid4()),
    }
    url = f"{NBB_BASE}/extracts/batch/{date_str}/accountingData"
    try:
        resp = requests.get(url, headers=headers, timeout=120)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 404:
            return None  # No filings on this date (weekend/holiday)
        logger.warning("HTTP %d for %s", resp.status_code, date_str)
        return None
    except Exception as e:
        logger.error("Download failed for %s: %s", date_str, e)
        return None


def parse_filing(filing_json):
    """Parse a single JSON-XBRL filing into database rows."""
    ref = filing_json.get("ReferenceNumber", "")
    enterprise_name = filing_json.get("EnterpriseName", "")
    address = filing_json.get("Address", {})
    legal_form = filing_json.get("LegalForm", "")

    # Determine enterprise number from reference or address
    cbe = address.get("EnterpriseNumber", "")
    if not cbe:
        # Try to extract from other fields
        return None, [], [], [], []

    cbe = str(cbe).replace(".", "").zfill(10)

    # Parse deposit info
    deposit_key = ref
    deposit_date = None  # Will be set from the date we're processing

    # Determine fiscal year from exercise dates
    exercise = filing_json.get("ExerciseDates", {})
    end_date = exercise.get("endDate", "")
    fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None

    filing_model = filing_json.get("ModelType", "")

    # Parse rubrics
    rubric_rows = []
    for rubric in filing_json.get("Rubrics", []):
        code = rubric.get("Code", "")
        value = rubric.get("Value")
        period = rubric.get("Period", "N")
        if code and value is not None:
            try:
                rubric_rows.append((
                    cbe, deposit_key, fiscal_year, deposit_date,
                    filing_model, code, period, float(value),
                ))
            except (ValueError, TypeError):
                pass

    # Parse administrators
    admin_rows = []
    for admin in filing_json.get("Administrators", []):
        admin_rows.append((
            cbe, deposit_key, str(fiscal_year) if fiscal_year else None,
            "legal" if admin.get("EnterpriseNumber") else "natural",
            admin.get("Name", admin.get("FirstName", "") + " " + admin.get("LastName", "")),
            admin.get("Function", ""),
            admin.get("EnterpriseNumber", ""),
            admin.get("MandateBeginDate", ""),
            admin.get("MandateEndDate", ""),
            admin.get("PermanentRepresentative", {}).get("Name", ""),
        ))

    # Parse shareholders
    sh_rows = []
    for sh in filing_json.get("Shareholders", []):
        sh_rows.append((
            cbe, deposit_key, str(fiscal_year) if fiscal_year else None,
            "entity" if sh.get("EnterpriseNumber") else "individual",
            sh.get("Name", ""),
            sh.get("EnterpriseNumber", ""),
            sh.get("Address", ""),
            sh.get("SharesHeld"),
            sh.get("OwnershipPercentage"),
        ))

    # Parse participating interests
    pi_rows = []
    for pi in filing_json.get("ParticipatingInterests", []):
        pi_rows.append((
            cbe, deposit_key, str(fiscal_year) if fiscal_year else None,
            pi.get("Name", ""),
            pi.get("EnterpriseNumber", ""),
            pi.get("Address", ""),
            pi.get("Country", ""),
            pi.get("OwnershipPercentage"),
            pi.get("EquityValue"),
            pi.get("NetResult"),
        ))

    return cbe, rubric_rows, admin_rows, sh_rows, pi_rows


def process_daily_zip(zip_content, date_str, conn):
    """Parse all filings in a ZIP and insert into the database."""
    cur = conn.cursor()

    try:
        zf = zipfile.ZipFile(BytesIO(zip_content))
    except zipfile.BadZipFile:
        logger.warning("Bad ZIP for %s", date_str)
        return 0, 0

    filings = 0
    rubrics = 0

    for name in zf.namelist():
        if not name.endswith(".json"):
            continue
        try:
            with zf.open(name) as f:
                filing = json.load(f)
        except (json.JSONDecodeError, KeyError):
            continue

        result = parse_filing(filing)
        if result is None:
            continue

        cbe, rubric_rows, admin_rows, sh_rows, pi_rows = result

        # Set deposit_date from the batch date
        rubric_rows = [(r[0], r[1], r[2], date_str, r[4], r[5], r[6], r[7]) for r in rubric_rows]

        if rubric_rows:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO financial_data
                    (enterprise_number, deposit_key, fiscal_year, deposit_date,
                     filing_model, rubric_code, period, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, rubric_rows, page_size=BATCH_SIZE)
            rubrics += len(rubric_rows)

        if admin_rows:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO administrator
                    (enterprise_number, deposit_key, fiscal_year, person_type,
                     name, role, identifier, mandate_start, mandate_end, representative_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, admin_rows, page_size=BATCH_SIZE)

        if sh_rows:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO shareholder
                    (enterprise_number, deposit_key, fiscal_year, shareholder_type,
                     name, identifier, address, shares_held, ownership_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, sh_rows, page_size=BATCH_SIZE)

        if pi_rows:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO participating_interest
                    (enterprise_number, deposit_key, fiscal_year, name,
                     identifier, address, country, ownership_pct, equity_value, net_result)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, pi_rows, page_size=BATCH_SIZE)

        # Log the load
        if rubric_rows:
            cur.execute("""
                INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """, (cbe, rubric_rows[0][1], len(rubric_rows)))

        filings += 1

    conn.commit()
    return filings, rubrics


def get_processed_dates(conn):
    """Get dates already processed (from a tracking table)."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS extract_log (
            extract_date DATE PRIMARY KEY,
            filings_count INTEGER,
            rubrics_count INTEGER,
            processed_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.execute("SELECT extract_date FROM extract_log")
    return {str(r[0]) for r in cur.fetchall()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-04-04", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"), help="End date")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    processed = get_processed_dates(conn)

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    total_days = (end - start).days + 1
    logger.info("Processing %d days from %s to %s", total_days, args.start, args.end)
    logger.info("Already processed: %d days", len(processed))

    current = start
    total_filings = 0
    total_rubrics = 0
    day_count = 0

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")

        if date_str in processed:
            current += timedelta(days=1)
            continue

        # Skip weekends (NBB doesn't publish on weekends)
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        zip_content = download_daily_zip(date_str)
        day_count += 1

        if zip_content:
            filings, rubrics = process_daily_zip(zip_content, date_str, conn)
            total_filings += filings
            total_rubrics += rubrics

            # Log processed date
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO extract_log (extract_date, filings_count, rubrics_count) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (date_str, filings, rubrics),
            )
            conn.commit()

            if day_count % 10 == 0:
                logger.info(
                    "Day %d: %s — %d filings, %d rubrics (total: %d filings, %d rubrics)",
                    day_count, date_str, filings, rubrics, total_filings, total_rubrics,
                )
        else:
            # Mark as processed (no data / holiday)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO extract_log (extract_date, filings_count, rubrics_count) VALUES (%s, 0, 0) ON CONFLICT DO NOTHING",
                (date_str,),
            )
            conn.commit()

        # Small delay between downloads
        time.sleep(0.5)
        current += timedelta(days=1)

    logger.info("DONE: %d days processed, %d filings, %d rubrics loaded", day_count, total_filings, total_rubrics)
    conn.close()


if __name__ == "__main__":
    main()
