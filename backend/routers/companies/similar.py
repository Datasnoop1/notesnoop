"""Companies similar router — sector benchmarks, similar companies, AI re-ranking, embeddings.

The ``/similar/ai`` endpoint blends three retrieval legs (embedding NN, NACE
peers, size-band fallback) with focus-sensitive weights, then asks an LLM
to re-rank the top 25 candidates with specific, business-grounded reasons.
See ``backend/retrieval.py``, ``backend/rerank.py``, ``backend/similar_cache.py``,
and ``backend/ai_routing.py`` for the moving parts.
"""

import json
import logging
import math
import re
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from db import fetch_all, fetch_one, execute
from auth import optional_user
from cache import ttl_cache
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
    call_userpath_rerank_llm,
    render_final_prompt,
    render_shortlist_prompt,
)
from similar_cache import compute_content_hash, ensure_similar_cache_schema
from utils import clean_cbe
from ._helpers import _resolve_nace_label, _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# Bumped whenever §4.2 prompt text or §4.3 output schema changes. Any bump
# forces cache invalidation for every CBE because the hash includes it.
PROMPT_VERSION = "v2.3.0"

FOCUS_VALUES = ("activity", "size", "geography")

# We always ask the LLM for up to this many items and cache the full ranking.
# The client-supplied `limit` is then applied as a post-filter so "Find more"
# (which expands limit from 10 to 20) doesn't trigger a cache miss and a
# redundant LLM call. 20 matches the upper bound of the `limit` query param.
MAX_RANKED_ITEMS = 30
SHORTLIST_SIZE = int(SIMILAR_COMPANIES_ROUTING.get("SHORTLIST_SIZE", 15))
MAX_REASONABLE_SIMILAR_FTE = 50_000
LARGE_SIMILAR_FTE_THRESHOLD = 10_000
MIN_REASONABLE_REVENUE_PER_FTE = 5_000


# ── Sector Benchmarking ──────────────────────────────────────────
#
# The percentile query is expensive on high-cardinality NACEs (retail,
# consulting can exceed 50k peers): seven PERCENTILE_CONT window functions
# in a single CROSS JOIN. The data only changes when an NBB filing for
# THIS company or its peers lands — at most once a day. We cache the
# whole response per CBE for 24h in-process, plus set a private
# Cache-Control so the browser doesn't even round-trip on tab switches.


@ttl_cache(ttl_seconds=86400, maxsize=8192)
def _sector_benchmark_cached(cbe: str) -> dict:
    """Compute the benchmark for one CBE. Pure read — safe to cache.

    Cache key is the cleaned CBE; result is the full JSON dict the
    endpoint returns. 8192 ≈ a typical week's worth of unique benchmark
    views; eviction policy in `cache.py` drops oldest expirations first
    when we go over.
    """
    info = fetch_one(
        "SELECT nace_code FROM company_info WHERE enterprise_number = %s", (cbe,),
    )
    if not info or not info.get("nace_code"):
        return {"error": "no_nace", "benchmarks": []}

    nace = info["nace_code"]
    return _sector_benchmark_compute(cbe, nace)


def _sector_benchmark_compute(cbe: str, nace: str) -> dict:
    """Inner: build the benchmark dict for a (cbe, nace). Pure read.

    Extracted from the original handler so the cache wrapper has a
    clean call site. Handler-level exception logging stays on the
    handler so a misbehaving SQL plan doesn't poison the cache.
    """
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
            c.fiscal_year, c.revenue, c.ebitda, c.net_profit, c.equity, c.total_assets, c.fte_total,
            c.ebitda_margin, c.equity_ratio,
            COUNT(*) FILTER (WHERE p.revenue IS NOT NULL) AS peer_count,
            -- Revenue
            COUNT(*) FILTER (WHERE p.revenue < c.revenue AND p.revenue IS NOT NULL) AS rev_below,
            COUNT(*) FILTER (WHERE p.revenue IS NOT NULL) AS rev_total,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY p.revenue) FILTER (WHERE p.revenue IS NOT NULL) AS rev_p25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.revenue) FILTER (WHERE p.revenue IS NOT NULL) AS rev_med,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY p.revenue) FILTER (WHERE p.revenue IS NOT NULL) AS rev_p75,
            -- EBITDA
            COUNT(*) FILTER (WHERE p.ebitda < c.ebitda AND p.ebitda IS NOT NULL) AS ebitda_below,
            COUNT(*) FILTER (WHERE p.ebitda IS NOT NULL) AS ebitda_total,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY p.ebitda) FILTER (WHERE p.ebitda IS NOT NULL) AS ebitda_p25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.ebitda) FILTER (WHERE p.ebitda IS NOT NULL) AS ebitda_med,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY p.ebitda) FILTER (WHERE p.ebitda IS NOT NULL) AS ebitda_p75,
            -- Net Profit
            COUNT(*) FILTER (WHERE p.net_profit < c.net_profit AND p.net_profit IS NOT NULL) AS np_below,
            COUNT(*) FILTER (WHERE p.net_profit IS NOT NULL) AS np_total,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.net_profit) FILTER (WHERE p.net_profit IS NOT NULL) AS np_med,
            -- FTE
            COUNT(*) FILTER (WHERE p.fte_total < c.fte_total AND p.fte_total IS NOT NULL) AS fte_below,
            COUNT(*) FILTER (WHERE p.fte_total IS NOT NULL) AS fte_total_cnt,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.fte_total) FILTER (WHERE p.fte_total IS NOT NULL) AS fte_med,
            -- Total Assets
            COUNT(*) FILTER (WHERE p.total_assets < c.total_assets AND p.total_assets IS NOT NULL) AS ta_below,
            COUNT(*) FILTER (WHERE p.total_assets IS NOT NULL) AS ta_total,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.total_assets) FILTER (WHERE p.total_assets IS NOT NULL) AS ta_med,
            -- EBITDA Margin
            COUNT(*) FILTER (WHERE p.ebitda_margin < c.ebitda_margin AND p.ebitda_margin IS NOT NULL) AS em_below,
            COUNT(*) FILTER (WHERE p.ebitda_margin IS NOT NULL) AS em_total,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.ebitda_margin) FILTER (WHERE p.ebitda_margin IS NOT NULL) AS em_med,
            -- Equity Ratio
            COUNT(*) FILTER (WHERE p.equity_ratio < c.equity_ratio AND p.equity_ratio IS NOT NULL) AS er_below,
            COUNT(*) FILTER (WHERE p.equity_ratio IS NOT NULL) AS er_total,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY p.equity_ratio) FILTER (WHERE p.equity_ratio IS NOT NULL) AS er_med
        FROM company c
        CROSS JOIN peers p
        GROUP BY
            c.fiscal_year, c.revenue, c.ebitda, c.net_profit, c.equity,
            c.total_assets, c.fte_total, c.ebitda_margin, c.equity_ratio
    """, (cbe, nace))

    if not row or not row.get("fiscal_year"):
        return {"error": "no_financials", "benchmarks": []}

    nace_label = _resolve_nace_label(nace, "2008")

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
        "nace_label": nace_label or nace,
        "fiscal_year": row["fiscal_year"],
        "peer_count": row.get("peer_count", 0),
        "benchmarks": benchmarks,
    }


@router.get("/{cbe}/sector-benchmark")
async def sector_benchmark(cbe: str, response: Response):
    """Return percentile rankings for a company within its NACE sector.

    Backed by a 24h in-process cache (`_sector_benchmark_cached`) +
    24h browser cache so tab-switches and back-button navigation are
    instant. Cache key is the cleaned CBE; underlying NBB filings
    update at most daily, so a stale value is at worst 24h behind.
    """
    cbe = clean_cbe(cbe)
    response.headers["Cache-Control"] = "private, max-age=86400, stale-while-revalidate=86400"
    try:
        return _sector_benchmark_cached(cbe)
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
                SELECT ci.enterprise_number,
                       COALESCE(
                           NULLIF(BTRIM(ci.name), ''),
                           (
                               SELECT d.denomination
                               FROM denomination d
                               WHERE d.entity_number = ci.enterprise_number
                                 AND d.type_of_denomination = '001'
                                 AND d.denomination IS NOT NULL
                                 AND BTRIM(d.denomination) <> ''
                               ORDER BY CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '4' THEN 3 ELSE 4 END,
                                        d.language
                               LIMIT 1
                           )
                       ) AS name,
                       ci.city,
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
                SELECT ci.enterprise_number,
                       COALESCE(
                           NULLIF(BTRIM(ci.name), ''),
                           (
                               SELECT d.denomination
                               FROM denomination d
                               WHERE d.entity_number = ci.enterprise_number
                                 AND d.type_of_denomination = '001'
                                 AND d.denomination IS NOT NULL
                                 AND BTRIM(d.denomination) <> ''
                               ORDER BY CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '4' THEN 3 ELSE 4 END,
                                        d.language
                               LIMIT 1
                           )
                       ) AS name,
                       ci.city,
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

        return [_sanitize_similar_result_row(r) for r in rows]
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
_REASON_ORDER = ("activity", "size", "geography")
_REASON_LABELS = {
    "activity": "Activity",
    "size": "Size",
    "geography": "Geography",
}
_REASON_SECTION_RE = re.compile(r"(Activity|Size|Geography):", re.IGNORECASE)


def _sanitize_similar_result_row(row: dict) -> dict:
    """Normalise Similar-tab rows without changing profile-overview fields."""
    serialized = _serialize_row(row)

    name = serialized.get("name")
    if isinstance(name, str):
        name = name.strip()
    if not name:
        enterprise_number = serialized.get("enterprise_number")
        serialized["name"] = (
            f"CBE {enterprise_number}" if enterprise_number else "Unknown company"
        )
    else:
        serialized["name"] = name

    city = serialized.get("city")
    if isinstance(city, str):
        serialized["city"] = city.strip() or None

    fte_total = serialized.get("fte_total")
    revenue = serialized.get("revenue")
    if isinstance(fte_total, (int, float)) and (
        not math.isfinite(fte_total)
        or fte_total < 0
        or fte_total > MAX_REASONABLE_SIMILAR_FTE
    ):
        serialized["fte_total"] = None
    elif (
        isinstance(fte_total, (int, float))
        and fte_total >= LARGE_SIMILAR_FTE_THRESHOLD
        and isinstance(revenue, (int, float))
        and revenue > 0
        and (revenue / fte_total) < MIN_REASONABLE_REVENUE_PER_FTE
    ):
        serialized["fte_total"] = None

    return serialized


def _describe_nace_match(
    label: str,
    nace_code: str | None,
    nace_desc: str | None,
    activity_anchor: str | None = None,
) -> str:
    if activity_anchor:
        if label == "exact":
            return f"Exact business overlap in {activity_anchor}"
        if label == "class":
            return f"Same 3-digit activity class around {activity_anchor}"
        if label == "group":
            return f"Related 2-digit activity group around {activity_anchor}"
        return f"Business-profile match in {activity_anchor}"
    nace_ref = nace_desc or nace_code or "related activity"
    if label == "exact":
        return f"Exact NACE match in {nace_ref}"
    if label == "class":
        return f"Same 3-digit NACE class around {nace_ref}"
    if label == "group":
        return f"Same 2-digit NACE group around {nace_ref}"
    return f"Blended business-profile match around {nace_ref}"


def _describe_size_match(revenue_ratio: float | None, fte_total: float | int | None) -> str:
    parts: list[str] = []
    if isinstance(revenue_ratio, (int, float)) and revenue_ratio > 0:
        if 0.85 <= revenue_ratio <= 1.15:
            parts.append("Revenue is very close to the target")
        elif 0.6 <= revenue_ratio <= 1.4:
            parts.append("Revenue is in a comparable range")
        elif revenue_ratio < 1:
            parts.append(f"Revenue is smaller at about {revenue_ratio:.1f}x of target")
        else:
            parts.append(f"Revenue is larger at about {revenue_ratio:.1f}x of target")
    else:
        parts.append("Revenue comparison is limited")

    if isinstance(fte_total, (int, float)) and math.isfinite(fte_total) and fte_total > 0:
        parts.append(f"FTE around {int(round(fte_total))}")

    return "; ".join(parts)


def _describe_geo_match(label: str, city: str | None) -> str:
    place = city or "a different location"
    if label == "same_city":
        return f"Same city: {place}"
    if label == "same_province":
        return f"Same province area: {place}"
    return f"Different geography: {place}"


def _structured_reason(activity: str, size: str, geography: str) -> str:
    return f"Activity: {activity} | Size: {size} | Geography: {geography}"


def _extract_reason_sections(reason: str | None) -> dict[str, str]:
    if not reason:
        return {}
    text = " ".join(str(reason).split())
    matches = list(_REASON_SECTION_RE.finditer(text))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for idx, match in enumerate(matches):
        key = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip(" |.;:-")
        if value:
            sections[key] = value
    return sections


def _format_reason_sections(sections: dict[str, str]) -> str:
    parts: list[str] = []
    for key in _REASON_ORDER:
        value = (sections.get(key) or "").strip()
        if value:
            parts.append(f"{_REASON_LABELS[key]}: {value}")
    return " | ".join(parts)


def _clean_reason_section(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip(" |.;:-")


def _is_generic_activity_section(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return True
    generic_patterns = (
        "same sector",
        "same industry",
        "similar activity",
        "related activity",
        "same nace",
        "business-profile match",
        "comparable business",
    )
    if any(pattern in lowered for pattern in generic_patterns):
        return True
    words = re.findall(r"[a-z0-9][a-z0-9&/+.-]*", lowered)
    return len(words) < 3


def _normalize_reason_sections(
    ai_sections: dict[str, str] | None,
    fallback_reason: str,
) -> dict[str, str]:
    fallback_sections = _extract_reason_sections(fallback_reason)
    merged: dict[str, str] = {}
    for key in _REASON_ORDER:
        value = _clean_reason_section((ai_sections or {}).get(key))
        if key == "activity" and _is_generic_activity_section(value):
            value = ""
        if not value:
            value = fallback_sections.get(key) or ""
        merged[key] = value
    return merged


def _fallback_reason_from_candidate(candidate: dict) -> str:
    row = candidate.get("row", {})
    activity = _describe_nace_match(
        candidate.get("nace_match_label") or "none",
        row.get("nace_code"),
        row.get("nace_desc"),
        candidate.get("activity_anchor"),
    )
    size = _describe_size_match(candidate.get("revenue_ratio"), row.get("fte_total"))
    geography = _describe_geo_match(candidate.get("geo_label") or "different", row.get("city"))
    return _structured_reason(activity, size, geography)


def _fallback_reason_from_payload(
    raw_row: dict,
    signals: dict | None,
    provenance: str | None,
) -> str:
    signal_map = signals or {}
    activity = _describe_nace_match(
        signal_map.get("nace_match") or "none",
        raw_row.get("nace_code"),
        raw_row.get("nace_desc"),
        signal_map.get("activity_anchor"),
    )
    if (provenance or "").startswith("embedding") and signal_map.get("nace_match") in (None, "none"):
        activity = "Embedding/business-profile match from similar description patterns"
    size = _describe_size_match(signal_map.get("revenue_ratio"), raw_row.get("fte_total"))
    geography = _describe_geo_match(signal_map.get("geo_match") or "different", raw_row.get("city"))
    return _structured_reason(activity, size, geography)


def _sector_fallback_result(raw_row: dict, target: dict, rank: int) -> dict:
    """Shape a legacy sector-peer row for /similar/ai empty-blend degradation."""
    serialized = _sanitize_similar_result_row(raw_row)
    row_city = (raw_row.get("city") or "").strip().lower()
    target_city = (target.get("city") or "").strip().lower()
    geo_label = "same_city" if row_city and row_city == target_city else "different"

    revenue_ratio = None
    row_revenue = raw_row.get("revenue")
    target_revenue = target.get("revenue")
    if (
        isinstance(row_revenue, (int, float))
        and isinstance(target_revenue, (int, float))
        and target_revenue > 0
    ):
        revenue_ratio = round(row_revenue / target_revenue, 3)

    reason = _structured_reason(
        _describe_nace_match("exact", target.get("nace_code"), target.get("nace_desc")),
        _describe_size_match(revenue_ratio, raw_row.get("fte_total")),
        _describe_geo_match(geo_label, raw_row.get("city")),
    )
    serialized["ai_reason"] = reason
    serialized["ai_reason_sections"] = _extract_reason_sections(reason)
    serialized["match_score"] = max(15, 35 - rank)
    serialized["provenance"] = "sector_fallback"
    serialized["signals"] = {
        "embedding_similarity": None,
        "nace_match": "exact",
        "revenue_ratio": revenue_ratio,
        "activity_overlap": None,
        "activity_anchor": target.get("nace_desc") or target.get("nace_code"),
        "geo_match": geo_label,
    }
    return serialized


def _normalize_reason(
    ai_reason: Optional[str],
    fallback_reason: str,
    ai_sections: dict[str, str] | None = None,
) -> str:
    fallback_sections = _extract_reason_sections(fallback_reason)
    fallback_normalized = _format_reason_sections(fallback_sections) or fallback_reason
    if ai_sections:
        normalized = _format_reason_sections(
            _normalize_reason_sections(ai_sections, fallback_reason)
        )
        if normalized:
            return normalized
    if not ai_reason:
        return fallback_normalized
    text = ai_reason.strip()
    if not text:
        return fallback_normalized

    ai_sections = _extract_reason_sections(text)
    if ai_sections:
        merged = {
            key: ai_sections.get(key) or fallback_sections.get(key) or ""
            for key in _REASON_ORDER
        }
        normalized = _format_reason_sections(merged)
        if normalized:
            return normalized

    return _format_reason_sections({
        "activity": text,
        "size": (
            fallback_sections.get("size")
            or "Comparable scale based on retrieved financial signals"
        ),
        "geography": (
            fallback_sections.get("geography")
            or "Included as a secondary factor"
        ),
    })


def _candidate_to_result(
    c: dict,
    ai_reason: Optional[str],
    ai_sections: dict[str, str] | None = None,
) -> dict:
    """Shape one blended candidate into the public API response row."""
    row = c.get("row", {})
    serialized = _sanitize_similar_result_row({k: row.get(k) for k in _RESULT_FIELDS})
    fallback_reason = _fallback_reason_from_candidate(c)
    normalized_reason = _normalize_reason(ai_reason, fallback_reason, ai_sections=ai_sections)
    normalized_sections = (
        _normalize_reason_sections(ai_sections, fallback_reason)
        if ai_sections
        else _extract_reason_sections(normalized_reason)
    )
    serialized["ai_reason"] = normalized_reason
    serialized["ai_reason_sections"] = normalized_sections
    serialized["match_score"] = int(c.get("match_score") or 0)
    serialized["provenance"] = c.get("provenance") or "fallback_size_band"
    serialized["signals"] = {
        "embedding_similarity": (
            float(c["embedding_similarity"]) if c.get("embedding_similarity") else None
        ),
        "nace_match": c.get("nace_match_label") or "none",
        "revenue_ratio": c.get("revenue_ratio"),
        "activity_overlap": c.get("activity_overlap_score"),
        "activity_anchor": c.get("activity_anchor"),
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


def _record_llm_result(log_event: dict, llm_result: dict) -> None:
    log_event["model_attempted"].extend(llm_result.get("attempted", []))
    log_event["llm_latency_ms"] += sum(llm_result.get("latencies", {}).values())
    for model, usage in (llm_result.get("usage") or {}).items():
        log_event["input_tokens"] += usage.get("input_tokens", 0)
        log_event["output_tokens"] += usage.get("output_tokens", 0)
        log_event["cost_usd_estimated"] += estimate_cost_usd(
            model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
        )


async def _call_rerank_userpath_timed(
    log_event: dict,
    pass_name: str,
    prompt: str,
    tier: str,
    *,
    n_candidates: int,
    schema: str,
) -> dict:
    started = time.monotonic()
    result = await call_userpath_rerank_llm(
        prompt,
        tier,
        n_candidates=n_candidates,
        schema=schema,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    log_event.setdefault("llm_pass_latency_ms", {})[pass_name] = elapsed_ms
    log_event.setdefault("llm_pass_model_used", {})[pass_name] = result.get("model_used")
    log_event.setdefault("llm_pass_errors", {})[pass_name] = result.get("errors", [])
    return result


def _apply_ranked_shortlist(candidates: list[dict], items: list[dict], limit: int) -> list[dict]:
    items_sorted = sorted(items, key=lambda x: x["rank"])
    shortlisted: list[dict] = []
    used_indices: set[int] = set()
    for entry in items_sorted:
        idx = entry["index"] - 1
        if idx < 0 or idx >= len(candidates) or idx in used_indices:
            continue
        used_indices.add(idx)
        shortlisted.append(candidates[idx])
        if len(shortlisted) >= limit:
            break
    if len(shortlisted) < limit:
        for idx, candidate in enumerate(candidates):
            if idx in used_indices:
                continue
            used_indices.add(idx)
            shortlisted.append(candidate)
            if len(shortlisted) >= limit:
                break
    return shortlisted


def _compose_pipeline_model_used(shortlist_model: str | None, final_model: str | None) -> str | None:
    left = (shortlist_model or "").strip()
    right = (final_model or "").strip()
    if left and right:
        return f"{left} -> {right}"
    return right or left or None


@router.get("/{cbe}/similar/ai")
async def get_similar_companies_ai(
    cbe: str,
    focus: Literal["activity", "size", "geography"] = Query("activity"),
    limit: int = Query(10, ge=1, le=30),
    user=Depends(optional_user),
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
    final_tier = "FINAL"
    final_model = get_tier_config(final_tier)["model"]

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
        "llm_pass_latency_ms": {},
        "llm_pass_model_used": {},
        "llm_pass_errors": {},
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
                SELECT ci.enterprise_number,
                       COALESCE(
                           NULLIF(BTRIM(ci.name), ''),
                           (
                               SELECT d.denomination
                               FROM denomination d
                               WHERE d.entity_number = ci.enterprise_number
                                 AND d.type_of_denomination = '001'
                                 AND d.denomination IS NOT NULL
                                 AND BTRIM(d.denomination) <> ''
                               ORDER BY CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '4' THEN 3 ELSE 4 END,
                                        d.language
                               LIMIT 1
                           )
                       ) AS name,
                       ci.nace_code, ci.city, ci.zipcode,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity, fl.total_assets, fl.personnel_costs,
                       COALESCE(nl.description, ci.nace_code) AS nace_desc,
                       ce.bulk_summary,
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
            try:
                fallback_rows = await get_similar_companies(cbe)
            except Exception:
                logger.exception("Sector fallback failed for %s", cbe)
                fallback_rows = []
            if fallback_rows:
                log_event["degraded"] = "sector_fallback_no_candidates"
                return [
                    _sector_fallback_result(row, target, idx)
                    for idx, row in enumerate(fallback_rows[:limit])
                ]
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
        candidate_rows_by_cbe = {
            item["enterprise_number"]: item.get("row", {})
            for item in candidates
        }
        candidate_profile_texts_sorted = [
            _raw_similarity_profile_str(
                candidate_rows_by_cbe.get(enterprise_number, {}).get("bulk_summary"),
                candidate_rows_by_cbe.get(enterprise_number, {}).get("ai_insights"),
            )
            for enterprise_number in cand_sorted
        ]
        content_hash = compute_content_hash(
            target_row=target,
            target_profile_text=_raw_similarity_profile_str(
                target.get("bulk_summary"),
                target.get("ai_insights"),
            ),
            candidate_cbes_sorted=cand_sorted,
            candidate_profile_texts_sorted=candidate_profile_texts_sorted,
            focus=focus,
            prompt_version=PROMPT_VERSION,
            model=f"{primary_model}->{final_model}",
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
        shortlist_limit = max(5, min(SHORTLIST_SIZE, len(candidates)))
        shortlist_prompt = render_shortlist_prompt(target, candidates, shortlist_limit)
        shortlist_result = await _call_rerank_userpath_timed(
            log_event,
            "shortlist",
            shortlist_prompt,
            tier_key,
            n_candidates=len(candidates),
            schema="rank_only",
        )
        _record_llm_result(log_event, shortlist_result)
        if shortlist_result.get("error") == "timeout":
            log_event["degraded"] = "shortlist_llm_timeout"
            return [_candidate_to_result(c, None) for c in candidates[:limit]]

        shortlist_items = shortlist_result.get("items") or []
        if shortlist_items:
            shortlisted_candidates = _apply_ranked_shortlist(
                candidates,
                shortlist_items,
                shortlist_limit,
            )
        else:
            shortlisted_candidates = candidates[:shortlist_limit]

        final_limit = max(5, min(MAX_RANKED_ITEMS, len(shortlisted_candidates)))
        final_prompt = render_final_prompt(target, shortlisted_candidates, final_limit)
        final_result = await _call_rerank_userpath_timed(
            log_event,
            "final",
            final_prompt,
            final_tier,
            n_candidates=len(shortlisted_candidates),
            schema="structured_reason",
        )
        _record_llm_result(log_event, final_result)
        if final_result.get("error") == "timeout":
            log_event["degraded"] = "final_llm_timeout"
            return [_candidate_to_result(c, None) for c in candidates[:limit]]

        final_items = final_result.get("items")
        if final_items is None:
            if shortlist_items:
                log_event["degraded"] = "final_llm_unavailable"
                model_used = shortlist_result.get("model_used")
                log_event["model_succeeded"] = model_used
                log_event["llm_returned_count"] = len(shortlist_items)
                log_event["llm_valid_count"] = len(shortlist_items)
                full_result = _apply_llm_ranking(
                    shortlisted_candidates,
                    shortlist_items,
                    MAX_RANKED_ITEMS,
                )
            else:
                log_event["degraded"] = "llm_unavailable"
                log_event["llm_returned_count"] = 0
                log_event["llm_valid_count"] = 0
                return [_candidate_to_result(c, None) for c in candidates[:limit]]
        else:
            model_used = _compose_pipeline_model_used(
                shortlist_result.get("model_used"),
                final_result.get("model_used"),
            )
            log_event["model_succeeded"] = model_used
            log_event["llm_returned_count"] = len(final_items)
            log_event["llm_valid_count"] = len(final_items)
            full_result = _apply_llm_ranking(
                shortlisted_candidates,
                final_items,
                MAX_RANKED_ITEMS,
            )

        _upsert_cache(cbe, focus, content_hash, model_used, full_result, candidates)
        return full_result[:limit]

        prompt = render_prompt(target, candidates, MAX_RANKED_ITEMS)
        llm_result = await call_userpath_rerank_llm(prompt, tier_key, n_candidates=len(candidates))

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


def _raw_similarity_profile_str(bulk_summary: object, ai_insights: object) -> str:
    """Canonical string for cache invalidation of similarity prompt inputs."""
    payload = {
        "bulk_summary": _raw_insights_str(bulk_summary),
        "ai_insights": _raw_insights_str(ai_insights),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


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
            SELECT ci.enterprise_number,
                   COALESCE(
                       NULLIF(BTRIM(ci.name), ''),
                       (
                           SELECT d.denomination
                           FROM denomination d
                           WHERE d.entity_number = ci.enterprise_number
                             AND d.type_of_denomination = '001'
                             AND d.denomination IS NOT NULL
                             AND BTRIM(d.denomination) <> ''
                           ORDER BY CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '4' THEN 3 ELSE 4 END,
                                    d.language
                           LIMIT 1
                       )
                   ) AS name,
                   ci.city,
                   ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS nace_desc,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                   fl.ebit, fl.net_profit, fl.equity, fl.total_assets, fl.personnel_costs,
                   ce.bulk_summary
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
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
        serialized = _sanitize_similar_result_row({k: raw.get(k) for k in _RESULT_FIELDS})
        stored_signals = signals[i] if i < len(signals) else None
        stored_provenance = provenance[i] if i < len(provenance) else "fallback_size_band"
        normalized_reason = _normalize_reason(
            reasons[i] if i < len(reasons) else None,
            _fallback_reason_from_payload(raw, stored_signals, stored_provenance),
        )
        serialized["ai_reason"] = normalized_reason
        serialized["ai_reason_sections"] = _extract_reason_sections(normalized_reason)
        serialized["match_score"] = int(match_scores[i]) if i < len(match_scores) else None
        serialized["provenance"] = stored_provenance
        serialized["signals"] = stored_signals if stored_signals else {
            "embedding_similarity": None, "nace_match": "none",
            "revenue_ratio": None, "activity_overlap": None,
            "activity_anchor": None, "geo_match": "different",
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


def _entry_reason_sections(entry: dict) -> dict[str, str] | None:
    sections = entry.get("reason_sections")
    if isinstance(sections, dict):
        return sections
    extracted = {
        key: entry.get(key)
        for key in _REASON_ORDER
        if isinstance(entry.get(key), str) and entry.get(key).strip()
    }
    return extracted or None


def _apply_llm_ranking(candidates: list[dict], items: list[dict], limit: int) -> list[dict]:
    """Reorder candidates by LLM ranks, then backfill from blended candidates.

    This keeps the model in charge of the top of the list while ensuring the
    expanded "Find more" view still grows even when the model only returns a
    shorter ranked subset.
    """
    items_sorted = sorted(items, key=lambda x: x["rank"])
    out: list[dict] = []
    used_indices: set[int] = set()
    for entry in items_sorted:
        idx = entry["index"] - 1  # LLM indices are 1-based
        if idx < 0 or idx >= len(candidates) or idx in used_indices:
            continue
        used_indices.add(idx)
        out.append(
            _candidate_to_result(
                candidates[idx],
                entry.get("reason"),
                _entry_reason_sections(entry),
            )
        )
        if len(out) >= limit:
            break

    if len(out) < limit:
        for idx, candidate in enumerate(candidates):
            if idx in used_indices:
                continue
            used_indices.add(idx)
            out.append(_candidate_to_result(candidate, None))
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
