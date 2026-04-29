"""Staatsblad structured-events API — Stage 3.

Endpoints:
    GET /api/companies/{cbe}/events
        All structured events for one CBE, ordered by pub_date DESC.
    GET /api/events/search
        Semantic/keyword search across all events.  Wired in Phase 3e;
        returns 501 until the embedding store is populated.

Auth: tier-gated via the existing TierLimitMiddleware + optional_user
dependency — matches the pattern used by the richer structure/enrichment
endpoints.  Read-only.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import optional_user
from db import fetch_all, fetch_one, get_connection, put_connection
from embeddings import embed_query
from utils import clean_cbe

logger = logging.getLogger(__name__)
router = APIRouter(tags=["staatsblad-events"])


VALID_EVENT_TYPES = {
    "admin_event", "capital_event", "share_transfer", "ownership_change",
    "ma_event", "liquidation_event", "corporate_change", "other_notable",
}


def _should_search_events_query(text: str) -> bool:
    """Return False for very short, non-numeric event searches.

    Two- and three-character Gazette searches are both noisy and expensive:
    they cannot use semantic search and force broad FTS/trigram scans. CBE-like
    numeric lookups stay enabled because partial enterprise numbers are useful.
    """
    stripped = (text or "").strip()
    return len(stripped) >= 4 or bool(re.search(r"\d{4,}", stripped))


def _serialize(row: dict) -> dict:
    import decimal, datetime as _dt
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (_dt.date, _dt.datetime)):
            out[k] = v.isoformat() if v else None
        else:
            out[k] = v
    return out


# ── GET /api/companies/{cbe}/events ─────────────────────────


@router.get("/api/companies/{cbe}/events")
async def company_events(
    cbe: str,
    event_type: Optional[str] = Query(None),
    since_date: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(optional_user),
):
    """All structured Staatsblad events for one company.

    Event timeline, newest first.  Filterable by event_type (one of the
    8 canonical enum values) and since_date (ISO YYYY-MM-DD).
    """
    cbe = clean_cbe(cbe)
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")

    params: list = [cbe]
    filters = "WHERE enterprise_number = %s"
    if event_type:
        if event_type not in VALID_EVENT_TYPES:
            raise HTTPException(400, f"event_type must be one of {sorted(VALID_EVENT_TYPES)}")
        filters += " AND event_type = %s"
        params.append(event_type)
    if since_date:
        try:
            since = date.fromisoformat(since_date)
        except ValueError:
            raise HTTPException(400, "since_date must be YYYY-MM-DD")
        filters += " AND pub_date >= %s"
        params.append(since)

    params.append(limit)

    try:
        rows = fetch_all(
            f"""SELECT id, pub_reference, pub_date, event_type, sub_type,
                       event_date, person_name, person_role, entity_name,
                       amount_eur, amount_shares, summary, extracted_at,
                       extraction_model
                FROM staatsblad_event
                {filters}
                ORDER BY pub_date DESC, id DESC
                LIMIT %s""",
            tuple(params),
        )
        return {"events": [_serialize(r) for r in rows]}
    except Exception:
        logger.exception("company_events failed for %s", cbe)
        raise HTTPException(500, "Internal server error")


# ── GET /api/events/search (semantic — filled in Phase 3e) ──


@router.get("/api/events/search")
async def search_events(
    q: str = Query(..., min_length=2),
    event_type: Optional[str] = Query(None),
    since_date: Optional[str] = Query(None),
    enterprise_number: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user=Depends(optional_user),
):
    """Semantic search across the structured event corpus.

    Wired in Phase 3e: embeds the query via OpenRouter's
    `text-embedding-3-small` (256 dims), runs pgvector cosine on
    `staatsblad_event_embedding`, and blends with a trigram/FTS
    keyword score on (summary, person_name, entity_name).

    Until the embedding store is populated (first Phase 4a backfill
    run), this endpoint returns a keyword-only fallback so the wiring
    can be exercised in staging.  To force the 501, pass
    `strict_semantic=true` (not implemented yet).
    """
    text = q.strip()
    if not _should_search_events_query(text):
        return {"query": q, "results": [], "count": 0, "skipped": "short_query"}

    # Validate filters upfront
    if event_type and event_type not in VALID_EVENT_TYPES:
        raise HTTPException(400, f"event_type must be one of {sorted(VALID_EVENT_TYPES)}")
    since: Optional[date] = None
    if since_date:
        try:
            since = date.fromisoformat(since_date)
        except ValueError:
            raise HTTPException(400, "since_date must be YYYY-MM-DD")
    if enterprise_number:
        enterprise_number = clean_cbe(enterprise_number)
        if not enterprise_number.isdigit() or len(enterprise_number) != 10:
            raise HTTPException(400, "enterprise_number must be 10 digits")

    # Delegate to the blended search.  If no embeddings exist yet, the
    # function will fall back to FTS+trigram only.
    try:
        # The search page fires this endpoint as a secondary section.
        # Cache query embeddings across semantic company and event search
        # so repeat terms do not pay another provider round-trip.
        emb = await embed_query(text) if len(text) >= 4 else None
    except Exception:
        logger.exception("Embedding call for query failed — falling back to keyword-only")
        emb = None
    try:
        # Accept any non-empty list — let the pgvector cast in
        # `_blended_search` enforce the dim. Hardcoding 256 silently
        # disabled semantic on NVIDIA (1024-dim) in 2026-04 onwards.
        results = _blended_search(
            q=text,
            emb=emb if (isinstance(emb, list) and len(emb) > 0) else None,
            event_type=event_type,
            since=since,
            enterprise_number=enterprise_number,
            limit=limit,
        )
        return {"query": q, "results": results, "count": len(results)}
    except Exception:
        logger.exception("events search failed for q=%r", q)
        raise HTTPException(500, "Internal server error")


def _blended_search(
    q: str,
    emb: Optional[list[float]],
    event_type: Optional[str],
    since: Optional[date],
    enterprise_number: Optional[str],
    limit: int,
) -> list[dict]:
    """Blend pgvector cosine similarity with FTS/trigram keyword score.

    Pass `emb=None` to force keyword-only mode.  The blended path falls
    through to keyword-only automatically when the embedding store is
    empty (no JOIN rows match).
    """
    # Build the filter clause once — reused by both paths.
    filter_parts = []
    filter_params: list = []
    if event_type:
        filter_parts.append("e.event_type = %s")
        filter_params.append(event_type)
    if since:
        filter_parts.append("e.pub_date >= %s")
        filter_params.append(since)
    if enterprise_number:
        filter_parts.append("e.enterprise_number = %s")
        filter_params.append(enterprise_number)
    filter_sql = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""

    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            vector_rows: list[dict] = []
            if emb is not None:
                # Vector-boosted search: ORDER BY (0.6 * 1-cos + 0.4 * trgm)
                # so both signals contribute.  pgvector 1-cosine distance is
                # `1 - (embedding <=> %s)`; we multiply by 0.6 and add a
                # trigram similarity on the summary.
                emb_literal = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
                try:
                    cur.execute(
                        f"""SELECT
                               e.id, e.enterprise_number, e.pub_reference, e.pub_date,
                               e.event_type, e.sub_type, e.event_date, e.person_name,
                               e.person_role, e.entity_name, e.amount_eur,
                               e.amount_shares, e.summary, e.extracted_at,
                               COALESCE(d.denomination, e.enterprise_number) AS company_name,
                               (1.0 - (emb.embedding <=> %s::vector)) AS vec_score,
                               similarity(
                                   coalesce(e.summary, '') || ' ' ||
                                   coalesce(e.person_name, '') || ' ' ||
                                   coalesce(e.entity_name, ''),
                                   %s
                               ) AS trgm_score
                           FROM staatsblad_event e
                           JOIN staatsblad_event_embedding emb ON emb.event_id = e.id
                           LEFT JOIN denomination d
                               ON d.entity_number = e.enterprise_number
                               AND d.type_of_denomination = '001'
                               AND d.language IN ('2','1')
                           WHERE TRUE {filter_sql}
                           ORDER BY (0.6 * (1.0 - (emb.embedding <=> %s::vector))
                                   + 0.4 * similarity(
                                         coalesce(e.summary, '') || ' ' ||
                                         coalesce(e.person_name, '') || ' ' ||
                                         coalesce(e.entity_name, ''),
                                         %s
                                     )) DESC
                           LIMIT %s""",
                        tuple([emb_literal, q] + filter_params + [emb_literal, q, limit]),
                    )
                    cols = [d.name for d in cur.description]
                    vector_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                except Exception:
                    # Missing/empty event embedding infrastructure should
                    # degrade to keyword search, not hide valid Gazette rows.
                    logger.warning("event vector search failed; using keyword fallback", exc_info=True)
                    conn.rollback()
                    cur.close()
                    cur = conn.cursor()

            if vector_rows:
                conn.commit()
                return [_serialize(r) for r in vector_rows]

            # Keyword-only fallback: FTS tsquery + trigram blend. This is
            # also the primary path for very short queries, where semantic
            # retrieval is noisy and expensive.
            cur.execute(
                f"""SELECT
                       e.id, e.enterprise_number, e.pub_reference, e.pub_date,
                       e.event_type, e.sub_type, e.event_date, e.person_name,
                       e.person_role, e.entity_name, e.amount_eur,
                       e.amount_shares, e.summary, e.extracted_at,
                       COALESCE(d.denomination, e.enterprise_number) AS company_name,
                       NULL::float AS vec_score,
                       similarity(
                           coalesce(e.summary, '') || ' ' ||
                           coalesce(e.person_name, '') || ' ' ||
                           coalesce(e.entity_name, ''),
                           %s
                       ) AS trgm_score
                   FROM staatsblad_event e
                   LEFT JOIN denomination d
                       ON d.entity_number = e.enterprise_number
                       AND d.type_of_denomination = '001'
                       AND d.language IN ('2','1')
                   WHERE (
                       to_tsvector('simple',
                           coalesce(e.summary, '') || ' ' ||
                           coalesce(e.person_name, '') || ' ' ||
                           coalesce(e.entity_name, ''))
                       @@ plainto_tsquery('simple', %s)
                       OR similarity(
                           coalesce(e.summary, '') || ' ' ||
                           coalesce(e.person_name, '') || ' ' ||
                           coalesce(e.entity_name, ''),
                           %s) > 0.2
                   ) {filter_sql}
                   ORDER BY trgm_score DESC
                   LIMIT %s""",
                tuple([q, q, q] + filter_params + [limit]),
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.commit()
            return [_serialize(r) for r in rows]
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
    finally:
        put_connection(conn)
