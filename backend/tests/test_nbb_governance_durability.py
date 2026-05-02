import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import nbb_governance  # noqa: E402


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))

    def close(self):
        self.conn.closed += 1


class FakeConn:
    def __init__(self):
        self.statements = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_record_governance_success_marks_ok(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(nbb_governance, "_governance_load_log_table_exists", lambda _cur: True)

    nbb_governance.record_governance_load_success(
        conn,
        "0403170701",
        "2024-00000001",
        {"administrators": 2, "shareholders": 1},
    )

    assert conn.commits == 1
    assert conn.rollbacks == 0
    sql, params = conn.statements[0]
    assert "INSERT INTO governance_load_log" in sql
    assert "status = 'ok'" in sql
    assert params[0:2] == ("0403170701", "2024-00000001")
    assert '"administrators": 2' in params[2]


def test_record_governance_failure_increments_retry(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(nbb_governance, "_governance_load_log_table_exists", lambda _cur: True)

    nbb_governance.record_governance_load_failure(
        conn,
        "0403170701",
        "2024-00000001",
        RuntimeError("boom"),
    )

    assert conn.commits == 1
    assert conn.rollbacks == 0
    sql, params = conn.statements[0]
    assert "status = 'error'" in sql
    assert "attempts = governance_load_log.attempts + 1" in sql
    assert params == ("0403170701", "2024-00000001", "boom")


def test_record_governance_skips_before_migration(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(nbb_governance, "_governance_load_log_table_exists", lambda _cur: False)

    nbb_governance.record_governance_load_failure(conn, "0403170701", "2024-00000001", "boom")

    assert conn.statements == []
    assert conn.commits == 0
    assert conn.rollbacks == 0
