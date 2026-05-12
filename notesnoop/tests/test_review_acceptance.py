from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))

from app.auth import CurrentUser
from app.routers import graph
from app.schemas import ReviewBulkAccept, ReviewDecision


REVIEW_ID = "00000000-0000-0000-0000-000000000110"
SIBLING_REVIEW_ID = "00000000-0000-0000-0000-000000000111"
PROJECT_NEW_ID = "00000000-0000-0000-0000-000000000101"
PROJECT_MERIDIAN_ID = "00000000-0000-0000-0000-000000000102"
PROJECT_INBOX_ID = "00000000-0000-0000-0000-000000000103"
PROJECT_PERSONAL_ID = "00000000-0000-0000-0000-000000000104"
PERSON_EXISTING_ID = "00000000-0000-0000-0000-000000000105"
COMPANY_EXISTING_ID = "00000000-0000-0000-0000-000000000106"


class FakeCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_values:
            return self.fetchall_values.pop(0)
        return []


@contextmanager
def fake_transaction(cur):
    yield cur


def _accept(monkeypatch, cur):
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))
    return graph.accept_review(REVIEW_ID, ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))


def _sql(cur):
    return "\n".join(sql for sql, _params in cur.executed)


def _params_for(cur, fragment):
    return [params for sql, params in cur.executed if fragment in sql]


def test_accept_review_lookup_is_scoped_to_target_user(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Existing Person", "matched_person_id": PERSON_EXISTING_ID, "confidence": 0.91},
    }
    cur = FakeCursor([review, None, {"id": PERSON_EXISTING_ID}])

    _accept(monkeypatch, cur)

    assert _params_for(cur, "target_user_id = %s AND state = 'open'")[0] == (REVIEW_ID, "owner-1")


def test_accept_review_canonicalizes_uuid_aliases_before_lookup():
    cur = FakeCursor(
        fetchone_values=[
            {"id": PERSON_EXISTING_ID},
            {"id": PROJECT_MERIDIAN_ID},
        ]
    )

    assert graph._accepted_person_id(cur, "workspace-1", f"urn:uuid:{PERSON_EXISTING_ID}") == PERSON_EXISTING_ID
    assert graph._propagatable_project_id(cur, "workspace-1", f"urn:uuid:{PROJECT_MERIDIAN_ID}", "owner-1") == PROJECT_MERIDIAN_ID

    assert _params_for(cur, "SELECT id FROM people")[0] == (PERSON_EXISTING_ID, "workspace-1")
    assert _params_for(cur, "JOIN workspaces w ON w.id = p.workspace_id")[0][0] == PROJECT_MERIDIAN_ID


def test_reject_review_lookup_is_scoped_to_target_user(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"title": "Private review", "confidence": 0.73},
    }
    cur = FakeCursor([review])
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    result = graph.reject_review(REVIEW_ID, ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))

    assert result == {"data": {"state": "rejected"}}
    assert _params_for(cur, "target_user_id = %s AND state = 'open'")[0] == (REVIEW_ID, "owner-1")


def test_accept_unknown_person_review_creates_links_and_updates_payload(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "  New Person  ", "confidence": 0.82},
    }
    cur = FakeCursor([review, {"archived_at": None}, {"id": "person-new"}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO people")[0] == ("workspace-1", "New Person", None, None, None, None, "owner-1")
    payload_json, updated_review_id = _params_for(cur, "SET payload = %s::jsonb")[0]
    assert updated_review_id == REVIEW_ID
    assert json.loads(payload_json)["matched_person_id"] == "person-new"
    assert _params_for(cur, "INSERT INTO note_people_links")[0] == ("note-1", "person-new", 0.82, "ai", "owner-1")
    assert _params_for(cur, "SELECT pg_advisory_xact_lock")[0] == ("memory-reconcile:note-1",)
    assert _params_for(cur, "INSERT INTO task_people")[0] == ("person-new", "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO meeting_people")[0] == ("person-new", "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO report_people")[0] == ("person-new", "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO company_people")[0] == ("person-new", "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO workflow_people")[0] == ("person-new", "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO calibration_events")[0] == ("workspace-1", 0.82)


def test_accept_unknown_project_review_creates_membership_links_and_updates_payload(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "project",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "  Apollo  ", "confidence": 0.78},
    }
    cur = FakeCursor([review, {"archived_at": None}, {"id": PROJECT_NEW_ID}, {"id": PROJECT_NEW_ID}, {"id": PROJECT_NEW_ID}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO projects")[0] == ("workspace-1", "Apollo", None, "on", "owner-1")
    assert _params_for(cur, "INSERT INTO project_members")[0] == (PROJECT_NEW_ID, "owner-1")
    payload_json, updated_review_id = _params_for(cur, "SET payload = %s::jsonb")[0]
    assert updated_review_id == REVIEW_ID
    assert json.loads(payload_json)["matched_project_id"] == PROJECT_NEW_ID
    assert _params_for(cur, "SELECT pg_advisory_xact_lock")[0] == ("note-1",)
    assert _params_for(cur, "SELECT pg_advisory_xact_lock")[1] == ("memory-reconcile:note-1",)
    assert _params_for(cur, "INSERT INTO note_projects")[0] == ("note-1", PROJECT_NEW_ID, "owner-1")
    assert _params_for(cur, "INSERT INTO task_projects")[0] == (PROJECT_NEW_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO meeting_projects")[0] == (PROJECT_NEW_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO report_projects")[0] == (PROJECT_NEW_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO company_projects")[0] == (PROJECT_NEW_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO workflow_projects")[0] == (PROJECT_NEW_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO calibration_events")[0] == ("workspace-1", 0.78)


def test_accept_company_review_reconciles_existing_memory_links(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "company",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Northstar", "confidence": 0.84},
    }
    cur = FakeCursor([review])
    monkeypatch.setattr(
        graph,
        "_materialize_review_candidate",
        lambda _cur, _review, _data, _user_id: COMPANY_EXISTING_ID,
    )

    result = _accept(monkeypatch, cur)

    assert result == {
        "data": {"state": "accepted", "entity_kind": "company", "entity_id": COMPANY_EXISTING_ID}
    }
    assert _params_for(cur, "INSERT INTO task_companies")[0] == (COMPANY_EXISTING_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO meeting_companies")[0] == (COMPANY_EXISTING_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO report_companies")[0] == (COMPANY_EXISTING_ID, "owner-1", "note-1", "workspace-1")
    assert _params_for(cur, "INSERT INTO workflow_companies")[0] == (COMPANY_EXISTING_ID, "owner-1", "note-1", "workspace-1")


def test_accept_project_review_updates_open_structured_review_project_context(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "project",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Project Meridian", "matched_project_id": PROJECT_MERIDIAN_ID, "confidence": 0.81},
    }
    cur = FakeCursor(
        [review, {"archived_at": None}, {"id": PROJECT_MERIDIAN_ID}, {"id": PROJECT_MERIDIAN_ID}, {"id": PROJECT_MERIDIAN_ID}],
        [[{"id": SIBLING_REVIEW_ID, "payload": {"title": "Send pricing options", "project_ids": [PROJECT_INBOX_ID]}}]],
    )

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO note_projects")[0] == ("note-1", PROJECT_MERIDIAN_ID, "owner-1")
    assert _params_for(cur, "AND entity_id = %s\n          AND target_user_id = %s")[0] == ("workspace-1", "note-1", "owner-1")
    payload_updates = _params_for(cur, "SET payload = %s::jsonb")
    assert len(payload_updates) == 1
    payload_json, updated_review_id = payload_updates[0]
    assert updated_review_id == SIBLING_REVIEW_ID
    assert json.loads(payload_json)["project_ids"] == [PROJECT_INBOX_ID, PROJECT_MERIDIAN_ID]


def test_accept_personal_project_review_does_not_update_structured_review_context(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "project",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Personal", "matched_project_id": PROJECT_PERSONAL_ID, "confidence": 0.81},
    }
    cur = FakeCursor([review, {"archived_at": None}, None])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert _params_for(cur, "INSERT INTO note_projects") == []
    assert _params_for(cur, "SET payload = %s::jsonb") == []
    assert _params_for(cur, "INSERT INTO task_projects") == []


def test_accept_malformed_project_review_does_not_uuid_crash(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "project",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Malformed", "matched_project_id": "not-a-uuid", "confidence": 0.81},
    }
    cur = FakeCursor([review, {"archived_at": None}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert "JOIN workspaces w ON w.id = p.workspace_id" not in _sql(cur)
    assert _params_for(cur, "INSERT INTO note_projects") == []
    assert _params_for(cur, "INSERT INTO task_projects") == []


def test_accept_malformed_review_id_returns_not_found_without_query(monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    with pytest.raises(graph.HTTPException) as exc:
        graph.accept_review("not-a-uuid", ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))

    assert exc.value.status_code == 404
    assert cur.executed == []


def test_reject_malformed_review_id_returns_not_found_without_query(monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    with pytest.raises(graph.HTTPException) as exc:
        graph.reject_review("not-a-uuid", ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))

    assert exc.value.status_code == 404
    assert cur.executed == []


def test_bulk_accept_malformed_review_id_returns_failure_without_query(monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    result = graph.accept_many_reviews(
        ReviewBulkAccept(review_ids=["not-a-uuid"], materialize=True),
        CurrentUser(clerk_user_id="owner-1"),
    )

    assert result == {
        "data": {
            "accepted": [],
            "failures": [{"review_id": "not-a-uuid", "status_code": 404, "detail": "Review item not found"}],
        }
    }
    assert cur.executed == []


def test_bulk_accept_orders_project_reviews_before_structured_reviews(monkeypatch):
    task_review_id = "00000000-0000-0000-0000-000000000120"
    project_review_id = "00000000-0000-0000-0000-000000000121"
    cur = FakeCursor(
        fetchall_values=[
            [
                {"id": task_review_id, "entity_kind": "task"},
                {"id": project_review_id, "entity_kind": "project"},
            ]
        ],
    )
    calls = []

    def fake_accept(cursor, review_id, user_id, *, materialize=True):
        calls.append((review_id, user_id, materialize))
        return {"state": "accepted", "review_id": review_id, "entity_kind": "task"}

    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))
    monkeypatch.setattr(graph, "_accept_review_in_txn", fake_accept)

    result = graph.accept_many_reviews(
        ReviewBulkAccept(review_ids=[task_review_id, project_review_id], materialize=True),
        CurrentUser(clerk_user_id="owner-1"),
    )

    assert [review_id for review_id, _user_id, _materialize in calls] == [project_review_id, task_review_id]
    assert all(user_id == "owner-1" and materialize for _review_id, user_id, materialize in calls)
    assert result["data"]["failures"] == []
    assert [item["review_id"] for item in result["data"]["accepted"]] == [project_review_id, task_review_id]
    assert _params_for(cur, "FROM review_queue")[0] == ("owner-1", [task_review_id, project_review_id])


def test_accept_matched_review_does_not_create_or_rewrite_payload(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Existing Person", "matched_person_id": PERSON_EXISTING_ID, "confidence": 0.91},
    }
    cur = FakeCursor([review, None, {"id": PERSON_EXISTING_ID}])

    result = _accept(monkeypatch, cur)

    assert result == {"data": {"state": "accepted"}}
    assert "INSERT INTO people" not in _sql(cur)
    assert "SET payload = %s::jsonb" not in _sql(cur)
    assert _params_for(cur, "INSERT INTO note_people_links")[0] == ("note-1", PERSON_EXISTING_ID, 0.91, "ai", "owner-1")


def test_accept_malformed_person_override_does_not_uuid_crash(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "person",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"name": "Existing Person", "confidence": 0.91},
    }
    cur = FakeCursor([review, None])
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    result = graph.accept_review(
        REVIEW_ID,
        ReviewDecision(payload={"matched_person_id": "not-a-uuid"}),
        CurrentUser(clerk_user_id="owner-1"),
    )

    assert result == {"data": {"state": "accepted"}}
    assert "SELECT id FROM people WHERE id = %s" not in _sql(cur)
    assert _params_for(cur, "INSERT INTO note_people_links") == []


def test_accept_archived_source_note_review_blocks_materialization(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {"title": "Stale archived task", "confidence": 0.8},
    }
    cur = FakeCursor([review, {"archived_at": "2026-05-12T12:00:00Z"}])
    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))

    with pytest.raises(graph.HTTPException) as exc:
        graph.accept_review(REVIEW_ID, ReviewDecision(), CurrentUser(clerk_user_id="owner-1"))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Review item is archived"
    assert _params_for(cur, "UPDATE review_queue SET state = 'archived'")[0] == (REVIEW_ID,)
    assert "INSERT INTO calibration_events" not in _sql(cur)


def test_accept_structured_task_review_materializes_edited_payload(monkeypatch):
    review = {
        "id": REVIEW_ID,
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
        "reason": "ai_suggestion",
        "payload": {
            "title": "Send Apollo follow-up",
            "status": "todo",
            "confidence": 0.86,
            "project_ids": ["project-1"],
        },
    }
    cur = FakeCursor([review])
    calls = []

    def fake_materialize(cursor, loaded_review, payload, user_id):
        calls.append((cursor, loaded_review, payload, user_id))
        return "task-created"

    monkeypatch.setattr(graph, "transaction", lambda _user_id: fake_transaction(cur))
    monkeypatch.setattr(graph, "_materialize_review_candidate", fake_materialize)

    result = graph.accept_review(
        REVIEW_ID,
        ReviewDecision(payload={"title": "Send Apollo diligence pack", "due_at": "2026-05-20"}),
        CurrentUser(clerk_user_id="owner-1"),
    )

    assert result == {"data": {"state": "accepted", "entity_kind": "task", "entity_id": "task-created"}}
    assert calls[0][1]["id"] == review["id"]
    assert calls[0][2]["title"] == "Send Apollo diligence pack"
    assert calls[0][2]["status"] == "todo"
    assert calls[0][2]["due_at"] == "2026-05-20"
    assert calls[0][2]["project_ids"] == ["project-1"]
    assert calls[0][3] == "owner-1"
    payload_updates = _params_for(cur, "SET payload = %s::jsonb")
    assert len(payload_updates) == 2
    assert json.loads(payload_updates[-1][0])["materialized_id"] == "task-created"
    assert _params_for(cur, "INSERT INTO calibration_events")[0] == ("workspace-1", 0.86)
