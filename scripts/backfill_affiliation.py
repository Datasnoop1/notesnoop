"""Backfill the affiliation table from historical NBB filings.

The `affiliation` table starts empty. The new `extract_governance_snapshot`
populates it for every NEW filing the loaders process, but historical
filings already in `administrator` (with `person_type='legal'`) never
ran through the new extractor.

This script targets that subset: it walks filings that contain at least
one legal-person admin and have not yet produced any affiliation row,
re-fetches the filing JSON from NBB, and re-runs the governance
extractor (which now emits affiliation rows). All inserts are
idempotent (`store_governance_snapshot` uses INSERT … WHERE NOT EXISTS),
so re-running is safe.

Usage:
    # Dry-run a few candidates to confirm the JSON shapes look sane:
    python scripts/backfill_affiliation.py --max-filings 20 --dry-run

    # Real run, capped per session so the operator can resume:
    python scripts/backfill_affiliation.py --max-filings 5000

NBB rate-limit: this script sleeps between calls; default 1.1s
gives ~3000 calls/hour, well below NBB's documented ceiling. A full
prod run is 24-48h walltime — `--max-filings` lets you split it
into nightly chunks the same way the existing nightly backload
script does.

Key revocation safety: matches the nightly backload pattern — on
HTTP 401 we exit immediately so the 15-min watchdog can rotate.
We never rotate keys in-script.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
for candidate in (REPO_ROOT, REPO_ROOT / "backend"):
    if (candidate / "nbb_governance.py").exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in compile-only contexts
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / ".env.production")

from nbb_governance import (  # type: ignore  # noqa: E402
    extract_governance_snapshot,
    store_governance_snapshot,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill_affiliation")

NBB_BASE_URL = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")
NBB_KEY = os.getenv("NBB_AUTHENTIC_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
USER_AGENT = "Datasnoop/1.0 (Company Intelligence)"


class KeyRevoked(Exception):
    """NBB returned 401 — surface to main, exit cleanly so watchdog rotates."""


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/x.jsonxbrl",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": USER_AGENT,
    }


def fetch_candidates(conn, limit: int) -> list[tuple[str, str, str | None]]:
    """Return (cbe, deposit_key, fiscal_year) tuples eligible for backfill.

    Eligible = at least one legal-person admin row with a usable
    identifier AND we have not yet attempted this filing in
    `affiliation_backfill_log`. We exclude on the log rather than
    on the affiliation table itself because filings whose legal-
    person admins have NO representatives produce zero affiliation
    rows but should still count as "attempted" — otherwise we'd
    re-fetch them every run forever.

    Ordered newest-first so the most recently seen relationships land
    in the search index sooner.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT DISTINCT a.enterprise_number, a.deposit_key, a.fiscal_year
            FROM administrator_fact a
            WHERE a.person_type = 'legal'
              AND a.identifier IS NOT NULL
              AND a.identifier <> ''
              -- Some admin rows from the legacy SQLite era carry empty
              -- deposit_keys (schema is NOT NULL but stored as ''). They
              -- produce malformed NBB URLs and 400s; filter them out.
              AND a.deposit_key IS NOT NULL
              AND a.deposit_key <> ''
              -- Sentinel from the legacy nbb_loader for "no XBRL filings"
              -- companies. Not a real filing.
              AND a.deposit_key <> 'NO_FILINGS'
              AND NOT EXISTS (
                  SELECT 1
                  FROM affiliation_backfill_log abl
                  WHERE abl.via_deposit_key = a.deposit_key
                    AND abl.via_enterprise_number = a.enterprise_number
              )
            ORDER BY a.deposit_key DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [(row[0], row[1], row[2]) for row in cur.fetchall()]
    finally:
        cur.close()


def record_attempt(conn, cbe: str, deposit_key: str, rows_inserted: int) -> None:
    """Mark a filing as attempted so the next run skips it.

    Idempotent: ON CONFLICT DO UPDATE refreshes attempted_at + rows_inserted
    so re-runs against the same row are accepted.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO affiliation_backfill_log
                (via_enterprise_number, via_deposit_key, attempted_at, rows_inserted)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (via_enterprise_number, via_deposit_key)
            DO UPDATE SET attempted_at = EXCLUDED.attempted_at,
                          rows_inserted = EXCLUDED.rows_inserted
            """,
            (cbe, deposit_key, rows_inserted),
        )
        conn.commit()
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
    if resp.status_code == 401:
        raise KeyRevoked(deposit_key)
    if resp.status_code != 200:
        log.warning("NBB returned HTTP %s for filing %s", resp.status_code, deposit_key)
        return None
    try:
        return resp.json()
    except Exception as exc:
        log.warning("Invalid JSON for filing %s: %s", deposit_key, exc)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill the affiliation table from historical NBB filings"
    )
    parser.add_argument(
        "--max-filings",
        type=int,
        default=1000,
        help="Cap on filings processed per run. Default 1000.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.1,
        help="Delay between NBB calls. Default 1.1s = ~3000/hour.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + extract but don't write to the affiliation table.",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL not configured")
    if not NBB_KEY:
        raise SystemExit("NBB_AUTHENTIC_KEY not configured")

    conn = psycopg2.connect(DATABASE_URL)
    session = requests.Session()
    processed = 0
    skipped_no_json = 0
    inserted_affiliations = 0
    try:
        candidates = fetch_candidates(conn, args.max_filings)
        log.info(
            "Found %d filings eligible for affiliation backfill (cap=%d)",
            len(candidates),
            args.max_filings,
        )
        if not candidates:
            log.info("Nothing to do.")
            return

        for cbe, deposit_key, fiscal_year in candidates:
            try:
                filing_json = fetch_filing(session, deposit_key)
            except KeyRevoked:
                log.error(
                    "NBB returned 401 on filing %s — exiting so watchdog can rotate",
                    deposit_key,
                )
                raise SystemExit(2)

            time.sleep(max(args.sleep_seconds, 0.0))
            if not filing_json:
                skipped_no_json += 1
                continue

            if args.dry_run:
                extracted = extract_governance_snapshot(
                    cbe, deposit_key, fiscal_year, filing_json
                )
                affiliation_rows = extracted.get("affiliations", [])
                log.info(
                    "%s %s dry-run: %d affiliation rows extracted",
                    cbe,
                    deposit_key,
                    len(affiliation_rows),
                )
                processed += 1
                continue

            try:
                counts = store_governance_snapshot(
                    conn, cbe, deposit_key, fiscal_year, filing_json
                )
            except Exception as exc:
                log.warning(
                    "%s %s: store_governance_snapshot failed: %s",
                    cbe,
                    deposit_key,
                    exc,
                )
                # Don't record an attempt on transient failures — we want
                # the next run to retry. Any legitimate error (bad JSON,
                # missing identifier) is upstream of this point and the
                # filing was either skipped before fetch or returned 0
                # rows successfully (still recorded below).
                continue

            new_affiliations = counts.get("affiliations", 0)
            inserted_affiliations += new_affiliations
            processed += 1
            try:
                record_attempt(conn, cbe, deposit_key, new_affiliations)
            except Exception as exc:
                log.warning(
                    "%s %s: failed to record backfill attempt: %s",
                    cbe,
                    deposit_key,
                    exc,
                )
            if new_affiliations:
                log.info(
                    "%s %s: +%d affiliation rows", cbe, deposit_key, new_affiliations
                )
            else:
                log.debug("%s %s: 0 affiliation rows (no representatives)", cbe, deposit_key)

            if processed % 100 == 0:
                log.info(
                    "Progress: %d/%d processed, %d affiliation rows inserted, %d skipped",
                    processed,
                    len(candidates),
                    inserted_affiliations,
                    skipped_no_json,
                )
    finally:
        conn.close()
        session.close()

    log.info(
        "Done. processed=%d, affiliations inserted=%d, skipped (no JSON)=%d",
        processed,
        inserted_affiliations,
        skipped_no_json,
    )


if __name__ == "__main__":
    main()
