#!/usr/bin/env python3
"""Refresh company_popularity from the last N days of activity_log.

Ranking signal used by `/api/companies/search` — adds a small multiplier
to results the user base has been clicking on recently. Counts DISTINCT
(user_email OR ip_hash, enterprise_number) hits on `/api/companies/{cbe}`
URLs so a single obsessive user can't inflate popularity.

Idempotent. Transactional. Runs nightly via cron. Safe to run ad-hoc.

Usage:
  python scripts/refresh_popularity.py [--lookback-days 28]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make `backend` importable so we share the same db pool / env config.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from db import execute, fetch_one  # noqa: E402


def main(lookback_days: int = 28) -> int:
    logger = logging.getLogger(__name__)
    logger.info("refreshing company_popularity (lookback=%d days)", lookback_days)

    # Aggregate click counts per CBE from activity_log.
    # - endpoint LIKE '/api/companies/{10 digits}(/|$)' filters to
    #   company-profile hits (not /search, /semantic, etc).
    # - COUNT(DISTINCT user_key) — a single user visiting 50 times
    #   still counts as 1.
    execute(
        """
        INSERT INTO company_popularity (enterprise_number, click_count, updated_at)
        SELECT cbe,
               COUNT(DISTINCT user_key)::int AS click_count,
               NOW()
        FROM (
            -- Anonymous requests already carry `anon:<ip_hash>` in
            -- `user_email`. The `activity_log` schema has no separate
            -- `ip_hash` column (see backend/main.py ActivityLog middleware).
            SELECT substring(endpoint FROM '/api/companies/([0-9]{10})') AS cbe,
                   COALESCE(user_email, 'anon') AS user_key
            FROM activity_log
            WHERE created_at >= NOW() - (%s || ' days')::interval
              AND endpoint ~ '^/api/companies/[0-9]{10}(/|$)'
        ) hits
        WHERE cbe IS NOT NULL
        GROUP BY cbe
        ON CONFLICT (enterprise_number) DO UPDATE
          SET click_count = EXCLUDED.click_count,
              updated_at  = EXCLUDED.updated_at
        """,
        (lookback_days,),
    )

    # Decay rows that haven't been seen in 2× the window — they're
    # stale enough to zero out. This keeps ranking from being dominated
    # forever by ancient popularity.
    execute(
        """
        UPDATE company_popularity
        SET click_count = 0,
            updated_at  = NOW()
        WHERE updated_at < NOW() - (%s || ' days')::interval * 2
          AND click_count > 0
        """,
        (lookback_days,),
    )

    total = fetch_one(
        "SELECT COUNT(*) AS n FROM company_popularity WHERE click_count > 0"
    )
    top5 = fetch_one(
        "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) AS top "
        "FROM (SELECT enterprise_number, click_count "
        "      FROM company_popularity ORDER BY click_count DESC LIMIT 5) t"
    )
    logger.info(
        "popularity refreshed: %d non-zero rows; top5=%s",
        total["n"] if total else 0,
        top5["top"] if top5 else "[]",
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(
        description="Refresh company_popularity from activity_log."
    )
    ap.add_argument(
        "--lookback-days",
        type=int,
        default=28,
        help="How many days of history to aggregate (default: 28).",
    )
    args = ap.parse_args()
    sys.exit(main(args.lookback_days))
