"""Phase 5.0 — unified-summary backfill helper.

The Phase 5.0 schema is now owned by tracked migrations. This script remains
as the data backfill and verification helper for `company_enrichment`.

Run inside the enrichment-worker container so DATABASE_URL is in env.

Usage:
    python /app/scripts/migrate_phase_5_0.py --phase schema   # verify schema
    python /app/scripts/migrate_phase_5_0.py --phase backfill --limit 1000   # smoke
    python /app/scripts/migrate_phase_5_0.py --phase backfill   # full
    python /app/scripts/migrate_phase_5_0.py --phase verify    # post-checks
    python /app/scripts/migrate_phase_5_0.py --phase rollback   # disabled; schema is migration-owned
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import psycopg2


CONSTRAINT_NAME = "enrichment_quality_tier_check"
INDEX_NAME = "idx_enrichment_quality_tier"
FUNCTION_NAME = "try_parse_jsonb"

REQUIRED_COLUMNS = {
    "unified_summary",
    "quality_tier",
    "quality_tier_at",
    "model_chain",
    "bulk_website_text",
    "bulk_website_text_at",
}


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
    print("\n=== schema verification ===", flush=True)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'company_enrichment'
                """
            )
            present_columns = {row[0] for row in cur.fetchall()}
            missing_columns = sorted(REQUIRED_COLUMNS - present_columns)
            if missing_columns:
                sys.exit(f"schema: missing columns: {', '.join(missing_columns)}")
            print("  required columns: ok", flush=True)

            if not constraint_exists(cur, CONSTRAINT_NAME):
                sys.exit(f"schema: missing constraint: {CONSTRAINT_NAME}")
            print("  quality_tier check constraint: ok", flush=True)

            cur.execute(
                """
                SELECT 1
                  FROM pg_indexes
                 WHERE schemaname = 'public'
                   AND tablename = 'company_enrichment'
                   AND indexname = %s
                """,
                (INDEX_NAME,),
            )
            if cur.fetchone() is None:
                sys.exit(f"schema: missing index: {INDEX_NAME}")
            print("  quality_tier index: ok", flush=True)

            cur.execute("SELECT to_regprocedure(%s)", (f"{FUNCTION_NAME}(text)",))
            if cur.fetchone()[0] is None:
                sys.exit(f"schema: missing function: {FUNCTION_NAME}(text)")
            print("  try_parse_jsonb(text): ok", flush=True)
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
    sys.exit("rollback disabled: Phase 5.0 schema is owned by tracked migrations")


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
