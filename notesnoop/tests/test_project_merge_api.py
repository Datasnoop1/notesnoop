from __future__ import annotations

import json
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
        "x-notesnoop-name": "Project Merge Tester",
    }


def test_merge_project_collapses_memory_links_and_review_payloads(client):
    user_id = f"project_merge_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Project merge workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    source = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Meridian duplicate"},
        headers=headers,
    ).json()["data"]
    target = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Meridian"},
        headers=headers,
    ).json()["data"]
    client.patch(
        f"/api/projects/{source['id']}",
        json={"description": "Pilot pricing and board summary work."},
        headers=headers,
    )

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Maya mentioned the Meridian pilot.", "project_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Draft Meridian pricing follow-up", "project_ids": [source["id"], target["id"]]},
        headers=headers,
    ).json()["data"]
    meeting = client.post(
        f"/api/workspaces/{workspace_id}/meetings",
        json={"title": "Meridian pilot sync", "project_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    report = client.post(
        f"/api/workspaces/{workspace_id}/reports",
        json={"title": "Meridian board brief", "project_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    workflow = client.post(
        f"/api/workspaces/{workspace_id}/workflows",
        json={"name": "Meridian procurement loop", "project_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Northstar Robotics", "project_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    flag = client.post("/api/flags", json={"project_id": source["id"]}, headers=headers)
    assert flag.status_code == 200, flag.text

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_queue (
                  workspace_id, target_user_id, entity_kind, entity_id, reason, payload
                )
                VALUES (%s, %s, 'task', %s, 'ai_suggestion', %s::jsonb)
                RETURNING id
                """,
                (
                    workspace_id,
                    user_id,
                    note["id"],
                    json.dumps({
                        "title": "Review project merge payload",
                        "matched_project_id": source["id"],
                        "project_ids": [source["id"], target["id"]],
                    }),
                ),
            )
            review_id = cur.fetchone()["id"]
        conn.commit()

    merge = client.post(
        f"/api/projects/{source['id']}/merge",
        json={"target_project_id": target["id"]},
        headers=headers,
    )
    assert merge.status_code == 200, merge.text
    assert merge.json()["data"]["merged"] is True
    assert merge.json()["data"]["target_project_id"] == target["id"]
    assert merge.json()["data"]["target_project"]["description"] == "Pilot pricing and board summary work."

    projects_after = client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers).json()["data"]
    project_ids = {project["id"] for project in projects_after}
    assert source["id"] not in project_ids
    assert target["id"] in project_ids

    timeline = client.get(f"/api/projects/{target['id']}/timeline", headers=headers).json()["data"]
    assert {row["id"] for row in timeline["notes"]} >= {note["id"]}
    assert {row["id"] for row in timeline["tasks"]} >= {task["id"]}
    assert {row["id"] for row in timeline["meetings"]} >= {meeting["id"]}
    assert {row["id"] for row in timeline["reports"]} >= {report["id"]}
    assert {row["id"] for row in timeline["workflows"]} >= {workflow["id"]}
    assert {row["id"] for row in timeline["companies"]} >= {company["id"]}

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            for table in (
                "note_projects",
                "task_projects",
                "meeting_projects",
                "report_projects",
                "workflow_projects",
                "company_projects",
                "project_members",
            ):
                cur.execute(f"SELECT count(*) AS n FROM {table} WHERE project_id = %s", (source["id"],))
                assert cur.fetchone()["n"] == 0
            cur.execute("SELECT count(*) AS n FROM task_projects WHERE task_id = %s AND project_id = %s", (task["id"], target["id"]))
            assert cur.fetchone()["n"] == 1
            cur.execute("SELECT count(*) AS n FROM flags WHERE project_id = %s", (target["id"],))
            assert cur.fetchone()["n"] == 1
            cur.execute("SELECT payload FROM review_queue WHERE id = %s", (review_id,))
            payload = cur.fetchone()["payload"]
            assert payload["matched_project_id"] == target["id"]
            assert payload["project_ids"] == [target["id"]]


def test_merge_project_rejects_self_target(client):
    user_id = f"project_self_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Project self merge"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]
    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Solo"},
        headers=headers,
    ).json()["data"]

    resp = client.post(
        f"/api/projects/{project['id']}/merge",
        json={"target_project_id": project["id"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_merge_project_rejects_system_and_cross_workspace_targets(client):
    a_user = f"project_a_{uuid.uuid4().hex[:10]}"
    b_user = f"project_b_{uuid.uuid4().hex[:10]}"
    a_headers = _headers(a_user)
    b_headers = _headers(b_user)
    a_boot = client.post("/api/bootstrap", json={"workspace_name": "A"}, headers=a_headers).json()["data"]
    b_boot = client.post("/api/bootstrap", json={"workspace_name": "B"}, headers=b_headers).json()["data"]
    a_ws = a_boot["workspace"]["id"]
    b_ws = b_boot["workspace"]["id"]
    a_project = client.post(
        f"/api/workspaces/{a_ws}/projects",
        json={"name": "A project"},
        headers=a_headers,
    ).json()["data"]
    b_project = client.post(
        f"/api/workspaces/{b_ws}/projects",
        json={"name": "B project"},
        headers=b_headers,
    ).json()["data"]
    a_inbox = next(project for project in a_boot["projects"] if project["kind"] == "inbox")

    system_resp = client.post(
        f"/api/projects/{a_inbox['id']}/merge",
        json={"target_project_id": a_project["id"]},
        headers=a_headers,
    )
    assert system_resp.status_code == 422

    cross_workspace_resp = client.post(
        f"/api/projects/{a_project['id']}/merge",
        json={"target_project_id": b_project["id"]},
        headers=a_headers,
    )
    assert cross_workspace_resp.status_code == 404


def test_merge_project_requires_authority_over_target_project(client):
    owner_id = f"target_owner_{uuid.uuid4().hex[:10]}"
    source_owner_id = f"source_owner_{uuid.uuid4().hex[:10]}"
    source_member_id = f"source_member_{uuid.uuid4().hex[:10]}"
    owner_headers = _headers(owner_id)
    source_headers = _headers(source_owner_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Target authority"}, headers=owner_headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]
    target = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Owner-only target"},
        headers=owner_headers,
    ).json()["data"]

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            for user_id in (source_owner_id, source_member_id):
                cur.execute(
                    """
                    INSERT INTO user_profiles (clerk_user_id, email, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (user_id, f"{user_id}@example.test", user_id),
                )
                cur.execute(
                    """
                    INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
                    VALUES (%s, %s, 'member')
                    ON CONFLICT DO NOTHING
                    """,
                    (workspace_id, user_id),
                )
            cur.execute(
                """
                INSERT INTO projects (workspace_id, name, kind, shared, created_by)
                VALUES (%s, 'Source-owned duplicate', 'user', TRUE, %s)
                RETURNING id
                """,
                (workspace_id, source_owner_id),
            )
            source_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO project_members (project_id, clerk_user_id)
                VALUES (%s, %s), (%s, %s)
                """,
                (source_id, source_owner_id, source_id, source_member_id),
            )
        conn.commit()

    resp = client.post(
        f"/api/projects/{source_id}/merge",
        json={"target_project_id": target["id"]},
        headers=source_headers,
    )
    assert resp.status_code == 403

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT shared FROM projects WHERE id = %s", (target["id"],))
            assert cur.fetchone()["shared"] is False
            cur.execute("SELECT clerk_user_id FROM project_members WHERE project_id = %s", (target["id"],))
            assert {row["clerk_user_id"] for row in cur.fetchall()} == {owner_id}
