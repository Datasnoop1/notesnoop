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

    recent = client.get(f"/api/workspaces/{workspace_id}/search", params={"q": ""}, headers=headers)
    assert recent.status_code == 200
    assert recent.json()["data"][0]["id"] == note_id

    person_timeline = client.get(f"/api/people/{person_id}/timeline", headers=headers)
    assert person_timeline.status_code == 200
    assert person_timeline.json()["data"]["notes"][0]["id"] == note_id
    assert person_timeline.json()["data"]["projects"][0]["id"] == project_id

    project_timeline = client.get(f"/api/projects/{project_id}/timeline", headers=headers)
    assert project_timeline.status_code == 200
    timeline_data = project_timeline.json()["data"]
    assert {row["id"] for row in timeline_data["notes"]} >= {note_id}
    assert timeline_data["people"][0]["id"] == person_id

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
