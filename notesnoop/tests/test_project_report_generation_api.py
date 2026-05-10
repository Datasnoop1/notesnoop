from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
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
    from app.routers import memory


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
        "x-notesnoop-name": "Project Report Tester",
    }


def test_project_report_generation_is_scoped_linked_and_counted(client, monkeypatch):
    suffix = uuid.uuid4().hex[:10]
    owner_id = f"report_owner_{suffix}"
    peer_id = f"report_peer_{suffix}"
    owner_headers = _headers(owner_id)
    peer_headers = _headers(peer_id)
    calls = []

    async def fake_generate(project_context, notes, tasks, meetings, reports, variant):
        calls.append(
            {
                "project_id": str(project_context["id"]),
                "notes": [row["id"] for row in notes],
                "tasks": [row["id"] for row in tasks],
                "meetings": [row["id"] for row in meetings],
                "reports": [row["id"] for row in reports],
                "people": [row["id"] for row in project_context["people"]],
                "companies": [row["id"] for row in project_context["companies"]],
                "variant": variant,
            }
        )
        return {"title": "Apollo generated report", "body": "## Executive summary\nGrounded.", "confidence": 0.87}

    monkeypatch.setattr(memory, "generate_project_report", fake_generate)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Report workspace"}, headers=owner_headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    personal_id = next(project["id"] for project in state["projects"] if project["kind"] == "personal")

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo"},
        headers=owner_headers,
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    empty_project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Empty Apollo"},
        headers=owner_headers,
    )
    assert empty_project.status_code == 200
    empty_project_id = empty_project.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Apollo weekly memo with Morgan.", "project_ids": [project_id]},
        headers=owner_headers,
    )
    assert note.status_code == 200
    note_id = note.json()["data"]["id"]

    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Morgan Lee", "company": "Northstar"},
        headers=owner_headers,
    )
    assert person.status_code == 200
    person_id = person.json()["data"]["id"]

    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Confirm Apollo pricing",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "note_ids": [note_id],
        },
        headers=owner_headers,
    )
    assert task.status_code == 200
    task_id = task.json()["data"]["id"]

    meeting = client.post(
        f"/api/workspaces/{workspace_id}/meetings",
        json={
            "title": "Apollo weekly sync",
            "summary": "Covered pricing and diligence blockers.",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "note_ids": [note_id],
        },
        headers=owner_headers,
    )
    assert meeting.status_code == 200
    meeting_id = meeting.json()["data"]["id"]

    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={
            "name": "Northstar Advisory",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "note_ids": [note_id],
        },
        headers=owner_headers,
    )
    assert company.status_code == 200
    company_id = company.json()["data"]["id"]

    prior_report = client.post(
        f"/api/workspaces/{workspace_id}/reports",
        json={
            "title": "Apollo prior report",
            "body": "Previous status and open questions.",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "company_ids": [company_id],
            "note_ids": [note_id],
            "task_ids": [task_id],
            "meeting_ids": [meeting_id],
        },
        headers=owner_headers,
    )
    assert prior_report.status_code == 200
    prior_report_id = prior_report.json()["data"]["id"]

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles (clerk_user_id, email, display_name)
                VALUES (%s, %s, 'Report Peer')
                ON CONFLICT DO NOTHING
                """,
                (peer_id, peer_headers["x-notesnoop-email"]),
            )
            cur.execute(
                """
                INSERT INTO workspace_members (workspace_id, clerk_user_id, role)
                VALUES (%s, %s, 'member')
                ON CONFLICT DO NOTHING
                """,
                (workspace_id, peer_id),
            )

    denied = client.post(f"/api/projects/{project_id}/reports/generate", json={}, headers=peer_headers)
    assert denied.status_code == 404

    personal = client.post(f"/api/projects/{personal_id}/reports/generate", json={}, headers=owner_headers)
    assert personal.status_code == 403

    empty = client.post(f"/api/projects/{empty_project_id}/reports/generate", json={}, headers=owner_headers)
    assert empty.status_code == 422

    generated = client.post(
        f"/api/projects/{project_id}/reports/generate",
        json={"title": "Apollo source report", "variant": "quick"},
        headers=owner_headers,
    )
    assert generated.status_code == 200
    data = generated.json()["data"]
    assert data["title"] == "Apollo source report"
    assert data["body"] == "## Executive summary\nGrounded."
    assert data["generation_confidence"] == 0.87
    assert data["source_counts"] == {
        "projects": 1,
        "notes": 1,
        "tasks": 1,
        "meetings": 1,
        "reports": 1,
        "people": 1,
        "companies": 1,
        "total": 7,
    }
    assert {row["id"] for row in data["projects"]} == {project_id}
    assert {row["id"] for row in data["notes"]} == {note_id}
    assert {row["id"] for row in data["tasks"]} == {task_id}
    assert {row["id"] for row in data["meetings"]} == {meeting_id}
    assert {row["id"] for row in data["source_reports"]} == {prior_report_id}
    assert {row["id"] for row in data["people"]} == {person_id}
    assert {row["id"] for row in data["companies"]} == {company_id}
    fetched = client.get(f"/api/reports/{data['id']}", headers=owner_headers)
    assert fetched.status_code == 200
    fetched_data = fetched.json()["data"]
    assert fetched_data["title"] == "Apollo source report"
    assert {row["id"] for row in fetched_data["projects"]} == {project_id}
    assert {row["id"] for row in fetched_data["tasks"]} == {task_id}
    assert {row["id"] for row in fetched_data["meetings"]} == {meeting_id}
    assert {row["id"] for row in fetched_data["source_reports"]} == {prior_report_id}
    assert {row["id"] for row in fetched_data["companies"]} == {company_id}
    assert calls == [
        {
            "project_id": project_id,
            "notes": [note_id],
            "tasks": [task_id],
            "meetings": [meeting_id],
            "reports": [prior_report_id],
            "people": [person_id],
            "companies": [company_id],
            "variant": "quick",
        }
    ]
