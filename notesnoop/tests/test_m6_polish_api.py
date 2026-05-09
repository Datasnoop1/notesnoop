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
        "x-notesnoop-name": "M6 Tester",
    }


def test_m6_merge_undo_flags_and_brief_safeguards(client):
    suffix = uuid.uuid4().hex[:10]
    user_id = f"m6_user_{suffix}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M6 workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    personal_id = next(project["id"] for project in state["projects"] if project["kind"] == "personal")

    project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Apollo", "color_hex": "#e85d4f"},
        headers=headers,
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]

    source = client.post(f"/api/workspaces/{workspace_id}/people", json={"name": "J. Smith"}, headers=headers)
    target = client.post(f"/api/workspaces/{workspace_id}/people", json={"name": "John Smith"}, headers=headers)
    assert source.status_code == target.status_code == 200
    source_id = source.json()["data"]["id"]
    target_id = target.json()["data"]["id"]

    note_source = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"title": "Source note", "body": "J. Smith source note body", "project_ids": [project_id]},
        headers=headers,
    )
    note_target = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"title": "Target note", "body": "John Smith target note body", "project_ids": [project_id]},
        headers=headers,
    )
    assert note_source.status_code == note_target.status_code == 200
    note_source_id = note_source.json()["data"]["id"]
    note_target_id = note_target.json()["data"]["id"]

    assert client.post(
        f"/api/notes/{note_source_id}/people",
        json={"person_id": source_id, "state": "confirmed", "source": "user"},
        headers=headers,
    ).status_code == 200
    assert client.post(
        f"/api/notes/{note_target_id}/people",
        json={"person_id": target_id, "state": "confirmed", "source": "user"},
        headers=headers,
    ).status_code == 200

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload)
                VALUES (%s, %s, 'person', %s, 'ai_suggestion', %s::jsonb)
                """,
                (workspace_id, user_id, note_source_id, f'{{"matched_person_id":"{source_id}","confidence":0.8}}'),
            )

    merged = client.post(
        f"/api/people/{source_id}/merge",
        json={"target_person_id": target_id},
        headers=headers,
    )
    assert merged.status_code == 200
    undo_id = merged.json()["data"]["undo_id"]
    assert client.get(f"/api/people/{source_id}/timeline", headers=headers).status_code == 404
    merged_timeline = client.get(f"/api/people/{target_id}/timeline", headers=headers)
    assert {note["id"] for note in merged_timeline.json()["data"]["notes"]} >= {note_source_id, note_target_id}

    undone = client.post(f"/api/person-merges/{undo_id}/undo", headers=headers)
    assert undone.status_code == 200
    source_timeline = client.get(f"/api/people/{source_id}/timeline", headers=headers).json()["data"]
    target_timeline = client.get(f"/api/people/{target_id}/timeline", headers=headers).json()["data"]
    assert {note["id"] for note in source_timeline["notes"]} == {note_source_id}
    assert {note["id"] for note in target_timeline["notes"]} == {note_target_id}

    personal_note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Private J. Smith compensation note", "project_ids": [personal_id]},
        headers=headers,
    )
    assert personal_note.status_code == 200
    personal_note_id = personal_note.json()["data"]["id"]
    assert client.post(
        f"/api/notes/{personal_note_id}/people",
        json={"person_id": source_id, "state": "confirmed", "source": "user"},
        headers=headers,
    ).status_code == 200

    quick = client.get(f"/api/briefs/note/{note_source_id}?variant=quick", headers=headers)
    full = client.get(f"/api/briefs/note/{note_source_id}?variant=full", headers=headers)
    assert quick.status_code == full.status_code == 200
    assert "J. Smith source note body" not in quick.json()["data"]["markdown"]
    assert "J. Smith source note body" in full.json()["data"]["markdown"]

    person_brief = client.get(f"/api/briefs/person/{source_id}?variant=quick", headers=headers)
    assert person_brief.status_code == 200
    markdown = person_brief.json()["data"]["markdown"]
    assert "+ 1 notes in private projects" in markdown
    assert "Private J. Smith compensation note" not in markdown

    for payload in ({"note_id": note_source_id}, {"project_id": project_id}, {"person_id": source_id}):
        assert client.post("/api/flags", json=payload, headers=headers).status_code == 200
    home = client.get(f"/api/workspaces/{workspace_id}/home", headers=headers)
    assert home.status_code == 200
    labels = {item["label"] for item in home.json()["data"]["flagged"]}
    assert {"Source note", "Apollo", "J. Smith"} <= labels
