from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

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
