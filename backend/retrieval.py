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
import re
import time
from typing import Any, Iterable

from db import fetch_all, fetch_one, get_connection, normalize_name, put_connection
from middleware.timing import record_db_timing
from similarity_profile import (
    build_similarity_profile,
    compute_activity_overlap_score,
    describe_activity_overlap,
    has_similarity_profile,
)
from utils import clean_cbe

logger = logging.getLogger(__name__)


FOCUS_WEIGHTS = {
    "activity":  {"emb": 0.32, "activity": 0.45, "nace": 0.10, "rev": 0.08, "geo": 0.05},
    "size":      {"emb": 0.18, "activity": 0.12, "nace": 0.05, "rev": 0.60, "geo": 0.05},
    "geography": {"emb": 0.18, "activity": 0.15, "nace": 0.05, "rev": 0.12, "geo": 0.50},
}


MIN_SCORE_FLOOR = 15        # candidates below this 0–100 score are dropped (§3.4)
LLM_INPUT_SET_SIZE = 150    # trim to this many before sending to the re-ranker
FALLBACK_TRIGGER = 30       # leg C runs only if A+B together yield fewer than this

# Per-leg fetch caps. Larger than LLM_INPUT_SET_SIZE because the blend can
# reorder candidates, and because dedup across legs shrinks the merged pool.
LEG_A_LIMIT = 80
LEG_B_LIMIT = 300           # bumped from 80 (2026-05-04) — operator wants
                            # exhaustive list returned to the UI; LLM still
                            # only ranks the top SHORTLIST_SIZE slot, the
                            # rest are score-sorted with template reasons.
LEG_C_LIMIT = 60
HNSW_EF_SEARCH = 100

GROUP_CONTROL_THRESHOLD_PCT = 50.0
HOLDING_VEHICLE_NACE_CODES = {
    "64190",
    "64200",
    "64201",
    "64202",
    "64300",
    "64910",
    "64921",
    "64922",
    "64991",
    "64992",
    "64999",
    "70100",
}
HOLDING_VEHICLE_NACE_PREFIXES = ("642", "643")
HOLDING_VEHICLE_MIN_SUBSIDIARIES = 3
HOLDING_VEHICLE_MAX_REVENUE = 2_000_000.0
HOLDING_WEAK_ACTIVITY_FLOOR = 0.0
HOLDING_NACE_ONLY_MIN_ACTIVITY_OVERLAP = 0.0
HOLDING_MIN_SCORE_FLOOR = 8
NACE_LOW_ACTIVITY_MIN_EXACT_REVENUE_SCORE = 0.10
NACE_LOW_ACTIVITY_MIN_RELATED_REVENUE_SCORE = 0.90
NACE_LOW_ACTIVITY_SCORE_FLOOR = 10
ACTIVITY_DETAIL_BONUS = {
    "activity": 0.04,
    "size": 0.02,
    "geography": 0.02,
}
WEAK_ACTIVITY_FLOOR = 0.08
NACE_PROFILE_DISCOUNT_FLOOR = 0.15
NACE_ONLY_MIN_ACTIVITY_OVERLAP = 0.12
ACTIVITY_FOCUS_MIN_ACTIVITY_OVERLAP = 0.10
ACTIVITY_FOCUS_MIN_EMBEDDING = 0.60


# ──────────────────────────────────────────────────────────────────────────
# Leg A — pgvector nearest neighbours
# ──────────────────────────────────────────────────────────────────────────

def _fetch_embedding_neighbors(target_cbe: str) -> list[dict]:
    """Run the pgvector KNN lookup in one transaction so SET LOCAL applies."""
    conn = get_connection()
    cur = None
    try:
        cur = conn.cursor()
        t0 = time.perf_counter()
        cur.execute(
            "SELECT embedding::text FROM company_embedding WHERE enterprise_number = %s",
            (target_cbe,),
        )
        target_row = cur.fetchone()
        if not target_row or not target_row[0]:
            record_db_timing((time.perf_counter() - t0) * 1000.0)
            conn.commit()
            return []

        target_embedding = target_row[0]
        cur.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(HNSW_EF_SEARCH),))
        cur.execute(
            """
            SELECT ce.enterprise_number,
                   1 - (ce.embedding <=> %s::vector) AS embedding_similarity
            FROM company_embedding ce
            WHERE ce.enterprise_number != %s
            ORDER BY ce.embedding <=> %s::vector
            LIMIT %s
            """,
            (target_embedding, target_cbe, target_embedding, LEG_A_LIMIT),
        )
        rows = cur.fetchall()
        record_db_timing((time.perf_counter() - t0) * 1000.0)
        conn.commit()
        return [
            {
                "enterprise_number": row[0],
                "embedding_similarity": row[1],
            }
            for row in rows
        ]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        put_connection(conn)


def retrieve_by_embedding(target_cbe: str, has_embedding: bool) -> list[dict]:
    """Fetch up to LEG_A_LIMIT candidates by cosine similarity on company_embedding.

    Returns an empty list if the target has no embedding or if pgvector is
    not enabled (caught by the outer try/except in the endpoint).
    """
    if not has_embedding:
        return []
    try:
        rows = _fetch_embedding_neighbors(target_cbe)
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

def retrieve_by_nace(
    target_cbe: str,
    target_nace: str,
    target_revenue: float | None,
    target_embedding: str | None = None,
) -> list[dict]:
    """Fetch NACE peers; rank same-code first, then by best-peer signal.

    Uses a LEFT JOIN to financial_latest so peers without an NBB filing
    (or with a filing that has no revenue) remain eligible. Many sectors
    file abridged accounts that omit revenue — real estate agencies,
    accountants, doctors, lawyers — and a hard inner-join silently
    excluded ~99% of NACE peers in those segments, so find-similar
    returned almost nothing for those targets.

    When the target has an embedding, the secondary ordering is by
    cosine similarity to the target embedding (peers with embeddings
    sort first by distance ascending; peers without embeddings sort
    last, then by revenue similarity, then enterprise_number for
    stability). This avoids the previous "oldest CBE wins" tiebreaker
    that surfaced 1970s shell companies ahead of well-described modern
    peers when the target had no revenue.

    Falls back to revenue-only ordering when the target has no
    embedding. Revenue placeholder of 1.0 keeps the LN expression
    well-defined; with NULL revenue rows GREATEST(NULL, 1) → 1, so
    revenue-less peers sort together with distance 0 when target also
    lacks revenue and to the back when target has revenue.
    """
    if not target_nace:
        return []
    rev_arg = float(target_revenue) if target_revenue and target_revenue > 0 else 1.0
    try:
        if target_embedding:
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
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                LEFT JOIN company_embedding ce_emb ON ce_emb.enterprise_number = ci.enterprise_number
                WHERE ci.enterprise_number != %s
                  AND (ci.nace_code = %s OR LEFT(ci.nace_code, 2) = LEFT(%s, 2))
                ORDER BY (CASE WHEN ci.nace_code = %s THEN 0 ELSE 1 END),
                         (CASE WHEN ce_emb.embedding IS NULL THEN 1 ELSE 0 END),
                         (ce_emb.embedding <=> %s::vector) ASC NULLS LAST,
                         ABS(LN(GREATEST(fl.revenue, 1)) - LN(GREATEST(%s, 1))) ASC,
                         ci.enterprise_number ASC
                LIMIT %s
                """,
                (
                    target_nace, target_nace, target_nace,
                    target_cbe,
                    target_nace, target_nace,
                    target_nace,
                    target_embedding,
                    rev_arg,
                    LEG_B_LIMIT,
                ),
            )
        else:
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
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.enterprise_number != %s
                  AND (ci.nace_code = %s OR LEFT(ci.nace_code, 2) = LEFT(%s, 2))
                ORDER BY (CASE WHEN ci.nace_code = %s THEN 0 ELSE 1 END),
                         ABS(LN(GREATEST(fl.revenue, 1)) - LN(GREATEST(%s, 1))) ASC,
                         ci.enterprise_number ASC
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


def _normalize_entity_name(name: str | None) -> str:
    cleaned = normalize_name(name or "")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_identifier_as_cbe(identifier: str | None) -> str:
    digits = re.sub(r"\D+", "", str(identifier or ""))
    if len(digits) not in (9, 10):
        return ""
    return clean_cbe(digits)


def _normalize_nace_code(nace_code: str | None) -> str:
    return re.sub(r"\D+", "", str(nace_code or ""))


def _is_holding_vehicle_target(target: dict, target_group: dict | None) -> bool:
    nace = _normalize_nace_code(target.get("nace_code"))
    if nace in HOLDING_VEHICLE_NACE_CODES or nace[:3] in HOLDING_VEHICLE_NACE_PREFIXES:
        return True

    group = target_group or {}
    subsidiary_count = len(group.get("subsidiary_ids", set()))
    revenue = _as_number(target.get("revenue"))
    return (
        subsidiary_count >= HOLDING_VEHICLE_MIN_SUBSIDIARIES
        and (revenue is None or revenue <= HOLDING_VEHICLE_MAX_REVENUE)
    )


def _is_nace_revenue_backed_candidate(
    source_set: set[str],
    nace: float,
    rev_score: float,
) -> bool:
    if source_set != {"nace"}:
        return False
    if nace >= 1.0 and rev_score >= NACE_LOW_ACTIVITY_MIN_EXACT_REVENUE_SCORE:
        return True
    return nace >= 0.4 and rev_score >= NACE_LOW_ACTIVITY_MIN_RELATED_REVENUE_SCORE


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
               ce.bulk_summary,
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


def _build_group_profiles(rows_by_cbe: dict[str, dict]) -> dict[str, dict]:
    """Load direct parent/subsidiary signals for same-group exclusion."""
    if not rows_by_cbe:
        return {}

    profiles = {
        cbe: {
            "own_name": _normalize_entity_name(row.get("name")),
            "controlling_shareholder_ids": set(),
            "controlling_shareholder_names": set(),
            "entity_shareholder_ids": set(),
            "entity_shareholder_names": set(),
            "subsidiary_ids": set(),
            "subsidiary_names": set(),
        }
        for cbe, row in rows_by_cbe.items()
    }

    cbes = list(rows_by_cbe.keys())
    placeholders = ",".join(["%s"] * len(cbes))

    try:
        # DELIBERATELY uses the base table, not the _current view. Phase 2
        # diagnosis refuted _current reads as the latency root cause; see
        # docs/find-similar-diagnosis-2026-05-03.md.
        shareholder_rows = fetch_all(
            f"""
            SELECT enterprise_number, identifier, name, ownership_pct, shareholder_type
            FROM shareholder
            WHERE enterprise_number IN ({placeholders})
              AND COALESCE(shareholder_type, 'entity') <> 'individual'
            """,
            tuple(cbes),
        )
    except Exception:
        logger.exception("Failed to hydrate shareholder group links")
        shareholder_rows = []

    for row in shareholder_rows:
        profile = profiles.get(row["enterprise_number"])
        if not profile:
            continue
        pct = _as_number(row.get("ownership_pct"))
        identifier = _clean_identifier_as_cbe(row.get("identifier"))
        name = _normalize_entity_name(row.get("name"))
        if identifier:
            profile["entity_shareholder_ids"].add(identifier)
        if name:
            profile["entity_shareholder_names"].add(name)
        if pct is None or pct < GROUP_CONTROL_THRESHOLD_PCT:
            continue
        if identifier:
            profile["controlling_shareholder_ids"].add(identifier)
        if name:
            profile["controlling_shareholder_names"].add(name)

    try:
        # DELIBERATELY uses the base table, not the _current view. Phase 2
        # diagnosis refuted _current reads as the latency root cause; see
        # docs/find-similar-diagnosis-2026-05-03.md.
        subsidiary_rows = fetch_all(
            f"""
            SELECT enterprise_number, identifier, name, ownership_pct
            FROM participating_interest
            WHERE enterprise_number IN ({placeholders})
            """,
            tuple(cbes),
        )
    except Exception:
        logger.exception("Failed to hydrate subsidiary group links")
        subsidiary_rows = []

    for row in subsidiary_rows:
        profile = profiles.get(row["enterprise_number"])
        if not profile:
            continue
        pct = _as_number(row.get("ownership_pct"))
        if pct is None or pct < GROUP_CONTROL_THRESHOLD_PCT:
            continue
        identifier = _clean_identifier_as_cbe(row.get("identifier"))
        name = _normalize_entity_name(row.get("name"))
        if identifier:
            profile["subsidiary_ids"].add(identifier)
        if name:
            profile["subsidiary_names"].add(name)

    return profiles


def _is_same_group(
    target_cbe: str,
    target_group: dict | None,
    candidate_cbe: str,
    candidate_group: dict | None,
) -> bool:
    """Return True for direct parent/subsidiary/sister-company links."""
    target = target_group or {}
    candidate = candidate_group or {}

    if (
        candidate_cbe in target.get("subsidiary_ids", set())
        or target_cbe in candidate.get("subsidiary_ids", set())
        or candidate_cbe in target.get("controlling_shareholder_ids", set())
        or target_cbe in candidate.get("controlling_shareholder_ids", set())
    ):
        return True

    target_name = target.get("own_name") or ""
    candidate_name = candidate.get("own_name") or ""
    if candidate_name and (
        candidate_name in target.get("subsidiary_names", set())
        or candidate_name in target.get("controlling_shareholder_names", set())
    ):
        return True
    if target_name and (
        target_name in candidate.get("subsidiary_names", set())
        or target_name in candidate.get("controlling_shareholder_names", set())
    ):
        return True

    if target.get("controlling_shareholder_ids", set()) & candidate.get(
        "controlling_shareholder_ids", set(),
    ):
        return True
    if target.get("controlling_shareholder_names", set()) & candidate.get(
        "controlling_shareholder_names", set(),
    ):
        return True
    if target.get("entity_shareholder_ids", set()) & candidate.get(
        "entity_shareholder_ids", set(),
    ):
        return True
    if target.get("entity_shareholder_names", set()) & candidate.get(
        "entity_shareholder_names", set(),
    ):
        return True
    return False


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

    target_cbe = str(target.get("enterprise_number") or "")
    target_nace = target.get("nace_code")
    target_rev = _as_number(target.get("revenue"))
    target_city = target.get("city")
    target_zip = target.get("zipcode")
    target_profile = build_similarity_profile(
        target.get("bulk_summary"),
        target.get("ai_insights"),
    )
    target_has_profile = has_similarity_profile(target_profile)
    group_profiles = _build_group_profiles(
        {
            target_cbe: target,
            **hydrated,
        },
    )
    target_group = group_profiles.get(target_cbe, {})
    is_holding_vehicle_target = _is_holding_vehicle_target(target, target_group)
    weak_activity_floor = (
        HOLDING_WEAK_ACTIVITY_FLOOR if is_holding_vehicle_target else WEAK_ACTIVITY_FLOOR
    )
    nace_only_min_activity_overlap = (
        HOLDING_NACE_ONLY_MIN_ACTIVITY_OVERLAP
        if is_holding_vehicle_target
        else NACE_ONLY_MIN_ACTIVITY_OVERLAP
    )
    score_floor = HOLDING_MIN_SCORE_FLOOR if is_holding_vehicle_target else MIN_SCORE_FLOOR

    scored: list[dict] = []
    for cbe, sig in merged.items():
        row = hydrated.get(cbe)
        if not row:
            continue
        if _is_same_group(target_cbe, target_group, cbe, group_profiles.get(cbe)):
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
        candidate_profile = build_similarity_profile(
            row.get("bulk_summary"),
            row.get("ai_insights"),
        )
        candidate_has_profile = has_similarity_profile(candidate_profile)
        has_profile_signal = target_has_profile and candidate_has_profile
        activity_overlap = compute_activity_overlap_score(target_profile, candidate_profile)
        activity_anchor = describe_activity_overlap(
            target_profile,
            candidate_profile,
            candidate_nace_desc=row.get("nace_desc"),
        )

        source_set = source_tags[cbe]
        is_nace_revenue_backed = _is_nace_revenue_backed_candidate(
            source_set,
            nace,
            rev_score,
        )
        if (
            "size_band" in source_set
            and nace < 0.4
            and emb < 0.55
            and activity_overlap < weak_activity_floor
        ):
            continue
        if (
            source_set == {"embedding"}
            and nace < 0.4
            and emb < 0.60
            and activity_overlap < weak_activity_floor
        ):
            continue
        if (
            has_profile_signal
            and source_set == {"nace"}
            and activity_overlap < nace_only_min_activity_overlap
            and not is_nace_revenue_backed
        ):
            continue
        nace_effective = nace
        if (
            has_profile_signal
            and activity_overlap < ACTIVITY_FOCUS_MIN_ACTIVITY_OVERLAP
            and not (is_holding_vehicle_target and nace >= 0.7)
            and not is_nace_revenue_backed
        ):
            nace_effective = min(nace_effective, NACE_PROFILE_DISCOUNT_FLOOR)
        if (
            has_profile_signal
            and focus == "activity"
            and activity_overlap < ACTIVITY_FOCUS_MIN_ACTIVITY_OVERLAP
            and emb < ACTIVITY_FOCUS_MIN_EMBEDDING
            and not (is_holding_vehicle_target and nace >= 0.7)
            and not is_nace_revenue_backed
        ):
            continue

        blended = (
            weights["emb"] * emb
            + weights["activity"] * activity_overlap
            + weights["nace"] * nace_effective
            + weights["rev"] * rev_score
            + weights["geo"] * geo_score
        )
        blended = min(1.0, blended + ACTIVITY_DETAIL_BONUS.get(focus, 0.0) * activity_overlap)
        match_score = int(round(100 * blended))
        candidate_score_floor = (
            min(score_floor, NACE_LOW_ACTIVITY_SCORE_FLOOR)
            if is_nace_revenue_backed
            else score_floor
        )
        if match_score < candidate_score_floor:
            continue

        revenue_ratio = None
        if cand_rev and target_rev:
            revenue_ratio = round(cand_rev / target_rev, 3)

        scored.append({
            "enterprise_number": cbe,
            "row": row,
            "match_score": match_score,
            "embedding_similarity": round(emb, 4) if emb else 0.0,
            "nace_score": round(nace_effective, 4),
            "revenue_ratio_score": round(rev_score, 4),
            "geo_score": round(geo_score, 4),
            "activity_overlap_score": round(activity_overlap, 4),
            "activity_anchor": activity_anchor,
            "geo_label": geo_label,
            "nace_match_label": _nace_match_label(row.get("nace_code"), target_nace),
            "revenue_ratio": revenue_ratio,
            "provenance": _derive_provenance(emb, nace, source_set),
            "source_tags": sorted(source_set),
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
