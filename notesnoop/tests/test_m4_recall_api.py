from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest


ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("NOTESNOOP_TEST_DATABASE_URL") or os.getenv("MIGRATE_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NOTESNOOP_TEST_DATABASE_URL or MIGRATE_DATABASE_URL is required",
)

if DATABASE_URL:
    os.environ.setdefault("NOTESNOOP_DATABASE_URL", DATABASE_URL)
    os.environ["NOTESNOOP_DEV_AUTH"] = "true"
    sys.path.insert(0, str(ROOT / "notesnoop-backend"))
    from fastapi.testclient import TestClient

    from app.main import app


def _run_migrations() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "notesnoop" / "migrate.py"), "up", "--target=ci"],
        cwd=ROOT,
        env={**os.environ, "NOTESNOOP_TEST_DATABASE_URL": DATABASE_URL or ""},
        check=True,
    )


@pytest.fixture(scope="module")
def client():
    _run_migrations()
    with TestClient(app) as test_client:
        yield test_client


def _headers(user_id: str) -> dict[str, str]:
    return {
        "x-notesnoop-user-id": user_id,
        "x-notesnoop-email": f"{user_id}@example.test",
        "x-notesnoop-name": "M4 Tester",
    }


def test_m4_structured_search_timelines_and_collaboration_signals(client):
    suffix = uuid.uuid4().hex[:10]
    user_id = f"m4_user_{suffix}"
    peer_id = f"m4_peer_{suffix}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M4 workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]

    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Morgan Lee", "company": "Northstar"},
        headers=headers,
    )
    assert person.status_code == 200
    person_id = person.json()["data"]["id"]

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    peer_headers = _headers(peer_id)
    invite = client.post(
        f"/api/projects/{project_id}/invites",
        json={"email": peer_headers["x-notesnoop-email"]},
        headers=headers,
    )
    assert invite.status_code == 200
    assert invite.json()["data"]["status"] == "pending"

    accepted = client.get("/api/me", headers=peer_headers)
    assert accepted.status_code == 200
    accepted_data = accepted.json()["data"]
    assert accepted_data["bootstrapped"] is True
    assert accepted_data["workspace"]["id"] == workspace_id
    assert accepted_data["accepted_invites"][0]["project_id"] == project_id

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Apollo quarterly launch memo with Morgan.", "project_ids": [project_id]},
        headers=headers,
    )
    assert note.status_code == 200
    note_id = note.json()["data"]["id"]

    suggested_person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Jordan Kim"},
        headers=peer_headers,
    )
    assert suggested_person.status_code == 200
    suggested_person_id = suggested_person.json()["data"]["id"]

    suggestion = client.post(
        f"/api/notes/{note_id}/people",
        json={"person_id": suggested_person_id, "state": "confirmed", "source": "user", "confidence": 0.88},
        headers=peer_headers,
    )
    assert suggestion.status_code == 200
    assert suggestion.json()["data"]["collaborator_suggestion"] is True
    assert suggested_person_id not in {row["id"] for row in client.get(f"/api/notes/{note_id}", headers=headers).json()["data"]["people"]}

    owner_home = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    assert owner_home.status_code == 200
    routed = next(
        row
        for row in owner_home.json()["data"]["pending_review"]
        if row["reason"] == "collaborator_suggestion" and row["payload"]["person_id"] == suggested_person_id
    )
    assert routed["target_user_id"] == user_id
    accepted_suggestion = client.post(f"/api/review-queue/{routed['id']}/accept", json={}, headers=headers)
    assert accepted_suggestion.status_code == 200
    accepted_people = client.get(f"/api/notes/{note_id}", headers=headers).json()["data"]["people"]
    assert suggested_person_id in {row["id"] for row in accepted_people}

    link = client.post(
        f"/api/notes/{note_id}/people",
        json={"person_id": person_id, "state": "confirmed", "source": "user", "confidence": 0.99},
        headers=headers,
    )
    assert link.status_code == 200
    assert client.post("/api/flags", json={"note_id": note_id}, headers=headers).status_code == 200
    assert client.get(f"/api/notes/{note_id}", headers=headers).status_code == 200
    assert client.get(f"/api/notes/{note_id}", headers=peer_headers).status_code == 200

    other_note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Unrelated memo", "project_ids": [project_id]},
        headers=headers,
    )
    assert other_note.status_code == 200

    filtered = client.get(
        f"/api/workspaces/{workspace_id}/search",
        params={"q": "memo", "person_id": person_id, "flagged_only": "true"},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()["data"]] == [note_id]

    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Prepare Apollo diligence pack",
            "description": "Morgan needs the revised diligence timeline.",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "note_ids": [note_id],
        },
        headers=headers,
    )
    assert task.status_code == 200
    graph_only_task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Project-only Apollo board prep",
            "description": "No source note, still a first-class project memory.",
            "project_ids": [project_id],
            "person_ids": [person_id],
        },
        headers=headers,
    )
    assert graph_only_task.status_code == 200
    graph_only_task_id = graph_only_task.json()["data"]["id"]
    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={
            "name": "Northstar Advisory",
            "description": "Apollo diligence counterparty",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "note_ids": [note_id],
        },
        headers=headers,
    )
    assert company.status_code == 200
    workflow = client.post(
        f"/api/workspaces/{workspace_id}/workflows",
        json={
            "name": "Apollo diligence workflow",
            "description": "Tracks the board prep loop.",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "task_ids": [graph_only_task_id],
        },
        headers=headers,
    )
    assert workflow.status_code == 200
    memory_search = client.get(
        f"/api/workspaces/{workspace_id}/search",
        params={"q": "diligence", "project_id": project_id, "person_id": person_id},
        headers=headers,
    )
    assert memory_search.status_code == 200
    memory_results = {(row["kind"], row["title"]) for row in memory_search.json()["meta"]["memory_results"]}
    assert ("task", "Prepare Apollo diligence pack") in memory_results
    assert ("company", "Northstar Advisory") in memory_results
    note_memory = client.get(f"/api/notes/{note_id}", headers=headers)
    assert note_memory.status_code == 200
    linked_memory = {(row["kind"], row["title"]) for row in note_memory.json()["data"]["memory_links"]}
    assert ("task", "Prepare Apollo diligence pack") in linked_memory
    assert ("company", "Northstar Advisory") in linked_memory
    memory_graph = client.get(
        f"/api/workspaces/{workspace_id}/memory-graph",
        params={"project_id": project_id},
        headers=headers,
    )
    assert memory_graph.status_code == 200
    graph_data = memory_graph.json()["data"]
    graph_nodes = {(row["kind"], row["id"]) for row in graph_data["nodes"]}
    graph_edges = {(row["from_kind"], row["from_id"], row["relation"], row["to_kind"], row["to_id"]) for row in graph_data["edges"]}
    assert ("task", graph_only_task_id) in graph_nodes
    assert ("workflow", workflow.json()["data"]["id"]) in graph_nodes
    assert ("task", graph_only_task_id, "filed_in", "project", project_id) in graph_edges
    assert ("task", graph_only_task_id, "assignee", "person", person_id) in graph_edges
    assert ("workflow", workflow.json()["data"]["id"], "contains", "task", graph_only_task_id) in graph_edges

    recent = client.get(f"/api/workspaces/{workspace_id}/search", params={"q": ""}, headers=headers)
    assert recent.status_code == 200
    assert recent.json()["data"][0]["id"] == note_id

    person_timeline = client.get(f"/api/people/{person_id}/timeline", headers=headers)
    assert person_timeline.status_code == 200
    person_timeline_data = person_timeline.json()["data"]
    assert person_timeline_data["notes"][0]["id"] == note_id
    assert person_timeline_data["projects"][0]["id"] == project_id
    person_events = {(row["kind"], row["title"]) for row in person_timeline_data["events"]}
    assert ("note", "Apollo quarterly launch memo") in person_events
    assert ("task", "Prepare Apollo diligence pack") in person_events

    project_timeline = client.get(f"/api/projects/{project_id}/timeline", headers=headers)
    assert project_timeline.status_code == 200
    timeline_data = project_timeline.json()["data"]
    assert {row["id"] for row in timeline_data["notes"]} >= {note_id}
    timeline_people = {row["id"] for row in timeline_data["people"]}
    assert person_id in timeline_people
    assert suggested_person_id in timeline_people
    project_events = {(row["kind"], row["title"]) for row in timeline_data["events"]}
    assert ("note", "Apollo quarterly launch memo") in project_events
    assert ("task", "Prepare Apollo diligence pack") in project_events

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload)
                VALUES (%s, %s, 'person', %s, 'ai_suggestion', %s::jsonb)
                """,
                (workspace_id, user_id, note_id, '{"name":"Morgan Lee","confidence":0.8}'),
            )

    count = client.get("/api/review-queue/count", params={"workspace_id": workspace_id}, headers=headers)
    assert count.status_code == 200
    assert count.json()["data"]["count"] >= 1

    activity = client.get(f"/api/collaborator-activity/{workspace_id}", headers=headers)
    assert activity.status_code == 200
    assert activity.json()["data"][0]["project_id"] == project_id
    assert activity.json()["data"][0]["active_viewer_count"] == 1

    shared_timeline = client.get(f"/api/projects/{project_id}/timeline", headers=headers)
    assert shared_timeline.status_code == 200
    assert shared_timeline.json()["data"]["members"][1]["clerk_user_id"] == peer_id
    assert shared_timeline.json()["data"]["invites"][0]["status"] == "accepted"
