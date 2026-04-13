"""Dashboard router — KPI stats for the home page."""

import logging
from fastapi import APIRouter, HTTPException

from db import fetch_one, fetch_all

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard():
    """Return KPI stats using fast pre-computed tables (not slow COUNT on raw data)."""
    try:
        # Use pg_stat estimated counts (instant) instead of COUNT(*) (slow full scan)
        stats = fetch_one("""
            SELECT
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'enterprise') AS enterprise_count,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_latest') AS financial_count,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_by_year') AS filing_count,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'administrator') AS admin_count,
                (SELECT value FROM meta WHERE variable = 'SnapshotDate') AS snapshot_date
        """)

        return {
            "enterprise_count": stats["enterprise_count"] or 0,
            "financial_count": stats["financial_count"] or 0,
            "filing_count": stats["filing_count"] or 0,
            "admin_count": stats["admin_count"] or 0,
            "snapshot_date": stats["snapshot_date"],
        }
    except Exception as e:
        logger.exception("Dashboard query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-companies")
async def get_top_companies(metric: str = "revenue", limit: int = 15):
    """Return top companies ranked by a given metric."""
    allowed_metrics = {"revenue", "ebitda", "fte_total"}
    if metric not in allowed_metrics:
        raise HTTPException(status_code=400, detail=f"metric must be one of {allowed_metrics}")
    if limit < 1 or limit > 100:
        limit = 15

    try:
        rows = fetch_all(f"""
            SELECT fl.enterprise_number,
                   COALESCE(ci.name, fl.enterprise_number) AS "name",
                   fl.{metric} AS "metric_value",
                   fl.ebitda,
                   fl.revenue,
                   CASE WHEN fl.revenue > 0
                        THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                   END AS "margin",
                   fl.fte_total,
                   fl.fiscal_year,
                   ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS "sector",
                   ci.city
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE fl.{metric} IS NOT NULL AND fl.{metric} > 0
            ORDER BY fl.{metric} DESC
            LIMIT %s
        """, (limit,))
        return rows
    except Exception as e:
        logger.exception("Top companies query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recently-loaded")
async def get_recently_loaded(limit: int = 10):
    """Return recently loaded financials."""
    if limit < 1 or limit > 50:
        limit = 10

    try:
        rows = fetch_all("""
            SELECT fl.enterprise_number,
                   COALESCE(ci.name, fl.enterprise_number) AS "name",
                   fl.revenue, fl.ebitda, fl.fiscal_year, n.loaded_at
            FROM financial_latest fl
            JOIN (
                SELECT enterprise_number, MAX(loaded_at) AS loaded_at
                FROM nbb_load_log
                WHERE deposit_key != 'NO_FILINGS'
                GROUP BY enterprise_number
            ) n ON n.enterprise_number = fl.enterprise_number
            LEFT JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            ORDER BY n.loaded_at DESC
            LIMIT %s
        """, (limit,))

        for row in rows:
            if row.get("loaded_at"):
                row["loaded_at"] = str(row["loaded_at"])

        return rows
    except Exception as e:
        logger.exception("Recently loaded query failed")
        raise HTTPException(status_code=500, detail=str(e))
