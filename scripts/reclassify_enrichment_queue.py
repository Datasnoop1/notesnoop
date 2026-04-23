"""Recompute queue priorities after an EBITDA fast-lane rule change.

Usage:

  python scripts/reclassify_enrichment_queue.py
  python scripts/reclassify_enrichment_queue.py --apply

The explicit operator rule is:
  known latest EBITDA < SEMANTIC_FASTLANE_EBITDA_FLOOR -> fast lane

This script mirrors that worker-side rule for the existing queue so the
backlog does not keep stale priorities after the routing change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

for env_path in (ROOT / ".env", ROOT / ".env.production"):
    if env_path.exists():
        load_dotenv(env_path)
        break

from db import fetch_one, transaction  # noqa: E402
from enrichment_routing import (  # noqa: E402
    FASTLANE_EBITDA_FLOOR,
    PRIORITY_TEMPLATE,
    PRIORITY_TIER1,
    PRIORITY_TIER2,
    PRIORITY_TIER3_NOWEB,
    PRIORITY_TIER3_WEB,
)
from semantic_bootstrap import ensure_semantic_schema  # noqa: E402


def _base_cte(status_filter_sql: str) -> str:
    return f"""
        WITH recomputed AS (
            SELECT
                j.enterprise_number,
                j.priority AS old_priority,
                CASE
                    WHEN COALESCE(e.status, '') <> 'AC'
                      OR COALESCE(e.juridical_situation, '') <> '000'
                        THEN {PRIORITY_TEMPLATE}
                    WHEN fl.ebitda IS NOT NULL AND fl.ebitda < %s
                        THEN {PRIORITY_TEMPLATE}
                    WHEN COALESCE(fl.revenue, 0) >= 50000000
                        THEN {PRIORITY_TIER1}
                    WHEN COALESCE(fl.revenue, 0) >= 5000000
                        THEN {PRIORITY_TIER2}
                    WHEN EXISTS (
                        SELECT 1
                          FROM contact c
                         WHERE c.entity_number = j.enterprise_number
                           AND c.contact_type = 'WEB'
                    )
                        THEN {PRIORITY_TIER3_WEB}
                    ELSE {PRIORITY_TIER3_NOWEB}
                END AS new_priority,
                fl.ebitda
            FROM enrichment_job j
            LEFT JOIN enterprise e
              ON e.enterprise_number = j.enterprise_number
            LEFT JOIN financial_latest fl
              ON fl.enterprise_number = j.enterprise_number
            WHERE {status_filter_sql}
        )
    """


def _counts_query(statuses: list[str]) -> tuple[str, tuple]:
    placeholders = ", ".join(["%s"] * len(statuses))
    cte = _base_cte(f"j.status IN ({placeholders})")
    sql = cte + """
        SELECT
            COUNT(*)::int AS scoped_jobs,
            COUNT(*) FILTER (
                WHERE ebitda IS NOT NULL AND ebitda < %s
            )::int AS explicit_fastlane_jobs,
            COUNT(*) FILTER (
                WHERE ebitda IS NOT NULL AND ebitda >= %s
            )::int AS known_quality_jobs,
            COUNT(*) FILTER (
                WHERE ebitda IS NULL
            )::int AS missing_ebitda_jobs,
            COUNT(*) FILTER (
                WHERE old_priority IS DISTINCT FROM new_priority
            )::int AS jobs_needing_update,
            COUNT(*) FILTER (
                WHERE new_priority = %s
            )::int AS target_template_priority_jobs
        FROM recomputed
    """
    params = (FASTLANE_EBITDA_FLOOR,) + tuple(statuses) + (
        FASTLANE_EBITDA_FLOOR,
        FASTLANE_EBITDA_FLOOR,
        FASTLANE_EBITDA_FLOOR,
        PRIORITY_TEMPLATE,
    )
    return sql, params


def _apply_query(statuses: list[str]) -> tuple[str, tuple]:
    placeholders = ", ".join(["%s"] * len(statuses))
    cte = _base_cte(f"j.status IN ({placeholders})")
    sql = cte + """
        UPDATE enrichment_job j
           SET priority = r.new_priority
          FROM recomputed r
         WHERE j.enterprise_number = r.enterprise_number
           AND j.priority IS DISTINCT FROM r.new_priority
    """
    params = (FASTLANE_EBITDA_FLOOR,) + tuple(statuses)
    return sql, params


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="write the recomputed priorities back to enrichment_job",
    )
    ap.add_argument(
        "--queued-only",
        action="store_true",
        help="limit the scope to queued jobs (default also updates claimed)",
    )
    args = ap.parse_args()

    ensure_semantic_schema()
    statuses = ["queued"] if args.queued_only else ["queued", "claimed"]

    counts_sql, counts_params = _counts_query(statuses)
    before = fetch_one(counts_sql, counts_params) or {}

    print(
        "scope=%s floor_eur=%.0f explicit_fastlane=%s missing_ebitda=%s "
        "known_quality=%s jobs_needing_update=%s"
        % (
            ",".join(statuses),
            FASTLANE_EBITDA_FLOOR,
            before.get("explicit_fastlane_jobs", 0),
            before.get("missing_ebitda_jobs", 0),
            before.get("known_quality_jobs", 0),
            before.get("jobs_needing_update", 0),
        )
    )

    if not args.apply:
        print("dry-run only; rerun with --apply to persist the new priorities")
        return 0

    apply_sql, apply_params = _apply_query(statuses)
    with transaction() as (_conn, cur):
        cur.execute(apply_sql, apply_params)
        updated = cur.rowcount

    print(f"updated {updated} queue rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
