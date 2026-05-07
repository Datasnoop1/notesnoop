#!/usr/bin/env python3
"""Fan a design-plan markdown out to a panel of Ollama Cloud models.

One-shot reviewer for plan documents. Reads the plan, sends it
concurrently to N models, prints each response. Never logs the API
key; output is intended to be piped back into the operator's chat.

Usage:
    python scripts/plan_review_panel.py docs/some-plan.md \\
        --models ollama:qwen3-coder-next ollama:kimi-k2.6 \\
                 ollama:deepseek-v4-pro:latest ollama:glm-5.1:latest
"""

from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Force stdout to UTF-8 so Ollama's en-dashes / arrows / NBSP don't blow
# up on Windows' default cp1252 codec.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = [
    "ollama:qwen3-coder-next",
    "ollama:kimi-k2.6",
    "ollama:deepseek-v4-pro:latest",
    "ollama:glm-5.1:latest",
]


def load_env_file(path: Path) -> None:
    """Lift only the Ollama-related vars from a dotenv file.

    Mirrors scripts/stage_d_migration_critic.py — keeps the rest of the
    environment untouched so we never accidentally leak DB or NBB creds
    via subprocess inheritance.
    """
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


def call_ollama(model: str, system: str, user: str, timeout_s: int) -> dict:
    """One synchronous call to Ollama Cloud's /api/chat. Returns
    {ok, model, latency_s, content, error?}."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "model": model, "latency_s": 0.0,
                "content": "", "error": "OLLAMA_API_KEY not set"}

    # Production strips the "ollama:" routing-tag prefix before sending to
    # Ollama Cloud (see backend/ai_client.py:_ollama_model_name).
    upstream_model = model.split(":", 1)[1] if model.startswith("ollama:") else model
    payload = {
        "model": upstream_model,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
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
            "User-Agent": "datasnoop-plan-review-panel",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "model": model,
                "latency_s": time.monotonic() - started,
                "content": "", "error": f"HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"ok": False, "model": model,
                "latency_s": time.monotonic() - started,
                "content": "", "error": f"{type(exc).__name__}: {exc}"}

    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    elapsed = time.monotonic() - started
    if not text:
        return {"ok": False, "model": model, "latency_s": elapsed,
                "content": "", "error": "empty response"}
    return {"ok": True, "model": model, "latency_s": elapsed, "content": text}


def build_system_prompt() -> str:
    return (
        "You are a senior software architect reviewing a design plan for a "
        "small SaaS public API. Be concrete and ruthless: flag CRITICAL "
        "issues that would break the design, WARNINGS that risk operational "
        "or correctness problems, and NITS for smaller improvements.\n\n"
        "Write your review in markdown with these sections, in order:\n"
        "  ## CRITICAL\n"
        "  ## WARNING\n"
        "  ## NITS\n"
        "  ## VERDICT: <APPROVE | REVISE | REJECT>\n\n"
        "Use APPROVE only if there are no CRITICALs and at most minor "
        "WARNINGs. Use REVISE if specific changes would make it APPROVE-able. "
        "Use REJECT only for fundamental design errors. Be specific: cite "
        "section numbers (§1, §2, ...) from the plan when referring to it."
    )


def build_user_prompt(plan_text: str) -> str:
    return (
        "Review the following design plan. The plan exists to add a new "
        "search/listing endpoint to a public read-only API for Belgian "
        "company financial data. It must coexist with an existing "
        "single-company /financials endpoint, gated per-API-key via a new "
        "scopes column. Focus on: correctness, security, abuse vectors, "
        "scalability of SQL, scope-system soundness, and rollout safety.\n\n"
        "Plan follows in fenced markdown.\n\n"
        "```markdown\n" + plan_text + "\n```"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_path", help="Path to plan markdown file")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--out-dir", default=None,
                        help="Optional dir to write per-model responses to")
    args = parser.parse_args(argv)

    load_env_file(ROOT / ".env")
    load_env_file(ROOT / ".env.production")
    # Also try the parent dir (worktree case where .env lives one level up).
    load_env_file(ROOT.parent.parent.parent / ".env")

    plan_path = Path(args.plan_path)
    if not plan_path.is_absolute():
        plan_path = (ROOT / plan_path).resolve()
    plan_text = plan_path.read_text(encoding="utf-8")

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(plan_text)

    print(f"# Plan review panel\n", flush=True)
    print(f"Plan: {plan_path}\n", flush=True)
    print(f"Models: {', '.join(args.models)}\n", flush=True)

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args.models)) as ex:
        futures = {
            ex.submit(call_ollama, m, system_prompt, user_prompt, args.timeout): m
            for m in args.models
        }
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: args.models.index(r["model"]))

    out_dir = Path(args.out_dir).resolve() if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for r in results:
        slug = r["model"].replace(":", "_").replace("/", "_")
        print("\n" + "=" * 72)
        print(f"## {r['model']}  ({r['latency_s']:.1f}s)")
        print("=" * 72 + "\n")
        if not r["ok"]:
            print(f"_FAILED: {r['error']}_")
            continue
        print(r["content"])
        if out_dir:
            (out_dir / f"{slug}.md").write_text(r["content"], encoding="utf-8")

    # Tally verdicts.
    print("\n" + "=" * 72)
    print("## Summary tally")
    print("=" * 72 + "\n")
    for r in results:
        if not r["ok"]:
            print(f"- {r['model']}: ERROR")
            continue
        # Heuristic: find the last "VERDICT:" line.
        verdict = "?"
        for line in reversed(r["content"].splitlines()):
            stripped = line.strip().lstrip("#").strip()
            if stripped.upper().startswith("VERDICT"):
                verdict = stripped.split(":", 1)[1].strip() if ":" in stripped else stripped
                break
        print(f"- {r['model']}: {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
