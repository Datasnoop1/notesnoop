"""Regression tests for Staatsblad event-search fallback behavior."""

import sys
import os
from pathlib import Path


os.environ.setdefault("SUPABASE_HS256_FALLBACK", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import staatsblad_events  # noqa: E402


def test_short_non_numeric_event_queries_are_skipped():
    assert staatsblad_events._should_search_events_query("ab") is False
    assert staatsblad_events._should_search_events_query(" abc ") is False


def test_useful_event_queries_are_allowed():
    assert staatsblad_events._should_search_events_query("abcd") is True
    assert staatsblad_events._should_search_events_query("0403") is True


class _Col:
    def __init__(self, name: str):
        self.name = name


class _Cursor:
    def __init__(self, *, vector_error: bool = False):
        self.vector_error = vector_error
        self.calls: list[str] = []
        self.description: list[_Col] = []
        self._rows: list[tuple] = []
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append(sql)
        if "JOIN staatsblad_event_embedding" in sql:
            if self.vector_error:
                raise RuntimeError("embedding table unavailable")
            self.description = [_Col("id")]
            self._rows = []
            return
        if "NULL::float AS vec_score" in sql:
            self.description = [
                _Col("id"),
                _Col("enterprise_number"),
                _Col("summary"),
                _Col("company_name"),
                _Col("vec_score"),
                _Col("trgm_score"),
            ]
            self._rows = [
                (
                    42,
                    "0403170701",
                    "Administrator appointment recorded",
                    "Colruyt Group",
                    None,
                    0.72,
                )
            ]
            return
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def fetchall(self):
        return self._rows

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, *, vector_error: bool = False):
        self.vector_error = vector_error
        self.cursors: list[_Cursor] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        cur = _Cursor(vector_error=self.vector_error)
        self.cursors.append(cur)
        return cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_blended_search_falls_back_to_keyword_when_vector_returns_no_rows(monkeypatch):
    conn = _Connection()
    monkeypatch.setattr(staatsblad_events, "get_connection", lambda: conn)
    monkeypatch.setattr(staatsblad_events, "put_connection", lambda _conn: None)

    rows = staatsblad_events._blended_search(
        q="appointment",
        emb=[0.1, 0.2],
        event_type=None,
        since=None,
        enterprise_number=None,
        limit=5,
    )

    assert rows[0]["id"] == 42
    assert rows[0]["company_name"] == "Colruyt Group"
    assert len(conn.cursors) == 1
    assert any("JOIN staatsblad_event_embedding" in sql for sql in conn.cursors[0].calls)
    assert any("NULL::float AS vec_score" in sql for sql in conn.cursors[0].calls)
    assert conn.commits == 1


def test_blended_search_falls_back_to_keyword_when_vector_query_errors(monkeypatch):
    conn = _Connection(vector_error=True)
    monkeypatch.setattr(staatsblad_events, "get_connection", lambda: conn)
    monkeypatch.setattr(staatsblad_events, "put_connection", lambda _conn: None)

    rows = staatsblad_events._blended_search(
        q="appointment",
        emb=[0.1, 0.2],
        event_type=None,
        since=None,
        enterprise_number=None,
        limit=5,
    )

    assert rows[0]["id"] == 42
    assert conn.rollbacks == 1
    assert len(conn.cursors) == 2
    assert any("JOIN staatsblad_event_embedding" in sql for sql in conn.cursors[0].calls)
    assert any("NULL::float AS vec_score" in sql for sql in conn.cursors[1].calls)
    assert conn.commits == 1
