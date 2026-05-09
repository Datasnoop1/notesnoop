from __future__ import annotations

import json
import os
from typing import Any

import httpx


OLLAMA_HOST = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "https://ollama.com")).rstrip("/")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
EXTRACTION_MODEL = os.getenv("NOTESNOOP_EXTRACTION_MODEL", "qwen3-coder-next")


EXTRACTION_SYSTEM = """You extract existing project/person mentions from messy professional notes.
Return strict JSON only:
{"people":[{"name":"...", "confidence":0.0, "span":[0,10]}], "projects":[{"name":"...", "confidence":0.0, "span":[0,10]}]}
Do not invent names. Confidence must be 0..1. Use character spans when obvious; otherwise [0,0]."""


async def extract_entities(note_body: str, known_people: list[str], known_projects: list[str]) -> dict[str, Any]:
    if not OLLAMA_API_KEY:
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    prompt = {
        "note": note_body[:12000],
        "known_people": known_people[:200],
        "known_projects": known_projects[:200],
        "instructions": [
            "Prefer matching known_people and known_projects.",
            "Unknown people may be returned as people mentions, but never create entities yourself.",
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
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Ollama extraction response must be a JSON object")
    data.setdefault("people", [])
    data.setdefault("projects", [])
    if not isinstance(data["people"], list) or not isinstance(data["projects"], list):
        raise ValueError("Ollama extraction response has invalid entity lists")
    return data
