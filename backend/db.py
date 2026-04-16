"""Database connection module for the FastAPI backend.

Uses a simple connection pool to avoid exhausting Supabase session pooler limits.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DATABASE_URL = os.getenv("DATABASE_URL", "")

# Simple pool: min 1, max 3 connections (Supabase session pooler is limited)
_pool = None


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in environment / .env file")
        _pool = psycopg2.pool.SimpleConnectionPool(2, 10, _DATABASE_URL)
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


def fetch_all(sql: str, params: tuple | list = None) -> list[dict]:
    """Execute a query and return all rows as a list of dicts."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.commit()
        return [dict(r) for r in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def fetch_one(sql: str, params: tuple | list = None) -> dict | None:
    """Execute a query and return the first row as a dict, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        conn.commit()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def execute(sql: str, params: tuple | list = None):
    """Execute a write query (INSERT/UPDATE/DELETE) and commit."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
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
    """Enable pg_trgm, add name_normalized column, populate it, and create GIN index.

    Safe to call on every startup — all statements use IF NOT EXISTS / are idempotent.
    Runs once per process (guarded by _trgm_migrated flag).
    """
    global _trgm_migrated
    if _trgm_migrated:
        return

    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1. Enable the pg_trgm extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        # 2. Add name_normalized column if it doesn't exist
        cur.execute(
            "ALTER TABLE company_info ADD COLUMN IF NOT EXISTS name_normalized TEXT;"
        )

        # 3. Populate name_normalized for rows where it is NULL
        #    (strip Belgian legal suffixes, lowercase, collapse whitespace)
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
            WHERE name_normalized IS NULL AND name IS NOT NULL;
        """, (_BELGIAN_SUFFIXES_RE,))
        normalized_count = cur.rowcount

        # 4. Create GIN trigram indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ci_name_trgm
            ON company_info USING GIN (name_normalized gin_trgm_ops);
        """)
        # 5. GIN trigram indexes on people tables for ILIKE searches
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_name_trgm
            ON administrator USING GIN (name gin_trgm_ops);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sh_name_trgm
            ON shareholder USING GIN (name gin_trgm_ops);
        """)

        conn.commit()
        cur.close()
        _trgm_migrated = True
        logger.info(
            "pg_trgm setup complete: normalized %d company names, GIN index ensured",
            normalized_count,
        )
    except Exception:
        conn.rollback()
        logger.exception("pg_trgm migration failed (non-fatal, will retry next startup)")
    finally:
        put_connection(conn)


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
    """Re-run normalization on all company_info rows. Returns count of rows updated."""
    conn = get_connection()
    try:
        cur = conn.cursor()
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
