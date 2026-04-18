"""Generate pgvector embeddings for Staatsblad events (Phase 3e).

Scans `staatsblad_event` for rows without a matching row in
`staatsblad_event_embedding`, composes a short embedding input string,
calls OpenRouter's `openai/text-embedding-3-small` at 256 dims, and
writes to the embedding table.

Runs after every extraction pass (daily and backfill).  Cost at 110k
events × $0.02 per 1M tokens × ~40 tokens/event ≈ $0.09 total.

Usage:
    python scripts/staatsblad_embed.py                  # process all pending
    python scripts/staatsblad_embed.py --batch 200      # 200 per pass
    python scripts/staatsblad_embed.py --limit 1000     # total cap
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from db import fetch_all, get_connection, put_connection  # noqa: E402
from embeddings import generate_embedding, EMBEDDING_DIMS, EMBEDDING_MODEL  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("staatsblad-embed")


def _embed_input(row: dict) -> str:
    """Compose the short string we embed.  Keep under ~80 tokens."""
    parts = [
        (row.get("event_type") or "").replace("_", " "),
        row.get("sub_type") or "",
        row.get("person_name") or "",
        row.get("person_role") or "",
        row.get("entity_name") or "",
        row.get("summary") or "",
    ]
    return " | ".join(p for p in parts if p).strip()


async def embed_pending(batch: int, limit: int | None) -> int:
    """Embed up to `limit` pending rows in slices of `batch`.
    Returns count embedded."""
    rows = fetch_all(
        """SELECT e.id, e.event_type, e.sub_type, e.person_name,
                  e.person_role, e.entity_name, e.summary
           FROM staatsblad_event e
           LEFT JOIN staatsblad_event_embedding emb ON emb.event_id = e.id
           WHERE emb.event_id IS NULL
           ORDER BY e.id ASC
           LIMIT %s""",
        (limit if limit else 10_000_000,),
    )
    if not rows:
        log.info("No pending events to embed.")
        return 0

    log.info("Pending embeddings: %d (processing %d at a time)", len(rows), batch)

    done = 0
    for i in range(0, len(rows), batch):
        slice_ = rows[i:i + batch]
        tasks = [generate_embedding(_embed_input(r)) for r in slice_]
        embeddings = await asyncio.gather(*tasks, return_exceptions=True)

        conn = get_connection()
        try:
            cur = conn.cursor()
            try:
                for r, emb in zip(slice_, embeddings):
                    if isinstance(emb, Exception) or not emb:
                        continue
                    if len(emb) != EMBEDDING_DIMS:
                        log.warning("Unexpected embedding dims=%d for event %s",
                                    len(emb), r["id"])
                        continue
                    # pgvector expects a string literal "[v1,v2,...]"
                    emb_literal = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
                    cur.execute(
                        """INSERT INTO staatsblad_event_embedding
                               (event_id, embedding, model)
                           VALUES (%s, %s::vector, %s)
                           ON CONFLICT (event_id) DO NOTHING""",
                        (r["id"], emb_literal, EMBEDDING_MODEL),
                    )
                    done += 1
                conn.commit()
            finally:
                cur.close()
        except Exception:
            conn.rollback()
            log.exception("Batch commit failed at slice starting %d", i)
        finally:
            put_connection(conn)

        log.info("  progress: %d/%d", done, len(rows))

    return done


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", type=int, default=100)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        log.error("OPENROUTER_API_KEY not set")
        return 2

    n = asyncio.run(embed_pending(batch=args.batch, limit=args.limit))
    log.info("Embedded %d events.", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
