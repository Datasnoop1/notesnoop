from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
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


EXTRACTION_SYSTEM = """You extract durable memory from messy professional notes.
Return strict JSON only:
{"people":[{"name":"...", "confidence":0.0, "span":[0,10]}], "projects":[{"name":"...", "confidence":0.0, "span":[0,10]}], "companies":[{"name":"...", "domain":null, "confidence":0.0, "span":[0,10]}], "tasks":[{"title":"...", "description":"...", "status":"todo|doing|blocked|done", "priority":1, "due_date":"YYYY-MM-DD or null", "person_names":[], "company_names":[], "company_ids":[], "task_ids":[], "relationship_hints":[], "confidence":0.0, "span":[0,10]}], "meetings":[{"title":"...", "summary":"...", "occurred_date":"YYYY-MM-DD or null", "person_names":[], "company_names":[], "decisions":[], "relationship_hints":[], "confidence":0.0}], "workflows":[{"name":"...", "description":"...", "task_titles":[], "task_ids":[], "company_names":[], "company_ids":[], "relationship_hints":[], "confidence":0.0}], "reports":[{"title":"...", "summary":"...", "task_titles":[], "task_ids":[], "company_names":[], "company_ids":[], "relationship_hints":[], "confidence":0.0}]}
Do not invent names, tasks, dates, or facts. Only include explicit items in the note. Preserve useful descriptions and relationship hints when present. Confidence must be 0..1. Use character spans when obvious; otherwise [0,0]."""

PROJECT_REPORT_SYSTEM = """You turn NoteSnoop project memory into a concise professional report.
Return strict JSON only:
{"title":"...", "body":"markdown report", "confidence":0.0}
The report must be grounded only in the provided notes, tasks, meetings, and prior reports. If data is thin, say so plainly. Include sections for Executive summary, Current state, Open loops, People/companies, Risks, and Next actions. Do not invent facts."""

MEMORY_ASK_SYSTEM = """You answer questions over NoteSnoop memory.
Return strict JSON only:
{"answer":"markdown answer", "confidence":0.0}
Use only the supplied notes and structured memory. If the evidence is thin or missing, say that directly. Do not invent names, dates, tasks, project status, or decisions."""


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
COMPANY_SUFFIX_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4}\s+"
    r"(?:BV|NV|LLC|Ltd|Limited|Inc|GmbH|SA|SAS|AG|Advisory|Capital|Partners|Ventures|Group|Bank))\b"
)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-[01]\d-[0-3]\d)\b")
EU_DATE_RE = re.compile(r"\b([0-3]?\d)[/-]([01]?\d)[/-](20\d{2})\b")


def _clean_action_title(text: str) -> str:
    title = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", text).strip()
    title = re.sub(r"^\s*(?:todo|to-do|action(?:\s+item)?|follow\s+up)\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .;")
    if len(title) > 240:
        title = title[:237].rstrip() + "..."
    return title


def _extract_due_date_hint(text: str) -> str | None:
    iso_match = ISO_DATE_RE.search(text)
    if iso_match:
        return iso_match.group(1)
    eu_match = EU_DATE_RE.search(text)
    if not eu_match:
        return None
    day, month, year = (int(eu_match.group(1)), int(eu_match.group(2)), int(eu_match.group(3)))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_relative_due_hint(text: str) -> str | None:
    match = re.search(
        r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _task_status_hint(text: str) -> str:
    if re.search(r"\b(blocked|stuck|waiting on|cannot proceed)\b", text, re.IGNORECASE):
        return "blocked"
    if re.search(r"\b(done|completed|sent|finished)\b", text, re.IGNORECASE):
        return "done"
    if re.search(r"\b(doing|in progress|working on|underway)\b", text, re.IGNORECASE):
        return "doing"
    return "todo"


def _task_priority_hint(text: str) -> int:
    if re.search(r"\b(urgent|asap|today|critical|high priority)\b", text, re.IGNORECASE):
        return 1
    if re.search(r"\b(important|this week|before)\b", text, re.IGNORECASE):
        return 2
    if re.search(r"\b(low priority|nice to have|someday)\b", text, re.IGNORECASE):
        return 5
    return 3


def _heuristic_company_mentions(note_body: str) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in COMPANY_SUFFIX_RE.finditer(note_body):
        name = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;")
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        mentions.append({"name": name, "domain": None, "confidence": 0.64, "span": [match.start(1), match.end(1)]})
    return mentions


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
        task = {
            "title": title,
            "description": segment,
            "status": _task_status_hint(segment),
            "priority": _task_priority_hint(segment),
            "due_date": _extract_due_date_hint(segment),
            "confidence": 0.86,
            "span": [match.start(), match.end()],
        }
        due_date_hint = _extract_relative_due_hint(segment)
        if due_date_hint:
            task["due_date_hint"] = due_date_hint
        tasks.append(task)
    return tasks


def deterministic_extract_meetings(note_body: str) -> list[dict[str, Any]]:
    text = " ".join(note_body.split())
    if not re.search(r"\b(meeting|call|sync|standup|demo|workshop)\b", text, re.IGNORECASE):
        return []
    title_match = re.search(r"(?im)^\s*(?:meeting|call|sync|standup|demo|workshop)\s*[:\-]\s*(.+)$", note_body)
    if title_match:
        title = title_match.group(1).strip()
    else:
        segment = next(
            (
                part.strip()
                for part in re.split(r"[.\n\r;]+", note_body)
                if re.search(r"\b(meeting|call|sync|standup|demo|workshop)\b", part, re.IGNORECASE)
            ),
            "Captured conversation",
        )
        title = segment[:160]
    return [{"title": _clean_action_title(title) or "Captured conversation", "summary": text[:360], "occurred_date": None, "confidence": 0.74}]


def deterministic_extract_reports(note_body: str) -> list[dict[str, Any]]:
    text = " ".join(note_body.split())
    if not re.search(r"\b(report|brief|summary|memo)\b", text, re.IGNORECASE):
        return []
    title_match = re.search(r"(?im)^\s*(?:report|brief|summary|memo)\s*[:\-]\s*(.+)$", note_body)
    title = title_match.group(1).strip() if title_match else "Captured brief"
    return [{"title": _clean_action_title(title) or "Captured brief", "summary": text[:900], "confidence": 0.72}]


def deterministic_extract_workflows(note_body: str) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?im)^\s*(?:workflow|process|loop)\s*[:\-]\s*(.+)$", note_body):
        name = _clean_action_title(match.group(1))
        key = name.casefold()
        if len(name) < 3 or key in seen:
            continue
        seen.add(key)
        workflows.append({"name": name, "description": " ".join(note_body.split())[:500], "confidence": 0.78})
    return workflows


def deterministic_extract_entities(
    note_body: str,
    known_people: list[str],
    known_projects: list[str],
    known_companies: list[str] | None = None,
) -> dict[str, Any]:
    known_company_mentions = _exact_mentions(note_body, known_companies or [])
    seen_company_names = {item["name"].casefold() for item in known_company_mentions}
    company_mentions = [*known_company_mentions]
    for company in _heuristic_company_mentions(note_body):
        if company["name"].casefold() not in seen_company_names:
            company_mentions.append(company)
            seen_company_names.add(company["name"].casefold())
    return {
        "people": _exact_mentions(note_body, known_people),
        "projects": _exact_mentions(note_body, known_projects),
        "companies": company_mentions,
        "tasks": deterministic_extract_tasks(note_body),
        "meetings": deterministic_extract_meetings(note_body),
        "workflows": deterministic_extract_workflows(note_body),
        "reports": deterministic_extract_reports(note_body),
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


def _citation(kind: str, item: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": str(item.get("id") or item.get("note_id") or ""),
        "title": _first_text(item, "title", "name", "body", "description", limit=120) or label,
        "label": label,
    }


def deterministic_memory_answer(query: str, notes: list[dict[str, Any]], memories: list[dict[str, Any]]) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    answer_lines = [f"### Answer", ""]
    if not notes and not memories:
        return {
            "answer": "I do not have enough matching memory to answer that yet.",
            "confidence": 0.25,
            "citations": [],
            "source_counts": {"notes": 0, "memory": 0},
        }

    if notes:
        answer_lines.append("Relevant notes:")
        for index, note in enumerate(notes[:5], start=1):
            label = f"N{index}"
            citations.append(_citation("note", note, label))
            answer_lines.append(f"- [{label}] {_first_text(note, 'title', 'body', limit=220)}")
    if memories:
        answer_lines.append("")
        answer_lines.append("Structured memory:")
        for index, memory in enumerate(memories[:6], start=1):
            label = f"M{index}"
            citations.append(_citation(str(memory.get("kind") or "memory"), memory, label))
            title = _first_text(memory, "title", "name", limit=160)
            subtitle = _first_text(memory, "subtitle", "description", "body", limit=180)
            answer_lines.append(f"- [{label}] {title}{f': {subtitle}' if subtitle else ''}")
    answer_lines.extend(["", f"Query: {query.strip()}"])
    return {
        "answer": "\n".join(answer_lines).strip(),
        "confidence": 0.55 if len(citations) < 3 else 0.7,
        "citations": citations,
        "source_counts": {"notes": len(notes), "memory": len(memories)},
    }


async def extract_entities(
    note_body: str,
    known_people: list[str],
    known_projects: list[str],
    known_companies: list[str] | None = None,
) -> dict[str, Any]:
    if _is_cloud_host() and not OLLAMA_API_KEY:
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    today = datetime.now(timezone.utc).date().isoformat()
    prompt = {
        "today": today,
        "note": note_body[:12000],
        "known_people": known_people[:200],
        "known_projects": known_projects[:200],
        "known_companies": (known_companies or [])[:200],
        "instructions": [
            f"Today's date is {today}. Resolve relative dates ('Friday', 'next week', 'tomorrow', 'May 22') against this. Never invent a year — if the note says 'May 22' use the next occurrence on or after today.",
            "Match known_people, known_projects, known_companies before creating new ones.",
            "Never invent UUIDs. If the note literally contains a UUID for a project / company / task, copy it; otherwise omit *_ids fields.",
            "Do not extract structural prefixes ('Action items:', 'TODOs:', 'Decisions:') as standalone tasks. Each task entry must be a discrete actionable phrase, not a list header.",
            "Never emit two tasks that describe the SAME action with different wording. If the note rephrases a single action (e.g. 'send X to Y by Wednesday' and 'email Y about X — Wednesday at latest' = one task), emit exactly one task with the most specific phrasing. The fact that an action appears in multiple sentences does not make it two tasks.",
            "For each task: title (required, short imperative phrase max 80 chars — never copy a list header or paragraph), description (1 sentence, optional), status ('todo' unless the note says doing/blocked/done), priority (1-5; 1 if urgent words like ASAP/urgent/today, else 3), due_date (YYYY-MM-DD if the note specifies a date explicitly or relatively, else null), person_names (assignee + watchers, list of names), company_names (list).",
            "For each meeting: title (required), occurred_date (YYYY-MM-DD or null), summary (2-3 sentences), person_names (attendees), company_names, decisions (list of short statements), follow_ups (list of short action statements).",
            "For each workflow: name (required), description (1-2 sentences), status (draft / active / paused / retired), person_names (owners), company_names.",
            "For each report: title (required), summary (3-4 sentences), status (draft / published / archived), person_names, company_names.",
            "For each company: name (required), domain (only if explicitly written), summary (optional 1 sentence).",
            "For each person mention: name (required) and optional role/company hint.",
            "relationship_hints: short strings describing why entities link (e.g. 'Acme is the customer', 'Alice is the new owner'). Optional but valued.",
            "If the note has a clear central topic in 6 words or fewer, propose it as `note_title` at the top level. Otherwise omit `note_title`.",
            "Return entities only when explicitly grounded in the note. No speculation.",
            "Output valid JSON only. No markdown, no commentary.",
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
            return deterministic_extract_entities(note_body, known_people, known_projects, known_companies)
        raise
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Ollama extraction response must be a JSON object")
    data.setdefault("people", [])
    data.setdefault("projects", [])
    for key in ("people", "projects", "companies", "tasks", "meetings", "workflows", "reports"):
        data.setdefault(key, [])
    if not all(isinstance(data[key], list) for key in ("people", "projects", "companies", "tasks", "meetings", "workflows", "reports")):
        raise ValueError("Ollama extraction response has invalid entity lists")
    existing_task_titles = {str(item.get("title", "")).strip().casefold() for item in data["tasks"] if isinstance(item, dict)}
    for task in deterministic_extract_tasks(note_body):
        if task["title"].casefold() not in existing_task_titles:
            data["tasks"].append(task)
    existing_company_names = {str(item.get("name", "")).strip().casefold() for item in data["companies"] if isinstance(item, dict)}
    for company in [*_exact_mentions(note_body, known_companies or []), *_heuristic_company_mentions(note_body)]:
        if company["name"].casefold() not in existing_company_names:
            data["companies"].append(company)
            existing_company_names.add(company["name"].casefold())
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


async def generate_memory_answer(
    query: str,
    notes: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = deterministic_memory_answer(query, notes, memories)
    if _is_cloud_host() and not OLLAMA_API_KEY:
        if REPORT_ALLOW_DETERMINISTIC_FALLBACK:
            return fallback
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    prompt = {
        "query": query,
        "context": context or {},
        "notes": notes[:12],
        "structured_memory": memories[:18],
        "citation_labels": fallback["citations"],
        "instructions": [
            "Answer the user question directly.",
            "Use markdown.",
            "Only use supplied memory.",
            "When useful, include source labels like [N1] or [M2] that match citation_labels.",
            "If the supplied memory is insufficient, say what is missing.",
        ],
    }
    payload = {
        "model": EXTRACTION_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": MEMORY_ASK_SYSTEM},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, default=str)},
        ],
        "format": "json",
        "options": {"temperature": 0.15},
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(f"{OLLAMA_HOST}/api/chat", headers=_headers(), json=payload)
            resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Ollama memory answer response must be a JSON object")
        answer = str(data.get("answer") or "").strip()
        if not answer:
            raise ValueError("Ollama memory answer response is missing answer")
        confidence = float(data.get("confidence") or fallback["confidence"])
        return {
            "answer": answer,
            "confidence": max(0.0, min(1.0, confidence)),
            "citations": fallback["citations"],
            "source_counts": fallback["source_counts"],
        }
    except Exception as exc:
        if REPORT_ALLOW_DETERMINISTIC_FALLBACK and (_is_transient_error(exc) or isinstance(exc, (ValueError, json.JSONDecodeError))):
            logger.warning("using deterministic memory answer fallback after Ollama answer failure: %s", exc)
            return fallback
        raise
