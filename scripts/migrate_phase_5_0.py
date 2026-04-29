"""Phase 5.0 — unified-summary schema migration.

Additive only. Reversible. Idempotent.

Adds 6 columns + 1 check constraint + 1 index to `company_enrichment`,
plus a small `try_parse_jsonb()` helper function. Backfills `unified_summary`
from existing `ai_insights` (preferred) or `bulk_summary` (fallback) in
batches.

Run inside the enrichment-worker container so DATABASE_URL is in env.

Usage:
    python /app/scripts/migrate_phase_5_0.py --phase schema   # add columns/index/fn
    python /app/scripts/migrate_phase_5_0.py --phase backfill --limit 1000   # smoke
    python /app/scripts/migrate_phase_5_0.py --phase backfill   # full
    python /app/scripts/migrate_phase_5_0.py --phase verify    # post-checks
    python /app/scripts/migrate_phase_5_0.py --phase rollback   # drop the additions
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import psycopg2
from psycopg2 import sql


SCHEMA_STATEMENTS: list[tuple[str, str]] = [
    (
        "add unified_summary column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS unified_summary JSONB",
    ),
    (
        "add quality_tier column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS quality_tier TEXT",
    ),
    (
        "add quality_tier_at column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS quality_tier_at TIMESTAMPTZ",
    ),
    (
        "add model_chain column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS model_chain JSONB",
    ),
    (
        "add bulk_website_text column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS bulk_website_text TEXT",
    ),
    (
        "add bulk_website_text_at column",
        "ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS bulk_website_text_at TIMESTAMPTZ",
    ),
]

CONSTRAINT_NAME = "enrichment_quality_tier_check"

CHECK_CONSTRAINT_SQL = """
ALTER TABLE company_enrichment
ADD CONSTRAINT enrichment_quality_tier_check
CHECK (quality_tier IS NULL OR quality_tier IN
  ('bulk_only', 'bulk_escalated', 'narrative_lite', 'narrative_full'))
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_enrichment_quality_tier
ON company_enrichment (quality_tier, quality_tier_at)
"""

TRY_PARSE_FN_SQL = """
CREATE OR REPLACE FUNCTION try_parse_jsonb(t text) RETURNS jsonb AS $$
BEGIN
  RETURN t::jsonb;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE
"""

ROLLBACK_STATEMENTS: list[tuple[str, str]] = [
    ("drop index", "DROP INDEX IF EXISTS idx_enrichment_quality_tier"),
    (
        "drop check constraint",
        "ALTER TABLE company_enrichment DROP CONSTRAINT IF EXISTS enrichment_quality_tier_check",
    ),
    ("drop bulk_website_text_at", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS bulk_website_text_at"),
    ("drop bulk_website_text", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS bulk_website_text"),
    ("drop model_chain", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS model_chain"),
    ("drop quality_tier_at", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS quality_tier_at"),
    ("drop quality_tier", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS quality_tier"),
    ("drop unified_summary", "ALTER TABLE company_enrichment DROP COLUMN IF EXISTS unified_summary"),
    ("drop try_parse_jsonb", "DROP FUNCTION IF EXISTS try_parse_jsonb(text)"),
]


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not in env")
    return psycopg2.connect(url)


def run_statement(cur, label: str, sql_text: str) -> None:
    t = time.monotonic()
    cur.execute(sql_text)
    dt = (time.monotonic() - t) * 1000
    print(f"  {label}: ok ({dt:.0f} ms)", flush=True)


def constraint_exists(cur, name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.table_constraints
         WHERE table_name = 'company_enrichment' AND constraint_name = %s
        """,
        (name,),
    )
    return cur.fetchone() is not None


def phase_schema() -> None:
    print("\n=== schema additions ===", flush=True)
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for label, stmt in SCHEMA_STATEMENTS:
                run_statement(cur, label, stmt)
            if constraint_exists(cur, CONSTRAINT_NAME):
                print(f"  add quality_tier check constraint: skipped (already exists)", flush=True)
            else:
                run_statement(cur, "add quality_tier check constraint", CHECK_CONSTRAINT_SQL)
            run_statement(cur, "create idx_enrichment_quality_tier", INDEX_SQL)
            run_statement(cur, "create try_parse_jsonb fn", TRY_PARSE_FN_SQL)
        conn.commit()
        print("schema: committed", flush=True)
    except Exception as e:
        conn.rollback()
        sys.exit(f"schema: rolled back: {e!r}")
    finally:
        conn.close()


def count_pending(cur, only_unbackfilled: bool = True) -> int:
    where = """
        WHERE (ai_insights IS NOT NULL AND ai_insights <> ''
               OR bulk_summary IS NOT NULL)
    """
    if only_unbackfilled:
        where += " AND unified_summary IS NULL"
    cur.execute(f"SELECT COUNT(*) FROM company_enrichment {where}")
    return cur.fetchone()[0]


def backfill_batch(cur, limit: int) -> int:
    """Backfill a batch. Returns number of rows updated."""
    cur.execute(
        """
        WITH targets AS (
          SELECT enterprise_number
            FROM company_enrichment
           WHERE unified_summary IS NULL
             AND (ai_insights IS NOT NULL AND ai_insights <> ''
                  OR bulk_summary IS NOT NULL)
           ORDER BY enterprise_number
           LIMIT %s
           FOR UPDATE SKIP LOCKED
        )
        UPDATE company_enrichment ce
           SET unified_summary = COALESCE(
                 try_parse_jsonb(ce.ai_insights),
                 ce.bulk_summary
               ),
               quality_tier = CASE
                 WHEN try_parse_jsonb(ce.ai_insights) IS NOT NULL THEN 'narrative_lite'
                 WHEN ce.bulk_summary IS NOT NULL                 THEN 'bulk_only'
                 ELSE NULL
               END,
               quality_tier_at = CASE
                 WHEN try_parse_jsonb(ce.ai_insights) IS NOT NULL THEN ce.generated_at
                 ELSE ce.bulk_summary_at
               END,
               model_chain = jsonb_build_array(
                 jsonb_build_object(
                   'step', 'legacy_backfill',
                   'source_column',
                     CASE WHEN try_parse_jsonb(ce.ai_insights) IS NOT NULL
                          THEN 'ai_insights' ELSE 'bulk_summary' END,
                   'completed_at', NOW()
                 )
               )
          FROM targets t
         WHERE ce.enterprise_number = t.enterprise_number
        """,
        (limit,),
    )
    return cur.rowcount


def phase_backfill(limit: int | None) -> None:
    print(f"\n=== backfill (batch limit={limit or 'unlimited'}) ===", flush=True)
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            initial_pending = count_pending(cur)
            print(f"  rows pending backfill: {initial_pending:,}", flush=True)
            if initial_pending == 0:
                print("  nothing to do", flush=True)
                return

            batch_size = limit if (limit and limit < 50_000) else 50_000
            total_done = 0
            while True:
                t = time.monotonic()
                done = backfill_batch(cur, batch_size)
                conn.commit()
                dt = time.monotonic() - t
                if done == 0:
                    break
                total_done += done
                print(f"  batch: +{done:,} rows in {dt:.1f}s (cumulative {total_done:,})", flush=True)
                if limit is not None and total_done >= limit:
                    break

            remaining = count_pending(cur)
            print(f"  done: {total_done:,} rows updated; {remaining:,} still pending", flush=True)
    except Exception as e:
        conn.rollback()
        sys.exit(f"backfill: rolled back: {e!r}")
    finally:
        conn.close()


VERIFY_QUERIES: list[tuple[str, str]] = [
    (
        "rows still missing unified_summary despite having a legacy summary",
        """
        SELECT COUNT(*) FROM company_enrichment
         WHERE unified_summary IS NULL
           AND (ai_insights IS NOT NULL AND ai_insights <> ''
                OR bulk_summary IS NOT NULL)
        """,
    ),
    (
        "tier distribution",
        """
        SELECT COALESCE(quality_tier, '(null)') AS tier, COUNT(*)
          FROM company_enrichment
         GROUP BY 1 ORDER BY 2 DESC
        """,
    ),
    (
        "tier set without unified_summary (should be 0)",
        """
        SELECT COUNT(*) FROM company_enrichment
         WHERE quality_tier IS NOT NULL AND unified_summary IS NULL
        """,
    ),
    (
        "ai_insights rows with malformed JSON (couldn't be parsed)",
        """
        SELECT COUNT(*) FROM company_enrichment
         WHERE ai_insights IS NOT NULL AND ai_insights <> ''
           AND try_parse_jsonb(ai_insights) IS NULL
        """,
    ),
    (
        "model_chain populated count",
        "SELECT COUNT(*) FROM company_enrichment WHERE model_chain IS NOT NULL",
    ),
]


def phase_verify() -> None:
    print("\n=== verification ===", flush=True)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for label, q in VERIFY_QUERIES:
                cur.execute(q)
                rows = cur.fetchall()
                if len(rows) == 1 and len(rows[0]) == 1:
                    print(f"  {label}: {rows[0][0]:,}", flush=True)
                else:
                    print(f"  {label}:", flush=True)
                    for row in rows:
                        print(f"    {row}", flush=True)
    finally:
        conn.close()


def phase_rollback() -> None:
    print("\n=== rollback (drop everything Phase 5.0 added) ===", flush=True)
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for label, stmt in ROLLBACK_STATEMENTS:
                run_statement(cur, label, stmt)
        conn.commit()
        print("rollback: committed", flush=True)
    except Exception as e:
        conn.rollback()
        sys.exit(f"rollback: rolled back: {e!r}")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True,
                    choices=("schema", "backfill", "verify", "rollback"))
    ap.add_argument("--limit", type=int, default=None,
                    help="cap rows to update in backfill phase (omit for full backfill)")
    args = ap.parse_args()

    if args.phase == "schema":
        phase_schema()
    elif args.phase == "backfill":
        phase_backfill(args.limit)
    elif args.phase == "verify":
        phase_verify()
    elif args.phase == "rollback":
        phase_rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
