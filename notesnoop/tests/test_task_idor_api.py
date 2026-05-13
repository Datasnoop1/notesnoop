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
    import psycopg2
    from fastapi.testclient import TestClient

    os.environ.setdefault("NOTESNOOP_DATABASE_URL", DATABASE_URL)
    os.environ["NOTESNOOP_DEV_AUTH"] = "true"
    sys.path.insert(0, str(ROOT / "notesnoop-backend"))

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
        "x-notesnoop-name": "Task IDOR Tester",
    }


def _count(sql: str, params: tuple) -> int:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return int(cur.fetchone()[0])


def _execute(sql: str, params: tuple) -> None:
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def test_task_endpoints_reject_cross_workspace_idor_and_link_injection(client):
    suffix = uuid.uuid4().hex[:10]
    owner = f"task_idor_owner_{suffix}"
    attacker = f"task_idor_attacker_{suffix}"
    owner_headers = _headers(owner)
    attacker_headers = _headers(attacker)

    owner_boot = client.post("/api/bootstrap", json={"workspace_name": f"Owner {suffix}"}, headers=owner_headers)
    attacker_boot = client.post("/api/bootstrap", json={"workspace_name": f"Attacker {suffix}"}, headers=attacker_headers)
    assert owner_boot.status_code == 200
    assert attacker_boot.status_code == 200
    owner_workspace = owner_boot.json()["data"]["workspace"]["id"]
    attacker_workspace = attacker_boot.json()["data"]["workspace"]["id"]

    owner_person = client.post(
        f"/api/workspaces/{owner_workspace}/people",
        json={"name": f"Owner Person {suffix}"},
        headers=owner_headers,
    ).json()["data"]
    attacker_person = client.post(
        f"/api/workspaces/{attacker_workspace}/people",
        json={"name": f"Attacker Person {suffix}"},
        headers=attacker_headers,
    ).json()["data"]
    attacker_project = client.post(
        f"/api/workspaces/{attacker_workspace}/projects",
        json={"name": f"Attacker Project {suffix}"},
        headers=attacker_headers,
    ).json()["data"]
    attacker_company = client.post(
        f"/api/workspaces/{attacker_workspace}/companies",
        json={"name": f"Attacker Company {suffix}"},
        headers=attacker_headers,
    ).json()["data"]
    attacker_note = client.post(
        f"/api/workspaces/{attacker_workspace}/notes",
        json={"body": f"Attacker note {suffix}"},
        headers=attacker_headers,
    ).json()["data"]

    owner_task = client.post(
        f"/api/workspaces/{owner_workspace}/tasks",
        json={
            "title": f"Owner task {suffix}",
            "person_ids": [owner_person["id"]],
            "assignee_id": owner_person["id"],
        },
        headers=owner_headers,
    ).json()["data"]
    attacker_task = client.post(
        f"/api/workspaces/{attacker_workspace}/tasks",
        json={"title": f"Attacker task {suffix}"},
        headers=attacker_headers,
    ).json()["data"]
    owner_reminder = client.post(
        f"/api/tasks/{owner_task['id']}/reminders",
        json={"remind_at": "2099-06-15T09:00:00Z"},
        headers=owner_headers,
    ).json()["data"]

    list_tasks = client.get(f"/api/workspaces/{owner_workspace}/tasks", headers=attacker_headers)
    assert list_tasks.status_code == 404
    assert client.get(f"/api/tasks/{owner_task['id']}", headers=attacker_headers).status_code == 404
    assert client.get(f"/api/tasks/{owner_task['id']}/comments", headers=attacker_headers).status_code == 404
    assert client.get(f"/api/workspaces/{owner_workspace}/reminders", headers=attacker_headers).status_code == 404

    patched = client.patch(
        f"/api/tasks/{owner_task['id']}",
        json={"title": f"Compromised {suffix}"},
        headers=attacker_headers,
    )
    assert patched.status_code == 404
    assert client.get(f"/api/tasks/{owner_task['id']}", headers=owner_headers).json()["data"]["title"] == owner_task["title"]

    seeded_owner_task = client.post(
        f"/api/workspaces/{owner_workspace}/tasks",
        json={"title": f"Seeded owner task {suffix}"},
        headers=owner_headers,
    ).json()["data"]
    _execute(
        """
        INSERT INTO task_people (task_id, person_id, workspace_id, relation, linked_by)
        VALUES (%s, %s, %s, 'assignee', %s)
        ON CONFLICT DO NOTHING
        """,
        (seeded_owner_task["id"], attacker_person["id"], owner_workspace, owner),
    )
    seeded_payload = client.get(f"/api/tasks/{seeded_owner_task['id']}", headers=owner_headers).json()["data"]
    assert seeded_payload["people"] == []
    assert seeded_payload["assignee_id"] is None
    assert seeded_payload["assignee_name"] is None

    injected_links = client.patch(
        f"/api/tasks/{owner_task['id']}",
        json={
            "project_ids": [attacker_project["id"]],
            "person_ids": [attacker_person["id"]],
            "assignee_id": attacker_person["id"],
            "company_ids": [attacker_company["id"]],
            "note_ids": [attacker_note["id"]],
        },
        headers=owner_headers,
    )
    assert injected_links.status_code == 422

    comment = client.post(
        f"/api/tasks/{owner_task['id']}/comments",
        json={"body": "cross-workspace comment"},
        headers=attacker_headers,
    )
    assert comment.status_code == 404
    assert _count("SELECT count(*) FROM task_comments WHERE task_id = %s", (owner_task["id"],)) == 0

    reminder_create = client.post(
        f"/api/tasks/{owner_task['id']}/reminders",
        json={"remind_at": "2099-07-15T09:00:00Z"},
        headers=attacker_headers,
    )
    assert reminder_create.status_code == 404

    reminder_patch = client.patch(
        f"/api/task-reminders/{owner_reminder['id']}",
        json={"state": "dismissed"},
        headers=attacker_headers,
    )
    assert reminder_patch.status_code == 404
    owner_task_after = client.get(f"/api/tasks/{owner_task['id']}", headers=owner_headers).json()["data"]
    assert owner_task_after["reminders"][0]["state"] == "pending"

    dependency = client.post(
        f"/api/tasks/{owner_task['id']}/dependencies",
        json={"blocking_task_id": attacker_task["id"]},
        headers=owner_headers,
    )
    assert dependency.status_code == 404
    assert _count(
        "SELECT count(*) FROM task_dependencies WHERE blocked_task_id = %s OR blocking_task_id = %s",
        (owner_task["id"], owner_task["id"]),
    ) == 0

    delete_dependency = client.delete(
        f"/api/tasks/{owner_task['id']}/dependencies/{attacker_task['id']}",
        headers=owner_headers,
    )
    assert delete_dependency.status_code == 404


def test_task_links_reject_same_workspace_inaccessible_resources(client):
    suffix = uuid.uuid4().hex[:10]
    owner = f"task_scoped_owner_{suffix}"
    member = f"task_scoped_member_{suffix}"
    owner_headers = _headers(owner)
    member_headers = _headers(member)

    owner_boot = client.post("/api/bootstrap", json={"workspace_name": f"Scoped Owner {suffix}"}, headers=owner_headers)
    member_boot = client.post("/api/bootstrap", json={"workspace_name": f"Scoped Member {suffix}"}, headers=member_headers)
    assert owner_boot.status_code == 200
    assert member_boot.status_code == 200
    workspace_id = owner_boot.json()["data"]["workspace"]["id"]

    _execute(
        """
        INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
        VALUES (%s, %s, 'member')
        ON CONFLICT DO NOTHING
        """,
        (workspace_id, member),
    )

    hidden_project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": f"Hidden Project {suffix}"},
        headers=owner_headers,
    ).json()["data"]
    hidden_company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": f"Hidden Company {suffix}"},
        headers=owner_headers,
    ).json()["data"]
    hidden_note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": f"Hidden project note {suffix}", "project_ids": [hidden_project["id"]]},
        headers=owner_headers,
    ).json()["data"]
    member_task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": f"Member task {suffix}"},
        headers=member_headers,
    ).json()["data"]

    for payload in (
        {"project_ids": [hidden_project["id"]]},
        {"company_ids": [hidden_company["id"]]},
        {"note_ids": [hidden_note["id"]]},
    ):
        created = client.post(
            f"/api/workspaces/{workspace_id}/tasks",
            json={"title": f"Injected create {uuid.uuid4().hex[:6]}", **payload},
            headers=member_headers,
        )
        assert created.status_code == 422
        patched = client.patch(f"/api/tasks/{member_task['id']}", json=payload, headers=member_headers)
        assert patched.status_code == 422

    _execute(
        """
        INSERT INTO task_projects (task_id, project_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (member_task["id"], hidden_project["id"], workspace_id, member),
    )
    _execute(
        """
        INSERT INTO task_companies (task_id, company_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (member_task["id"], hidden_company["id"], workspace_id, member),
    )
    _execute(
        """
        INSERT INTO task_notes (task_id, note_id, workspace_id, linked_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (member_task["id"], hidden_note["id"], workspace_id, member),
    )
    detail = client.get(f"/api/tasks/{member_task['id']}", headers=member_headers)
    assert detail.status_code == 200
    payload = detail.json()["data"]
    assert payload["projects"] == []
    assert payload["companies"] == []
    assert payload["notes"] == []
    filtered_tasks = client.get(
        f"/api/workspaces/{workspace_id}/tasks",
        params={"project_id": hidden_project["id"]},
        headers=member_headers,
    )
    assert filtered_tasks.status_code == 422

    reminder = client.post(
        f"/api/tasks/{member_task['id']}/reminders",
        json={"remind_at": "2099-08-15T09:00:00Z"},
        headers=member_headers,
    )
    assert reminder.status_code == 200
    assert reminder.json()["data"]["projects"] == []
    patched_reminder = client.patch(
        f"/api/task-reminders/{reminder.json()['data']['id']}",
        json={"state": "snoozed", "snoozed_until": "2099-08-16T09:00:00Z"},
        headers=member_headers,
    )
    assert patched_reminder.status_code == 200
    assert patched_reminder.json()["data"]["projects"] == []
    filtered_reminders = client.get(
        f"/api/workspaces/{workspace_id}/reminders",
        params={"project_id": hidden_project["id"]},
        headers=member_headers,
    )
    assert filtered_reminders.status_code == 422
