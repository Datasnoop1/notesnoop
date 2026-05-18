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

from cache import ttl_cache
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
    """Semantic company search (hybrid semantic + lexical ranking)."""
    text = (q or "").strip()
    if len(text) < 2:
        raise HTTPException(status_code=422, detail="query_too_short")

    qtype = detect_query_type(text)
    cbe_digits = extract_cbe_digits(text) if qtype == "cbe" else None
    nq = _v2_normalize_name(text)
    rev = _v2_reversed_key(text)

    # Build the SQL with parameterised filters. pgvector needs the
    # embedding as a literal (it's a typed vector), so we coerce via
    # CAST on a string param — psycopg2 parameter binding handles it
    # safely.
    nace = _sanitize_nace_prefix(nace_prefix)
    reg = _sanitize_region(region)

    clauses = []
    params: list = []

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

    # Fast paths:
    # - CBE-like queries: bypass embeddings and do direct lookup.
    # - Very short queries: lexical-only (cheap, avoids noisy embeddings).
    if cbe_digits and len(cbe_digits) >= 4:
        sql = f"""
            SELECT ci.enterprise_number,
                   ci.name, ci.city, ci.nace_code,
                   nl.description AS nace_description,
                   fl.revenue, fl.ebitda, fl.fte_total,
                   ce_bulk.bulk_confidence,
                   ce_bulk.bulk_summary->>'business_description' AS description,
                   1.0 AS similarity,
                   1.0 AS lexical_score
              FROM company_info ci
         LEFT JOIN nace_lookup nl      ON nl.nace_code = ci.nace_code
         LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
         LEFT JOIN company_enrichment ce_bulk
                    ON ce_bulk.enterprise_number = ci.enterprise_number
              {where} {"AND" if where else "WHERE"} ci.enterprise_number LIKE %s
          ORDER BY ci.enterprise_number
             LIMIT %s OFFSET %s
        """
        params.extend([cbe_digits + "%", int(limit), int(offset)])
    elif len(nq) < 4:
        sql = f"""
            WITH lex AS (
                SELECT ci.enterprise_number,
                       GREATEST(
                           similarity(ci.name_normalized, %s),
                           similarity(ci.name_normalized, %s),
                           similarity(ci.name_normalized, %s)
                       ) AS lexical_score
                  FROM company_info ci
                 WHERE ci.name_normalized LIKE %s
                    OR ci.name_normalized LIKE %s
                 ORDER BY lexical_score DESC
                 LIMIT 400
            )
            SELECT ci.enterprise_number,
                   ci.name, ci.city, ci.nace_code,
                   nl.description AS nace_description,
                   fl.revenue, fl.ebitda, fl.fte_total,
                   ce_bulk.bulk_confidence,
                   ce_bulk.bulk_summary->>'business_description' AS description,
                   NULL::float8 AS similarity,
                   lex.lexical_score
              FROM lex
              JOIN company_info ci        ON ci.enterprise_number = lex.enterprise_number
         LEFT JOIN nace_lookup nl         ON nl.nace_code = ci.nace_code
         LEFT JOIN financial_latest fl    ON fl.enterprise_number = ci.enterprise_number
         LEFT JOIN company_enrichment ce_bulk
                    ON ce_bulk.enterprise_number = ci.enterprise_number
              {where}
          ORDER BY lex.lexical_score DESC NULLS LAST
             LIMIT %s OFFSET %s
        """
        params.extend([
            nq,
            rev,
            text.lower(),
            nq + "%",
            "%" + nq + "%",
            int(limit),
            int(offset),
        ])
    else:
        embedding = await embed_query(text)
        if not embedding:
            raise HTTPException(status_code=503, detail="embedding_unavailable")

        sql = f"""
            WITH
            sem AS (
                SELECT ce.enterprise_number,
                       1 - (ce.embedding <=> %s::vector) AS similarity
                  FROM company_embedding ce
                 ORDER BY ce.embedding <=> %s::vector
                 LIMIT 250
            ),
            lex AS (
                SELECT ci.enterprise_number,
                       GREATEST(
                           similarity(ci.name_normalized, %s),
                           similarity(ci.name_normalized, %s)
                       ) AS lexical_score
                  FROM company_info ci
                 WHERE ci.name_normalized = %s
                    OR ci.name_normalized LIKE %s
                    OR ci.name_normalized LIKE %s
                    OR similarity(ci.name_normalized, %s) > 0.35
                 ORDER BY lexical_score DESC
                 LIMIT 250
            ),
            candidates AS (
                SELECT enterprise_number FROM sem
                UNION
                SELECT enterprise_number FROM lex
            )
            SELECT c.enterprise_number,
                   ci.name, ci.city, ci.nace_code,
                   nl.description AS nace_description,
                   fl.revenue, fl.ebitda, fl.fte_total,
                   ce_bulk.bulk_confidence,
                   ce_bulk.bulk_summary->>'business_description' AS description,
                   sem.similarity,
                   lex.lexical_score,
                   (0.65 * COALESCE(sem.similarity, 0)
                    + 0.25 * COALESCE(lex.lexical_score, 0)
                    + 0.10 * LEAST(
                        1.0,
                        GREATEST(0.0, LN(10 + COALESCE(fl.revenue, 0)) / 20.0)
                      )
                   ) AS score
              FROM candidates c
              JOIN company_info ci        ON ci.enterprise_number = c.enterprise_number
         LEFT JOIN sem                  ON sem.enterprise_number = c.enterprise_number
         LEFT JOIN lex                  ON lex.enterprise_number = c.enterprise_number
         LEFT JOIN nace_lookup nl       ON nl.nace_code = ci.nace_code
         LEFT JOIN financial_latest fl  ON fl.enterprise_number = c.enterprise_number
         LEFT JOIN company_enrichment ce_bulk
                    ON ce_bulk.enterprise_number = c.enterprise_number
              {where}
          ORDER BY score DESC
             LIMIT %s OFFSET %s
        """
        params.extend([
            str(embedding),
            str(embedding),
            nq,
            rev,
            nq,
            nq + "%",
            "%" + nq + "%",
            nq,
            int(limit),
            int(offset),
        ])

    try:
        rows = fetch_all(sql, params)
    except Exception:
        logger.exception("semantic search failed for q=%r", text[:80])
        raise HTTPException(status_code=500, detail="query_failed")

    query_tokens = [t for t in (nq or "").split() if len(t) >= 3][:6]
    results = []
    for r in rows:
        name = (r.get("name") or "").lower()
        desc = (r.get("description") or "").lower()
        reasons: list[str] = []
        for tok in query_tokens:
            if tok and (tok in name or tok in desc):
                reasons.append(tok)
            if len(reasons) >= 3:
                break

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
            "similarity": (
                None
                if r.get("similarity") is None
                else float(r.get("similarity") or 0.0)
            ),
            "lexical_score": (
                None
                if r.get("lexical_score") is None
                else float(r.get("lexical_score") or 0.0)
            ),
            "match_reasons": reasons,
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


@ttl_cache(ttl_seconds=60, maxsize=1024)
def _suggest_cached(raw: str, limit: int) -> dict:
    """Run the suggest pipeline once and memoise. Keyed on `(raw, limit)`
    so any normalisation drift is invisible to the cache.

    60 s TTL is short enough that name additions / typos surface within
    the minute, and long enough that "t", "to", "tot", "tota", "total"
    typed sequentially by users on the same prefix all share the same
    cached row after the first hit. maxsize bounds memory at ~1k keys.
    """
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
    row = fetch_one(_SUGGEST_SQL, params)
    if not row or not row.get("payload"):
        return _empty_suggest(raw)
    payload = row["payload"]
    if isinstance(payload, str):
        import json
        payload = json.loads(payload)
    payload.setdefault("q", raw)
    return payload


@router.get("/suggest")
async def suggest(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(SUGGEST_DEFAULT_LIMIT, ge=1, le=SUGGEST_MAX_LIMIT),
):
    """Grouped autocomplete: companies, people, CBE exact, addresses.

    Fires on every keystroke once the query hits 2 chars (frontend
    debounces to 150 ms). Uses prefix matching (indexed) not trigram
    similarity so the hot path stays fast. Result cached 60 s — common
    short prefixes (`tot`, `koffi`, `antwer`) repeat constantly across
    users, so memoising keeps the autocomplete loader snappy.
    """
    raw = (q or "").strip()
    if len(raw) < 2:
        return _empty_suggest(raw)
    try:
        return _suggest_cached(raw.lower(), int(limit))
    except Exception:
        logger.exception("suggest failed for q=%r", raw[:80])
        return _empty_suggest(raw)


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
    FROM administrator_current a
    WHERE a.person_type = 'natural'
      AND a.name_normalized IS NOT NULL
      AND %(nq_pfx)s IS NOT NULL
      AND length(%(nq_pfx)s) >= 4  -- ≥3-char prefix; 2-char prefix
                                   -- on 1M admin rows is ~3s even
                                   -- with trigram index.
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
    -- The 4-OR ILIKE produces tens of thousands of candidates for common
    -- prefixes (e.g. "antwer" + wildcard → 65k+). DISTINCT ON over that
    -- whole set was the main hot-path cost (~600 ms). Take a hard 200-row
    -- pre-cap, then DISTINCT ON in an outer SELECT — same 3-row output,
    -- ~50x fewer rows through the sort.
    SELECT DISTINCT ON (street, city) street, city, zipcode, cbe
    FROM (
        SELECT COALESCE(ad.street_nl, ad.street_fr) AS street,
               ci.city,
               ad.zipcode,
               ci.enterprise_number AS cbe
        FROM address ad
        JOIN company_info ci ON ci.enterprise_number = ad.entity_number
        WHERE ad.type_of_address = 'REGO'
          AND %(nq_pfx)s IS NOT NULL
          AND length(%(nq_pfx)s) >= 4
          AND (
              ad.street_nl          ILIKE %(nq_pfx)s
              OR ad.street_fr       ILIKE %(nq_pfx)s
              OR ad.municipality_nl ILIKE %(nq_pfx)s
              OR ad.municipality_fr ILIKE %(nq_pfx)s
          )
        LIMIT 200
    ) raw_addr
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
