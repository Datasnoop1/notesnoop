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
        "x-notesnoop-name": "Reminder Tester",
    }


def test_task_reminder_lifecycle_and_active_uniqueness(client):
    suffix = uuid.uuid4().hex[:10]
    headers = _headers(f"reminders_{suffix}")

    boot = client.post("/api/bootstrap", json={"workspace_name": "Reminder workspace"}, headers=headers)
    assert boot.status_code == 200
    workspace_id = boot.json()["data"]["workspace"]["id"]

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Send Apollo reminder proof",
            "due_at": "2026-05-15T12:00:00Z",
            "project_ids": [project_id],
        },
        headers=headers,
    )
    assert task.status_code == 200
    task_id = task.json()["data"]["id"]

    reminders = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers)
    assert reminders.status_code == 200
    active = [row for row in reminders.json()["data"] if row["task_id"] == task_id]
    assert len(active) == 1
    reminder_id = active[0]["id"]

    snoozed = client.patch(
        f"/api/task-reminders/{reminder_id}",
        json={"state": "snoozed", "snoozed_until": "2026-05-16T09:00:00Z"},
        headers=headers,
    )
    assert snoozed.status_code == 200
    assert snoozed.json()["data"]["state"] == "snoozed"

    changed_due = client.patch(
        f"/api/tasks/{task_id}",
        json={"due_at": "2026-05-20T12:00:00Z"},
        headers=headers,
    )
    assert changed_due.status_code == 200
    changed_rows = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers).json()["data"]
    active_after_due_change = [row for row in changed_rows if row["task_id"] == task_id]
    assert len(active_after_due_change) == 1
    assert active_after_due_change[0]["id"] == reminder_id
    assert active_after_due_change[0]["state"] == "pending"
    assert active_after_due_change[0]["remind_at"].startswith("2026-05-20T12:00:00")

    dismissed = client.patch(f"/api/task-reminders/{reminder_id}", json={"state": "dismissed"}, headers=headers)
    assert dismissed.status_code == 200
    rows_after_dismiss = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers).json()["data"]
    assert not [row for row in rows_after_dismiss if row["id"] == reminder_id]

    revived = client.patch(
        f"/api/tasks/{task_id}",
        json={"due_at": "2026-05-21T12:00:00Z"},
        headers=headers,
    )
    assert revived.status_code == 200
    revived_rows = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers).json()["data"]
    assert len([row for row in revived_rows if row["task_id"] == task_id]) == 1

    cleared = client.patch(f"/api/tasks/{task_id}", json={"due_at": None}, headers=headers)
    assert cleared.status_code == 200
    rows_after_clear = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers).json()["data"]
    assert not [row for row in rows_after_clear if row["task_id"] == task_id]

    redated = client.patch(
        f"/api/tasks/{task_id}",
        json={"due_at": "2026-05-22T12:00:00Z"},
        headers=headers,
    )
    assert redated.status_code == 200
    done = client.patch(f"/api/tasks/{task_id}", json={"status": "done"}, headers=headers)
    assert done.status_code == 200
    rows_after_done = client.get(f"/api/workspaces/{workspace_id}/reminders", headers=headers).json()["data"]
    assert not [row for row in rows_after_done if row["task_id"] == task_id]
