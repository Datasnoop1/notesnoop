"""Staatsblad structured-event backfill (Phase 4a/4b).

Submits Staatsblad publications in chunks to Anthropic's batch API
(50% discount) and writes the parsed events to Postgres. Resume-safe
via `staatsblad_backfill_progress` and cost-guarded against a
`--max-spend-usd` cap.

Usage:
    python scripts/staatsblad_backfill.py \
        --since-date 2025-04-18 \
        --run-id phase4a \
        --max-spend-usd 180 \
        --batch-size 500 \
        --pub-types ONTSLAGEN-BENOEMINGEN,NOMINATIONS-DEMISSIONS,...

The script runs in a single process; when --workers > 1 we fan PDF
preparation (download + OCR) across threads but the batch submission
itself is serial, because each chunk must persist its results before
the next runs (so a mid-run halt leaves a clean checkpoint).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from staatsblad_extraction.extractor import (  # noqa: E402
    HAIKU_ANTHROPIC,
    STAATSBLAD_TOOL_DEFINITION_V3,
    build_batch_request,
    check_anthropic_balance,
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
log = logging.getLogger("staatsblad-backfill")


# Per-spec default pub_types: filings that typically carry board-level
# or capital events. We include a wide set because the operator asked
# for full 8-category coverage (not just admin events).
DEFAULT_PUB_TYPES = ",".join([
    "ONTSLAGEN-BENOEMINGEN",
    "ONTSLAGEN - BENOEMINGEN",
    "NOMINATIONS-DEMISSIONS",
    "NOMINATIONS - DEMISSIONS",
    "BENOEMINGEN",
    "ONTSLAGEN",
    "NOMINATIONS",
    "DEMISSIONS",
    "KAPITAAL",
    "CAPITAL",
    "FUSIE",
    "FUSION",
    "SPLITSING",
    "SCISSION",
    "ONTBINDING",
    "DISSOLUTION",
    "VEREFFENING",
    "LIQUIDATION",
    "STATUTEN",
    "STATUTS",
    "AANDELEN",
    "ACTIONS",
    "NAAMSWIJZIGING",
    "DENOMINATION",
    "OMZETTING",
    "TRANSFORMATION",
    "ZETEL",
    "SIEGE",
])


# Per-filing unit cost guesstimate from pilot: ~$0.0013 with batch +
# caching, aggressive sectioner, V5 prompt.  Used as a floor for the
# cost-guard check when the Anthropic balance endpoint doesn't return
# anything useful.
PER_FILING_COST_FLOOR_USD = 0.0015


def db_conn():
    """Lazy import + connect to Postgres via the backend's db helper."""
    # Import here so the module can be imported without a live DB
    # (unit tests, dry-run).
    from db import get_connection  # type: ignore
    return get_connection()


async def _prepare_one(pub_row: dict) -> dict | None:
    """Async wrapper for prepare_filing — returns a dict containing the
    prepared filing fields ready to build a batch request, or None."""
    prepared = await prepare_filing(pub_row)
    if not prepared:
        return None
    return {
        "prepared": prepared,
        "batch_request": build_batch_request(prepared),
    }


def _fetch_candidate_publications(
    conn,
    since_date: date,
    pub_types: list[str],
    run_id: str,
    limit: int | None,
) -> list[dict]:
    """SELECT publications within window that haven't been processed yet
    in this run.  We filter by (a) pub_type ILIKE any of the input list,
    (b) no entry in staatsblad_backfill_progress with status='extracted',
    (c) no entry in staatsblad_event (safety net against a re-run that
    didn't record progress).

    Ordered pub_date DESC so the freshest filings land first; if a run
    halts early the operator still gets recent data.
    """
    patterns = [f"%{t.strip()}%" for t in pub_types if t.strip()]
    cur = conn.cursor()
    try:
        # Using ANY + ILIKE comparison: Postgres supports this via
        # array comparison with ILIKE ANY array.
        cur.execute(
            """WITH candidates AS (
                   SELECT sp.enterprise_number, sp.pub_date, sp.pub_type,
                          sp.reference, sp.pdf_url, sp.entity_name
                   FROM staatsblad_publication sp
                   WHERE sp.pub_date >= %s
                     AND sp.reference IS NOT NULL
                     AND sp.reference <> 'NO_DATA'
                     AND sp.pdf_url IS NOT NULL
                     AND sp.pub_type ILIKE ANY(%s::text[])
               )
               SELECT * FROM candidates c
               WHERE NOT EXISTS (
                   -- Only skip refs that fully completed (status='extracted').
                   -- An 'ocr_done' checkpoint means the chunk crashed after
                   -- OCR but before the batch persisted — we WANT to
                   -- re-process those on resume, so we exclude them from
                   -- the "skip" clause.
                   SELECT 1 FROM staatsblad_backfill_progress p
                   WHERE p.run_id = %s AND p.pub_reference = c.reference
                     AND p.status = 'extracted'
               )
               AND NOT EXISTS (
                   SELECT 1 FROM staatsblad_event e
                   WHERE e.enterprise_number = c.enterprise_number
                     AND e.pub_reference = c.reference
               )
               ORDER BY c.pub_date DESC
               LIMIT %s""",
            (since_date, patterns, run_id, limit if limit else 10_000_000),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


def _estimate_chunk_cost_usd(n_filings: int) -> float:
    return n_filings * PER_FILING_COST_FLOOR_USD


def _format_halt_message(
    remaining_balance: float | None,
    next_chunk_cost: float,
    observed_spend: float,
    max_spend: float,
    run_id: str,
) -> str:
    lines = [
        "=" * 60,
        "STAATSBLAD BACKFILL HALTED — cost-guard trip",
        "=" * 60,
        f"Observed spend so far: ${observed_spend:.2f}",
        f"Max-spend cap:         ${max_spend:.2f}",
        f"Next chunk estimate:   ${next_chunk_cost:.2f}",
    ]
    if remaining_balance is not None:
        lines.append(f"Anthropic balance:     ${remaining_balance:.2f}")
    lines.append("")
    lines.append("To resume:")
    lines.append(
        f"  python scripts/staatsblad_backfill.py --run-id {run_id} "
        f"--since-date <same as before> --max-spend-usd <new cap>"
    )
    lines.append("=" * 60)
    return "\n".join(lines)


async def run_backfill(
    since_date: date,
    pub_types: list[str],
    run_id: str,
    batch_size: int,
    workers: int,
    max_spend_usd: float,
    poll_interval_sec: int,
    poll_max_hours: int,
    dry_run: bool,
    limit: int | None,
) -> int:
    """Main entry point.  Returns process exit code."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY not set")
        return 2

    conn = db_conn()
    conn.autocommit = False

    try:
        import anthropic  # defer import so --help works without the SDK
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except ImportError:
        log.error("anthropic SDK not installed — `pip install anthropic`")
        return 2

    observed_spend_usd = 0.0

    pubs = _fetch_candidate_publications(
        conn, since_date, pub_types, run_id, limit,
    )
    log.info(
        "Found %d candidate publications since %s (run_id=%s)",
        len(pubs), since_date, run_id,
    )
    if not pubs:
        log.info("Nothing to do — exiting cleanly.")
        return 0

    if dry_run:
        log.info("DRY RUN — would submit %d filings in %d batches",
                 len(pubs), (len(pubs) + batch_size - 1) // batch_size)
        return 0

    total_events = 0
    total_filings_processed = 0
    total_ocr_skipped = 0

    chunks = [pubs[i:i + batch_size] for i in range(0, len(pubs), batch_size)]
    for chunk_idx, chunk in enumerate(chunks, start=1):
        # ── Cost guard check ─────────────────────────────────
        next_chunk_cost = _estimate_chunk_cost_usd(len(chunk))
        if observed_spend_usd + next_chunk_cost > max_spend_usd:
            balance = check_anthropic_balance(os.environ["ANTHROPIC_API_KEY"])
            print(_format_halt_message(
                balance, next_chunk_cost, observed_spend_usd, max_spend_usd, run_id,
            ))
            return 1

        log.info(
            "Chunk %d/%d — %d filings  (spend so far $%.2f, chunk est $%.2f)",
            chunk_idx, len(chunks), len(chunk), observed_spend_usd, next_chunk_cost,
        )

        # ── Parallel PDF download + OCR ──────────────────────
        log.info("Preparing PDFs (%d workers)...", workers)
        sem = asyncio.Semaphore(workers)

        async def _bounded(pub):
            async with sem:
                return await _prepare_one(pub)

        prepared_results = await asyncio.gather(*[_bounded(p) for p in chunk])
        prepared_map: dict[str, dict] = {}
        requests_list: list[dict] = []
        for pub, res in zip(chunk, prepared_results):
            ref = pub.get("reference")
            if res is None:
                total_ocr_skipped += 1
                try:
                    record_progress(conn, run_id, ref, "failed", "prepare_failed")
                    conn.commit()
                except Exception:
                    conn.rollback()
                continue
            prepared_map[ref] = res["prepared"]
            requests_list.append(res["batch_request"])
            try:
                record_progress(conn, run_id, ref, "ocr_done")
                conn.commit()
            except Exception:
                conn.rollback()

        if not requests_list:
            log.warning("Chunk %d — all filings failed OCR, skipping submit", chunk_idx)
            continue

        # ── Submit batch ────────────────────────────────────
        log.info("Submitting batch of %d to Anthropic...", len(requests_list))
        submit_ts = time.monotonic()
        try:
            batch = client.messages.batches.create(requests=requests_list)
        except Exception as e:
            log.exception("Batch submit failed: %s", e)
            return 3

        log.info("Batch id=%s status=%s", batch.id, batch.processing_status)

        # ── Poll for completion ─────────────────────────────
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
            log.error(
                "Batch %s did not end within %d hours — halting with checkpoint at chunk %d",
                final_batch.id, poll_max_hours, chunk_idx,
            )
            return 4

        # ── Parse + persist ─────────────────────────────────
        chunk_events = 0
        chunk_input_tokens = 0
        chunk_cache_read = 0
        chunk_output = 0
        for entry in client.messages.batches.results(final_batch.id):
            ref = entry.custom_id
            prepared = prepared_map.get(ref)
            if prepared is None:
                log.warning("Unknown custom_id %s in batch results", ref)
                continue
            result_type = entry.result.type
            if result_type != "succeeded":
                err = str(getattr(entry.result, "error", "unknown"))
                try:
                    record_progress(conn, run_id, ref, "failed", err[:500])
                    conn.commit()
                except Exception:
                    conn.rollback()
                continue

            msg = entry.result.message
            usage = msg.usage
            chunk_input_tokens += getattr(usage, "input_tokens", 0) or 0
            chunk_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
            chunk_output += getattr(usage, "output_tokens", 0) or 0

            events = extract_tool_use_events(msg.content)
            try:
                inserted = persist_events(
                    conn, prepared, events, extraction_model=HAIKU_ANTHROPIC,
                )
                record_progress(conn, run_id, ref, "extracted")
                conn.commit()
                chunk_events += inserted
                total_filings_processed += 1
            except Exception as e:
                conn.rollback()
                log.exception("Persist failed for %s", ref)
                try:
                    record_progress(conn, run_id, ref, "failed",
                                    f"persist:{type(e).__name__}")
                    conn.commit()
                except Exception:
                    conn.rollback()

        # Translate the batch usage into a cost number for the guard.
        # Batch pricing: 50% of base. Haiku 4.5 base rates are $1/$5
        # per million in/out, cache-read $0.10 per million.
        non_cached_input = max(0, chunk_input_tokens - chunk_cache_read)
        chunk_cost = 0.5 * (
            non_cached_input * 1.00
            + chunk_cache_read * 0.10
            + chunk_output * 5.00
        ) / 1_000_000
        observed_spend_usd += chunk_cost
        cache_share = (chunk_cache_read / chunk_input_tokens) if chunk_input_tokens else 0
        log.info(
            "Chunk %d done — events=%d input=%d cache_read=%d (%.0f%%) out=%d cost=$%.4f",
            chunk_idx, chunk_events, chunk_input_tokens, chunk_cache_read,
            cache_share * 100, chunk_output, chunk_cost,
        )
        total_events += chunk_events

    log.info("")
    log.info("=" * 60)
    log.info("BACKFILL COMPLETE  run_id=%s", run_id)
    log.info("Candidates found:     %d", len(pubs))
    log.info("Filings processed:    %d", total_filings_processed)
    log.info("OCR/prep failures:    %d", total_ocr_skipped)
    log.info("Events inserted:      %d", total_events)
    log.info("Observed spend:       $%.2f (cap $%.2f)",
             observed_spend_usd, max_spend_usd)
    log.info("=" * 60)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since-date", type=str, required=True,
                   help="YYYY-MM-DD — earliest pub_date to include")
    p.add_argument("--run-id", type=str, required=True,
                   help="Unique identifier for this run — reused for resume")
    p.add_argument("--max-spend-usd", type=float, default=180.0,
                   help="Halt if next chunk would exceed this cumulative spend")
    p.add_argument("--batch-size", type=int, default=500,
                   help="Filings per Anthropic batch submission")
    p.add_argument("--workers", type=int, default=8,
                   help="Parallel PDF download + OCR workers per chunk")
    p.add_argument("--poll-interval-sec", type=int, default=30,
                   help="Seconds between batch-status polls")
    p.add_argument("--poll-max-hours", type=int, default=24,
                   help="Give up on a batch after this many hours")
    p.add_argument("--pub-types", type=str, default=DEFAULT_PUB_TYPES,
                   help="Comma-separated list of pub_type ILIKE patterns")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap total candidates (useful for smoke tests)")
    p.add_argument("--dry-run", action="store_true",
                   help="Just report candidate count; do not submit")
    args = p.parse_args()

    try:
        since_date = date.fromisoformat(args.since_date)
    except ValueError:
        log.error("--since-date must be YYYY-MM-DD")
        return 2

    return asyncio.run(run_backfill(
        since_date=since_date,
        pub_types=[t.strip() for t in args.pub_types.split(",") if t.strip()],
        run_id=args.run_id,
        batch_size=args.batch_size,
        workers=args.workers,
        max_spend_usd=args.max_spend_usd,
        poll_interval_sec=args.poll_interval_sec,
        poll_max_hours=args.poll_max_hours,
        dry_run=args.dry_run,
        limit=args.limit,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
