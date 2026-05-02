#!/usr/bin/env python3
"""Retry NBB governance extraction failures recorded in governance_load_log."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

import psycopg2
import requests


ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "backend"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in container contexts
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv:
    load_dotenv(ROOT / ".env.production")

from nbb_governance import (  # noqa: E402
    record_governance_load_failure,
    record_governance_load_success,
    store_governance_snapshot,
)


LOG = logging.getLogger("retry_failed_governance")

DATABASE_URL = os.getenv("DATABASE_URL", "")
NBB_BASE_URL = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be").rstrip("/")
NBB_KEY = os.getenv("NBB_AUTHENTIC_KEY", "")
USER_AGENT = "Datasnoop/1.0 (Belgian Company Intelligence)"
MAX_RETRY_ATTEMPTS = int(os.getenv("GOVERNANCE_RETRY_MAX_ATTEMPTS", "7"))
PRESTORE_CIRCUIT_BREAKER = int(os.getenv("GOVERNANCE_RETRY_CIRCUIT_BREAKER", "5"))


def _safe_error(error: Exception | str, limit: int = 1000) -> str:
    """Redact secrets before an error reaches cron logs or governance_load_log."""
    message = str(error) or error.__class__.__name__
    message = message.replace("\r", " ").replace("\n", " ")
    if NBB_KEY:
        message = message.replace(NBB_KEY, "[redacted]")
    message = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [redacted]", message)
    message = re.sub(
        r"(?i)\b((?:NBB-CBSO-Subscription-Key|Authorization|api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|key|token|password|secret)=)[^&\s]+",
        r"\1[redacted]",
        message,
    )
    return message[:limit]


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/x.jsonxbrl",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": USER_AGENT,
    }


def fetch_retry_rows(conn, limit: int, max_attempts: int) -> list[tuple[str, str, int | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT gl.enterprise_number,
                   gl.deposit_key,
                   fs.fiscal_year
            FROM governance_load_log gl
            LEFT JOIN financial_summary fs
              ON fs.enterprise_number = gl.enterprise_number
             AND fs.deposit_key = gl.deposit_key
            WHERE gl.status = 'error'
              AND (gl.next_retry_at IS NULL OR gl.next_retry_at <= NOW())
              AND gl.attempts < %s
            ORDER BY gl.last_attempt_at NULLS FIRST,
                     gl.created_at ASC
            LIMIT %s
            """,
            (max_attempts, limit),
        )
        return [(row[0], row[1], row[2]) for row in cur.fetchall()]


def fetch_filing(session: requests.Session, deposit_key: str) -> dict | None:
    resp = session.get(
        f"{NBB_BASE_URL}/authentic/deposit/{deposit_key}/accountingData",
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"NBB returned HTTP {resp.status_code}")
    return resp.json()


def retry_once(
    conn,
    session: requests.Session,
    cbe: str,
    deposit_key: str,
    fiscal_year: int | None,
    *,
    dry_run: bool,
) -> bool:
    filing_json = fetch_filing(session, deposit_key)
    if dry_run:
        LOG.info("%s %s: dry-run fetched filing", cbe, deposit_key)
        return True

    try:
        counts = store_governance_snapshot(conn, cbe, deposit_key, fiscal_year, filing_json)
        record_governance_load_success(conn, cbe, deposit_key, counts)
        LOG.info("%s %s: governance retry succeeded: %s", cbe, deposit_key, counts)
        return True
    except Exception as exc:
        safe_error = _safe_error(exc)
        LOG.warning("%s %s: governance retry failed: %s", cbe, deposit_key, safe_error)
        record_governance_load_failure(conn, cbe, deposit_key, safe_error)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-attempts", type=int, default=MAX_RETRY_ATTEMPTS)
    parser.add_argument("--circuit-breaker", type=int, default=PRESTORE_CIRCUIT_BREAKER)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL not configured")
    if not NBB_KEY:
        raise SystemExit("NBB_AUTHENTIC_KEY not configured")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    with psycopg2.connect(DATABASE_URL) as conn:
        rows = fetch_retry_rows(conn, max(args.limit, 1), max(args.max_attempts, 1))
        LOG.info("retry candidates: %d", len(rows))
        if not rows:
            return 0

        ok = 0
        failed = 0
        prestore_failures = 0
        with requests.Session() as session:
            for cbe, deposit_key, fiscal_year in rows:
                try:
                    if retry_once(
                        conn,
                        session,
                        cbe,
                        deposit_key,
                        fiscal_year,
                        dry_run=args.dry_run,
                    ):
                        ok += 1
                    else:
                        failed += 1
                    prestore_failures = 0
                except Exception as exc:
                    failed += 1
                    prestore_failures += 1
                    safe_error = _safe_error(exc)
                    LOG.warning("%s %s: retry failed before store: %s", cbe, deposit_key, safe_error)
                    if not args.dry_run:
                        record_governance_load_failure(conn, cbe, deposit_key, safe_error)
                    if prestore_failures >= max(args.circuit_breaker, 1):
                        LOG.error(
                            "stopping after %d consecutive pre-store failures",
                            prestore_failures,
                        )
                        break
                time.sleep(max(args.sleep_seconds, 0.0))

    LOG.info("done: ok=%d failed=%d", ok, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
