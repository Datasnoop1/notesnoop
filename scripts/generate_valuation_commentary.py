"""Pre-generate valuation AI commentary for a batch of CBEs nightly.

Scoped to companies with:
  - a recent financial filing (financial_latest row)
  - no commentary in cache yet, OR commentary older than 90 days
  - prioritised by "favourited by ≥1 user" then "viewed in the last 30 days"

Keeps LLM cost bounded via --max-calls. Cached rows land in
valuation_commentary_cache; the admin primer PDF + on-screen valuation
tab both read from this cache.

Run via cron nightly:
    30 5 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        python /app/../scripts/generate_valuation_commentary.py \
        --max-calls 50 \
        >> scripts/_watchdog_state/valuation_commentary.log 2>&1
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import execute, fetch_all  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("val_commentary")


def candidates(limit: int) -> list[str]:
    """Pick the next CBEs to generate for.
    Priority: favourited (any user) → recently viewed → others.
    Excludes: companies with commentary generated in last 90 days.
    """
    rows = fetch_all(
        """
        WITH fav_ents AS (
            SELECT DISTINCT enterprise_number FROM favourite
        ),
        viewed_ents AS (
            SELECT DISTINCT enterprise_number
            FROM company_view_history
            WHERE last_viewed_at > NOW() - INTERVAL '30 days'
        ),
        ranked AS (
            SELECT fl.enterprise_number,
                   CASE
                     WHEN fe.enterprise_number IS NOT NULL THEN 1
                     WHEN ve.enterprise_number IS NOT NULL THEN 2
                     ELSE 3
                   END AS prio,
                   fl.total_assets
            FROM financial_latest fl
            LEFT JOIN fav_ents fe ON fe.enterprise_number = fl.enterprise_number
            LEFT JOIN viewed_ents ve ON ve.enterprise_number = fl.enterprise_number
            LEFT JOIN valuation_commentary_cache vcc
                ON vcc.enterprise_number = fl.enterprise_number
                AND vcc.generated_at > NOW() - INTERVAL '90 days'
            WHERE vcc.enterprise_number IS NULL
              AND fl.revenue IS NOT NULL
              AND fl.ebitda IS NOT NULL
        )
        SELECT enterprise_number
        FROM ranked
        ORDER BY prio, total_assets DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )
    return [r["enterprise_number"] for r in rows]


async def _generate_one(cbe: str) -> bool:
    """Returns True on success. Swallow LLM errors so one bad company
    doesn't kill the run. Calls the PLAIN-Python worker (not the FastAPI
    route handler) so Query() defaults don't leak into the call."""
    from routers.companies.valuation import _generate_and_cache_valuation_commentary  # type: ignore
    try:
        res = await _generate_and_cache_valuation_commentary(cbe=cbe)
        return bool(res.get("commentary") if isinstance(res, dict) else False)
    except Exception as e:
        log.warning("commentary generation failed for %s: %s", cbe, e)
        return False


async def main_async(max_calls: int) -> None:
    cbes = candidates(max_calls)
    log.info("generating valuation commentary for %d companies", len(cbes))
    ok = 0
    for cbe in cbes:
        if await _generate_one(cbe):
            ok += 1
        # modest pacing: LLM is cheap but OpenRouter has per-org rate limits
        await asyncio.sleep(1)
    log.info("valuation commentary: %d/%d generated", ok, len(cbes))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=50,
                    help="Max companies to generate for per run (default 50)")
    args = ap.parse_args()
    asyncio.run(main_async(args.max_calls))
