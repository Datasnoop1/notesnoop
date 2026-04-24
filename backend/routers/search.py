"""Semantic-search endpoint backed by `company_embedding`.

`GET /api/search/semantic?q=workwear&limit=20&offset=0&nace_prefix=&region=&min_revenue=`

Flow:
  1. Query embedding — served from `query_embedding_cache` (30-day TTL)
     with a single OpenRouter call on miss (~$0.00002/query).
  2. pgvector cosine against `company_embedding` with the HNSW index. We
     accept the pgvector default `ef_search=40` for pilot; Phase 2 will
     tune it after retrieval-quality measurements.
  3. Filter out rows with `bulk_confidence IN ('low','insufficient_information')`
     by default. Power users opt in via `?include_uncertain=1`.
  4. Optional NACE prefix / region / min revenue filters (same columns as
     the classic screener).
  5. Tier-gated via `TierLimitMiddleware` in `main.py` — this endpoint
     classifies into `ai_enrichments_per_day` because every miss burns
     an embedding call.

The ranking blend (0.7·cosine + 0.2·log(revenue) + 0.1·recency) from the
plan is NOT implemented in Phase 1 — pure cosine keeps the contract
simple for pilot smoke-testing. Phase 6 wires the blend in alongside the
semantic-first screener UX redesign.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one
from embeddings import embed_query
from search_normalization import (
    detect_query_type,
    extract_cbe_digits,
    normalize_name as _v2_normalize_name,
    reversed_key as _v2_reversed_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

SEMANTIC_MAX_LIMIT = 50
SEMANTIC_DEFAULT_LIMIT = 20


def _sanitize_nace_prefix(v: str | None) -> str:
    """Only digits allowed, max 5 chars — NACE codes are numeric."""
    if not v:
        return ""
    clean = "".join(ch for ch in v if ch.isdigit())[:5]
    return clean


def _sanitize_region(v: str | None) -> str:
    """Allow only alphanumerics, spaces, and dashes; cap length."""
    if not v:
        return ""
    clean = "".join(ch for ch in v if ch.isalnum() or ch in " -")[:64]
    return clean.strip()


@router.get("/semantic")
async def semantic_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(SEMANTIC_DEFAULT_LIMIT, ge=1, le=SEMANTIC_MAX_LIMIT),
    offset: int = Query(0, ge=0, le=10_000),
    nace_prefix: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    min_revenue: Optional[float] = Query(None, ge=0),
    include_uncertain: int = Query(0, ge=0, le=1),
):
    """Return companies ranked by cosine similarity to the query embedding."""
    text = (q or "").strip()
    if len(text) < 2:
        raise HTTPException(status_code=422, detail="query_too_short")

    embedding = await embed_query(text)
    if not embedding:
        raise HTTPException(status_code=503, detail="embedding_unavailable")

    # Build the SQL with parameterised filters. pgvector needs the
    # embedding as a literal (it's a typed vector), so we coerce via
    # CAST on a string param — psycopg2 parameter binding handles it
    # safely.
    nace = _sanitize_nace_prefix(nace_prefix)
    reg = _sanitize_region(region)

    clauses = []
    params: list = [str(embedding)]

    if not include_uncertain:
        # SAFE: the string literal below is hardcoded — no user input
        # reaches the SQL body here. If you ever make this clause
        # dependent on request data, parameterise it instead.
        clauses.append(
            "COALESCE(ce_bulk.bulk_confidence, 'low') IN ('high', 'medium')"
        )

    if nace:
        clauses.append("ci.nace_code LIKE %s")
        params.append(nace + "%")

    if reg:
        clauses.append("(ci.city ILIKE %s OR ci.zipcode LIKE %s)")
        params.append(f"%{reg}%")
        params.append(f"{reg}%")

    if min_revenue is not None:
        clauses.append("COALESCE(fl.revenue, 0) >= %s")
        params.append(float(min_revenue))

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = f"""
        SELECT ce.enterprise_number,
               ci.name, ci.city, ci.nace_code,
               nl.description AS nace_description,
               fl.revenue, fl.ebitda, fl.fte_total,
               ce_bulk.bulk_confidence,
               ce_bulk.bulk_summary->>'business_description' AS description,
               1 - (ce.embedding <=> %s::vector) AS similarity
          FROM company_embedding ce
          JOIN company_info ci        ON ci.enterprise_number = ce.enterprise_number
     LEFT JOIN nace_lookup nl         ON nl.nace_code = ci.nace_code
     LEFT JOIN financial_latest fl    ON fl.enterprise_number = ce.enterprise_number
     LEFT JOIN company_enrichment ce_bulk
                ON ce_bulk.enterprise_number = ce.enterprise_number
          {where}
      ORDER BY ce.embedding <=> %s::vector
         LIMIT %s OFFSET %s
    """
    # Two embedding slots in the SQL — append again + pagination.
    params.append(str(embedding))
    params.append(int(limit))
    params.append(int(offset))

    try:
        rows = fetch_all(sql, params)
    except Exception as e:
        logger.exception("semantic search failed for q=%r", text[:80])
        raise HTTPException(status_code=500, detail=f"query_failed:{type(e).__name__}")

    results = []
    for r in rows:
        results.append({
            "enterprise_number": r["enterprise_number"],
            "name": r.get("name"),
            "city": r.get("city"),
            "nace_code": r.get("nace_code"),
            "nace_description": r.get("nace_description"),
            "revenue": r.get("revenue"),
            "ebitda": r.get("ebitda"),
            "fte_total": r.get("fte_total"),
            "description": r.get("description"),
            "confidence": r.get("bulk_confidence"),
            "similarity": float(r.get("similarity") or 0.0),
        })

    return {
        "q": text,
        "limit": limit,
        "offset": offset,
        "count": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# GET /api/search/suggest?q=...&limit=5
# Grouped autocomplete for the header search dropdown.
# p95 target <150 ms. Single round-trip via json_build_object.
# ---------------------------------------------------------------------------

SUGGEST_MAX_LIMIT = 10
SUGGEST_DEFAULT_LIMIT = 5


@router.get("/suggest")
async def suggest(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(SUGGEST_DEFAULT_LIMIT, ge=1, le=SUGGEST_MAX_LIMIT),
):
    """Grouped autocomplete: companies, people, CBE exact, addresses.

    Fires on every keystroke once the query hits 2 chars (frontend
    debounces to 150 ms). Uses prefix matching (indexed) not trigram
    similarity so the hot path stays fast.
    """
    raw = (q or "").strip()
    if len(raw) < 2:
        return _empty_suggest(raw)

    qtype = detect_query_type(raw)
    cbe_digits = extract_cbe_digits(raw) if qtype == "cbe" else None
    nq = _v2_normalize_name(raw)
    rev = _v2_reversed_key(raw)

    params = {
        "nq": nq or None,
        "nq_pfx": (nq + "%") if nq else None,
        "rev": rev or None,
        "cbe_pfx": (cbe_digits + "%") if cbe_digits else None,
        "limit": int(limit),
    }
    try:
        row = fetch_one(_SUGGEST_SQL, params)
    except Exception:
        logger.exception("suggest failed for q=%r", raw[:80])
        return _empty_suggest(raw)
    if not row or not row.get("payload"):
        return _empty_suggest(raw)
    payload = row["payload"]
    # psycopg2 returns JSON columns as parsed dicts when using the
    # default JSON decoder; wrap defensively.
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    payload.setdefault("q", raw)
    return payload


def _empty_suggest(q: str) -> dict:
    return {
        "q": q,
        "companies": [],
        "people": [],
        "cbe_match": None,
        "addresses": [],
    }


_SUGGEST_SQL = """
WITH
companies AS (
    SELECT ci.enterprise_number AS cbe,
           ci.name,
           ci.city,
           COALESCE(jfc.category, 'commercial') AS category,
           (ci.name_normalized = %(nq)s)::int AS exact_match,
           CASE WHEN COALESCE(jfc.category, 'commercial') = 'commercial' THEN 0 ELSE 1 END AS cat_order
    FROM company_info ci
    JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
    LEFT JOIN juridical_form_category jfc ON jfc.code = e.juridical_form
    WHERE %(nq_pfx)s IS NOT NULL
      AND (ci.name_normalized LIKE %(nq_pfx)s OR ci.name_normalized = %(nq)s)
    ORDER BY exact_match DESC, cat_order, ci.name
    LIMIT %(limit)s
),
people_raw AS (
    SELECT a.name, a.enterprise_number
    FROM administrator a
    WHERE a.person_type = 'natural'
      AND a.name_normalized IS NOT NULL
      AND %(nq_pfx)s IS NOT NULL
      AND (
          a.name_normalized LIKE %(nq_pfx)s
          OR (%(rev)s IS NOT NULL AND a.name_reversed = %(rev)s)
      )
    LIMIT 200
),
people AS (
    SELECT INITCAP(MIN(p.name)) AS name,
           COUNT(DISTINCT p.enterprise_number)::int AS company_count
    FROM people_raw p
    GROUP BY LOWER(p.name)
    ORDER BY company_count DESC, 1
    LIMIT %(limit)s
),
cbe_match AS (
    SELECT e.enterprise_number AS cbe,
           COALESCE(ci.name, e.enterprise_number) AS name
    FROM enterprise e
    LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
    WHERE %(cbe_pfx)s IS NOT NULL
      AND e.enterprise_number LIKE %(cbe_pfx)s
    ORDER BY e.enterprise_number
    LIMIT 1
),
addresses AS (
    SELECT DISTINCT ON (COALESCE(ad.street_nl, ad.street_fr, ''), ci.city)
           COALESCE(ad.street_nl, ad.street_fr) AS street,
           ci.city,
           ad.zipcode,
           ci.enterprise_number AS cbe
    FROM company_info ci
    JOIN address ad ON ad.entity_number = ci.enterprise_number
                    AND ad.type_of_address = 'REGO'
    WHERE %(nq_pfx)s IS NOT NULL
      AND (
          LOWER(ad.street_nl)        LIKE LOWER(%(nq_pfx)s)
          OR LOWER(ad.street_fr)     LIKE LOWER(%(nq_pfx)s)
          OR LOWER(ad.municipality_nl) LIKE LOWER(%(nq_pfx)s)
          OR LOWER(ad.municipality_fr) LIKE LOWER(%(nq_pfx)s)
      )
    LIMIT 3
)
SELECT json_build_object(
  -- Preserve CTE ORDER BY inside the aggregate (per the Postgres
  -- spec, plain json_agg doesn't promise order — only the aggregate's
  -- own ORDER BY does).
  'companies',  COALESCE((SELECT json_agg(
                    json_build_object(
                        'cbe', c.cbe, 'name', c.name,
                        'city', c.city, 'category', c.category
                    )
                    ORDER BY c.exact_match DESC, c.cat_order, c.name
                 ) FROM companies c),  '[]'::json),
  'people',     COALESCE((SELECT json_agg(
                    json_build_object('name', p.name, 'company_count', p.company_count)
                    ORDER BY p.company_count DESC, p.name
                 ) FROM people p),     '[]'::json),
  'cbe_match',  (SELECT row_to_json(cm) FROM cbe_match cm LIMIT 1),
  'addresses',  COALESCE((SELECT json_agg(row_to_json(a)) FROM addresses a),  '[]'::json)
) AS payload
"""
