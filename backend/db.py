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
        _pool = psycopg2.pool.SimpleConnectionPool(1, 3, _DATABASE_URL)
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
