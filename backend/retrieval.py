"""Candidate retrieval for the /similar/ai endpoint.

Three legs run independently and are blended into a single ranked list:

    Leg A — pgvector nearest neighbours over company_embedding.
    Leg B — NACE peers with revenue-aware ordering.
    Leg C — size-band fallback keyed on revenue only.

Leg C only runs when legs A and B together produced fewer than 20 unique
candidates. The blended ``match_score`` is a weighted sum whose weights
depend on the caller's ``focus`` (activity / size / geography).

Nothing here calls an LLM; this module is pure candidate selection.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable

from db import fetch_all, fetch_one

logger = logging.getLogger(__name__)


FOCUS_WEIGHTS = {
    "activity":  {"emb": 0.55, "nace": 0.25, "rev": 0.10, "geo": 0.10},
    "size":      {"emb": 0.30, "nace": 0.15, "rev": 0.50, "geo": 0.05},
    "geography": {"emb": 0.30, "nace": 0.15, "rev": 0.15, "geo": 0.40},
}


MIN_SCORE_FLOOR = 15        # candidates below this 0–100 score are dropped (§3.4)
LLM_INPUT_SET_SIZE = 25     # trim to this many before sending to the re-ranker
FALLBACK_TRIGGER = 20       # leg C runs only if A+B together yield fewer than this

# Per-leg fetch caps. Larger than LLM_INPUT_SET_SIZE because the blend can
# reorder candidates, and because dedup across legs shrinks the merged pool.
LEG_A_LIMIT = 60
LEG_B_LIMIT = 60
LEG_C_LIMIT = 40


# ──────────────────────────────────────────────────────────────────────────
# Leg A — pgvector nearest neighbours
# ──────────────────────────────────────────────────────────────────────────

def retrieve_by_embedding(target_cbe: str, has_embedding: bool) -> list[dict]:
    """Fetch up to LEG_A_LIMIT candidates by cosine similarity on company_embedding.

    Returns an empty list if the target has no embedding or if pgvector is
    not enabled (caught by the outer try/except in the endpoint).
    """
    if not has_embedding:
        return []
    try:
        rows = fetch_all(
            """
            SELECT ce.enterprise_number,
                   1 - (ce.embedding <=> target.embedding) AS embedding_similarity
            FROM company_embedding ce
            CROSS JOIN (
                SELECT embedding FROM company_embedding WHERE enterprise_number = %s
            ) target
            WHERE ce.enterprise_number != %s
            ORDER BY ce.embedding <=> target.embedding
            LIMIT %s
            """,
            (target_cbe, target_cbe, LEG_A_LIMIT),
        )
    except Exception:
        logger.exception("retrieve_by_embedding failed for %s", target_cbe)
        return []
    out = []
    for r in rows:
        sim = float(r.get("embedding_similarity") or 0.0)
        out.append({
            "enterprise_number": r["enterprise_number"],
            "embedding_similarity": max(0.0, min(1.0, sim)),
            "_source": "embedding",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Leg B — NACE peers
# ──────────────────────────────────────────────────────────────────────────

def retrieve_by_nace(target_cbe: str, target_nace: str, target_revenue: float | None) -> list[dict]:
    """Fetch NACE peers; rank same-code first, then by revenue log-distance.

    Uses a revenue placeholder of 1.0 when the target has no revenue so the
    SQL expression stays well-defined — revenue ordering becomes arbitrary
    in that case, which is the desired behaviour (we still prefer exact
    NACE matches).
    """
    if not target_nace:
        return []
    rev_arg = float(target_revenue) if target_revenue and target_revenue > 0 else 1.0
    try:
        rows = fetch_all(
            """
            SELECT ci.enterprise_number,
                   CASE
                     WHEN ci.nace_code = %s THEN 1.0
                     WHEN LEFT(ci.nace_code, 3) = LEFT(%s, 3) THEN 0.7
                     WHEN LEFT(ci.nace_code, 2) = LEFT(%s, 2) THEN 0.4
                     ELSE 0.0
                   END AS nace_score
            FROM company_info ci
            JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number != %s
              AND (ci.nace_code = %s OR LEFT(ci.nace_code, 2) = LEFT(%s, 2))
              AND fl.revenue IS NOT NULL
            ORDER BY (CASE WHEN ci.nace_code = %s THEN 0 ELSE 1 END),
                     ABS(LN(GREATEST(fl.revenue, 1)) - LN(GREATEST(%s, 1))) ASC
            LIMIT %s
            """,
            (
                target_nace, target_nace, target_nace,
                target_cbe,
                target_nace, target_nace,
                target_nace,
                rev_arg,
                LEG_B_LIMIT,
            ),
        )
    except Exception:
        logger.exception("retrieve_by_nace failed for %s", target_cbe)
        return []
    out = []
    for r in rows:
        score = float(r.get("nace_score") or 0.0)
        out.append({
            "enterprise_number": r["enterprise_number"],
            "nace_score": max(0.0, min(1.0, score)),
            "_source": "nace",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Leg C — size-band fallback
# ──────────────────────────────────────────────────────────────────────────

def retrieve_by_size_band(target_cbe: str, target_revenue: float | None) -> list[dict]:
    """Fetch active companies with revenue in a 0.3×–3× band around the target.

    Returns [] when the target has no revenue, since a size band around
    ``None`` is meaningless.
    """
    if not target_revenue or target_revenue <= 0:
        return []
    rev_min = float(target_revenue) * 0.3
    rev_max = float(target_revenue) * 3.0
    try:
        rows = fetch_all(
            """
            SELECT ci.enterprise_number
            FROM company_info ci
            JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number != %s
              AND fl.revenue BETWEEN %s AND %s
            ORDER BY ABS(fl.revenue - %s) ASC
            LIMIT %s
            """,
            (target_cbe, rev_min, rev_max, float(target_revenue), LEG_C_LIMIT),
        )
    except Exception:
        logger.exception("retrieve_by_size_band failed for %s", target_cbe)
        return []
    return [
        {
            "enterprise_number": r["enterprise_number"],
            "size_score": 0.3,
            "_source": "size_band",
        }
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────────────
# Blending and scoring
# ──────────────────────────────────────────────────────────────────────────

def _compute_nace_score(cand_nace: str | None, target_nace: str | None) -> float:
    """Replicate leg B's CASE expression in Python for off-leg candidates."""
    if not cand_nace or not target_nace:
        return 0.0
    if cand_nace == target_nace:
        return 1.0
    if cand_nace[:3] == target_nace[:3]:
        return 0.7
    if cand_nace[:2] == target_nace[:2]:
        return 0.4
    return 0.0


def _compute_revenue_ratio_score(cand_rev: float | None, target_rev: float | None) -> float:
    """exp(-|ln(cand / target)|) clipped to [0, 1]. 0 when either is missing/≤0."""
    if not cand_rev or cand_rev <= 0 or not target_rev or target_rev <= 0:
        return 0.0
    ratio = float(cand_rev) / float(target_rev)
    if ratio <= 0:
        return 0.0
    try:
        score = math.exp(-abs(math.log(ratio)))
    except (ValueError, OverflowError):
        return 0.0
    return max(0.0, min(1.0, score))


def _compute_geo_score(
    cand_city: str | None,
    cand_zip: str | None,
    target_city: str | None,
    target_zip: str | None,
) -> tuple[float, str]:
    """Return (score, label) where label is one of same_city/same_province/different."""
    cand_city_n = (cand_city or "").strip().lower()
    target_city_n = (target_city or "").strip().lower()
    if cand_city_n and target_city_n and cand_city_n == target_city_n:
        return 1.0, "same_city"
    cand_prefix = (cand_zip or "")[:2]
    target_prefix = (target_zip or "")[:2]
    if cand_prefix and target_prefix and cand_prefix == target_prefix:
        return 0.5, "same_province"
    return 0.0, "different"


def _derive_provenance(emb: float, nace: float, source_tags: set[str]) -> str:
    if emb > 0.5 and nace >= 0.7:
        return "embedding+nace"
    if emb > 0.5 and nace < 0.7:
        return "embedding_only"
    if emb <= 0.5 and nace >= 0.4:
        return "nace_only"
    if "size_band" in source_tags and nace < 0.4 and emb <= 0.5:
        return "fallback_size_band"
    return "fallback_size_band"


def _nace_match_label(cand_nace: str | None, target_nace: str | None) -> str:
    if not cand_nace or not target_nace:
        return "none"
    if cand_nace == target_nace:
        return "exact"
    if cand_nace[:3] == target_nace[:3]:
        return "class"
    if cand_nace[:2] == target_nace[:2]:
        return "group"
    return "none"


def _hydrate_candidates(cbes: list[str]) -> dict[str, dict]:
    """Batch-load info+financials for all merged candidates.

    Returned as {cbe: row_dict}. Rows that don't resolve are simply absent
    from the map, which downstream code tolerates.
    """
    if not cbes:
        return {}
    placeholders = ",".join(["%s"] * len(cbes))
    rows = fetch_all(
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
               ci.city, ci.zipcode,
               ci.nace_code,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
               fl.ebit, fl.net_profit, fl.equity, fl.total_assets,
               fl.personnel_costs,
               COALESCE(nl.description, ci.nace_code) AS nace_desc,
               ce.ai_insights
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
        WHERE ci.enterprise_number IN ({placeholders})
        """,
        tuple(cbes),
    )
    return {r["enterprise_number"]: dict(r) for r in rows}


def blend_candidates(
    legs: dict[str, list[dict]],
    focus: str,
    target: dict,
) -> list[dict]:
    """Merge legs, score, tag provenance, drop low scores, return top 25.

    ``legs`` keys: ``embedding``, ``nace``, ``size_band``.
    ``target`` must at minimum provide nace_code, revenue, city, zipcode.

    The returned list has length ≤ LLM_INPUT_SET_SIZE and is sorted by
    match_score descending. Each item has all fields needed to render both
    the LLM prompt and the final API response.
    """
    weights = FOCUS_WEIGHTS.get(focus, FOCUS_WEIGHTS["activity"])

    # Merge by enterprise_number, remembering which legs surfaced each CBE.
    merged: dict[str, dict] = {}
    source_tags: dict[str, set[str]] = {}
    for row in legs.get("embedding", []):
        cbe = row["enterprise_number"]
        merged.setdefault(cbe, {})["embedding_similarity"] = row.get("embedding_similarity", 0.0)
        source_tags.setdefault(cbe, set()).add("embedding")
    for row in legs.get("nace", []):
        cbe = row["enterprise_number"]
        merged.setdefault(cbe, {})["nace_score"] = row.get("nace_score", 0.0)
        source_tags.setdefault(cbe, set()).add("nace")
    for row in legs.get("size_band", []):
        cbe = row["enterprise_number"]
        merged.setdefault(cbe, {})
        source_tags.setdefault(cbe, set()).add("size_band")

    if not merged:
        return []

    hydrated = _hydrate_candidates(list(merged.keys()))

    target_nace = target.get("nace_code")
    target_rev = _as_number(target.get("revenue"))
    target_city = target.get("city")
    target_zip = target.get("zipcode")

    scored: list[dict] = []
    for cbe, sig in merged.items():
        row = hydrated.get(cbe)
        if not row:
            continue

        emb = float(sig.get("embedding_similarity") or 0.0)
        # Leg B only returns candidates that match on 2-digit NACE or better;
        # for embedding-only candidates we still want to credit a NACE match
        # that happens to line up, so compute on the fly.
        nace_from_leg = sig.get("nace_score")
        nace = float(nace_from_leg) if nace_from_leg is not None else _compute_nace_score(
            row.get("nace_code"), target_nace
        )
        cand_rev = _as_number(row.get("revenue"))
        rev_score = _compute_revenue_ratio_score(cand_rev, target_rev)
        geo_score, geo_label = _compute_geo_score(
            row.get("city"), row.get("zipcode"), target_city, target_zip
        )

        blended = (
            weights["emb"] * emb
            + weights["nace"] * nace
            + weights["rev"] * rev_score
            + weights["geo"] * geo_score
        )
        match_score = int(round(100 * blended))
        if match_score < MIN_SCORE_FLOOR:
            continue

        revenue_ratio = None
        if cand_rev and target_rev:
            revenue_ratio = round(cand_rev / target_rev, 3)

        scored.append({
            "enterprise_number": cbe,
            "row": row,
            "match_score": match_score,
            "embedding_similarity": round(emb, 4) if emb else 0.0,
            "nace_score": round(nace, 4),
            "revenue_ratio_score": round(rev_score, 4),
            "geo_score": round(geo_score, 4),
            "geo_label": geo_label,
            "nace_match_label": _nace_match_label(row.get("nace_code"), target_nace),
            "revenue_ratio": revenue_ratio,
            "provenance": _derive_provenance(emb, nace, source_tags[cbe]),
            "source_tags": sorted(source_tags[cbe]),
        })

    scored.sort(key=lambda c: c["match_score"], reverse=True)
    return scored[:LLM_INPUT_SET_SIZE]


def leg_needs_fallback(legs: dict[str, list[dict]]) -> bool:
    """Should leg C fire? True iff A ∪ B has fewer than FALLBACK_TRIGGER unique CBEs."""
    seen: set[str] = set()
    for row in legs.get("embedding", []):
        seen.add(row["enterprise_number"])
    for row in legs.get("nace", []):
        seen.add(row["enterprise_number"])
    return len(seen) < FALLBACK_TRIGGER


def _as_number(value):
    """Duplicate of similar_cache._as_number; kept local to avoid a circular import."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
