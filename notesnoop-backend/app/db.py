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
_pools: dict[tuple[str, str], psycopg2.pool.ThreadedConnectionPool] = {}
_conn_pool_keys: dict[int, tuple[str, str]] = {}
_lock = threading.Lock()


def _database_url(url: str | None = None) -> str:
    database_url = url or get_settings().database_url
    if not database_url:
        raise RuntimeError("NOTESNOOP_DATABASE_URL or DATABASE_URL is required")
    return database_url


def _get_pool(database_url: str | None = None, application_name: str = "notesnoop-backend") -> psycopg2.pool.ThreadedConnectionPool:
    key = (_database_url(database_url), application_name)
    with _lock:
        pool = _pools.get(key)
        if pool is None or pool.closed:
            pool = psycopg2.pool.ThreadedConnectionPool(
                1,
                12,
                key[0],
                connect_timeout=10,
                application_name=application_name,
            )
            _pools[key] = pool
        return pool


def get_conn(database_url: str | None = None, application_name: str = "notesnoop-backend"):
    pool = _get_pool(database_url, application_name)
    conn = pool.getconn()
    _conn_pool_keys[id(conn)] = (_database_url(database_url), application_name)
    conn.autocommit = False
    return conn


def get_worker_conn():
    settings = get_settings()
    return get_conn(settings.worker_database_url, application_name="notesnoop-worker")


def put_conn(conn) -> None:
    if conn is None:
        return
    key = _conn_pool_keys.pop(id(conn), None)
    pool = _pools.get(key) if key else None
    try:
        if conn.closed:
            return
        if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        if pool is None:
            conn.close()
        else:
            pool.putconn(conn)
    except Exception:
        logger.debug("discarding broken database connection", exc_info=True)
        try:
            if pool is None:
                conn.close()
            else:
                pool.putconn(conn, close=True)
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
