"""LLM re-ranking for the /similar/ai endpoint.

Pure functions plus one async entry point. No FastAPI, no DB: callers pass
candidate dicts (as produced by backend.retrieval.blend_candidates) plus a
target dict and get back either a list of re-ranked entries or an error
indicator describing which fallback branch the caller should take.

The prompt template is a verbatim transcription of section 4.2 of the spec.
It lives in this module because the spec pins ``PROMPT_VERSION`` to the module
that owns the endpoint; this module is re-exported from
backend/routers/companies/similar.py via ``from backend.rerank import
PROMPT_TEMPLATE``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai_client import ai_complete_with_meta
from ai_routing import SIMILAR_COMPANIES_ROUTING, get_fallback_chain, get_tier_config
from similarity_profile import (
    build_similarity_profile,
    build_similarity_profile_block,
    has_similarity_profile,
)

logger = logging.getLogger(__name__)


# Per-candidate insight caps (characters, not tokens - close enough for a
# 4-char/token rule of thumb at the scale we care about).
MAX_CANDIDATE_INSIGHT_CHARS = 500
MAX_TARGET_INSIGHT_CHARS = 800
MAX_FIELD_CHARS = 120
INSIGHT_FIELDS_IN_ORDER = ("business_description", "products", "customers", "market_position")

# Minimum number of surviving candidates required to justify calling the LLM.
MIN_CANDIDATES_FOR_LLM = 5

# LLM-output schema bounds (section 4.3).
MIN_REASON_CHARS = 20
MAX_REASON_CHARS = 300
MAX_LLM_ITEMS = 30


PROMPT_TEMPLATE = """You are a Belgian company analyst ranking candidates for private equity deal sourcing. Rank by how similar each candidate's CORE BUSINESS is to the TARGET.

Ranking criteria in order:
1. ACTIVITY MATCH - identical products/services/customer segments (highest weight).
2. BUSINESS MODEL MATCH - distributor vs manufacturer vs service provider, B2B vs B2C.
3. SIZE PROXIMITY - similar revenue and headcount, tiebreaker only.

Do NOT penalise candidates for being larger or smaller. Do NOT rank by geography unless activity is identical.
EXCLUDE companies that appear to be in the same corporate group as the target, including parent companies, subsidiaries, and sister companies under the same holding.

The `reason` field MUST be specific and structured in exactly this format: "Activity: <specific business overlap> | Size: <brief size comparison> | Geography: <brief geography note>".
Use the labels exactly as written and keep the pipe separators.
The Activity part must name the product category, customer segment, or business model. REJECT generic reasons like "same sector" or "similar activity". Example of a good reason: "Activity: Wholesale of industrial abrasives to automotive OEMs | Size: Similar EUR10-20M distributor scale | Geography: Different region, secondary factor." Example of a bad reason: "Operates in the same industry."

If a candidate is clearly unrelated, exclude it from the output rather than forcing a rank.

TARGET (CBE {target_cbe}):
Name: {target_name}
Location: {target_city}
Financials: Revenue EUR{target_revenue}, EBITDA EUR{target_ebitda}, FTE {target_fte}
NACE: {target_nace_code} - {target_nace_desc}
Profile: {target_insight_block}

CANDIDATES:
{candidate_blocks}

Each candidate block format:
[{{index}}] {{name}} ({{city}}) - Rev EUR{{revenue}}, EBITDA EUR{{ebitda}}, FTE {{fte}} - NACE {{nace}} - Profile: {{insight_block}}

Return ONLY a JSON array. No prose, no markdown fences. Schema:
[
  {{"index": <int matching input index>, "rank": <int 1..N>, "reason": "Activity: ... | Size: ... | Geography: ..."}}
]
Return between 5 and {limit} items. Omit candidates that are not meaningfully similar."""


# ---------------------------------------------------------------------------
# Insight block assembly
# ---------------------------------------------------------------------------

def _parse_insights(raw: Any) -> dict:
    """Coerce the ai_insights column (JSON string or already-decoded dict) to a dict."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _field_to_str(val: Any) -> str:
    """Flatten lists to comma-separated strings; coerce everything else to str."""
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(str(v).strip() for v in val if v is not None)
    return str(val).strip()


def build_insight_block(
    ai_insights_json: Any,
    nace_desc: str | None,
    max_chars: int = MAX_CANDIDATE_INSIGHT_CHARS,
) -> str:
    """Backwards-compatible helper for ai_insights-only call sites."""
    profile = build_similarity_profile(None, ai_insights_json)
    return build_similarity_profile_block(
        profile,
        nace_desc,
        max_chars=max_chars,
        max_field_chars=MAX_FIELD_CHARS,
    )


def build_business_profile_block(
    bulk_summary_json: Any,
    ai_insights_json: Any,
    nace_desc: str | None,
    max_chars: int = MAX_CANDIDATE_INSIGHT_CHARS,
) -> str:
    """Build the business profile block used for similarity ranking."""
    profile = build_similarity_profile(bulk_summary_json, ai_insights_json)
    return build_similarity_profile_block(
        profile,
        nace_desc,
        max_chars=max_chars,
        max_field_chars=MAX_FIELD_CHARS,
    )


def build_target_insight_block(
    ai_insights_json: Any,
    nace_desc: str | None,
) -> str:
    """Target-specific insight block: 800-char cap, explicit no-profile message."""
    profile = build_similarity_profile(None, ai_insights_json)
    if not has_similarity_profile(profile):
        nace_clean = (nace_desc or "").strip() or "n/a"
        return f"[no profile available; rely on NACE: {nace_clean}]"
    return build_similarity_profile_block(
        profile,
        nace_desc,
        max_chars=MAX_TARGET_INSIGHT_CHARS,
        max_field_chars=MAX_FIELD_CHARS,
    )


def build_target_business_profile_block(
    bulk_summary_json: Any,
    ai_insights_json: Any,
    nace_desc: str | None,
) -> str:
    """Target profile that prefers factual bulk summaries when available."""
    profile = build_similarity_profile(bulk_summary_json, ai_insights_json)
    if not has_similarity_profile(profile):
        nace_clean = (nace_desc or "").strip() or "n/a"
        return f"[no profile available; rely on NACE: {nace_clean}]"
    return build_similarity_profile_block(
        profile,
        nace_desc,
        max_chars=MAX_TARGET_INSIGHT_CHARS,
        max_field_chars=MAX_FIELD_CHARS,
    )


# ---------------------------------------------------------------------------
# Numeric formatting
# ---------------------------------------------------------------------------

def _format_money(value: Any) -> str:
    """EURX.XM >= 1M, EURXXXk otherwise, 'n/a' for None/invalid."""
    if value is None:
        return "n/a"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if n == 0:
        return "0"
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs_n >= 1_000:
        return f"{int(round(n / 1_000))}k"
    return f"{int(round(n))}"


def _format_fte(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return "n/a"


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def build_candidate_lines(candidates: list[dict]) -> str:
    """Render the candidate_blocks string expected by the prompt template."""
    lines: list[str] = []
    for i, candidate in enumerate(candidates, start=1):
        row = candidate.get("row", {})
        insight = build_business_profile_block(
            row.get("bulk_summary"),
            row.get("ai_insights"),
            row.get("nace_desc"),
        )
        lines.append(
            f"[{i}] {row.get('name', '?')} ({row.get('city', '?')}) "
            f"- Rev EUR{_format_money(row.get('revenue'))}, "
            f"EBITDA EUR{_format_money(row.get('ebitda'))}, "
            f"FTE {_format_fte(row.get('fte_total'))} "
            f"- NACE {row.get('nace_code') or 'n/a'} "
            f"- Profile: {insight}"
        )
    return "\n".join(lines)


def render_prompt(target: dict, candidates: list[dict], limit: int) -> str:
    """Substitute all placeholders. No Python .format() because the template
    contains literal JSON braces which would break str.format."""
    rendered = (
        PROMPT_TEMPLATE
        .replace("{target_cbe}", str(target.get("enterprise_number") or ""))
        .replace("{target_name}", str(target.get("name") or ""))
        .replace("{target_city}", str(target.get("city") or ""))
        .replace("{target_revenue}", _format_money(target.get("revenue")))
        .replace("{target_ebitda}", _format_money(target.get("ebitda")))
        .replace("{target_fte}", _format_fte(target.get("fte_total")))
        .replace("{target_nace_code}", str(target.get("nace_code") or "n/a"))
        .replace("{target_nace_desc}", str(target.get("nace_desc") or "n/a"))
        .replace(
            "{target_insight_block}",
            build_target_business_profile_block(
                target.get("bulk_summary"),
                target.get("ai_insights"),
                target.get("nace_desc"),
            ),
        )
        .replace("{candidate_blocks}", build_candidate_lines(candidates))
        .replace("{limit}", str(limit))
    )
    rendered = rendered.replace("{{", "{").replace("}}", "}")
    return rendered


# ---------------------------------------------------------------------------
# JSON parsing plus validation
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = _JSON_FENCE_RE.sub("", cleaned).strip()
    return cleaned


def validate_llm_output(raw_text: str, n_candidates: int) -> tuple[list[dict] | None, str | None]:
    """Parse and validate the LLM response. Returns (items, error)."""
    if not raw_text or not raw_text.strip():
        return None, "parse"

    cleaned = _strip_fences(raw_text)
    if not cleaned.startswith("["):
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if not match:
            return None, "parse"
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None, "parse"

    if not isinstance(data, list):
        return None, "not_array"
    if len(data) > MAX_LLM_ITEMS:
        data = data[:MAX_LLM_ITEMS]

    valid: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        rank = entry.get("rank")
        reason = entry.get("reason")
        if not isinstance(idx, int) or not isinstance(rank, int):
            continue
        if not isinstance(reason, str):
            continue
        if idx < 1 or idx > n_candidates:
            continue
        if rank < 1 or rank > MAX_LLM_ITEMS:
            continue
        reason_stripped = reason.strip()
        if len(reason_stripped) < MIN_REASON_CHARS:
            continue
        if len(reason_stripped) > MAX_REASON_CHARS:
            reason_stripped = reason_stripped[: MAX_REASON_CHARS - 1].rstrip() + "..."
        valid.append({"index": idx, "rank": rank, "reason": reason_stripped})

    if not valid:
        return None, "bad_item"
    if len(valid) < 3:
        return None, "too_few_valid"

    seen_idx: set[int] = set()
    deduped: list[dict] = []
    valid.sort(key=lambda value: value["rank"])
    for entry in valid:
        if entry["index"] in seen_idx:
            continue
        seen_idx.add(entry["index"])
        deduped.append(entry)

    for pos, entry in enumerate(deduped, start=1):
        entry["rank"] = pos

    return deduped, None


# ---------------------------------------------------------------------------
# LLM call with fallback chain
# ---------------------------------------------------------------------------

_JSON_RETRY_HINT = (
    "\n\nYour previous response was not valid JSON matching the schema. "
    "Return only the JSON array."
)


async def call_rerank_llm(
    prompt: str,
    tier: str,
    n_candidates: int,
) -> dict:
    """Walk the fallback chain and never raise."""
    cfg = get_tier_config(tier)
    primary = cfg["model"]
    max_tokens = cfg.get("max_tokens", 1200)
    temperature = cfg.get("temperature", 0.2)
    timeout_s = float(SIMILAR_COMPANIES_ROUTING.get("REQUEST_TIMEOUT_S", 12))
    max_retries = int(SIMILAR_COMPANIES_ROUTING.get("MAX_RETRIES_PER_MODEL", 1))

    chain = get_fallback_chain(primary)
    attempted: list[str] = []
    errors: list[str] = []
    latencies: dict[str, int] = {}
    usage: dict[str, dict] = {}

    for model in chain:
        for attempt in range(max_retries + 1):
            call_prompt = prompt if attempt == 0 else prompt + _JSON_RETRY_HINT
            meta = await ai_complete_with_meta(
                call_prompt,
                system="",
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=timeout_s,
            )
            attempted.append(model)
            latencies[model] = max(latencies.get(model, 0), meta.get("latency_ms", 0))
            usage[model] = {
                "input_tokens": meta.get("input_tokens", 0),
                "output_tokens": meta.get("output_tokens", 0),
            }
            if not meta.get("ok"):
                errors.append(meta.get("error") or "unknown")
                continue

            items, parse_err = validate_llm_output(meta["text"], n_candidates)
            if items is not None:
                return {
                    "items": items,
                    "model_used": model,
                    "attempted": attempted,
                    "latencies": latencies,
                    "usage": usage,
                    "error": None,
                    "errors": errors,
                }
            errors.append(f"parse:{parse_err}")

    return {
        "items": None,
        "model_used": None,
        "attempted": attempted,
        "latencies": latencies,
        "usage": usage,
        "error": "llm_unavailable",
        "errors": errors,
    }
