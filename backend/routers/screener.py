"""Screener router — filter, browse, and rank Belgian companies."""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user
from cache import ttl_cache
from feature_flags import person_public_url_enabled
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
    # Fixed assets = rubric 20/28 (intangible + tangible + financial).
    # Already pre-pivoted on financial_latest — no LATERAL join needed.
    "fixed_assets_desc": "fl.fixed_assets DESC NULLS LAST",
}


@ttl_cache(ttl_seconds=900)
def _nace_suggestions_cached(q: str) -> list:
    return fetch_all("""
        SELECT nace_code, description, company_count
        FROM nace_lookup
        WHERE nace_code ILIKE %s OR description ILIKE %s
        ORDER BY company_count DESC NULLS LAST
        LIMIT 50
    """, (f"%{q}%", f"%{q}%"))


@router.get("/nace-suggestions")
async def nace_suggestions(q: str = Query("", min_length=1, max_length=80)):
    """Return NACE codes matching the query. Cached 15 min — nace_lookup changes rarely.

    `max_length` caps the cache-key cardinality so a hostile caller can't
    push the in-process cache toward eviction churn with junk strings.
    """
    return _nace_suggestions_cached(q.lower())


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
    margin_min: Optional[float] = Query(None, ge=0, description="DEPRECATED alias for ebitda_margin_min — kept for back-compat with stored presets."),
    ebitda_margin_min: Optional[float] = Query(None, ge=0, description="Min EBITDA margin %  (= ebitda / revenue * 100)"),
    ebit_margin_min: Optional[float] = Query(None, ge=0, description="Min EBIT margin % (= ebit / revenue * 100)"),
    keyword: Optional[str] = Query(None, description="Filter by semantic keyword — matches words inside company_enrichment.bulk_summary.products_services (case-insensitive substring)"),
    nd_ebitda_max: Optional[float] = Query(None, description="Max Net Debt / EBITDA ratio"),
    rev_growth_min: Optional[float] = Query(None, description="Min revenue growth % YoY"),
    rev_growth_max: Optional[float] = Query(None, description="Max revenue growth % YoY"),
    ebitda_growth_min: Optional[float] = Query(None, description="Min EBITDA growth % YoY"),
    ebitda_growth_max: Optional[float] = Query(None, description="Max EBITDA growth % YoY"),
    fte_growth_3y_min: Optional[float] = Query(None, description="Min FTE 3y growth %"),
    fte_growth_3y_max: Optional[float] = Query(None, description="Max FTE 3y growth %"),
    fixed_assets_min: Optional[float] = Query(None, ge=0, description="Min fixed assets (rubric 20/28 \u2014 intangible + tangible + financial) in EUR"),
    fixed_assets_max: Optional[float] = Query(None, ge=0, description="Max fixed assets (rubric 20/28 \u2014 intangible + tangible + financial) in EUR"),
    distress: Optional[str] = Query(None, description="Distress filter: 'bankruptcy', 'wco', or 'any'"),
    no_financials: bool = Query(False, description="Show only companies that have no NBB financials loaded yet (coverage-gap mode)"),
    include_sparklines: bool = Query(False, description="Attach last-5-year revenue + EBITDA arrays per row for trend sparklines"),
    include_percentiles: bool = Query(False, description="Attach sector-level percentile rankings (revenue / EBITDA / margin) from the sector_percentiles materialized view"),
    sort: str = Query("ebit_desc", description="Sort order"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Screen companies with dynamic WHERE clause filters.

    Exact SQL extracted from app/pages/1_screener.py run_query().
    """
    # When distress is set, most rows have NULL financials so financial
    # sort keys put the few filed rows on top and a long NULL tail below.
    # Override the default to alphabetical so the result reads cleanly;
    # the user can still pick a financial sort explicitly.
    if distress and sort == "ebit_desc":
        sort_sql = SORT_OPTIONS["name_asc"]
    else:
        sort_sql = SORT_OPTIONS.get(sort, "fl.ebit DESC")

    conditions = []
    params = []

    # When distress OR no_financials is set we anchor on `enterprise`
    # (not financial_latest), so fall back to the activity/address tables
    # for nace + zipcode filtering. The COALESCE also keeps things working
    # once the full KBO universe is in company_info (post-refresh).
    coverage_mode = bool(distress) or no_financials
    nace_expr = "COALESCE(ci.nace_code, ac.nace_code)" if coverage_mode else "ci.nace_code"
    zip_expr = "COALESCE(ci.zipcode, ad.zipcode)" if coverage_mode else "ci.zipcode"

    if nace:
        nace_codes = parse_nace_list(nace)
        if not nace_codes:
            raise HTTPException(status_code=400, detail="Invalid NACE code(s)")
        if len(nace_codes) == 1:
            conditions.append(f"{nace_expr} LIKE %s")
            params.append(f"{nace_codes[0]}%")
        else:
            nace_conds = []
            for code in nace_codes:
                nace_conds.append(f"{nace_expr} LIKE %s")
                params.append(f"{code}%")
            conditions.append(f"({' OR '.join(nace_conds)})")
    if zipcode:
        conditions.append(f"{zip_expr} LIKE %s")
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
    # margin_min is the legacy EBITDA-margin filter; ebitda_margin_min is
    # the new explicit name. Both map to the same SQL — caller can use
    # either. If both are set, the stricter (higher) value wins.
    effective_ebitda_margin = margin_min if ebitda_margin_min is None else (
        max(margin_min, ebitda_margin_min) if margin_min is not None else ebitda_margin_min
    )
    if effective_ebitda_margin is not None:
        conditions.append("fl.revenue > 0")
        conditions.append("(fl.ebitda / fl.revenue * 100) >= %s")
        params.append(effective_ebitda_margin)
    if ebit_margin_min is not None:
        conditions.append("fl.revenue > 0")
        conditions.append("(fl.ebit / fl.revenue * 100) >= %s")
        params.append(ebit_margin_min)
    if keyword:
        # Case-insensitive substring match against any of the
        # products_services array entries. Requires the company to have
        # an enrichment row; companies without enrichment cannot satisfy
        # a positive keyword filter (this is the intended UX — the user
        # is explicitly filtering ON keywords, so absent data should
        # exclude the row, not include it).
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM company_enrichment ce_kw
                WHERE ce_kw.enterprise_number = e.enterprise_number
                  AND jsonb_typeof(ce_kw.bulk_summary->'products_services') = 'array'
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements_text(ce_kw.bulk_summary->'products_services') AS kw
                      WHERE kw ILIKE %s
                  )
            )
        """)
        params.append(f"%{keyword}%")
    if nd_ebitda_max is not None:
        conditions.append("""
            fl.ebitda > 0 AND
            (COALESCE(fl.lt_financial_debt, 0) + COALESCE(fl.st_financial_debt, 0) - COALESCE(fl.cash, 0)) / fl.ebitda <= %s
        """)
        params.append(nd_ebitda_max)

    # Growth filters — compare with previous year
    needs_prev_year = any(v is not None for v in [
        rev_growth_min, rev_growth_max, ebitda_growth_min, ebitda_growth_max,
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

    # FTE 3y growth — compares against prev3 (fiscal_year - 3). Companies
    # without 3-year history are excluded from the result by the WHERE
    # clause. Operator replaced "Mgmt change in last X days" with this
    # because it's a much better signal of sustained scale-up vs noise.
    needs_fte_3y = fte_growth_3y_min is not None or fte_growth_3y_max is not None
    if fte_growth_3y_min is not None:
        conditions.append("prev3.fte_total > 0 AND ((fl.fte_total - prev3.fte_total) / prev3.fte_total * 100) >= %s")
        params.append(fte_growth_3y_min)
    if fte_growth_3y_max is not None:
        conditions.append("prev3.fte_total > 0 AND ((fl.fte_total - prev3.fte_total) / prev3.fte_total * 100) <= %s")
        params.append(fte_growth_3y_max)

    # Fixed assets — rubric 20/28 = intangible + tangible + financial fixed
    # assets. Already pre-pivoted on `financial_latest.fixed_assets` so no
    # LATERAL join is needed; this also means we no longer pay the
    # rubric-22 lookup cost on every screener call.
    if fixed_assets_min is not None:
        conditions.append("COALESCE(fl.fixed_assets, 0) >= %s")
        params.append(fixed_assets_min)
    if fixed_assets_max is not None:
        conditions.append("COALESCE(fl.fixed_assets, 0) <= %s")
        params.append(fixed_assets_max)

    # Distress / juridical situation. Codes per docs/belgian-gaap.md +
    # graveyard.py; bankruptcy = 048-053, WCO/reorganisation = 020-026.
    # "healthy" uses the operational allowlist (`OPERATIONAL_CODES`) —
    # consistent with `graveyard.py` which treats anything NOT in that set
    # as failed/distressed (including liquidation, dissolution, cessation).
    # `IS NULL` keeps the LEFT-JOIN-anchored variant safe when no enterprise
    # row matches an orphan financial_latest row.
    DISTRESS_CODES = "'048','049','050','051','052','053','020','021','022','023','024','025','026'"
    OPERATIONAL_CODES = "'000','001','002','003','090','100'"
    if distress == "bankruptcy":
        conditions.append("e.juridical_situation IN ('048','049','050','051','052','053')")
    elif distress == "wco":
        conditions.append("e.juridical_situation IN ('020','021','022','023','024','025','026')")
    elif distress == "any":
        conditions.append(f"e.juridical_situation IN ({DISTRESS_CODES})")
    elif distress == "healthy":
        conditions.append(f"e.juridical_situation IN ({OPERATIONAL_CODES})")

    # Coverage-gap mode: restrict to KBO-registered companies with no
    # NBB filing in `financial_latest` yet. Requires the enterprise-
    # anchored FROM clause to be active (same shape distress mode uses).
    if no_financials:
        conditions.append("fl.enterprise_number IS NULL")

    where = (" AND " + " AND ".join(conditions)) if conditions else ""

    prev_join = """
        LEFT JOIN financial_summary prev
            ON prev.enterprise_number = fl.enterprise_number
            AND prev.fiscal_year = fl.fiscal_year - 1
    """ if needs_prev_year else ""

    prev3_join = """
        LEFT JOIN financial_summary prev3
            ON prev3.enterprise_number = fl.enterprise_number
            AND prev3.fiscal_year = fl.fiscal_year - 3
    """ if needs_fte_3y else ""

    # Fixed assets are already pivoted on financial_latest.fixed_assets,
    # so no LATERAL join is needed (the previous rubric-22 / real-estate
    # LATERAL was removed when we switched to the broader 20/28 value).
    fixed_assets_join = ""

    # Growth select columns
    growth_cols = ""
    if needs_prev_year:
        growth_cols = """,
               CASE WHEN prev.revenue > 0
                    THEN ROUND(((fl.revenue - prev.revenue) / ABS(prev.revenue) * 100)::numeric, 1)
               END AS "rev_growth_pct",
               CASE WHEN prev.ebitda IS NOT NULL AND ABS(prev.ebitda) > 0
                    THEN ROUND(((fl.ebitda - prev.ebitda) / ABS(prev.ebitda) * 100)::numeric, 1)
               END AS "ebitda_growth_pct"
        """
    fte_3y_col = ""
    if needs_fte_3y:
        fte_3y_col = """,
               CASE WHEN prev3.fte_total > 0
                    THEN ROUND(((fl.fte_total - prev3.fte_total) / prev3.fte_total * 100)::numeric, 1)
               END AS "fte_growth_3y_pct"
        """

    # Fixed-assets column always returned (drives the result table column
    # and lets the user see the value without setting a filter).
    fixed_assets_col = ', fl.fixed_assets AS "fixed_assets"'

    # Semantic keywords — first 5 items from products_services in bulk_summary.
    # LEFT JOIN so companies without enrichment still appear; the JSONB
    # extraction is done in Postgres to avoid any per-row Python overhead.
    # The jsonb_typeof guard prevents a hard error if any row's
    # products_services is malformed (e.g. a string or object instead of
    # an array — review-flagged latent crash risk).
    semantic_keywords_col = """,
               CASE WHEN jsonb_typeof(ce.bulk_summary->'products_services') = 'array' THEN
                   ARRAY(
                       SELECT jsonb_array_elements_text(
                           ce.bulk_summary->'products_services'
                       )
                       LIMIT 5
                   )
               ELSE ARRAY[]::text[] END AS "semantic_keywords"
    """

    # Sparkline history — last 5 fiscal years of revenue/EBITDA per row.
    # LATERAL returns an ORDERED array so the frontend can draw a line
    # directly. Skipped unless explicitly requested; adds a small but
    # real per-row cost at large `limit`.
    # Sector percentiles — from the sector_percentiles materialized view.
    # peer_count filters out noise: percentiles across <10 companies are
    # too jittery to surface meaningfully.
    percentile_col = ""
    percentile_join = ""
    if include_percentiles:
        percentile_col = """,
               CASE WHEN sp.peer_count >= 10 THEN sp.rev_rank END AS "rev_rank_pct",
               CASE WHEN sp.peer_count >= 10 THEN sp.ebitda_rank END AS "ebitda_rank_pct",
               CASE WHEN sp.peer_count >= 10 THEN sp.margin_rank END AS "margin_rank_pct",
               sp.peer_count AS "peer_count"
        """
        anchor_cbe = "e.enterprise_number" if coverage_mode else "fl.enterprise_number"
        percentile_join = f"""
            LEFT JOIN sector_percentiles sp ON sp.enterprise_number = {anchor_cbe}
        """

    sparkline_col = ""
    sparkline_join = ""
    if include_sparklines:
        sparkline_col = """,
               sl.rev_history AS "rev_history",
               sl.ebitda_history AS "ebitda_history",
               sl.year_history AS "year_history"
        """
        anchor_cbe = "e.enterprise_number" if coverage_mode else "fl.enterprise_number"
        sparkline_join = f"""
            LEFT JOIN LATERAL (
                SELECT
                    ARRAY_AGG(revenue ORDER BY fiscal_year)      AS rev_history,
                    ARRAY_AGG(ebitda  ORDER BY fiscal_year)      AS ebitda_history,
                    ARRAY_AGG(fiscal_year ORDER BY fiscal_year)  AS year_history
                FROM (
                    SELECT fiscal_year, revenue, ebitda
                    FROM financial_by_year
                    WHERE enterprise_number = {anchor_cbe}
                    ORDER BY fiscal_year DESC
                    LIMIT 5
                ) recent
            ) sl ON TRUE
        """

    # When the user filters by distress (bankruptcy / WCO / any-distress),
    # anchor the query on `enterprise` instead of `financial_latest`. Most
    # bankrupt or WCO companies haven't filed accounts, AND `company_info`
    # is built from `financial_latest` (not from `enterprise`), so an INNER
    # JOIN through company_info would also miss them. We therefore LEFT JOIN
    # company_info and fall back to the raw KBO `denomination` / `address`
    # tables for name + city + zipcode when no `company_info` row exists.
    # The CBE itself comes off the `enterprise` table so it's never NULL.
    if coverage_mode:
        # Subquery picks the canonical (NL preferred, fall back to FR) name
        # per enterprise without inflating cardinality.
        anchor_from = """
            FROM enterprise e
            LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
            LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
            LEFT JOIN LATERAL (
                SELECT denomination
                FROM denomination d2
                WHERE d2.entity_number = e.enterprise_number
                  AND d2.type_of_denomination = '001'
                ORDER BY CASE d2.language WHEN '1' THEN 1 WHEN '2' THEN 2 ELSE 3 END
                LIMIT 1
            ) dn ON TRUE
            LEFT JOIN LATERAL (
                SELECT zipcode, municipality_nl
                FROM address a2
                WHERE a2.entity_number = e.enterprise_number
                  AND a2.type_of_address = 'REGO'
                LIMIT 1
            ) ad ON TRUE
            LEFT JOIN LATERAL (
                SELECT nace_code
                FROM activity ac2
                WHERE ac2.entity_number = e.enterprise_number
                  AND ac2.activity_group = '001'
                  AND ac2.nace_version = '2008'
                  AND ac2.classification = 'MAIN'
                LIMIT 1
            ) ac ON TRUE
            LEFT JOIN nace_lookup nl ON nl.nace_code = COALESCE(ci.nace_code, ac.nace_code)
            LEFT JOIN company_enrichment ce ON ce.enterprise_number = e.enterprise_number
        """
        cbe_col = "e.enterprise_number"
        name_col = "COALESCE(ci.name, dn.denomination)"
        city_col = "COALESCE(ci.city, ad.municipality_nl)"
    else:
        anchor_from = """
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            LEFT JOIN enterprise e ON e.enterprise_number = fl.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            LEFT JOIN company_enrichment ce ON ce.enterprise_number = fl.enterprise_number
        """
        cbe_col = "fl.enterprise_number"
        name_col = "ci.name"
        city_col = "ci.city"

    sql = f"""
        SELECT {cbe_col} AS "cbe",
               {name_col} AS "name",
               COALESCE(nl.description, ci.nace_code) AS "nace",
               {city_col} AS "city",
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
               {fte_3y_col}
               {fixed_assets_col}
               {sparkline_col}
               {percentile_col}
               {semantic_keywords_col}
        {anchor_from}
        {prev_join}
        {prev3_join}
        {fixed_assets_join}
        {sparkline_join}
        {percentile_join}
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
                        "rev_growth_pct", "ebitda_growth_pct",
                        "fte_growth_3y_pct", "fixed_assets",
                        "rev_rank_pct", "ebitda_rank_pct", "margin_rank_pct"):
                if row.get(key) is not None:
                    row[key] = float(row[key])
            if isinstance(row.get("start_date"), (datetime.date, datetime.datetime)):
                row["start_date"] = str(row["start_date"])
            # Sparkline arrays — cast Decimals to floats element-wise.
            for arr_key in ("rev_history", "ebitda_history"):
                arr = row.get(arr_key)
                if isinstance(arr, list):
                    row[arr_key] = [float(v) if v is not None else None for v in arr]
            # Semantic keywords — coerce empty Postgres arrays to None so the
            # frontend receives null instead of [] for unenriched companies.
            kw = row.get("semantic_keywords")
            if isinstance(kw, list) and len(kw) == 0:
                row["semantic_keywords"] = None

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
async def nl_screener(body: NLScreenerBody, user=Depends(optional_user)):
    """Translate a natural language query into screener filters via LLM.

    Anonymous-friendly per operator policy. Tier-bucketed under
    ``ai_enrichments_per_day`` so anon abuse stays cost-bounded.
    """
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
        "- ebitda_growth_min / ebitda_growth_max: EBITDA growth % YoY\n"
        "- fte_growth_3y_min / fte_growth_3y_max: 3-year FTE headcount growth %\n"
        "- fixed_assets_min / fixed_assets_max: fixed assets (rubric 20/28 \u2014 intangible + tangible + financial) in EUR\n"
        "- distress: 'healthy' | 'bankruptcy' | 'wco' | 'any' — filter on juridical situation\n"
        "- sort: revenue_desc | ebit_desc | ebitda_desc | fte_desc | name_asc | fixed_assets_desc\n"
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


@sitemap_router.get("/persons")
async def sitemap_persons():
    """Return public Person v1 profile ids for sitemap generation."""
    if not person_public_url_enabled():
        return []
    rows = fetch_all("""
        SELECT person_id::text
        FROM person
        WHERE status = 'active'
        ORDER BY role_count DESC NULLS LAST, person_id
        LIMIT 50000
    """)
    return [r["person_id"] for r in rows]
