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


@router.get("/nace-suggestions")
async def nace_suggestions(q: str = Query("", min_length=1)):
    """Return NACE codes matching the query (code or description)."""
    rows = fetch_all("""
        SELECT nace_code, description, company_count
        FROM nace_lookup
        WHERE nace_code ILIKE %s OR description ILIKE %s
        ORDER BY company_count DESC NULLS LAST
        LIMIT 20
    """, (f"%{q}%", f"%{q}%"))
    return rows


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
    nd_ebitda_max: Optional[float] = Query(None, description="Max Net Debt / EBITDA ratio"),
    rev_growth_min: Optional[float] = Query(None, description="Min revenue growth % YoY"),
    rev_growth_max: Optional[float] = Query(None, description="Max revenue growth % YoY"),
    ebitda_growth_min: Optional[float] = Query(None, description="Min EBITDA growth % YoY"),
    ebitda_growth_max: Optional[float] = Query(None, description="Max EBITDA growth % YoY"),
    assets_growth_min: Optional[float] = Query(None, description="Min total assets growth % YoY"),
    assets_growth_max: Optional[float] = Query(None, description="Max total assets growth % YoY"),
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
    if nd_ebitda_max is not None:
        conditions.append("""
            fl.ebitda > 0 AND
            (COALESCE(fl.lt_financial_debt, 0) + COALESCE(fl.st_financial_debt, 0) - COALESCE(fl.cash, 0)) / fl.ebitda <= %s
        """)
        params.append(nd_ebitda_max)

    # Growth filters — compare with previous year
    needs_prev_year = any(v is not None for v in [
        rev_growth_min, rev_growth_max, ebitda_growth_min, ebitda_growth_max,
        assets_growth_min, assets_growth_max,
    ])

    if rev_growth_min is not None:
        conditions.append("prev.revenue > 0 AND ((fl.revenue - prev.revenue) / ABS(prev.revenue) * 100) >= %s")
        params.append(rev_growth_min)
    if rev_growth_max is not None:
        conditions.append("prev.revenue > 0 AND ((fl.revenue - prev.revenue) / ABS(prev.revenue) * 100) <= %s")
        params.append(rev_growth_max)
    if ebitda_growth_min is not None:
        conditions.append("prev.ebitda IS NOT NULL AND ABS(prev.ebitda) > 0 AND ((fl.ebitda - prev.ebitda) / ABS(prev.ebitda) * 100) >= %s")
        params.append(ebitda_growth_min)
    if ebitda_growth_max is not None:
        conditions.append("prev.ebitda IS NOT NULL AND ABS(prev.ebitda) > 0 AND ((fl.ebitda - prev.ebitda) / ABS(prev.ebitda) * 100) <= %s")
        params.append(ebitda_growth_max)
    if assets_growth_min is not None:
        conditions.append("prev.total_assets > 0 AND ((fl.total_assets - prev.total_assets) / prev.total_assets * 100) >= %s")
        params.append(assets_growth_min)
    if assets_growth_max is not None:
        conditions.append("prev.total_assets > 0 AND ((fl.total_assets - prev.total_assets) / prev.total_assets * 100) <= %s")
        params.append(assets_growth_max)

    where = (" AND " + " AND ".join(conditions)) if conditions else ""

    prev_join = """
        LEFT JOIN financial_summary prev
            ON prev.enterprise_number = fl.enterprise_number
            AND prev.fiscal_year = fl.fiscal_year - 1
    """ if needs_prev_year else ""

    # Growth select columns
    growth_cols = ""
    if needs_prev_year:
        growth_cols = """,
               CASE WHEN prev.revenue > 0
                    THEN ROUND(((fl.revenue - prev.revenue) / ABS(prev.revenue) * 100)::numeric, 1)
               END AS "rev_growth_pct",
               CASE WHEN prev.ebitda IS NOT NULL AND ABS(prev.ebitda) > 0
                    THEN ROUND(((fl.ebitda - prev.ebitda) / ABS(prev.ebitda) * 100)::numeric, 1)
               END AS "ebitda_growth_pct",
               CASE WHEN prev.total_assets > 0
                    THEN ROUND(((fl.total_assets - prev.total_assets) / prev.total_assets * 100)::numeric, 1)
               END AS "assets_growth_pct"
        """

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
               fl.fte_total AS "fte",
               e.juridical_form AS "jf_label",
               e.start_date AS "start_date"
               {growth_cols}
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN enterprise e ON e.enterprise_number = fl.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        {prev_join}
        WHERE 1=1 {where}
        ORDER BY {sort_sql}
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(sql, tuple(params))

        # Convert Decimals to floats and dates to strings for JSON serialization
        import decimal
        import datetime
        for row in rows:
            for key in ("revenue", "ebit", "ebitda", "margin_pct", "net_profit", "fte",
                        "rev_growth_pct", "ebitda_growth_pct", "assets_growth_pct"):
                if row.get(key) is not None:
                    row[key] = float(row[key])
            if isinstance(row.get("start_date"), (datetime.date, datetime.datetime)):
                row["start_date"] = str(row["start_date"])

        return rows
    except Exception as e:
        logger.exception("Screener query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
