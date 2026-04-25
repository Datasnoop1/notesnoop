"""Stats router — aggregate analytics across the entire database."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one, get_connection
from cache import ttl_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stats", tags=["stats"])

# Sector / province / size aggregates query 100k+ rows and change at most
# once a day. A 5-minute in-process cache turns a 1.4s response into a
# sub-millisecond dict lookup for repeat callers.
_STATS_TTL_S = 300

PROVINCE_SQL = """
    CASE
      WHEN ci.zipcode BETWEEN '1000' AND '1299' THEN 'Brussels'
      WHEN ci.zipcode BETWEEN '1300' AND '1499' THEN 'Brabant Wallon'
      WHEN ci.zipcode BETWEEN '1500' AND '1999' THEN 'Vlaams-Brabant'
      WHEN ci.zipcode BETWEEN '2000' AND '2999' THEN 'Antwerpen'
      WHEN ci.zipcode BETWEEN '3000' AND '3499' THEN 'Vlaams-Brabant'
      WHEN ci.zipcode BETWEEN '3500' AND '3999' THEN 'Limburg'
      WHEN ci.zipcode BETWEEN '4000' AND '4999' THEN 'Liege'
      WHEN ci.zipcode BETWEEN '5000' AND '5999' THEN 'Namur'
      WHEN ci.zipcode BETWEEN '6000' AND '6599' THEN 'Hainaut'
      WHEN ci.zipcode BETWEEN '6600' AND '6999' THEN 'Luxembourg'
      WHEN ci.zipcode BETWEEN '7000' AND '7999' THEN 'Hainaut'
      WHEN ci.zipcode BETWEEN '8000' AND '8999' THEN 'West-Vlaanderen'
      WHEN ci.zipcode BETWEEN '9000' AND '9999' THEN 'Oost-Vlaanderen'
      ELSE 'Other'
    END
"""

VALID_PROVINCES = [
    "Brussels", "Antwerpen", "Oost-Vlaanderen", "West-Vlaanderen",
    "Vlaams-Brabant", "Limburg", "Liege", "Hainaut", "Namur",
    "Brabant Wallon", "Luxembourg",
]


def _serialize(rows: list) -> list:
    """Convert Decimal types to floats for JSON serialization."""
    import decimal
    import datetime
    result = []
    for row in rows:
        out = {}
        for k, v in row.items():
            if isinstance(v, decimal.Decimal):
                out[k] = float(v)
            elif isinstance(v, (datetime.date, datetime.datetime)):
                out[k] = str(v)
            else:
                out[k] = v
        result.append(out)
    return result


# ---------------------------------------------------------------------------
# GET /api/stats/overview
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_overview_cached(province: Optional[str]) -> dict:
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    row = fetch_one(f"""
        SELECT
            COUNT(DISTINCT fl.enterprise_number)  AS "n_companies",
            SUM(fl.revenue)                        AS "total_revenue",
            SUM(fl.ebitda)                         AS "total_ebitda",
            SUM(fl.fte_total)                      AS "total_fte",
            AVG(fl.fte_total)                      AS "avg_fte",
            SUM(COALESCE(fl.lt_financial_debt,0) + COALESCE(fl.st_financial_debt,0)
                - COALESCE(fl.cash,0))             AS "total_nfd"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE 1=1 {prov_clause}
    """)

    # Median margin computed entirely in SQL — old version pulled every
    # row into Python (~80k+) and sorted client-side, which dominated the
    # response time at scale.
    median_row = fetch_one(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (
                  ORDER BY (CAST(fl.ebitda AS REAL) / fl.revenue * 100)
               ) AS median_margin
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 500000 AND fl.ebitda IS NOT NULL {prov_clause}
    """)

    result: dict = {}
    if row:
        import decimal
        for k, v in row.items():
            result[k] = float(v) if isinstance(v, decimal.Decimal) else v
    median_margin = median_row.get("median_margin") if median_row else None
    result["median_margin"] = round(float(median_margin), 1) if median_margin is not None else None
    return result


@router.get("/overview")
async def stats_overview(
    province: Optional[str] = Query(None, description="Province filter"),
):
    """Overall database stats: company count, total revenue, EBITDA, FTE, NFD."""
    try:
        return _stats_overview_cached(province if province in VALID_PROVINCES else None)
    except Exception:
        logger.exception("Stats overview query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/evolution
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_evolution_cached(y_min: int, y_max: int, province: Optional[str]) -> list:
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"
    prov_clause_fy = prov_clause.replace("fl.", "fy.") if prov_clause else ""

    agg = fetch_all(f"""
        SELECT
            fy.fiscal_year,
            COUNT(DISTINCT fy.enterprise_number)              AS "companies",
            SUM(fy.revenue)/1e6                              AS "revenue_m",
            SUM(fy.ebitda)/1e6                               AS "ebitda_m",
            SUM(fy.ebit)/1e6                                 AS "ebit_m",
            SUM(fy.net_profit)/1e6                           AS "net_profit_m",
            SUM(COALESCE(fy.lt_financial_debt,0)+COALESCE(fy.st_financial_debt,0)
                -COALESCE(fy.cash,0))/1e6                    AS "nfd_m"
        FROM financial_by_year fy
        JOIN company_info ci ON ci.enterprise_number = fy.enterprise_number
        WHERE fy.fiscal_year BETWEEN %s AND %s
        {prov_clause_fy}
        GROUP BY fy.fiscal_year
        ORDER BY fy.fiscal_year
    """, (y_min, y_max))
    return _serialize(agg)


@router.get("/evolution")
async def stats_evolution(
    y_min: int = Query(2021, ge=2015, le=2030),
    y_max: int = Query(2024, ge=2015, le=2030),
    province: Optional[str] = Query(None),
):
    """Financial evolution by fiscal year."""
    try:
        return _stats_evolution_cached(y_min, y_max, province if province in VALID_PROVINCES else None)
    except Exception:
        logger.exception("Stats evolution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/sectors
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_sectors_cached(province: Optional[str], top_n: int) -> list:
    prov_clause = ""
    params: tuple = ()
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = %s"
        params = (province,)

    rows = fetch_all(f"""
            WITH base AS (
                SELECT
                    SUBSTR(ci.nace_code, 1, 2)                          AS nace2,
                    COALESCE(nl.description, SUBSTR(ci.nace_code,1,2))  AS sector,
                    fl.enterprise_number,
                    fl.revenue, fl.ebitda, fl.fte_total,
                    COALESCE(fl.lt_financial_debt,0)
                    + COALESCE(fl.st_financial_debt,0)
                    - COALESCE(fl.cash,0)                               AS nfd,
                    CASE WHEN fl.revenue > 0 AND fl.ebitda IS NOT NULL
                         THEN fl.ebitda / fl.revenue * 100 END          AS margin_pct,
                    CASE WHEN fl.ebitda > 0 THEN
                         (COALESCE(fl.lt_financial_debt,0)
                          + COALESCE(fl.st_financial_debt,0)
                          - COALESCE(fl.cash,0)) / fl.ebitda
                    END                                                 AS nfd_ebitda_ratio
                FROM financial_latest fl
                JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code,1,2)
                WHERE ci.nace_code IS NOT NULL
                {prov_clause}
            )
            SELECT
                nace2,
                MAX(sector)                                                   AS sector,
                COUNT(DISTINCT enterprise_number)                             AS companies,
                ROUND((SUM(revenue) / 1e6)::numeric, 1)                       AS revenue_m,
                ROUND((SUM(ebitda) / 1e6)::numeric, 1)                        AS ebitda_m,
                ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY margin_pct)::numeric, 1)
                    AS med_margin,
                ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY fte_total)::numeric, 0)
                    AS med_fte,
                ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY nfd_ebitda_ratio)::numeric, 2)
                    AS med_nfd_ebitda
            FROM base
            GROUP BY nace2
            HAVING COUNT(DISTINCT enterprise_number) >= 10
            ORDER BY companies DESC
            LIMIT %s
        """, params + (top_n,))

    # Decimal → float (cheap, small result set after aggregation)
    import decimal
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, decimal.Decimal):
                r[k] = float(v)
    return rows


@router.get("/sectors")
async def stats_sectors(
    province: Optional[str] = Query(None),
    top_n: int = Query(10, ge=5, le=50),
):
    """Sector breakdown by 2-digit NACE code.

    Median computation pushed to SQL (percentile_cont) instead of loading
    all 150k rows into Python — cuts latency from ~2-3s to ~150ms at
    current data volumes. Result cached in-process for 5 min.
    """
    try:
        return _stats_sectors_cached(province if province in VALID_PROVINCES else None, top_n)
    except Exception:
        logger.exception("Stats sectors query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/provinces
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_provinces_cached() -> list:
    # Aggregate entirely in SQL — the previous version pulled every
    # company's revenue/ebitda/fte (~150k rows) into Python and median'd
    # client-side, which dominated the response time at scale.
    rows = fetch_all(f"""
        SELECT
            {PROVINCE_SQL}                                              AS province,
            COUNT(DISTINCT fl.enterprise_number)                        AS companies,
            ROUND((SUM(fl.revenue)/1e6)::numeric, 1)                    AS revenue_m,
            ROUND((SUM(fl.ebitda)/1e6)::numeric, 1)                     AS ebitda_m,
            ROUND(percentile_cont(0.5) WITHIN GROUP (
                  ORDER BY CASE WHEN fl.revenue > 0 AND fl.ebitda IS NOT NULL
                                THEN fl.ebitda / fl.revenue * 100 END
            )::numeric, 1)                                              AS med_margin,
            ROUND(SUM(fl.fte_total)::numeric, 0)                        AS total_fte,
            ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY fl.fte_total)::numeric, 0)
                                                                        AS med_fte
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE ci.zipcode IS NOT NULL AND {PROVINCE_SQL} != 'Other'
        GROUP BY {PROVINCE_SQL}
        ORDER BY companies DESC
    """)
    return _serialize(rows)


@router.get("/provinces")
async def stats_provinces():
    """Province-level stats. Cached 5 min."""
    try:
        return _stats_provinces_cached()
    except Exception:
        logger.exception("Stats provinces query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/margin-distribution
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_margin_distribution_cached(province: Optional[str]) -> list:
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"
    rows = fetch_all(f"""
        SELECT
            ROUND((fl.ebitda / fl.revenue * 100)::numeric) AS "margin_bucket",
            COUNT(*) AS "n"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 100000
          AND fl.ebitda / fl.revenue * 100 BETWEEN -50 AND 80
          {prov_clause}
        GROUP BY "margin_bucket"
        ORDER BY "margin_bucket"
    """)
    return _serialize(rows)


@router.get("/margin-distribution")
async def stats_margin_distribution(
    province: Optional[str] = Query(None),
):
    """EBITDA margin distribution histogram data. Cached 5 min."""
    try:
        return _stats_margin_distribution_cached(province if province in VALID_PROVINCES else None)
    except Exception:
        logger.exception("Margin distribution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/sector-scatter — revenue (X) vs EBITDA margin % (Y) per company
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_sector_scatter_cached(nace: str, limit: int) -> list:
    rows = fetch_all("""
            SELECT
                ci.enterprise_number AS cbe,
                ci.name,
                ci.city,
                fl.revenue,
                fl.ebitda,
                fl.fte_total AS fte,
                ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) AS margin_pct
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            WHERE ci.nace_code LIKE %s
              AND fl.revenue > 100000
              AND fl.ebitda IS NOT NULL
              AND fl.ebitda / fl.revenue * 100 BETWEEN -50 AND 80
            ORDER BY fl.revenue DESC
            LIMIT %s
    """, (f"{nace}%", limit))
    return _serialize(rows)


@router.get("/sector-scatter")
async def stats_sector_scatter(
    nace: str = Query(..., min_length=2, max_length=5, description="NACE prefix (2-5 digits)"),
    limit: int = Query(300, ge=10, le=1000),
):
    """Per-company revenue vs EBITDA-margin scatter for one NACE sector.

    Cached 5 min — sectors with high traffic (62 ICT, 47 Retail) repeat
    constantly and the underlying data only refreshes nightly.
    """
    nace = nace.strip()
    if not nace.isdigit():
        raise HTTPException(status_code=400, detail="NACE must be numeric")
    try:
        return _stats_sector_scatter_cached(nace, limit)
    except Exception:
        logger.exception("Sector scatter query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/size-distribution
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=_STATS_TTL_S)
def _stats_size_distribution_cached(province: Optional[str]) -> list:
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"
    rows = fetch_all(f"""
        SELECT
            CASE
                WHEN fl.revenue < 1e6    THEN '< 1M'
                WHEN fl.revenue < 5e6    THEN '1-5M'
                WHEN fl.revenue < 10e6   THEN '5-10M'
                WHEN fl.revenue < 25e6   THEN '10-25M'
                WHEN fl.revenue < 50e6   THEN '25-50M'
                WHEN fl.revenue < 100e6  THEN '50-100M'
                WHEN fl.revenue < 250e6  THEN '100-250M'
                ELSE '> 250M'
            END AS "size_bucket",
            CASE
                WHEN fl.revenue < 1e6    THEN 1
                WHEN fl.revenue < 5e6    THEN 2
                WHEN fl.revenue < 10e6   THEN 3
                WHEN fl.revenue < 25e6   THEN 4
                WHEN fl.revenue < 50e6   THEN 5
                WHEN fl.revenue < 100e6  THEN 6
                WHEN fl.revenue < 250e6  THEN 7
                ELSE 8
            END AS "sort_key",
            COUNT(*) AS "companies",
            SUM(fl.revenue)/1e6 AS "revenue_m"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 0 {prov_clause}
        GROUP BY "size_bucket", "sort_key"
        ORDER BY "sort_key"
    """)
    return _serialize(rows)


@router.get("/size-distribution")
async def stats_size_distribution(
    province: Optional[str] = Query(None),
):
    """Company size distribution by revenue bucket. Cached 5 min."""
    try:
        return _stats_size_distribution_cached(province if province in VALID_PROVINCES else None)
    except Exception:
        logger.exception("Size distribution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Outperformer buckets
#
# Companies are bucketed based on their 2023 vs 2025 financials:
#   - revenue_growers: revenue up >= 10% over the period
#   - high_margin:     2025 EBITDA margin >= 15%
#   - margin_growers:  relative EBITDA-margin growth >= 20% (base margin >= 2%)
#   - other:           none of the above
#
# Universe: companies with revenue filings in BOTH 2023 and 2025 and
# rev_2023 >= 1M EUR (floor to drop noisy tiny companies). Buckets overlap —
# one company can be in multiple outperformer buckets. "Other" is mutually
# exclusive with the three outperformer buckets.
# ---------------------------------------------------------------------------

BUCKET_BASE_YEAR = 2023
BUCKET_END_YEAR = 2025
BUCKET_MIN_REVENUE = 1_000_000          # EUR floor on base-year revenue
BUCKET_REV_GROWTH = 0.10                # >= 10% total rev growth
BUCKET_HIGH_MARGIN = 0.15               # >= 15% EBITDA margin (end year)
BUCKET_MARGIN_GROWTH = 0.20             # >= 20% relative margin growth
BUCKET_MIN_BASE_MARGIN = 0.02           # base margin floor so ratios aren't noise

VALID_BUCKETS = {"revenue_growers", "high_margin", "margin_growers", "other"}


def _bucket_cte_sql() -> str:
    """Return the WITH clause defining a `labeled` CTE with bucket flags.

    Callers append their own `SELECT ... FROM labeled l ...`. The CTE exposes:
        enterprise_number, rev_23, rev_25, ebitda_23, ebitda_25,
        rev_growth_pct, margin_25, margin_23, margin_growth_pct,
        is_rev_grower, is_high_margin, is_margin_grower, is_other
    """
    return f"""
    WITH years AS (
        SELECT
            fy.enterprise_number,
            MAX(CASE WHEN fy.fiscal_year = {BUCKET_BASE_YEAR} THEN fy.revenue END) AS rev_23,
            MAX(CASE WHEN fy.fiscal_year = {BUCKET_END_YEAR}  THEN fy.revenue END) AS rev_25,
            MAX(CASE WHEN fy.fiscal_year = {BUCKET_BASE_YEAR} THEN fy.ebitda  END) AS ebitda_23,
            MAX(CASE WHEN fy.fiscal_year = {BUCKET_END_YEAR}  THEN fy.ebitda  END) AS ebitda_25
        FROM financial_by_year fy
        WHERE fy.fiscal_year IN ({BUCKET_BASE_YEAR}, {BUCKET_END_YEAR})
        GROUP BY fy.enterprise_number
    ),
    universe AS (
        SELECT *
        FROM years
        WHERE rev_23 IS NOT NULL
          AND rev_25 IS NOT NULL
          AND rev_23 >= {BUCKET_MIN_REVENUE}
          AND rev_25 > 0
    ),
    labeled AS (
        SELECT
            u.enterprise_number,
            u.rev_23, u.rev_25, u.ebitda_23, u.ebitda_25,
            ((u.rev_25 - u.rev_23) / u.rev_23) AS rev_growth_pct,
            CASE WHEN u.ebitda_25 IS NOT NULL THEN (u.ebitda_25 / u.rev_25) END AS margin_25,
            CASE WHEN u.ebitda_23 IS NOT NULL THEN (u.ebitda_23 / u.rev_23) END AS margin_23,
            CASE
                WHEN u.ebitda_23 IS NOT NULL AND u.ebitda_25 IS NOT NULL
                 AND (u.ebitda_23 / u.rev_23) >= {BUCKET_MIN_BASE_MARGIN}
                THEN ((u.ebitda_25 / u.rev_25) - (u.ebitda_23 / u.rev_23)) / (u.ebitda_23 / u.rev_23)
            END AS margin_growth_pct,
            (((u.rev_25 - u.rev_23) / u.rev_23) >= {BUCKET_REV_GROWTH}) AS is_rev_grower,
            (u.ebitda_25 IS NOT NULL AND (u.ebitda_25 / u.rev_25) >= {BUCKET_HIGH_MARGIN}) AS is_high_margin,
            (u.ebitda_23 IS NOT NULL AND u.ebitda_25 IS NOT NULL
             AND (u.ebitda_23 / u.rev_23) >= {BUCKET_MIN_BASE_MARGIN}
             AND ((u.ebitda_25 / u.rev_25) - (u.ebitda_23 / u.rev_23)) / (u.ebitda_23 / u.rev_23) >= {BUCKET_MARGIN_GROWTH}
            ) AS is_margin_grower,
            (NOT (((u.rev_25 - u.rev_23) / u.rev_23) >= {BUCKET_REV_GROWTH})
             AND NOT (u.ebitda_25 IS NOT NULL AND (u.ebitda_25 / u.rev_25) >= {BUCKET_HIGH_MARGIN})
             AND NOT (u.ebitda_23 IS NOT NULL AND u.ebitda_25 IS NOT NULL
                 AND (u.ebitda_23 / u.rev_23) >= {BUCKET_MIN_BASE_MARGIN}
                 AND ((u.ebitda_25 / u.rev_25) - (u.ebitda_23 / u.rev_23)) / (u.ebitda_23 / u.rev_23) >= {BUCKET_MARGIN_GROWTH})
            ) AS is_other
        FROM universe u
    )
    """


def _bucket_filter_clause(bucket: str, alias: str = "l") -> str:
    """SQL predicate selecting rows in a given bucket."""
    if bucket == "revenue_growers":
        return f"{alias}.is_rev_grower"
    if bucket == "high_margin":
        return f"{alias}.is_high_margin"
    if bucket == "margin_growers":
        return f"{alias}.is_margin_grower"
    if bucket == "other":
        return f"{alias}.is_other"
    raise ValueError(f"Unknown bucket: {bucket}")


# ---------------------------------------------------------------------------
# GET /api/stats/outperformers/overview
# ---------------------------------------------------------------------------

@router.get("/outperformers/overview")
async def outperformers_overview():
    """Counts and summary metrics for the four buckets.

    Returns a dict with one entry per bucket. Revenue-grower and margin-grower
    stats include median growth rates; high-margin returns median margin.
    """
    try:
        row = fetch_one(f"""
            {_bucket_cte_sql()}
            SELECT
                COUNT(*) FILTER (WHERE l.is_rev_grower)    AS n_rev_growers,
                COUNT(*) FILTER (WHERE l.is_high_margin)   AS n_high_margin,
                COUNT(*) FILTER (WHERE l.is_margin_grower) AS n_margin_growers,
                COUNT(*) FILTER (WHERE l.is_other)         AS n_other,
                COUNT(*)                                   AS n_universe,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY l.rev_growth_pct)
                    FILTER (WHERE l.is_rev_grower)         AS med_rev_growth,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY l.margin_25)
                    FILTER (WHERE l.is_high_margin)        AS med_high_margin,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY l.margin_growth_pct)
                    FILTER (WHERE l.is_margin_grower)      AS med_margin_growth,
                SUM(l.rev_25) FILTER (WHERE l.is_rev_grower)    AS rev_rev_growers,
                SUM(l.rev_25) FILTER (WHERE l.is_high_margin)   AS rev_high_margin,
                SUM(l.rev_25) FILTER (WHERE l.is_margin_grower) AS rev_margin_growers,
                SUM(l.rev_25) FILTER (WHERE l.is_other)         AS rev_other
            FROM labeled l
        """)

        # Sanitize Decimals
        import decimal
        def num(v):
            if v is None:
                return None
            if isinstance(v, decimal.Decimal):
                return float(v)
            return v

        def pct(v):
            v = num(v)
            return round(v * 100, 1) if v is not None else None

        return {
            "base_year": BUCKET_BASE_YEAR,
            "end_year": BUCKET_END_YEAR,
            "universe": num(row["n_universe"]) if row else 0,
            "thresholds": {
                "min_revenue": BUCKET_MIN_REVENUE,
                "revenue_growth_pct": BUCKET_REV_GROWTH * 100,
                "high_margin_pct": BUCKET_HIGH_MARGIN * 100,
                "margin_growth_pct": BUCKET_MARGIN_GROWTH * 100,
            },
            "buckets": {
                "revenue_growers": {
                    "count": num(row["n_rev_growers"]) if row else 0,
                    "median_metric_pct": pct(row["med_rev_growth"]) if row else None,
                    "metric_label": f"Median revenue growth {BUCKET_BASE_YEAR}-{BUCKET_END_YEAR}",
                    "total_revenue_m": round(num(row["rev_rev_growers"]) / 1e6, 1) if row and row["rev_rev_growers"] else 0,
                },
                "high_margin": {
                    "count": num(row["n_high_margin"]) if row else 0,
                    "median_metric_pct": pct(row["med_high_margin"]) if row else None,
                    "metric_label": f"Median EBITDA margin {BUCKET_END_YEAR}",
                    "total_revenue_m": round(num(row["rev_high_margin"]) / 1e6, 1) if row and row["rev_high_margin"] else 0,
                },
                "margin_growers": {
                    "count": num(row["n_margin_growers"]) if row else 0,
                    "median_metric_pct": pct(row["med_margin_growth"]) if row else None,
                    "metric_label": f"Median margin growth {BUCKET_BASE_YEAR}-{BUCKET_END_YEAR}",
                    "total_revenue_m": round(num(row["rev_margin_growers"]) / 1e6, 1) if row and row["rev_margin_growers"] else 0,
                },
                "other": {
                    "count": num(row["n_other"]) if row else 0,
                    "median_metric_pct": None,
                    "metric_label": "All remaining companies",
                    "total_revenue_m": round(num(row["rev_other"]) / 1e6, 1) if row and row["rev_other"] else 0,
                },
            },
        }
    except Exception:
        logger.exception("Outperformers overview query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/outperformers/breakdown
# ---------------------------------------------------------------------------

@router.get("/outperformers/breakdown")
async def outperformers_breakdown(
    bucket: str = Query(..., description="revenue_growers | high_margin | margin_growers | other"),
    top_sectors: int = Query(15, ge=5, le=50),
    top_companies: int = Query(25, ge=5, le=100),
):
    """Sector mix and top companies for a given bucket.

    Used to answer "what kind of activities do these outperformers have?".
    """
    if bucket not in VALID_BUCKETS:
        raise HTTPException(status_code=400, detail="Invalid bucket")

    bucket_filter = _bucket_filter_clause(bucket, alias="l")

    if bucket == "revenue_growers":
        order_expr = "l.rev_growth_pct DESC NULLS LAST"
    elif bucket == "high_margin":
        order_expr = "l.margin_25 DESC NULLS LAST"
    elif bucket == "margin_growers":
        order_expr = "l.margin_growth_pct DESC NULLS LAST"
    else:
        order_expr = "l.rev_25 DESC NULLS LAST"

    try:
        sectors = fetch_all(f"""
            {_bucket_cte_sql()}
            SELECT
                SUBSTR(ci.nace_code, 1, 2)                         AS nace2,
                COALESCE(nl.description, SUBSTR(ci.nace_code,1,2)) AS sector,
                COUNT(*)                                           AS companies,
                SUM(l.rev_25) / 1e6                                AS revenue_m,
                SUM(l.ebitda_25) / 1e6                             AS ebitda_m
            FROM labeled l
            JOIN company_info ci ON ci.enterprise_number = l.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code, 1, 2)
            WHERE {bucket_filter}
              AND ci.nace_code IS NOT NULL
            GROUP BY SUBSTR(ci.nace_code, 1, 2), nl.description
            ORDER BY companies DESC
            LIMIT %s
        """, (top_sectors,))

        companies = fetch_all(f"""
            {_bucket_cte_sql()}
            SELECT
                l.enterprise_number                                 AS cbe,
                COALESCE(ci.name, l.enterprise_number)              AS name,
                ci.nace_code,
                COALESCE(nl.description, SUBSTR(ci.nace_code,1,2))  AS sector,
                ci.city,
                l.rev_23, l.rev_25,
                l.ebitda_23, l.ebitda_25,
                l.rev_growth_pct,
                l.margin_25, l.margin_23, l.margin_growth_pct
            FROM labeled l
            JOIN company_info ci ON ci.enterprise_number = l.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code, 1, 2)
            WHERE {bucket_filter}
            ORDER BY {order_expr}
            LIMIT %s
        """, (top_companies,))

        return {
            "bucket": bucket,
            "sectors": _serialize(sectors),
            "companies": _serialize(companies),
        }
    except Exception:
        logger.exception("Outperformers breakdown query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
