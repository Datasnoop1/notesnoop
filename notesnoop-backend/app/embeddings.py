from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
from dataclasses import dataclass

import httpx


logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "https://ollama.com")).rstrip("/")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

EMBEDDING_MODEL = os.getenv("NOTESNOOP_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
EMBEDDING_DIMENSION = int(os.getenv("NOTESNOOP_EMBEDDING_DIMENSION", "1024"))
ALLOW_LEXICAL_FALLBACK = os.getenv("NOTESNOOP_EMBEDDING_ALLOW_LEXICAL_FALLBACK", "true").lower() in {
    "1",
    "true",
    "yes",
}

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_'-]*")


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str
    provider: str
    dimension: int
    text_sha256: str


class EmbeddingUnavailable(RuntimeError):
    pass


def _is_cloud_host() -> bool:
    return "ollama.com" in OLLAMA_HOST


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def note_embedding_text(note: dict) -> str:
    return "\n\n".join(str(part).strip() for part in (note.get("title"), note.get("body")) if str(part or "").strip())


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lexical_hash_embedding(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        tokens = ["empty"]

    values = [0.0] * dimension

    def add_token(token: str, weight: float) -> None:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = -1.0 if digest[4] & 1 else 1.0
        values[bucket] += sign * weight

    previous = ""
    for token in tokens[:4096]:
        add_token(token, 1.0 + min(len(token), 20) / 20.0)
        if previous:
            add_token(f"{previous} {token}", 0.5)
        previous = token

    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 8) for value in values]


def vector_literal(vector: list[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSION:
        raise ValueError(f"Expected embedding dimension {EMBEDDING_DIMENSION}, got {len(vector)}")
    parts = []
    for value in vector:
        rendered = f"{float(value):.8f}".rstrip("0").rstrip(".")
        parts.append(rendered if rendered not in {"", "-0"} else "0")
    return "[" + ",".join(parts) + "]"


async def _ollama_embedding(text: str) -> list[float]:
    if _is_cloud_host() and not OLLAMA_API_KEY:
        raise EmbeddingUnavailable("OLLAMA_API_KEY is not configured")
    payload = {"model": EMBEDDING_MODEL, "input": text[:12000]}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/embed",
            headers=_headers(),
            json=payload,
        )
    if response.status_code in {401, 403, 404}:
        raise EmbeddingUnavailable(f"Ollama embedding endpoint unavailable: HTTP {response.status_code}")
    response.raise_for_status()
    data = response.json()
    raw = data.get("embeddings") or data.get("embedding")
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        raw = raw[0]
    if not isinstance(raw, list) or not raw:
        raise EmbeddingUnavailable("Ollama embedding response did not contain a vector")
    vector = [float(value) for value in raw]
    if len(vector) != EMBEDDING_DIMENSION:
        raise EmbeddingUnavailable(
            f"Ollama embedding dimension {len(vector)} does not match locked dimension {EMBEDDING_DIMENSION}"
        )
    return vector


async def embed_text(text: str) -> EmbeddingResult:
    normalized_text = text.strip() or "empty"
    digest = text_sha256(normalized_text)
    try:
        vector = await _ollama_embedding(normalized_text)
        return EmbeddingResult(
            vector=vector,
            model=EMBEDDING_MODEL,
            provider="ollama",
            dimension=EMBEDDING_DIMENSION,
            text_sha256=digest,
        )
    except Exception as exc:
        if not ALLOW_LEXICAL_FALLBACK:
            raise
        logger.info("using lexical embedding fallback: %s", exc)
        return EmbeddingResult(
            vector=lexical_hash_embedding(normalized_text),
            model=EMBEDDING_MODEL,
            provider="lexical_hash",
            dimension=EMBEDDING_DIMENSION,
            text_sha256=digest,
        )


def embed_text_sync(text: str) -> EmbeddingResult:
    return asyncio.run(embed_text(text))


def upsert_note_embedding(cur, note: dict, result: EmbeddingResult) -> None:
    cur.execute(
        """
        INSERT INTO embeddings (
          note_id,
          workspace_id,
          embedding,
          model_version,
          provider,
          embedding_dimension,
          embedding_text_sha256,
          computed_at
        )
        VALUES (%s, %s, %s::vector, %s, %s, %s, %s, now())
        ON CONFLICT (note_id) DO UPDATE
          SET workspace_id = EXCLUDED.workspace_id,
              embedding = EXCLUDED.embedding,
              model_version = EXCLUDED.model_version,
              provider = EXCLUDED.provider,
              embedding_dimension = EXCLUDED.embedding_dimension,
              embedding_text_sha256 = EXCLUDED.embedding_text_sha256,
              computed_at = EXCLUDED.computed_at
        """,
        (
            note["id"],
            note["workspace_id"],
            vector_literal(result.vector),
            result.model,
            result.provider,
            result.dimension,
            result.text_sha256,
        ),
    )
