#!/usr/bin/env python3
"""End-to-end NoteSnoop smoke runner for staging/preview.

This is intentionally API-level: it proves the v1 product workflow without
requiring a human to click through every control. Use a dev-auth-enabled
preview/staging backend, or point it at localhost during development.

Example:
  python scripts/notesnoop_smoke.py --base-url http://localhost:3010
  python scripts/notesnoop_smoke.py --base-url http://62.238.14.150:8091 \
    --basic-auth "$NOTESNOOP_PREVIEW_BASIC_AUTH"
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class SmokeUser:
    user_id: str
    email: str
    name: str


class SmokeClient:
    def __init__(self, base_url: str, user: SmokeUser, basic_auth: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.basic_auth = basic_auth

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self.base_url}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-notesnoop-user-id": self.user.user_id,
            "x-notesnoop-email": self.user.email,
            "x-notesnoop-name": self.user.name,
        }
        if self.basic_auth:
            token = base64.b64encode(self.basic_auth.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        if status not in expected:
            raise AssertionError(f"{method} {path} returned {status}, expected {expected}: {raw[:500]}")
        if not raw:
            return status, {}
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"raw": raw}

    def get(self, path: str, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        return self.request("GET", path, expected=expected)[1]

    def post(self, path: str, payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        return self.request("POST", path, payload, expected)[1]

    def patch(self, path: str, payload: dict[str, Any], expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        return self.request("PATCH", path, payload, expected)[1]

    def put(self, path: str, payload: dict[str, Any], expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        return self.request("PUT", path, payload, expected)[1]


def data(response: dict[str, Any]) -> Any:
    return response.get("data")


def by_kind(projects: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    for project in projects:
        if project.get("kind") == kind:
            return project
    raise AssertionError(f"missing {kind} project")


def by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for row in rows:
        if row.get("name") == name:
            return row
    raise AssertionError(f"missing row named {name}")


def assert_true(value: Any, label: str) -> None:
    if not value:
        raise AssertionError(label)
    print(f"ok - {label}")


def wait_for_note_processed(client: SmokeClient, note_id: str, timeout_s: int = 45) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = data(client.get(f"/api/notes/{note_id}"))
        if last and last.get("ai_processing_status") in {"processed", "skipped"}:
            return last
        time.sleep(2)
    return last or {}


def run(base_url: str, basic_auth: str | None) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner = SmokeClient(
        base_url,
        SmokeUser(f"smoke-owner-{suffix}", f"smoke-owner-{suffix}@example.test", "Smoke Owner"),
        basic_auth,
    )
    peer = SmokeClient(
        base_url,
        SmokeUser(f"smoke-peer-{suffix}", f"smoke-peer-{suffix}@example.test", "Smoke Peer"),
        basic_auth,
    )

    boot = data(owner.post("/api/bootstrap", {"workspace_name": f"Smoke {suffix}", "timezone": "UTC"}))
    workspace_id = boot["workspace"]["id"]
    inbox = by_kind(boot["projects"], "inbox")
    personal = by_kind(boot["projects"], "personal")
    assert_true(inbox and personal, "bootstrap created Inbox and Personal projects")

    for name in [f"Avery Smoke {suffix}", f"Blair Smoke {suffix}"]:
        owner.post(f"/api/workspaces/{workspace_id}/people", {"name": name})
    state = data(owner.get("/api/me"))
    avery = by_name(state["people"], f"Avery Smoke {suffix}")
    blair = by_name(state["people"], f"Blair Smoke {suffix}")
    assert_true(avery and blair, "warm-start people can be pre-seeded")

    project = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/projects",
            {"name": f"Apollo Smoke {suffix}", "color_hex": "#e85d4f"},
        )
    )
    note = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/notes",
            {
                "body": f"Avery Smoke {suffix} mentioned Apollo Smoke {suffix} follow-up. Need a brief by Tuesday.",
                "project_ids": [inbox["id"]],
            },
        )
    )
    assert_true(note.get("project_nudge", {}).get("inbox_only"), "contextual project nudge offered from Inbox note")
    opened = wait_for_note_processed(owner, note["id"])
    assert_true(opened.get("id") == note["id"], "first note saved and can be opened")

    owner.post(f"/api/notes/{note['id']}/people", {"person_id": avery["id"], "state": "confirmed", "source": "user"})
    owner.put(f"/api/notes/{note['id']}/projects", {"project_ids": [project["id"]], "confirm_personal_move": False})
    person_timeline = data(owner.get(f"/api/people/{avery['id']}/timeline"))
    project_timeline = data(owner.get(f"/api/projects/{project['id']}/timeline"))
    search_q = urlencode({"q": f"Avery Smoke {suffix}", "person_id": avery["id"]})
    search = data(owner.get(f"/api/workspaces/{workspace_id}/search?{search_q}"))
    assert_true(person_timeline["notes"], "person timeline populates")
    assert_true(project_timeline["notes"], "project timeline populates")
    assert_true(search, "persistent search returns matching notes")

    task_memory_note = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/notes",
            {
                "title": f"Task memory {suffix}",
                "body": f"Action: follow up with Avery Smoke {suffix} about Apollo Smoke {suffix} materials.",
                "note_kind": "task",
                "project_ids": [project["id"]],
            },
        )
    )
    call_memory_note = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/notes",
            {
                "title": f"Apollo call memory {suffix}",
                "body": "Kickoff call: legal timeline is still the blocker.",
                "note_kind": "call",
                "project_ids": [project["id"]],
            },
        )
    )
    report_memory_note = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/notes",
            {
                "title": f"Apollo report memory {suffix}",
                "body": "Weekly status: progress, blockers, next asks.",
                "note_kind": "report",
                "project_ids": [project["id"]],
            },
        )
    )
    for memory_note in [task_memory_note, call_memory_note, report_memory_note]:
        wait_for_note_processed(owner, memory_note["id"], timeout_s=60)
    materialized_home = data(owner.get(f"/api/workspaces/{workspace_id}/home"))
    assert_true(
        any(item.get("source_note_id") == task_memory_note["id"] for item in materialized_home["open_tasks"]),
        "AI worker materializes task memories into task graph",
    )
    assert_true(
        any(item.get("note_id") == call_memory_note["id"] or item.get("source_note_id") == call_memory_note["id"] for item in materialized_home["meetings_calls"]),
        "AI worker materializes call memories into meeting graph",
    )
    assert_true(
        any(item.get("note_id") == report_memory_note["id"] or item.get("source_note_id") == report_memory_note["id"] for item in materialized_home["reports_briefs"]),
        "AI worker materializes report memories into report graph",
    )

    task = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/tasks",
            {
                "title": f"Send Apollo follow-up {suffix}",
                "description": "Confirm diligence timeline and next decision owner.",
                "status": "doing",
                "priority": 1,
                "project_ids": [project["id"]],
                "person_ids": [avery["id"]],
                "note_ids": [note["id"]],
            },
        )
    )
    owner.patch(f"/api/tasks/{task['id']}", {"status": "blocked"})
    meeting = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/meetings",
            {
                "title": f"Apollo kickoff call {suffix}",
                "summary": "Avery needs the revised timeline before the brief.",
                "project_ids": [project["id"]],
                "person_ids": [avery["id"]],
                "note_ids": [note["id"]],
            },
        )
    )
    report = data(
        owner.post(
            f"/api/workspaces/{workspace_id}/reports",
            {
                "title": f"Apollo weekly brief {suffix}",
                "body": "Progress, blockers, open loops, and next asks.",
                "project_ids": [project["id"]],
                "person_ids": [avery["id"]],
                "note_ids": [note["id"]],
                "task_ids": [task["id"]],
            },
        )
    )
    project_summary = data(owner.get(f"/api/projects/{project['id']}/summary"))
    home_memory = data(owner.get(f"/api/workspaces/{workspace_id}/home"))
    assert_true(any(item["id"] == task["id"] for item in home_memory["open_tasks"]), "dashboard open tasks populate from task graph")
    assert_true(any(item["id"] == meeting["id"] for item in home_memory["meetings_calls"]), "dashboard meetings/calls populate from meeting graph")
    assert_true(any(item["id"] == report["id"] for item in home_memory["reports_briefs"]), "dashboard reports/briefs populate from report graph")
    assert_true(project_summary["task_counts"]["blocked"] >= 1, "project summary includes task state")
    assert_true(home_memory["project_intelligence"], "project intelligence cards populate")

    owner.post("/api/flags", {"note_id": note["id"]})
    owner.post("/api/flags", {"project_id": project["id"]})
    owner.post("/api/flags", {"person_id": avery["id"]})
    home = data(owner.get(f"/api/workspaces/{workspace_id}/home"))
    assert_true(len(home["flagged"]) >= 3, "flag affordances populate Home flagged section")

    quick = data(owner.get(f"/api/briefs/note/{note['id']}?variant=quick"))["markdown"]
    full = data(owner.get(f"/api/briefs/person/{avery['id']}?variant=full"))["markdown"]
    assert_true("#" in quick and "Recent notes:" in full, "quick and full copy briefs are generated")

    merge = data(owner.post(f"/api/people/{blair['id']}/merge", {"target_person_id": avery["id"]}))
    owner.post(f"/api/person-merges/{merge['undo_id']}/undo")
    assert_true(merge["merged"], "person merge and undo work")

    personal_status, _body = owner.request(
        "POST",
        f"/api/workspaces/{workspace_id}/notes",
        {
            "body": "This should not mix personal and shared projects.",
            "project_ids": [personal["id"], project["id"]],
        },
        expected=(422,),
    )
    assert_true(personal_status == 422, "Personal project hard-block rejects mixed project note")

    email_result = data(owner.post(f"/api/workspaces/{workspace_id}/send-test-email"))
    assert_true(email_result["outcome"] == "saved", "test inbound email saves to Inbox")
    notes = data(owner.get(f"/api/workspaces/{workspace_id}/notes?project_id={inbox['id']}"))
    email_note = next((item for item in notes if item.get("raw_email_metadata")), None)
    assert_true(email_note and email_note["ai_processing_status"] == "skipped", "email AI default is Manual")
    owner.post(f"/api/notes/{email_note['id']}/process-with-ai")

    owner.post(f"/api/projects/{project['id']}/invites", {"email": peer.user.email})
    peer_state = data(peer.get("/api/me"))
    assert_true(peer_state.get("accepted_invites"), "invited peer auto-accepts project invite")
    peer_person = data(peer.post(f"/api/workspaces/{workspace_id}/people", {"name": f"Peer Suggested {suffix}"}))
    suggestion = data(
        peer.post(
            f"/api/notes/{note['id']}/people",
            {"person_id": peer_person["id"], "state": "confirmed", "source": "user"},
        )
    )
    assert_true(suggestion.get("collaborator_suggestion"), "collaborator link routes through Review Queue")
    owner_home = data(owner.get(f"/api/workspaces/{workspace_id}/home"))
    review = next((item for item in owner_home["pending_review"] if item.get("reason") == "collaborator_suggestion"), None)
    assert_true(review, "owner sees collaborator suggestion")
    owner.post(f"/api/review-queue/{review['id']}/accept", {})

    saw_429 = False
    for _ in range(15):
        status, _payload = owner.request("POST", f"/api/notes/{note['id']}/process-with-ai", expected=(200, 429))
        if status == 429:
            saw_429 = True
            break
    assert_true(saw_429, "AI rate limiting returns 429 under stress")

    print(f"Smoke complete for workspace {workspace_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:3010")
    parser.add_argument("--basic-auth", default=None, help="username:password for preview basic auth")
    args = parser.parse_args()
    try:
        run(args.base_url, args.basic_auth)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
