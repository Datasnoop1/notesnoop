from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx


logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "https://ollama.com")).rstrip("/")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
EXTRACTION_MODEL = os.getenv("NOTESNOOP_EXTRACTION_MODEL", "qwen3-coder-next")
ALLOW_DETERMINISTIC_FALLBACK = os.getenv("NOTESNOOP_EXTRACTION_ALLOW_DETERMINISTIC_FALLBACK", "true").lower() in {
    "1",
    "true",
    "yes",
}
REPORT_ALLOW_DETERMINISTIC_FALLBACK = os.getenv("NOTESNOOP_REPORT_ALLOW_DETERMINISTIC_FALLBACK", "true").lower() in {
    "1",
    "true",
    "yes",
}


EXTRACTION_SYSTEM = """You extract existing project/person mentions and explicit action items from messy professional notes.
Return strict JSON only:
{"people":[{"name":"...", "confidence":0.0, "span":[0,10]}], "projects":[{"name":"...", "confidence":0.0, "span":[0,10]}], "tasks":[{"title":"...", "due_date":"YYYY-MM-DD or null", "confidence":0.0, "span":[0,10]}]}
Do not invent names or tasks. Only include tasks/action items that are explicit in the note. Confidence must be 0..1. Use character spans when obvious; otherwise [0,0]."""

PROJECT_REPORT_SYSTEM = """You turn NoteSnoop project memory into a concise professional report.
Return strict JSON only:
{"title":"...", "body":"markdown report", "confidence":0.0}
The report must be grounded only in the provided notes, tasks, meetings, and prior reports. If data is thin, say so plainly. Include sections for Executive summary, Current state, Open loops, People/companies, Risks, and Next actions. Do not invent facts."""


def _is_cloud_host() -> bool:
    return "ollama.com" in OLLAMA_HOST


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    return headers


def _is_transient_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "too many requests",
            "rate limit",
            "timed out",
            "timeout",
            "connection reset",
            "temporarily unavailable",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
    )


def _exact_mentions(note_body: str, names: list[str]) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        clean = str(name or "").strip()
        key = clean.casefold()
        if len(clean) < 2 or key in seen:
            continue
        seen.add(key)
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(clean)}(?![A-Za-z0-9])", re.IGNORECASE)
        match = pattern.search(note_body)
        if match:
            mentions.append({"name": clean, "confidence": 0.92, "span": [match.start(), match.end()]})
    return mentions


ACTION_ITEM_RE = re.compile(
    r"\b("
    r"todo|to-do|action(?:\s+item)?|follow\s+up|need(?:s|ed)?\s+to|we\s+need|i\s+need|please"
    r")\b",
    re.IGNORECASE,
)


def _clean_action_title(text: str) -> str:
    title = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", text).strip()
    title = re.sub(r"^\s*(?:todo|to-do|action(?:\s+item)?|follow\s+up)\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .;")
    if len(title) > 240:
        title = title[:237].rstrip() + "..."
    return title


def deterministic_extract_tasks(note_body: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r"[^.\n\r;]+(?:[.\n\r;]|$)", note_body):
        segment = match.group(0).strip()
        if not segment or not ACTION_ITEM_RE.search(segment):
            continue
        title = _clean_action_title(segment)
        key = title.casefold()
        if len(title) < 3 or key in seen:
            continue
        seen.add(key)
        tasks.append({"title": title, "confidence": 0.86, "span": [match.start(), match.end()]})
    return tasks


def deterministic_extract_entities(note_body: str, known_people: list[str], known_projects: list[str]) -> dict[str, Any]:
    return {
        "people": _exact_mentions(note_body, known_people),
        "projects": _exact_mentions(note_body, known_projects),
        "tasks": deterministic_extract_tasks(note_body),
    }


def _first_text(row: dict[str, Any], *keys: str, limit: int = 360) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return " ".join(value.split())[:limit]
    return ""


def deterministic_project_report(
    project: dict[str, Any],
    notes: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    meetings: list[dict[str, Any]] | None = None,
    reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meetings = meetings or []
    reports = reports or []
    project_name = str(project.get("name") or "Project").strip()
    open_tasks = [task for task in tasks if task.get("status") not in {"done", "archived"}]
    blocked_tasks = [task for task in open_tasks if task.get("status") == "blocked"]
    note_lines = [_first_text(note, "title", "body") for note in notes[:6]]
    meeting_lines = [_first_text(meeting, "title", "summary") for meeting in meetings[:4]]
    prior_report_lines = [_first_text(report, "title", "body") for report in reports[:3]]

    lines = [
        f"# {project_name} report",
        "",
        "## Executive summary",
    ]
    if note_lines or meeting_lines or prior_report_lines:
        lines.extend(f"- {item}" for item in [*note_lines[:3], *meeting_lines[:2], *prior_report_lines[:1]] if item)
    else:
        lines.append("- Thin data: no captured project notes, meetings, or reports yet.")
    lines.extend(
        [
            "",
            "## Current state",
            f"- Captured notes: {len(notes)}",
            f"- Meetings/calls: {len(meetings)}",
            f"- Reports/briefs: {len(reports)}",
            f"- Open loops: {len(open_tasks)}",
            "",
            "## Open loops",
        ]
    )
    if open_tasks:
        lines.extend(
            f"- [{task.get('status') or 'todo'}] {_first_text(task, 'title', 'description', limit=220)}"
            for task in open_tasks[:10]
        )
    else:
        lines.append("- No open tasks captured.")
    lines.extend(["", "## Risks"])
    if blocked_tasks:
        lines.extend(f"- Blocked: {_first_text(task, 'title', 'description', limit=220)}" for task in blocked_tasks[:5])
    elif len(notes) < 2 and not meetings:
        lines.append("- Thin data: capture more notes or meetings before treating this report as complete.")
    else:
        lines.append("- No explicit blockers captured.")
    lines.extend(["", "## Next actions"])
    if open_tasks:
        lines.extend(f"- {_first_text(task, 'title', 'description', limit=220)}" for task in open_tasks[:5])
    else:
        lines.append("- Capture the next concrete follow-up as a task.")
    return {
        "title": f"{project_name} report",
        "body": "\n".join(lines).strip(),
        "confidence": 0.62 if notes or tasks or meetings else 0.35,
    }


async def extract_entities(note_body: str, known_people: list[str], known_projects: list[str]) -> dict[str, Any]:
    if _is_cloud_host() and not OLLAMA_API_KEY:
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    prompt = {
        "note": note_body[:12000],
        "known_people": known_people[:200],
        "known_projects": known_projects[:200],
        "instructions": [
            "Prefer matching known_people and known_projects.",
            "Unknown people may be returned as people mentions, but never create entities yourself.",
            "Return explicit tasks/action items when the note says need, follow up, todo, or action item.",
            "If an action item has an explicit due date, return due_date as YYYY-MM-DD; otherwise null.",
            "Only return JSON. No markdown.",
        ],
    }
    payload = {
        "model": EXTRACTION_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "format": "json",
        "options": {"temperature": 0.1},
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{OLLAMA_HOST}/api/chat",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
    except Exception as exc:
        if ALLOW_DETERMINISTIC_FALLBACK and _is_transient_error(exc):
            logger.warning("using deterministic extraction fallback after transient Ollama failure: %s", exc)
            return deterministic_extract_entities(note_body, known_people, known_projects)
        raise
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Ollama extraction response must be a JSON object")
    data.setdefault("people", [])
    data.setdefault("projects", [])
    data.setdefault("tasks", [])
    if not isinstance(data["people"], list) or not isinstance(data["projects"], list) or not isinstance(data["tasks"], list):
        raise ValueError("Ollama extraction response has invalid entity lists")
    existing_task_titles = {str(item.get("title", "")).strip().casefold() for item in data["tasks"] if isinstance(item, dict)}
    for task in deterministic_extract_tasks(note_body):
        if task["title"].casefold() not in existing_task_titles:
            data["tasks"].append(task)
    return data


async def generate_project_report(
    project: dict[str, Any],
    notes: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    meetings: list[dict[str, Any]] | None = None,
    reports: list[dict[str, Any]] | None = None,
    variant: str = "full",
) -> dict[str, Any]:
    fallback = deterministic_project_report(project, notes, tasks, meetings, reports)
    if _is_cloud_host() and not OLLAMA_API_KEY:
        if REPORT_ALLOW_DETERMINISTIC_FALLBACK:
            return fallback
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    prompt = {
        "project": project,
        "notes": notes[:40],
        "tasks": tasks[:60],
        "meetings": (meetings or [])[:25],
        "prior_reports": (reports or [])[:10],
        "variant": variant,
        "instructions": [
            "Ground every statement in the provided memory.",
            "Use markdown in body.",
            "If evidence is thin, explicitly degrade confidence.",
            "Do not invent people, companies, dates, risks, or tasks.",
        ],
    }
    payload = {
        "model": EXTRACTION_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": PROJECT_REPORT_SYSTEM},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, default=str)},
        ],
        "format": "json",
        "options": {"temperature": 0.2},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{OLLAMA_HOST}/api/chat", headers=_headers(), json=payload)
            resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Ollama report response must be a JSON object")
        title = str(data.get("title") or fallback["title"]).strip()[:240]
        body = str(data.get("body") or "").strip()
        if not body:
            raise ValueError("Ollama report response is missing body")
        confidence = float(data.get("confidence") or fallback["confidence"])
        return {"title": title, "body": body, "confidence": max(0.0, min(1.0, confidence))}
    except Exception as exc:
        if REPORT_ALLOW_DETERMINISTIC_FALLBACK and (_is_transient_error(exc) or isinstance(exc, (ValueError, json.JSONDecodeError))):
            logger.warning("using deterministic project report fallback after Ollama report failure: %s", exc)
            return fallback
        raise
