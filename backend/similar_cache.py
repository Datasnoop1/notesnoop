"""Cache helpers for the AI-powered /similar/ai endpoint.

Responsibilities:
  - Compute a stable content hash over everything that should invalidate a
    cached ranking (target financials, target insights, the retrieved
    candidate set, the focus parameter, the prompt version, and the model).
  - Provide a compatibility schema hook for callers while the actual
    ai_similar_cache schema is managed by tracked migrations.

The primary key stays ``enterprise_number`` for backwards compatibility —
the content hash is a lookup predicate, not a key. One row per CBE is
kept; a new focus or hash simply overwrites it.
"""

from __future__ import annotations

import hashlib
import json
_schema_ensured = False


def ensure_similar_cache_schema() -> None:
    """Compatibility shim for the old ai_similar_cache runtime DDL.

    Runtime DDL moved to tracked migrations in Week-1b. Safe to call on every
    request; the guard flag makes subsequent calls within the same process
    no-ops.
    """
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True


def compute_content_hash(
    target_row: dict,
    target_profile_text: str | None,
    candidate_cbes_sorted: list[str],
    candidate_profile_texts_sorted: list[str] | None,
    focus: str,
    prompt_version: str,
    model: str,
) -> str:
    """Stable SHA-256 hash over all inputs that affect a ranking.

    Changing any target financial, target insights, the retrieved candidate
    set, the focus weighting, the prompt version, or the model must flip
    the hash. The candidate list is sorted by the caller so retrieval-order
    noise does not trigger false invalidations.
    """
    payload = {
        "target_fy": target_row.get("fiscal_year"),
        "target_rev": _as_number(target_row.get("revenue")),
        "target_ebitda": _as_number(target_row.get("ebitda")),
        "target_fte": _as_number(target_row.get("fte_total")),
        "target_nace": target_row.get("nace_code"),
        "target_profile_sha": hashlib.sha256(
            (target_profile_text or "").encode("utf-8")
        ).hexdigest(),
        "candidates": candidate_cbes_sorted,
        "candidate_profile_shas": [
            hashlib.sha256((text or "").encode("utf-8")).hexdigest()
            for text in (candidate_profile_texts_sorted or [])
        ],
        "focus": focus,
        "prompt_version": prompt_version,
        "model": model,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _as_number(value):
    """Normalise numeric inputs so Decimal/int/float produce the same hash.

    Without this, the same revenue coming back from psycopg as Decimal vs.
    int would produce different JSON and therefore different hashes,
    causing spurious cache misses.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
