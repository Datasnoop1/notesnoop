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

sys.path.insert(0, str(ROOT / "notesnoop-backend"))
from app.embeddings import EMBEDDING_DIMENSION, EMBEDDING_MODEL, lexical_hash_embedding, vector_literal


def test_lexical_hash_embedding_is_deterministic_and_locked_to_m3_dimension():
    first = lexical_hash_embedding("Apollo diligence memo")
    second = lexical_hash_embedding("Apollo diligence memo")
    other = lexical_hash_embedding("Zephyr operating plan")

    assert len(first) == EMBEDDING_DIMENSION == 1024
    assert first == second
    assert first != other
    assert vector_literal(first).startswith("[")


if DATABASE_URL:
    os.environ.setdefault("NOTESNOOP_DATABASE_URL", DATABASE_URL)
    os.environ["NOTESNOOP_DEV_AUTH"] = "true"
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
    if not DATABASE_URL:
        pytest.skip("NOTESNOOP_TEST_DATABASE_URL or MIGRATE_DATABASE_URL is required")
    _run_migrations()
    with TestClient(app) as test_client:
        yield test_client


def _headers(user_id: str) -> dict[str, str]:
    return {
        "x-notesnoop-user-id": user_id,
        "x-notesnoop-email": f"{user_id}@example.test",
        "x-notesnoop-name": "M3 Tester",
    }


def _seed_embedding(note_id: str, semantic_text: str) -> None:
    vector = vector_literal(lexical_hash_embedding(semantic_text))
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO embeddings (
                  note_id,
                  workspace_id,
                  embedding,
                  model_version,
                  provider,
                  embedding_dimension,
                  embedding_text_sha256
                )
                SELECT id, workspace_id, %s::vector, %s, 'lexical_hash', 1024, %s
                FROM notes
                WHERE id = %s
                """,
                (vector, EMBEDDING_MODEL, f"test-{uuid.uuid4().hex}", note_id),
            )


def test_semantic_search_returns_embedding_only_match_and_reports_exclusions(client):
    user_id = f"m3_user_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M3 workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]

    manual_project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Manual", "ai_mode": "manual"},
        headers=headers,
    )
    assert manual_project.status_code == 200
    project_id = manual_project.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Coded note without the query terms.", "project_ids": [project_id]},
        headers=headers,
    )
    assert note.status_code == 200
    note_id = note.json()["data"]["id"]
    _seed_embedding(note_id, "orbital escrow transition")

    search = client.get(
        f"/api/workspaces/{workspace_id}/search",
        params={"q": "orbital escrow"},
        headers=headers,
    )
    assert search.status_code == 200
    payload = search.json()
    assert payload["data"][0]["id"] == note_id
    assert payload["data"][0]["search_source"] == "semantic"
    assert payload["meta"]["semantic_enabled"] is True
    assert payload["meta"]["semantic_excluded"] >= 0


def test_ai_rate_limit_returns_429_under_stress(client):
    user_id = f"m3_rate_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)

    boot = client.post("/api/bootstrap", json={"workspace_name": "M3 rate workspace"}, headers=headers)
    assert boot.status_code == 200
    state = boot.json()["data"]
    workspace_id = state["workspace"]["id"]

    manual_project = client.post(
        f"/api/workspaces/{workspace_id}/projects",
        json={"name": "Manual AI", "ai_mode": "manual"},
        headers=headers,
    )
    assert manual_project.status_code == 200
    project_id = manual_project.json()["data"]["id"]

    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Manual project note for AI stress.", "project_ids": [project_id]},
        headers=headers,
    )
    assert note.status_code == 200
    note_id = note.json()["data"]["id"]

    responses = [client.post(f"/api/notes/{note_id}/process-with-ai", headers=headers) for _ in range(12)]
    statuses = [response.status_code for response in responses]

    assert 429 in statuses
    first_429 = statuses.index(429)
    assert all(status == 200 for status in statuses[:first_429])
    assert responses[first_429].headers.get("Retry-After")
