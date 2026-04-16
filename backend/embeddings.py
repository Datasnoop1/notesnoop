"""Embedding utilities — generate and store vector embeddings for semantic search.

Uses OpenRouter's embeddings API with a free or cheap model.
Stores vectors in PostgreSQL via pgvector extension.

Models (change EMBEDDING_MODEL to switch):
  - nvidia/llama-nemotron-embed-vl-1b-v2:free  (free, logs data)
  - openai/text-embedding-3-small               ($0.02/1M tokens, 1536 dims)
"""

import json
import logging
import os
from typing import Optional

import httpx
from db import get_connection, put_connection, execute, fetch_one, fetch_all

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "1536"))

_table_ensured = False


def ensure_embedding_table():
    """Create the company_embedding table with pgvector if it doesn't exist."""
    global _table_ensured
    if _table_ensured:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS company_embedding (
                enterprise_number VARCHAR(10) PRIMARY KEY,
                embedding vector({EMBEDDING_DIMS}),
                source_text TEXT,
                model VARCHAR(100),
                generated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ce_embedding
            ON company_embedding USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
        conn.commit()
        cur.close()
        _table_ensured = True
        logger.info("company_embedding table ensured (dims=%d)", EMBEDDING_DIMS)
    except Exception as e:
        conn.rollback()
        # IVFFlat index needs rows first — retry without index
        try:
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS company_embedding (
                    enterprise_number VARCHAR(10) PRIMARY KEY,
                    embedding vector({EMBEDDING_DIMS}),
                    source_text TEXT,
                    model VARCHAR(100),
                    generated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            _table_ensured = True
            logger.info("company_embedding table ensured (no index yet — add after first batch)")
        except Exception:
            conn.rollback()
            logger.exception("Failed to create company_embedding table")
    finally:
        put_connection(conn)


async def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a text string via OpenRouter."""
    if not OPENROUTER_API_KEY or not text:
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
                    "input": text[:8000],  # Truncate to avoid token limits
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("Embedding API returned %d: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
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
            """INSERT INTO company_embedding (enterprise_number, embedding, source_text, model)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (enterprise_number) DO UPDATE SET
                   embedding = EXCLUDED.embedding,
                   source_text = EXCLUDED.source_text,
                   model = EXCLUDED.model,
                   generated_at = NOW()""",
            (cbe, str(embedding), text[:2000], EMBEDDING_MODEL),
        )
        return True
    except Exception as e:
        logger.error("Failed to store embedding for %s: %s", cbe, e)
        return False


async def find_similar_by_embedding(cbe: str, limit: int = 20) -> list[dict]:
    """Find companies with the most similar embeddings using cosine distance.

    Returns list of {enterprise_number, name, city, similarity, source_text} sorted by similarity.
    """
    ensure_embedding_table()
    cbe = cbe.strip().replace(".", "").zfill(10)

    # Get the target company's embedding
    target = fetch_one(
        "SELECT embedding FROM company_embedding WHERE enterprise_number = %s", (cbe,)
    )
    if not target or not target.get("embedding"):
        return []

    # Find nearest neighbors
    rows = fetch_all(f"""
        SELECT ce.enterprise_number, ci.name, ci.city,
               1 - (ce.embedding <=> %s::vector) AS similarity
        FROM company_embedding ce
        LEFT JOIN company_info ci ON ci.enterprise_number = ce.enterprise_number
        WHERE ce.enterprise_number != %s
        ORDER BY ce.embedding <=> %s::vector
        LIMIT %s
    """, (target["embedding"], cbe, target["embedding"], limit))

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
                """INSERT INTO company_embedding (enterprise_number, embedding, source_text, model)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (enterprise_number) DO UPDATE SET
                       embedding = EXCLUDED.embedding, source_text = EXCLUDED.source_text,
                       model = EXCLUDED.model, generated_at = NOW()""",
                (cbe, str(embedding), text[:2000], EMBEDDING_MODEL),
            )
            embedded += 1
            if embedded % 10 == 0:
                logger.info("Embedded %d/%d companies...", embedded, len(rows))
        except Exception as e:
            logger.error("Embedding failed for %s: %s", row["enterprise_number"], e)
            errors += 1

    logger.info("Batch embedding done: %d embedded, %d errors, %d total candidates", embedded, errors, len(rows))
    return {"embedded": embedded, "skipped": len(rows) - embedded - errors, "errors": errors}
