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
from app import auth, email_ingest, main, ollama_client, worker
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


def test_generated_project_report_access_and_personal_guards(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    payload = memory.ProjectReportGenerateRequest()

    async def unexpected_generate(*_args, **_kwargs):
        raise AssertionError("generation should not run")

    monkeypatch.setattr(memory, "generate_project_report", unexpected_generate)

    inaccessible = FakeCursor(
        fetchone_values=[
            {"id": "project-1", "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"},
            {"allowed": False},
        ]
    )

    @contextmanager
    def inaccessible_transaction(_user_id):
        yield inaccessible

    monkeypatch.setattr(memory, "transaction", inaccessible_transaction)
    with pytest.raises(HTTPException) as denied:
        memory.generate_project_memory_report("project-1", payload, user)
    assert denied.value.status_code == 404

    personal = FakeCursor(
        fetchone_values=[
            {"id": "project-personal", "workspace_id": "workspace-1", "name": "Personal", "kind": "personal"},
            {"allowed": True},
        ]
    )

    @contextmanager
    def personal_transaction(_user_id):
        yield personal

    monkeypatch.setattr(memory, "transaction", personal_transaction)
    with pytest.raises(HTTPException) as blocked:
        memory.generate_project_memory_report("project-personal", payload, user)
    assert blocked.value.status_code == 403


def test_generated_project_report_rejects_empty_sources(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    read_cursor = FakeCursor(
        fetchone_values=[
            {"id": "project-1", "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"},
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
        memory.generate_project_memory_report("project-1", memory.ProjectReportGenerateRequest(), user)
    assert empty.value.status_code == 422
    assert "needs notes, tasks, meetings, or prior reports" in empty.value.detail


def test_generated_project_report_links_deduped_sources_and_counts(monkeypatch):
    user = auth.CurrentUser(clerk_user_id="user-1")
    project = {"id": "project-1", "workspace_id": "workspace-1", "name": "Apollo", "kind": "user"}
    read_cursor = FakeCursor(
        fetchone_values=[project, {"allowed": True}],
        fetchall_values=[
            [{"id": "note-1", "title": "Memo"}, {"id": "note-1", "title": "Memo again"}, {"id": "note-2", "title": "Call"}],
            [{"id": "task-1", "title": "Follow up"}, {"id": "task-1", "title": "Follow up duplicate"}],
            [{"id": "meeting-1", "title": "Partner sync"}],
            [{"id": "prior-report-1", "title": "Prior"}, {"id": "prior-report-1", "title": "Prior duplicate"}],
            [{"id": "person-1", "name": "Morgan"}, {"id": "person-1", "name": "Morgan again"}, {"id": "person-2", "name": "Jordan"}],
            [{"id": "company-1", "name": "Northstar"}, {"id": "company-1", "name": "Northstar duplicate"}],
        ],
    )
    write_cursor = FakeCursor(fetchone_values=[project, {"allowed": True}, {"id": "report-1", "workspace_id": "workspace-1"}])
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
        "project-1",
        memory.ProjectReportGenerateRequest(title="Custom report", variant="quick"),
        user,
    )

    assert captured == {
        "project_people": ["person-1", "person-2"],
        "project_companies": ["company-1"],
        "notes": ["note-1", "note-2"],
        "tasks": ["task-1"],
        "meetings": ["meeting-1"],
        "reports": ["prior-report-1"],
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

    assert params_for("INSERT INTO reports")[0] == ("workspace-1", "Custom report", "Grounded body", "user-1")
    assert params_for("INSERT INTO report_projects") == [("report-1", "project-1", "workspace-1", "user-1")]
    assert [params[1] for params in params_for("INSERT INTO report_notes")] == ["note-1", "note-2"]
    assert [params[1] for params in params_for("INSERT INTO report_tasks")] == ["task-1"]
    assert [params[1] for params in params_for("INSERT INTO report_people")] == ["person-1", "person-2"]
    assert [params[1] for params in params_for("INSERT INTO report_companies")] == ["company-1"]


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
        "project_ids": ["project-1"],
        "person_ids": ["person-1"],
    }
    cur = FakeCursor(
        fetchone_values=[
            {"id": "note-1", "workspace_id": "workspace-1", "body": "Original note", "note_kind": "note"},
            {"id": "task-1"},
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
    assert "INSERT INTO report_companies" in executed_sql


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
