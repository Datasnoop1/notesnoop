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
        "x-notesnoop-name": "Assignee Tester",
    }


def test_task_assignee_picker_writes_assignee_and_watcher_roles(client):
    user_id = f"assignee_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Assignee workspace"}, headers=headers)
    assert boot.status_code == 200
    workspace_id = boot.json()["data"]["workspace"]["id"]

    alice = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Alice Owner"},
        headers=headers,
    )
    bob = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Bob Watcher"},
        headers=headers,
    )
    assert alice.status_code == 200 and bob.status_code == 200
    alice_id = alice.json()["data"]["id"]
    bob_id = bob.json()["data"]["id"]

    created = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Send Apollo memo",
            "person_ids": [alice_id, bob_id],
            "assignee_id": alice_id,
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    task_data = created.json()["data"]
    task_id = task_data["id"]
    assert task_data["assignee_id"] == alice_id
    assert task_data["assignee_name"] == "Alice Owner"
    relations_by_id = {row["id"]: row.get("relation") for row in task_data["people"]}
    assert relations_by_id[alice_id] == "assignee"
    assert relations_by_id[bob_id] == "watcher"
    # linked_via must be 'manual' for user-initiated edits.
    via_by_id = {row["id"]: row.get("linked_via") for row in task_data["people"]}
    assert via_by_id[alice_id] == "manual"
    assert via_by_id[bob_id] == "manual"

    reassigned = client.patch(
        f"/api/tasks/{task_id}",
        json={"assignee_id": bob_id, "person_ids": [alice_id, bob_id]},
        headers=headers,
    )
    assert reassigned.status_code == 200
    payload = reassigned.json()["data"]
    assert payload["assignee_id"] == bob_id
    assert payload["assignee_name"] == "Bob Watcher"
    relations_after = {row["id"]: row.get("relation") for row in payload["people"]}
    assert relations_after[bob_id] == "assignee"
    assert relations_after[alice_id] == "watcher"

    cleared = client.patch(
        f"/api/tasks/{task_id}",
        json={"assignee_id": None, "person_ids": [alice_id]},
        headers=headers,
    )
    assert cleared.status_code == 200
    payload2 = cleared.json()["data"]
    # When assignee_id is None and only one person is linked, that person becomes the
    # default assignee (preserves legacy single-link semantics).
    assert payload2["assignee_id"] == alice_id
    assert all(row["id"] == alice_id for row in payload2["people"])
