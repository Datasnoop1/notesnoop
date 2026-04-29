"""Phase-5 elaboration A/B scorer.

Reads the JSONL produced by elaboration_benchmark.py and asks an INDEPENDENT
judge model (qwen3-next) to rank the three paths per company across five
dimensions, then aggregates.

Run inside the enrichment-worker container.

Usage:
    python /app/scripts/elaboration_score.py \
        --in /tmp/elaboration_results.jsonl \
        --out /tmp/elaboration_scores.jsonl \
        --summary /tmp/elaboration_summary.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/app")
import httpx  # noqa: E402
import time  # noqa: E402


JUDGE_MODEL = "gpt-oss:120b-cloud"
JUDGE_MAX_TOKENS = 2000
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


async def call_ollama(model: str, system: str, prompt: str, max_tokens: int,
                      temperature: float = 0.1, timeout_s: float = 240.0) -> dict:
    started = time.monotonic()
    meta = {"text": "", "ok": False, "error": None, "status_code": None, "latency_ms": 0}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "stream": False,
               "think": False,  # gpt-oss handles this; falls back to reasoning_effort if needed
               "messages": messages,
               "options": {"num_predict": max_tokens, "temperature": temperature}}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"},
                json=payload, timeout=timeout_s,
            )
            meta["status_code"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message") or {}
                meta["text"] = (msg.get("content") or "").strip()
                meta["ok"] = bool(meta["text"])
                if not meta["ok"]:
                    meta["error"] = f"empty_completion (done_reason={data.get('done_reason')})"
            else:
                meta["error"] = f"http_{resp.status_code}"
                meta["text"] = resp.text[:300]
    except httpx.TimeoutException:
        meta["error"] = "timeout"
    except Exception as e:
        meta["error"] = f"exc: {e!r}"
    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    return meta
DIMENSIONS = ["faithfulness", "specificity", "completeness", "coherence", "calibration"]
PATH_LABEL = {
    "A_deepseek_alone": "Path A (DeepSeek v4 Pro alone)",
    "B_kimi_alone": "Path B (Kimi K2.6 alone)",
    "C_deepseek_then_kimi": "Path C (DeepSeek draft + Kimi refine)",
}


JUDGE_SYSTEM_PROMPT = """You are an impartial evaluator scoring three AI-generated company narratives for a Belgian private-equity screener. You see the source dossier they were given AND the three narratives. Your job: score each narrative across five dimensions on a 1-5 scale, then pick an overall winner.

Dimensions (1=worst, 5=best):
- faithfulness: are claims grounded in the source dossier? Penalize hallucinations.
- specificity: concrete vs generic. "makes industrial valves for petrochemical plants" beats "provides high-quality services".
- completeness: are all schema fields filled with non-trivial content?
- coherence: internal consistency. Penalize contradictions between fields.
- calibration: does the confidence rating match the evidence quality? "high" with thin sources is bad; "low" with rich sources is also bad.

Tie-breakers go to the path that's more useful to a deal team in 30 seconds of reading.

Output STRICT JSON only (no markdown, no prose around it):
{
  "scores": {
    "A": {"faithfulness": 1-5, "specificity": 1-5, "completeness": 1-5, "coherence": 1-5, "calibration": 1-5},
    "B": {"faithfulness": 1-5, "specificity": 1-5, "completeness": 1-5, "coherence": 1-5, "calibration": 1-5},
    "C": {"faithfulness": 1-5, "specificity": 1-5, "completeness": 1-5, "coherence": 1-5, "calibration": 1-5}
  },
  "overall_winner": "A" | "B" | "C" | "tie",
  "rationale": "2-3 sentences explaining the winner."
}"""


def load_records(path: Path) -> dict[str, dict]:
    """Group records by CBE -> {path -> record}."""
    by_cbe: dict[str, dict] = defaultdict(dict)
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("error") or not r.get("path"):
                continue
            by_cbe[r["cbe"]][r["path"]] = r
    return dict(by_cbe)


def parse_json_safely(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def render_narrative(record: dict) -> str:
    parsed = record.get("parsed")
    if parsed:
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    return record.get("text") or "(no output)"


async def score_one(cbe: str, paths: dict[str, dict]) -> dict:
    if not all(p in paths for p in ("A_deepseek_alone", "B_kimi_alone", "C_deepseek_then_kimi")):
        return {"cbe": cbe, "error": "missing_paths", "have": list(paths.keys())}

    a, b, c = paths["A_deepseek_alone"], paths["B_kimi_alone"], paths["C_deepseek_then_kimi"]

    # Pull the dossier from the first record (the script doesn't dump it explicitly,
    # but we have the fields we passed in). Reconstruct a brief dossier label.
    dossier = (
        f"Company: {a.get('name')} (CBE {cbe})\n"
        f"City: {a.get('city')} | NACE: {a.get('nace_code')}\n"
        f"Website: {a.get('website_url') or '(none)'}\n"
        f"Pages scraped: {a.get('scraped_pages') or '[]'}\n"
        f"Input dossier size: {a.get('input_chars')} chars\n"
        f"NOTE: full dossier was passed to all three models; you are evaluating their outputs."
    )

    prompt = (
        f"Source dossier metadata:\n{dossier}\n\n"
        f"=== Narrative A (DeepSeek v4 Pro alone) ===\n{render_narrative(a)}\n\n"
        f"=== Narrative B (Kimi K2.6 alone) ===\n{render_narrative(b)}\n\n"
        f"=== Narrative C (DeepSeek draft + Kimi refine) ===\n{render_narrative(c)}\n\n"
        "Score each narrative now. Return JSON only."
    )

    meta = await call_ollama(
        model=JUDGE_MODEL, system=JUDGE_SYSTEM_PROMPT, prompt=prompt,
        max_tokens=JUDGE_MAX_TOKENS, temperature=0.1, timeout_s=240.0,
    )
    parsed = parse_json_safely(meta.get("text", ""))
    return {
        "cbe": cbe,
        "name": a.get("name"),
        "judge_model": JUDGE_MODEL,
        "judge_ok": meta.get("ok"),
        "judge_error": meta.get("error"),
        "judge_latency_ms": meta.get("latency_ms"),
        "judge_raw": meta.get("text", "")[:8000],
        "parsed": parsed,
    }


async def run_all(in_path: Path, out_path: Path, summary_path: Path) -> None:
    by_cbe = load_records(in_path)
    print(f"[score] {len(by_cbe)} companies to judge", flush=True)

    sem = asyncio.Semaphore(3)

    async def _bound(cbe: str, paths: dict) -> dict:
        async with sem:
            try:
                return await score_one(cbe, paths)
            except Exception as e:
                return {"cbe": cbe, "error": f"runtime: {e!r}"}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with out_path.open("w", encoding="utf-8") as fp:
        for fut in asyncio.as_completed([_bound(c, p) for c, p in by_cbe.items()]):
            r = await fut
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
            fp.flush()
            results.append(r)
            print(f"[score] {len(results)}/{len(by_cbe)} done", flush=True)

    write_summary(results, summary_path)
    print(f"[score] wrote {out_path} and {summary_path}", flush=True)


def write_summary(results: list[dict], summary_path: Path) -> None:
    """Aggregate scores into a markdown summary."""
    sums: dict[str, dict[str, int]] = {p: {d: 0 for d in DIMENSIONS} for p in ("A", "B", "C")}
    counts = 0
    win_counts = {"A": 0, "B": 0, "C": 0, "tie": 0}
    per_company_rows: list[str] = []

    for r in results:
        parsed = r.get("parsed") or {}
        scores = parsed.get("scores") or {}
        if not all(k in scores for k in ("A", "B", "C")):
            continue
        ok = True
        for path in ("A", "B", "C"):
            for d in DIMENSIONS:
                v = scores[path].get(d)
                if not isinstance(v, (int, float)):
                    ok = False
                    break
                sums[path][d] += int(v)
            if not ok:
                break
        if not ok:
            continue
        counts += 1
        winner = parsed.get("overall_winner") or "tie"
        if winner not in win_counts:
            winner = "tie"
        win_counts[winner] += 1
        a_total = sum(scores["A"][d] for d in DIMENSIONS)
        b_total = sum(scores["B"][d] for d in DIMENSIONS)
        c_total = sum(scores["C"][d] for d in DIMENSIONS)
        per_company_rows.append(
            f"| {r.get('cbe')} | {r.get('name','')[:30]} | {a_total} | {b_total} | {c_total} | {winner} |"
        )

    lines: list[str] = []
    lines.append("# Phase-5 elaboration A/B benchmark — judge results")
    lines.append("")
    lines.append(f"Companies scored: **{counts}** (of {len(results)} attempted)")
    lines.append(f"Judge: `{JUDGE_MODEL}`")
    lines.append("")
    lines.append("## Aggregate scores (averaged 1-5)")
    lines.append("")
    lines.append("| Path | Faithfulness | Specificity | Completeness | Coherence | Calibration | Total |")
    lines.append("|------|---|---|---|---|---|---|")
    for path, label in [("A", "DeepSeek v4 Pro alone"), ("B", "Kimi K2.6 alone"),
                        ("C", "DeepSeek + Kimi refine")]:
        if counts == 0:
            continue
        avgs = {d: sums[path][d] / counts for d in DIMENSIONS}
        total = sum(avgs.values())
        lines.append(
            f"| **{path}** {label} | {avgs['faithfulness']:.2f} | "
            f"{avgs['specificity']:.2f} | {avgs['completeness']:.2f} | "
            f"{avgs['coherence']:.2f} | {avgs['calibration']:.2f} | "
            f"**{total:.2f}** / 25 |"
        )
    lines.append("")
    lines.append("## Overall winner counts")
    lines.append("")
    for k in ("A", "B", "C", "tie"):
        lines.append(f"- **{k}**: {win_counts[k]}")
    lines.append("")
    lines.append("## Per-company score totals")
    lines.append("")
    lines.append("| CBE | Name | A total | B total | C total | Winner |")
    lines.append("|-----|------|---------|---------|---------|--------|")
    lines.extend(per_company_rows)
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()
    asyncio.run(run_all(Path(args.in_path), Path(args.out), Path(args.summary)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
