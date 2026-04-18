"""Daily Staatsblad structured-event extraction (incremental).

Picks up any publications added in the last N days that don't yet have
entries in `staatsblad_event` and processes them via the regular
Anthropic API (not batch) for low latency. Acceptable cost: roughly
150-300 filings/day → $0.10-$0.20/day.

Usage (cron):
    0 4 * * *  python scripts/staatsblad_incremental.py --lookback-days 2

The 48-hour look-back window covers the weekend gap where no cron runs
(so Sunday/Monday filings get picked up in the Monday 04:00 run).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from staatsblad_extraction.extractor import (  # noqa: E402
    HAIKU_ANTHROPIC,
    extract_one,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("staatsblad-incremental")


# Narrower filter than the backfill: the daily pipeline only hits the
# "hot" categories because they account for virtually all extractable
# events. If volume ever becomes a concern we can trim further.
DEFAULT_PUB_TYPES = [
    "%ONTSLAG%", "%BENOEM%", "%NOMINATION%", "%DEMISSION%",
    "%KAPITAAL%", "%CAPITAL%", "%FUSIE%", "%FUSION%",
    "%ONTBINDING%", "%DISSOLUTION%", "%VEREFFENING%", "%LIQUIDATION%",
    "%NAAMSWIJZ%", "%DENOMINATION%", "%OMZETTING%", "%TRANSFORMATION%",
    "%ZETEL%", "%SIEGE%", "%STATUTEN%", "%STATUTS%",
    "%AANDELEN%", "%ACTIONS%", "%SPLITSING%", "%SCISSION%",
]


def db_conn():
    from db import get_connection  # type: ignore
    return get_connection()


def _fetch_pending(conn, lookback_days: int, pub_types: list[str], cap: int) -> list[dict]:
    """Rows whose loaded_at is within the window and which don't yet
    appear in staatsblad_event."""
    since = datetime.utcnow() - timedelta(days=lookback_days)
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT sp.enterprise_number, sp.pub_date, sp.pub_type,
                      sp.reference, sp.pdf_url, sp.entity_name
               FROM staatsblad_publication sp
               WHERE sp.loaded_at >= %s
                 AND sp.reference IS NOT NULL
                 AND sp.reference <> 'NO_DATA'
                 AND sp.pdf_url IS NOT NULL
                 AND sp.pub_type ILIKE ANY(%s::text[])
                 AND NOT EXISTS (
                     SELECT 1 FROM staatsblad_event e
                     WHERE e.enterprise_number = sp.enterprise_number
                       AND e.pub_reference = sp.reference
                 )
               ORDER BY sp.pub_date DESC
               LIMIT %s""",
            (since, pub_types, cap),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lookback-days", type=int, default=2)
    p.add_argument("--cap", type=int, default=2000,
                   help="Safety cap — bail early if more than this pending")
    p.add_argument("--run-id", type=str,
                   default=f"incremental-{datetime.utcnow():%Y%m%d}")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY not set")
        return 2

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except ImportError:
        log.error("anthropic SDK not installed")
        return 2

    conn = db_conn()
    conn.autocommit = False
    pending = _fetch_pending(conn, args.lookback_days, DEFAULT_PUB_TYPES, args.cap)
    log.info("Pending: %d filings from the last %d days",
             len(pending), args.lookback_days)

    if args.dry_run or not pending:
        return 0

    ok_count = 0
    fail_count = 0
    events_total = 0
    for i, pub in enumerate(pending, start=1):
        log.info("[%d/%d] %s/%s (%s)",
                 i, len(pending), pub["enterprise_number"], pub["reference"],
                 pub.get("pub_type", "")[:40])
        res = await extract_one(pub, client, conn, run_id=args.run_id)
        if res["ok"]:
            ok_count += 1
            events_total += res["events_inserted"]
        else:
            fail_count += 1
            log.warning("  failed: %s", res.get("error"))

    log.info("")
    log.info("Incremental done: ok=%d failed=%d events=%d",
             ok_count, fail_count, events_total)
    return 0 if fail_count == 0 or ok_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
