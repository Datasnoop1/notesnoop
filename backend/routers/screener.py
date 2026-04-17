"""Screener router — filter, browse, and rank Belgian companies."""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user
from utils import parse_nace_list

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
        LIMIT 50
    """, (f"%{q}%", f"%{q}%"))
    return rows


@router.get("")
async def screener(
    nace: Optional[str] = Query(None, description="NACE code prefix (e.g. 28, 461)"),
    zipcode: Optional[str] = Query(None, description="Zipcode prefix for province filter"),
    mgmt_change_days: Optional[int] = Query(None, description="Companies with management changes in last N days"),
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
    real_estate_min: Optional[float] = Query(None, ge=0, description="Min real estate (rubric 22 — land + buildings) in EUR"),
    real_estate_max: Optional[float] = Query(None, ge=0, description="Max real estate (rubric 22 — land + buildings) in EUR"),
    distress: Optional[str] = Query(None, description="Distress filter: 'bankruptcy', 'wco', or 'any'"),
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
        nace_codes = parse_nace_list(nace)
        if not nace_codes:
            raise HTTPException(status_code=400, detail="Invalid NACE code(s)")
        if len(nace_codes) == 1:
            conditions.append("ci.nace_code LIKE %s")
            params.append(f"{nace_codes[0]}%")
        else:
            nace_conds = []
            for code in nace_codes:
                nace_conds.append("ci.nace_code LIKE %s")
                params.append(f"{code}%")
            conditions.append(f"({' OR '.join(nace_conds)})")
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
    if mgmt_change_days is not None and mgmt_change_days > 0:
        conditions.append("""
            fl.enterprise_number IN (
                SELECT DISTINCT enterprise_number FROM staatsblad_publication
                WHERE pub_date >= (CURRENT_DATE - INTERVAL '1 day' * %s)::text
                  AND (pub_type ILIKE '%%BENOEMINGEN%%' OR pub_type ILIKE '%%ONTSLAGEN%%')
            )
        """)
        params.append(mgmt_change_days)
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

    # Real estate (rubric 22 — Terreinen en gebouwen / land and buildings).
    # Looked up from financial_data per fiscal year aligned with financial_latest.
    needs_real_estate = real_estate_min is not None or real_estate_max is not None
    if real_estate_min is not None:
        conditions.append("COALESCE(re.land_buildings, 0) >= %s")
        params.append(real_estate_min)
    if real_estate_max is not None:
        conditions.append("COALESCE(re.land_buildings, 0) <= %s")
        params.append(real_estate_max)

    # Distress / juridical situation. Codes per docs/belgian-gaap.md +
    # graveyard.py; bankruptcy = 048-053, WCO/reorganisation = 020-026.
    if distress == "bankruptcy":
        conditions.append("e.juridical_situation IN ('048','049','050','051','052','053')")
    elif distress == "wco":
        conditions.append("e.juridical_situation IN ('020','021','022','023','024','025','026')")
    elif distress == "any":
        conditions.append("e.juridical_situation IN ('048','049','050','051','052','053','020','021','022','023','024','025','026')")

    where = (" AND " + " AND ".join(conditions)) if conditions else ""

    prev_join = """
        LEFT JOIN financial_summary prev
            ON prev.enterprise_number = fl.enterprise_number
            AND prev.fiscal_year = fl.fiscal_year - 1
    """ if needs_prev_year else ""

    # Real-estate join: pulls rubric 22 (land + buildings) for the same
    # fiscal year as financial_latest. Only joined when needed so the
    # default screener stays fast.
    real_estate_join = """
        LEFT JOIN LATERAL (
            SELECT MAX(value) AS land_buildings
            FROM financial_data fd
            WHERE fd.enterprise_number = fl.enterprise_number
              AND fd.fiscal_year = fl.fiscal_year
              AND fd.rubric_code = '22'
        ) re ON TRUE
    """ if needs_real_estate else ""

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

    real_estate_col = ""
    if needs_real_estate:
        real_estate_col = ', re.land_buildings AS "real_estate"'

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
               e.juridical_situation AS "juridical_situation",
               e.start_date AS "start_date"
               {growth_cols}
               {real_estate_col}
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN enterprise e ON e.enterprise_number = fl.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        {prev_join}
        {real_estate_join}
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
                        "rev_growth_pct", "ebitda_growth_pct", "assets_growth_pct",
                        "real_estate"):
                if row.get(key) is not None:
                    row[key] = float(row[key])
            if isinstance(row.get("start_date"), (datetime.date, datetime.datetime)):
                row["start_date"] = str(row["start_date"])

        return rows
    except Exception as e:
        logger.exception("Screener query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/screener/nl — Natural Language Screener
# ---------------------------------------------------------------------------

class NLScreenerBody(BaseModel):
    query: str


@router.post("/nl")
async def nl_screener(body: NLScreenerBody, user=Depends(get_current_user)):
    """Translate a natural language query into screener filters via LLM."""
    from ai_client import ai_complete

    system = (
        "You are a Belgian company screener assistant. Convert the user's natural language query "
        "into structured JSON filter parameters.\n\n"
        "Available filters:\n"
        '- nace: NACE code prefix (e.g. "28" for manufacturing, "46" for wholesale, "62" for IT)\n'
        '- zipcode: Belgian zipcode prefix for province ("1" Brussels, "2" Antwerp, "3" Vl-Brabant, "4" Liege, "5" Namur, "6" Luxembourg, "7" Hainaut, "8" W-Vl, "9" O-Vl, "35" Limburg, "13" Br-Wallon)\n'
        "- rev_min / rev_max: revenue in EUR\n"
        "- ebit_min / ebit_max: EBIT in EUR\n"
        "- ebitda_min / ebitda_max: EBITDA in EUR\n"
        "- fte_min / fte_max: number of employees\n"
        "- margin_min: minimum EBITDA margin %\n"
        "- nd_ebitda_max: max Net Debt / EBITDA ratio\n"
        "- rev_growth_min / rev_growth_max: revenue growth % YoY\n"
        "- mgmt_change_days: companies with management changes in last N days\n"
        "- sort: revenue_desc | ebit_desc | ebitda_desc | fte_desc | name_asc\n"
        "- limit: max results (default 100)\n\n"
        "Common NACE codes: 10-33 Manufacturing, 41-43 Construction, 45-47 Wholesale/Retail, "
        "49-53 Transport, 55-56 Hotels/Restaurants, 58-63 ICT/Media, 64-66 Finance, "
        "68 Real estate, 69-75 Professional services, 86-88 Healthcare\n\n"
        "Return ONLY valid JSON with the filter keys. Use numeric values (not strings) for amounts. "
        "Convert M/million to actual numbers (5M = 5000000). If unsure about a filter, omit it."
    )

    try:
        raw = await ai_complete(body.query, system=system, max_tokens=300, model="google/gemini-2.5-flash")
        # Parse JSON
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return {"filters": {}, "explanation": raw, "error": "Could not parse filters"}
        filters = json.loads(json_match.group())
        return {"filters": filters, "raw_response": raw}
    except Exception as e:
        logger.error("NL screener failed: %s", e)
        return {"filters": {}, "error": "AI processing failed"}


# ---------------------------------------------------------------------------
# GET /api/sitemap/companies — company CBEs for dynamic sitemap
# ---------------------------------------------------------------------------

from fastapi import APIRouter as _AR
sitemap_router = APIRouter(prefix="/api/sitemap", tags=["sitemap"])


@sitemap_router.get("/companies")
async def sitemap_companies():
    """Return all company CBE numbers that have financial data (for sitemap generation)."""
    rows = fetch_all("""
        SELECT enterprise_number FROM company_info
        ORDER BY enterprise_number
        LIMIT 50000
    """)
    return [r["enterprise_number"] for r in rows]
