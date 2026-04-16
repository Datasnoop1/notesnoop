"""Cache helpers for the AI-powered /similar/ai endpoint.

Responsibilities:
  - Compute a stable content hash over everything that should invalidate a
    cached ranking (target financials, target insights, the retrieved
    candidate set, the focus parameter, the prompt version, and the model).
  - Lazily ensure the ai_similar_cache table and its auxiliary columns and
    index exist. This mirrors the inline-migration pattern already used
    elsewhere in backend/ (see embeddings.ensure_embedding_table).

The primary key stays ``enterprise_number`` for backwards compatibility —
the content hash is a lookup predicate, not a key. One row per CBE is
kept; a new focus or hash simply overwrites it.
"""

from __future__ import annotations

import hashlib
import json
import logging

from db import get_connection, put_connection

logger = logging.getLogger(__name__)

_schema_ensured = False


def ensure_similar_cache_schema() -> None:
    """Create / upgrade the ai_similar_cache table. Idempotent.

    Safe to call on every request — the guard flag makes subsequent calls
    within the same process no-ops. Schema changes are additive and use
    IF NOT EXISTS so this can run ahead of an out-of-band migration too.
    """
    global _schema_ensured
    if _schema_ensured:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_similar_cache (
                enterprise_number VARCHAR(10) PRIMARY KEY,
                ranked_cbes TEXT,
                reasons TEXT,
                generated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE ai_similar_cache ADD COLUMN IF NOT EXISTS content_hash TEXT")
        cur.execute(
            "ALTER TABLE ai_similar_cache "
            "ADD COLUMN IF NOT EXISTS focus TEXT NOT NULL DEFAULT 'activity'"
        )
        cur.execute("ALTER TABLE ai_similar_cache ADD COLUMN IF NOT EXISTS match_scores TEXT")
        cur.execute("ALTER TABLE ai_similar_cache ADD COLUMN IF NOT EXISTS provenance TEXT")
        cur.execute("ALTER TABLE ai_similar_cache ADD COLUMN IF NOT EXISTS signals TEXT")
        cur.execute("ALTER TABLE ai_similar_cache ADD COLUMN IF NOT EXISTS model_used TEXT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ai_similar_cache_hash_idx "
            "ON ai_similar_cache (enterprise_number, focus, content_hash)"
        )
        conn.commit()
        cur.close()
        _schema_ensured = True
    except Exception:
        conn.rollback()
        logger.exception("Failed to ensure ai_similar_cache schema (will retry next call)")
    finally:
        put_connection(conn)


def compute_content_hash(
    target_row: dict,
    target_insights: str | None,
    candidate_cbes_sorted: list[str],
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
        "target_insights_sha": hashlib.sha256(
            (target_insights or "").encode("utf-8")
        ).hexdigest(),
        "candidates": candidate_cbes_sorted,
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
