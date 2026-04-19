"""Every-2-day batch-API catch-up for Staatsblad event extraction.

Replaces the earlier `staatsblad_incremental.py` daily script.  Runs
via cron every 48h (`0 4 */2 * *`) and uses the Anthropic **batch API**
(50 % discount) rather than the per-request regular API. 24h batch
turnaround fits comfortably in the 2-day cadence.

Behaviour:
  - Reads staatsblad_publication rows loaded in the last 72 hours
    that don't yet have entries in staatsblad_event.  (72h overlap
    catches anything a prior run missed.)
  - Submits them as one Anthropic batch chunk.
  - Polls up to `--poll-max-hours` (default 18h); anything still
    outstanding at exit time rolls into the next run via the
    staatsblad_backfill_progress checkpoint.
  - Reuses the backfill's extractor helpers + cost guard.

Cost envelope: ~150-400 filings / 2 days × $0.0015 ≈ $0.50-1.20 per
run, ~$10-20 / month.

Usage (cron):
    0 4 */2 * *  python scripts/staatsblad_batch_every_2d.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from staatsblad_extraction.extractor import (  # noqa: E402
    HAIKU_ANTHROPIC,
    build_batch_request,
    extract_tool_use_events,
    persist_events,
    prepare_filing,
    record_progress,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("staatsblad-batch-every-2d")


# Match the daily incremental's category filter — narrower than the
# backfill because we only want event-dense publications for the
# recurring catch-up.
DEFAULT_PUB_TYPE_PATTERNS = [
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


def _fetch_pending(
    conn, lookback_hours: int, pub_types: list[str], cap: int,
) -> list[dict]:
    since = datetime.utcnow() - timedelta(hours=lookback_hours)
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


async def _prepare_bounded(pub: dict, sem: asyncio.Semaphore):
    async with sem:
        prepared = await prepare_filing(pub)
        if not prepared:
            return None
        return prepared


async def run(
    lookback_hours: int,
    cap: int,
    workers: int,
    poll_interval_sec: int,
    poll_max_hours: int,
    run_id: str,
    dry_run: bool,
) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY not set")
        return 2

    try:
        import anthropic
    except ImportError:
        log.error("anthropic SDK not installed")
        return 2

    conn = db_conn()
    conn.autocommit = False

    pending = _fetch_pending(conn, lookback_hours, DEFAULT_PUB_TYPE_PATTERNS, cap)
    log.info("Pending: %d filings from the last %dh", len(pending), lookback_hours)

    if dry_run:
        return 0
    if not pending:
        log.info("Nothing to submit this cycle.")
        return 0

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Prepare PDFs in parallel
    sem = asyncio.Semaphore(workers)
    prepared_list = await asyncio.gather(*[_prepare_bounded(p, sem) for p in pending])
    prepared_map: dict[str, object] = {}
    requests_list: list[dict] = []
    for pub, prep in zip(pending, prepared_list):
        ref = pub.get("reference")
        if prep is None:
            try:
                record_progress(conn, run_id, ref, "failed", "prepare_failed")
                conn.commit()
            except Exception:
                conn.rollback()
            continue
        prepared_map[ref] = prep
        requests_list.append(build_batch_request(prep))
        try:
            record_progress(conn, run_id, ref, "ocr_done")
            conn.commit()
        except Exception:
            conn.rollback()

    if not requests_list:
        log.warning("All pending filings failed OCR — nothing to submit.")
        return 0

    log.info("Submitting batch of %d to Anthropic...", len(requests_list))
    submit_ts = time.monotonic()
    batch = client.messages.batches.create(requests=requests_list)
    log.info("Batch id=%s status=%s", batch.id, batch.processing_status)

    deadline = submit_ts + poll_max_hours * 3600
    final_batch = batch
    while time.monotonic() < deadline:
        time.sleep(poll_interval_sec)
        current = client.messages.batches.retrieve(batch.id)
        log.info("Poll: status=%s counts=%s",
                 current.processing_status, current.request_counts)
        final_batch = current
        if current.processing_status == "ended":
            break

    if final_batch.processing_status != "ended":
        log.warning(
            "Batch %s did not end within %dh — the checkpoint stays at 'ocr_done', "
            "next cycle picks it up.", final_batch.id, poll_max_hours,
        )
        return 0

    events_inserted = 0
    filings_processed = 0
    for entry in client.messages.batches.results(final_batch.id):
        ref = entry.custom_id
        prepared = prepared_map.get(ref)
        if prepared is None:
            continue
        if entry.result.type != "succeeded":
            err = str(getattr(entry.result, "error", "unknown"))
            try:
                record_progress(conn, run_id, ref, "failed", err[:500])
                conn.commit()
            except Exception:
                conn.rollback()
            continue
        events = extract_tool_use_events(entry.result.message.content)
        try:
            inserted = persist_events(conn, prepared, events, extraction_model=HAIKU_ANTHROPIC)
            record_progress(conn, run_id, ref, "extracted")
            conn.commit()
            events_inserted += inserted
            filings_processed += 1
        except Exception as e:
            conn.rollback()
            log.exception("Persist failed for %s", ref)
            try:
                record_progress(conn, run_id, ref, "failed",
                                f"persist:{type(e).__name__}")
                conn.commit()
            except Exception:
                conn.rollback()

    log.info("")
    log.info("Batch cycle complete.  filings=%d  events=%d", filings_processed, events_inserted)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lookback-hours", type=int, default=72,
                   help="Look back this many hours for newly-loaded publications.")
    p.add_argument("--cap", type=int, default=5000)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--poll-interval-sec", type=int, default=60)
    p.add_argument("--poll-max-hours", type=int, default=18)
    p.add_argument("--run-id", type=str,
                   default=f"every2d-{datetime.utcnow():%Y%m%d}")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    return asyncio.run(run(
        lookback_hours=args.lookback_hours,
        cap=args.cap,
        workers=args.workers,
        poll_interval_sec=args.poll_interval_sec,
        poll_max_hours=args.poll_max_hours,
        run_id=args.run_id,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
