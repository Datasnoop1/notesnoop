from __future__ import annotations

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
    os.environ["NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED"] = "true"
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
        "x-notesnoop-name": "M5 Tester",
    }


def _postmark_payload(inbound_address: str, message_id: str, sender: str = "sender@example.test") -> dict:
    return {
        "MessageID": message_id,
        "From": sender,
        "FromFull": {"Email": sender, "Name": "Sender"},
        "OriginalRecipient": inbound_address,
        "ToFull": [{"Email": inbound_address, "Name": "NoteSnoop"}],
        "Subject": "Forwarded diligence note",
        "TextBody": "Forwarded email body for Apollo and Morgan.",
        "Headers": [{"Name": "Message-ID", "Value": f"<{message_id}@example.test>"}],
    }


def _mailgun_payload(inbound_address: str, message_id: str, sender: str = "sender@example.test") -> dict:
    return {
        "Message-Id": message_id,
        "recipient": inbound_address,
        "sender": sender,
        "subject": "Mailgun diligence note",
        "body-plain": "Mailgun email body for Apollo and Morgan.",
    }


def _insert_inbox_project(workspace_id: str, user_id: str, *, shared: bool) -> str:
    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (workspace_id, name, kind, color_hex, shared, created_by)
                VALUES (%s, 'Inbox', 'inbox', '#0f766e', %s, %s)
                RETURNING id
                """,
                (workspace_id, shared, user_id),
            )
            project_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO project_members (project_id, clerk_user_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (project_id, user_id),
            )
    return project_id


def test_postmark_manual_email_path_test_email_and_block_sender(client):
    user_id = f"m5_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M5 workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]
    inbound_address = state["inbound_address"]
    assert state["workspace"]["email_ai_mode"] == "manual"

    message_id = f"postmark-{uuid.uuid4()}"
    inbound = client.post("/webhooks/email/inbound", json=_postmark_payload(inbound_address, message_id))
    assert inbound.status_code == 200
    assert inbound.json()["data"]["outcome"] == "saved"
    note_id = inbound.json()["data"]["note_id"]

    duplicate = client.post("/webhooks/email/inbound", json=_postmark_payload(inbound_address, message_id))
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["duplicate"] is True

    note = client.get(f"/api/notes/{note_id}", headers=headers)
    assert note.status_code == 200
    note_data = note.json()["data"]
    assert note_data["raw_email_metadata"]["provider"] == "postmark"
    assert note_data["ai_processing_status"] == "skipped"

    queued = client.post(f"/api/notes/{note_id}/process-with-ai", headers=headers)
    assert queued.status_code == 200

    blocks_before = client.get("/api/email-blocks", headers=headers)
    assert blocks_before.status_code == 200
    assert blocks_before.json()["data"] == []

    blocked = client.post("/api/email-blocks", json={"note_id": note_id}, headers=headers)
    assert blocked.status_code == 200
    assert blocked.json()["data"]["sender_pattern"] == "sender@example.test"

    removed = client.get(f"/api/notes/{note_id}", headers=headers)
    assert removed.status_code == 404

    blocked_message = client.post(
        "/webhooks/email/inbound",
        json=_postmark_payload(inbound_address, f"postmark-{uuid.uuid4()}"),
    )
    assert blocked_message.status_code == 200
    assert blocked_message.json()["data"]["outcome"] == "blocked_sender"

    test_email = client.post(f"/api/workspaces/{workspace_id}/send-test-email", headers=headers)
    assert test_email.status_code == 200
    assert test_email.json()["data"]["outcome"] == "saved"


def test_mailgun_adapter_and_unknown_provider_are_gated(client):
    user_id = f"m5_mailgun_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M5 Mailgun workspace"}, headers=headers)
    assert boot.status_code == 200
    inbound_address = boot.json()["data"]["inbound_address"]

    unknown = client.post(
        "/webhooks/email/inbound",
        json=_mailgun_payload(inbound_address, f"mailgun-{uuid.uuid4()}"),
        headers={"X-NoteSnoop-Provider": "unknown"},
    )
    assert unknown.status_code == 400

    message_id = f"mailgun-{uuid.uuid4()}"
    inbound = client.post(
        "/webhooks/email/inbound",
        json=_mailgun_payload(inbound_address, message_id),
        headers={"X-NoteSnoop-Provider": "mailgun"},
    )
    assert inbound.status_code == 200
    assert inbound.json()["data"]["outcome"] == "saved"
    note_id = inbound.json()["data"]["note_id"]

    note = client.get(f"/api/notes/{note_id}", headers=headers)
    assert note.status_code == 200
    assert note.json()["data"]["raw_email_metadata"]["provider"] == "mailgun"


def test_email_ingestion_respects_private_and_shared_inbox_modes(client):
    suffix = uuid.uuid4().hex[:10]

    private_user = f"m5_private_{suffix}"
    private_headers = _headers(private_user)
    private_boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M5 private inbox workspace", "inbox_mode": "per_user_private"},
        headers=private_headers,
    )
    assert private_boot.status_code == 200
    private_state = private_boot.json()["data"]
    private_workspace_id = private_state["workspace"]["id"]
    private_inbox_id = next(project["id"] for project in private_state["projects"] if project["kind"] == "inbox")
    stale_shared_inbox_id = _insert_inbox_project(private_workspace_id, private_user, shared=True)

    private_message_id = f"postmark-private-{uuid.uuid4()}"
    private_inbound = client.post(
        "/webhooks/email/inbound",
        json=_postmark_payload(private_state["inbound_address"], private_message_id),
    )
    assert private_inbound.status_code == 200
    private_note_id = private_inbound.json()["data"]["note_id"]
    private_note = client.get(f"/api/notes/{private_note_id}", headers=private_headers)
    assert private_note.status_code == 200
    private_project_ids = {project["id"] for project in private_note.json()["data"]["projects"]}
    assert private_inbox_id in private_project_ids
    assert stale_shared_inbox_id not in private_project_ids

    shared_user = f"m5_shared_{suffix}"
    shared_headers = _headers(shared_user)
    shared_boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M5 shared inbox workspace", "inbox_mode": "shared"},
        headers=shared_headers,
    )
    assert shared_boot.status_code == 200
    shared_state = shared_boot.json()["data"]
    shared_workspace_id = shared_state["workspace"]["id"]
    shared_inbox_id = next(project["id"] for project in shared_state["projects"] if project["kind"] == "inbox")
    stale_private_inbox_id = _insert_inbox_project(shared_workspace_id, shared_user, shared=False)

    shared_message_id = f"postmark-shared-{uuid.uuid4()}"
    shared_inbound = client.post(
        "/webhooks/email/inbound",
        json=_postmark_payload(shared_state["inbound_address"], shared_message_id),
    )
    assert shared_inbound.status_code == 200
    shared_note_id = shared_inbound.json()["data"]["note_id"]
    shared_note = client.get(f"/api/notes/{shared_note_id}", headers=shared_headers)
    assert shared_note.status_code == 200
    shared_project_ids = {project["id"] for project in shared_note.json()["data"]["projects"]}
    assert shared_inbox_id in shared_project_ids
    assert stale_private_inbox_id not in shared_project_ids
