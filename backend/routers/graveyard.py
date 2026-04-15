"""Graveyard router — non-active companies and repeat-offender directors."""

import logging
import decimal
import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graveyard", tags=["graveyard"])

ROLE_LABELS = {
    "fct:m10": "Director",
    "fct:m11": "Managing director",
    "fct:m12": "Chairman",
    "fct:m13": "Administrator",
    "fct:m14": "Secretary",
    "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor",
    "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

# KBO uses juridical_situation to flag troubled companies.
# All companies have status='AC' in the open data — non-active ones are
# distinguished by juridical_situation codes:
#   000 = Normal, 001 = Juridical creation, 002 = Extension, 090 = New statutes,
#   100 = Identification — these are healthy.
# Everything else is dissolution, liquidation, bankruptcy, merger, etc.
HEALTHY_SITUATIONS = ("000", "001", "002", "003", "090", "100")


def _serialize(rows: list) -> list:
    """Convert Decimal/date types to JSON-safe primitives."""
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
# GET /api/graveyard/overview
# ---------------------------------------------------------------------------

@router.get("/overview")
async def graveyard_overview():
    """Aggregate stats on companies with non-normal juridical situation."""
    try:
        # Total healthy vs troubled
        totals = fetch_one("""
            SELECT
                COUNT(*) FILTER (WHERE juridical_situation IN ('000','001','002','003','090','100'))
                    AS healthy_count,
                COUNT(*) FILTER (WHERE juridical_situation NOT IN ('000','001','002','003','090','100'))
                    AS troubled_count
            FROM enterprise
            WHERE type_of_enterprise = '1'
        """)

        # Breakdown by juridical situation (troubled only)
        by_situation = fetch_all("""
            SELECT
                e.juridical_situation AS code,
                COALESCE(
                    (SELECT c.description FROM code c
                     WHERE c.category = 'JuridicalSituation' AND c.code = e.juridical_situation
                       AND c.language = 'FR'),
                    (SELECT c.description FROM code c
                     WHERE c.category = 'JuridicalSituation' AND c.code = e.juridical_situation
                       AND c.language = 'NL'),
                    e.juridical_situation
                ) AS label,
                COUNT(*) AS count
            FROM enterprise e
            WHERE e.juridical_situation NOT IN ('000','001','002','003','090','100')
              AND e.type_of_enterprise = '1'
            GROUP BY e.juridical_situation
            ORDER BY count DESC
        """)

        # Group situations into categories for the status chart
        by_category = fetch_all("""
            SELECT
                CASE
                    WHEN e.juridical_situation IN ('048','049','050','051','052','053')
                        THEN 'Bankruptcy'
                    WHEN e.juridical_situation IN ('010','012','013','014','112')
                        THEN 'Dissolution / Liquidation'
                    WHEN e.juridical_situation IN ('021','022','023','024','025','026','020')
                        THEN 'Merger / Split'
                    WHEN e.juridical_situation IN ('030','031','040','041','042','043','091')
                        THEN 'Judicial reorganisation'
                    WHEN e.juridical_situation IN ('006','011','015','016','017','018','019')
                        THEN 'Cessation'
                    ELSE 'Other'
                END AS label,
                COUNT(*) AS count
            FROM enterprise e
            WHERE e.juridical_situation NOT IN ('000','001','002','003','090','100')
              AND e.type_of_enterprise = '1'
            GROUP BY label
            ORDER BY count DESC
        """)

        # Troubled companies by founding decade
        by_decade = fetch_all("""
            SELECT
                (EXTRACT(YEAR FROM e.start_date::date) / 10)::int * 10 AS decade,
                COUNT(*) AS count
            FROM enterprise e
            WHERE e.juridical_situation NOT IN ('000','001','002','003','090','100')
              AND e.type_of_enterprise = '1'
              AND e.start_date IS NOT NULL
              AND e.start_date != ''
            GROUP BY decade
            ORDER BY decade
        """)

        return {
            "active_count": totals["healthy_count"] if totals else 0,
            "non_active_count": totals["troubled_count"] if totals else 0,
            "by_status": _serialize(by_category),
            "by_situation": _serialize(by_situation),
            "by_decade": _serialize(by_decade),
        }
    except Exception:
        logger.exception("Graveyard overview query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/graveyard/repeat-offenders
# ---------------------------------------------------------------------------

@router.get("/repeat-offenders")
async def repeat_offenders(
    min_failed: int = Query(2, ge=2, le=50, description="Minimum failed companies to qualify"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
):
    """Directors/administrators who appear in multiple troubled companies.

    Returns a ranked list with failed company count and currently-healthy count.
    """
    try:
        rows = fetch_all("""
            WITH failed_admins AS (
                SELECT
                    UPPER(TRIM(a.name)) AS norm_name,
                    COUNT(DISTINCT a.enterprise_number) AS failed_count
                FROM administrator a
                INNER JOIN enterprise e ON e.enterprise_number = a.enterprise_number
                WHERE a.person_type = 'natural'
                  AND a.name IS NOT NULL
                  AND TRIM(a.name) != ''
                  AND e.juridical_situation NOT IN ('000','001','002','003','090','100')
                  AND e.type_of_enterprise = '1'
                GROUP BY UPPER(TRIM(a.name))
                HAVING COUNT(DISTINCT a.enterprise_number) >= %s
                ORDER BY failed_count DESC
                LIMIT %s
            )
            SELECT
                fa.norm_name AS name,
                fa.failed_count,
                COALESCE(
                    (SELECT COUNT(DISTINCT a2.enterprise_number)
                     FROM administrator a2
                     JOIN enterprise e2 ON e2.enterprise_number = a2.enterprise_number
                     WHERE UPPER(TRIM(a2.name)) = fa.norm_name
                       AND a2.person_type = 'natural'
                       AND e2.juridical_situation IN ('000','001','002','003','090','100')
                       AND e2.type_of_enterprise = '1'),
                    0
                ) AS active_count
            FROM failed_admins fa
            ORDER BY fa.failed_count DESC, fa.norm_name
        """, (min_failed, limit))

        return {
            "offenders": _serialize(rows),
            "total": len(rows),
        }
    except Exception:
        logger.exception("Repeat offenders query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/graveyard/person/{name}/companies
# ---------------------------------------------------------------------------

@router.get("/person/{name}/companies")
async def person_failed_companies(name: str):
    """All company associations for a person, split into troubled vs healthy."""
    try:
        # Troubled companies
        failed_rows = fetch_all("""
            SELECT
                a.enterprise_number,
                COALESCE(d.denomination, a.enterprise_number) AS company_name,
                a.role,
                a.mandate_start,
                a.mandate_end,
                e.juridical_situation,
                COALESCE(
                    (SELECT c.description FROM code c
                     WHERE c.category = 'JuridicalSituation' AND c.code = e.juridical_situation
                       AND c.language = 'FR'),
                    (SELECT c.description FROM code c
                     WHERE c.category = 'JuridicalSituation' AND c.code = e.juridical_situation
                       AND c.language = 'NL'),
                    e.juridical_situation
                ) AS situation_label,
                CASE
                    WHEN e.juridical_situation IN ('048','049','050','051','052','053')
                        THEN 'Bankruptcy'
                    WHEN e.juridical_situation IN ('010','012','013','014','112')
                        THEN 'Dissolution'
                    WHEN e.juridical_situation IN ('021','022','023','024','025','026','020')
                        THEN 'Merger / Split'
                    WHEN e.juridical_situation IN ('030','031','040','041','042','043','091')
                        THEN 'Reorganisation'
                    WHEN e.juridical_situation IN ('006','011','015','016','017','018','019')
                        THEN 'Cessation'
                    ELSE 'Other'
                END AS status_label,
                e.start_date,
                fl.revenue,
                fl.ebitda,
                fl.fte_total,
                fl.fiscal_year
            FROM administrator a
            JOIN enterprise e ON e.enterprise_number = a.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = a.enterprise_number
                AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl ON fl.enterprise_number = a.enterprise_number
            WHERE UPPER(TRIM(a.name)) = UPPER(TRIM(%s))
              AND a.person_type = 'natural'
              AND e.juridical_situation NOT IN ('000','001','002','003','090','100')
              AND e.type_of_enterprise = '1'
            ORDER BY a.mandate_start DESC NULLS LAST
        """, (name,))

        # Healthy companies
        active_rows = fetch_all("""
            SELECT
                a.enterprise_number,
                COALESCE(d.denomination, a.enterprise_number) AS company_name,
                a.role,
                a.mandate_start,
                a.mandate_end,
                fl.revenue,
                fl.ebitda,
                fl.fte_total,
                fl.fiscal_year
            FROM administrator a
            JOIN enterprise e ON e.enterprise_number = a.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = a.enterprise_number
                AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl ON fl.enterprise_number = a.enterprise_number
            WHERE UPPER(TRIM(a.name)) = UPPER(TRIM(%s))
              AND a.person_type = 'natural'
              AND e.juridical_situation IN ('000','001','002','003','090','100')
              AND e.type_of_enterprise = '1'
            ORDER BY a.mandate_start DESC NULLS LAST
        """, (name,))

        # Add role labels and deduplicate
        for row in failed_rows + active_rows:
            row["role_label"] = ROLE_LABELS.get(row.get("role", ""), row.get("role", ""))

        seen_failed = set()
        unique_failed = []
        for row in failed_rows:
            key = (row["enterprise_number"], row.get("role"))
            if key not in seen_failed:
                seen_failed.add(key)
                unique_failed.append(row)

        seen_active = set()
        unique_active = []
        for row in active_rows:
            key = (row["enterprise_number"], row.get("role"))
            if key not in seen_active:
                seen_active.add(key)
                unique_active.append(row)

        return {
            "name": name,
            "failed_companies": _serialize(unique_failed),
            "active_companies": _serialize(unique_active),
        }
    except Exception:
        logger.exception("Person failed companies query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
