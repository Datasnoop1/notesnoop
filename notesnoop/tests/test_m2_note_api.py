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
        "x-notesnoop-name": "M2 Tester",
    }


def _insert_inbox_project(workspace_id: str, user_id: str, *, shared: bool) -> str:
    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (workspace_id, name, kind, color_hex, shared, created_by)
                VALUES (%s, 'Inbox', 'inbox', '#0f766e', %s, %s)
                RETURNING id
                """,
                (workspace_id, shared, user_id),
            )
            project_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO project_members (project_id, clerk_user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (project_id, user_id),
            )
    return project_id


def _project_ids(payload: dict, kind: str) -> list[str]:
    return [project["id"] for project in payload["projects"] if project["kind"] == kind]


def test_note_versions_project_nudge_and_personal_project_block(client):
    user_id = f"m2_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M2 workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    personal_id = next(project["id"] for project in state["projects"] if project["kind"] == "personal")

    apollo = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    assert apollo.status_code == 200
    apollo_id = apollo.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Apollo follow-up\nTalk to Morgan about the diligence memo."},
        headers=headers,
    )
    assert note.status_code == 200
    note_data = note.json()["data"]
    note_id = note_data["id"]
    assert note_data["project_nudge"]["inbox_only"] is True
    assert [project["name"] for project in note_data["project_nudge"]["matched_projects"]] == ["Apollo"]
    assert [version["version"] for version in note_data["versions"]] == [1]

    updated = client.patch(
        f"/api/notes/{note_id}",
        json={"body": "Apollo revised follow-up\nSend the memo after IC."},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "Apollo revised follow-up"

    versions = client.get(f"/api/notes/{note_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert [row["version"] for row in versions.json()["data"]] == [2, 1]

    moved = client.put(
        f"/api/notes/{note_id}/projects",
        json={"project_ids": [apollo_id]},
        headers=headers,
    )
    assert moved.status_code == 200
    moved_data = moved.json()["data"]
    assert [project["name"] for project in moved_data["projects"]] == ["Apollo"]
    assert moved_data["project_nudge"]["inbox_only"] is False

    personal_note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Private compensation note", "project_ids": [personal_id]},
        headers=headers,
    )
    assert personal_note.status_code == 200
    personal_note_id = personal_note.json()["data"]["id"]

    mixed = client.put(
        f"/api/notes/{personal_note_id}/projects",
        json={"project_ids": [personal_id, apollo_id]},
        headers=headers,
    )
    assert mixed.status_code == 422

    blocked_move = client.put(
        f"/api/notes/{personal_note_id}/projects",
        json={"project_ids": [apollo_id]},
        headers=headers,
    )
    assert blocked_move.status_code == 409

    confirmed_move = client.put(
        f"/api/notes/{personal_note_id}/projects",
        json={"project_ids": [apollo_id], "confirm_personal_move": True},
        headers=headers,
    )
    assert confirmed_move.status_code == 200
    assert confirmed_move.json()["data"]["is_personal"] is False


def test_private_workspace_hides_stale_shared_inbox_and_captures_to_private_inbox(client):
    user_id = f"m2_private_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M2 private inbox workspace", "inbox_mode": "per_user_private"},
        headers=headers,
    )
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    private_inbox_id = next(project["id"] for project in state["projects"] if project["kind"] == "inbox")

    stale_shared_inbox_id = _insert_inbox_project(workspace_id, user_id, shared=True)

    refreshed = client.get(f"/api/me?workspace_id={workspace_id}", headers=headers)
    assert refreshed.status_code == 200
    assert _project_ids(refreshed.json()["data"], "inbox") == [private_inbox_id]

    listed = client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers)
    assert listed.status_code == 200
    listed_inboxes = [project["id"] for project in listed.json()["data"] if project["kind"] == "inbox"]
    assert listed_inboxes == [private_inbox_id]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Private inbox capture should not land in the stale shared inbox."},
        headers=headers,
    )
    assert note.status_code == 200
    linked_project_ids = {project["id"] for project in note.json()["data"]["projects"]}
    assert private_inbox_id in linked_project_ids
    assert stale_shared_inbox_id not in linked_project_ids


def test_shared_workspace_uses_shared_inbox_even_when_private_inbox_exists(client):
    user_id = f"m2_shared_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M2 shared inbox workspace", "inbox_mode": "shared"},
        headers=headers,
    )
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    shared_inbox_id = next(project["id"] for project in state["projects"] if project["kind"] == "inbox")

    stale_private_inbox_id = _insert_inbox_project(workspace_id, user_id, shared=False)

    refreshed = client.get(f"/api/me?workspace_id={workspace_id}", headers=headers)
    assert refreshed.status_code == 200
    assert _project_ids(refreshed.json()["data"], "inbox") == [shared_inbox_id]

    listed = client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers)
    assert listed.status_code == 200
    listed_inboxes = [project["id"] for project in listed.json()["data"] if project["kind"] == "inbox"]
    assert listed_inboxes == [shared_inbox_id]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Shared inbox capture should ignore an old private inbox."},
        headers=headers,
    )
    assert note.status_code == 200
    linked_project_ids = {project["id"] for project in note.json()["data"]["projects"]}
    assert shared_inbox_id in linked_project_ids
    assert stale_private_inbox_id not in linked_project_ids

    explicit_stale = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Explicit stale private inbox should be rejected.", "project_ids": [stale_private_inbox_id]},
        headers=headers,
    )
    assert explicit_stale.status_code == 422

    linked_note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Shared inbox relink source note.", "project_ids": [shared_inbox_id]},
        headers=headers,
    )
    assert linked_note.status_code == 200
    relinked = client.put(
        f"/api/notes/{linked_note.json()['data']['id']}/projects",
        json={"project_ids": [stale_private_inbox_id]},
        headers=headers,
    )
    assert relinked.status_code == 422


def test_shared_workspace_invite_accepts_existing_shared_inbox(client):
    suffix = uuid.uuid4().hex[:10]
    owner_id = f"m2_owner_{suffix}"
    peer_id = f"m2_peer_{suffix}"
    owner_headers = _headers(owner_id)
    peer_headers = _headers(peer_id)

    boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M2 shared invite workspace", "inbox_mode": "shared"},
        headers=owner_headers,
    )
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    shared_inbox_id = next(project["id"] for project in state["projects"] if project["kind"] == "inbox")

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Shared Invite Project"},
        headers=owner_headers,
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    invite = client.post(
        f"/api/projects/{project_id}/invites",
        json={"email": peer_headers["x-notesnoop-email"]},
        headers=owner_headers,
    )
    assert invite.status_code == 200

    accepted = client.get("/api/me", headers=peer_headers)
    assert accepted.status_code == 200
    accepted_data = accepted.json()["data"]
    assert accepted_data["workspace"]["id"] == workspace_id
    assert _project_ids(accepted_data, "inbox") == [shared_inbox_id]
