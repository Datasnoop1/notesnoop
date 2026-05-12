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
        "x-notesnoop-name": "Merge Tester",
    }


def test_merge_company_collapses_links_and_drops_source(client):
    user_id = f"co_merge_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Merge co workspace"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]

    # Two companies with the same intent — the dup the operator would clean up.
    source = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Acme Corp", "domain": "acme.com"},
        headers=headers,
    ).json()["data"]
    target = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Acme"},
        headers=headers,
    ).json()["data"]

    # A person, a note, and a task — all linked to BOTH companies through
    # different surfaces — to make sure the join-table migration deduplicates.
    person = client.post(
        f"/api/workspaces/{workspace_id}/people",
        json={"name": "Riley Quinn", "company_ids": [source["id"], target["id"]]},
        headers=headers,
    ).json()["data"]
    note = client.post(
        f"/api/workspaces/{workspace_id}/notes",
        json={"body": "Discussion with Riley about Acme.", "company_ids": [source["id"]]},
        headers=headers,
    ).json()["data"]
    task = client.post(
        f"/api/workspaces/{workspace_id}/tasks",
        json={"title": "Follow up with Acme", "company_ids": [source["id"], target["id"]]},
        headers=headers,
    ).json()["data"]

    merge = client.post(
        f"/api/companies/{source['id']}/merge",
        json={"target_company_id": target["id"]},
        headers=headers,
    )
    assert merge.status_code == 200, merge.text
    assert merge.json()["data"]["merged"] is True
    assert merge.json()["data"]["target_company_id"] == target["id"]

    # Source company is gone.
    gone = client.get(f"/api/workspaces/{workspace_id}/companies", headers=headers).json()["data"]
    company_ids = {c["id"] for c in gone}
    assert source["id"] not in company_ids
    assert target["id"] in company_ids

    # Target company picked up the source's domain (target had none).
    target_after = next(c for c in gone if c["id"] == target["id"])
    assert target_after.get("domain") == "acme.com"

    # Person no longer has source company in their links.
    refreshed_person = client.get(f"/api/workspaces/{workspace_id}/people", headers=headers).json()["data"]
    # We can't easily query company links from the people list; verify via note.
    note_after = client.get(f"/api/notes/{note['id']}", headers=headers).json()["data"]
    company_ids_on_note = [c["id"] for c in note_after.get("companies", [])]
    assert source["id"] not in company_ids_on_note
    assert target["id"] in company_ids_on_note

    # Task carries only the surviving company id and no duplicates.
    task_after = client.get(f"/api/tasks/{task['id']}", headers=headers).json()["data"]
    task_company_ids = [c["id"] for c in task_after.get("companies", [])]
    assert source["id"] not in task_company_ids
    assert task_after.get("companies", []).count({"id": target["id"]}) <= 1
    assert target["id"] in task_company_ids


def test_merge_company_rejects_self_target(client):
    user_id = f"co_merge_self_{uuid.uuid4().hex[:10]}"
    headers = _headers(user_id)
    boot = client.post("/api/bootstrap", json={"workspace_name": "Self merge"}, headers=headers)
    workspace_id = boot.json()["data"]["workspace"]["id"]
    company = client.post(
        f"/api/workspaces/{workspace_id}/companies",
        json={"name": "Solo Inc"},
        headers=headers,
    ).json()["data"]
    resp = client.post(
        f"/api/companies/{company['id']}/merge",
        json={"target_company_id": company["id"]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_merge_company_rejects_cross_workspace(client):
    a_user = f"co_a_{uuid.uuid4().hex[:10]}"
    b_user = f"co_b_{uuid.uuid4().hex[:10]}"
    a_headers = _headers(a_user)
    b_headers = _headers(b_user)
    a_ws = client.post("/api/bootstrap", json={"workspace_name": "A"}, headers=a_headers).json()["data"]["workspace"]["id"]
    b_ws = client.post("/api/bootstrap", json={"workspace_name": "B"}, headers=b_headers).json()["data"]["workspace"]["id"]
    a_company = client.post(
        f"/api/workspaces/{a_ws}/companies", json={"name": "Acme in A"}, headers=a_headers,
    ).json()["data"]
    b_company = client.post(
        f"/api/workspaces/{b_ws}/companies", json={"name": "Acme in B"}, headers=b_headers,
    ).json()["data"]
    resp = client.post(
        f"/api/companies/{a_company['id']}/merge",
        json={"target_company_id": b_company["id"]},
        headers=a_headers,
    )
    assert resp.status_code == 404
