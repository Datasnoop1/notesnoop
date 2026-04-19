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
