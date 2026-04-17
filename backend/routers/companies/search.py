"""Companies search router — name/CBE search, semantic search, fuzzy match."""

import logging
import re

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one, normalize_name
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/companies/search?q=...
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_companies(q: str = Query(..., min_length=1)):
    """Search companies by name or CBE number.

    SQL extracted from app/pages/2_company.py search_companies().
    """
    query = q.strip()
    # Normalise CBE / VAT input so all of the following route to the
    # same CBE search path:
    #   "0403170701", "0403.170.701", "0403 170 701"
    #   "BE0403170701", "BE 0403.170.701", "BE-0403170701", "be0403170701"
    # The "BE" prefix is only stripped when the remainder is all digits,
    # so a real name like "BE International" still falls through to
    # name search. Use the raw digit string (no zero-padding) for
    # prefix matching so "0403" still matches CBEs starting with 0403.
    # The 4-digit floor prevents "1" from being treated as a CBE.
    candidate = re.sub(r"^\s*BE[\s.\-]*", "", query, flags=re.IGNORECASE)
    candidate = re.sub(r"[\s.\-]", "", candidate)
    if candidate.isdigit() and len(candidate) >= 4:
        query_digits = candidate
        is_cbe_search = True
    else:
        query_digits = query.replace(".", "").replace(" ", "")
        is_cbe_search = query_digits.isdigit() and len(query_digits) >= 4

    try:
        if is_cbe_search:
            # CBE prefix search on enterprise (fast, indexed)
            rows = fetch_all("""
                SELECT e.enterprise_number, COALESCE(ci.name, e.enterprise_number) AS "name",
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM enterprise e
                LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE e.enterprise_number LIKE %s
                LIMIT 20
            """, (f"{query_digits}%",))
        else:
            # First: search company_info (170K, fast, has financials)
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name,
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM company_info ci
                JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE ci.name ILIKE %s
                ORDER BY ci.name
                LIMIT 20
            """, (f"%{query}%",))

            # If not enough results, also search denomination table
            if len(rows) < 20:
                remaining = 20 - len(rows)
                existing_cbes = {r["enterprise_number"] for r in rows}
                extra = fetch_all("""
                    SELECT e.enterprise_number, d.denomination AS "name",
                           e.status, e.juridical_form AS "jf_label",
                           a.municipality_nl AS "city",
                           NULL AS "sector", e.start_date,
                           NULL::real AS "revenue", NULL::real AS "ebitda",
                           NULL::numeric AS "ebitda_margin_pct",
                           NULL::real AS "fte_total", NULL::integer AS "fiscal_year"
                    FROM denomination d
                    JOIN enterprise e ON e.enterprise_number = d.entity_number
                    LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
                    WHERE d.denomination ILIKE %s
                      AND d.type_of_denomination = '001'
                      AND d.language IN ('2','1')
                    ORDER BY d.denomination
                    LIMIT %s
                """, (f"%{query}%", remaining + 10))
                for r in extra:
                    if r["enterprise_number"] not in existing_cbes:
                        rows.append(r)
                        existing_cbes.add(r["enterprise_number"])
                        if len(rows) >= 20:
                            break

            # If no results, try alternative/fuzzy matches
            if not rows:
                words = query.split()
                if len(words) > 1:
                    # Try matching any word
                    conditions = " OR ".join(["ci.name ILIKE %s"] * len(words))
                    params = tuple(f"%{w}%" for w in words)
                    rows = fetch_all(f"""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE {conditions}
                        ORDER BY ci.name LIMIT 20
                    """, params)
                elif len(query) >= 3:
                    # Try prefix match
                    rows = fetch_all("""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE ci.name ILIKE %s
                        ORDER BY ci.name LIMIT 20
                    """, (f"{query}%",))

            # Final fallback: trigram similarity on name_normalized
            if not rows and len(query) >= 3:
                nq = normalize_name(query)
                if nq:
                    rows = fetch_all("""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE ci.name_normalized IS NOT NULL
                          AND similarity(ci.name_normalized, %s) > 0.3
                        ORDER BY similarity(ci.name_normalized, %s) DESC
                        LIMIT 20
                    """, (nq, nq))

            # Address fallback: search by street, city, or zipcode when
            # name-based search returned few results
            if len(rows) < 5 and len(query) >= 2:
                remaining = 20 - len(rows)
                existing_cbes = {r["enterprise_number"] for r in rows}
                like_q = f"%{query}%"
                # Check if query looks like a pure zipcode (4-digit Belgian postal code)
                zip_q = query if query.isdigit() and len(query) == 4 else None
                addr_rows = fetch_all("""
                    SELECT ci.enterprise_number, ci.name,
                           e.status, e.juridical_form AS "jf_label", ci.city,
                           COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                           fl.revenue, fl.ebitda,
                           CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                           fl.fte_total, fl.fiscal_year
                    FROM address a
                    JOIN company_info ci ON ci.enterprise_number = a.entity_number
                    JOIN enterprise e ON e.enterprise_number = a.entity_number
                    LEFT JOIN financial_latest fl ON fl.enterprise_number = a.entity_number
                    LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                    WHERE a.type_of_address = 'REGO'
                      AND (
                          a.street_nl ILIKE %s
                          OR a.street_fr ILIKE %s
                          OR a.municipality_nl ILIKE %s
                          OR a.municipality_fr ILIKE %s
                          OR (%s IS NOT NULL AND a.zipcode = %s)
                      )
                    ORDER BY ci.name
                    LIMIT %s
                """, (like_q, like_q, like_q, like_q, zip_q, zip_q, remaining + 10))
                for r in addr_rows:
                    if r["enterprise_number"] not in existing_cbes:
                        rows.append(r)
                        existing_cbes.add(r["enterprise_number"])
                        if len(rows) >= 20:
                            break

        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("Company search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/semantic-search?q=...
# ---------------------------------------------------------------------------

@router.get("/semantic-search")
async def semantic_search(q: str = Query(..., min_length=1)):
    """Fuzzy / semantic company search using pg_trgm trigram similarity.

    Searches company_info.name with trigram similarity scoring, then falls
    back to ILIKE if no good trigram matches are found.  When the
    company_embedding table contains vectors in the future, cosine-similarity
    results will be merged in automatically.
    """
    query = q.strip()
    nq = normalize_name(query)

    try:
        # --- Phase 1: trigram similarity on name_normalized (GIN-indexed) ---
        trgm_rows = fetch_all("""
            SELECT ci.enterprise_number, ci.name,
                   e.status, e.juridical_form AS "jf_label", ci.city,
                   COALESCE(nl.description, ci.nace_code) AS "sector",
                   e.start_date,
                   fl.revenue, fl.ebitda,
                   CASE WHEN fl.revenue > 0
                        THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                   END AS "ebitda_margin_pct",
                   fl.fte_total, fl.fiscal_year,
                   GREATEST(
                       similarity(ci.name_normalized, %s),
                       similarity(ci.name, %s)
                   ) AS score
            FROM company_info ci
            JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE ci.name_normalized %% %s
               OR ci.name ILIKE %s
            ORDER BY score DESC, ci.name
            LIMIT 25
        """, (nq or query, query, nq or query, f"%{query}%"))

        # --- Phase 2: vector cosine search (when embeddings exist) ---
        emb_rows = []
        try:
            has_embeddings = fetch_one(
                "SELECT EXISTS(SELECT 1 FROM company_embedding LIMIT 1) AS has_data"
            )
            if has_embeddings and has_embeddings.get("has_data"):
                emb_rows = fetch_all("""
                    SELECT ce.enterprise_number, ci.name,
                           e.status, e.juridical_form AS "jf_label", ci.city,
                           COALESCE(nl.description, ci.nace_code) AS "sector",
                           e.start_date,
                           fl.revenue, fl.ebitda,
                           CASE WHEN fl.revenue > 0
                                THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                           END AS "ebitda_margin_pct",
                           fl.fte_total, fl.fiscal_year,
                           0.0::float AS score
                    FROM company_embedding ce
                    JOIN enterprise e ON e.enterprise_number = ce.enterprise_number
                    LEFT JOIN company_info ci ON ci.enterprise_number = ce.enterprise_number
                    LEFT JOIN financial_latest fl ON fl.enterprise_number = ce.enterprise_number
                    LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                    WHERE ce.description ILIKE %s
                    ORDER BY ce.description
                    LIMIT 50
                """, (f"%{query}%",))
        except Exception:
            pass  # embedding table may not exist yet in some environments

        # --- Merge & deduplicate ----------------------------------
        seen = set()
        merged = []
        for row in trgm_rows + emb_rows:
            cbe = row["enterprise_number"]
            if cbe not in seen:
                seen.add(cbe)
                merged.append(row)

        # Drop the internal score column before returning
        for row in merged:
            row.pop("score", None)

        return [_serialize_row(r) for r in merged[:25]]

    except Exception as e:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/fuzzy-match?name=...&threshold=0.4&limit=10
# ---------------------------------------------------------------------------

@router.get("/fuzzy-match")
async def fuzzy_match(
    name: str = Query(..., min_length=1),
    threshold: float = Query(0.3, ge=0.1, le=1.0),
    limit: int = Query(10, ge=1, le=50),
):
    """Fuzzy entity matching using pg_trgm on the normalized name column.

    Matches company names after stripping Belgian legal suffixes (NV, SA,
    BVBA, SRL, etc.) so that "SOLVAY SA", "Solvay", and "SOLVAY NV" all
    match each other.  Returns companies sorted by similarity score.
    """
    normalized_query = normalize_name(name.strip())
    if not normalized_query:
        return []

    try:
        rows = fetch_all("""
            SELECT ci.enterprise_number, ci.name, ci.city, ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS sector,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                   similarity(ci.name_normalized, %s) AS score
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE ci.name_normalized IS NOT NULL
              AND similarity(ci.name_normalized, %s) > %s
            ORDER BY score DESC
            LIMIT %s
        """, (normalized_query, normalized_query, threshold, limit))

        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("Fuzzy match failed")
        raise HTTPException(status_code=500, detail="Internal server error")
