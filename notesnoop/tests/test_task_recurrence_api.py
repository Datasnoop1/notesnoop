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
        "x-notesnoop-name": "Recurrence Tester",
    }


def test_marking_recurring_task_done_spawns_next_instance(client):
    user_id = f"recur_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Recurrence ws"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Weekly ops"},
        headers=headers,
    ).json()["data"]

    created = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Weekly status review",
            "due_at": "2026-05-15T09:00:00Z",
            "recurrence": "weekly",
            "project_ids": [project["id"]],
        },
        headers=headers,
    ).json()["data"]
    assert created["recurrence"] == "weekly"

    # Mark it done — should spawn a new task one week later with same project link.
    done = client.patch(
        f"/api/tasks/{created['id']}",
        json={"status": "done"},
        headers=headers,
    )
    assert done.status_code == 200

    listed = client.get(
        f"/api/workspaces/{workspace_id}/tasks",
        headers=headers,
    ).json()["data"]
    title_matches = [t for t in listed if t["title"] == "Weekly status review"]
    assert len(title_matches) == 2
    next_instance = next(t for t in title_matches if t["status"] != "done")
    assert next_instance["recurrence"] == "weekly"
    assert next_instance["due_at"].startswith("2026-05-22")
    # Project link carried over.
    project_ids = [p["id"] for p in next_instance.get("projects", [])]
    assert project["id"] in project_ids


def test_non_recurring_task_done_does_not_spawn(client):
    user_id = f"norecur_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Norecur ws"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]
    created = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "One-off task", "due_at": "2026-05-15T09:00:00Z"},
        headers=headers,
    ).json()["data"]
    client.patch(f"/api/tasks/{created['id']}", json={"status": "done"}, headers=headers)
    listed = client.get(f"/api/workspaces/{workspace_id}/tasks", headers=headers).json()["data"]
    matches = [t for t in listed if t["title"] == "One-off task"]
    assert len(matches) == 1


def test_recurring_task_without_due_date_does_not_spawn(client):
    user_id = f"recur_nodue_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Recur nodue"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]
    created = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Floating recurring", "recurrence": "weekly"},
        headers=headers,
    ).json()["data"]
    client.patch(f"/api/tasks/{created['id']}", json={"status": "done"}, headers=headers)
    listed = client.get(f"/api/workspaces/{workspace_id}/tasks", headers=headers).json()["data"]
    matches = [t for t in listed if t["title"] == "Floating recurring"]
    assert len(matches) == 1
