"""Stats router — aggregate analytics across the entire database."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one, get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stats", tags=["stats"])

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

@router.get("/overview")
async def stats_overview(
    province: Optional[str] = Query(None, description="Province filter"),
):
    """Overall database stats: company count, total revenue, EBITDA, FTE, NFD.

    SQL extracted from app/pages/4_stats.py load_overview().
    """
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    try:
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

        # Median margin (computed server-side)
        margin_rows = fetch_all(f"""
            SELECT CAST(fl.ebitda AS REAL) / fl.revenue * 100 AS "margin"
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            WHERE fl.revenue > 500000 AND fl.ebitda IS NOT NULL {prov_clause}
            ORDER BY "margin"
        """)

        median_margin = None
        if margin_rows:
            margins = [float(r["margin"]) for r in margin_rows if r["margin"] is not None]
            if margins:
                margins.sort()
                mid = len(margins) // 2
                median_margin = margins[mid] if len(margins) % 2 else (margins[mid - 1] + margins[mid]) / 2

        result = {}
        if row:
            import decimal
            for k, v in row.items():
                result[k] = float(v) if isinstance(v, decimal.Decimal) else v
        result["median_margin"] = round(median_margin, 1) if median_margin is not None else None

        return result
    except Exception as e:
        logger.exception("Stats overview query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/evolution
# ---------------------------------------------------------------------------

@router.get("/evolution")
async def stats_evolution(
    y_min: int = Query(2021, ge=2015, le=2030),
    y_max: int = Query(2024, ge=2015, le=2030),
    province: Optional[str] = Query(None),
):
    """Financial evolution by fiscal year.

    SQL extracted from app/pages/4_stats.py load_evolution().
    """
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    # Replace fl. with fy. in the province clause for financial_by_year table
    prov_clause_fy = prov_clause.replace("fl.", "fy.") if prov_clause else ""

    try:
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
    except Exception as e:
        logger.exception("Stats evolution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/sectors
# ---------------------------------------------------------------------------

@router.get("/sectors")
async def stats_sectors(
    province: Optional[str] = Query(None),
    top_n: int = Query(10, ge=5, le=50),
):
    """Sector breakdown by 2-digit NACE code.

    SQL extracted from app/pages/4_stats.py load_nace_stats().
    """
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    try:
        raw = fetch_all(f"""
            SELECT
                SUBSTR(ci.nace_code, 1, 2)                                    AS "nace2",
                COALESCE(nl.description, SUBSTR(ci.nace_code,1,2))            AS "sector",
                fl.enterprise_number,
                fl.revenue, fl.ebitda, fl.fte_total,
                COALESCE(fl.lt_financial_debt,0)+COALESCE(fl.st_financial_debt,0)
                    -COALESCE(fl.cash,0)                                      AS "nfd"
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code,1,2)
            WHERE ci.nace_code IS NOT NULL
            {prov_clause}
        """)

        if not raw:
            return []

        # Aggregate in Python (matching the Streamlit approach for median computation)
        from collections import defaultdict
        import statistics

        groups = defaultdict(lambda: {
            "enterprises": set(), "revenues": [], "ebitdas": [],
            "margins": [], "ftes": [], "nfd_ebitdas": [], "sector": "",
        })

        for row in raw:
            nace2 = row["nace2"]
            groups[nace2]["sector"] = row["sector"] or nace2
            groups[nace2]["enterprises"].add(row["enterprise_number"])

            rev = float(row["revenue"]) if row["revenue"] is not None else None
            ebitda = float(row["ebitda"]) if row["ebitda"] is not None else None
            fte = float(row["fte_total"]) if row["fte_total"] is not None else None
            nfd = float(row["nfd"]) if row["nfd"] is not None else None

            if rev is not None:
                groups[nace2]["revenues"].append(rev)
            if ebitda is not None:
                groups[nace2]["ebitdas"].append(ebitda)
            if fte is not None:
                groups[nace2]["ftes"].append(fte)
            if rev and rev > 0 and ebitda is not None:
                groups[nace2]["margins"].append(ebitda / rev * 100)
            if ebitda and ebitda > 0 and nfd is not None:
                groups[nace2]["nfd_ebitdas"].append(nfd / ebitda)

        result = []
        for nace2, data in groups.items():
            n = len(data["enterprises"])
            if n < 10:
                continue
            result.append({
                "nace2": nace2,
                "sector": data["sector"],
                "companies": n,
                "revenue_m": round(sum(data["revenues"]) / 1e6, 1) if data["revenues"] else 0,
                "ebitda_m": round(sum(data["ebitdas"]) / 1e6, 1) if data["ebitdas"] else 0,
                "med_margin": round(statistics.median(data["margins"]), 1) if data["margins"] else None,
                "med_fte": round(statistics.median(data["ftes"]), 0) if data["ftes"] else None,
                "med_nfd_ebitda": round(statistics.median(data["nfd_ebitdas"]), 2) if data["nfd_ebitdas"] else None,
            })

        result.sort(key=lambda x: x["companies"], reverse=True)
        return result[:top_n]

    except Exception as e:
        logger.exception("Stats sectors query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/provinces
# ---------------------------------------------------------------------------

@router.get("/provinces")
async def stats_provinces():
    """Province-level stats.

    SQL extracted from app/pages/4_stats.py load_province_stats().
    """
    try:
        raw = fetch_all(f"""
            SELECT
                {PROVINCE_SQL}                                                 AS "province",
                fl.enterprise_number,
                fl.revenue, fl.ebitda, fl.fte_total
            FROM financial_latest fl
            JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
            WHERE ci.zipcode IS NOT NULL AND {PROVINCE_SQL} != 'Other'
        """)

        if not raw:
            return []

        from collections import defaultdict
        import statistics

        groups = defaultdict(lambda: {
            "enterprises": set(), "revenues": [], "ebitdas": [],
            "margins": [], "ftes": [],
        })

        for row in raw:
            prov = row["province"]
            groups[prov]["enterprises"].add(row["enterprise_number"])
            rev = float(row["revenue"]) if row["revenue"] is not None else None
            ebitda = float(row["ebitda"]) if row["ebitda"] is not None else None
            fte = float(row["fte_total"]) if row["fte_total"] is not None else None
            if rev is not None:
                groups[prov]["revenues"].append(rev)
            if ebitda is not None:
                groups[prov]["ebitdas"].append(ebitda)
            if fte is not None:
                groups[prov]["ftes"].append(fte)
            if rev and rev > 0 and ebitda is not None:
                groups[prov]["margins"].append(ebitda / rev * 100)

        result = []
        for prov, data in groups.items():
            result.append({
                "province": prov,
                "companies": len(data["enterprises"]),
                "revenue_m": round(sum(data["revenues"]) / 1e6, 1) if data["revenues"] else 0,
                "ebitda_m": round(sum(data["ebitdas"]) / 1e6, 1) if data["ebitdas"] else 0,
                "med_margin": round(statistics.median(data["margins"]), 1) if data["margins"] else None,
                "total_fte": round(sum(data["ftes"]), 0) if data["ftes"] else 0,
                "med_fte": round(statistics.median(data["ftes"]), 0) if data["ftes"] else None,
            })

        result.sort(key=lambda x: x["companies"], reverse=True)
        return result

    except Exception as e:
        logger.exception("Stats provinces query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/margin-distribution
# ---------------------------------------------------------------------------

@router.get("/margin-distribution")
async def stats_margin_distribution(
    province: Optional[str] = Query(None),
):
    """EBITDA margin distribution histogram data.

    SQL extracted from app/pages/4_stats.py load_margin_distribution().
    """
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    try:
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
    except Exception as e:
        logger.exception("Margin distribution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/stats/size-distribution
# ---------------------------------------------------------------------------

@router.get("/size-distribution")
async def stats_size_distribution(
    province: Optional[str] = Query(None),
):
    """Company size distribution by revenue bucket.

    SQL extracted from app/pages/4_stats.py load_size_distribution().
    """
    prov_clause = ""
    if province and province in VALID_PROVINCES:
        prov_clause = f"AND {PROVINCE_SQL} = '{province}'"

    try:
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
    except Exception as e:
        logger.exception("Size distribution query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
