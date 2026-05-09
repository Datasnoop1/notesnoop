from __future__ import annotations

import contextlib
import logging
import threading
from typing import Iterator

import psycopg2
import psycopg2.extras
import psycopg2.pool

from .config import get_settings


logger = logging.getLogger(__name__)
_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    with _lock:
        if _pool is None or _pool.closed:
            database_url = get_settings().database_url
            if not database_url:
                raise RuntimeError("NOTESNOOP_DATABASE_URL or DATABASE_URL is required")
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1,
                12,
                database_url,
                connect_timeout=10,
                application_name="notesnoop-backend",
            )
        return _pool


def get_conn():
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def put_conn(conn) -> None:
    if conn is None:
        return
    try:
        if conn.closed:
            return
        if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        _get_pool().putconn(conn)
    except Exception:
        logger.debug("discarding broken database connection", exc_info=True)
        try:
            _get_pool().putconn(conn, close=True)
        except Exception:
            with contextlib.suppress(Exception):
                conn.close()


@contextlib.contextmanager
def transaction(user_id: str | None = None, provider_webhook: bool = False) -> Iterator:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            if user_id:
                cur.execute("SET LOCAL notesnoop.current_user_id = %s", (user_id,))
            if provider_webhook:
                cur.execute("SET LOCAL notesnoop.provider_webhook = 'true'")
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def one(cur, sql: str, params: tuple = ()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def many(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]
