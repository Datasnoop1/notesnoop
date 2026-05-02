"""Repair missing governance rows for companies that already have financials."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid

import psycopg2
import requests

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for candidate in (REPO_ROOT, os.path.join(REPO_ROOT, "backend")):
    if os.path.exists(os.path.join(candidate, "nbb_governance.py")) and candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in compile-only contexts
    load_dotenv = None

if load_dotenv:
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    load_dotenv(os.path.join(REPO_ROOT, ".env.production"))

from nbb_governance import extract_governance_snapshot, store_governance_snapshot  # type: ignore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill_nbb_governance")

NBB_BASE_URL = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")
NBB_KEY = os.getenv("NBB_AUTHENTIC_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
USER_AGENT = "Datasnoop/1.0 (Belgian Company Intelligence)"


def _clean_cbe(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/x.jsonxbrl",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": USER_AGENT,
    }


def fetch_company_filings(conn, cbe: str) -> list[tuple[str, int | None]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT DISTINCT deposit_key, fiscal_year
            FROM financial_summary
            WHERE enterprise_number = %s
            ORDER BY fiscal_year DESC NULLS LAST, deposit_key DESC
            """,
            (cbe,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_existing_counts(conn, cbe: str, deposit_key: str) -> dict[str, int]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM administrator_fact
                 WHERE enterprise_number = %s AND deposit_key = %s) AS admin_count,
                (SELECT COUNT(*) FROM shareholder_fact
                 WHERE enterprise_number = %s AND deposit_key = %s) AS shareholder_count,
                (SELECT COUNT(*) FROM participating_interest_fact
                 WHERE enterprise_number = %s AND deposit_key = %s) AS pi_count
            """,
            (cbe, deposit_key, cbe, deposit_key, cbe, deposit_key),
        )
        admin_count, shareholder_count, pi_count = cur.fetchone()
        return {
            "administrators": admin_count or 0,
            "shareholders": shareholder_count or 0,
            "participating_interests": pi_count or 0,
        }
    finally:
        cur.close()


def fetch_filing(session: requests.Session, deposit_key: str) -> dict | None:
    try:
        resp = session.get(
            f"{NBB_BASE_URL}/authentic/deposit/{deposit_key}/accountingData",
            headers=_headers(),
            timeout=30,
        )
    except Exception as exc:
        log.warning("Network error for filing %s: %s", deposit_key, exc)
        return None
    if resp.status_code != 200:
        log.warning("NBB returned HTTP %s for filing %s", resp.status_code, deposit_key)
        return None
    try:
        return resp.json()
    except Exception as exc:
        log.warning("Invalid JSON for filing %s: %s", deposit_key, exc)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing NBB governance rows for one or more companies")
    parser.add_argument("cbes", nargs="+", help="One or more CBE numbers")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and inspect filings without writing to the database")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Delay between NBB calls (default: 1.0)")
    parser.add_argument("--limit-filings", type=int, default=0, help="Optional cap on filings per company (0 = all)")
    args = parser.parse_args()

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL not configured")
    if not NBB_KEY:
        raise SystemExit("NBB_AUTHENTIC_KEY not configured")

    conn = psycopg2.connect(DATABASE_URL)
    session = requests.Session()
    total_companies = 0
    total_inserted = {"administrators": 0, "shareholders": 0, "participating_interests": 0}
    try:
        for raw_cbe in args.cbes:
            cbe = _clean_cbe(raw_cbe)
            filings = fetch_company_filings(conn, cbe)
            if args.limit_filings > 0:
                filings = filings[:args.limit_filings]
            if not filings:
                log.info("%s: no financial filings found", cbe)
                continue

            total_companies += 1
            log.info("%s: %d filings to inspect", cbe, len(filings))
            for deposit_key, fiscal_year in filings:
                existing = fetch_existing_counts(conn, cbe, deposit_key)
                if all(existing.values()):
                    log.info("%s %s: governance already present, skipping", cbe, deposit_key)
                    continue

                filing_json = fetch_filing(session, deposit_key)
                time.sleep(max(args.sleep_seconds, 0.0))
                if not filing_json:
                    continue

                if args.dry_run:
                    extracted = extract_governance_snapshot(cbe, deposit_key, fiscal_year, filing_json)
                    counts = {name: len(rows) for name, rows in extracted.items()}
                    log.info("%s %s dry-run: %s", cbe, deposit_key, counts)
                    continue

                try:
                    counts = store_governance_snapshot(conn, cbe, deposit_key, fiscal_year, filing_json)
                except Exception as exc:
                    log.warning("%s %s: governance backfill failed: %s", cbe, deposit_key, exc)
                    continue

                for key, value in counts.items():
                    total_inserted[key] += value
                log.info("%s %s: inserted %s", cbe, deposit_key, counts)
    finally:
        conn.close()
        session.close()

    log.info(
        "Done. Companies=%d, inserted admins=%d, shareholders=%d, subsidiaries=%d",
        total_companies,
        total_inserted["administrators"],
        total_inserted["shareholders"],
        total_inserted["participating_interests"],
    )


if __name__ == "__main__":
    main()
