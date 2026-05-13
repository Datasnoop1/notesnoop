#!/usr/bin/env python3
"""Measure NoteSnoop capture-to-extracted-memory latency.

The timer starts when the note create request is sent and stops when the note
reports ai_processing_status=processed/skipped. In normal auto-AI workspaces,
this is the user's first reviewable-memory moment.

Example:
  python scripts/notesnoop_extraction_perf.py --base-url http://localhost:3010 --dev-auth --samples 5
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PerfUser:
    user_id: str
    email: str
    name: str


class Client:
    def __init__(
        self,
        base_url: str,
        user: PerfUser,
        *,
        dev_auth: bool = False,
        bearer_token: str | None = None,
        preview_basic_auth: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.dev_auth = dev_auth
        self.bearer_token = bearer_token
        self.preview_basic_auth = preview_basic_auth

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.dev_auth:
            headers.update(
                {
                    "x-notesnoop-user-id": self.user.user_id,
                    "x-notesnoop-email": self.user.email,
                    "x-notesnoop-name": self.user.name,
                }
            )
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if self.preview_basic_auth:
            token = base64.b64encode(self.preview_basic_auth.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        req = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=45) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        if status not in expected:
            raise AssertionError(f"{method} {path} returned {status}, expected {expected}: {raw[:500]}")
        return json.loads(raw) if raw else {}

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any] | None = None, expected: tuple[int, ...] = (200,)) -> dict[str, Any]:
        return self.request("POST", path, payload, expected)


def data(response: dict[str, Any]) -> Any:
    return response.get("data")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * pct)))
    return ordered[index]


def wait_for_processed(client: Client, note_id: str, timeout_s: int, poll_interval_s: float) -> tuple[dict[str, Any], float]:
    deadline = time.perf_counter() + timeout_s
    last: dict[str, Any] = {}
    while time.perf_counter() < deadline:
        last = data(client.get(f"/api/notes/{note_id}")) or {}
        if last.get("ai_processing_status") in {"processed", "skipped"}:
            return last, time.perf_counter()
        time.sleep(poll_interval_s)
    raise TimeoutError(f"note {note_id} did not finish extraction; last status={last.get('ai_processing_status')}")


def _is_local_url(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def run(
    base_url: str,
    samples: int,
    timeout_s: int,
    poll_interval_s: float,
    *,
    dev_auth: bool,
    allow_remote_dev_auth: bool,
    bearer_token: str | None,
    preview_basic_auth: str | None,
) -> dict[str, Any]:
    if poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be positive")
    if dev_auth and not allow_remote_dev_auth and not _is_local_url(base_url):
        raise ValueError("Remote dev-auth perf runs require --allow-remote-dev-auth")
    if bearer_token and preview_basic_auth:
        raise ValueError("Use either NOTESNOOP_PERF_BEARER_TOKEN or NOTESNOOP_PREVIEW_BASIC_AUTH, not both")
    suffix = uuid.uuid4().hex[:8]
    client = Client(
        base_url,
        PerfUser(f"perf-extract-{suffix}", f"perf-extract-{suffix}@example.test", "Extraction Perf"),
        dev_auth=dev_auth,
        bearer_token=bearer_token,
        preview_basic_auth=preview_basic_auth,
    )
    boot = data(client.post("/api/bootstrap", {"workspace_name": f"Extraction Perf {suffix}", "timezone": "UTC"}))
    workspace_id = boot["workspace"]["id"]
    inbox = next(project for project in boot["projects"] if project.get("kind") == "inbox")
    timings: list[dict[str, Any]] = []

    for index in range(samples):
        body = (
            f"Extraction perf {suffix}-{index}: Morgan Lee met Nova Capital about Project Meridian. "
            "Action: ask Priya Shah to send the diligence pack by Friday. "
            "Decision: legal review stays blocked until Acme Holdings confirms the data room export."
        )
        started = time.perf_counter()
        note = data(
            client.post(
                f"/api/workspaces/{workspace_id}/notes",
                {
                    "title": f"Extraction perf {suffix}-{index}",
                    "body": body,
                    "project_ids": [inbox["id"]],
                },
            )
        )
        if note.get("ai_processing_status") in {"unprocessed", "skipped"}:
            client.post(f"/api/notes/{note['id']}/process-with-ai", expected=(200, 429))
        finished_note, finished = wait_for_processed(client, note["id"], timeout_s, poll_interval_s)
        elapsed = finished - started
        review_rows = data(client.get(f"/api/workspaces/{workspace_id}/review-queue?limit=100")) or []
        timings.append(
            {
                "note_id": note["id"],
                "seconds": round(elapsed, 3),
                "status": finished_note.get("ai_processing_status"),
                "open_reviews": len([row for row in review_rows if row.get("entity_id") == note["id"] and row.get("state", "open") == "open"]),
            }
        )

    seconds = [item["seconds"] for item in timings]
    return {
        "workspace_id": workspace_id,
        "samples": len(timings),
        "timings": timings,
        "summary": {
            "p50_seconds": round(statistics.median(seconds), 3),
            "p95_seconds": round(percentile(seconds, 0.95), 3),
            "max_seconds": round(max(seconds), 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("NOTESNOOP_PERF_BASE_URL", "http://localhost:3010"))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout-s", type=int, default=90)
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    parser.add_argument("--dev-auth", action="store_true", help="send NoteSnoop dev-auth headers")
    parser.add_argument(
        "--allow-remote-dev-auth",
        action="store_true",
        help="allow dev-auth headers against a non-localhost base URL",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.base_url,
                args.samples,
                args.timeout_s,
                args.poll_interval_s,
                dev_auth=args.dev_auth,
                allow_remote_dev_auth=args.allow_remote_dev_auth,
                bearer_token=os.getenv("NOTESNOOP_PERF_BEARER_TOKEN"),
                preview_basic_auth=os.getenv("NOTESNOOP_PREVIEW_BASIC_AUTH"),
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
