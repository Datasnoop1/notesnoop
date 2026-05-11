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


def _headers(user_id: str, name: str = "Comment Tester") -> dict[str, str]:
    return {
        "x-notesnoop-user-id": user_id,
        "x-notesnoop-email": f"{user_id}@example.test",
        "x-notesnoop-name": name,
    }


def _make_workspace_and_task(client, headers: dict[str, str]) -> tuple[str, str]:
    boot = client.post("/api/bootstrap", json={"workspace_name": "Comments workspace"}, headers=headers)
    assert boot.status_code == 200, boot.text
    workspace_id = boot.json()["data"]["workspace"]["id"]
    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Decide on Apollo memo wording"},
        headers=headers,
    )
    assert task.status_code == 200, task.text
    return workspace_id, task.json()["data"]["id"]


def test_create_list_and_delete_task_comments(client):
    user_id = f"comments_owner_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id, name="Owner User")
    _, task_id = _make_workspace_and_task(client, headers)

    empty = client.get(f"/api/tasks/{task_id}/comments", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["data"] == []

    first = client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": "First pass looks good — waiting on Morgan's input."},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_data = first.json()["data"]
    assert first_data["task_id"] == task_id
    assert first_data["author_user_id"] == user_id
    assert first_data["author_name"] == "Owner User"
    assert first_data["body"].startswith("First pass")

    second = client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": "  Morgan responded: ship it.  "},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["data"]["body"] == "Morgan responded: ship it."

    listed = client.get(f"/api/tasks/{task_id}/comments", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert [row["body"] for row in rows] == [
        "First pass looks good — waiting on Morgan's input.",
        "Morgan responded: ship it.",
    ]
    assert all(row["author_user_id"] == user_id for row in rows)

    removed = client.delete(f"/api/comments/{rows[0]['id']}", headers=headers)
    assert removed.status_code == 200

    remaining = client.get(f"/api/tasks/{task_id}/comments", headers=headers).json()["data"]
    assert len(remaining) == 1
    assert remaining[0]["body"] == "Morgan responded: ship it."


def test_empty_comment_body_rejected(client):
    user_id = f"comments_empty_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    _, task_id = _make_workspace_and_task(client, headers)

    blank = client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": "   "},
        headers=headers,
    )
    assert blank.status_code == 400

    too_short = client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": ""},
        headers=headers,
    )
    assert too_short.status_code == 422  # Pydantic min_length=1


def test_only_author_can_delete_their_comment(client):
    owner_id = f"comments_author_{uuid.uuid4().hex[:10]}"
    intruder_id = f"comments_intruder_{uuid.uuid4().hex[:10]}"
    owner_headers = _headers(owner_id, name="Author")
    intruder_headers = _headers(intruder_id, name="Intruder")
    workspace_id, task_id = _make_workspace_and_task(client, owner_headers)

    posted = client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": "Owner's confidential thought."},
        headers=owner_headers,
    )
    assert posted.status_code == 200
    comment_id = posted.json()["data"]["id"]

    # Intruder is not a workspace member, so they can't see the task at all (RLS).
    intruder_view = client.get(f"/api/tasks/{task_id}/comments", headers=intruder_headers)
    assert intruder_view.status_code == 404

    # Even if the intruder guesses the comment id, they get 404 (RLS hides the row).
    intruder_delete = client.delete(f"/api/comments/{comment_id}", headers=intruder_headers)
    assert intruder_delete.status_code in (403, 404)

    # The comment is still there.
    still_there = client.get(f"/api/tasks/{task_id}/comments", headers=owner_headers).json()["data"]
    assert len(still_there) == 1 and still_there[0]["id"] == comment_id
