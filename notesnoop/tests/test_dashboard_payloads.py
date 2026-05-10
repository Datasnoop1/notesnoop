"""Integration smoke tests for the dashboard / review-queue payloads.

Verifies that the slices A-V additions are wired all the way through:
loose_ends + today_counts + pipeline_counts on /home, source_people /
source_companies on /review-queue, linked_via persistence on manual
edits, and assignee_id surfaced on the task payload after the new
assignee picker writes it.
"""

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
        "x-notesnoop-name": "Dashboard Tester",
    }


def test_home_payload_contains_loose_ends_today_counts_and_pipeline_counts(client):
    user_id = f"dash_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Dashboard workspace"}, headers=headers)
    assert boot.status_code == 200
    workspace_id = boot.json()["data"]["workspace"]["id"]

    # Capture a note so today_counts.new_notes > 0 and loose_ends.notes_without_project has it.
    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Apollo follow-up - Morgan to send memo by Friday."},
        headers=headers,
    )
    assert note.status_code == 200

    # Create a person with no company so loose_ends.people_without_company catches it.
    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Quiet Person"},
        headers=headers,
    )
    assert person.status_code == 200

    home = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    assert home.status_code == 200
    data = home.json()["data"]

    # pipeline_counts (slice A): always present, all int keys.
    assert isinstance(data["pipeline_counts"], dict)
    for key in ("received", "processing", "needs_review", "accepted", "failed"):
        assert isinstance(data["pipeline_counts"][key], int)

    # loose_ends (slice G): four keys, three are lists, stale_reviews_count is an int.
    loose = data["loose_ends"]
    assert isinstance(loose, dict)
    assert isinstance(loose["notes_without_project"], list)
    assert isinstance(loose["tasks_without_owner"], list)
    assert isinstance(loose["people_without_company"], list)
    assert isinstance(loose["stale_reviews_count"], int)

    # today_counts (slice V): three int keys.
    today = data["today_counts"]
    assert isinstance(today, dict)
    assert today["new_notes"] >= 1
    assert isinstance(today["tasks_done"], int)
    assert isinstance(today["reviews_accepted"], int)


def test_task_link_writes_linked_via_manual_and_payload_round_trips(client):
    user_id = f"link_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Linked workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Owner Person"},
        headers=headers,
    )
    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Northstar Advisory"},
        headers=headers,
    )
    project_id = project.json()["data"]["id"]
    person_id = person.json()["data"]["id"]
    company_id = company.json()["data"]["id"]

    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Linked through manual UI flow",
            "project_ids": [project_id],
            "person_ids": [person_id],
            "company_ids": [company_id],
            "assignee_id": person_id,
        },
        headers=headers,
    )
    assert task.status_code == 200
    task_data = task.json()["data"]

    for collection in (task_data["projects"], task_data["people"], task_data["companies"]):
        assert all(row.get("linked_via") == "manual" for row in collection)
    assert task_data["assignee_id"] == person_id


def test_company_detail_surfaces_tasks_and_meetings_linked_to_company(client):
    """Verify slice Z: company payload returns tasks + meetings, not just
    people/projects/notes. Lets the company sheet act as a real anchor.
    """
    user_id = f"company_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Company workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Northstar"},
        headers=headers,
    )
    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Alice"},
        headers=headers,
    )
    company_id = company.json()["data"]["id"]
    person_id = person.json()["data"]["id"]

    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={
            "title": "Northstar follow-up",
            "person_ids": [person_id],
            "company_ids": [company_id],
            "assignee_id": person_id,
        },
        headers=headers,
    )
    assert task.status_code == 200
    meeting = client.post(
        f"/api/workspaces/{workspace_id}/meetings",
        json={"title": "Northstar weekly", "company_ids": [company_id]},
        headers=headers,
    )
    assert meeting.status_code == 200

    company_payload = client.get(f"/api/companies/{company_id}", headers=headers)
    assert company_payload.status_code == 200
    data = company_payload.json()["data"]
    assert any(t["title"] == "Northstar follow-up" for t in (data.get("tasks") or []))
    task_row = next(t for t in data["tasks"] if t["title"] == "Northstar follow-up")
    assert task_row["assignee_name"] == "Alice"
    assert any(m["title"] == "Northstar weekly" for m in (data.get("meetings") or []))


def test_end_to_end_capture_review_accept_dashboard_happy_path(client):
    """Drive the full happy path: capture note, seed review queue, accept the
    candidate, then verify the materialized task lives in the dashboard /home
    payload and in the company's tasks list. Closes the user's directive to
    "make sure all functionality actually works".
    """
    from app.db import transaction

    user_id = f"e2e_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "E2E workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    apollo = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    morgan = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Morgan Lee"},
        headers=headers,
    )
    northstar = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Northstar Advisory"},
        headers=headers,
    )
    project_id = apollo.json()["data"]["id"]
    person_id = morgan.json()["data"]["id"]
    company_id = northstar.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={
            "body": "Apollo follow-up — Morgan to send the diligence pack to Northstar by Friday.",
            "project_ids": [project_id],
        },
        headers=headers,
    )
    note_id = note.json()["data"]["id"]

    client.post(
        f"/api/notes/{note_id}/people",
        json={"person_id": person_id, "state": "confirmed", "source": "user"},
        headers=headers,
    )
    with transaction(user_id) as cur:
        cur.execute(
            "INSERT INTO company_notes (company_id, note_id, workspace_id, linked_by) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (company_id, note_id, workspace_id, user_id),
        )
        cur.execute(
            "INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload) VALUES (%s, %s, 'task', %s, 'ai_suggestion', %s::jsonb) RETURNING id",
            (
                workspace_id,
                user_id,
                note_id,
                '{"title":"Send Apollo diligence pack","status":"todo","confidence":0.88,"summary":"Morgan owns this by Friday.","person_names":["Morgan Lee"],"company_names":["Northstar Advisory"]}',
            ),
        )
        review_id = str(cur.fetchone()["id"])

    accept = client.post(f"/api/review-queue/{review_id}/accept", headers=headers, json={})
    assert accept.status_code == 200, accept.text
    accepted = accept.json()["data"]
    assert accepted["state"] == "accepted"
    assert accepted.get("entity_kind") == "task"
    task_id = accepted["entity_id"]

    task_payload = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert task_payload.status_code == 200
    task_data = task_payload.json()["data"]
    assert task_data["title"] == "Send Apollo diligence pack"
    # AI-driven materialization writes linked_via='ai' on every link it created.
    for collection in (task_data["projects"], task_data["people"], task_data["companies"]):
        assert all(row.get("linked_via") == "ai" for row in collection)

    home = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    home_data = home.json()["data"]
    open_titles = [t["title"] for t in home_data.get("open_tasks", [])]
    assert "Send Apollo diligence pack" in open_titles
    accepted_open = next(t for t in home_data["open_tasks"] if t["title"] == "Send Apollo diligence pack")
    assert accepted_open["assignee_name"] == "Morgan Lee"

    company_detail = client.get(f"/api/companies/{company_id}", headers=headers)
    company_tasks = [t["title"] for t in company_detail.json()["data"].get("tasks", [])]
    assert "Send Apollo diligence pack" in company_tasks


def test_note_archive_restore_round_trip(client):
    """Archiving a note hides it from /home recent_notes; restoring brings it back."""
    user_id = f"archive_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Archive workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Test note to archive"},
        headers=headers,
    )
    note_id = note.json()["data"]["id"]

    home_before = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    titles_before = [n["title"] for n in home_before.json()["data"]["recent_notes"]]
    assert any("Test note to archive" in (t or "") for t in titles_before)

    archived = client.post(f"/api/notes/{note_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["data"]["archived"] is True

    home_after = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    titles_after = [n["title"] for n in home_after.json()["data"]["recent_notes"]]
    assert not any("Test note to archive" in (t or "") for t in titles_after)

    restored = client.post(f"/api/notes/{note_id}/restore", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["data"]["archived"] is False

    home_final = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    titles_final = [n["title"] for n in home_final.json()["data"]["recent_notes"]]
    assert any("Test note to archive" in (t or "") for t in titles_final)


def test_review_queue_exposes_source_people_and_source_companies(client):
    """Verify slice D's backend addition: source-note people + companies are surfaced
    on the review-queue list so the Review Sheet can pre-seed its pickers.
    """
    from app.db import transaction

    user_id = f"review_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Review workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Source Person"},
        headers=headers,
    )
    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Source Company"},
        headers=headers,
    )
    person_id = person.json()["data"]["id"]
    company_id = company.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Source note for the review queue picker prefill test."},
        headers=headers,
    )
    note_id = note.json()["data"]["id"]

    # Manually attach the person + company to the note so the join lights up.
    client.post(
        f"/api/notes/{note_id}/people",
        json={"person_id": person_id, "state": "confirmed", "source": "user"},
        headers=headers,
    )
    with transaction(user_id) as cur:
        cur.execute(
            "INSERT INTO company_notes (company_id, note_id, workspace_id, linked_by) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (company_id, note_id, workspace_id, user_id),
        )
        cur.execute(
            "INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload) VALUES (%s, %s, 'task', %s, 'ai_suggestion', %s::jsonb)",
            (workspace_id, user_id, note_id, '{"title":"Prefill candidate","confidence":0.7}'),
        )

    queue = client.get(f"/api/workspaces/{workspace_id}/review-queue", headers=headers)
    assert queue.status_code == 200
    items = queue.json()["data"]
    assert items, "expected at least one review queue row"
    row = items[0]
    assert any(p["id"] == person_id for p in row.get("source_people") or [])
    assert any(c["id"] == company_id for c in row.get("source_companies") or [])


def test_activity_endpoint_returns_recent_events(client):
    """Verify /workspaces/{id}/activity returns chronological events from last 7 days."""
    user_id = f"activity_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Activity workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Activity test note"},
        headers=headers,
    )
    assert note.status_code == 200

    activity = client.get(f"/api/workspaces/{workspace_id}/activity?days=7", headers=headers)
    assert activity.status_code == 200
    rows = activity.json()["data"]
    note_events = [r for r in rows if r["kind"] == "note_created"]
    assert len(note_events) >= 1
    assert any("Activity test note" in (r["title"] or "") for r in note_events)
    assert activity.json()["meta"]["days"] == 7


def test_home_week_counts_aggregate_last_seven_days(client):
    """Verify /home returns week_counts aggregating last 7 days of activity."""
    user_id = f"week_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Week workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    # Capture three notes in the past 7 days (just-created counts)
    for n in range(3):
        client.post(
            f"/api/workspaces/{workspace_id}/notes",
            json={"body": f"Week note {n}"},
            headers=headers,
        )

    home = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    assert home.status_code == 200
    week = home.json()["data"].get("week_counts")
    assert isinstance(week, dict)
    assert week.get("new_notes", 0) >= 3
    for key in ("tasks_done", "reviews_accepted", "notes_archived", "projects_closed"):
        assert key in week


def test_project_close_and_reopen_filters_recent_projects(client):
    """Closing a project hides it from /home recent_projects; reopening brings it back."""
    user_id = f"proj_close_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Close workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    project_create = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Alpha Diligence", "color_hex": "#888888"},
        headers=headers,
    )
    project_id = project_create.json()["data"]["id"]

    # Capture a note so the project shows up in recent_projects
    client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Initial diligence note", "project_ids": [project_id]},
        headers=headers,
    )

    home_before = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    before_ids = [p["id"] for p in home_before.json()["data"]["recent_projects"]]
    assert project_id in before_ids

    closed = client.patch(
        f"/api/projects/{project_id}",
        json={"status": "closed"},
        headers=headers,
    )
    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "closed"
    assert closed.json()["data"]["closed_at"] is not None

    home_after = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    after_ids = [p["id"] for p in home_after.json()["data"]["recent_projects"]]
    assert project_id not in after_ids

    reopened = client.patch(
        f"/api/projects/{project_id}",
        json={"status": "active"},
        headers=headers,
    )
    assert reopened.status_code == 200
    assert reopened.json()["data"]["status"] == "active"
    assert reopened.json()["data"]["closed_at"] is None

    home_final = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    final_ids = [p["id"] for p in home_final.json()["data"]["recent_projects"]]
    assert project_id in final_ids


def test_inbox_project_cannot_be_closed(client):
    """System projects (inbox / personal) refuse status changes with HTTP 400."""
    user_id = f"sys_close_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Sys workspace"}, headers=headers)
    inbox = next(p for p in boot.json()["data"]["projects"] if p["kind"] == "inbox")

    response = client.patch(
        f"/api/projects/{inbox['id']}",
        json={"status": "closed"},
        headers=headers,
    )
    assert response.status_code == 400


def test_triage_endpoint_lists_unprocessed_and_bulk_actions(client):
    """Triage view returns unprocessed notes; bulk-process queues each and bulk-archive hides them."""
    from app.db import transaction

    user_id = f"triage_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "Triage workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    # Set workspace AI to manual so freshly-created notes land in 'skipped' (a
    # legitimate triage-eligible status) instead of immediately flipping to
    # 'processing'.
    with transaction(user_id) as cur:
        cur.execute("UPDATE workspaces SET ai_mode = 'manual' WHERE id = %s", (workspace_id,))

    note_a = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Forwarded diligence note A"},
        headers=headers,
    )
    note_b = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Forwarded diligence note B"},
        headers=headers,
    )
    note_a_id = note_a.json()["data"]["id"]
    note_b_id = note_b.json()["data"]["id"]

    listing = client.get(f"/api/workspaces/{workspace_id}/triage", headers=headers)
    assert listing.status_code == 200
    ids = {row["id"] for row in listing.json()["data"]}
    assert note_a_id in ids and note_b_id in ids

    process = client.post(
        f"/api/workspaces/{workspace_id}/triage/process",
        json={"note_ids": [note_a_id]},
        headers=headers,
    )
    assert process.status_code == 200
    assert note_a_id in process.json()["data"]["queued"]

    archive = client.post(
        f"/api/workspaces/{workspace_id}/triage/archive",
        json={"note_ids": [note_b_id]},
        headers=headers,
    )
    assert archive.status_code == 200
    assert note_b_id in archive.json()["data"]["archived"]

    after = client.get(f"/api/workspaces/{workspace_id}/triage", headers=headers)
    remaining_ids = {row["id"] for row in after.json()["data"]}
    assert note_a_id not in remaining_ids  # advanced to 'processing'
    assert note_b_id not in remaining_ids  # archived
