"""Backfill NBB financial data from daily extract archives.

Downloads every day's filing ZIP from April 2022 → today and loads them
into SQLite. Much faster than company-by-company loading: ~2,000 filings
per ZIP, one API call per date.

For each date:
  1. Download references ZIP → build deposit_key → fiscal_year map
  2. Download accounting data ZIP → parse and load filings
  3. Skip weekends/holidays (404) automatically

Usage:
    python scripts/backfill_nbb.py                          # full backfill
    python scripts/backfill_nbb.py --start 2024-01-01       # from specific date
    python scripts/backfill_nbb.py --dry-run                # preview only
"""

import argparse
import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from nbb_client import NBBClient, NBBError
from nbb_loader import (
    _get_field, already_loaded, compute_ebitda, extract_ref_metadata,
    fmt, log, parse_filing, store_filing,
)

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")

# Extract archive retains ~1 month of data (not the 3 years the docs claim)
ARCHIVE_START = date(2026, 3, 2)


def load_references_for_date(client, target_date):
    """Download references ZIP and return {deposit_key: (fiscal_year, deposit_date, model_type)}."""
    resp = client.get_extract_references(target_date)
    if resp is None:
        return None  # 404 — no filings this day (weekend/holiday)

    ref_map = {}
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            try:
                with zf.open(name) as f:
                    ref_data = json.load(f)
            except Exception:
                continue

            # Handle both single ref and list of refs
            refs = ref_data if isinstance(ref_data, list) else [ref_data]
            for ref in refs:
                dk, fy, dd, mt = extract_ref_metadata(ref)
                ent = _get_field(ref, "EnterpriseNumber", "enterpriseNumber", "cbeNumber")
                if ent:
                    ent = ent.replace(".", "")
                if dk:
                    ref_map[dk] = (fy, dd, mt, ent)

    return ref_map


def load_extract_for_date(conn, client, target_date, ref_map, dry_run=False):
    """Download and load all filings for a single date.

    Returns (loaded, skipped, errors) counts.
    """
    resp = client.get_extract_json(target_date)
    if resp is None:
        return 0, 0, 0

    loaded = skipped = errors = 0

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            try:
                with zf.open(name) as f:
                    filing_json = json.load(f)
            except Exception as e:
                errors += 1
                continue

            deposit_key = _get_field(filing_json, "ReferenceNumber", "referenceNumber", "depositKey")
            if not deposit_key:
                deposit_key = os.path.splitext(os.path.basename(name))[0]

            if not dry_run and already_loaded(conn, deposit_key):
                skipped += 1
                continue

            # Look up metadata from the references ZIP
            fiscal_year, deposit_date, model_type, ent_num = ref_map.get(
                deposit_key, (None, None, None, None)
            )

            parsed = parse_filing(
                filing_json,
                deposit_key=deposit_key,
                fiscal_year=fiscal_year,
                deposit_date=deposit_date or str(target_date),
                filing_model=model_type,
            )
            if not parsed:
                errors += 1
                continue

            # Patch enterprise_number from reference metadata if missing
            if not parsed["enterprise_number"] and ent_num:
                parsed["enterprise_number"] = ent_num
            if not parsed["enterprise_number"]:
                errors += 1
                continue

            store_filing(conn, parsed, dry_run=dry_run)
            loaded += 1

    return loaded, skipped, errors


def backfill(conn, client, start_date, end_date, dry_run=False):
    """Iterate from start_date to end_date and load all extracts."""
    total_loaded = total_skipped = total_errors = 0
    days_with_data = 0
    days_no_data = 0

    current = start_date
    total_days = (end_date - start_date).days + 1
    day_num = 0

    log(f"Backfill: {start_date} -> {end_date} ({total_days} days)")
    log(f"{'[DRY RUN] ' if dry_run else ''}Starting...")
    t0 = time.time()

    while current <= end_date:
        day_num += 1

        # Fetch references first (for fiscal year metadata)
        try:
            ref_map = load_references_for_date(client, current)
        except NBBError as e:
            if e.status_code in (401, 403):
                log(f"  AUTH ERROR on references: {e} — aborting")
                break
            log(f"  {current}: references error: {e}")
            current += timedelta(days=1)
            continue
        except Exception as e:
            log(f"  {current}: references error: {e}")
            current += timedelta(days=1)
            continue

        if ref_map is None:
            days_no_data += 1
            current += timedelta(days=1)
            continue

        # Fetch and load accounting data
        try:
            loaded, skipped, errors = load_extract_for_date(
                conn, client, current, ref_map, dry_run=dry_run
            )
        except NBBError as e:
            if e.status_code in (401, 403):
                log(f"  AUTH ERROR on extract: {e} — aborting")
                break
            log(f"  {current}: extract error: {e}")
            current += timedelta(days=1)
            continue
        except Exception as e:
            log(f"  {current}: extract error: {e}")
            current += timedelta(days=1)
            continue

        total_loaded += loaded
        total_skipped += skipped
        total_errors += errors
        days_with_data += 1

        elapsed = time.time() - t0
        rate = total_loaded / elapsed if elapsed > 0 else 0
        log(
            f"  {current}: +{loaded} loaded, {skipped} skipped, {errors} err "
            f"| refs={len(ref_map)} "
            f"| cumul: {total_loaded:,} filings, {days_with_data} days "
            f"[{day_num}/{total_days}, {rate:.0f} filings/s]"
        )

        current += timedelta(days=1)

    elapsed = time.time() - t0
    log(f"{'='*60}")
    log(f"Backfill complete in {elapsed/60:.1f} minutes")
    log(f"  Days with data:  {days_with_data}")
    log(f"  Days without:    {days_no_data} (weekends/holidays)")
    log(f"  Filings loaded:  {total_loaded:,}")
    log(f"  Filings skipped: {total_skipped:,} (already in DB)")
    log(f"  Errors:          {total_errors:,}")

    # Print DB stats
    companies = conn.execute("SELECT COUNT(DISTINCT enterprise_number) FROM financial_data").fetchone()[0]
    filings = conn.execute("SELECT COUNT(DISTINCT deposit_key) FROM financial_data WHERE deposit_key != 'NO_FILINGS'").fetchone()[0]
    log(f"  DB totals: {companies:,} companies, {filings:,} filings")


def main():
    parser = argparse.ArgumentParser(description="Backfill NBB financial data from daily extracts")
    parser.add_argument("--start", default=str(ARCHIVE_START),
                        help=f"Start date YYYY-MM-DD (default: {ARCHIVE_START})")
    parser.add_argument("--end", default=str(date.today()),
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        log(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -65536")  # 64MB cache

    client = NBBClient()

    try:
        backfill(conn, client, start, end, dry_run=args.dry_run)
    except KeyboardInterrupt:
        log("Interrupted — progress saved (all loaded filings are committed)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
