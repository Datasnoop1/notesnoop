from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))

from app import worker


class FakeCursor:
    def __init__(self, fetchone_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self.cursor_obj = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *_, **__):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_claim_job_reclaims_stale_running_jobs_after_visibility_timeout(monkeypatch):
    cursor = FakeCursor(fetchone_values=[{"id": "job-stale", "attempts": 2}])
    conn = FakeConn(cursor)
    returned = []

    monkeypatch.setattr(worker, "get_conn", lambda: conn)
    monkeypatch.setattr(worker, "put_conn", lambda returned_conn: returned.append(returned_conn))

    job = worker._claim_job()

    assert job == {"id": "job-stale", "attempts": 2}
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert returned == [conn]

    executed_sql = "\n".join(sql for sql, _params in cursor.executed)
    normalized_sql = " ".join(executed_sql.split())
    assert "SET state = 'running', consumed_at = now(), attempts = attempts + 1" in normalized_sql
    assert "state = 'queued' AND (consumed_at IS NULL OR consumed_at <= now())" in normalized_sql
    assert (
        "state = 'running' AND consumed_at IS NOT NULL "
        "AND consumed_at < now() - (visibility_timeout_minutes * interval '1 minute')"
    ) in normalized_sql
    assert "FOR UPDATE SKIP LOCKED" in normalized_sql
