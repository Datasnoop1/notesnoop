"""Evaluation harness for /api/companies/{cbe}/similar/ai.

Usage
-----
    python backend/eval/similar_companies_eval.py                # DEFAULT tier
    python backend/eval/similar_companies_eval.py --tier CHEAP   # CHEAP tier
    python backend/eval/similar_companies_eval.py --tier BOTH    # both, two runs

The golden set lives at backend/eval/golden_set.json (list of
``{"target_cbe": "...", "peers": ["...", ...]}``). Populate it by hand;
the loader ignores entries with an empty ``target_cbe`` so the scaffold
file does not cause failures before you label real targets.

Outputs two CSVs into backend/eval/results/:
    eval_<timestamp>.csv          — one row per (target, tier)
    eval_<timestamp>_summary.csv  — aggregated by tier

Metrics: Recall@10, Precision@10, nDCG@10, reason-specificity 0-3
(LLM-judged, prompt pinned below), latency, tokens, cost, degraded rate.

The harness is intentionally self-contained — it exercises the exported
functions of ``backend.retrieval``, ``backend.rerank``, and
``backend.similar_cache`` directly rather than going through HTTP, so you
can run it without the FastAPI app. It still talks to the live Postgres
and OpenRouter, so run it against a staging dataset.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import logging
import math
import os
import statistics
import sys
from pathlib import Path

# Allow running as a script from repo root: add backend/ to sys.path.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from ai_client import ai_complete_with_meta  # noqa: E402
from ai_routing import SIMILAR_COMPANIES_ROUTING, estimate_cost_usd, get_tier_config  # noqa: E402
from db import fetch_one  # noqa: E402
from retrieval import (  # noqa: E402
    LLM_INPUT_SET_SIZE,
    blend_candidates,
    leg_needs_fallback,
    retrieve_by_embedding,
    retrieve_by_nace,
    retrieve_by_size_band,
)
from rerank import call_rerank_llm, render_prompt  # noqa: E402
from similar_cache import ensure_similar_cache_schema  # noqa: E402
from utils import clean_cbe  # noqa: E402


logger = logging.getLogger("similar_companies_eval")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
RESULTS_DIR = Path(__file__).parent / "results"


JUDGE_PROMPT = """You are scoring the specificity of a one-sentence rationale for why two Belgian companies are similar. The rationale was produced by an AI deal-sourcing tool. Score on a 0-3 integer rubric:

0 = GENERIC. Uses only words like "same sector", "similar activity", "related industry", "comparable business", without naming a product, service, customer segment, or business model.
1 = NACE-LEVEL. Names the industry or NACE description in words (e.g. "wholesale trade", "manufacturing of machinery") but does not name a concrete product or customer segment.
2 = PRODUCT/SERVICE-LEVEL. Names a specific product category, service, or trade (e.g. "industrial abrasives", "cold-chain logistics", "HR payroll software").
3 = PRODUCT + SEGMENT/MODEL. Names a specific product AND a customer segment OR a business model (distributor / manufacturer / B2B service / franchise / etc.).

Rationale to score:
{reason}

Return ONLY a JSON object of the form {{"score": N}} where N is an integer in 0..3. No prose."""


# ──────────────────────────────────────────────────────────────────────────
# Golden set loading
# ──────────────────────────────────────────────────────────────────────────

def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    """Load the golden set, stripping comment entries."""
    if not path.exists():
        raise FileNotFoundError(f"Golden set not found at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("Golden set must be a JSON array.")
    entries = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        # Drop the scaffold entry (empty target_cbe) and any entry whose
        # first key is a _comment marker.
        target = clean_cbe(str(entry.get("target_cbe") or ""))
        peers_raw = entry.get("peers") or []
        peers = [clean_cbe(str(p)) for p in peers_raw if p]
        if not target or len(target) != 10:
            continue
        if not peers:
            continue
        entries.append({
            "target_cbe": target,
            "peers": peers,
        })
    return entries


# ──────────────────────────────────────────────────────────────────────────
# Endpoint replay — call the pipeline directly for a fixed tier
# ──────────────────────────────────────────────────────────────────────────

async def run_for_target(target_cbe: str, tier: str, focus: str = "activity", limit: int = 10) -> dict:
    """Drive the same pipeline the router uses, but with a pinned tier."""
    cfg = get_tier_config(tier)
    target = fetch_one(
        """
        SELECT ci.enterprise_number, ci.name, ci.nace_code, ci.city, ci.zipcode,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
               COALESCE(nl.description, ci.nace_code) AS nace_desc,
               ce.ai_insights
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
        WHERE ci.enterprise_number = %s
        """,
        (target_cbe,),
    )
    if not target:
        return {"error": "target_not_found", "returned": []}

    try:
        has_embedding = bool(fetch_one(
            "SELECT 1 FROM company_embedding WHERE enterprise_number = %s", (target_cbe,),
        ))
    except Exception:
        has_embedding = False

    leg_a = retrieve_by_embedding(target_cbe, has_embedding)
    leg_b = retrieve_by_nace(target_cbe, target.get("nace_code"), target.get("revenue"))
    legs = {"embedding": leg_a, "nace": leg_b, "size_band": []}
    if leg_needs_fallback(legs):
        legs["size_band"] = retrieve_by_size_band(target_cbe, target.get("revenue"))

    blended = blend_candidates(legs, focus, target)[:LLM_INPUT_SET_SIZE]
    if not blended:
        return {"error": "no_candidates", "returned": []}

    started = dt.datetime.now(dt.timezone.utc)
    llm = {
        "items": None,
        "model_used": None,
        "attempted": [],
        "latencies": {},
        "usage": {},
        "error": "skipped",
    }
    if len(blended) >= 5:
        prompt = render_prompt(target, blended, limit)
        llm = await call_rerank_llm(prompt, tier, n_candidates=len(blended))
    elapsed_ms = int((dt.datetime.now(dt.timezone.utc) - started).total_seconds() * 1000)

    items = llm.get("items")
    degraded = llm.get("error") if items is None else None

    # Produce the final ordered list of returned CBEs + reasons, matching
    # the router's _apply_llm_ranking semantics.
    ranked: list[dict] = []
    if items:
        sorted_items = sorted(items, key=lambda x: x["rank"])
        used: set[int] = set()
        for entry in sorted_items:
            idx = entry["index"] - 1
            if idx < 0 or idx >= len(blended) or idx in used:
                continue
            used.add(idx)
            ranked.append({
                "enterprise_number": blended[idx]["enterprise_number"],
                "reason": entry["reason"],
                "match_score": blended[idx]["match_score"],
            })
            if len(ranked) >= limit:
                break
    else:
        for c in blended[:limit]:
            ranked.append({
                "enterprise_number": c["enterprise_number"],
                "reason": None,
                "match_score": c["match_score"],
            })

    input_tokens = sum(u.get("input_tokens", 0) for u in (llm.get("usage") or {}).values())
    output_tokens = sum(u.get("output_tokens", 0) for u in (llm.get("usage") or {}).values())
    cost = sum(
        estimate_cost_usd(m, u.get("input_tokens", 0), u.get("output_tokens", 0))
        for m, u in (llm.get("usage") or {}).items()
    )

    return {
        "target_name": target.get("name"),
        "target_revenue": float(target.get("revenue") or 0) if target.get("revenue") else 0,
        "tier": tier,
        "model_used": llm.get("model_used") or cfg["model"],
        "returned": ranked,
        "latency_ms": elapsed_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
        "degraded": degraded,
        "degraded_reason": degraded,
    }


# ──────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────

def recall_at_k(returned_cbes: list[str], golden_cbes: list[str], k: int = 10) -> float:
    if not golden_cbes:
        return 0.0
    top = set(returned_cbes[:k])
    hits = sum(1 for c in golden_cbes if c in top)
    return hits / len(golden_cbes)


def precision_at_k(returned_cbes: list[str], golden_cbes: list[str], k: int = 10) -> float:
    top = returned_cbes[:k]
    if not top:
        return 0.0
    golden_set = set(golden_cbes)
    hits = sum(1 for c in top if c in golden_set)
    return hits / len(top)


def ndcg_at_k(returned_cbes: list[str], golden_cbes: list[str], k: int = 10) -> float:
    golden_set = set(golden_cbes)
    gains = [1 if c in golden_set else 0 for c in returned_cbes[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal_hits = min(len(golden_cbes), k)
    idcg = sum(1 / math.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0:
        return 0.0
    return dcg / idcg


async def score_reason_specificity(reason: str | None) -> int:
    """Ask the judge model (Haiku) for a 0..3 specificity score. Returns 0 if
    the reason is missing or the judge fails."""
    if not reason or not reason.strip():
        return 0
    prompt = JUDGE_PROMPT.replace("{reason}", reason.strip())
    meta = await ai_complete_with_meta(
        prompt,
        system="",
        model="anthropic/claude-haiku-4-5",
        max_tokens=40,
        temperature=0.0,
        timeout_s=8.0,
    )
    if not meta.get("ok"):
        return 0
    raw = meta["text"].strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0:
            return 0
        data = json.loads(raw[start:end + 1])
        score = int(data.get("score", 0))
        return max(0, min(3, score))
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0


# ──────────────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────────────

async def eval_one(
    golden_entry: dict,
    tier: str,
    focus: str,
    run_id: str,
) -> dict:
    target = golden_entry["target_cbe"]
    peers = golden_entry["peers"]

    result = await run_for_target(target, tier, focus=focus)
    returned = result.get("returned", [])
    returned_cbes = [r["enterprise_number"] for r in returned]
    reasons = [r.get("reason") for r in returned]

    spec_scores = [await score_reason_specificity(r) for r in reasons]
    spec_mean = statistics.mean(spec_scores) if spec_scores else 0.0
    spec_min = min(spec_scores) if spec_scores else 0

    return {
        "run_id": run_id,
        "target_cbe": target,
        "target_name": result.get("target_name") or "",
        "target_revenue": result.get("target_revenue") or 0,
        "focus": focus,
        "model_tier": tier,
        "model_used": result.get("model_used") or "",
        "recall_at_10": round(recall_at_k(returned_cbes, peers, k=10), 4),
        "precision_at_10": round(precision_at_k(returned_cbes, peers, k=10), 4),
        "ndcg_at_10": round(ndcg_at_k(returned_cbes, peers, k=10), 4),
        "reason_specificity_mean": round(spec_mean, 3),
        "reason_specificity_min": spec_min,
        "latency_ms": result.get("latency_ms") or 0,
        "input_tokens": result.get("input_tokens") or 0,
        "output_tokens": result.get("output_tokens") or 0,
        "cost_usd": result.get("cost_usd") or 0.0,
        "degraded": bool(result.get("degraded")),
        "degraded_reason": result.get("degraded_reason") or "",
        "returned_count": len(returned_cbes),
        "golden_count": len(peers),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


PER_ROW_COLS = (
    "run_id", "target_cbe", "target_name", "target_revenue",
    "focus", "model_tier", "model_used",
    "recall_at_10", "precision_at_10", "ndcg_at_10",
    "reason_specificity_mean", "reason_specificity_min",
    "latency_ms", "input_tokens", "output_tokens", "cost_usd",
    "degraded", "degraded_reason", "returned_count", "golden_count",
    "timestamp",
)

SUMMARY_COLS = (
    "model_tier", "model_used",
    "recall_at_10_mean", "precision_at_10_mean", "ndcg_at_10_mean",
    "reason_specificity_mean",
    "latency_p50", "latency_p95",
    "cost_usd_mean", "cost_usd_total",
    "degradation_rate", "n_runs",
)


def write_per_row_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PER_ROW_COLS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in PER_ROW_COLS})


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    by_tier: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r["model_tier"], r.get("model_used") or "")
        by_tier.setdefault(key, []).append(r)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLS)
        writer.writeheader()
        for (tier, model), group in sorted(by_tier.items()):
            latencies = [r.get("latency_ms") or 0 for r in group]
            costs = [r.get("cost_usd") or 0.0 for r in group]
            writer.writerow({
                "model_tier": tier,
                "model_used": model,
                "recall_at_10_mean": round(statistics.mean(r["recall_at_10"] for r in group), 4),
                "precision_at_10_mean": round(statistics.mean(r["precision_at_10"] for r in group), 4),
                "ndcg_at_10_mean": round(statistics.mean(r["ndcg_at_10"] for r in group), 4),
                "reason_specificity_mean": round(
                    statistics.mean(r["reason_specificity_mean"] for r in group), 3,
                ),
                "latency_p50": int(_percentile(latencies, 0.5)),
                "latency_p95": int(_percentile(latencies, 0.95)),
                "cost_usd_mean": round(statistics.mean(costs), 6),
                "cost_usd_total": round(sum(costs), 6),
                "degradation_rate": round(
                    sum(1 for r in group if r["degraded"]) / len(group), 4,
                ),
                "n_runs": len(group),
            })


async def main_async(tiers: list[str], focus: str) -> int:
    ensure_similar_cache_schema()
    golden = load_golden_set()
    if not golden:
        logger.error(
            "Golden set at %s is empty — populate it with real (target, peers) pairs "
            "before running the eval.", GOLDEN_SET_PATH,
        )
        return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    run_id = f"run_{stamp}"
    rows: list[dict] = []
    for tier in tiers:
        logger.info("Eval starting for tier=%s focus=%s n=%d", tier, focus, len(golden))
        for entry in golden:
            try:
                rows.append(await eval_one(entry, tier, focus, run_id))
            except Exception:
                logger.exception(
                    "Eval failed for target=%s tier=%s — recording degraded row",
                    entry.get("target_cbe"), tier,
                )
                rows.append({
                    "run_id": run_id,
                    "target_cbe": entry.get("target_cbe") or "",
                    "target_name": "",
                    "target_revenue": 0,
                    "focus": focus,
                    "model_tier": tier,
                    "model_used": "",
                    "recall_at_10": 0.0, "precision_at_10": 0.0, "ndcg_at_10": 0.0,
                    "reason_specificity_mean": 0.0, "reason_specificity_min": 0,
                    "latency_ms": 0, "input_tokens": 0, "output_tokens": 0,
                    "cost_usd": 0.0,
                    "degraded": True, "degraded_reason": "eval_exception",
                    "returned_count": 0, "golden_count": len(entry.get("peers") or []),
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                })

    per_row_path = RESULTS_DIR / f"eval_{stamp}.csv"
    summary_path = RESULTS_DIR / f"eval_{stamp}_summary.csv"
    write_per_row_csv(per_row_path, rows)
    write_summary_csv(summary_path, rows)
    logger.info("Wrote %s and %s", per_row_path, summary_path)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate /similar/ai against a golden set.")
    parser.add_argument("--tier", choices=["DEFAULT", "CHEAP", "BOTH"], default="BOTH")
    parser.add_argument("--focus", choices=["activity", "size", "geography"], default="activity")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tiers = ["DEFAULT", "CHEAP"] if args.tier == "BOTH" else [args.tier]
    return asyncio.run(main_async(tiers, args.focus))


if __name__ == "__main__":
    raise SystemExit(main())
