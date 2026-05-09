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


EXTRACTION_SYSTEM = """You extract existing project/person mentions and explicit action items from messy professional notes.
Return strict JSON only:
{"people":[{"name":"...", "confidence":0.0, "span":[0,10]}], "projects":[{"name":"...", "confidence":0.0, "span":[0,10]}], "tasks":[{"title":"...", "due_date":"YYYY-MM-DD or null", "confidence":0.0, "span":[0,10]}]}
Do not invent names or tasks. Only include tasks/action items that are explicit in the note. Confidence must be 0..1. Use character spans when obvious; otherwise [0,0]."""


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
