"""Regression tests for psycopg2 pool return safety."""

import sys
from pathlib import Path

import psycopg2.extensions

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402


class _Info:
    def __init__(self, status):
        self.transaction_status = status


class _Cursor:
    description = [object()]

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))

    def fetchone(self):
        sql = self.conn.executed[-1][0]
        if "pg_backend_pid" in sql:
            return ("datasnoop:rid=abc123", 1234)
        return ("datasnoop",)


class _Connection:
    def __init__(self, status=psycopg2.extensions.TRANSACTION_STATUS_IDLE):
        self.info = _Info(status)
        self.closed = 0
        self.autocommit = False
        self.executed = []

    def cursor(self):
        return _Cursor(self)

    def get_backend_pid(self):
        return 1234

    def close(self):
        self.closed = 1


class _Pool:
    def __init__(self):
        self.returned = []
        self.conn = None

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


def test_put_connection_resets_application_name_before_pool_return(monkeypatch):
    pool = _Pool()
    conn = _Connection()
    monkeypatch.setattr(db, "_get_pool", lambda: pool)

    db.put_connection(conn)

    assert pool.returned == [(conn, False)]
    assert conn.autocommit is False
    assert conn.executed == [
        (
            "SELECT set_config('application_name', %s, false)",
            ("datasnoop",),
        )
    ]


def test_put_connection_discards_non_idle_transaction(monkeypatch):
    pool = _Pool()
    conn = _Connection(psycopg2.extensions.TRANSACTION_STATUS_INERROR)
    monkeypatch.setattr(db, "_get_pool", lambda: pool)

    db.put_connection(conn)

    assert pool.returned == [(conn, True)]
    assert conn.executed == []


def test_get_connection_tags_cancellable_request(monkeypatch):
    conn = _Connection()
    pool = _Pool()
    pool.getconn = lambda: conn
    monkeypatch.setattr(db, "_get_pool", lambda: pool)

    token = db.set_query_cancel_context(db.QueryCancelContext("abc123", "/api/companies/search"))
    try:
        got = db.get_connection()
        pid, request_id = db.get_query_cancel_context().snapshot()
    finally:
        db.reset_query_cancel_context(token)

    assert got is conn
    assert request_id == "abc123"
    assert pid == 1234
    assert conn.executed == [
        (
            "SELECT set_config('application_name', %s, false), pg_backend_pid()",
            ("datasnoop:rid=abc123",),
        )
    ]


def test_cancel_backend_uses_pid_and_application_name_guard(monkeypatch):
    conn = _Connection()
    pool = _Pool()
    pool.conn = conn
    pool.getconn = lambda: conn
    monkeypatch.setattr(db, "_get_cancel_pool", lambda: pool)

    assert db.cancel_backend_for_request(777, "abc123") is True

    sql, params = conn.executed[0]
    assert "pg_cancel_backend(pid)" in sql
    assert "application_name = %s" in sql
    assert params == (777, "datasnoop:rid=abc123")
    assert pool.returned == [(conn, False)]
