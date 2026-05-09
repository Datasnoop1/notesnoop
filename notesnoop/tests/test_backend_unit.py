from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))

from app import auth, email_ingest, ollama_client, worker
from app.briefing import make_unsubscribe_token, parse_unsubscribe_token
from app.embeddings import EmbeddingResult
from app.routers import realtime, webhooks


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
        dev_auth=False,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    auth._jwks_cache = {}
    auth._jwks_fetched_at = 0

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

    async def fake_extract(_body, _people, _projects):
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

    finish_calls.clear()
    asyncio.run(worker.handle_job({"id": "job-noop", "kind": "unknown"}))
    assert finish_calls[-1] == ("job-noop", "done", None)
