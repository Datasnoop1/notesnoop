"""Graveyard router — non-active companies and repeat-offender directors."""

import logging
import decimal
import datetime
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graveyard", tags=["graveyard"])

# Simple in-memory cache — these queries are heavy but data changes at most daily.
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 600  # 10 minutes


def _cached(key: str):
    """Return cached value if fresh, else None."""
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None


def _set_cache(key: str, val: object):
    _cache[key] = (time.time(), val)

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

# Bankruptcy codes (declared + closure stages) and judicial reorganisation
# (WCO — Wet op Continuïteit Ondernemingen) codes used for the
# Scorebord / In-Process split.
BANKRUPTCY_CODES = ("048", "049", "050", "051", "052", "053")
WCO_CODES = ("030", "031", "040", "041", "042", "043", "091")


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
    cached = _cached("overview")
    if cached:
        return cached
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

        result = {
            "active_count": totals["healthy_count"] if totals else 0,
            "non_active_count": totals["troubled_count"] if totals else 0,
            "by_status": _serialize(by_category),
            "by_situation": _serialize(by_situation),
            "by_decade": _serialize(by_decade),
        }
        _set_cache("overview", result)
        return result
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
    """Scorebord — directors/administrators ranked by *finished* bankruptcies.

    A company counts toward `failed_count` when its juridical_situation is a
    bankruptcy code AND there is no currently-open Regsol case. Companies still
    in active proceedings are surfaced via `/in-process` instead so the
    scorebord reflects settled track record rather than ongoing cases.
    """
    cache_key = f"offenders:{min_failed}:{limit}"
    cached = _cached(cache_key)
    if cached:
        return cached
    try:
        rows = fetch_all("""
            WITH person_companies AS (
                SELECT
                    UPPER(TRIM(a.name)) AS norm_name,
                    a.enterprise_number,
                    CASE
                        WHEN e.juridical_situation IN %s
                         AND NOT EXISTS (
                             SELECT 1 FROM insolvency_case ic
                             WHERE ic.enterprise_number = e.enterprise_number
                               AND ic.status = 'open'
                         )
                        THEN 'finished_bankruptcy'
                        WHEN e.juridical_situation IN ('000','001','002','003','090','100')
                        THEN 'healthy'
                        ELSE 'other'
                    END AS bucket
                FROM administrator a
                INNER JOIN enterprise e ON e.enterprise_number = a.enterprise_number
                WHERE a.person_type = 'natural'
                  AND a.name IS NOT NULL
                  AND TRIM(a.name) != ''
            ),
            person_stats AS (
                SELECT
                    norm_name,
                    COUNT(DISTINCT enterprise_number) FILTER (WHERE bucket = 'finished_bankruptcy') AS failed_count,
                    COUNT(DISTINCT enterprise_number) FILTER (WHERE bucket = 'healthy') AS active_count
                FROM person_companies
                GROUP BY norm_name
                HAVING COUNT(DISTINCT enterprise_number) FILTER (WHERE bucket = 'finished_bankruptcy') >= %s
            )
            SELECT norm_name AS name, failed_count, active_count
            FROM person_stats
            ORDER BY failed_count DESC, norm_name
            LIMIT %s
        """, (BANKRUPTCY_CODES, min_failed, limit))

        result = {
            "offenders": _serialize(rows),
            "total": len(rows),
        }
        _set_cache(cache_key, result)
        return result
    except Exception:
        logger.exception("Repeat offenders query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/graveyard/in-process
# ---------------------------------------------------------------------------

@router.get("/in-process")
async def in_process(
    case_type: Optional[str] = Query(
        None,
        description="Filter: 'bankruptcy', 'wco' (reorganisation), or omit for both",
    ),
    limit: int = Query(200, ge=1, le=1000),
):
    """Companies currently in bankruptcy or judicial reorganisation (WCO).

    Signal: either an open Regsol insolvency_case, or a juridical_situation
    code that indicates an in-flight proceeding (even without a Regsol scrape).
    A curator is only recorded in insolvency_case — NULL means unknown or
    not yet assigned.
    """
    cache_key = f"in_process:{case_type}:{limit}"
    cached = _cached(cache_key)
    if cached:
        return cached
    try:
        where_bucket_sql = ""
        params: list = [BANKRUPTCY_CODES, WCO_CODES]
        if case_type == "bankruptcy":
            where_bucket_sql = "WHERE bucket = 'bankruptcy'"
        elif case_type == "wco":
            where_bucket_sql = "WHERE bucket = 'wco'"

        rows = fetch_all(f"""
            WITH base AS (
                SELECT
                    e.enterprise_number,
                    e.juridical_situation,
                    CASE
                        WHEN e.juridical_situation IN %s THEN 'bankruptcy'
                        WHEN e.juridical_situation IN %s THEN 'wco'
                        ELSE NULL
                    END AS kbo_bucket
                FROM enterprise e
                WHERE e.type_of_enterprise = '1'
                  AND (
                    e.juridical_situation IN %s
                    OR e.juridical_situation IN %s
                  )
            ),
            with_case AS (
                SELECT
                    b.enterprise_number,
                    b.juridical_situation,
                    b.kbo_bucket,
                    ic.docket_number,
                    ic.case_type AS regsol_case_type,
                    ic.court,
                    ic.opened_at,
                    ic.status AS regsol_status,
                    ic.curator_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.enterprise_number
                        ORDER BY
                            CASE WHEN ic.status = 'open' THEN 0 ELSE 1 END,
                            ic.opened_at DESC NULLS LAST
                    ) AS rn
                FROM base b
                LEFT JOIN insolvency_case ic
                    ON ic.enterprise_number = b.enterprise_number
                   AND ic.case_type IN ('bankruptcy', 'reorganisation')
                   AND (ic.status = 'open' OR ic.status IS NULL)
            ),
            deduped AS (
                SELECT * FROM with_case WHERE rn = 1
            ),
            classified AS (
                SELECT
                    *,
                    CASE
                        WHEN regsol_case_type = 'bankruptcy' THEN 'bankruptcy'
                        WHEN regsol_case_type = 'reorganisation' THEN 'wco'
                        ELSE kbo_bucket
                    END AS bucket
                FROM deduped
            )
            SELECT
                c.enterprise_number,
                COALESCE(d.denomination, c.enterprise_number) AS company_name,
                c.juridical_situation,
                COALESCE(
                    (SELECT code.description FROM code
                     WHERE code.category = 'JuridicalSituation'
                       AND code.code = c.juridical_situation
                       AND code.language = 'FR'),
                    (SELECT code.description FROM code
                     WHERE code.category = 'JuridicalSituation'
                       AND code.code = c.juridical_situation
                       AND code.language = 'NL'),
                    c.juridical_situation
                ) AS situation_label,
                c.bucket,
                c.docket_number,
                c.court,
                c.opened_at,
                c.curator_name,
                fl.revenue,
                fl.ebitda,
                fl.fte_total,
                fl.fiscal_year
            FROM classified c
            LEFT JOIN denomination d
                ON d.entity_number = c.enterprise_number
               AND d.type_of_denomination = '001'
               AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl
                ON fl.enterprise_number = c.enterprise_number
            {where_bucket_sql}
            ORDER BY
                CASE WHEN c.opened_at IS NULL THEN 1 ELSE 0 END,
                c.opened_at DESC,
                c.enterprise_number
            LIMIT %s
        """, (BANKRUPTCY_CODES, WCO_CODES, BANKRUPTCY_CODES, WCO_CODES, limit))

        total = len(rows)
        n_curator = sum(1 for r in rows if r.get("curator_name"))
        n_bankruptcy = sum(1 for r in rows if r.get("bucket") == "bankruptcy")
        n_wco = sum(1 for r in rows if r.get("bucket") == "wco")

        result = {
            "cases": _serialize(rows),
            "total": total,
            "bankruptcy_count": n_bankruptcy,
            "wco_count": n_wco,
            "curator_assigned_count": n_curator,
        }
        _set_cache(cache_key, result)
        return result
    except Exception:
        logger.exception("In-process query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/graveyard/director-aging
# ---------------------------------------------------------------------------

@router.get("/director-aging")
async def director_aging(
    min_total: int = Query(2, ge=1, le=50, description="Minimum bankrupt companies to qualify"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Directors of currently-bankrupt companies, bucketed by how close to
    the bankruptcy date their mandate was still active.

    Bucket = the *shortest* distance between the person's last active day in
    a company and the date that company's bankruptcy was opened (per Regsol).
    A person still in office when bankruptcy was declared lands in
    `at_bankruptcy`. Mandates that started after the bankruptcy (e.g.
    liquidators appointed post-faillissement) are excluded.

    Requires a known `insolvency_case.opened_at` — companies in bankruptcy
    codes without a Regsol scrape can't be aged and are ignored.
    """
    cache_key = f"director_aging:{min_total}:{limit}"
    cached = _cached(cache_key)
    if cached:
        return cached
    try:
        rows = fetch_all("""
            WITH bankrupt_companies AS (
                SELECT
                    e.enterprise_number,
                    MIN(ic.opened_at) AS bankruptcy_date
                FROM enterprise e
                JOIN insolvency_case ic
                    ON ic.enterprise_number = e.enterprise_number
                WHERE e.juridical_situation IN %s
                  AND ic.case_type = 'bankruptcy'
                  AND ic.opened_at IS NOT NULL
                GROUP BY e.enterprise_number
            ),
            director_mandates AS (
                SELECT
                    UPPER(TRIM(a.name)) AS norm_name,
                    a.enterprise_number,
                    bc.bankruptcy_date,
                    -- to_date rolls invalid-but-shaped strings over instead of
                    -- erroring (e.g. '2024-02-31' → '2024-03-02'), so the whole
                    -- query never crashes on a single malformed KBO field.
                    CASE
                        WHEN a.mandate_start ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                        THEN to_date(SUBSTRING(a.mandate_start, 1, 10), 'YYYY-MM-DD')
                        ELSE NULL
                    END AS mandate_start_d,
                    CASE
                        WHEN a.mandate_end ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                        THEN to_date(SUBSTRING(a.mandate_end, 1, 10), 'YYYY-MM-DD')
                        ELSE NULL
                    END AS mandate_end_d
                FROM administrator a
                JOIN bankrupt_companies bc
                    ON bc.enterprise_number = a.enterprise_number
                WHERE a.person_type = 'natural'
                  AND a.name IS NOT NULL
                  AND TRIM(a.name) != ''
            ),
            distance_calc AS (
                SELECT
                    norm_name,
                    enterprise_number,
                    CASE
                        -- No dates at all: can't attribute an aging bucket.
                        WHEN mandate_start_d IS NULL AND mandate_end_d IS NULL
                            THEN NULL
                        -- Joined after bankruptcy (e.g. liquidator): exclude.
                        WHEN mandate_start_d IS NOT NULL
                             AND mandate_start_d > bankruptcy_date
                            THEN NULL
                        -- Still in office at bankruptcy.
                        WHEN mandate_end_d IS NULL
                             OR mandate_end_d >= bankruptcy_date
                            THEN 0
                        ELSE (bankruptcy_date - mandate_end_d)
                    END AS distance_days
                FROM director_mandates
            ),
            bucketed AS (
                SELECT
                    norm_name,
                    enterprise_number,
                    CASE
                        WHEN distance_days <= 90   THEN 'at_bankruptcy'
                        WHEN distance_days <= 180  THEN 'within_6m'
                        WHEN distance_days <= 365  THEN 'within_1y'
                        WHEN distance_days <= 730  THEN 'within_2y'
                        WHEN distance_days <= 1095 THEN 'within_3y'
                        ELSE 'older'
                    END AS bucket
                FROM distance_calc
                WHERE distance_days IS NOT NULL
            ),
            deduped AS (
                SELECT DISTINCT ON (norm_name, enterprise_number)
                    norm_name, enterprise_number, bucket
                FROM bucketed
                ORDER BY norm_name, enterprise_number,
                    CASE bucket
                        WHEN 'at_bankruptcy' THEN 0
                        WHEN 'within_6m'     THEN 1
                        WHEN 'within_1y'     THEN 2
                        WHEN 'within_2y'     THEN 3
                        WHEN 'within_3y'     THEN 4
                        WHEN 'older'         THEN 5
                    END
            )
            SELECT
                norm_name AS name,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE bucket = 'at_bankruptcy') AS at_bankruptcy,
                COUNT(*) FILTER (WHERE bucket = 'within_6m')     AS within_6m,
                COUNT(*) FILTER (WHERE bucket = 'within_1y')     AS within_1y,
                COUNT(*) FILTER (WHERE bucket = 'within_2y')     AS within_2y,
                COUNT(*) FILTER (WHERE bucket = 'within_3y')     AS within_3y,
                COUNT(*) FILTER (WHERE bucket = 'older')         AS older
            FROM deduped
            GROUP BY norm_name
            HAVING COUNT(*) >= %s
            ORDER BY
                COUNT(*) FILTER (WHERE bucket = 'at_bankruptcy') DESC,
                COUNT(*) DESC,
                norm_name
            LIMIT %s
        """, (BANKRUPTCY_CODES, min_total, limit))

        result = {
            "directors": _serialize(rows),
            "total": len(rows),
            "buckets": [
                {"key": "at_bankruptcy", "label": "≤3 months", "order": 0},
                {"key": "within_6m",     "label": "3–6 months", "order": 1},
                {"key": "within_1y",     "label": "6–12 months", "order": 2},
                {"key": "within_2y",     "label": "1–2 years", "order": 3},
                {"key": "within_3y",     "label": "2–3 years", "order": 4},
                {"key": "older",         "label": ">3 years", "order": 5},
            ],
        }
        _set_cache(cache_key, result)
        return result
    except Exception:
        logger.exception("Director aging query failed")
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
