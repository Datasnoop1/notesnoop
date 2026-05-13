from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))
sys.path.insert(0, str(ROOT / "notesnoop"))

import migrate
from app import auth, email_ingest, main, ollama_client, services, worker
from app.briefing import make_unsubscribe_token, parse_unsubscribe_token
from app.embeddings import EmbeddingResult
from app.routers import memory, notes, realtime, webhooks


class FakeCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_values:
            return self.fetchone_values.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_values:
            return self.fetchall_values.pop(0)
        return []


def _params_for_backend(cur, fragment):
    return [params for sql, params in cur.executed if fragment in sql]


class FakeConn:
    def __init__(self, cursor: FakeCursor | None = None):
        self.cursor_obj = cursor or FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.autocommit = False

    def cursor(self, *_, **__):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_auth_jwks_clerk_token_and_dev_user_paths(monkeypatch):
    settings = SimpleNamespace(
        clerk_jwks_url="https://clerk.test/jwks",
        clerk_issuer="https://issuer.test/",
        clerk_authorized_party="notesnoop.app",
        clerk_secret_key="sk_test_secret",
        dev_auth=False,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    auth._jwks_cache = {}
    auth._jwks_fetched_at = 0
    auth._clerk_user_cache = {}

    assert auth._jwks_url() == "https://clerk.test/jwks"
    settings.clerk_jwks_url = ""
    assert auth._jwks_url() == "https://issuer.test/.well-known/jwks.json"
    settings.clerk_issuer = ""
    assert auth._jwks_url() == ""
    with pytest.raises(HTTPException) as missing_config:
        auth._get_jwks()
    assert missing_config.value.status_code == 500

    settings.clerk_issuer = "https://issuer.test"
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"keys": [{"kid": "kid-1"}]})
    monkeypatch.setattr(auth.httpx, "get", lambda *_args, **_kwargs: response)
    assert auth._get_jwks()["keys"][0]["kid"] == "kid-1"
    assert auth._get_jwks()["keys"][0]["kid"] == "kid-1"

    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda _token: {"alg": "HS256", "kid": "kid-1"})
    with pytest.raises(HTTPException) as bad_alg:
        auth._verify_clerk_token("token")
    assert bad_alg.value.status_code == 401

    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda _token: {"alg": "RS256", "kid": "kid-1"})
    monkeypatch.setattr(auth.jwk, "construct", lambda key, algorithm: {"key": key, "algorithm": algorithm})
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user_1",
            "email": "user@example.test",
            "name": "User One",
            "picture": "https://example.test/avatar.png",
            "azp": "notesnoop.app",
        },
    )
    assert auth._verify_clerk_token("token")["sub"] == "user_1"

    request = Request({"type": "http", "headers": []})
    user = auth.current_user(request, authorization="Bearer token")
    assert user.clerk_user_id == "user_1"
    assert user.email == "user@example.test"

    def profile_get(url, **_kwargs):
        if "/v1/users/user_2" in url:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "id": "user_2",
                    "first_name": "Fallback",
                    "last_name": "User",
                    "image_url": "https://example.test/fallback.png",
                    "primary_email_address_id": "email_1",
                    "email_addresses": [{"id": "email_1", "email_address": "fallback@example.test"}],
                },
            )
        return response

    monkeypatch.setattr(auth.httpx, "get", profile_get)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *_args, **_kwargs: {
            "sub": "user_2",
            "azp": "notesnoop.app",
        },
    )
    fallback_user = auth.current_user(request, authorization="Bearer token")
    assert fallback_user.email == "fallback@example.test"
    assert fallback_user.display_name == "Fallback User"

    settings.dev_auth = True
    dev_user = auth.current_user(
        request,
        x_notesnoop_user_id="dev-2",
        x_notesnoop_email="dev-2@example.test",
        x_notesnoop_name="Dev Two",
    )
    assert dev_user.email == "dev-2@example.test"
    assert dev_user.display_name == "Dev Two"


def test_ollama_extraction_payload_and_validation(monkeypatch):
    async def missing_key_case():
        with pytest.raises(RuntimeError):
            await ollama_client.extract_entities("Body", [], [])

    async def valid_case():
        result = await ollama_client.extract_entities("Note body", ["Morgan"], ["Apollo"])
        return result

    monkeypatch.setattr(ollama_client, "OLLAMA_API_KEY", "")
    asyncio.run(missing_key_case())
    posted = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps({"people": [{"name": "Morgan", "confidence": 0.9}], "projects": []})}}

    class FakeClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, headers, json):
            posted.update({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(ollama_client, "OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(valid_case())
    assert result["people"][0]["name"] == "Morgan"
    assert posted["headers"]["Authorization"] == "Bearer test-key"
    assert posted["json"]["format"] == "json"

    fallback = ollama_client.deterministic_extract_entities(
        "Morgan Lee discussed Apollo. Action: follow up with legal.",
        ["Morgan Lee", "Morgan", "Absent Person"],
        ["Apollo", "Missing Project"],
    )
    assert fallback["people"][0]["name"] == "Morgan Lee"
    assert fallback["people"][0]["span"] == [0, 10]
    assert fallback["projects"][0]["name"] == "Apollo"
    assert fallback["tasks"][0]["title"] == "follow up with legal"

    actions = ollama_client.deterministic_extract_tasks(
        "We need to send the deck.\nTODO: confirm pricing\nFYI no task here."
    )
    assert [item["title"] for item in actions] == ["We need to send the deck", "confirm pricing"]

    report = ollama_client.deterministic_project_report(
        {"name": "Apollo"},
        [{"title": "IC memo", "body": "Apollo needs pricing detail."}],
        [{"title": "Confirm pricing", "status": "blocked", "priority": 1, "due_at": None}],
        [{"title": "Partner call", "summary": "Discussed timing."}],
        [],
    )
    assert report["title"] == "Apollo report"
    assert "## Executive summary" in report["body"]
    assert "Confirm pricing" in report["body"]
    assert report["confidence"] > 0.5

    answer = ollama_client.deterministic_memory_answer(
        "What is blocked on Apollo?",
        [{"id": "note-1", "title": "Apollo update", "body": "Pricing is blocked until Morgan sends details."}],
        [{"id": "task-1", "kind": "task", "title": "Confirm pricing", "subtitle": "Blocked by missing details"}],
    )
    assert "Apollo update" in answer["answer"]
    assert answer["citations"][0]["label"] == "N1"
    assert answer["citations"][1]["kind"] == "task"
    assert answer["source_counts"] == {"notes": 1, "memory": 1}
    assert notes._memory_query_terms("What is blocked on Apollo?") == ["blocked", "apollo"]

    busy_answer = ollama_client.deterministic_memory_answer(
        "What diligence memory exists for Apollo?",
        [],
        [{"id": "report-1", "kind": "report", "title": "Apollo relationship memory report", "subtitle": "Quarterly update"}]
        + [
            {"id": f"context-{index}", "kind": "workflow", "title": f"Apollo context {index}", "subtitle": "Generic context"}
            for index in range(8)
        ]
        + [
            {
                "id": "task-2",
                "kind": "task",
                "title": "Prepare Apollo diligence pack",
                "subtitle": "Morgan needs the revised diligence timeline.",
            },
        ],
    )
    assert "Prepare Apollo diligence pack" in busy_answer["answer"]

    class MemoryAnswerResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps({"answer": "Apollo has diligence context.", "confidence": 0.8})}}

    class MemoryAnswerClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return MemoryAnswerResponse()

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", MemoryAnswerClient)
    monkeypatch.setattr(ollama_client, "OLLAMA_API_KEY", "test-key")
    generated_answer = asyncio.run(
        ollama_client.generate_memory_answer(
            "What diligence memory exists for Apollo?",
            [],
            [
                {
                    "id": "task-2",
                    "kind": "task",
                    "title": "Prepare Apollo diligence pack",
                    "subtitle": "Morgan needs the revised diligence timeline.",
                },
            ],
        )
    )
    assert "Prepare Apollo diligence pack" in generated_answer["answer"]

    class RateLimitedResponse:
        status_code = 429

        def raise_for_status(self):
            request = httpx.Request("POST", "https://ollama.test/api/chat")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    class RateLimitedClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return RateLimitedResponse()

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", RateLimitedClient)
    monkeypatch.setattr(ollama_client, "ALLOW_DETERMINISTIC_FALLBACK", True)
    rate_limited = asyncio.run(ollama_client.extract_entities("Morgan met Apollo", ["Morgan"], ["Apollo"]))
    assert rate_limited["people"][0]["name"] == "Morgan"


def test_health_and_readiness(monkeypatch):
    assert main.health()["status"] == "ok"
    settings = SimpleNamespace(
        dev_auth=False,
        clerk_issuer="https://issuer.test",
        postmark_dry_run=False,
        postmark_server_token="postmark-token",
        email_ai_default="manual",
    )
    conn = FakeConn(FakeCursor(fetchone_values=[(1,)]))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "get_conn", lambda: conn)
    monkeypatch.setattr(main, "put_conn", lambda _conn: None)
    monkeypatch.setattr(main, "_ops_checks", lambda _cur: {})
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "false")
    monkeypatch.setenv("NOTESNOOP_POSTMARK_BASIC_AUTH", "postmark:user")

    ready = main.readiness()

    assert ready["status"] == "ready"
    assert ready["beta_status"] == "ready"
    assert ready["checks"]["database"]["ok"] is True
    assert ready["checks"]["auth"]["mode"] == "clerk"

    settings.postmark_server_token = ""
    settings.postmark_dry_run = False
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    blocked = main.readiness()
    assert blocked["status"] == "blocked"
    assert blocked["beta_status"] == "blocked"
    assert blocked["checks"]["ollama"]["ok"] is False
    assert blocked["checks"]["postmark_outbound"]["ok"] is False

    settings.dev_auth = True
    settings.postmark_server_token = "postmark-token"
    settings.postmark_dry_run = True
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "true")
    preview_ready = main.readiness()
    assert preview_ready["status"] == "ready"
    assert preview_ready["beta_status"] == "blocked"
    assert preview_ready["checks"]["auth"]["beta_ok"] is False
    assert preview_ready["checks"]["postmark_outbound"]["mode"] == "dry_run"


def test_reserved_memory_graph_migration_parses_and_stays_notesnoop_scoped():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0012_reserved_memory_graph.sql")

    assert migration.filename == "0012_reserved_memory_graph.sql"
    assert migration.mode == "tx"
    assert migration.statement_timeout == "120s"
    assert "CREATE TABLE IF NOT EXISTS tasks" in migration.sql
    assert "CREATE TABLE IF NOT EXISTS reports" in migration.sql
    assert "CREATE POLICY tasks_workspace_access" in migration.sql
    assert "CREATE POLICY report_notes_resource_access" in migration.sql
    assert "enforce_memory_link_workspace" in migration.sql
    assert "datasnoop" not in migration.sql.lower()
    assert "ALTER TABLE notes" not in migration.sql


def test_ai_memory_materialization_migration_adds_source_provenance():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0013_ai_memory_materialization_provenance.sql")

    assert migration.filename == "0013_ai_memory_materialization_provenance.sql"
    assert "ALTER TABLE tasks" in migration.sql
    assert "source_note_id UUID REFERENCES notes" in migration.sql
    assert "idx_notesnoop_tasks_source_note_kind_title" in migration.sql
    assert "idx_notesnoop_meetings_source_note_kind" in migration.sql
    assert "idx_notesnoop_reports_source_note_kind" in migration.sql


def test_ai_processing_error_migration_adds_note_failure_context():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0014_ai_processing_error.sql")

    assert migration.filename == "0014_ai_processing_error.sql"
    assert "ADD COLUMN IF NOT EXISTS ai_processing_error TEXT" in migration.sql


def test_structured_memory_review_guardrails_migration_adds_provenance():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0022_structured_memory_review_guardrails.sql")

    assert migration.filename == "0022_structured_memory_review_guardrails.sql"
    assert "'task','meeting','report','workflow','company'" in migration.sql
    assert "ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'" in migration.sql
    assert "ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue" in migration.sql
    assert "ADD COLUMN IF NOT EXISTS source_payload JSONB" in migration.sql
    assert "idx_notesnoop_review_queue_candidate_key" in migration.sql
    assert "datasnoop" not in migration.sql.lower()


def test_project_scoped_memory_rls_migration_replaces_workspace_wide_access():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0015_project_scoped_memory_rls.sql")

    assert migration.filename == "0015_project_scoped_memory_rls.sql"
    assert "CREATE OR REPLACE FUNCTION can_access_task" in migration.sql
    assert "can_access_project(tp.project_id)" in migration.sql
    assert "DROP POLICY IF EXISTS tasks_workspace_access" in migration.sql
    assert "CREATE POLICY tasks_project_access" in migration.sql
    assert "DROP POLICY IF EXISTS companies_workspace_access" in migration.sql
    assert "CREATE POLICY companies_project_access" in migration.sql


def test_memory_insert_rls_migration_keeps_project_visibility_but_allows_member_writes():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0016_relax_memory_insert_checks.sql")

    assert migration.filename == "0016_relax_memory_insert_checks.sql"
    assert "USING (can_access_task(id))" in migration.sql
    assert "WITH CHECK (is_workspace_member(workspace_id))" in migration.sql
    assert "USING (can_access_report(id))" in migration.sql


def test_memory_returning_visibility_migration_allows_fresh_rows_to_return():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0017_memory_returning_visibility.sql")

    assert migration.filename == "0017_memory_returning_visibility.sql"
    assert "created_by = current_user_id()" in migration.sql
    assert "OR can_access_task(id)" in migration.sql
    assert "OR can_access_report(id)" in migration.sql
    assert "WITH CHECK (is_workspace_member(workspace_id))" in migration.sql


def test_ops_heartbeat_migration_adds_worker_and_ai_job_health():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0018_ops_heartbeat.sql")

    assert migration.filename == "0018_ops_heartbeat.sql"
    assert "CREATE TABLE IF NOT EXISTS ops_heartbeats" in migration.sql
    assert "CREATE OR REPLACE FUNCTION ops_ai_job_health" in migration.sql
    assert "stale_running" in migration.sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ops_heartbeats" in migration.sql


def test_task_reminders_migration_adds_first_class_due_reminders():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0019_task_reminders.sql")

    assert migration.filename == "0019_task_reminders.sql"
    assert "CREATE TABLE IF NOT EXISTS task_reminders" in migration.sql
    assert "CREATE OR REPLACE FUNCTION sync_task_due_reminder" in migration.sql
    assert "CREATE TRIGGER trg_tasks_sync_due_reminder" in migration.sql
    assert "INSERT INTO task_reminders" in migration.sql
    assert "CREATE POLICY task_reminders_task_access" in migration.sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON task_reminders" in migration.sql


def test_task_reminder_active_uniqueness_migration_prevents_duplicate_snoozes():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0021_task_reminder_active_uniqueness.sql")

    assert migration.filename == "0021_task_reminder_active_uniqueness.sql"
    assert "idx_notesnoop_task_reminders_active_task_channel" in migration.sql
    assert "WHERE state IN ('pending','snoozed')" in migration.sql
    assert "DROP INDEX IF EXISTS idx_notesnoop_task_reminders_pending_task_channel" in migration.sql
    assert "UPDATE task_reminders" in migration.sql
    assert "IF NOT FOUND THEN" in migration.sql


def test_home_rls_fast_path_migration_preserves_project_visibility_helpers():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0034_home_rls_fast_path.sql")

    assert migration.filename == "0034_home_rls_fast_path.sql"
    assert "CREATE POLICY notes_project_access" in migration.sql
    assert "created_by = current_user_id() AND is_workspace_member(workspace_id)" in migration.sql
    assert "OR can_access_note(id)" in migration.sql
    assert "CREATE POLICY note_projects_note_access" in migration.sql
    assert "can_access_project(project_id) OR can_access_note(note_id)" in migration.sql
    assert "WITH CHECK (can_access_note(note_id) AND can_access_project(project_id))" in migration.sql


def test_project_bootstrap_returning_migration_restores_direct_creator_select():
    migration = migrate.parse_migration(ROOT / "notesnoop" / "migrations" / "0036_project_bootstrap_returning.sql")

    assert migration.filename == "0036_project_bootstrap_returning.sql"
    assert "CREATE POLICY projects_creator_returning_select" in migration.sql
    assert "FOR SELECT" in migration.sql
    assert "created_by = current_user_id()" in migration.sql
    assert "AND is_workspace_member(workspace_id)" in migration.sql
    assert "coalesce(w.inbox_mode, 'per_user_private') <> 'shared'" in migration.sql
    assert "coalesce(w.inbox_mode, 'per_user_private') = 'shared'" in migration.sql
    assert "USING (can_access_project(id))" not in migration.sql


def test_search_skips_semantic_when_keyword_results_are_plentiful():
    assert notes._should_run_semantic_search("Apollo", 0) is True
    assert notes._should_run_semantic_search("Apollo", notes.SEARCH_KEYWORD_FAST_PATH_MIN_ROWS - 1) is True
    assert notes._should_run_semantic_search("Apollo", notes.SEARCH_KEYWORD_FAST_PATH_MIN_ROWS) is False
    assert notes._should_run_semantic_search("ap", 0) is False


def test_project_summary_helper_is_deterministic():
    summary = memory.build_project_summary(
        {"id": "project-1", "name": "Apollo"},
        [
            {"title": "", "body": "First note body with useful context"},
            {"title": "Named note", "body": "Ignored body"},
        ],
        [
            {"title": "Unblock contract", "status": "blocked", "priority": 1, "due_at": None},
            {"title": "Draft memo", "status": "doing", "priority": 3, "due_at": None},
            {"title": "Old shipped work", "status": "done", "priority": 5, "due_at": None},
        ],
    )

    assert summary["project_id"] == "project-1"
    assert summary["task_counts"] == {"todo": 0, "doing": 1, "blocked": 1, "done": 1}
    assert [task["title"] for task in summary["open_tasks"]] == ["Unblock contract", "Draft memo"]
    assert summary["recent_notes"] == ["First note body with useful context", "Named note"]
    assert summary["markdown"].splitlines() == [
        "# Apollo",
        "Tasks: 1 blocked, 1 doing, 0 todo, 1 done",
        "Open tasks:",
        "- [blocked] Unblock contract",
        "- [doing] Draft memo",
        "Recent notes:",
        "- First note body with useful context",
        "- Named note",
    ]


def test_derived_note_titles_trim_participant_tails_only_for_descriptive_titles():
    assert services.derive_title("Apollo quarterly launch memo with Morgan.", None) == (
        "Apollo quarterly launch memo",
        True,
    )
    assert services.derive_title("Call with Morgan.", None) == ("Call with Morgan", True)
    assert services.derive_title("Apollo sync", "Keep exact title with Morgan") == ("Keep exact title with Morgan", False)


def test_generated_project_report_access_and_personal_guards(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    payload = memory.ProjectReportGenerateRequest()
    project_id = "00000000-0000-0000-0000-000000000211"
    personal_project_id = "00000000-0000-0000-0000-000000000212"

    async def unexpected_generate(*_args, **_kwargs):
        raise AssertionError("generation should not run")

    monkeypatch.setattr(memory, "generate_project_report", unexpected_generate)

    inaccessible = FakeCursor(
        fetchone_values=[
            {"id": project_id, "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"},
            {"allowed": False},
        ]
    )

    @contextmanager
    def inaccessible_transaction(_user_id):
        yield inaccessible

    monkeypatch.setattr(memory, "transaction", inaccessible_transaction)
    with pytest.raises(HTTPException) as denied:
        memory.generate_project_memory_report(f"urn:uuid:{project_id}", payload, user)
    assert denied.value.status_code == 404
    assert _params_for_backend(inaccessible, "SELECT * FROM projects WHERE id = %s")[0] == (project_id,)
    assert _params_for_backend(inaccessible, "SELECT can_access_project(%s::uuid)")[0] == (project_id,)

    personal = FakeCursor(
        fetchone_values=[
            {"id": personal_project_id, "workspace_id": "workspace-1", "name": "Personal", "kind": "personal"},
            {"allowed": True},
        ]
    )

    @contextmanager
    def personal_transaction(_user_id):
        yield personal

    monkeypatch.setattr(memory, "transaction", personal_transaction)
    with pytest.raises(HTTPException) as blocked:
        memory.generate_project_memory_report(personal_project_id, payload, user)
    assert blocked.value.status_code == 403


def test_generated_project_report_rejects_empty_sources(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    project_id = "00000000-0000-0000-0000-000000000213"
    read_cursor = FakeCursor(
        fetchone_values=[
            {"id": project_id, "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"},
            {"allowed": True},
        ],
        fetchall_values=[[], [], [], [], [], []],
    )

    async def unexpected_generate(*_args, **_kwargs):
        raise AssertionError("empty projects should not generate reports")

    @contextmanager
    def fake_transaction(_user_id):
        yield read_cursor

    monkeypatch.setattr(memory, "transaction", fake_transaction)
    monkeypatch.setattr(memory, "generate_project_report", unexpected_generate)

    with pytest.raises(HTTPException) as empty:
        memory.generate_project_memory_report(project_id, memory.ProjectReportGenerateRequest(), user)
    assert empty.value.status_code == 422
    assert "needs notes, tasks, meetings, or prior reports" in empty.value.detail


def test_generated_project_report_links_deduped_sources_and_counts(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    project_id = "00000000-0000-0000-0000-000000000201"
    note_1 = "00000000-0000-0000-0000-000000000202"
    note_2 = "00000000-0000-0000-0000-000000000203"
    task_id = "00000000-0000-0000-0000-000000000204"
    meeting_id = "00000000-0000-0000-0000-000000000205"
    prior_report_id = "00000000-0000-0000-0000-000000000206"
    person_1 = "00000000-0000-0000-0000-000000000207"
    person_2 = "00000000-0000-0000-0000-000000000208"
    company_id = "00000000-0000-0000-0000-000000000209"
    report_id = "00000000-0000-0000-0000-000000000210"
    project = {"id": project_id, "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"}
    read_cursor = FakeCursor(
        fetchone_values=[project, {"allowed": True}],
        fetchall_values=[
            [{"id": note_1, "title": "Memo"}, {"id": note_1, "title": "Memo again"}, {"id": note_2, "title": "Call"}],
            [{"id": task_id, "title": "Follow up"}, {"id": task_id, "title": "Follow up duplicate"}],
            [{"id": meeting_id, "title": "Partner sync"}],
            [{"id": prior_report_id, "title": "Prior"}, {"id": prior_report_id, "title": "Prior duplicate"}],
            [{"id": person_1, "name": "Morgan"}, {"id": person_1, "name": "Morgan again"}, {"id": person_2, "name": "Jordan"}],
            [{"id": company_id, "name": "Northstar"}, {"id": company_id, "name": "Northstar duplicate"}],
        ],
    )
    write_cursor = FakeCursor(fetchone_values=[project, {"allowed": True}, {"id": report_id, "workspace_id": "workspace-1"}])
    cursors = [read_cursor, write_cursor]
    captured = {}

    async def fake_generate(project_context, notes, tasks, meetings, reports, variant):
        captured.update(
            {
                "project_people": [row["id"] for row in project_context["people"]],
                "project_companies": [row["id"] for row in project_context["companies"]],
                "notes": [row["id"] for row in notes],
                "tasks": [row["id"] for row in tasks],
                "meetings": [row["id"] for row in meetings],
                "reports": [row["id"] for row in reports],
                "variant": variant,
            }
        )
        return {"title": "Generated", "body": "Grounded body", "confidence": 0.81}

    @contextmanager
    def fake_transaction(_user_id):
        yield cursors.pop(0)

    monkeypatch.setattr(memory, "transaction", fake_transaction)
    monkeypatch.setattr(memory, "generate_project_report", fake_generate)
    monkeypatch.setattr(memory, "_report_payload", lambda _cur, report_id: {"id": report_id})

    result = memory.generate_project_memory_report(
        project_id,
        memory.ProjectReportGenerateRequest(title="Custom report", variant="quick"),
        user,
    )

    assert captured == {
        "project_people": [person_1, person_2],
        "project_companies": [company_id],
        "notes": [note_1, note_2],
        "tasks": [task_id],
        "meetings": [meeting_id],
        "reports": [prior_report_id],
        "variant": "quick",
    }
    assert result["data"]["generation_confidence"] == 0.81
    assert result["data"]["source_counts"] == {
        "projects": 1,
        "notes": 2,
        "tasks": 1,
        "meetings": 1,
        "reports": 1,
        "people": 2,
        "companies": 1,
        "total": 9,
    }

    def params_for(fragment: str) -> list[tuple]:
        return [params for sql, params in write_cursor.executed if fragment in sql]

    insert_params = params_for("INSERT INTO reports")[0]
    assert insert_params[:4] == ("workspace-1", "Custom report", "Grounded body", "user-1")
    assert insert_params[4] == 0.81
    assert json.loads(insert_params[5])["source_counts"]["total"] == 9
    assert params_for("INSERT INTO report_projects") == [(report_id, project_id, "workspace-1", "user-1", "manual")]
    assert [params[1] for params in params_for("INSERT INTO report_notes")] == [note_1, note_2]
    assert [params[1] for params in params_for("INSERT INTO report_tasks")] == [task_id]
    assert [params[1] for params in params_for("INSERT INTO report_meetings")] == [meeting_id]
    assert [params[1] for params in params_for("INSERT INTO report_reports")] == [prior_report_id]
    assert [params[1] for params in params_for("INSERT INTO report_people")] == [person_1, person_2]
    assert [params[1] for params in params_for("INSERT INTO report_companies")] == [company_id]


def test_email_and_webhook_helpers(monkeypatch):
    assert email_ingest.html_to_text(None) == ""
    assert email_ingest.html_to_text("<p>Hello<br>World</p>") == "Hello\nWorld"
    assert email_ingest.header_value([{"Name": "Message-ID", "Value": "<m1>"}], "message-id") == "<m1>"
    assert email_ingest.header_value({"Name": "Message-ID"}, "message-id") is None

    postmark = email_ingest.postmark_envelope(
        {
            "ToFull": [{"Email": "USER@in.notesnoop.app"}],
            "FromFull": {"Email": "sender@example.test"},
            "Subject": "",
            "HtmlBody": "<b>Forwarded</b>",
            "MessageID": "postmark-1",
            "Headers": [{"Name": "Message-ID", "Value": "<rfc-1>"}],
        }
    )
    assert postmark["recipient"] == "user@in.notesnoop.app"
    assert postmark["subject"] == "(no subject)"
    assert postmark["body"] == "Forwarded"

    mailgun = email_ingest.mailgun_envelope(
        {
            "token": "mailgun-token",
            "recipient": "alias@in.notesnoop.app",
            "sender": "Sender <sender@example.test>",
            "body-html": "<p>Fallback body</p>",
        }
    )
    assert mailgun["message_id"] == "mailgun-token"
    assert mailgun["sender"] == "sender@example.test"

    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "true")
    webhooks._verify_postmark_auth(b"{}", None, None)
    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "false")
    monkeypatch.setenv("NOTESNOOP_POSTMARK_BASIC_AUTH", "user:pass")
    with pytest.raises(HTTPException) as bad_basic:
        webhooks._verify_postmark_auth(b"{}", "Basic wrong", None)
    assert bad_basic.value.status_code == 403
    webhooks._verify_postmark_auth(b"{}", "Basic dXNlcjpwYXNz", None)

    monkeypatch.delenv("NOTESNOOP_POSTMARK_BASIC_AUTH", raising=False)
    monkeypatch.setenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET", "secret")
    raw = b'{"ok":true}'
    signature = hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    webhooks._verify_postmark_auth(raw, None, signature)
    with pytest.raises(HTTPException):
        webhooks._verify_postmark_auth(raw, None, "bad")

    monkeypatch.delenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "true")
    webhooks._verify_mailgun_auth({}, None, None, None, None)
    monkeypatch.setenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "false")

    monkeypatch.setenv("NOTESNOOP_MAILGUN_BASIC_AUTH", "mg:user")
    with pytest.raises(HTTPException) as bad_mailgun_basic:
        webhooks._verify_mailgun_auth({}, "Basic wrong", None, None, None)
    assert bad_mailgun_basic.value.status_code == 403
    webhooks._verify_mailgun_auth({}, "Basic bWc6dXNlcg==", None, None, None)

    monkeypatch.delenv("NOTESNOOP_MAILGUN_BASIC_AUTH", raising=False)
    monkeypatch.setenv("NOTESNOOP_MAILGUN_SIGNING_KEY", "mailgun-secret")
    mg_timestamp = "1778335300"
    mg_token = "mailgun-token"
    mg_signature = hmac.new(b"mailgun-secret", f"{mg_timestamp}{mg_token}".encode("utf-8"), hashlib.sha256).hexdigest()
    webhooks._verify_mailgun_auth(
        {"signature": {"timestamp": mg_timestamp, "token": mg_token, "signature": mg_signature}},
        None,
        None,
        None,
        None,
    )
    with pytest.raises(HTTPException):
        webhooks._verify_mailgun_auth({}, None, mg_timestamp, mg_token, "bad")


def test_unsubscribe_tokens_and_realtime_helpers(monkeypatch):
    token = make_unsubscribe_token("workspace-1", "user-1")
    assert parse_unsubscribe_token(token) == {"workspace_id": "workspace-1", "user_id": "user-1"}
    assert parse_unsubscribe_token(token[:-1] + "x") is None
    assert parse_unsubscribe_token("not-base64") is None

    rows = iter([{"workspace_id": "workspace-1"}, None])
    monkeypatch.setattr(realtime, "one", lambda *_args, **_kwargs: next(rows))
    assert realtime._resolve_workspace_id(object(), "user-1", None) == "workspace-1"
    with pytest.raises(HTTPException) as missing_workspace:
        realtime._resolve_workspace_id(object(), "user-1", None)
    assert missing_workspace.value.status_code == 404

    monkeypatch.setattr(realtime, "one", lambda *_args, **_kwargs: {"id": "workspace-2"})
    assert realtime._resolve_workspace_id(object(), "user-1", "workspace-2") == "workspace-2"
    monkeypatch.setattr(realtime, "one", lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException):
        realtime._ensure_workspace_access(object(), "workspace-404")

    monkeypatch.setattr(realtime, "one", lambda *_args, **_kwargs: pytest.fail("malformed project_id should not query"))
    with pytest.raises(HTTPException) as malformed_project:
        realtime._resolve_project_filter_id(object(), "workspace-1", "not-a-uuid")
    assert malformed_project.value.status_code == 404

    project_id = "00000000-0000-0000-0000-000000000041"
    project_calls = []

    def fake_project_one(_cur, _sql, params):
        project_calls.append(params)
        return {"id": project_id}

    monkeypatch.setattr(realtime, "one", fake_project_one)
    assert realtime._resolve_project_filter_id(object(), "workspace-1", project_id.upper()) == project_id
    assert project_calls == [(project_id, "workspace-1")]

    assert realtime._sse("ping", {"workspace_id": "workspace-1"}) == 'event: ping\ndata: {"workspace_id": "workspace-1"}\n\n'

    class Notify:
        def __init__(self, payload):
            self.payload = payload

    class NotifyConn:
        def __init__(self, payloads):
            self.notifies = [Notify(payload) for payload in payloads]
            self.polls = 0

        def poll(self):
            self.polls += 1

    monkeypatch.setattr(realtime.select, "select", lambda *_args: ([], [], []))
    assert realtime._wait_for_notification(NotifyConn([]), 0.01) is None
    monkeypatch.setattr(realtime.select, "select", lambda conn, *_args: (conn, [], []))
    assert realtime._wait_for_notification(NotifyConn([]), 0.01) is None
    assert realtime._wait_for_notification(NotifyConn(['{"event":"note","workspace_id":"workspace-1"}']), 0.01)["event"] == "note"
    assert realtime._wait_for_notification(NotifyConn(["plain text"]), 0.01) == {"event": "message", "payload": "plain text"}
    assert realtime._wait_for_notification(NotifyConn(["[1,2,3]"]), 0.01) is None


def test_notes_filter_helpers_reject_malformed_uuid_before_query(monkeypatch):
    monkeypatch.setattr(notes, "one", lambda *_args, **_kwargs: pytest.fail("malformed IDs should not query"))

    with pytest.raises(HTTPException) as bad_project:
        notes._resolve_project_filter_id(object(), "workspace-1", "not-a-uuid")
    assert bad_project.value.status_code == 404

    with pytest.raises(HTTPException) as bad_person:
        notes._resolve_person_filter_id(object(), "workspace-1", "not-a-uuid")
    assert bad_person.value.status_code == 404

    with pytest.raises(HTTPException) as bad_project_list:
        notes._normalize_project_ids_or_422(["not-a-uuid"])
    assert bad_project_list.value.status_code == 422

    with pytest.raises(HTTPException) as bad_note_list:
        notes._normalize_note_ids_or_422(["not-a-uuid"])
    assert bad_note_list.value.status_code == 422

    project_id = "00000000-0000-0000-0000-000000000042"
    person_id = "00000000-0000-0000-0000-000000000043"
    note_id = "00000000-0000-0000-0000-000000000044"
    calls = []

    def fake_one(_cur, _sql, params):
        calls.append(params)
        return {"id": params[0]}

    monkeypatch.setattr(notes, "one", fake_one)
    assert notes._resolve_project_filter_id(object(), "workspace-1", project_id.upper()) == project_id
    assert notes._resolve_person_filter_id(object(), "workspace-1", person_id.upper()) == person_id
    assert calls == [(project_id, "workspace-1"), (person_id, "workspace-1")]
    project_ids = [project_id.upper(), project_id]
    assert notes._normalize_project_ids_or_422(project_ids) == [project_id, project_id]
    assert notes._normalize_note_ids_or_422([f"urn:uuid:{note_id}"]) == [note_id]


def test_notes_triage_bulk_actions_canonicalize_note_ids(monkeypatch):
    note_id = "00000000-0000-0000-0000-000000000055"
    process_cur = FakeCursor(fetchall_values=[[{"id": note_id, "is_personal": False, "ai_processing_status": "unprocessed"}]])

    @contextmanager
    def process_transaction(_user_id):
        yield process_cur

    monkeypatch.setattr(notes, "transaction", process_transaction)
    monkeypatch.setattr(notes, "consume_ai_quota", lambda *_args, **_kwargs: (True, None))
    user = SimpleNamespace(clerk_user_id="owner-1")

    result = notes.triage_process("workspace-1", {"note_ids": [f"urn:uuid:{note_id}"]}, user)

    assert result["data"]["queued"] == [note_id]
    assert _params_for_backend(process_cur, "id = ANY(%s::uuid[])")[0] == ("workspace-1", [note_id])

    archive_cur = FakeCursor(fetchall_values=[[{"id": note_id}]])

    @contextmanager
    def archive_transaction(_user_id):
        yield archive_cur

    monkeypatch.setattr(notes, "transaction", archive_transaction)
    monkeypatch.setattr(notes, "_archive_note_in_txn", lambda _cur, archived_note_id: archived_note_id == note_id)

    archived = notes.triage_archive("workspace-1", {"note_ids": [note_id.upper()]}, user)

    assert archived["data"]["archived"] == [note_id]
    assert _params_for_backend(archive_cur, "id = ANY(%s::uuid[])")[0] == ("workspace-1", [note_id])


def test_memory_validate_ids_rejects_malformed_uuid_before_query(monkeypatch):
    monkeypatch.setattr(memory, "one", lambda *_args, **_kwargs: pytest.fail("malformed IDs should not query"))

    with pytest.raises(HTTPException) as bad_project:
        memory._validate_project_ids(object(), "workspace-1", ["not-a-uuid"])
    assert bad_project.value.status_code == 422

    project_id = "00000000-0000-0000-0000-000000000044"
    assert memory._normalize_uuid_or_422(f"urn:uuid:{project_id}", "bad") == project_id
    calls = []

    def fake_one(_cur, _sql, params):
        calls.append(params)
        return {"count": 1}

    monkeypatch.setattr(memory, "one", fake_one)
    memory._validate_project_ids(object(), "workspace-1", [project_id.upper()])
    assert calls == [("workspace-1", [project_id])]


def test_memory_link_writers_canonicalize_uuid_aliases():
    project_id = "00000000-0000-0000-0000-000000000048"
    person_id = "00000000-0000-0000-0000-000000000049"
    cur = FakeCursor()

    memory._link_many(
        cur,
        "task_projects",
        "task_id",
        "project_id",
        "task-1",
        "workspace-1",
        [f"urn:uuid:{project_id}", project_id.upper()],
        "owner-1",
    )
    memory._apply_task_people(
        cur,
        "task-1",
        "workspace-1",
        [person_id.upper()],
        f"urn:uuid:{person_id}",
        "owner-1",
        replace=False,
    )

    assert _params_for_backend(cur, "INSERT INTO task_projects")[0][1] == project_id
    people_params = _params_for_backend(cur, "INSERT INTO task_people")[0]
    assert people_params[1] == person_id
    assert people_params[3] == "assignee"


def test_memory_canonicalizes_ask_source_ids():
    project_id = "00000000-0000-0000-0000-000000000050"
    task_id = "00000000-0000-0000-0000-000000000051"

    source_ids = memory._canonical_source_ids(
        {
            "note": [],
            "task": [f"urn:uuid:{task_id}"],
            "meeting": [],
            "report": [],
            "workflow": [],
            "company": [],
            "person": [],
            "project": [project_id.upper()],
        }
    )

    assert source_ids["project"] == [project_id]
    assert source_ids["task"] == [task_id]


def test_memory_task_dependencies_canonicalize_uuid_aliases(monkeypatch):
    task_id = "00000000-0000-0000-0000-000000000052"
    blocking_id = "00000000-0000-0000-0000-000000000053"
    cur = FakeCursor(
        fetchone_values=[
            {"id": task_id, "workspace_id": "workspace-1"},
            {"id": blocking_id, "workspace_id": "workspace-1"},
            None,
        ]
    )

    @contextmanager
    def fake_transaction(_user_id):
        yield cur

    monkeypatch.setattr(memory, "transaction", fake_transaction)
    monkeypatch.setattr(memory, "_task_payload", lambda _cur, _task_id: {"id": _task_id})
    user = SimpleNamespace(clerk_user_id="owner-1")

    result = memory.add_task_dependency(
        f"urn:uuid:{task_id}",
        SimpleNamespace(blocking_task_id=f"urn:uuid:{blocking_id}"),
        user,
    )

    assert result == {"data": {"id": task_id}}
    assert _params_for_backend(cur, "SELECT id, workspace_id FROM tasks WHERE id = %s") == [
        (task_id,),
        (blocking_id,),
    ]
    assert _params_for_backend(cur, "INSERT INTO task_dependencies")[0] == (
        task_id,
        blocking_id,
        "workspace-1",
        "owner-1",
    )


def test_update_report_filters_self_report_links_after_canonicalization(monkeypatch):
    report_id = "00000000-0000-0000-0000-000000000057"
    source_report_id = "00000000-0000-0000-0000-000000000058"
    cur = FakeCursor(
        fetchone_values=[
            {"id": report_id, "workspace_id": "workspace-1", "title": "Report", "status": "draft"},
            {"count": 1},
        ]
    )

    @contextmanager
    def fake_transaction(_user_id):
        yield cur

    monkeypatch.setattr(memory, "transaction", fake_transaction)
    monkeypatch.setattr(memory, "_report_payload", lambda _cur, normalized_report_id: {"id": normalized_report_id})
    user = SimpleNamespace(clerk_user_id="owner-1")

    result = memory.update_report(
        f"urn:uuid:{report_id}",
        memory.ReportUpdate(report_ids=[f"urn:uuid:{report_id}", report_id.upper(), source_report_id]),
        user,
    )

    assert result == {"data": {"id": report_id}}
    assert _params_for_backend(cur, "SELECT * FROM reports WHERE id = %s")[0] == (report_id,)
    assert _params_for_backend(cur, "DELETE FROM report_reports WHERE report_id = %s") == [(report_id,)]
    assert _params_for_backend(cur, "INSERT INTO report_reports") == [
        (report_id, source_report_id, "workspace-1", "owner-1")
    ]


def test_memory_list_filters_reject_malformed_project_id_before_query(monkeypatch):
    @contextmanager
    def fake_transaction(_user_id):
        yield FakeCursor()

    monkeypatch.setattr(memory, "transaction", fake_transaction)
    monkeypatch.setattr(memory, "many", lambda *_args, **_kwargs: pytest.fail("malformed project_id should not query"))
    user = SimpleNamespace(clerk_user_id="owner-1")

    for endpoint in (
        memory.list_tasks,
        memory.list_task_reminders,
        memory.list_meetings,
        memory.list_reports,
        memory.list_workflows,
    ):
        with pytest.raises(HTTPException) as exc:
            endpoint("workspace-1", project_id="not-a-uuid", user=user)
        assert exc.value.status_code == 422


def test_default_notes_and_tasks_lists_hide_archived_items(monkeypatch):
    user = SimpleNamespace(clerk_user_id="owner-1")

    note_cur = FakeCursor()

    @contextmanager
    def fake_note_transaction(_user_id):
        yield note_cur

    monkeypatch.setattr(notes, "transaction", fake_note_transaction)
    notes.list_notes("workspace-1", user=user)
    note_sql, note_params = next((sql, params) for sql, params in note_cur.executed if "FROM notes n" in sql)
    assert "n.archived_at IS NULL" in note_sql
    assert note_params == ("workspace-1",)

    include_note_cur = FakeCursor()

    @contextmanager
    def fake_include_note_transaction(_user_id):
        yield include_note_cur

    monkeypatch.setattr(notes, "transaction", fake_include_note_transaction)
    notes.list_notes("workspace-1", include_archived=True, user=user)
    include_note_sql, _ = next((sql, params) for sql, params in include_note_cur.executed if "FROM notes n" in sql)
    assert "n.archived_at IS NULL" not in include_note_sql

    task_cur = FakeCursor()

    @contextmanager
    def fake_task_transaction(_user_id):
        yield task_cur

    monkeypatch.setattr(memory, "transaction", fake_task_transaction)
    memory.list_tasks("workspace-1", user=user)
    task_sql, task_params = next((sql, params) for sql, params in task_cur.executed if "FROM tasks t" in sql)
    assert "t.status <> 'archived'" in task_sql
    assert task_params == ("workspace-1",)

    include_task_cur = FakeCursor()

    @contextmanager
    def fake_include_task_transaction(_user_id):
        yield include_task_cur

    monkeypatch.setattr(memory, "transaction", fake_include_task_transaction)
    memory.list_tasks("workspace-1", include_archived=True, user=user)
    include_task_sql, _ = next((sql, params) for sql, params in include_task_cur.executed if "FROM tasks t" in sql)
    assert "t.status <> 'archived'" not in include_task_sql


def test_memory_search_defaults_hide_archived_tasks_and_reports():
    cur = FakeCursor()

    notes._memory_search_results(cur, "workspace-1", "weekly", None, None)
    task_sql = next(sql for sql, _params in cur.executed if "FROM tasks item" in sql)
    report_sql = next(sql for sql, _params in cur.executed if "FROM reports item" in sql)
    assert "item.status <> 'archived'" in task_sql
    assert "item.status <> 'archived'" in report_sql

    include_cur = FakeCursor()
    notes._memory_search_results(include_cur, "workspace-1", "weekly", None, None, include_archived=True)
    include_task_sql = next(sql for sql, _params in include_cur.executed if "FROM tasks item" in sql)
    include_report_sql = next(sql for sql, _params in include_cur.executed if "FROM reports item" in sql)
    assert "item.status <> 'archived'" not in include_task_sql
    assert "item.status <> 'archived'" not in include_report_sql

    context_cur = FakeCursor()
    notes._memory_context_results(context_cur, "workspace-1", "project-1", None)
    context_task_sql = next(sql for sql, _params in context_cur.executed if "FROM tasks item" in sql)
    context_report_sql = next(sql for sql, _params in context_cur.executed if "FROM reports item" in sql)
    assert "item.status <> 'archived'" in context_task_sql
    assert "item.status <> 'archived'" in context_report_sql


def test_home_loose_notes_reuses_materialized_scope(monkeypatch):
    cur = FakeCursor()
    many_calls = []

    @contextmanager
    def fake_transaction(_user_id):
        yield cur

    def fake_many(_cur, sql, params=()):
        many_calls.append((sql, params))
        return []

    monkeypatch.setattr(notes, "transaction", fake_transaction)
    monkeypatch.setattr(notes, "many", fake_many)
    monkeypatch.setattr(notes, "one", lambda *_args, **_kwargs: {})

    notes.home("workspace-1", user=SimpleNamespace(clerk_user_id="owner-1"))

    assert any("home_visible_note_projects_note_idx" in sql for sql, _params in cur.executed)
    loose_sql, loose_params = next(
        (sql, params)
        for sql, params in many_calls
        if "FROM home_visible_notes n" in sql
        and "FROM home_visible_note_projects np" in sql
        and "p.kind <> 'inbox'" in sql
    )
    assert "FROM notes n" not in loose_sql
    assert loose_params == ()


def test_note_payload_scopes_review_suggestions_to_target_user():
    cur = FakeCursor(
        fetchone_values=[
            {
                "id": "note-1",
                "workspace_id": "workspace-1",
                "title": "Note",
                "body": "Body",
                "note_kind": "note",
            }
        ],
    )

    payload = notes.get_note_payload(cur, "note-1", "owner-1")

    assert payload["id"] == "note-1"
    review_sql, review_params = next(
        (sql, params)
        for sql, params in cur.executed
        if "FROM review_queue rq" in sql
    )
    assert "rq.target_user_id = %s" in review_sql
    assert review_params == ("note-1", "owner-1", "note-1")


def test_get_note_canonicalizes_route_uuid_before_payload_lookup(monkeypatch):
    note_id = "00000000-0000-0000-0000-000000000056"
    cur = FakeCursor()
    looked_up = []

    @contextmanager
    def fake_transaction(_user_id):
        yield cur

    def fake_get_note_payload(_cur, normalized_note_id, target_user_id):
        looked_up.append((normalized_note_id, target_user_id))
        return {"id": normalized_note_id, "workspace_id": "workspace-1"}

    monkeypatch.setattr(notes, "transaction", fake_transaction)
    monkeypatch.setattr(notes, "get_note_payload", fake_get_note_payload)
    user = SimpleNamespace(clerk_user_id="owner-1")

    result = notes.get_note(f"urn:uuid:{note_id}", user)

    assert result == {"data": {"id": note_id, "workspace_id": "workspace-1"}}
    assert looked_up == [(note_id, "owner-1")]
    assert _params_for_backend(cur, "INSERT INTO recently_accessed")[0] == ("owner-1", note_id)
    assert _params_for_backend(cur, "INSERT INTO note_viewers")[0] == (note_id, "owner-1", "workspace-1")


def test_worker_matching_claim_finish_and_process_extract(monkeypatch):
    rows = [{"id": "p1", "name": "Morgan Lee"}, {"id": "p2", "name": "Jordan Kim"}]
    assert worker._best_match("morgan lee", rows)[0]["id"] == "p1"
    assert worker._best_match("Morgn Lee", rows)[1] >= 0.80
    assert worker._best_match("Unrelated", rows)[0] is None
    assert worker._best_match("Nobody", [])[1] == 0.0

    claim_conn = FakeConn(FakeCursor(fetchone_values=[{"id": "job-1", "kind": "extract"}]))
    returned = []
    monkeypatch.setattr(worker, "get_conn", lambda: claim_conn)
    monkeypatch.setattr(worker, "put_conn", lambda conn: returned.append(conn))
    assert worker._claim_job()["id"] == "job-1"
    assert claim_conn.commits == 1
    assert returned[-1] is claim_conn

    finish_conn = FakeConn()
    monkeypatch.setattr(worker, "get_conn", lambda: finish_conn)
    worker._finish_job("job-1", "done")
    assert finish_conn.commits == 1
    assert any("UPDATE ai_jobs" in sql for sql, _params in finish_conn.cursor_obj.executed)

    retry_conn = FakeConn()
    monkeypatch.setattr(worker, "get_conn", lambda: retry_conn)
    worker._retry_job("job-1", "429 Too Many Requests", 30)
    assert retry_conn.commits == 1
    assert any("state = 'queued'" in sql for sql, _params in retry_conn.cursor_obj.executed)

    async def fake_extract(_body, _people, _projects, _companies=None):
        return {
            "people": [
                {"name": "Morgan Lee", "confidence": 0.97},
                {"name": "New Person", "confidence": 0.78},
                {"name": "Low Person", "confidence": 0.2},
                {"name": "", "confidence": 0.99},
            ],
            "projects": [
                {"name": "Apollo", "confidence": 0.96},
                {"name": "Shared Deal", "confidence": 0.94},
                {"name": "New Deal", "confidence": 0.8},
                {"name": "Personal", "confidence": 0.95},
                {"name": "", "confidence": 0.99},
            ],
            "tasks": [{"title": "Send Apollo follow-up", "confidence": 0.86, "due_date": "2026-05-15"}],
        }

    async def fake_embed(_text):
        return EmbeddingResult([0.0], "test-model", "test", 1, "sha")

    note = {
        "id": "note-1",
        "workspace_id": "workspace-1",
        "title": "Apollo update",
        "body": "Morgan mentioned Apollo.",
        "is_personal": False,
        "created_by": "creator-1",
    }
    people = [{"id": "person-1", "name": "Morgan Lee"}]
    projects = [
        {"id": "project-1", "name": "Apollo", "kind": "user", "shared": False},
        {"id": "project-2", "name": "Shared Deal", "kind": "user", "shared": True},
        {"id": "project-3", "name": "Personal", "kind": "personal", "shared": False},
    ]
    conn_queue = [FakeConn(FakeCursor(fetchone_values=[None])), FakeConn()]
    used_conns = []

    def next_conn():
        conn = conn_queue.pop(0)
        used_conns.append(conn)
        return conn

    finish_calls = []
    upserts = []
    monkeypatch.setattr(worker, "_load_context", lambda _cur, _note_id: (note, people, projects))
    monkeypatch.setattr(worker, "get_conn", next_conn)
    monkeypatch.setattr(worker, "extract_entities", fake_extract)
    monkeypatch.setattr(worker, "embed_text", fake_embed)
    monkeypatch.setattr(worker, "upsert_note_embedding", lambda cur, loaded_note, result: upserts.append((loaded_note, result)))
    monkeypatch.setattr(worker, "_finish_job", lambda job_id, state, error=None: finish_calls.append((job_id, state, error)))
    asyncio.run(worker._process_extract({"id": "job-extract", "note_id": "note-1", "target_user_id": None}))

    assert finish_calls[-1] == ("job-extract", "done", None)
    assert upserts[0][0]["id"] == "note-1"
    executed_sql = "\n".join(sql for conn in used_conns for sql, _params in conn.cursor_obj.executed)
    assert "INSERT INTO note_people_links" in executed_sql
    assert "INSERT INTO review_queue" in executed_sql
    assert "INSERT INTO calibration_events" in executed_sql
    assert "INSERT INTO note_projects" in executed_sql
    review_params = [
        params
        for conn in used_conns
        for sql, params in conn.cursor_obj.executed
        if "INSERT INTO review_queue" in sql
    ]
    assert review_params
    assert isinstance(review_params[0][-1], str)
    assert json.loads(review_params[0][-1])["name"] == "New Person"
    review_payloads = [json.loads(params[-1]) for params in review_params]
    task_payload = next(payload for payload in review_payloads if payload.get("title") == "Send Apollo follow-up")
    assert task_payload["candidate_key"].startswith("task:note-1:action_item")
    assert task_payload["due_at"] == "2026-05-15"
    assert "INSERT INTO tasks" not in executed_sql


def test_worker_materializes_ai_memory_idempotently():
    note = {
        "id": "note-1",
        "workspace_id": "workspace-1",
        "title": "Weekly call",
        "body": "Action: follow up with legal.",
        "note_kind": "call",
        "occurred_at": "2026-05-09T10:00:00Z",
        "created_by": "creator-1",
    }
    cur = FakeCursor(
        fetchone_values=[{"id": "task-1"}, {"id": "meeting-1"}],
        fetchall_values=[[{"id": "project-1"}], [{"person_id": "person-1"}]],
    )

    result = worker._materialize_ai_memory(
        cur,
        note,
        {"tasks": [{"title": "follow up with legal", "due_date": "2026-05-15"}, {"title": "follow up with legal"}]},
        "creator-1",
    )

    assert result == {"tasks": 1, "meetings": 1, "reports": 0, "workflows": 0, "companies": 0}
    executed_sql = "\n".join(sql for sql, _params in cur.executed)
    assert "ON CONFLICT (source_note_id, source_kind, lower(title))" in executed_sql
    assert "ON CONFLICT (source_note_id, source_kind)" in executed_sql
    assert "INSERT INTO task_notes" in executed_sql
    assert "INSERT INTO meeting_notes" in executed_sql
    assert "INSERT INTO task_projects" in executed_sql
    assert "INSERT INTO task_people" in executed_sql
    assert "INSERT INTO meeting_people" in executed_sql
    task_inserts = [params for sql, params in cur.executed if "INSERT INTO tasks" in sql]
    assert len(task_inserts) == 1
    assert task_inserts[0][1] == "follow up with legal"
    assert task_inserts[0][5] == "2026-05-15T12:00:00+00:00"
    assert task_inserts[0][8] == "action_item"
    assert task_inserts[0][9] is None


def test_worker_materializes_accepted_structured_review_candidate():
    project_id = "00000000-0000-0000-0000-000000000001"
    person_id = "00000000-0000-0000-0000-000000000002"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Send edited Apollo pack",
        "description": "Edited by reviewer",
        "status": "doing",
        "priority": 1,
        "due_at": "2026-05-20",
        "source_kind": "action_item",
        "confidence": 0.86,
        "project_ids": [project_id],
        "person_ids": [person_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [{"id": project_id}],
            [{"id": project_id}],
            [{"id": person_id}],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    assert task_params[1] == "Send edited Apollo pack"
    assert task_params[2] == "Edited by reviewer"
    assert task_params[3] == "doing"
    assert task_params[4] == 1
    assert task_params[9] == "review-task-1"
    assert task_params[10] == 0.86
    assert json.loads(task_params[11])["title"] == "Send edited Apollo pack"
    assert "INSERT INTO task_projects" in "\n".join(sql for sql, _params in cur.executed)
    assert "INSERT INTO task_people" in "\n".join(sql for sql, _params in cur.executed)


def test_worker_drops_malformed_and_cross_workspace_person_ids_from_structured_reviews():
    accepted_person_id = "00000000-0000-0000-0000-000000000004"
    missing_person_id = "00000000-0000-0000-0000-000000000005"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Keep person links scoped",
        "person_ids": ["not-a-uuid", missing_person_id, accepted_person_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [],
            [{"id": accepted_person_id}],
            [],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    linked_person_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_people" in sql
    ]
    assert linked_person_ids == [accepted_person_id]
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    assert json.loads(task_params[11])["person_ids"] == [accepted_person_id]
    assert payload["person_ids"] == [accepted_person_id]


def test_worker_filters_structured_review_secondary_memory_ids_before_linking():
    task_id = "00000000-0000-0000-0000-000000000038"
    meeting_id = "00000000-0000-0000-0000-000000000039"
    workflow_id = "00000000-0000-0000-0000-000000000040"
    report_source_id = "00000000-0000-0000-0000-000000000041"
    stale_task_id = "00000000-0000-0000-0000-000000000042"
    review = {
        "id": "review-report-1",
        "workspace_id": "workspace-1",
        "entity_kind": "report",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Review secondary links",
        "task_ids": ["not-a-uuid", stale_task_id, task_id],
        "meeting_ids": [meeting_id],
        "workflow_ids": [workflow_id],
        "report_ids": [report_source_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "report-1"},
        ],
        fetchall_values=[
            [],
            [],
            [],
            [{"id": task_id}],
            [{"id": meeting_id}],
            [{"id": workflow_id}],
            [{"id": report_source_id}],
        ],
    )

    report_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert report_id == "report-1"
    assert _params_for_backend(cur, "INSERT INTO report_tasks") == [("report-1", task_id, "workspace-1", "owner-1")]
    assert _params_for_backend(cur, "INSERT INTO report_meetings") == [("report-1", meeting_id, "workspace-1", "owner-1")]
    assert _params_for_backend(cur, "INSERT INTO report_workflows") == [("report-1", workflow_id, "workspace-1", "owner-1")]
    assert _params_for_backend(cur, "INSERT INTO report_reports") == [("report-1", report_source_id, "workspace-1", "owner-1")]
    report_params = next(params for sql, params in cur.executed if "INSERT INTO reports" in sql)
    source_payload = json.loads(report_params[9])
    assert source_payload["task_ids"] == [task_id]
    assert source_payload["meeting_ids"] == [meeting_id]
    assert source_payload["workflow_ids"] == [workflow_id]
    assert source_payload["report_ids"] == [report_source_id]


def test_worker_canonicalizes_uuid_aliases_before_uuid_array_queries():
    project_id = "00000000-0000-0000-0000-000000000045"
    task_id = "00000000-0000-0000-0000-000000000046"
    cur = FakeCursor(
        fetchall_values=[
            [{"id": project_id}],
            [{"id": task_id}],
        ]
    )

    assert worker._visible_non_personal_project_ids(
        cur, "workspace-1", "owner-1", [f"urn:uuid:{project_id}"]
    ) == [project_id]
    assert worker._visible_workspace_entity_ids(
        cur, "tasks", "workspace-1", [f"urn:uuid:{task_id}"]
    ) == [task_id]

    assert _params_for_backend(cur, "p.id = ANY(%s::uuid[])")[0][1] == [project_id]
    assert _params_for_backend(cur, "FROM tasks")[0][1] == [task_id]


def test_worker_materializes_review_candidate_with_current_note_project_links():
    inbox_id = "00000000-0000-0000-0000-000000000011"
    meridian_id = "00000000-0000-0000-0000-000000000012"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Send Meridian pricing",
        "description": "Accepted after the Project Meridian suggestion.",
        "project_ids": [inbox_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "meeting"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [{"id": inbox_id}, {"id": meridian_id}],
            [{"id": inbox_id}, {"id": meridian_id}],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    linked_project_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_projects" in sql
    ]
    assert linked_project_ids == [inbox_id, meridian_id]


def test_worker_materializes_review_candidate_with_current_note_company_links():
    company_id = "00000000-0000-0000-0000-000000000031"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Send Northstar diligence summary",
        "description": "Accepted after the Northstar company suggestion.",
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [],
            [],
            [{"company_id": company_id}],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    linked_company_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_companies" in sql
    ]
    assert linked_company_ids == [company_id]
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    assert json.loads(task_params[11])["company_ids"] == [company_id]
    assert payload["company_ids"] == [company_id]
    company_context_sql = next(sql for sql, _params in cur.executed if "FROM company_notes" in sql)
    assert "ORDER BY linked_at" in company_context_sql
    assert "created_at" not in company_context_sql


def test_worker_merges_review_payload_and_current_note_person_company_links():
    payload_person_id = "00000000-0000-0000-0000-000000000034"
    linked_person_id = "00000000-0000-0000-0000-000000000035"
    payload_company_id = "00000000-0000-0000-0000-000000000036"
    linked_company_id = "00000000-0000-0000-0000-000000000037"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Merge explicit and accepted context",
        "person_ids": [payload_person_id],
        "company_ids": [payload_company_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [],
            [{"id": payload_person_id}],
            [{"person_id": linked_person_id}],
            [{"id": payload_company_id}],
            [{"company_id": linked_company_id}],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    linked_person_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_people" in sql
    ]
    linked_company_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_companies" in sql
    ]
    assert linked_person_ids == [payload_person_id, linked_person_id]
    assert linked_company_ids == [payload_company_id, linked_company_id]
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    source_payload = json.loads(task_params[11])
    assert source_payload["person_ids"] == [payload_person_id, linked_person_id]
    assert source_payload["company_ids"] == [payload_company_id, linked_company_id]


def test_worker_drops_missing_company_ids_from_structured_review_payloads():
    missing_company_id = "00000000-0000-0000-0000-000000000032"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Do not trust stale company IDs",
        "company_ids": [missing_company_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [],
            [],
            [],
            [],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    assert "INSERT INTO task_companies" not in "\n".join(sql for sql, _params in cur.executed)
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    assert json.loads(task_params[11])["company_ids"] == []
    assert payload["company_ids"] == []


def test_worker_materializes_company_review_with_matched_company_id_without_duplicate():
    company_id = "00000000-0000-0000-0000-000000000047"
    review = {
        "id": "review-company-1",
        "workspace_id": "workspace-1",
        "entity_kind": "company",
        "entity_id": "note-1",
    }
    payload = {
        "name": "Northstar alias",
        "domain": "northstar.example",
        "matched_company_id": f"urn:uuid:{company_id}",
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": company_id},
            {"id": company_id},
            {"id": company_id},
        ],
        fetchall_values=[
            [],
            [],
            [{"id": company_id}],
            [],
        ],
    )

    materialized_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert materialized_id == company_id
    executed_sql = "\n".join(sql for sql, _params in cur.executed)
    assert "INSERT INTO companies" not in executed_sql
    assert "UPDATE companies" in executed_sql
    assert payload["matched_company_id"] == company_id
    assert payload["company_ids"] == [company_id]
    update_params = next(params for sql, params in cur.executed if "UPDATE companies" in sql)
    assert json.loads(update_params[6])["matched_company_id"] == company_id


def test_worker_rejects_personal_projects_from_structured_review_payloads():
    personal_id = "00000000-0000-0000-0000-000000000021"
    other_workspace_id = "00000000-0000-0000-0000-000000000023"
    project_id = "00000000-0000-0000-0000-000000000022"
    review = {
        "id": "review-task-1",
        "workspace_id": "workspace-1",
        "entity_kind": "task",
        "entity_id": "note-1",
    }
    payload = {
        "title": "Keep personal project private",
        "project_ids": [personal_id, "not-a-uuid", other_workspace_id, project_id],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
        ],
        fetchall_values=[
            [],
            [{"id": project_id}],
        ],
    )

    task_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert task_id == "task-1"
    linked_project_ids = [
        params[1]
        for sql, params in cur.executed
        if "INSERT INTO task_projects" in sql
    ]
    assert linked_project_ids == [project_id]
    task_params = next(params for sql, params in cur.executed if "INSERT INTO tasks" in sql)
    assert json.loads(task_params[11])["project_ids"] == [project_id]
    assert payload["project_ids"] == [project_id]
    visibility_sql, visibility_params = next(
        (sql, params)
        for sql, params in cur.executed
        if "JOIN workspaces w ON w.id = p.workspace_id" in sql
    )
    assert "coalesce(w.inbox_mode, 'per_user_private') = 'shared' AND p.shared = TRUE" in visibility_sql
    assert "coalesce(w.inbox_mode, 'per_user_private') <> 'shared'" in visibility_sql
    assert "p.created_by = %s" in visibility_sql
    assert visibility_params == (
        "workspace-1",
        [personal_id, other_workspace_id, project_id],
        "owner-1",
    )


def test_worker_materializes_full_memory_graph_from_ai_payload():
    note = {
        "id": "note-graph-1",
        "workspace_id": "workspace-1",
        "title": "Apollo operating note",
        "body": "Northstar call. Workflow: IC memo loop. Brief: weekly risks.",
        "note_kind": "note",
        "occurred_at": "2026-05-09T10:00:00Z",
        "created_by": "creator-1",
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "company-1"},
            {"id": "task-1"},
            {"id": "meeting-1"},
            {"id": "workflow-1"},
            {"id": "report-1"},
        ],
        fetchall_values=[[{"id": "project-1"}], [{"person_id": "person-1"}]],
    )

    result = worker._materialize_ai_memory(
        cur,
        note,
        {
            "companies": [{"name": "Northstar", "domain": "northstar.example"}],
            "tasks": [{"title": "send weekly risk brief", "due_date": "2026-05-15"}],
            "meetings": [{"title": "Northstar call", "summary": "Discussed diligence risks."}],
            "workflows": [{"name": "IC memo loop", "description": "Repeat diligence memo review."}],
            "reports": [{"title": "Weekly risks brief", "summary": "Risks and next actions."}],
        },
        "creator-1",
    )

    assert result == {"tasks": 1, "meetings": 1, "reports": 1, "workflows": 1, "companies": 1}
    executed_sql = "\n".join(sql for sql, _params in cur.executed)
    assert "INSERT INTO companies" in executed_sql
    assert "INSERT INTO company_notes" in executed_sql
    assert "INSERT INTO company_projects" in executed_sql
    assert "INSERT INTO company_people" in executed_sql
    assert "INSERT INTO meetings" in executed_sql
    assert "INSERT INTO workflows" in executed_sql
    assert "INSERT INTO workflow_notes" in executed_sql
    assert "INSERT INTO workflow_tasks" in executed_sql
    assert "INSERT INTO reports" in executed_sql
    assert "INSERT INTO task_companies" in executed_sql
    assert "INSERT INTO meeting_companies" in executed_sql
    assert "INSERT INTO workflow_companies" in executed_sql
    assert "INSERT INTO report_companies" in executed_sql


def test_worker_resolves_email_company_mentions_into_review_links():
    note = {
        "id": "email-note-1",
        "workspace_id": "workspace-1",
        "title": "Forwarded diligence note",
        "body": "Northstar email: todo send security pack.",
        "note_kind": "email",
        "occurred_at": "2026-05-09T10:00:00Z",
        "created_by": "creator-1",
    }
    data = {
        "companies": [{"name": "Northstar Advisory", "confidence": 0.95}],
        "tasks": [{"title": "Send security pack", "company_names": ["Northstar Advisory"], "confidence": 0.9}],
        "meetings": [{"title": "Northstar partner sync", "company_names": ["Northstar Advisory"], "confidence": 0.86}],
        "workflows": [{"name": "Security review loop", "company_names": ["Northstar Advisory"], "confidence": 0.83}],
        "reports": [{"title": "Security brief", "company_names": ["Northstar Advisory"], "confidence": 0.82}],
    }
    cur = FakeCursor(fetchall_values=[
        [{"id": "company-1", "name": "Northstar Advisory"}],
    ])

    linked = worker._enrich_company_links_from_context(
        cur,
        note,
        data,
        "creator-1",
        ["project-1"],
        ["person-1"],
        [{"id": "company-1", "name": "Northstar Advisory"}],
        "job-1",
    )
    candidates = worker._structured_memory_candidates(note, data, ["project-1"], ["person-1"])
    by_kind = {kind: payload for kind, payload in candidates}

    assert linked == ["company-1"]
    assert "company" not in by_kind
    assert by_kind["task"]["company_ids"] == ["company-1"]
    assert by_kind["meeting"]["company_ids"] == ["company-1"]
    assert by_kind["workflow"]["company_ids"] == ["company-1"]
    assert by_kind["report"]["company_ids"] == ["company-1"]
    executed_sql = "\n".join(sql for sql, _params in cur.executed)
    assert "INSERT INTO company_notes" in executed_sql
    assert "INSERT INTO company_projects" in executed_sql
    assert "INSERT INTO company_people" in executed_sql


def test_worker_personal_skip_and_failure_paths(monkeypatch):
    personal_note = {
        "id": "note-personal",
        "workspace_id": "workspace-1",
        "title": "Personal",
        "body": "Private",
        "is_personal": True,
        "created_by": "creator-1",
    }
    conn = FakeConn()
    finish_calls = []
    monkeypatch.setattr(worker, "_load_context", lambda _cur, _note_id: (personal_note, [], []))
    monkeypatch.setattr(worker, "get_conn", lambda: conn)
    monkeypatch.setattr(worker, "put_conn", lambda _conn: None)
    monkeypatch.setattr(worker, "_finish_job", lambda job_id, state, error=None: finish_calls.append((job_id, state, error)))
    asyncio.run(worker._process_extract({"id": "job-personal", "note_id": "note-personal", "target_user_id": "creator-1"}))
    assert finish_calls[-1] == ("job-personal", "done", None)
    assert conn.commits == 1

    async def failing_process(_job):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_process_extract", failing_process)
    finish_calls.clear()
    asyncio.run(worker.handle_job({"id": "job-fail", "kind": "extract", "note_id": "note-1"}))
    assert finish_calls[-1] == ("job-fail", "failed", "boom")

    retry_calls = []

    async def transient_process(_job):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(worker, "_process_extract", transient_process)
    monkeypatch.setattr(worker, "_retry_job", lambda job_id, error, delay: retry_calls.append((job_id, error, delay)))
    monkeypatch.setattr(worker, "RETRY_BACKOFF_SECONDS", 7)
    monkeypatch.setattr(worker, "MAX_JOB_ATTEMPTS", 3)
    finish_calls.clear()
    asyncio.run(worker.handle_job({"id": "job-retry", "kind": "extract", "note_id": "note-1", "attempts": 1}))
    assert retry_calls[-1] == ("job-retry", "429 Too Many Requests", 7)
    assert finish_calls == []

    asyncio.run(worker.handle_job({"id": "job-retry-exhausted", "kind": "extract", "note_id": "note-1", "attempts": 3}))
    assert finish_calls[-1] == ("job-retry-exhausted", "failed", "429 Too Many Requests")

    finish_calls.clear()
    asyncio.run(worker.handle_job({"id": "job-noop", "kind": "unknown"}))
    assert finish_calls[-1] == ("job-noop", "done", None)
