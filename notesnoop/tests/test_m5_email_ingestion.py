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
