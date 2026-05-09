from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))

from app.auth import CurrentUser
from app.routers import graph
from app.schemas import ReviewDecision


class FakeCursor:
    def __init__(self, fetchone_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None


@contextmanager
def fake_transaction(cur):
    yield cur


def _accept(monkeypatch, cur):
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))
    return graph.accept_review("review-1", ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))


def _sql(cur):
    return "\n".join(sql for sql, _params in cur.executed)


def _params_for(cur, fragment):
    return [params for sql, params in cur.executed if fragment in sql]


def test_accept_unknown_person_review_creates_links_and_updates_payload(monkeypatch):
    review = {
        "id": "review-1",
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "  New Person  ", "confidence": 0.82},
    }
    cur = FakeCursor([review, {"id": "person-new"}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO people")[0] == ("workspace-1", "New Person", None, None, None, None, "owner-1")
    payload_json, updated_review_id = _params_for(cur, "SET payload = %s::jsonb")[0]
    assert updated_review_id == "review-1"
    assert json.loads(payload_json)["matched_person_id"] == "person-new"
    assert _params_for(cur, "INSERT INTO note_people_links")[0] == ("note-1", "person-new", 0.82, "ai", "owner-1")
    assert _params_for(cur, "INSERT INTO calibration_events")[0] == ("workspace-1", 0.82)


def test_accept_unknown_project_review_creates_membership_links_and_updates_payload(monkeypatch):
    review = {
        "id": "review-1",
        "workspace_id": "workspace-1",
        "entity_kind": "project",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "  Apollo  ", "confidence": 0.78},
    }
    cur = FakeCursor([review, {"id": "project-new"}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO projects")[0] == ("workspace-1", "Apollo", None, "on", "owner-1")
    assert _params_for(cur, "INSERT INTO project_members")[0] == ("project-new", "owner-1")
    payload_json, updated_review_id = _params_for(cur, "SET payload = %s::jsonb")[0]
    assert updated_review_id == "review-1"
    assert json.loads(payload_json)["matched_project_id"] == "project-new"
    assert _params_for(cur, "SELECT pg_advisory_xact_lock")[0] == ("note-1",)
    assert _params_for(cur, "INSERT INTO note_projects")[0] == ("note-1", "project-new", "owner-1")
    assert _params_for(cur, "INSERT INTO calibration_events")[0] == ("workspace-1", 0.78)


def test_accept_matched_review_does_not_create_or_rewrite_payload(monkeypatch):
    review = {
        "id": "review-1",
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Existing Person", "matched_person_id": "person-existing", "confidence": 0.91},
    }
    cur = FakeCursor([review])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert "INSERT INTO people" not in _sql(cur)
    assert "SET payload = %s::jsonb" not in _sql(cur)
    assert _params_for(cur, "INSERT INTO note_people_links")[0] == ("note-1", "person-existing", 0.91, "ai", "owner-1")
