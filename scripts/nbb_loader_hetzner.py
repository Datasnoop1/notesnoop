"""Load financial data from NBB API directly on Hetzner server.

Finds companies in company_info that have no financial_data records,
fetches their filings from NBB, and inserts the data.

Run on the Hetzner server: python nbb_loader_hetzner.py
"""

import os
import sys
import json
import time
import uuid
import logging

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
NBB_KEY = os.getenv("NBB_AUTHENTIC_KEY")
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")
if not NBB_KEY:
    raise RuntimeError("NBB_AUTHENTIC_KEY environment variable not set")
NBB_BASE = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")

BATCH_SIZE = 50  # companies per batch
DELAY = 1.0  # seconds between API calls


def get_companies_without_data(conn, limit=500):
    """Find legal-person enterprises not yet checked for NBB filings."""
    cur = conn.cursor()
    cur.execute("""
        SELECT e.enterprise_number
        FROM enterprise e
        LEFT JOIN nbb_load_log nl ON nl.enterprise_number = e.enterprise_number
        WHERE e.type_of_enterprise = '1'
          AND e.status = 'AC'
          AND nl.enterprise_number IS NULL
        ORDER BY RANDOM()
        LIMIT %s
    """, (limit,))
    return [r[0] for r in cur.fetchall()]


def fetch_references(cbe):
    """Get filing references from NBB for a company."""
    headers = {
        "Accept": "application/json",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
    }
    resp = requests.get(
        f"{NBB_BASE}/authentic/legalEntity/{cbe}/references",
        headers=headers, timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code in (403, 404):
        return []  # No filings available — expected for many companies
    logger.warning("NBB references %s: HTTP %d", cbe, resp.status_code)
    return []


def fetch_filing_json(ref_number):
    """Fetch JSON-XBRL data for a filing."""
    headers = {
        "Accept": "application/x.jsonxbrl",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
    }
    resp = requests.get(
        f"{NBB_BASE}/authentic/deposit/{ref_number}/accountingData",
        headers=headers, timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def parse_filing(cbe, ref, filing_json):
    """Extract rubric rows from a JSON-XBRL filing."""
    rows = []
    if not filing_json:
        return rows

    deposit_key = ref.get("ReferenceNumber", "")
    deposit_date = ref.get("DepositDate", "")
    filing_model = ref.get("ModelType", "")

    # Extract exercise dates for fiscal year
    exercise = ref.get("ExerciseDates", {})
    end_date = exercise.get("endDate", "")
    fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None

    # Parse rubrics from the XBRL JSON
    for rubric in filing_json.get("Rubrics", filing_json.get("rubrics", [])):
        code = rubric.get("Code", rubric.get("code", ""))
        value = rubric.get("Value", rubric.get("value"))
        period = rubric.get("Period", rubric.get("period", "N"))

        if code and value is not None:
            rows.append((
                cbe, deposit_key, fiscal_year, deposit_date,
                filing_model, code, period, float(value),
            ))

    return rows


def main():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    companies = get_companies_without_data(conn, limit=500)
    logger.info("Found %d companies without financial data", len(companies))

    if not companies:
        logger.info("All companies have data. Nothing to do.")
        conn.close()
        return

    loaded = 0
    skipped = 0

    for i, cbe in enumerate(companies):
        try:
            refs = fetch_references(cbe)
            time.sleep(DELAY)

            if not refs:
                # Mark as checked (no filings)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO nbb_load_log (enterprise_number, deposit_key) "
                    "VALUES (%s, 'NO_FILINGS') ON CONFLICT DO NOTHING",
                    (cbe,),
                )
                conn.commit()
                skipped += 1
                continue

            total_rubrics = 0
            for ref in refs:
                ref_num = ref.get("ReferenceNumber", "")
                if not ref_num:
                    continue

                filing = fetch_filing_json(ref_num)
                time.sleep(DELAY)

                rows = parse_filing(cbe, ref, filing)
                if rows:
                    cur = conn.cursor()
                    psycopg2.extras.execute_batch(
                        cur,
                        """INSERT INTO financial_data
                           (enterprise_number, deposit_key, fiscal_year, deposit_date,
                            filing_model, rubric_code, period, value)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        rows,
                    )
                    # Log the load
                    cur.execute(
                        "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (cbe, ref_num, len(rows)),
                    )
                    conn.commit()
                    total_rubrics += len(rows)

            loaded += 1
            if (i + 1) % 10 == 0:
                logger.info(
                    "Progress: %d/%d (loaded=%d, skipped=%d)",
                    i + 1, len(companies), loaded, skipped,
                )

        except Exception as e:
            conn.rollback()
            logger.error("Error loading %s: %s", cbe, e)

    logger.info("Done. Loaded: %d, Skipped: %d", loaded, skipped)
    conn.close()


if __name__ == "__main__":
    main()
