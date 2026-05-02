"""Embedding utilities — generate and store vector embeddings for semantic search.

Provider-selectable backend. Stores vectors in PostgreSQL via pgvector.

Provider selection (env-driven):
  - EMBEDDING_PROVIDER=nvidia → NVIDIA NIM (build.nvidia.com).
    Default model nvidia/nv-embedqa-e5-v5 at 1024 dims. Asymmetric — pass
    input_type='query' for search queries, 'passage' for corpus documents.
  - EMBEDDING_PROVIDER=openrouter → OpenRouter, default
    openai/text-embedding-3-small at 256 dims (legacy path).

Auto-default: 'nvidia' when NVIDIA_API_KEY is set, else 'openrouter'.

HNSW index for fast approximate nearest-neighbour at scale. No source_text
stored — derivable from company_enrichment.bulk_summary / ai_insights.
"""

import hashlib
import json
import logging
import os
from typing import Literal, Optional

import httpx
from db import execute, fetch_one, fetch_all

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")


def _resolve_provider() -> str:
    p = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    if p in ("nvidia", "openrouter"):
        return p
    return "nvidia" if NVIDIA_API_KEY else "openrouter"


EMBEDDING_PROVIDER = _resolve_provider()

_PROVIDER_DEFAULTS = {
    "nvidia": ("nvidia/nv-embedqa-e5-v5", 1024),
    "openrouter": ("openai/text-embedding-3-small", 256),
}
_DEF_MODEL, _DEF_DIMS = _PROVIDER_DEFAULTS[EMBEDDING_PROVIDER]
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", _DEF_MODEL)
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", str(_DEF_DIMS)))

# Query-embedding cache TTL. 30 days matches the plan; the daily
# admin-page view plus recurring screener searches mean most popular
# queries get served from cache.
QUERY_CACHE_TTL_DAYS = int(os.getenv("QUERY_CACHE_TTL_DAYS", "30"))

_table_ensured = False


def ensure_embedding_table():
    """Compatibility shim for the old company_embedding startup DDL.

    Runtime DDL moved to tracked migrations in Week-1b.
    """
    global _table_ensured
    if _table_ensured:
        return
    _table_ensured = True


async def generate_embedding(
    text: str,
    *,
    input_type: Literal["query", "passage"] = "passage",
) -> list[float] | None:
    """Generate an embedding for a text string via the configured provider.

    `input_type` is only meaningful for asymmetric models like NVIDIA's
    nv-embedqa-e5-v5: pass 'query' when embedding a search query, 'passage'
    for corpus documents. OpenRouter's symmetric models ignore it.
    """
    if not text:
        return None
    if EMBEDDING_PROVIDER == "nvidia":
        return await _nvidia_embed_one(text, input_type)
    return await _openrouter_embed_one(text)


async def _nvidia_embed_one(text: str, input_type: str) -> list[float] | None:
    if not NVIDIA_API_KEY:
        logger.warning("NVIDIA_API_KEY not set; cannot embed via NVIDIA NIM")
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NVIDIA_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {NVIDIA_API_KEY}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": text[:8000],
                    "input_type": input_type,
                    "truncate": "END",
                    "encoding_format": "float",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("NVIDIA embedding API returned %d: %s",
                               resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        logger.error("NVIDIA embedding generation failed: %s", e)
        return None


async def _openrouter_embed_one(text: str) -> list[float] | None:
    if not OPENROUTER_API_KEY:
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": text[:8000],
                    "dimensions": EMBEDDING_DIMS,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("OpenRouter embedding returned %d: %s",
                               resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        logger.error("OpenRouter embedding generation failed: %s", e)
        return None


def build_embedding_text(insights: dict) -> str:
    """Build the text to embed from AI insights JSON.

    Combines business_description + products + customers + market_position
    into a single searchable text block.
    """
    parts = []
    for field in ("business_description", "products", "customers", "market_position", "history", "group_context"):
        val = insights.get(field)
        if val:
            if isinstance(val, list):
                parts.append(", ".join(str(v) for v in val))
            else:
                parts.append(str(val))
    return " ".join(parts).strip()


async def embed_company(cbe: str, force: bool = False) -> bool:
    """Generate and store embedding for a single company.

    Returns True if embedding was generated, False if skipped/failed.
    """
    ensure_embedding_table()
    cbe = cbe.strip().replace(".", "").zfill(10)

    # Check if already embedded (skip unless force)
    if not force:
        existing = fetch_one(
            "SELECT 1 FROM company_embedding WHERE enterprise_number = %s", (cbe,)
        )
        if existing:
            return False

    # Get AI insights
    row = fetch_one(
        "SELECT ai_insights FROM company_enrichment WHERE enterprise_number = %s AND ai_insights IS NOT NULL",
        (cbe,),
    )
    if not row or not row.get("ai_insights"):
        return False

    # Parse insights
    try:
        insights = json.loads(row["ai_insights"]) if isinstance(row["ai_insights"], str) else row["ai_insights"]
    except Exception:
        return False

    # Build text and generate embedding
    text = build_embedding_text(insights)
    if not text or len(text) < 20:
        return False

    embedding = await generate_embedding(text)
    if not embedding:
        return False

    # Store
    try:
        execute(
            """INSERT INTO company_embedding (enterprise_number, embedding, model)
               VALUES (%s, %s, %s)
               ON CONFLICT (enterprise_number) DO UPDATE SET
                   embedding = EXCLUDED.embedding,
                   model = EXCLUDED.model,
                   generated_at = NOW()""",
            (cbe, str(embedding), EMBEDDING_MODEL),
        )
        return True
    except Exception as e:
        logger.error("Failed to store embedding for %s: %s", cbe, e)
        return False


async def find_similar_by_embedding(cbe: str, limit: int = 20) -> list[dict]:
    """Find companies with the most similar embeddings using cosine distance.

    Returns list of {enterprise_number, name, city, similarity} sorted by similarity.
    """
    ensure_embedding_table()
    cbe = cbe.strip().replace(".", "").zfill(10)

    # Use subquery to avoid serializing pgvector type through psycopg2
    rows = fetch_all("""
        SELECT ce.enterprise_number, ci.name, ci.city,
               1 - (ce.embedding <=> target.embedding) AS similarity
        FROM company_embedding ce
        CROSS JOIN (SELECT embedding FROM company_embedding WHERE enterprise_number = %s) target
        LEFT JOIN company_info ci ON ci.enterprise_number = ce.enterprise_number
        WHERE ce.enterprise_number != %s
        ORDER BY ce.embedding <=> target.embedding
        LIMIT %s
    """, (cbe, cbe, limit))

    return [dict(r) for r in rows]


async def batch_embed_all(limit: int = 500) -> dict:
    """Embed all companies that have AI insights but no embedding yet.

    Returns: {"embedded": int, "skipped": int, "errors": int}
    """
    ensure_embedding_table()

    rows = fetch_all("""
        SELECT ce.enterprise_number, ce.ai_insights
        FROM company_enrichment ce
        WHERE ce.ai_insights IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM company_embedding emb
              WHERE emb.enterprise_number = ce.enterprise_number
          )
        LIMIT %s
    """, (limit,))

    embedded = 0
    errors = 0

    for row in rows:
        try:
            cbe = row["enterprise_number"]
            insights = json.loads(row["ai_insights"]) if isinstance(row["ai_insights"], str) else row["ai_insights"]
            text = build_embedding_text(insights)
            if not text or len(text) < 20:
                continue

            embedding = await generate_embedding(text)
            if not embedding:
                errors += 1
                continue

            execute(
                """INSERT INTO company_embedding (enterprise_number, embedding, model)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (enterprise_number) DO UPDATE SET
                       embedding = EXCLUDED.embedding,
                       model = EXCLUDED.model, generated_at = NOW()""",
                (cbe, str(embedding), EMBEDDING_MODEL),
            )
            embedded += 1
            if embedded % 10 == 0:
                logger.info("Embedded %d/%d companies...", embedded, len(rows))
        except Exception as e:
            logger.error("Embedding failed for %s: %s", row["enterprise_number"], e)
            errors += 1

    logger.info("Batch embedding done: %d embedded, %d errors, %d total candidates", embedded, errors, len(rows))
    return {"embedded": embedded, "skipped": len(rows) - embedded - errors, "errors": errors}


# ── Bulk embedder used by the Phase 1 enrichment worker ──────────────


async def generate_embeddings_batch(
    texts: list[str],
    *,
    input_type: Literal["query", "passage"] = "passage",
) -> list[list[float] | None]:
    """Embed a batch of texts in a single provider call.

    Returns a list aligned with `texts` — entries are None when the API
    returned a malformed result or the input was empty.
    """
    if not texts:
        return []
    if EMBEDDING_PROVIDER == "nvidia":
        return await _nvidia_embed_batch(texts, input_type)
    return await _openrouter_embed_batch(texts)


async def _nvidia_embed_batch(texts: list[str], input_type: str) -> list[list[float] | None]:
    if not NVIDIA_API_KEY:
        return [None] * len(texts)
    cleaned: list[str] = [(t or "")[:8000] or "empty" for t in texts]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{NVIDIA_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {NVIDIA_API_KEY}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": cleaned,
                    "input_type": input_type,
                    "truncate": "END",
                    "encoding_format": "float",
                },
                timeout=60,
            )
            if resp.status_code != 200:
                logger.warning("NVIDIA batch embedding returned %d: %s",
                               resp.status_code, resp.text[:200])
                return [None] * len(texts)
            data = resp.json().get("data") or []
            out: list[list[float] | None] = [None] * len(texts)
            for item in data:
                i = item.get("index")
                emb = item.get("embedding")
                if isinstance(i, int) and 0 <= i < len(out) and isinstance(emb, list):
                    if not (texts[i] or "").strip():
                        continue
                    out[i] = emb
            return out
    except Exception as e:
        logger.error("NVIDIA batch embedding failed: %s", e)
        return [None] * len(texts)


async def _openrouter_embed_batch(texts: list[str]) -> list[list[float] | None]:
    if not OPENROUTER_API_KEY:
        return [None] * len(texts)
    cleaned: list[str] = [(t or "")[:8000] or "empty" for t in texts]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": cleaned,
                    "dimensions": EMBEDDING_DIMS,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                logger.warning("OpenRouter batch embedding returned %d: %s",
                               resp.status_code, resp.text[:200])
                return [None] * len(texts)
            data = resp.json().get("data") or []
            out: list[list[float] | None] = [None] * len(texts)
            for item in data:
                i = item.get("index")
                emb = item.get("embedding")
                if isinstance(i, int) and 0 <= i < len(out) and isinstance(emb, list):
                    if not (texts[i] or "").strip():
                        continue
                    out[i] = emb
            return out
    except Exception as e:
        logger.error("OpenRouter batch embedding failed: %s", e)
        return [None] * len(texts)


# ── Query-embedding cache (for /api/search/semantic) ─────────────────


_query_cache_ensured = False


def _ensure_query_embedding_cache() -> None:
    """Compatibility shim for the old query_embedding_cache startup DDL."""
    global _query_cache_ensured
    if _query_cache_ensured:
        return
    _query_cache_ensured = True


def _query_hash(q: str) -> str:
    return hashlib.sha256(q.strip().lower().encode("utf-8")).hexdigest()


async def embed_query(q: str) -> list[float] | None:
    """Return a cached embedding for a search query, generating on miss.

    Cache keyed by `sha256(lower(strip(q)))` with a 30-day TTL. Rows
    older than the TTL are treated as misses and overwritten. A miss
    costs one embedding API call (~$0.00002 per query on
    text-embedding-3-small @ 256 dims) — fine, but the cache means
    repeat queries are free. The /api/search/semantic router calls this
    on every request.
    """
    text = (q or "").strip()
    if not text:
        return None
    _ensure_query_embedding_cache()
    h = _query_hash(text)

    row = fetch_one(
        "SELECT embedding::text AS embedding_text, created_at "
        "FROM query_embedding_cache WHERE query_hash = %s",
        (h,),
    )
    if row:
        age_days = None
        try:
            from datetime import datetime, timezone
            created = row.get("created_at")
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created).days
        except Exception:
            age_days = None
        if age_days is None or age_days < QUERY_CACHE_TTL_DAYS:
            try:
                return _parse_pgvector(row["embedding_text"])
            except Exception:
                pass  # fall through to regenerate

    embedding = await generate_embedding(text, input_type="query")
    if not embedding:
        return None

    try:
        execute(
            """
            INSERT INTO query_embedding_cache
                   (query_hash, query_text, embedding, model)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (query_hash) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                created_at = NOW()
            """,
            (h, text, str(embedding), EMBEDDING_MODEL),
        )
    except Exception:
        logger.warning("Failed to persist query-cache row for '%s'", text[:80])

    return embedding


def _parse_pgvector(s: str) -> list[float]:
    """Parse pgvector text output '[1.0,2.0,...]' → list[float]."""
    s = (s or "").strip().strip("[]")
    if not s:
        return []
    return [float(x) for x in s.split(",")]


# ── Bulk embedding writer for the Phase 1 enrichment worker ────────


def store_company_embedding(cbe: str, embedding: list[float]) -> None:
    """Write a single company embedding. Same upsert shape as embed_company.

    Kept as a public helper so the bulk worker can re-use the embedder
    output directly instead of re-parsing `ai_insights` like
    `embed_company` does.
    """
    ensure_embedding_table()
    execute(
        """INSERT INTO company_embedding (enterprise_number, embedding, model)
           VALUES (%s, %s, %s)
           ON CONFLICT (enterprise_number) DO UPDATE SET
               embedding = EXCLUDED.embedding,
               model = EXCLUDED.model,
               generated_at = NOW()""",
        (cbe.strip().zfill(10), str(embedding), EMBEDDING_MODEL),
    )
