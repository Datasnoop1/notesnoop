"""Screener router — filter, browse, and rank Belgian companies."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/screener", tags=["screener"])

SORT_OPTIONS = {
    "ebit_desc": "fl.ebit DESC NULLS LAST",
    "ebit_asc": "fl.ebit ASC NULLS LAST",
    "revenue_desc": "fl.revenue DESC NULLS LAST",
    "ebitda_desc": "fl.ebitda DESC NULLS LAST",
    "fte_desc": "fl.fte_total DESC NULLS LAST",
    "name_asc": "ci.name ASC NULLS LAST",
}


@router.get("")
async def screener(
    nace: Optional[str] = Query(None, description="NACE code prefix (e.g. 28, 461)"),
    zipcode: Optional[str] = Query(None, description="Zipcode prefix for province filter"),
    ebit_min: Optional[float] = Query(None, ge=0),
    ebit_max: Optional[float] = Query(None, ge=0),
    ebitda_min: Optional[float] = Query(None, ge=0),
    ebitda_max: Optional[float] = Query(None, ge=0),
    rev_min: Optional[float] = Query(None, ge=0),
    rev_max: Optional[float] = Query(None, ge=0),
    fte_min: Optional[float] = Query(None, ge=0),
    fte_max: Optional[float] = Query(None, ge=0),
    margin_min: Optional[float] = Query(None, ge=0),
    sort: str = Query("ebit_desc", description="Sort order"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Screen companies with dynamic WHERE clause filters.

    Exact SQL extracted from app/pages/1_screener.py run_query().
    """
    sort_sql = SORT_OPTIONS.get(sort, "fl.ebit DESC")

    conditions = []
    params = []

    if nace:
        conditions.append("ci.nace_code LIKE %s")
        params.append(f"{nace}%")
    if zipcode:
        conditions.append("ci.zipcode LIKE %s")
        params.append(f"{zipcode}%")
    if ebit_min is not None:
        conditions.append("fl.ebit >= %s")
        params.append(ebit_min)
    if ebit_max is not None:
        conditions.append("fl.ebit <= %s")
        params.append(ebit_max)
    if ebitda_min is not None:
        conditions.append("fl.ebitda >= %s")
        params.append(ebitda_min)
    if ebitda_max is not None:
        conditions.append("fl.ebitda <= %s")
        params.append(ebitda_max)
    if rev_min is not None:
        conditions.append("fl.revenue >= %s")
        params.append(rev_min)
    if rev_max is not None:
        conditions.append("fl.revenue <= %s")
        params.append(rev_max)
    if fte_min is not None:
        conditions.append("fl.fte_total >= %s")
        params.append(fte_min)
    if fte_max is not None:
        conditions.append("fl.fte_total <= %s")
        params.append(fte_max)
    if margin_min is not None:
        conditions.append("fl.revenue > 0")
        conditions.append("(fl.ebitda / fl.revenue * 100) >= %s")
        params.append(margin_min)

    where = (" AND " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT fl.enterprise_number AS "cbe",
               ci.name AS "name",
               COALESCE(nl.description, ci.nace_code) AS "nace",
               ci.city AS "city",
               fl.fiscal_year AS "fiscal_year",
               fl.revenue AS "revenue",
               fl.ebit AS "ebit",
               fl.ebitda AS "ebitda",
               CASE WHEN fl.revenue > 0
                    THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
               END AS "margin_pct",
               fl.net_profit AS "net_profit",
               fl.fte_total AS "fte"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE 1=1 {where}
        ORDER BY {sort_sql}
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(sql, tuple(params))

        # Convert Decimals to floats for JSON serialization
        for row in rows:
            for key in ("revenue", "ebit", "ebitda", "margin_pct", "net_profit", "fte"):
                if row.get(key) is not None:
                    row[key] = float(row[key])

        return rows
    except Exception as e:
        logger.exception("Screener query failed")
        raise HTTPException(status_code=500, detail=str(e))
