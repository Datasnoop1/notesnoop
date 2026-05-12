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
        "x-notesnoop-name": "Dependency Tester",
    }


def _make_workspace(client, user_id: str) -> str:
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Deps workspace"}, headers=headers)
    return boot.json()["data"]["workspace"]["id"]


def test_add_and_remove_task_dependency_round_trip(client):
    user_id = f"deps_owner_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    workspace_id = _make_workspace(client, user_id)
    a = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Draft term sheet"},
        headers=headers,
    ).json()["data"]
    b = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Get legal review"},
        headers=headers,
    ).json()["data"]

    # A is blocked by B.
    add = client.post(
        f"/api/tasks/{a['id']}/dependencies",
        json={"blocking_task_id": b["id"]},
        headers=headers,
    )
    assert add.status_code == 200, add.text
    a_after = add.json()["data"]
    assert [row["id"] for row in a_after["blocked_by"]] == [b["id"]]
    assert a_after["blocking"] == []

    # B should report that it's blocking A.
    b_get = client.get(f"/api/tasks/{b['id']}", headers=headers).json()["data"]
    assert [row["id"] for row in b_get["blocking"]] == [a["id"]]
    assert b_get["blocked_by"] == []

    # Adding the same dependency again is a no-op (ON CONFLICT DO NOTHING).
    again = client.post(
        f"/api/tasks/{a['id']}/dependencies",
        json={"blocking_task_id": b["id"]},
        headers=headers,
    )
    assert again.status_code == 200
    assert len(again.json()["data"]["blocked_by"]) == 1

    # Removing the dependency clears it from both sides.
    delete = client.delete(
        f"/api/tasks/{a['id']}/dependencies/{b['id']}",
        headers=headers,
    )
    assert delete.status_code == 200
    assert delete.json()["data"]["blocked_by"] == []
    b_after = client.get(f"/api/tasks/{b['id']}", headers=headers).json()["data"]
    assert b_after["blocking"] == []


def test_task_dependency_rejects_self_and_direct_cycles(client):
    user_id = f"deps_cycle_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    workspace_id = _make_workspace(client, user_id)
    a = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Task A"},
        headers=headers,
    ).json()["data"]
    b = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Task B"},
        headers=headers,
    ).json()["data"]

    self_dep = client.post(
        f"/api/tasks/{a['id']}/dependencies",
        json={"blocking_task_id": a["id"]},
        headers=headers,
    )
    assert self_dep.status_code == 422

    client.post(
        f"/api/tasks/{a['id']}/dependencies",
        json={"blocking_task_id": b["id"]},
        headers=headers,
    )
    cycle = client.post(
        f"/api/tasks/{b['id']}/dependencies",
        json={"blocking_task_id": a["id"]},
        headers=headers,
    )
    assert cycle.status_code == 422


def test_task_dependency_rejects_cross_workspace(client):
    a_user = f"deps_a_{uuid.uuid4().hex[:10]}"
    b_user = f"deps_b_{uuid.uuid4().hex[:10]}"
    a_headers = _headers(a_user)
    b_headers = _headers(b_user)
    a_ws = _make_workspace(client, a_user)
    b_ws = _make_workspace(client, b_user)
    a_task = client.post(
        f"/api/workspaces/{a_ws}/tasks", json={"title": "A task"}, headers=a_headers,
    ).json()["data"]
    b_task = client.post(
        f"/api/workspaces/{b_ws}/tasks", json={"title": "B task"}, headers=b_headers,
    ).json()["data"]
    resp = client.post(
        f"/api/tasks/{a_task['id']}/dependencies",
        json={"blocking_task_id": b_task["id"]},
        headers=a_headers,
    )
    # Either 422 (workspace mismatch) or 404 (RLS hides the task) is acceptable;
    # both are correct denial responses for "you can't link these".
    assert resp.status_code in (404, 422)
