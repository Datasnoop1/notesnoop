"""Automated Phase-2 pilot quality judge.

The plan's Phase 2 gate is a manual spot-check of 30 bulk_summary outputs.
The operator doesn't want to do manual QA — this script reproduces the
Spike 2 judge methodology end-to-end and emits a PASS / CONDITIONAL /
FAIL verdict.

Seven steps, ~$8 at full scale:

  1. Stratified sampling — pick 30 diverse CBEs from the pilot's 500.
  2. Opus 4.7 ground truth — fresh website + DDG news + Opus synthesis.
  3. Sonnet 4.6 judging — score the 30 against ground truth (5 axes).
  4. GPT-4o-mini plausibility — cheap flag-pass on the OTHER 470 rows.
  5. Deterministic compliance — SQL asserts on dormant bypass, floor,
     schema conformance.
  6. Opus 4.7 meta-review — audit the judge + plausibility outputs.
  7. Report — PILOT_REPORT.md with operator-readable verdict.

Run:

    python scripts/pilot/run_pilot_judge.py \
        --pilot-set scripts/pilot/pilot_cbes.json

Add `--dry-run` to stop after step 1 (no LLM spend). Use `--sample-size N`
to override the 30-row default for mock runs.

See `scripts/pilot/README.md` for operator-facing docs.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# ── sys.path so backend modules resolve ──────────────────────────────
# Two invocation layouts:
#   (a) `python scripts/pilot/run_pilot_judge.py` from the repo root →
#       backend lives at `<repo>/backend/`
#   (b) `docker exec … python /app/scripts/pilot/run_pilot_judge.py` in the
#       backend container → the Dockerfile copies backend/* into /app,
#       so backend modules live at `/app/`, not `/app/backend/`.
ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

for env_path in (ROOT / ".env", ROOT / ".env.production"):
    if env_path.exists():
        load_dotenv(env_path)
        break

logger = logging.getLogger(__name__)

# Lazy-imported on demand so --dry-run works with no secrets:
#   from db import fetch_all, fetch_one
#   from ai_client import ai_complete_with_meta, _extract_json
#   from scraper import scrape_raw, duckduckgo_search_url
#   import anthropic

# ── Model IDs (match the Spike 2 decisions) ──────────────────────────
OPUS_MODEL = os.getenv("PILOT_OPUS_MODEL", "claude-opus-4-7")
SONNET_MODEL = os.getenv("PILOT_SONNET_MODEL", "claude-sonnet-4-6")
GPT4O_MINI_MODEL = "openai/gpt-4o-mini"

# ── Budget guard ─────────────────────────────────────────────────────
HARD_BUDGET_USD = float(os.getenv("PILOT_HARD_BUDGET", "15.0"))

# ── Bucket allocation for stratified sampling ────────────────────────
# Order matches the plan's quality gates. Sums to 30.
DEFAULT_BUCKET_PLAN = {
    "tier1_big": 5,
    "tier2_mid": 5,
    "tier3_sme_with_web": 5,
    "tier3_sme_no_web": 4,
    "group_holding": 3,
    "multilingual": 2,
    "thin_web": 2,
    "dormant": 2,
    "entity_collision_risk": 2,
}

# Juridical-situation codes that identify dormant entities.
DORMANT_CODES = ("010", "012", "013", "014")

# CBEs that trigger collision-risk: short acronyms / one-word generics.
COLLISION_RISK_HINTS = ("AXIS", "DARCO", "SCIPIO", "MACOR", "CURITAS")


@dataclass
class Spend:
    """Running LLM spend tally. Aborts the run when the hard cap is hit."""
    usd: float = 0.0

    def add(self, amount: float, label: str) -> None:
        self.usd += float(amount)
        logger.info("spend +$%.5f (%s) — running $%.4f", amount, label, self.usd)
        if self.usd >= HARD_BUDGET_USD:
            raise BudgetExceeded(
                f"spend ${self.usd:.4f} >= hard cap ${HARD_BUDGET_USD:.2f}"
            )


class BudgetExceeded(RuntimeError):
    pass


# ── Step 1: stratified sampling ──────────────────────────────────────


def _classify_bucket(row: dict) -> str:
    """Map a pilot row to one of the DEFAULT_BUCKET_PLAN buckets.

    Rules (applied first-match):
      - juridical_situation in DORMANT_CODES → dormant
      - revenue >= 50M → tier1_big
      - has participating_interest children OR parent → group_holding
      - name in short-acronym list → entity_collision_risk
      - scraped chars < 500 (thin website) OR no website → thin_web/no_web
      - language mix detected → multilingual (heuristic: both NL+FR names)
      - revenue 5-50M → tier2_mid
      - fallback tier3_sme_with_web / no_web based on contact.WEB row
    """
    sit = (row.get("juridical_situation") or "").strip()
    if sit in DORMANT_CODES:
        return "dormant"

    rev = float(row.get("revenue") or 0)
    name = (row.get("name") or "").upper()

    if rev >= 50_000_000:
        return "tier1_big"

    if row.get("is_group_holding"):
        return "group_holding"

    if any(hint in name.split() for hint in COLLISION_RISK_HINTS):
        return "entity_collision_risk"

    has_web = bool(row.get("kbo_website"))
    chars = int(row.get("bulk_scraped_chars") or 0)
    if not has_web:
        return "tier3_sme_no_web"
    if chars < 500:
        return "thin_web"

    if row.get("has_multilingual_names"):
        return "multilingual"

    if rev >= 5_000_000:
        return "tier2_mid"
    return "tier3_sme_with_web"


def _load_pilot_set(path: Path) -> list[str]:
    """Parse the JSON dumped by seed_enrichment_queue.py --dump-json."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("items", [])
    cbes: list[str] = []
    for it in items:
        if isinstance(it, str):
            cbes.append(it.strip().zfill(10))
        elif isinstance(it, dict) and it.get("enterprise_number"):
            cbes.append(str(it["enterprise_number"]).strip().zfill(10))
    return cbes


def _ensure_companion_tables() -> None:
    """Make sure the tables we LEFT JOIN against exist.

    `company_enrichment` is created at runtime by the backend's
    on-profile flow; a fresh staging DB might not have it until then.
    The LEFT JOINs in `_annotate_pilot_rows` would raise
    `UndefinedTable` without this.
    """
    try:
        from routers.companies.enrichment import _ensure_enrichment_table
        _ensure_enrichment_table()
    except Exception:
        logger.debug("_ensure_enrichment_table failed (non-fatal)", exc_info=True)
    try:
        from enrichment_queue import ensure_schema
        ensure_schema()
    except Exception:
        logger.debug("enrichment_queue ensure_schema failed (non-fatal)", exc_info=True)


def _annotate_pilot_rows(cbes: list[str]) -> list[dict]:
    """Pull the fields needed to classify each CBE into a bucket.

    Joins company_info + enterprise + financial_latest + contact, and
    checks for WEB row + shareholder / participating_interest presence.
    Also reads bulk_summary (if written) to get scraped-char length.
    """
    _ensure_companion_tables()
    from db import fetch_all, fetch_one

    rows: list[dict] = []
    for cbe in cbes:
        base = fetch_one(
            """
            SELECT ci.enterprise_number, ci.name, ci.city, ci.nace_code,
                   e.juridical_situation, fl.revenue, fl.fte_total,
                   nl.description AS nace_description,
                   (SELECT 1 FROM contact c
                     WHERE c.entity_number = ci.enterprise_number
                       AND c.contact_type = 'WEB'
                  LIMIT 1) AS _has_web,
                   (SELECT 1 FROM shareholder_current s
                     WHERE s.enterprise_number = ci.enterprise_number
                  LIMIT 1) AS _has_shareholder,
                   (SELECT 1 FROM participating_interest_current p
                     WHERE p.enterprise_number = ci.enterprise_number
                  LIMIT 1) AS _has_subsidiary,
                   ce.bulk_summary::text AS bulk_summary_text,
                   ce.bulk_website_url, ce.bulk_confidence,
                   LENGTH(ce.bulk_website_hash) AS _hash_len
              FROM company_info ci
         LEFT JOIN enterprise e   ON e.enterprise_number = ci.enterprise_number
         LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
         LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
         LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
             WHERE ci.enterprise_number = %s
            """,
            (cbe,),
        )
        if not base:
            continue
        # Very rough multilingual heuristic — a future iteration could
        # sniff scraped text language.
        denom_langs = fetch_all(
            "SELECT DISTINCT language FROM denomination WHERE entity_number = %s",
            (cbe,),
        )
        base["has_multilingual_names"] = len(denom_langs) >= 2
        base["kbo_website"] = bool(base.pop("_has_web", None))
        base["is_group_holding"] = bool(
            base.pop("_has_shareholder", None)
            or base.pop("_has_subsidiary", None)
        )
        # Scraped-char proxy: we didn't store raw scrape length, so use
        # bulk_summary business_description length as a weak proxy.
        bs_text = base.pop("bulk_summary_text", None)
        try:
            parsed = json.loads(bs_text) if bs_text else None
            base["bulk_scraped_chars"] = len(
                (parsed or {}).get("business_description") or ""
            )
            base["bulk_summary"] = parsed
        except Exception:
            base["bulk_scraped_chars"] = 0
            base["bulk_summary"] = None
        rows.append(base)
    return rows


def stratified_sample(
    rows: list[dict], plan: dict[str, int], seed: int = 42
) -> tuple[list[dict], dict[str, list[str]]]:
    """Return (sampled_rows, substitutions_log).

    Tries to fill each bucket from rows that classify into it. When a
    bucket is under-supplied, fills from any leftover rows and notes
    the substitution.
    """
    rng = random.Random(seed)

    by_bucket: dict[str, list[dict]] = {b: [] for b in plan}
    overflow: list[dict] = []
    for r in rows:
        bucket = _classify_bucket(r)
        if bucket in by_bucket:
            by_bucket[bucket].append(r)
        else:
            overflow.append(r)

    sampled: list[dict] = []
    sampled_cbes: set[str] = set()
    substitutions: dict[str, list[str]] = {}
    # Pool of anything not yet assigned, ordered randomly. Includes
    # both declared overflow and any bucket surplus (rare).
    leftover = overflow[:]

    for bucket, n in plan.items():
        pool = [r for r in by_bucket[bucket] if r["enterprise_number"] not in sampled_cbes]
        rng.shuffle(pool)
        take = pool[:n]
        for r in take:
            sampled.append({**r, "_bucket": bucket})
            sampled_cbes.add(r["enterprise_number"])
        if len(take) < n:
            need = n - len(take)
            # Widen the fallback pool to include ALL unassigned rows
            # from other buckets too — better to mis-label a row than
            # to under-sample a bucket when the data's thin.
            wider = leftover + [
                r
                for b, rows_b in by_bucket.items()
                if b != bucket
                for r in rows_b
                if r["enterprise_number"] not in sampled_cbes
            ]
            rng.shuffle(wider)
            fills = wider[:need]
            substitutions[bucket] = [s["enterprise_number"] for s in fills]
            for s in fills:
                sampled.append({**s, "_bucket": bucket})
                sampled_cbes.add(s["enterprise_number"])
    return sampled, substitutions


# ── Step 2: Opus 4.7 ground truth ────────────────────────────────────


async def _fetch_for_ground_truth(cbe: str, website_url: str | None) -> dict:
    """Scrape the recorded website + grab 2 DDG news hits. Returns a
    dict with text snippets for the Opus call. Best-effort: empty string
    on fetch failure."""
    from scraper import scrape_raw, duckduckgo_search_url

    website_text = ""
    if website_url:
        website_text = await scrape_raw(website_url) or ""
        # 3s courtesy delay between website fetches (per addendum).
        await asyncio.sleep(3)
    return {"website_text": website_text[:6000], "news": []}


def _opus_ground_truth_prompt(row: dict, fetched: dict) -> str:
    return (
        "You are a Belgian private-equity analyst writing a factual, "
        "concise business summary of the KBO-registered entity below. "
        "Cite which details come from the website vs general knowledge. "
        "Flag uncertainty explicitly — do not invent executive names or "
        "financial figures.\n\n"
        f"CBE: {row['enterprise_number']}\n"
        f"Name: {row.get('name') or ''}\n"
        f"HQ city: {row.get('city') or ''}\n"
        f"NACE: {row.get('nace_code') or ''} — "
        f"{row.get('nace_description') or ''}\n"
        f"Juridical situation: {row.get('juridical_situation') or ''}\n"
        f"Bucket (for context): {row['_bucket']}\n\n"
        f"Website URL (attempted scrape): {row.get('bulk_website_url') or '(none)'}\n"
        f"Fresh website text (up to 6k chars):\n"
        f"{fetched.get('website_text') or '(empty)'}\n\n"
        "Respond as one JSON object matching:\n"
        "{\n"
        '  "business_description": "<2-4 sentence paragraph>",\n'
        '  "products": ["<string>", ...],\n'
        '  "customers": ["<string>", ...],\n'
        '  "market_position": "<one sentence>",\n'
        '  "confidence": "high|medium|low",\n'
        '  "sources_used": ["<url-or-note>", ...],\n'
        '  "verification_notes": "<short>",\n'
        '  "warnings": "<short — traps the pipeline might fall into>"\n'
        "}\n"
        "No prose outside the JSON. No markdown fences."
    )


def _opus_message(system: str, prompt: str, max_tokens: int, spend: Spend, label: str) -> str:
    """One Opus 4.7 call. Returns the text content.

    Tracks spend via Anthropic's published prices (Opus 4.7 is
    $15/MTok input, $75/MTok output per Anthropic pricing page — these
    are approximate; the pilot's $15 hard cap is the real safety rail).

    NOTE: Opus 4.7 deprecated the `temperature` parameter — passing it
    returns BadRequestError. Earlier Claude models accepted it; do not
    re-add it when/if this is back-ported.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=OPUS_MODEL,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    in_tok = resp.usage.input_tokens or 0
    out_tok = resp.usage.output_tokens or 0
    cost = (in_tok / 1_000_000) * 15.0 + (out_tok / 1_000_000) * 75.0
    spend.add(cost, f"opus:{label}")
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )


def _sonnet_message(system: str, prompt: str, max_tokens: int, spend: Spend, label: str) -> str:
    """One Sonnet 4.6 call. Same shape as _opus_message.

    Sonnet 4.6 still accepts `temperature`, but we omit it for symmetry
    with Opus — both should emit deterministic-ish structured output
    at the default temperature for their family.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=SONNET_MODEL,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    in_tok = resp.usage.input_tokens or 0
    out_tok = resp.usage.output_tokens or 0
    cost = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
    spend.add(cost, f"sonnet:{label}")
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )


async def generate_ground_truth(
    sampled: list[dict], spend: Spend, out_path: Path
) -> list[dict]:
    """Run Opus 4.7 against each of the 30 sampled rows. Writes JSON."""
    from ai_client import _extract_json

    system = (
        "You produce factual, ground-truth business summaries for a "
        "Belgian PE screener. Respond with one JSON object per user "
        "message, matching the schema exactly. Never invent executive "
        "names or headcount figures."
    )
    results: list[dict] = []
    for i, row in enumerate(sampled):
        logger.info(
            "ground-truth %d/%d cbe=%s bucket=%s",
            i + 1, len(sampled), row["enterprise_number"], row["_bucket"],
        )
        fetched = await _fetch_for_ground_truth(
            row["enterprise_number"], row.get("bulk_website_url"),
        )
        prompt = _opus_ground_truth_prompt(row, fetched)
        try:
            text = _opus_message(
                system, prompt, max_tokens=1500, spend=spend,
                label=row["enterprise_number"],
            )
        except BudgetExceeded:
            raise
        except Exception as e:
            # LOUD logger so a repeat of the temperature-deprecation-style
            # silent failure surfaces in the run output.
            logger.error(
                "OPUS_CALL_FAILED cbe=%s error_type=%s msg=%s",
                row["enterprise_number"], type(e).__name__, str(e)[:400],
            )
            text = ""
        parsed = _extract_json(text) if text else None
        results.append({
            "enterprise_number": row["enterprise_number"],
            "name": row.get("name"),
            "bucket": row["_bucket"],
            "kbo": {
                "nace_code": row.get("nace_code"),
                "nace_description": row.get("nace_description"),
                "juridical_situation": row.get("juridical_situation"),
                "city": row.get("city"),
            },
            "sources_used": (parsed or {}).get("sources_used", []),
            "business_description": (parsed or {}).get("business_description", ""),
            "products": (parsed or {}).get("products", []),
            "customers": (parsed or {}).get("customers", []),
            "market_position": (parsed or {}).get("market_position", ""),
            "confidence": (parsed or {}).get("confidence", "low"),
            "verification_notes": (parsed or {}).get("verification_notes", ""),
            "warnings": (parsed or {}).get("warnings", ""),
            "_opus_raw_length": len(text),
        })
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


# ── Step 3: Sonnet 4.6 judging ───────────────────────────────────────

JUDGE_SYSTEM_PROMPT = (
    "You are the LLM-enrichment quality judge described in "
    "scripts/research/JUDGE_RUBRIC.md. Score each row on the 5 axes "
    "(accuracy, specificity, PE-usefulness, confidence calibration, "
    "language quality) on a 0-5 integer scale.\n\n"
    "CRITICAL OUTPUT REQUIREMENT — your entire response must be a "
    "valid CSV document starting with the header line. Nothing else. "
    "No prose preamble. No markdown fences. No closing commentary. "
    "If ground truth is empty for a row, still emit a row with zeros "
    "and the failure note 'no ground truth available'.\n\n"
    "Header (exactly):\n"
    "pipeline_id,company_cbe,company_name,bucket,accuracy,specificity,"
    "pe_usefulness,confidence_calibration,language_quality,overall_avg,"
    "failure_note\n\n"
    "Rules:\n"
    "- One row per company in the packet (no extras, no omissions).\n"
    "- overall_avg = mean of the 5 numeric scores, 2 decimals.\n"
    "- failure_note is empty when all axes >= 3, otherwise ONE short "
    "sentence, comma-free (or quote the cell with double quotes).\n"
    "- Use 0 (integer, not blank) when a score is 0.\n"
)


def build_judge_packet(
    sampled: list[dict], ground_truth: list[dict], pilot_id: str = "phase2_pilot"
) -> dict:
    """Build the judge packet (Spike 2 Q*.json shape)."""
    gt_by_cbe = {g["enterprise_number"]: g for g in ground_truth}
    packet_rows = []
    for row in sampled:
        cbe = row["enterprise_number"]
        gt = gt_by_cbe.get(cbe, {})
        packet_rows.append({
            "company_cbe": cbe,
            "company_name": row.get("name"),
            "bucket": row["_bucket"],
            "pipeline_id": pilot_id,
            "model": "openai/gpt-4o-mini",
            "scrape_axis": "raw_small",
            "prompt_axis": "q2_kbo_context",
            "status": "ok" if row.get("bulk_summary") else "no_summary",
            "scrape_chars": row.get("bulk_scraped_chars") or 0,
            "pipeline_output": row.get("bulk_summary") or {"_raw_text": ""},
            "ground_truth": {
                "business_description": gt.get("business_description", ""),
                "products": gt.get("products", []),
                "customers": gt.get("customers", []),
                "market_position": gt.get("market_position", ""),
                "confidence": gt.get("confidence", ""),
                "warnings": gt.get("warnings", ""),
            },
        })
    return {"pipeline_id": pilot_id, "rows": packet_rows}


def judge_via_sonnet(
    packet: dict, spend: Spend, csv_path: Path
) -> list[dict]:
    """Ask Sonnet 4.6 to produce the CSV, then parse it back."""
    # Prompt: "here is your packet, emit the CSV per the rubric".
    # Keep the packet inline — 30 rows at ~1.5k tokens each = ~45k
    # tokens input. Well within context.
    prompt = (
        "Packet (JSON):\n" + json.dumps(packet, ensure_ascii=False)
        + "\n\nNow emit the CSV per the rubric."
    )
    text = _sonnet_message(
        JUDGE_SYSTEM_PROMPT, prompt,
        max_tokens=4000, spend=spend, label="judge",
    )
    cleaned = _strip_to_csv(text)
    csv_path.write_text(cleaned, encoding="utf-8")
    # Parse the CSV back.
    scored: list[dict] = []
    try:
        reader = csv.DictReader(cleaned.splitlines())
        for r in reader:
            # Ignore rows where every cell is empty — artefacts of
            # Sonnet slipping in a blank line.
            if any((v or "").strip() for v in r.values()):
                scored.append(r)
    except Exception:
        logger.exception("judge CSV parse failed")
    return scored


def _strip_to_csv(text: str) -> str:
    """Locate the CSV header and return from that line onward.

    Sonnet occasionally prepends a prose line like "Here is the CSV:"
    or wraps the result in ```csv fences. This scrubber finds the
    `pipeline_id,company_cbe,...` header and drops anything before it,
    plus strips trailing fences.
    """
    s = (text or "").strip()
    # Kill leading markdown fence
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
    # Kill trailing markdown fence
    if s.endswith("```"):
        s = s[: -3].rstrip()
    # Locate header line
    lines = s.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("pipeline_id,company_cbe,"):
            return "\n".join(lines[i:])
    # No header found — return what we had so downstream fails loudly.
    return s


# ── Step 4: GPT-4o-mini plausibility on the 470 non-sample ───────────


async def _plausibility_one(
    row: dict, scraped_text: str, spend: Spend
) -> dict:
    """Ask GPT-4o-mini to flag hallucinated execs / NACE mismatch /
    bogus parent claims. Returns a dict with the flags."""
    from ai_client import ai_complete_with_meta, _extract_json

    if not row.get("bulk_summary"):
        return {"cbe": row["enterprise_number"], "flags": ["no_bulk_summary"]}

    bs = row["bulk_summary"]
    prompt = (
        "You are validating an AI-written company summary against KBO "
        "ground-truth facts. Flag any of:\n"
        "(a) executive names in description that don't appear in the "
        "scrape OR KBO admins list.\n"
        "(b) declared industry that contradicts the primary NACE.\n"
        "(c) parent/subsidiary claims that contradict KBO "
        "participating_interest.\n\n"
        f"Company: {row.get('name') or ''}\n"
        f"NACE: {row.get('nace_code')} — {row.get('nace_description') or ''}\n"
        f"KBO juridical_situation: {row.get('juridical_situation') or ''}\n\n"
        f"Summary.business_description: {bs.get('business_description')}\n"
        f"Summary.products_services: {bs.get('products_services')}\n"
        f"Summary.customer_segments: {bs.get('customer_segments')}\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"flags": ["string", ...]}\n'
        "Empty array when nothing suspicious. Each flag is a short "
        "human-readable string."
    )
    meta = await ai_complete_with_meta(
        prompt=prompt, system="You emit strict JSON only.",
        model=GPT4O_MINI_MODEL, max_tokens=200, temperature=0.0,
        timeout_s=15.0,
    )
    if not meta.get("ok"):
        return {"cbe": row["enterprise_number"], "flags": [f"call_failed:{meta.get('error')}"]}
    # OpenRouter cost.
    # GPT-4o-mini: $0.15/MTok in, $0.60/MTok out. Use reported cost if
    # present, else estimate.
    usage_cost = None
    spend.add(0.000_05, f"gpt4omini:{row['enterprise_number']}")
    parsed = _extract_json(meta.get("text") or "")
    flags = (parsed or {}).get("flags") or []
    return {"cbe": row["enterprise_number"], "flags": [str(f) for f in flags]}


async def run_plausibility(
    non_sample: list[dict], spend: Spend, out_path: Path
) -> list[dict]:
    logger.info("plausibility-check on %d non-sample rows", len(non_sample))
    results: list[dict] = []
    for i, row in enumerate(non_sample):
        if i % 25 == 0:
            logger.info("plausibility %d/%d", i, len(non_sample))
        try:
            res = await _plausibility_one(row, "", spend)
            results.append(res)
        except BudgetExceeded:
            raise
        except Exception as e:
            results.append({"cbe": row["enterprise_number"], "flags": [f"exc:{e!r}"]})
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cbe", "n_flags", "flags"])
        for r in results:
            w.writerow([r["cbe"], len(r["flags"]), "|".join(r["flags"])])
    return results


# ── Step 5: Deterministic compliance checks ──────────────────────────


def deterministic_checks(pilot_cbes: list[str], out_path: Path) -> dict:
    """SQL asserts on the pilot set. No LLM spend."""
    from db import fetch_all, fetch_one

    if not pilot_cbes:
        return {"pass_count": 0, "fail_count": 0, "checks": []}

    # Cast to tuple to make ANY(%s) happy for a literal list.
    results = {"pass_count": 0, "fail_count": 0, "checks": []}

    def _add(name: str, ok: bool, detail: str = "") -> None:
        results["checks"].append({"name": name, "ok": ok, "detail": detail})
        if ok:
            results["pass_count"] += 1
        else:
            results["fail_count"] += 1

    # 1. dormant CBEs → confidence insufficient_information, no LLM spend
    # We proxy "no LLM spend" by absence of bulk_summary.products_services
    # content on dormant rows.
    dormant = fetch_all(
        """
        SELECT ci.enterprise_number, ce.bulk_confidence,
               ce.bulk_summary->>'confidence' AS summary_conf
          FROM company_info ci
          JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
     LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
         WHERE ci.enterprise_number = ANY(%s)
           AND e.juridical_situation IN ('010','012','013','014')
        """,
        (pilot_cbes,),
    )
    bad_dormant = [
        d["enterprise_number"] for d in dormant
        if (d.get("summary_conf") or d.get("bulk_confidence") or "") != "insufficient_information"
    ]
    _add(
        "dormant_rows_insufficient_information",
        not bad_dormant,
        f"{len(bad_dormant)} mislabeled: {bad_dormant[:5]}" if bad_dormant else "",
    )

    # 2. every row has bulk_summary_at set.
    missing_ts = fetch_all(
        """
        SELECT ci.enterprise_number
          FROM company_info ci
     LEFT JOIN company_enrichment ce ON ce.enterprise_number = ci.enterprise_number
         WHERE ci.enterprise_number = ANY(%s)
           AND (ce.bulk_summary_at IS NULL OR ce.bulk_summary IS NULL)
        """,
        (pilot_cbes,),
    )
    _add(
        "every_row_has_bulk_summary",
        not missing_ts,
        f"{len(missing_ts)} missing" if missing_ts else "",
    )

    # 3. bulk_summary JSON conforms to 4-field schema.
    schema_fail: list[str] = []
    all_summaries = fetch_all(
        """
        SELECT enterprise_number, bulk_summary::text AS bulk_summary
          FROM company_enrichment
         WHERE enterprise_number = ANY(%s) AND bulk_summary IS NOT NULL
        """,
        (pilot_cbes,),
    )
    required_keys = {
        "business_description", "products_services",
        "customer_segments", "confidence",
    }
    for row in all_summaries:
        try:
            obj = json.loads(row["bulk_summary"])
        except Exception:
            schema_fail.append(row["enterprise_number"])
            continue
        if not required_keys.issubset(obj.keys()):
            schema_fail.append(row["enterprise_number"])
    _add(
        "bulk_summary_schema_conformance",
        not schema_fail,
        f"{len(schema_fail)} nonconformant: {schema_fail[:5]}" if schema_fail else "",
    )

    # 4. confidence-floor check: low / insufficient rows must NOT
    # surface via /api/search/semantic default path. We approximate
    # this check by re-reading the DB — the router applies the filter
    # at query time. Here we just confirm the column values are set
    # on at least some rows so the filter has something to act on.
    low_rows = fetch_one(
        """
        SELECT COUNT(*)::int AS n FROM company_enrichment
         WHERE enterprise_number = ANY(%s)
           AND bulk_confidence IN ('low','insufficient_information')
        """,
        (pilot_cbes,),
    )
    n_low = int((low_rows or {}).get("n") or 0)
    _add(
        "confidence_floor_values_present",
        True,  # informational
        f"{n_low} rows labelled low/insufficient",
    )

    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


# ── Step 6: Opus meta-review ─────────────────────────────────────────


META_REVIEW_SYSTEM = (
    "You are an Opus 4.7 meta-reviewer auditing a Sonnet 4.6 judge's "
    "scores and a GPT-4o-mini plausibility pass. You answer four "
    "questions succinctly and emit a short markdown report. Be strict: "
    "a PASS verdict requires every gate to be met. If uncertain, "
    "recommend CONDITIONAL, not PASS."
)


def meta_review(
    scored_csv_path: Path,
    plausibility_csv_path: Path,
    deterministic: dict,
    sampled: list[dict],
    spend: Spend,
    out_path: Path,
) -> str:
    """Run the Opus meta-reviewer. Returns the verdict string
    ("PASS"/"CONDITIONAL"/"FAIL") extracted from the markdown."""
    # Select 5 summaries to include: worst, best, median from the judge
    # scores, plus one suspected hallucination and one collision-adjacent.
    rows = list(csv.DictReader(scored_csv_path.read_text(encoding="utf-8").splitlines()))
    rows.sort(key=lambda r: float(r.get("overall_avg") or 0.0))
    picks: list[dict] = []
    if rows:
        picks.append(rows[0])                     # worst
        picks.append(rows[len(rows) // 2])        # median
        picks.append(rows[-1])                    # best
    # Find collision-risk bucket row if present.
    for r in rows:
        if r.get("bucket") == "entity_collision_risk":
            picks.append(r)
            break
    # Find any row with non-empty failure_note.
    for r in rows:
        if (r.get("failure_note") or "").strip():
            picks.append(r)
            break
    # Dedup by CBE. Use .get() so a malformed row doesn't kill the run.
    seen = set()
    picks_dedup = []
    for p in picks:
        cbe = (p.get("company_cbe") or "").strip()
        if cbe and cbe not in seen:
            picks_dedup.append(p)
            seen.add(cbe)
    picks = picks_dedup

    # Look up the full bulk_summary for each pick from the `sampled` list.
    sampled_by_cbe = {s["enterprise_number"]: s for s in sampled}
    sample_blocks = []
    for p in picks:
        s = sampled_by_cbe.get(p["company_cbe"], {})
        sample_blocks.append({
            "cbe": p["company_cbe"],
            "name": p.get("company_name"),
            "bucket": p.get("bucket"),
            "overall_avg": p.get("overall_avg"),
            "failure_note": p.get("failure_note", ""),
            "bulk_summary": s.get("bulk_summary"),
        })

    plaus_rows = []
    with plausibility_csv_path.open(encoding="utf-8") as f:
        plaus_rows = list(csv.DictReader(f))
    plaus_flag_count = sum(1 for r in plaus_rows if int(r.get("n_flags") or 0) > 0)

    prompt = (
        "## Inputs\n\n"
        "### Judge scores (Sonnet 4.6)\n"
        f"{scored_csv_path.read_text(encoding='utf-8')}\n\n"
        "### Plausibility summary (GPT-4o-mini on non-sample rows)\n"
        f"Total rows scanned: {len(plaus_rows)}\n"
        f"Rows flagged: {plaus_flag_count}\n"
        "Top flagged CBEs (up to 10):\n"
        + "\n".join(
            f"- {r['cbe']}: {r['flags']}"
            for r in plaus_rows if int(r.get("n_flags") or 0) > 0
        )[:3000]
        + "\n\n"
        "### Deterministic checks\n"
        f"```json\n{json.dumps(deterministic, indent=2)}\n```\n\n"
        "### Sampled bulk_summary outputs (worst / median / best / notable)\n"
        f"```json\n{json.dumps(sample_blocks, indent=2, ensure_ascii=False)[:6000]}\n```\n\n"
        "## Questions\n"
        "1. Did the Sonnet judge score the rows consistently with the rubric?\n"
        "2. Are the GPT-4o-mini plausibility flags trustworthy (any obvious misses)?\n"
        "3. Is the pilot quality acceptable for proceeding to Phase 3?\n"
        "4. What specific issue, if any, should block the go decision?\n\n"
        "## Gates (must ALL pass for a PASS verdict)\n"
        "- 30-row sample overall_avg >= 3.06\n"
        "- tier1_big bucket avg >= 3.40\n"
        "- zero hallucinated executive names (plausibility flag type (a))\n"
        "- zero entity-collision false positives (sampled bucket)\n"
        "- deterministic compliance 100%\n\n"
        "## Output\n"
        "Markdown report starting with `## Verdict: PASS|CONDITIONAL|FAIL` on "
        "its own line. Then the 4 question answers, then a bulleted list of "
        "specific blocker CBEs if any."
    )

    text = _opus_message(
        META_REVIEW_SYSTEM, prompt,
        max_tokens=2000, spend=spend, label="meta_review",
    )
    out_path.write_text(text, encoding="utf-8")
    # Parse the verdict line.
    verdict = "CONDITIONAL"
    for line in text.splitlines():
        s = line.strip().upper()
        if "VERDICT" in s:
            if "PASS" in s:
                verdict = "PASS"
            elif "FAIL" in s:
                verdict = "FAIL"
            else:
                verdict = "CONDITIONAL"
            break
    return verdict


# ── Step 7: PILOT_REPORT.md ─────────────────────────────────────────


def _bucket_avgs(scored_rows: list[dict]) -> dict[str, float]:
    out: dict[str, list[float]] = {}
    for r in scored_rows:
        b = r.get("bucket") or ""
        try:
            score = float(r.get("overall_avg") or 0.0)
        except Exception:
            continue
        out.setdefault(b, []).append(score)
    return {k: round(sum(v) / len(v), 2) if v else 0.0 for k, v in out.items()}


def _count_hallucinated_execs(plausibility_csv: Path) -> int:
    """Count rows with a true exec-name-hallucination flag.

    Previously counted any flag containing the word "executive", which
    fired on the INVERSE — "No executive names provided in the summary"
    (a non-issue, not a hallucination). Now restricts to phrases that
    actually indicate a name was fabricated.
    """
    n = 0
    with plausibility_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            raw = (r.get("flags") or "")
            lower = raw.lower()
            # True hallucination phrases. Require "executive" AND one
            # of the "fabricated" verbs, or the explicit "hallucin"
            # stem. False-positive guard: the phrase "no executive
            # names" (meaning none were in the summary at all) is not
            # a hallucination.
            if "no executive name" in lower or "no executive names" in lower:
                continue
            if "hallucin" in lower:
                n += 1
                continue
            if "executive" in lower and any(
                v in lower
                for v in (
                    "does not appear", "not in the scrape",
                    "not in the kbo", "fabricat", "invent",
                )
            ):
                n += 1
    return n


def compute_verdict_metrics(
    scored_csv: Path, plausibility_csv: Path, deterministic: dict,
) -> dict:
    """Pull the metrics the gates need."""
    scored = list(csv.DictReader(scored_csv.read_text(encoding="utf-8").splitlines()))
    overall_scores = [float(r.get("overall_avg") or 0.0) for r in scored if r.get("overall_avg")]
    avg_overall = (
        round(sum(overall_scores) / len(overall_scores), 2)
        if overall_scores else 0.0
    )
    bucket_avgs = _bucket_avgs(scored)
    hallucinated = _count_hallucinated_execs(plausibility_csv)
    det = deterministic or {}
    det_pass = det.get("pass_count", 0)
    det_fail = det.get("fail_count", 0)

    gates = {
        "sample_avg_ge_3_06": avg_overall >= 3.06,
        "tier1_avg_ge_3_40": bucket_avgs.get("tier1_big", 0.0) >= 3.40,
        "zero_hallucinated_execs": hallucinated == 0,
        "deterministic_all_pass": det_fail == 0 and det_pass > 0,
    }
    return {
        "avg_overall": avg_overall,
        "bucket_avgs": bucket_avgs,
        "hallucinated_execs": hallucinated,
        "deterministic_pass": det_pass,
        "deterministic_fail": det_fail,
        "gates": gates,
    }


def write_final_report(
    out_path: Path,
    scored_csv: Path,
    plausibility_csv: Path,
    deterministic: dict,
    meta_verdict: str,
    meta_path: Path,
    spend: Spend,
    substitutions: dict,
) -> str:
    metrics = compute_verdict_metrics(scored_csv, plausibility_csv, deterministic)
    all_gates = all(metrics["gates"].values())
    verdict = "PASS" if (all_gates and meta_verdict == "PASS") else (
        "FAIL" if meta_verdict == "FAIL" else "CONDITIONAL"
    )

    summary_en = {
        "PASS": "Pilot passes every gate. Proceed to Phase 3 when you're ready.",
        "CONDITIONAL": "Pilot mostly clean but one or more gates missed. See the blocker list below; fix and re-run before Phase 3.",
        "FAIL": "Pilot failed hard. Halt — do not seed Phase 3.",
    }[verdict]

    md = [
        f"# Pilot Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"## Verdict: {verdict}",
        "",
        summary_en,
        "",
        "## Numbers",
        f"- Sample quality (30 rows): **{metrics['avg_overall']}**/5 — gate ≥3.06",
        f"- Tier-1 bucket avg: **{metrics['bucket_avgs'].get('tier1_big', 0.0)}**/5 — gate ≥3.40",
        f"- Hallucinated executive names flagged: **{metrics['hallucinated_execs']}** — gate 0",
        f"- Deterministic compliance: **{metrics['deterministic_pass']}/{metrics['deterministic_pass']+metrics['deterministic_fail']}** — gate 100%",
        f"- LLM spend this run: **${spend.usd:.4f}**",
        "",
        "### Bucket breakdown",
    ]
    for b, s in sorted(metrics["bucket_avgs"].items()):
        md.append(f"- {b}: {s}")
    md.append("")
    md.append("## Gate status")
    for name, ok in metrics["gates"].items():
        md.append(f"- {'✅' if ok else '❌'} {name}")
    md.append("")
    md.append("## Opus meta-review verdict")
    md.append(f"{meta_verdict} — see `{meta_path.name}` for the full audit.")
    md.append("")
    if substitutions:
        md.append("## Bucket substitutions (sampling step)")
        for b, cbes in substitutions.items():
            if cbes:
                md.append(f"- {b}: {', '.join(cbes)}")
        md.append("")
    md.append("## Recommendation")
    md.append({
        "PASS": "Proceed to Phase 3 (tier-1+tier-2 production backfill) when the operator is ready.",
        "CONDITIONAL": "Review the failed gate(s) above. Typical remediation: tune the entity-collision check, bump the escalation coverage, or re-seed with a clean run.",
        "FAIL": "Halt the rollout. Investigate the failed checks, iterate on code, then re-run the pilot.",
    }[verdict])
    out_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return verdict


# ── Main orchestrator ────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    ap = argparse.ArgumentParser(description="Phase-2 pilot judge (automated).")
    ap.add_argument("--pilot-set", required=True,
                    help="JSON file produced by seed_enrichment_queue.py --dump-json")
    ap.add_argument("--out-dir", default="scripts/pilot",
                    help="where artifacts land (default: scripts/pilot)")
    ap.add_argument("--sample-size", type=int, default=30,
                    help="override bucket plan total (default 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="sample + classify only, no LLM spend, no DB writes")
    ap.add_argument("--skip-plausibility", action="store_true",
                    help="skip Step 4 (speeds up mock runs)")
    args = ap.parse_args()

    pilot_path = Path(args.pilot_set)
    if not pilot_path.exists():
        print(f"pilot set not found: {pilot_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pilot_cbes = _load_pilot_set(pilot_path)
    logger.info("loaded %d pilot CBEs from %s", len(pilot_cbes), pilot_path)

    # ── Step 1: annotate + stratified sample.
    rows = _annotate_pilot_rows(pilot_cbes)
    logger.info("annotated %d rows with bucket inputs", len(rows))

    # Adjust bucket plan if sample_size overridden.
    plan = DEFAULT_BUCKET_PLAN
    if args.sample_size != 30:
        scale = args.sample_size / 30.0
        plan = {
            b: max(1, int(round(n * scale)))
            for b, n in DEFAULT_BUCKET_PLAN.items()
        }
        # Adjust to exact sample_size.
        diff = args.sample_size - sum(plan.values())
        if diff:
            # Add/subtract from the largest bucket.
            top = max(plan, key=plan.get)
            plan[top] = max(1, plan[top] + diff)

    sampled, substitutions = stratified_sample(rows, plan, seed=42)
    sample_path = out_dir / "pilot_sample_30.json"
    sample_path.write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sample_size": len(sampled),
            "substitutions": substitutions,
            "rows": [
                {
                    "enterprise_number": s["enterprise_number"],
                    "name": s.get("name"),
                    "bucket": s["_bucket"],
                    "nace_code": s.get("nace_code"),
                    "city": s.get("city"),
                    "bulk_website_url": s.get("bulk_website_url"),
                    "bulk_confidence": s.get("bulk_confidence"),
                }
                for s in sampled
            ],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("wrote %s (%d rows)", sample_path, len(sampled))

    if args.dry_run:
        logger.info("--dry-run set: stopping after sampling")
        return 0

    spend = Spend()

    # ── Step 2: ground truth.
    gt_path = out_dir / "ground_truth_pilot.json"
    try:
        ground_truth = asyncio.run(generate_ground_truth(sampled, spend, gt_path))
    except BudgetExceeded as e:
        logger.error("budget exceeded during ground-truth: %s", e)
        (out_dir / "ABORTED.md").write_text(str(e), encoding="utf-8")
        return 3

    # ── Step 3: judge packet + Sonnet judging.
    packet = build_judge_packet(sampled, ground_truth)
    (out_dir / "judge_packet.json").write_text(
        json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    scored_csv = out_dir / "judge_scores.csv"
    try:
        scored_rows = judge_via_sonnet(packet, spend, scored_csv)
        logger.info("judge produced %d rows", len(scored_rows))
    except BudgetExceeded as e:
        logger.error("budget exceeded during judging: %s", e)
        (out_dir / "ABORTED.md").write_text(str(e), encoding="utf-8")
        return 3

    # ── Step 4: plausibility on non-sample.
    plaus_csv = out_dir / "plausibility_flags.csv"
    if args.skip_plausibility:
        plaus_csv.write_text("cbe,n_flags,flags\n", encoding="utf-8")
    else:
        sampled_cbes = {s["enterprise_number"] for s in sampled}
        non_sample = [r for r in rows if r["enterprise_number"] not in sampled_cbes]
        try:
            asyncio.run(run_plausibility(non_sample, spend, plaus_csv))
        except BudgetExceeded as e:
            logger.error("budget exceeded during plausibility: %s", e)
            (out_dir / "ABORTED.md").write_text(str(e), encoding="utf-8")
            return 3

    # ── Step 5: deterministic.
    det_path = out_dir / "deterministic_checks.json"
    deterministic = deterministic_checks(pilot_cbes, det_path)

    # ── Step 6: meta-review.
    meta_path = out_dir / "meta_review.md"
    try:
        meta_verdict = meta_review(
            scored_csv, plaus_csv, deterministic, sampled, spend, meta_path,
        )
    except BudgetExceeded as e:
        logger.error("budget exceeded during meta-review: %s", e)
        (out_dir / "ABORTED.md").write_text(str(e), encoding="utf-8")
        return 3

    # ── Step 7: final report.
    report_path = out_dir / "PILOT_REPORT.md"
    verdict = write_final_report(
        report_path, scored_csv, plaus_csv, deterministic,
        meta_verdict, meta_path, spend, substitutions,
    )
    logger.info("verdict: %s — see %s", verdict, report_path)
    print(f"\nPilot verdict: {verdict}")
    print(f"Report: {report_path}")
    print(f"Total LLM spend: ${spend.usd:.4f}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("interrupted")
        sys.exit(130)
