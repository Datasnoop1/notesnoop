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
from nbb_governance import store_governance_snapshot

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


def _pick(d: dict, *keys):
    """Return the first present, non-None value from d for any of the given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def parse_filing(filing_json: dict, ref_metadata: dict | None = None) -> tuple[str, str, int | None, str, str, list[tuple]]:
    """Parse a single filing JSON into rubric rows.

    Returns: (cbe, deposit_key, fiscal_year, deposit_date, filing_model, rows)
    where rows is a list of (cbe, deposit_key, fiscal_year, deposit_date, filing_model, rubric_code, period, value).

    NBB's 2026 extract schema: accountingData filings carry Rubrics + ReferenceNumber
    (PascalCase) but NOT the CBE. The CBE is only in the references ZIP under
    `enterpriseNumber` (camelCase). We must join on ReferenceNumber.
    """
    deposit_key = _pick(filing_json, "ReferenceNumber", "referenceNumber", "DepositKey") or ""

    legal_entity = filing_json.get("LegalEntity") or {}
    cbe = _pick(
        filing_json, "EnterpriseNumber", "enterpriseNumber"
    ) or _pick(legal_entity, "EnterpriseNumber", "enterpriseNumber") or ""
    if not cbe and ref_metadata:
        cbe = _pick(ref_metadata, "enterpriseNumber", "EnterpriseNumber") or ""
    cbe = str(cbe).replace(".", "").strip()

    if not deposit_key and ref_metadata:
        deposit_key = _pick(ref_metadata, "referenceNumber", "ReferenceNumber") or ""

    fiscal_year = None
    deposit_date = ""
    filing_model = ""

    meta_source = ref_metadata or filing_json
    exercise = _pick(meta_source, "ExerciseDates", "exerciseDates") or {}
    end_date = _pick(exercise, "endDate", "EndDate") or ""
    fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None
    deposit_date = _pick(meta_source, "DepositDate", "depositDate") or ""
    filing_model = _pick(meta_source, "ModelType", "modelType") or ""

    rows = []
    for rubric in filing_json.get("Rubrics") or filing_json.get("rubrics") or []:
        code = _pick(rubric, "Code", "code") or ""
        value = _pick(rubric, "Value", "value")
        period = _pick(rubric, "Period", "period") or "N"

        if code and value is not None:
            try:
                rows.append((
                    cbe, deposit_key, fiscal_year, deposit_date,
                    filing_model, code, period, float(value),
                ))
            except (TypeError, ValueError):
                continue

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

                    # Look up reference metadata by the filing's own ReferenceNumber
                    # (this is where CBE + fiscal year + model type live under the
                    # 2026 schema — the filing itself no longer carries them).
                    ref_key = (
                        filing_json.get("ReferenceNumber")
                        or filing_json.get("referenceNumber")
                        or ""
                    )
                    ref_meta = ref_map.get(ref_key)

                    cbe, deposit_key, fiscal_year, deposit_date, filing_model, rows = parse_filing(
                        filing_json, ref_meta
                    )

                    if not cbe or not deposit_key or not rows:
                        skipped += 1
                        continue

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

                    try:
                        store_governance_snapshot(conn, cbe, deposit_key, fiscal_year, filing_json)
                    except Exception as gov_err:
                        log.warning(
                            "Governance store failed for %s filing %s: %s",
                            cbe, deposit_key, gov_err,
                        )

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
        # Explicit target column list: `fixed_assets` was added late via
        # ALTER TABLE so it sits at the end of `financial_latest`'s real
        # column order, NOT next to `total_assets` like in the source view.
        # Without an explicit list, positional insertion shifts fixed_assets,
        # fte_total, and personnel_costs into the wrong slots.
        cur.execute("""
            INSERT INTO financial_latest
                (enterprise_number, fiscal_year, filing_model,
                 revenue, ebit, da, ebitda, net_profit,
                 equity, lt_financial_debt, st_financial_debt, cash,
                 total_assets, fixed_assets, fte_total, personnel_costs)
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

        # company_info — insert rows for newly-loaded financials.
        # Pick the best-language denomination per enterprise (NL > FR > none > DE/EN)
        # and the best NACE per enterprise (RSZ group 006 > VAT 001, latest
        # taxonomy preferred). Keep this in sync with refresh_company_info()
        # in backend/kbo_daily_update.py — both materialisers must agree on
        # priority or the daily update will flip newly-loaded rows back.
        cur.execute("""
            INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
            SELECT DISTINCT ON (fl.enterprise_number)
                fl.enterprise_number,
                d.denomination,
                a.municipality_nl,
                a.zipcode,
                act.nace_code
            FROM financial_latest fl
            LEFT JOIN denomination d ON d.entity_number = fl.enterprise_number
                AND d.type_of_denomination = '001'
            LEFT JOIN address a ON a.entity_number = fl.enterprise_number
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
            WHERE NOT EXISTS (SELECT 1 FROM company_info ci WHERE ci.enterprise_number = fl.enterprise_number)
            ORDER BY fl.enterprise_number,
                     CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '0' THEN 3
                                     WHEN '3' THEN 4 WHEN '4' THEN 5 ELSE 6 END,
                     d.denomination NULLS LAST
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

        # Refresh the sector_percentiles MV so screener pills + radar scores
        # reflect the new data. CONCURRENTLY keeps it readable during refresh
        # but requires running OUTSIDE a transaction block. Use a dedicated
        # short-lived connection so we don't leak autocommit mode back into
        # the shared pool (which would break transactional assumptions for
        # the next caller).
        try:
            import psycopg2 as _pg2
            import os as _os
            sp_conn = _pg2.connect(_os.getenv("DATABASE_URL"))
            try:
                sp_conn.set_isolation_level(_pg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                sp_cur = sp_conn.cursor()
                sp_cur.execute("SELECT to_regclass('public.sector_percentiles')")
                if sp_cur.fetchone()[0] is not None:
                    sp_t0 = time.time()
                    sp_cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY sector_percentiles")
                    log.info("sector_percentiles refreshed in %.1fs", time.time() - sp_t0)
                sp_cur.close()
            finally:
                sp_conn.close()
        except Exception as e:
            log.warning("sector_percentiles refresh failed (non-fatal): %s", e)

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
