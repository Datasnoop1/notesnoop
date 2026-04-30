"""Postgres-backed work queue for the bulk enrichment worker.

One row per enterprise in `enrichment_job`. Claims use
`FOR UPDATE SKIP LOCKED` so multiple worker loops (threads or
processes) don't grab the same CBE. Caller owns the transaction
boundary; finish/fail closes it out.

Kept deliberately small — the worker in `backend/enrichment_worker.py`
reads this as a library, not an abstraction layer. See
`plans/i-want-to-explore-delightful-storm.md` §Bulk worker for the
lifecycle contract.
"""

from __future__ import annotations

import logging
from typing import Iterable

from db import execute, fetch_all, fetch_one, get_connection, put_connection

logger = logging.getLogger(__name__)

# `claim_one` increments `attempts` at claim time — i.e. the counter
# reflects the claim, not the failure. With MAX_ATTEMPTS=5 the job gets
# 5 total attempts; the 5th failure flips it to 'dead'. Don't lower
# this without also loosening the `mark_failed` comparison, or you'll
# kill jobs after the first transient error.
MAX_ATTEMPTS = 5

_schema_ensured = False


def ensure_schema() -> None:
    """Compatibility shim for the old enrichment_job startup DDL.

    Runtime DDL moved to tracked migrations in Week-1b. Safe to call
    repeatedly; gated by a module-level flag.
    """
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True


def enqueue(cbe: str, priority: int = 0) -> bool:
    """Insert a single CBE. Returns True if a new row was created."""
    ensure_schema()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO enrichment_job (enterprise_number, priority) "
            "VALUES (%s, %s) ON CONFLICT (enterprise_number) DO NOTHING",
            (cbe.strip().zfill(10), int(priority)),
        )
        created = cur.rowcount == 1
        conn.commit()
        cur.close()
        return created
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def bulk_enqueue(rows: Iterable[tuple[str, int]]) -> int:
    """Insert many (cbe, priority) pairs. Returns the number of new rows.

    Used by `scripts/seed_enrichment_queue.py` for the initial backfill.
    """
    ensure_schema()
    inserted = 0
    conn = get_connection()
    try:
        cur = conn.cursor()
        for cbe, priority in rows:
            cur.execute(
                "INSERT INTO enrichment_job (enterprise_number, priority) "
                "VALUES (%s, %s) ON CONFLICT (enterprise_number) DO NOTHING",
                (cbe.strip().zfill(10), int(priority)),
            )
            if cur.rowcount == 1:
                inserted += 1
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)
    return inserted


def claim_one() -> dict | None:
    """Atomically claim the highest-priority queued job.

    Returns a dict with keys
    `{enterprise_number, priority, attempts}` — or None if nothing is
    queued. Uses `FOR UPDATE SKIP LOCKED` for concurrent-worker safety.
    """
    ensure_schema()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH next AS (
                SELECT enterprise_number
                FROM enrichment_job
                WHERE status = 'queued'
                ORDER BY priority DESC, enqueued_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE enrichment_job j
               SET status = 'claimed',
                   attempts = j.attempts + 1,
                   claimed_at = NOW()
              FROM next
             WHERE j.enterprise_number = next.enterprise_number
         RETURNING j.enterprise_number, j.priority, j.attempts
            """
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if row is None:
            return None
        return {
            "enterprise_number": row[0],
            "priority": row[1],
            "attempts": row[2],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def claim_many(limit: int) -> list[dict]:
    """Atomically claim up to `limit` queued jobs in one round-trip.

    Same ordering and concurrency guarantees as `claim_one`, but reduces
    database chatter when a worker has several free slots to fill.
    """
    ensure_schema()
    limit = max(0, int(limit))
    if limit <= 0:
        return []
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH next AS (
                SELECT enterprise_number
                  FROM enrichment_job
                 WHERE status = 'queued'
              ORDER BY priority DESC, enqueued_at ASC
                 LIMIT %s
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE enrichment_job j
               SET status = 'claimed',
                   attempts = j.attempts + 1,
                   claimed_at = NOW()
              FROM next
             WHERE j.enterprise_number = next.enterprise_number
         RETURNING j.enterprise_number, j.priority, j.attempts
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        return [
            {
                "enterprise_number": row[0],
                "priority": row[1],
                "attempts": row[2],
            }
            for row in rows
        ]
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def mark_done(cbe: str) -> None:
    """Move a claimed job to `done`. Idempotent."""
    execute(
        "UPDATE enrichment_job SET status = 'done', finished_at = NOW(), "
        "last_error = NULL WHERE enterprise_number = %s",
        (cbe,),
    )


def mark_excluded(cbe: str) -> None:
    """Move a job to `excluded` so it is outside the semantic corpus."""
    execute(
        """
        UPDATE enrichment_job
           SET status = 'excluded',
               priority = 0,
               attempts = 0,
               claimed_at = NULL,
               finished_at = NOW(),
               last_error = NULL
         WHERE enterprise_number = %s
        """,
        (cbe,),
    )


_SECRET_REDACT_PATTERNS = (
    ("Bearer ", "Bearer [REDACTED]"),
    ("api_key=", "api_key=[REDACTED]"),
    ("apikey=", "apikey=[REDACTED]"),
    ("sk-", "sk-[REDACTED]"),
)


def _redact(error: str) -> str:
    """Defence-in-depth: scrub anything that looks like a bearer token
    or API key before persisting an error string.

    The admin dead-letter view renders `last_error` verbatim, so even
    though no current caller sends tokens, future refactors could
    inadvertently leak them through. Cheap belt-and-braces.
    """
    out = error
    for needle, replacement in _SECRET_REDACT_PATTERNS:
        if needle in out:
            # Redact the needle + the next 12 chars (covers a typical
            # token tail). Keep the rest of the message intact so
            # admins still see the error shape.
            import re as _re
            out = _re.sub(
                _re.escape(needle) + r"\S{0,80}",
                replacement,
                out,
            )
    return out


def mark_failed(cbe: str, error: str) -> None:
    """Return a claimed job to the queue with an error annotation.

    If `attempts >= MAX_ATTEMPTS`, mark the row `dead` instead so the
    worker never reclaims it. Dead rows surface on the admin page's
    dead-letter tab for manual inspection.
    """
    trimmed = _redact((error or "")[:4000])
    execute(
        """
        UPDATE enrichment_job
           SET status = CASE WHEN attempts >= %s THEN 'dead' ELSE 'queued' END,
               last_error = %s,
               finished_at = CASE WHEN attempts >= %s THEN NOW() ELSE NULL END
         WHERE enterprise_number = %s
        """,
        (MAX_ATTEMPTS, trimmed, MAX_ATTEMPTS, cbe),
    )


def release_stale(older_than_minutes: int = 30) -> int:
    """Un-claim jobs that have been claimed longer than the threshold.

    A worker crash before mark_done/mark_failed would otherwise strand
    the job as 'claimed' forever. Returns the number of rows returned
    to the queue.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE enrichment_job
               SET status = 'queued',
                   claimed_at = NULL,
                   last_error = COALESCE(last_error, '') ||
                                ' [stale-claim released]'
             WHERE status = 'claimed'
               AND claimed_at < NOW() - (%s * INTERVAL '1 minute')
            """,
            (int(older_than_minutes),),
        )
        released = cur.rowcount
        conn.commit()
        cur.close()
        return released
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def stats() -> dict:
    """Summary counts by status, for the admin page."""
    ensure_schema()
    rows = fetch_all(
        "SELECT status, COUNT(*)::bigint AS n FROM enrichment_job GROUP BY status"
    )
    return {r["status"]: int(r["n"]) for r in rows}


def recent_failures(limit: int = 50) -> list[dict]:
    """Latest failed/dead jobs for the admin dead-letter view."""
    ensure_schema()
    rows = fetch_all(
        """
        SELECT enterprise_number, status, attempts,
               claimed_at, finished_at, last_error
          FROM enrichment_job
         WHERE status IN ('dead', 'failed') OR last_error IS NOT NULL
      ORDER BY COALESCE(finished_at, claimed_at) DESC NULLS LAST
         LIMIT %s
        """,
        (int(limit),),
    )
    return [dict(r) for r in rows]


def meta_flag(name: str, default: str | None = None) -> str | None:
    """Read a string from the `meta` table. Returns `default` when absent."""
    row = fetch_one("SELECT value FROM meta WHERE variable = %s", (name,))
    return row["value"] if row else default


def set_meta_flag(name: str, value: str) -> None:
    execute(
        "INSERT INTO meta (variable, value) VALUES (%s, %s) "
        "ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
        (name, value),
    )


def enrichment_enabled() -> bool:
    """Kill switch — when false, worker drains on next poll."""
    val = (meta_flag("enrichment_enabled", "true") or "").strip().lower()
    return val in ("true", "1", "yes", "on")
