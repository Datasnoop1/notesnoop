#!/usr/bin/env python3
"""Ask Ollama Cloud to critique the Stage D migration artifacts.

This is a reproducible one-shot reviewer for the Stage D implementation PR.
It reads only checked-in files and sends them to Ollama Cloud; it never prints
or logs the API key / database URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "ollama:qwen3-coder-next"
FILES = (
    "docs/bitemporal-stage-d-design-proposal.md",
    "migrations/2026-05-05_bitemporal_valid_from_stage_d.sql",
    "migrations/2026-05-05_bitemporal_valid_from_stage_d_rollback.sql",
    "ops/stage_d_cleanup_day7.sql",
    "ops/_apply_stage_d_cleanup.sh",
    "docs/bitemporal-stage-d-implementation-runbook.md",
    "backend/tests/test_bitemporal_valid_from_stage_d.py",
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    allowed = {"OLLAMA_BASE_URL", "OLLAMA_API_KEY"}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def read_artifacts() -> str:
    parts: list[str] = []
    for rel in FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        parts.append(f"\n\n===== {rel} =====\n{text}")
    return "".join(parts)


def call_ollama(model: str, prompt: str, timeout_s: int) -> str:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / ".env.production")

    base_url = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OLLAMA_API_KEY is not configured in env/.env/.env.production")

    print(f"Sending Stage D artifacts to {base_url}/api/chat with model {model}", file=sys.stderr)
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior PostgreSQL migration reviewer. Find "
                    "correctness, rollback, operational, and security risks. "
                    "Prioritize CRITICAL findings that must block Stage D."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.1, "num_predict": 4000},
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "datasnoop-stage-d-critic",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"Ollama HTTP {exc.code}: {body}") from exc

    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    elapsed = time.monotonic() - started
    if not text:
        raise SystemExit(f"Ollama returned an empty response after {elapsed:.1f}s")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args(argv)

    prompt = (
        "Review these Stage D artifacts against the design document. "
        "Do not complain that the migration is not applied; Step 2 is "
        "implementation-only. Return markdown with sections: CRITICAL, "
        "WARNING, NITS, and PASS/FAIL recommendation.\n"
        f"{read_artifacts()}"
    )
    print(call_ollama(args.model, prompt, args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
