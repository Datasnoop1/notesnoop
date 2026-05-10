from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notesnoop-backend"))

from app import ollama_client, worker


class RecordingCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.executed = []

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


def test_deterministic_fallback_extracts_messy_multi_action_notes_with_due_hints():
    note = (
        "Northstar / Apollo messy follow-up dump:\n"
        "- Action: Morgan to send revised MSA by 2026-05-15; Priya needs to confirm security owner tomorrow\n"
        "* TODO: chase Acme legal for redlines due Friday; FYI budget looks fine\n"
        "We need a CRM migration checklist before Monday."
    )

    tasks = ollama_client.deterministic_extract_tasks(note)
    titles = [task["title"] for task in tasks]

    assert titles == [
        "Morgan to send revised MSA by 2026-05-15",
        "Priya needs to confirm security owner tomorrow",
        "chase Acme legal for redlines due Friday",
        "We need a CRM migration checklist before Monday",
    ]
    assert tasks[0]["due_date"] == "2026-05-15"
    assert tasks[1]["due_date_hint"] == "tomorrow"
    assert tasks[2]["due_date_hint"] == "Friday"
    assert tasks[3]["due_date_hint"] == "Monday"
    assert all(task["confidence"] >= 0.8 for task in tasks)


def test_ollama_extraction_contract_keeps_structured_task_and_relationship_fields(monkeypatch):
    posted = {}
    ai_response = {
        "people": [{"name": "Morgan Lee", "confidence": 0.93, "relationship": "client sponsor"}],
        "projects": [{"name": "Apollo CRM", "confidence": 0.91}],
        "companies": [{"name": "Northstar Health", "domain": "northstar.example", "confidence": 0.9}],
        "tasks": [
            {
                "title": "Send revised MSA",
                "description": "Morgan needs the Acme redlines folded into the Northstar MSA.",
                "due_date": "2026-05-15",
                "priority": 1,
                "status": "doing",
                "company_ids": ["company-northstar"],
                "task_ids": ["task-prereq-redlines"],
                "relationship_hints": [
                    {"kind": "blocks", "target": "task-prereq-redlines"},
                    {"kind": "owned_by", "target": "Morgan Lee"},
                ],
                "confidence": 0.88,
            }
        ],
        "meetings": [],
        "workflows": [],
        "reports": [],
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps(ai_response)}}

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

    result = asyncio.run(
        ollama_client.extract_entities(
            "Northstar Health Apollo CRM call. Action: Send revised MSA by 2026-05-15.",
            ["Morgan Lee"],
            ["Apollo CRM"],
            ["Northstar Health"],
        )
    )

    system_prompt = posted["json"]["messages"][0]["content"]
    for field in ("description", "priority", "status", "company_ids", "task_ids", "relationship_hints"):
        assert field in system_prompt

    task = result["tasks"][0]
    assert task["description"].startswith("Morgan needs")
    assert task["priority"] == 1
    assert task["status"] == "doing"
    assert task["company_ids"] == ["company-northstar"]
    assert task["task_ids"] == ["task-prereq-redlines"]
    assert task["relationship_hints"][0]["kind"] == "blocks"


def test_review_candidates_preserve_context_and_source_fields_for_audit():
    note = {
        "id": "note-audit-1",
        "workspace_id": "workspace-1",
        "title": "Northstar Apollo operating note",
        "body": "Messy call notes with Acme and Northstar details.",
        "note_kind": "note",
    }
    project_ids = ["project-apollo"]
    person_ids = ["person-morgan", "person-priya"]
    data = {
        "companies": [
            {
                "name": "Northstar Health",
                "domain": "northstar.example",
                "description": "Client account for Apollo CRM rollout.",
                "confidence": 0.9,
            }
        ],
        "tasks": [
            {
                "title": "Send revised MSA",
                "description": "Include Acme redlines and Northstar security owner.",
                "due_date": "2026-05-15",
                "status": "doing",
                "priority": 1,
                "company_ids": ["company-northstar"],
                "relationship_hints": [{"kind": "owned_by", "target": "Morgan Lee"}],
                "confidence": 0.87,
            }
        ],
        "meetings": [],
        "workflows": [],
        "reports": [
            {
                "title": "Apollo weekly risk brief",
                "summary": "Northstar security review is the main open loop.",
                "status": "draft",
                "task_ids": ["task-msa"],
                "company_ids": ["company-northstar"],
                "confidence": 0.82,
            }
        ],
    }

    candidates = worker._structured_memory_candidates(note, data, project_ids, person_ids)
    by_kind = {kind: payload for kind, payload in candidates}

    task_payload = by_kind["task"]
    assert task_payload["source_note_id"] == "note-audit-1"
    assert task_payload["note_id"] == "note-audit-1"
    assert task_payload["project_ids"] == project_ids
    assert task_payload["person_ids"] == person_ids
    assert task_payload["description"] == "Include Acme redlines and Northstar security owner."
    assert task_payload["status"] == "doing"
    assert task_payload["priority"] == 1
    assert task_payload["company_ids"] == ["company-northstar"]
    assert task_payload["relationship_hints"][0]["target"] == "Morgan Lee"

    report_payload = by_kind["report"]
    assert report_payload["project_ids"] == project_ids
    assert report_payload["person_ids"] == person_ids
    assert report_payload["task_ids"] == ["task-msa"]
    assert report_payload["company_ids"] == ["company-northstar"]
    assert "Northstar security review" in report_payload["body"]


def test_materializing_review_candidate_stores_source_payload_and_context_links():
    review = {
        "id": "review-report-1",
        "workspace_id": "workspace-1",
        "entity_kind": "report",
        "entity_id": "note-audit-1",
    }
    payload = {
        "title": "Apollo weekly risk brief",
        "body": "Northstar security review is the main open loop.",
        "status": "draft",
        "source_kind": "ai_report:apollo weekly risk brief",
        "confidence": 0.82,
        "project_ids": ["project-apollo"],
        "person_ids": ["person-morgan"],
        "task_ids": ["task-msa"],
        "company_ids": ["company-northstar"],
        "source_note_id": "note-audit-1",
        "note_id": "note-audit-1",
    }
    cur = RecordingCursor(
        fetchone_values=[
            {"id": "note-audit-1", "workspace_id": "workspace-1", "body": "Original messy note", "note_kind": "note"},
            {"id": "report-1"},
        ],
        fetchall_values=[
            [{"id": "company-northstar", "name": "company-northstar"}],
        ],
    )

    report_id = worker._materialize_review_candidate(cur, review, payload, "owner-1")

    assert report_id == "report-1"
    report_params = next(params for sql, params in cur.executed if "INSERT INTO reports" in sql)
    assert report_params[1] == "Apollo weekly risk brief"
    assert report_params[2] == "Northstar security review is the main open loop."
    assert report_params[7] == "review-report-1"
    assert report_params[8] == 0.82
    stored_payload = json.loads(report_params[9])
    assert stored_payload["source_note_id"] == "note-audit-1"
    assert stored_payload["project_ids"] == ["project-apollo"]
    assert stored_payload["person_ids"] == ["person-morgan"]
    assert stored_payload["task_ids"] == ["task-msa"]
    assert stored_payload["company_ids"] == ["company-northstar"]

    executed_sql = "\n".join(sql for sql, _params in cur.executed)
    assert "INSERT INTO report_projects" in executed_sql
    assert "INSERT INTO report_people" in executed_sql
    assert "INSERT INTO report_tasks" in executed_sql
    assert "INSERT INTO report_companies" in executed_sql
