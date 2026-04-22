"""Shared bootstrap + readiness helpers for the semantic-enrichment pipeline.

The pipeline previously depended on a very specific rollout order:
backend startup needed to run the Phase 1 migrations, the worker needed a
seeded queue, and the admin UI assumed every supporting table already
existed. When one of those steps was skipped, the system often looked
"empty" instead of clearly reporting what was missing.

This module centralises the schema/default setup and exposes a small
readiness snapshot used by the worker, admin panel, and semantic search
endpoint.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from db import execute, fetch_all, fetch_one
from enrichment_queue import ensure_schema as ensure_queue_schema
from enrichment_queue import meta_flag, set_meta_flag

DEFAULT_DAILY_BUDGET_USD = "10.00"
WORKER_HEARTBEAT_VARIABLE = "enrichment_worker_last_heartbeat"
WORKER_STATE_VARIABLE = "enrichment_worker_state"
WORKER_NOTE_VARIABLE = "enrichment_worker_note"
DEFAULT_WORKER_STALE_AFTER_S = 180

_semantic_schema_ensured = False

_REQUIRED_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "ZENROWS_API_KEY",
    "ENRICHMENT_ADMIN_PASSWORD",
)

_SEMANTIC_COLUMNS = (
    ("website_summary", "TEXT"),
    ("linkedin_summary", "TEXT"),
    ("website_url", "TEXT"),
    ("ai_insights", "TEXT"),
    ("bulk_summary", "JSONB"),
    ("bulk_summary_at", "TIMESTAMPTZ"),
    ("bulk_website_hash", "TEXT"),
    ("bulk_website_url", "TEXT"),
    ("bulk_confidence", "TEXT"),
)

_SKIPLIST_SEEDS = (
    ("pappers.be", "domain", "seed: KBO aggregator"),
    ("bsearch.be", "domain", "seed: business directory"),
    ("handelsgids.be", "domain", "seed: business directory"),
    ("infobel.be", "domain", "seed: directory"),
    ("immoweb.be", "domain", "seed: real-estate listing"),
    ("lemariagedelouise.be", "domain", "seed: wedding-vendor listing"),
    ("economie.fgov.be", "domain", "seed: KBO portal"),
    ("kompass.com", "domain", "seed: B2B directory"),
    ("europages.com", "domain", "seed: B2B directory"),
    ("dnb.com", "domain", "seed: credit directory"),
    ("companyweb.be", "domain", "seed: directory"),
    ("staatsbladmonitor.be", "domain", "seed: gazette mirror"),
    ("trends.knack.be", "domain", "seed: press directory"),
    ("/bedrijvengids/", "path", "seed: municipal business index"),
    ("/annuaire/", "path", "seed: FR municipal directory"),
    ("/infrastructuur-", "path", "seed: municipal infrastructure"),
)


def _table_exists(table_name: str) -> bool:
    row = fetch_one(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_name = %s
        ) AS present
        """,
        (table_name,),
    )
    return bool(row and row.get("present"))


def _safe_count(table_name: str, where_sql: str = "", params: tuple | list | None = None) -> int:
    if not _table_exists(table_name):
        return 0
    sql = f"SELECT COUNT(*)::bigint AS n FROM {table_name}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    row = fetch_one(sql, params)
    return int(row["n"] or 0) if row else 0


def _safe_status_counts() -> dict[str, int]:
    if not _table_exists("enrichment_job"):
        return {}
    rows = fetch_all(
        "SELECT status, COUNT(*)::bigint AS n FROM enrichment_job GROUP BY status"
    )
    return {str(r["status"]): int(r["n"]) for r in rows}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_company_enrichment_table() -> None:
    """Ensure the semantic columns exist on `company_enrichment`.

    The on-profile enrichment routes also create this table lazily. We
    duplicate the minimal DDL here so the bulk semantic pipeline can be
    bootstrapped independently from profile traffic.
    """
    execute(
        """
        CREATE TABLE IF NOT EXISTS company_enrichment (
            enterprise_number VARCHAR(10) PRIMARY KEY,
            summary TEXT,
            generated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    for column, typ in _SEMANTIC_COLUMNS:
        execute(
            f"ALTER TABLE company_enrichment "
            f"ADD COLUMN IF NOT EXISTS {column} {typ}"
        )


def ensure_meta_defaults() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            variable TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    if meta_flag("enrichment_enabled") is None:
        set_meta_flag("enrichment_enabled", "true")
    if meta_flag("enrichment_daily_budget") is None:
        set_meta_flag("enrichment_daily_budget", DEFAULT_DAILY_BUDGET_USD)


def ensure_aggregator_skiplist() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS aggregator_skiplist (
            id          SERIAL PRIMARY KEY,
            pattern     TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'domain',
            reason      TEXT,
            added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            added_by    TEXT,
            UNIQUE (pattern, kind)
        )
        """
    )
    for pattern, kind, reason in _SKIPLIST_SEEDS:
        execute(
            """
            INSERT INTO aggregator_skiplist (pattern, kind, reason, added_by)
            VALUES (%s, %s, %s, 'seed')
            ON CONFLICT (pattern, kind) DO NOTHING
            """,
            (pattern, kind, reason),
        )


def ensure_semantic_schema() -> None:
    """Create every table/default the semantic pipeline depends on."""
    global _semantic_schema_ensured
    if _semantic_schema_ensured:
        return
    from ai_client import _ensure_llm_call_log_table
    from embeddings import ensure_embedding_table, ensure_query_embedding_cache

    ensure_meta_defaults()
    ensure_company_enrichment_table()
    ensure_queue_schema()
    _ensure_llm_call_log_table()
    ensure_embedding_table()
    ensure_query_embedding_cache()
    ensure_aggregator_skiplist()
    _semantic_schema_ensured = True


def record_worker_heartbeat(state: str, note: str | None = None) -> None:
    """Persist a lightweight worker heartbeat in `meta` for observability."""
    ensure_meta_defaults()
    now = datetime.now(timezone.utc).isoformat()
    set_meta_flag(WORKER_HEARTBEAT_VARIABLE, now)
    set_meta_flag(WORKER_STATE_VARIABLE, (state or "unknown")[:80])
    if note is not None:
        set_meta_flag(WORKER_NOTE_VARIABLE, note[:240])


def get_semantic_readiness(
    stale_after_s: int = DEFAULT_WORKER_STALE_AFTER_S,
) -> dict[str, Any]:
    """Return a JSON-serialisable readiness snapshot for admin and scripts."""
    meta_present = _table_exists("meta")

    def _meta(name: str, default: str | None = None) -> str | None:
        if not meta_present:
            return default
        return meta_flag(name, default)

    tables = {
        "meta": meta_present,
        "company_enrichment": _table_exists("company_enrichment"),
        "enrichment_job": _table_exists("enrichment_job"),
        "company_embedding": _table_exists("company_embedding"),
        "query_embedding_cache": _table_exists("query_embedding_cache"),
        "aggregator_skiplist": _table_exists("aggregator_skiplist"),
    }
    env = {name: bool(os.getenv(name)) for name in _REQUIRED_ENV_VARS}

    worker_heartbeat_raw = _meta(WORKER_HEARTBEAT_VARIABLE)
    worker_heartbeat = _parse_iso(worker_heartbeat_raw)
    worker_age_s: int | None = None
    if worker_heartbeat is not None:
        worker_age_s = int(
            (datetime.now(timezone.utc) - worker_heartbeat).total_seconds()
        )

    counts = {
        "bulk_rows": _safe_count("company_enrichment", "bulk_summary IS NOT NULL"),
        "publishable_rows": _safe_count(
            "company_enrichment",
            "bulk_confidence IN ('high', 'medium')",
        ),
        "embedding_rows": _safe_count("company_embedding"),
        "query_cache_rows": _safe_count("query_embedding_cache"),
    }
    queue_counts = _safe_status_counts()

    issues: list[str] = []
    for table_name, present in tables.items():
        if not present:
            issues.append(f"missing_table:{table_name}")
    for env_name, present in env.items():
        if not present:
            issues.append(f"missing_env:{env_name}")
    if counts["bulk_rows"] == 0:
        issues.append("no_bulk_rows")
    if counts["embedding_rows"] == 0:
        issues.append("no_company_embeddings")
    if sum(queue_counts.values()) == 0:
        issues.append("queue_empty")
    if worker_age_s is None:
        issues.append("worker_heartbeat_missing")
    elif worker_age_s > stale_after_s:
        issues.append("worker_heartbeat_stale")

    return {
        "tables": tables,
        "env": env,
        "counts": counts,
        "queue_counts": queue_counts,
        "meta": {
            "enrichment_enabled": _meta("enrichment_enabled", "true"),
            "enrichment_daily_budget": _meta(
                "enrichment_daily_budget",
                DEFAULT_DAILY_BUDGET_USD,
            ),
        },
        "worker": {
            "last_heartbeat": worker_heartbeat_raw,
            "heartbeat_age_s": worker_age_s,
            "state": _meta(WORKER_STATE_VARIABLE),
            "note": _meta(WORKER_NOTE_VARIABLE),
            "stale_after_s": int(stale_after_s),
            "is_stale": worker_age_s is None or worker_age_s > stale_after_s,
        },
        "issues": issues,
        "schema_ready": all(tables.values()),
        "search_ready": tables["company_embedding"] and counts["embedding_rows"] > 0,
    }
