from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
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
    os.environ["NOTESNOOP_POSTMARK_DRY_RUN"] = "true"
    sys.path.insert(0, str(ROOT / "notesnoop-backend"))
    from fastapi.testclient import TestClient

    from app.briefing import enqueue_due_morning_briefings, make_unsubscribe_token
    from app.config import get_settings
    from app.main import app
    from app.worker import handle_job

    get_settings.cache_clear()


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
        "x-notesnoop-name": "M7 Tester",
    }


def test_m7_morning_briefing_enqueue_send_unsubscribe_and_bounce(client):
    suffix = uuid.uuid4().hex[:10]
    user_id = f"m7_user_{suffix}"
    headers = _headers(user_id)

    boot = client.post(
        "/api/bootstrap",
        json={"workspace_name": "M7 workspace", "timezone": "UTC", "morning_briefing_optin": True},
        headers=headers,
    )
    assert boot.status_code == 200
    workspace_id = boot.json()["data"]["workspace"]["id"]

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO review_queue (workspace_id, target_user_id, entity_kind, entity_id, reason, payload)
                VALUES (%s, %s, 'person', gen_random_uuid(), 'ai_suggestion', %s::jsonb)
                """,
                (workspace_id, user_id, '{"name":"Secret note subject","confidence":0.82}'),
            )

    result = enqueue_due_morning_briefings(datetime(2026, 5, 9, 8, 5, tzinfo=timezone.utc))
    assert result["queued"] == 1
    duplicate = enqueue_due_morning_briefings(datetime(2026, 5, 9, 8, 30, tzinfo=timezone.utc))
    assert duplicate["queued"] == 0

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM ai_jobs
                WHERE workspace_id = %s
                  AND target_user_id = %s
                  AND kind = 'briefing'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id, user_id),
            )
            job = dict(cur.fetchone())

    asyncio.run(handle_job(job))

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT state, payload FROM ai_jobs WHERE id = %s", (job["id"],))
            sent = dict(cur.fetchone())

    assert sent["state"] == "done"
    delivery = sent["payload"]["delivery"]
    assert delivery["dry_run"] is True
    template_model = delivery["postmark_payload"]["TemplateModel"]
    assert template_model["pending_count"] == 1
    assert "Secret note subject" not in str(delivery["postmark_payload"])
    assert any(header["Name"] == "List-Unsubscribe" for header in delivery["postmark_payload"]["Headers"])

    token = make_unsubscribe_token(workspace_id, user_id)
    unsubscribed = client.post(f"/webhooks/email/unsubscribe?token={token}")
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["data"]["unsubscribed"] is True

    with psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT morning_briefing_optin FROM workspace_members WHERE workspace_id = %s AND clerk_user_id = %s",
                (workspace_id, user_id),
            )
            assert cur.fetchone()["morning_briefing_optin"] is False

    toggled = client.patch(
        f"/api/workspaces/{workspace_id}/settings",
        json={"morning_briefing_optin": True},
        headers=headers,
    )
    assert toggled.status_code == 200
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("RESET ROLE")
            cur.execute("SET ROLE notesnoop_app")
            cur.execute("RESET notesnoop.current_user_id")
            cur.execute("SELECT disable_morning_briefing(%s, %s)", (workspace_id, user_id))
            assert cur.fetchone()[0] is True
    toggled_again = client.patch(
        f"/api/workspaces/{workspace_id}/settings",
        json={"morning_briefing_optin": True},
        headers=headers,
    )
    assert toggled_again.status_code == 200
    bounced = client.post("/webhooks/email/bounce", json={"Email": f"{user_id}@example.test", "Type": "HardBounce"})
    assert bounced.status_code == 200
    assert bounced.json()["data"]["disabled_memberships"] == 1
