"""Seed the `enrichment_job` queue for the bulk-enrichment worker.

Usage (from inside the backend container, or with DATABASE_URL set):

  # Pilot (Phase 2): 500 diverse tier-1 CBEs
  python scripts/seed_enrichment_queue.py --scope pilot --limit 500

  # Tier-1 + tier-2 (Phase 3)
  python scripts/seed_enrichment_queue.py --scope tier1_2

  # Tier-3 with a KBO website on file
  python scripts/seed_enrichment_queue.py --scope tier3_web

  # Tier-3 without a website — discovery-first
  python scripts/seed_enrichment_queue.py --scope tier3_no_web --limit 1000

  # Dry run (count only, no inserts)
  python scripts/seed_enrichment_queue.py --scope pilot --dry-run

Priorities (see `backend/enrichment_routing.py`):
    tier1=100, tier2=50, tier3_web=20, tier3_no_web=10, template=5

The worker claims highest priority first; the pilot scope intentionally
spreads across buckets so the operator can eyeball quality per tier in
one run.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Allow `python scripts/seed_enrichment_queue.py` from repo root by
# appending backend/ to sys.path so `db` and `enrichment_queue` resolve.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from db import fetch_all  # noqa: E402
from enrichment_queue import bulk_enqueue, ensure_schema  # noqa: E402
from enrichment_routing import (  # noqa: E402
    PRIORITY_TIER1, PRIORITY_TIER2, PRIORITY_TIER3_WEB, PRIORITY_TIER3_NOWEB,
    PRIORITY_TEMPLATE,
)


SCOPE_SQL = {
    "pilot": """
        -- Spread across buckets for Phase 2 smoke-test.
        (
            SELECT ci.enterprise_number,
                   CASE
                       WHEN COALESCE(fl.revenue, 0) >= 50000000 THEN {tier1}
                       WHEN COALESCE(fl.revenue, 0) >= 5000000  THEN {tier2}
                       WHEN has_web                            THEN {t3w}
                       ELSE {t3nw}
                   END AS priority
              FROM company_info ci
              JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
         LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        CROSS JOIN LATERAL (
                 SELECT EXISTS (
                    SELECT 1 FROM contact c
                     WHERE c.entity_number = ci.enterprise_number
                       AND c.contact_type = 'WEB'
                 ) AS has_web
             ) t
             WHERE e.status = 'AC'
               AND e.juridical_situation = '000'
               AND e.type_of_enterprise = '2'
               AND (has_web OR COALESCE(fl.revenue, 0) > 0)
          ORDER BY md5(ci.enterprise_number || 'seed-phase2')
             LIMIT %s
        )
    """,
    "tier1_2": """
        (
            SELECT ci.enterprise_number,
                   CASE
                       WHEN COALESCE(fl.revenue, 0) >= 50000000 THEN {tier1}
                       ELSE {tier2}
                   END AS priority
              FROM company_info ci
              JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
         LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
             WHERE e.status = 'AC'
               AND e.juridical_situation = '000'
               AND COALESCE(fl.revenue, 0) >= 1000000
        )
    """,
    "tier3_web": """
        (
            SELECT ci.enterprise_number, {t3w} AS priority
              FROM company_info ci
              JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
             WHERE e.status = 'AC'
               AND e.juridical_situation = '000'
               AND EXISTS (
                    SELECT 1 FROM contact c
                     WHERE c.entity_number = ci.enterprise_number
                       AND c.contact_type = 'WEB'
               )
        )
    """,
    "tier3_no_web": """
        (
            SELECT ci.enterprise_number, {t3nw} AS priority
              FROM company_info ci
              JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
             WHERE e.status = 'AC'
               AND e.juridical_situation = '000'
               AND NOT EXISTS (
                    SELECT 1 FROM contact c
                     WHERE c.entity_number = ci.enterprise_number
                       AND c.contact_type = 'WEB'
               )
        )
    """,
    "template": """
        (
            SELECT ci.enterprise_number, {tpl} AS priority
              FROM company_info ci
              JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
             WHERE e.status != 'AC' OR e.juridical_situation != '000'
        )
    """,
}


def _render_scope(scope: str) -> str:
    sql = SCOPE_SQL[scope].format(
        tier1=PRIORITY_TIER1, tier2=PRIORITY_TIER2,
        t3w=PRIORITY_TIER3_WEB, t3nw=PRIORITY_TIER3_NOWEB,
        tpl=PRIORITY_TEMPLATE,
    )
    return sql.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", required=True, choices=list(SCOPE_SQL.keys()))
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of rows inserted (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ensure_schema()

    inner = _render_scope(args.scope)
    sql = f"SELECT enterprise_number, priority FROM {inner} AS sub"
    params: list = []
    if args.scope == "pilot":
        # The pilot scope has its own LIMIT placeholder inside the
        # SELECT; inject via params.
        params.append(int(args.limit or 500))
    if args.limit is not None and args.scope != "pilot":
        sql += " LIMIT %s"
        params.append(int(args.limit))

    print(f"scope={args.scope} limit={args.limit} dry_run={args.dry_run}")
    t0 = time.monotonic()
    rows = fetch_all(sql, params or None)
    elapsed = time.monotonic() - t0
    print(f"selected {len(rows)} candidates in {elapsed:.1f}s")

    if args.dry_run:
        buckets: dict[int, int] = {}
        for r in rows:
            buckets[r["priority"]] = buckets.get(r["priority"], 0) + 1
        for pri in sorted(buckets, reverse=True):
            print(f"  priority {pri}: {buckets[pri]} rows")
        return 0

    pairs = [(r["enterprise_number"], int(r["priority"])) for r in rows]
    inserted = bulk_enqueue(pairs)
    print(f"inserted {inserted} new jobs (skipped {len(pairs) - inserted} already-queued)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
