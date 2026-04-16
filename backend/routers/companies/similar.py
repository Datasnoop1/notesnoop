"""Companies similar router — sector benchmarks, similar companies, AI re-ranking, embeddings.

The ``/similar/ai`` endpoint blends three retrieval legs (embedding NN, NACE
peers, size-band fallback) with focus-sensitive weights, then asks an LLM
to re-rank the top 25 candidates with specific, business-grounded reasons.
See ``backend/retrieval.py``, ``backend/rerank.py``, ``backend/similar_cache.py``,
and ``backend/ai_routing.py`` for the moving parts.
"""

import json
import logging
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from db import fetch_all, fetch_one, execute
from auth import get_current_user
from ai_routing import (
    SIMILAR_COMPANIES_ROUTING,
    estimate_cost_usd,
    get_tier_config,
    select_tier,
)
from retrieval import (
    LLM_INPUT_SET_SIZE,
    blend_candidates,
    leg_needs_fallback,
    retrieve_by_embedding,
    retrieve_by_nace,
    retrieve_by_size_band,
)
from rerank import (
    MIN_CANDIDATES_FOR_LLM,
    build_target_insight_block,
    call_rerank_llm,
    render_prompt,
)
from similar_cache import compute_content_hash, ensure_similar_cache_schema
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# Bumped whenever §4.2 prompt text or §4.3 output schema changes. Any bump
# forces cache invalidation for every CBE because the hash includes it.
PROMPT_VERSION = "v2.0.1"

FOCUS_VALUES = ("activity", "size", "geography")

# We always ask the LLM for up to this many items and cache the full ranking.
# The client-supplied `limit` is then applied as a post-filter so "Find more"
# (which expands limit from 10 to 20) doesn't trigger a cache miss and a
# redundant LLM call. 20 matches the upper bound of the `limit` query param.
MAX_RANKED_ITEMS = 20


# ── Sector Benchmarking ──────────────────────────────────────────

@router.get("/{cbe}/sector-benchmark")
async def sector_benchmark(cbe: str):
    """Return percentile rankings for a company within its NACE sector (single batched query)."""
    cbe = clean_cbe(cbe)

    try:
        info = fetch_one(
            "SELECT nace_code FROM company_info WHERE enterprise_number = %s", (cbe,),
        )
        if not info or not info.get("nace_code"):
            return {"error": "no_nace", "benchmarks": []}

        nace = info["nace_code"]

        # Single query: get company values + all percentiles in one shot
        row = fetch_one("""
            WITH company AS (
                SELECT revenue, ebitda, net_profit, equity, total_assets, fte_total, fiscal_year,
                       CASE WHEN revenue > 0 THEN ebitda / revenue * 100 END AS ebitda_margin,
                       CASE WHEN total_assets > 0 THEN equity / total_assets * 100 END AS equity_ratio
                FROM financial_latest WHERE enterprise_number = %s
            ),
            peers AS (
                SELECT fl.*,
                       CASE WHEN fl.revenue > 0 THEN fl.ebitda / fl.revenue * 100 END AS ebitda_margin,
                       CASE WHEN fl.total_assets > 0 THEN fl.equity / fl.total_assets * 100 END AS equity_ratio
                FROM financial_latest fl
                JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
                WHERE ci.nace_code = %s
            )
            SELECT
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS peer_count,
                c.fiscal_year, c.revenue, c.ebitda, c.net_profit, c.equity, c.total_assets, c.fte_total,
                c.ebitda_margin, c.equity_ratio,
                -- Revenue
                (SELECT COUNT(*) FROM peers WHERE revenue < c.revenue AND revenue IS NOT NULL) AS rev_below,
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS rev_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p75,
                -- EBITDA
                (SELECT COUNT(*) FROM peers WHERE ebitda < c.ebitda AND ebitda IS NOT NULL) AS ebitda_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p75,
                -- Net Profit
                (SELECT COUNT(*) FROM peers WHERE net_profit < c.net_profit AND net_profit IS NOT NULL) AS np_below,
                (SELECT COUNT(*) FROM peers WHERE net_profit IS NOT NULL) AS np_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY net_profit) FROM peers WHERE net_profit IS NOT NULL) AS np_med,
                -- FTE
                (SELECT COUNT(*) FROM peers WHERE fte_total < c.fte_total AND fte_total IS NOT NULL) AS fte_below,
                (SELECT COUNT(*) FROM peers WHERE fte_total IS NOT NULL) AS fte_total_cnt,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fte_total) FROM peers WHERE fte_total IS NOT NULL) AS fte_med,
                -- Total Assets
                (SELECT COUNT(*) FROM peers WHERE total_assets < c.total_assets AND total_assets IS NOT NULL) AS ta_below,
                (SELECT COUNT(*) FROM peers WHERE total_assets IS NOT NULL) AS ta_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_assets) FROM peers WHERE total_assets IS NOT NULL) AS ta_med,
                -- EBITDA Margin
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin < c.ebitda_margin AND ebitda_margin IS NOT NULL) AS em_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda_margin) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_med,
                -- Equity Ratio
                (SELECT COUNT(*) FROM peers WHERE equity_ratio < c.equity_ratio AND equity_ratio IS NOT NULL) AS er_below,
                (SELECT COUNT(*) FROM peers WHERE equity_ratio IS NOT NULL) AS er_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY equity_ratio) FROM peers WHERE equity_ratio IS NOT NULL) AS er_med
            FROM company c
        """, (cbe, nace))

        if not row or not row.get("fiscal_year"):
            return {"error": "no_financials", "benchmarks": []}

        nace_label = fetch_one("SELECT description FROM nace_lookup WHERE nace_code = %s", (nace,))

        def pct(below, total):
            return round((below / total) * 100, 1) if total and total > 0 else None

        def fv(v):
            return float(v) if v is not None else None

        benchmarks = []
        defs = [
            ("Revenue", "eur", "revenue", "rev_below", "rev_total", "rev_p25", "rev_med", "rev_p75"),
            ("EBITDA", "eur", "ebitda", "ebitda_below", "ebitda_total", "ebitda_p25", "ebitda_med", "ebitda_p75"),
            ("Net Profit", "eur", "net_profit", "np_below", "np_total", None, "np_med", None),
            ("FTE", "num", "fte_total", "fte_below", "fte_total_cnt", None, "fte_med", None),
            ("Total Assets", "eur", "total_assets", "ta_below", "ta_total", None, "ta_med", None),
            ("EBITDA Margin", "pct", "ebitda_margin", "em_below", "em_total", None, "em_med", None),
            ("Equity Ratio", "pct", "equity_ratio", "er_below", "er_total", None, "er_med", None),
        ]
        for label, fmt, val_key, below_key, total_key, p25_key, med_key, p75_key in defs:
            val = row.get(val_key)
            total = row.get(total_key)
            if val is None or not total:
                continue
            benchmarks.append({
                "metric": label, "format": fmt,
                "value": fv(val),
                "percentile": pct(row.get(below_key, 0), total),
                "p25": fv(row.get(p25_key)) if p25_key else None,
                "median": fv(row.get(med_key)) if med_key else None,
                "p75": fv(row.get(p75_key)) if p75_key else None,
                "peer_count": total,
            })

        return {
            "nace_code": nace,
            "nace_label": nace_label["description"] if nace_label else nace,
            "fiscal_year": row["fiscal_year"],
            "peer_count": row.get("peer_count", 0),
            "benchmarks": benchmarks,
        }
    except Exception:
        logger.exception("Sector benchmark failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/similar — non-AI sector peers (unchanged contract)
# ---------------------------------------------------------------------------

@router.get("/{cbe}/similar")
async def get_similar_companies(cbe: str):
    """Find up to 10 companies in the same NACE sector with closest revenue."""
    cbe = clean_cbe(cbe)

    try:
        target = fetch_one("""
            SELECT ci.nace_code, fl.revenue
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number = %s
        """, (cbe,))

        if not target:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        nace = target.get("nace_code")
        revenue = target.get("revenue")

        if not nace:
            return []

        if revenue and revenue > 0:
            rev_min = float(revenue) * 0.1
            rev_max = float(revenue) * 10.0
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity,
                       fl.total_assets, fl.personnel_costs
                FROM company_info ci
                JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                  AND fl.revenue IS NOT NULL
                  AND fl.revenue BETWEEN %s AND %s
                ORDER BY ABS(fl.revenue - %s)
                LIMIT 100
            """, (nace, cbe, rev_min, rev_max, float(revenue)))
        else:
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity,
                       fl.total_assets, fl.personnel_costs
                FROM company_info ci
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                ORDER BY fl.revenue DESC NULLS LAST
                LIMIT 100
            """, (nace, cbe))

        return [_serialize_row(r) for r in rows]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Similar companies failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/similar/ai — AI-enhanced similarity (rewrite)
# ---------------------------------------------------------------------------

# Response field set — every row must have every key (null-padded) so the
# frontend can rely on a stable shape regardless of degradation path.
_RESULT_FIELDS = (
    "enterprise_number", "name", "city",
    "revenue", "ebitda", "fte_total", "fiscal_year",
    "ebit", "net_profit", "equity", "total_assets", "personnel_costs",
)


def _candidate_to_result(c: dict, ai_reason: Optional[str]) -> dict:
    """Shape one blended candidate into the public API response row."""
    row = c.get("row", {})
    serialized = _serialize_row({k: row.get(k) for k in _RESULT_FIELDS})
    serialized["ai_reason"] = ai_reason
    serialized["match_score"] = int(c.get("match_score") or 0)
    serialized["provenance"] = c.get("provenance") or "fallback_size_band"
    serialized["signals"] = {
        "embedding_similarity": (
            float(c["embedding_similarity"]) if c.get("embedding_similarity") else None
        ),
        "nace_match": c.get("nace_match_label") or "none",
        "revenue_ratio": c.get("revenue_ratio"),
        "geo_match": c.get("geo_label") or "different",
    }
    return serialized


def _emit_log(event: dict) -> None:
    """Write one structured JSON line to stdout. Never raises."""
    try:
        event["event"] = "similar_ai"
        logger.info(json.dumps(event, default=str, ensure_ascii=False))
    except Exception:
        # Observability must never break the response path.
        logger.exception("Failed to emit similar_ai log line")


@router.get("/{cbe}/similar/ai")
async def get_similar_companies_ai(
    cbe: str,
    focus: Literal["activity", "size", "geography"] = Query("activity"),
    limit: int = Query(10, ge=1, le=20),
    user=Depends(get_current_user),
):
    """Blend NACE, embedding, and size-band peers; re-rank with an LLM.

    Tier limits and the per-IP rate limiter (backend/main.py and
    backend/rate_limit.py) still apply — this handler never bypasses them.
    Every failure mode resolves to HTTP 200 with either results or ``[]``.
    """
    started = time.monotonic()
    cbe = clean_cbe(cbe)
    tier_key = select_tier(cheap_mode=False)
    tier_cfg = get_tier_config(tier_key)
    primary_model = tier_cfg["model"]

    log_event: dict = {
        "cbe_target": cbe,
        "focus": focus,
        "limit": limit,
        "tier_selected": tier_key,
        "model_attempted": [],
        "model_succeeded": None,
        "cache_hit": False,
        "cache_reason": None,
        "content_hash": None,
        "leg_a_count": 0,
        "leg_b_count": 0,
        "leg_c_count": 0,
        "candidates_after_merge": 0,
        "candidates_sent_to_llm": 0,
        "llm_returned_count": 0,
        "llm_valid_count": 0,
        "llm_latency_ms": 0,
        "total_latency_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd_estimated": 0.0,
        "degraded": None,
        "prompt_version": PROMPT_VERSION,
    }

    try:
        ensure_similar_cache_schema()

        # ── Resolve target ────────────────────────────────────────
        try:
            target = fetch_one(
                """
                SELECT ci.enterprise_number, ci.name, ci.nace_code, ci.city, ci.zipcode,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity, fl.total_assets, fl.personnel_costs,
                       COALESCE(nl.description, ci.nace_code) AS nace_desc,
                       ce.ai_insights
                FROM company_info ci
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
                WHERE ci.enterprise_number = %s
                """,
                (cbe,),
            )
        except Exception:
            logger.exception("Target lookup failed for %s", cbe)
            log_event["degraded"] = "db_error_target"
            return []

        if not target:
            log_event["degraded"] = "target_not_found"
            return []

        # Is there an embedding row for the target?
        try:
            has_embedding_row = fetch_one(
                "SELECT 1 FROM company_embedding WHERE enterprise_number = %s", (cbe,),
            )
        except Exception:
            # pgvector may be missing in some environments — treat as no embedding.
            has_embedding_row = None
        has_embedding = bool(has_embedding_row)

        target_nace = target.get("nace_code")
        if not target_nace and not has_embedding:
            log_event["degraded"] = "no_nace_no_embedding"
            return []

        # ── Run retrieval legs ────────────────────────────────────
        try:
            leg_a = retrieve_by_embedding(cbe, has_embedding)
            leg_b = retrieve_by_nace(cbe, target_nace, target.get("revenue"))
            legs = {"embedding": leg_a, "nace": leg_b, "size_band": []}
            log_event["leg_a_count"] = len(leg_a)
            log_event["leg_b_count"] = len(leg_b)

            if leg_needs_fallback(legs):
                leg_c = retrieve_by_size_band(cbe, target.get("revenue"))
                legs["size_band"] = leg_c
                log_event["leg_c_count"] = len(leg_c)
        except Exception:
            logger.exception("Retrieval legs failed for %s", cbe)
            log_event["degraded"] = "db_error_retrieval"
            return []

        blended = blend_candidates(legs, focus, target)
        log_event["candidates_after_merge"] = len(blended)

        if not blended:
            log_event["degraded"] = "no_candidates"
            return []

        # ── Trim and check if LLM step is worth running ────────────
        candidates = blended[:LLM_INPUT_SET_SIZE]
        log_event["candidates_sent_to_llm"] = len(candidates)

        if len(candidates) < MIN_CANDIDATES_FOR_LLM:
            log_event["degraded"] = "too_few_for_llm"
            # Return blended top-N, sliced to the client's `limit`.
            return [_candidate_to_result(c, None) for c in candidates[:limit]]

        # ── Content hash + cache lookup ───────────────────────────
        cand_sorted = sorted(c["enterprise_number"] for c in candidates)
        content_hash = compute_content_hash(
            target_row=target,
            target_insights=_raw_insights_str(target.get("ai_insights")),
            candidate_cbes_sorted=cand_sorted,
            focus=focus,
            prompt_version=PROMPT_VERSION,
            model=primary_model,
        )
        log_event["content_hash"] = content_hash

        cached_result = _try_cache(cbe, focus, content_hash, candidates, limit)
        if cached_result is not None:
            log_event["cache_hit"] = True
            log_event["cache_reason"] = "fresh"
            log_event["model_succeeded"] = cached_result["_model_used"]
            return cached_result["rows"][:limit]
        log_event["cache_reason"] = _cache_miss_reason(cbe, focus, content_hash)

        # ── Build prompt and call LLM ─────────────────────────────
        # Always ask the LLM for up to MAX_RANKED_ITEMS so the cached ranking
        # covers both the default `limit=10` view and the expanded `limit=20`
        # "Find more" view without a second round-trip to the model.
        prompt = render_prompt(target, candidates, MAX_RANKED_ITEMS)
        llm_result = await call_rerank_llm(prompt, tier_key, n_candidates=len(candidates))

        log_event["model_attempted"] = llm_result.get("attempted", [])
        log_event["llm_latency_ms"] = sum(llm_result.get("latencies", {}).values())
        for model, usage in (llm_result.get("usage") or {}).items():
            log_event["input_tokens"] += usage.get("input_tokens", 0)
            log_event["output_tokens"] += usage.get("output_tokens", 0)
            log_event["cost_usd_estimated"] += estimate_cost_usd(
                model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
            )

        items = llm_result.get("items")
        if items is None:
            log_event["degraded"] = "llm_unavailable"
            log_event["llm_returned_count"] = 0
            log_event["llm_valid_count"] = 0
            # Blended fallback: return the top candidates sliced to `limit`.
            return [_candidate_to_result(c, None) for c in candidates[:limit]]

        model_used = llm_result.get("model_used")
        log_event["model_succeeded"] = model_used
        log_event["llm_returned_count"] = len(items)
        log_event["llm_valid_count"] = len(items)

        # ── Reorder candidates by LLM ranks ───────────────────────
        # Build the full ranking (up to MAX_RANKED_ITEMS) once, cache it,
        # then slice to the client's `limit`.
        full_result = _apply_llm_ranking(candidates, items, MAX_RANKED_ITEMS)

        # ── UPSERT cache ──────────────────────────────────────────
        _upsert_cache(cbe, focus, content_hash, model_used, full_result, candidates)

        return full_result[:limit]

    except Exception:
        logger.exception("Similar AI endpoint crashed for %s", cbe)
        log_event["degraded"] = "unexpected_exception"
        return []
    finally:
        log_event["total_latency_ms"] = int((time.monotonic() - started) * 1000)
        log_event["cost_usd_estimated"] = round(log_event["cost_usd_estimated"], 6)
        _emit_log(log_event)


# ---------------------------------------------------------------------------
# Cache helpers — local to the endpoint because they mutate response shape
# ---------------------------------------------------------------------------

def _raw_insights_str(ai_insights: object) -> str | None:
    """Coerce the ai_insights column to the exact string we hash over.

    Input can be a JSON string (from psycopg), a dict (from downstream parsing),
    or None. Returning a stable canonical form keeps the content hash stable.
    """
    if ai_insights is None:
        return None
    if isinstance(ai_insights, str):
        return ai_insights
    try:
        return json.dumps(ai_insights, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None


def _try_cache(cbe: str, focus: str, content_hash: str, candidates: list[dict], limit: int):
    """Return {rows, _model_used} if a fresh cache row matches, else None."""
    try:
        row = fetch_one(
            """
            SELECT ranked_cbes, reasons, match_scores, provenance, signals, model_used
            FROM ai_similar_cache
            WHERE enterprise_number = %s
              AND focus = %s
              AND content_hash = %s
              AND generated_at > NOW() - INTERVAL '30 days'
            """,
            (cbe, focus, content_hash),
        )
    except Exception:
        logger.exception("Cache lookup failed for %s", cbe)
        return None
    if not row or not row.get("ranked_cbes"):
        return None

    try:
        ranked_cbes = json.loads(row["ranked_cbes"])
        reasons = json.loads(row["reasons"]) if row.get("reasons") else []
        match_scores = json.loads(row["match_scores"]) if row.get("match_scores") else []
        provenance = json.loads(row["provenance"]) if row.get("provenance") else []
        signals = json.loads(row["signals"]) if row.get("signals") else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    # Rehydrate by zipping cached metadata with live financials. We re-query
    # financials rather than caching them so the UI always sees fresh numbers.
    if not ranked_cbes:
        return {"rows": [], "_model_used": row.get("model_used")}

    placeholders = ",".join(["%s"] * len(ranked_cbes))
    try:
        live = fetch_all(
            f"""
            SELECT ci.enterprise_number, ci.name, ci.city,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                   fl.ebit, fl.net_profit, fl.equity, fl.total_assets, fl.personnel_costs
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number IN ({placeholders})
            """,
            tuple(ranked_cbes),
        )
    except Exception:
        logger.exception("Cache hydration query failed for %s", cbe)
        return None
    by_cbe = {r["enterprise_number"]: r for r in live}

    rows: list[dict] = []
    for i, c in enumerate(ranked_cbes):
        raw = by_cbe.get(c)
        if not raw:
            continue
        serialized = _serialize_row({k: raw.get(k) for k in _RESULT_FIELDS})
        serialized["ai_reason"] = reasons[i] if i < len(reasons) else None
        serialized["match_score"] = int(match_scores[i]) if i < len(match_scores) else None
        serialized["provenance"] = provenance[i] if i < len(provenance) else "fallback_size_band"
        serialized["signals"] = signals[i] if i < len(signals) else {
            "embedding_similarity": None, "nace_match": "none",
            "revenue_ratio": None, "geo_match": "different",
        }
        rows.append(serialized)

    return {"rows": rows, "_model_used": row.get("model_used")}


def _cache_miss_reason(cbe: str, focus: str, content_hash: str) -> str:
    """Best-effort classification of why the cache lookup missed.

    Not on the hot path — only called when we already know we'll recompute,
    so a slightly slow classification is fine.
    """
    try:
        row = fetch_one(
            "SELECT content_hash, focus, generated_at FROM ai_similar_cache WHERE enterprise_number = %s",
            (cbe,),
        )
    except Exception:
        return "miss"
    if not row:
        return "miss"
    if row.get("content_hash") != content_hash or row.get("focus") != focus:
        return "hash_mismatch"
    return "stale"


def _apply_llm_ranking(candidates: list[dict], items: list[dict], limit: int) -> list[dict]:
    """Reorder candidates by LLM ranks; the LLM may return fewer than ``limit``."""
    items_sorted = sorted(items, key=lambda x: x["rank"])
    out: list[dict] = []
    used_indices: set[int] = set()
    for entry in items_sorted:
        idx = entry["index"] - 1  # LLM indices are 1-based
        if idx < 0 or idx >= len(candidates) or idx in used_indices:
            continue
        used_indices.add(idx)
        out.append(_candidate_to_result(candidates[idx], entry["reason"]))
        if len(out) >= limit:
            break
    return out


def _upsert_cache(
    cbe: str,
    focus: str,
    content_hash: str,
    model_used: str | None,
    result_rows: list[dict],
    candidates: list[dict],
) -> None:
    """Persist the re-ranked list. Failure is logged but not raised."""
    try:
        ranked_cbes = [r["enterprise_number"] for r in result_rows]
        reasons = [r.get("ai_reason") for r in result_rows]
        match_scores = [r.get("match_score") for r in result_rows]
        provenance = [r.get("provenance") for r in result_rows]
        signals = [r.get("signals") for r in result_rows]
        execute(
            """
            INSERT INTO ai_similar_cache
                (enterprise_number, ranked_cbes, reasons, generated_at,
                 content_hash, focus, match_scores, provenance, signals, model_used)
            VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (enterprise_number) DO UPDATE SET
                ranked_cbes   = EXCLUDED.ranked_cbes,
                reasons       = EXCLUDED.reasons,
                generated_at  = NOW(),
                content_hash  = EXCLUDED.content_hash,
                focus         = EXCLUDED.focus,
                match_scores  = EXCLUDED.match_scores,
                provenance    = EXCLUDED.provenance,
                signals       = EXCLUDED.signals,
                model_used    = EXCLUDED.model_used
            """,
            (
                cbe,
                json.dumps(ranked_cbes),
                json.dumps(reasons),
                content_hash,
                focus,
                json.dumps(match_scores),
                json.dumps(provenance),
                json.dumps(signals, default=str),
                model_used,
            ),
        )
    except Exception:
        logger.exception("Cache write failed for %s", cbe)


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/semantic-similar — pure embedding neighbour search
# ---------------------------------------------------------------------------

@router.get("/{cbe}/semantic-similar")
async def semantic_similar_companies(cbe: str, limit: int = Query(20, ge=1, le=50)):
    """Find companies with similar business descriptions using vector embeddings."""
    from embeddings import find_similar_by_embedding, ensure_embedding_table
    ensure_embedding_table()
    cbe = clean_cbe(cbe)

    results = await find_similar_by_embedding(cbe, limit=limit)
    if not results:
        return []

    cbes = [r["enterprise_number"] for r in results]
    if cbes:
        placeholders = ",".join(["%s"] * len(cbes))
        financials = fetch_all(f"""
            SELECT enterprise_number, revenue, ebitda, fte_total, fiscal_year
            FROM financial_latest
            WHERE enterprise_number IN ({placeholders})
        """, tuple(cbes))
        fin_map = {r["enterprise_number"]: r for r in financials}

        for r in results:
            fin = fin_map.get(r["enterprise_number"], {})
            r["revenue"] = float(fin["revenue"]) if fin.get("revenue") else None
            r["ebitda"] = float(fin["ebitda"]) if fin.get("ebitda") else None
            r["fte_total"] = float(fin["fte_total"]) if fin.get("fte_total") else None
            r["fiscal_year"] = fin.get("fiscal_year")
            r["similarity"] = round(float(r.get("similarity", 0)), 4)

    return results
