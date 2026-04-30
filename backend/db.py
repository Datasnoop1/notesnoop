"""Database connection module for the FastAPI backend.

Uses a simple connection pool to avoid exhausting Supabase session pooler limits.
"""

import os
import logging
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

from middleware.timing import record_db_timing

load_dotenv()

logger = logging.getLogger(__name__)

_DATABASE_URL = os.getenv("DATABASE_URL", "")

# Hard caps so a stalled socket can never hang a caller forever. The
# enrichment worker froze for ~20.5h on 2026-04-26 because a sync DB call on
# the asyncio event loop got stuck on a half-open socket — Linux TCP
# keepalive + retries can take hours to declare the connection dead. These
# values bound the worst case to seconds.
DB_CONNECT_TIMEOUT_S = int(os.getenv("DB_CONNECT_TIMEOUT_S", "10"))
# 120s server-side cap. Backend admin queries are the legitimate long ones;
# anything longer is almost certainly a stuck connection. The enrichment
# worker has its own tighter per-job ceiling on top of this.
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "120000"))

# Simple pool: min 1, max 3 connections (Supabase session pooler is limited)
_pool = None


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in environment / .env file")
        # ThreadedConnectionPool (not SimpleConnectionPool) — getconn /
        # putconn are wrapped in a threading.Lock. The de-async of
        # /api/{companies,people}/search (2026-04-30, search-perf-deasync)
        # routes them through FastAPI's threadpool, so concurrent
        # workers now hit the pool from multiple threads. Drop-in
        # replacement; same constructor args.
        #
        # maxconn 10 → 20: FastAPI threadpool defaults to ~40 workers.
        # Under typing-storm with cancelled-but-still-running queries
        # (statement_timeout=120s), 11+ concurrent search threads on the
        # old maxconn=10 would hit ThreadedConnectionPool's hard PoolError.
        # 20 doubles the headroom while staying well within Postgres'
        # default max_connections budget shared with the worker fleet.
        _pool = psycopg2.pool.ThreadedConnectionPool(
            2,
            20,
            _DATABASE_URL,
            connect_timeout=DB_CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}",
        )
    return _pool


def get_connection():
    """Get a pooled PostgreSQL connection."""
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def put_connection(conn):
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


@contextmanager
def get_conn():
    """Context manager that yields a pooled connection."""
    conn = get_connection()
    try:
        yield conn
    finally:
        put_connection(conn)


_STALE_CONN_ERRS = (
    psycopg2.InterfaceError,
    psycopg2.OperationalError,
)


def _is_stale_conn_error(exc: Exception) -> bool:
    """Match the specific "pooled connection died on the server side"
    failures that retrying on a fresh connection should recover from.
    Don't retry on query-syntax errors or data errors."""
    if not isinstance(exc, _STALE_CONN_ERRS):
        return False
    msg = str(exc).lower()
    return (
        "connection already closed" in msg
        or "ssl syscall error" in msg
        or "server closed the connection" in msg
        or "connection is bad" in msg
        or "no connection" in msg
    )


def _discard_connection(conn):
    """Close + discard a broken connection instead of returning it to the pool.

    Routes the close through `pool.putconn(conn, close=True)` so the pool
    drops the slot from `_used`. Calling `conn.close()` directly leaves
    the slot permanently occupied — pre-existed under SimpleConnectionPool
    but only became dangerous under ThreadedConnectionPool, which raises
    PoolError on exhaustion instead of blocking. Falls back to a raw
    close if the pool isn't available for any reason.
    """
    try:
        _get_pool().putconn(conn, close=True)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def fetch_all(sql: str, params: tuple | list = None) -> list[dict]:
    """Execute a query and return all rows as a list of dicts.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            t0 = time.perf_counter()
            cur.execute(sql, params)
            rows = cur.fetchall()
            record_db_timing((time.perf_counter() - t0) * 1000.0)
            cur.close()
            conn.commit()
            return [dict(r) for r in rows]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            # On retry we already discarded; otherwise return to pool.
            if conn.closed == 0:
                put_connection(conn)


def fetch_one(sql: str, params: tuple | list = None) -> dict | None:
    """Execute a query and return the first row as a dict, or None.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            t0 = time.perf_counter()
            cur.execute(sql, params)
            row = cur.fetchone()
            record_db_timing((time.perf_counter() - t0) * 1000.0)
            cur.close()
            conn.commit()
            return dict(row) if row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            if conn.closed == 0:
                put_connection(conn)


def execute(sql: str, params: tuple | list = None):
    """Execute a write query (INSERT/UPDATE/DELETE) and commit.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor()
            t0 = time.perf_counter()
            cur.execute(sql, params)
            record_db_timing((time.perf_counter() - t0) * 1000.0)
            conn.commit()
            cur.close()
            return
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            if conn.closed == 0:
                put_connection(conn)


@contextmanager
def transaction():
    """Context manager for multi-statement transactions.

    Yields (conn, cursor). Commits on clean exit, rolls back on exception.
    Use this for operations that need atomicity across multiple statements.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


# ---------------------------------------------------------------------------
# pg_trgm fuzzy matching migration
# ---------------------------------------------------------------------------

# Belgian legal-form suffixes to strip during name normalization
_BELGIAN_SUFFIXES_RE = (
    r"\s*("
    r"NV|SA|BVBA|SRL|SPRL|BV|CVBA|SCRL|VOF|SNC|SE|"
    r"COMM\.?\s*V|SCS|GCV|ASBL|VZW|AISBL|IVZW"
    r")\s*$"
)

_trgm_migrated = False


def ensure_trgm_setup():
    """Compatibility shim for the old startup schema bootstrap.

    Runtime DDL moved to tracked migrations in Week-1b. Keep this callable so
    older startup wiring stays harmless during rollout.
    """
    global _trgm_migrated
    if _trgm_migrated:
        return
    _trgm_migrated = True
    logger.info("Startup schema bootstrap skipped; schema is managed by migrations")


# ---------------------------------------------------------------------------
# Phase-22 defaults
# ---------------------------------------------------------------------------
# Schema DDL for these tables/columns moved to tracked migrations in Week-1b.
# This function keeps the boot-time data seed that is still useful after the
# migration has created invoice_vendor_pattern.

_phase22_migrated = False


def ensure_phase22_schema():
    """Seed Phase-22 defaults after tracked migrations created the tables."""
    global _phase22_migrated
    if _phase22_migrated:
        return
    try:
        from invoice_classifier import seed_default_patterns

        n = seed_default_patterns()
        if n:
            logger.info("Seeded %d invoice vendor patterns", n)
        _phase22_migrated = True
    except Exception:
        logger.exception("Phase-22 seed defaults failed (non-fatal)")


def normalize_name(name: str) -> str:
    """Normalize a company name for trigram matching (Python-side).

    Strips Belgian legal-form suffixes, lowercases, collapses whitespace.
    Used to normalize query inputs before comparing against name_normalized.
    """
    import re
    if not name:
        return ""
    # Strip Belgian legal suffixes
    cleaned = re.sub(_BELGIAN_SUFFIXES_RE, "", name, flags=re.IGNORECASE)
    # Lowercase and collapse whitespace
    return re.sub(r"\s+", " ", cleaned.lower()).strip()


def refresh_all_normalized_names() -> int:
    """Re-run normalization on all company_info rows. Returns count of rows updated.

    Post-search-V2 migration `company_info.name_normalized` is a
    GENERATED STORED column — Postgres rejects any UPDATE that targets
    it. We detect that situation via `f_unaccent()` and short-circuit
    with a no-op return so admin callers don't see a 500.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # V2 migration guard — generated columns are self-maintained.
        cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'f_unaccent' LIMIT 1")
        if cur.fetchone() is not None:
            cur.close()
            logger.info(
                "refresh_all_normalized_names: search V2 detected — "
                "name_normalized is a generated column, no-op"
            )
            return 0

        cur.execute(f"""
            UPDATE company_info
            SET name_normalized = TRIM(REGEXP_REPLACE(
                LOWER(REGEXP_REPLACE(
                    name,
                    %s,
                    '', 'gi'
                )),
                '\\s+', ' ', 'g'
            ))
            WHERE name IS NOT NULL;
        """, (_BELGIAN_SUFFIXES_RE,))
        count = cur.rowcount
        conn.commit()
        cur.close()
        logger.info("Re-normalized %d company names", count)
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)
