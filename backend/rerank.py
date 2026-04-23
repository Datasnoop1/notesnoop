"""LLM re-ranking for the /similar/ai endpoint.

Pure functions + one async entry point. No FastAPI, no DB — callers pass
candidate dicts (as produced by backend.retrieval.blend_candidates) plus a
target dict and get back either a list of re-ranked entries or an error
indicator describing which fallback branch the caller should take.

The prompt template is a verbatim transcription of §4.2 of the spec. It
lives in this module because the spec pins ``PROMPT_VERSION`` to the
module that owns the endpoint; this module is re-exported from
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


# Per-candidate insight caps (characters, not tokens — close enough for a
# 4-char/token rule of thumb at the scale we care about).
MAX_CANDIDATE_INSIGHT_CHARS = 500
MAX_TARGET_INSIGHT_CHARS = 800
MAX_FIELD_CHARS = 120
INSIGHT_FIELDS_IN_ORDER = ("business_description", "products", "customers", "market_position")

# Minimum number of surviving candidates required to justify calling the LLM.
MIN_CANDIDATES_FOR_LLM = 5

# LLM-output schema bounds (§4.3).
MIN_REASON_CHARS = 20
MAX_REASON_CHARS = 300
MIN_SECTION_CHARS = 8
MAX_SECTION_CHARS = 140
MAX_LLM_ITEMS = 30
GENERIC_ACTIVITY_PATTERNS = (
    "same sector",
    "same industry",
    "similar activity",
    "related activity",
    "same nace",
    "same 3-digit",
    "same 2-digit",
    "business-profile match",
    "comparable business",
)


PROMPT_TEMPLATE = """You are a Belgian company analyst ranking candidates for private equity deal sourcing. Rank by how similar each candidate's CORE BUSINESS is to the TARGET.

Ranking criteria in order:
1. ACTIVITY MATCH — identical products/services/customer segments (highest weight).
2. BUSINESS MODEL MATCH — distributor vs manufacturer vs service provider, B2B vs B2C.
3. SIZE PROXIMITY — similar revenue and headcount, tiebreaker only.

Do NOT penalise candidates for being larger or smaller. Do NOT rank by geography unless activity is identical.
EXCLUDE companies that appear to be in the same corporate group as the target, including parent companies, subsidiaries, and sister companies under the same holding.

The `reason` field MUST be specific and structured in exactly this format: "Activity: <specific business overlap> | Size: <brief size comparison> | Geography: <brief geography note>".
Use the labels exactly as written and keep the pipe separators.
The Activity part must name the product category, customer segment, or business model. REJECT generic reasons like "same sector" or "similar activity". Example of a good reason: "Activity: Wholesale of industrial abrasives to automotive OEMs | Size: Similar \u20ac10-20M distributor scale | Geography: Different region, secondary factor." Example of a bad reason: "Operates in the same industry."

If a candidate is clearly unrelated, exclude it from the output rather than forcing a rank.

TARGET (CBE {target_cbe}):
Name: {target_name}
Location: {target_city}
Financials: Revenue \u20ac{target_revenue}, EBITDA \u20ac{target_ebitda}, FTE {target_fte}
NACE: {target_nace_code} \u2014 {target_nace_desc}
Profile: {target_insight_block}

CANDIDATES:
{candidate_blocks}

Each candidate block format:
[{{index}}] {{name}} ({{city}}) \u2014 Rev \u20ac{{revenue}}, EBITDA \u20ac{{ebitda}}, FTE {{fte}} \u2014 NACE {{nace}} \u2014 Profile: {{insight_block}}

Return ONLY a JSON array. No prose, no markdown fences. Schema:
[
  {{"index": <int matching input index>, "rank": <int 1..N>, "reason": "Activity: ... | Size: ... | Geography: ..."}}
]
Return between 5 and {limit} items. Omit candidates that are not meaningfully similar."""


SHORTLIST_PROMPT_TEMPLATE = """You are a Belgian company analyst selecting the best comparable companies for private equity deal sourcing. Rank candidates by how similar each candidate's CORE BUSINESS is to the TARGET.

Ranking criteria in order:
1. ACTIVITY MATCH â€” identical products/services/customer segments (highest weight).
2. BUSINESS MODEL MATCH â€” distributor vs manufacturer vs service provider, B2B vs B2C.
3. SIZE PROXIMITY â€” similar revenue and headcount, tiebreaker only.

Do NOT penalise candidates for being larger or smaller. Do NOT rank by geography unless activity is identical.
EXCLUDE companies that appear to be in the same corporate group as the target, including parent companies, subsidiaries, and sister companies under the same holding.

If a candidate is clearly unrelated, exclude it from the output rather than forcing a rank.

TARGET (CBE {target_cbe}):
Name: {target_name}
Location: {target_city}
Financials: Revenue \u20ac{target_revenue}, EBITDA \u20ac{target_ebitda}, FTE {target_fte}
NACE: {target_nace_code} \u2014 {target_nace_desc}
Profile: {target_insight_block}

CANDIDATES:
{candidate_blocks}

Each candidate block format:
[{{index}}] {{name}} ({{city}}) \u2014 Rev \u20ac{{revenue}}, EBITDA \u20ac{{ebitda}}, FTE {{fte}} \u2014 NACE {{nace}} \u2014 Profile: {{insight_block}}

Return ONLY a JSON array. No prose, no markdown fences. Schema:
[
  {{"index": <int matching input index>, "rank": <int 1..N>}}
]
Return between 5 and {limit} items. Omit candidates that are not meaningfully similar."""


FINAL_PROMPT_TEMPLATE = """You are a Belgian company analyst writing the final comparable-company ranking for private equity deal sourcing. Rank by how similar each candidate's CORE BUSINESS is to the TARGET.

Ranking criteria in order:
1. ACTIVITY MATCH â€” identical products/services/customer segments (highest weight).
2. BUSINESS MODEL MATCH â€” distributor vs manufacturer vs service provider, B2B vs B2C.
3. SIZE PROXIMITY â€” similar revenue and headcount, tiebreaker only.

Do NOT penalise candidates for being larger or smaller. Do NOT rank by geography unless activity is identical.
EXCLUDE companies that appear to be in the same corporate group as the target, including parent companies, subsidiaries, and sister companies under the same holding.
Use the retrieval signals as evidence, but trust the business profile first. If the signals and profile conflict, prefer the profile.
Treat NACE as a weak fallback only. An exact NACE match without clear business overlap should be excluded.

The output MUST be structured.
- `activity` must name the concrete business overlap: product category, customer segment, or business model.
- `size` must briefly explain the scale relationship using the financials and headcount.
- `geography` must briefly note location, but only as a secondary factor.
- REJECT generic activity text like "same sector", "similar activity", "same industry", or "related business".

If a candidate is clearly unrelated, exclude it from the output rather than forcing a rank.

TARGET (CBE {target_cbe}):
Name: {target_name}
Location: {target_city}
Financials: Revenue \u20ac{target_revenue}, EBITDA \u20ac{target_ebitda}, FTE {target_fte}
NACE: {target_nace_code} \u2014 {target_nace_desc}
Profile: {target_insight_block}

CANDIDATES:
{candidate_blocks}

Each candidate block format:
[{{index}}] {{name}} ({{city}}) \u2014 Rev \u20ac{{revenue}}, EBITDA \u20ac{{ebitda}}, FTE {{fte}} \u2014 NACE {{nace}} \u2014 Profile: {{insight_block}} \u2014 Signals: {{signals}}

Return ONLY a JSON array. No prose, no markdown fences. Schema:
[
  {{
    "index": <int matching input index>,
    "rank": <int 1..N>,
    "activity": "<specific business overlap>",
    "size": "<brief size comparison>",
    "geography": "<brief geography note>"
  }}
]
Return between 5 and {limit} items. Omit candidates that are not meaningfully similar."""


PROMPT_TEMPLATE = FINAL_PROMPT_TEMPLATE
SHORTLIST_PROMPT_TEMPLATE = SHORTLIST_PROMPT_TEMPLATE.replace("Ã¢â‚¬â€", "-")
FINAL_PROMPT_TEMPLATE = FINAL_PROMPT_TEMPLATE.replace("Ã¢â‚¬â€", "-")
PROMPT_TEMPLATE = FINAL_PROMPT_TEMPLATE


# ──────────────────────────────────────────────────────────────────────────
# Insight block assembly
# ──────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────
# Numeric formatting (§4.2)
# ──────────────────────────────────────────────────────────────────────────

def _format_money(value: Any) -> str:
    """€X.XM ≥ 1M, €XXXk otherwise, 'n/a' for None/invalid."""
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


# ──────────────────────────────────────────────────────────────────────────
# Prompt rendering
# ──────────────────────────────────────────────────────────────────────────

def _format_signal_block(candidate: dict) -> str:
    parts: list[str] = []
    activity_anchor = (candidate.get("activity_anchor") or "").strip()
    if activity_anchor:
        parts.append(f"anchor {activity_anchor}")
    activity_overlap = candidate.get("activity_overlap_score")
    if isinstance(activity_overlap, (int, float)):
        parts.append(f"activity overlap {float(activity_overlap):.2f}")
    nace_match = (candidate.get("nace_match_label") or "").strip()
    if nace_match and nace_match != "none":
        parts.append(f"NACE {nace_match}")
    revenue_ratio = candidate.get("revenue_ratio")
    if isinstance(revenue_ratio, (int, float)) and revenue_ratio > 0:
        parts.append(f"revenue {float(revenue_ratio):.2f}x target")
    geo_label = (candidate.get("geo_label") or "").strip()
    if geo_label:
        parts.append(f"geography {geo_label}")
    return "; ".join(parts) if parts else "no extra retrieval signals"


def build_candidate_lines(candidates: list[dict], include_signals: bool = False) -> str:
    """Render the candidate_blocks string expected by the prompt template.

    ``candidates`` is the output of blend_candidates — each item has a
    ``row`` dict with the hydrated financial fields and NACE metadata.
    """
    lines: list[str] = []
    for i, c in enumerate(candidates, start=1):
        row = c.get("row", {})
        insight = build_business_profile_block(
            row.get("bulk_summary"),
            row.get("ai_insights"),
            row.get("nace_desc"),
        )
        line = (
            f"[{i}] {row.get('name', '?')} ({row.get('city', '?')}) "
            f"\u2014 Rev \u20ac{_format_money(row.get('revenue'))}, "
            f"EBITDA \u20ac{_format_money(row.get('ebitda'))}, "
            f"FTE {_format_fte(row.get('fte_total'))} "
            f"\u2014 NACE {row.get('nace_code') or 'n/a'} "
            f"\u2014 Profile: {insight}"
        )
        if include_signals:
            line += f" \u2014 Signals: {_format_signal_block(c)}"
        lines.append(line)
    return "\n".join(lines)


def render_prompt(target: dict, candidates: list[dict], limit: int) -> str:
    """Substitute all placeholders. No Python .format() — the template
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
        .replace("{target_insight_block}", build_target_business_profile_block(
            target.get("bulk_summary"),
            target.get("ai_insights"),
            target.get("nace_desc"),
        ))
        .replace("{candidate_blocks}", build_candidate_lines(candidates))
        .replace("{limit}", str(limit))
    )
    # The template uses {{index}} etc. as escaped literal braces that the
    # spec wants to appear in the rendered prompt as `{index}` so the LLM
    # sees the literal format description. Collapse the doubled braces now.
    rendered = rendered.replace("{{", "{").replace("}}", "}")
    return rendered


def _render_prompt(
    template: str,
    target: dict,
    candidates: list[dict],
    limit: int,
    *,
    include_signals: bool = False,
) -> str:
    rendered = (
        template
        .replace("{target_cbe}", str(target.get("enterprise_number") or ""))
        .replace("{target_name}", str(target.get("name") or ""))
        .replace("{target_city}", str(target.get("city") or ""))
        .replace("{target_revenue}", _format_money(target.get("revenue")))
        .replace("{target_ebitda}", _format_money(target.get("ebitda")))
        .replace("{target_fte}", _format_fte(target.get("fte_total")))
        .replace("{target_nace_code}", str(target.get("nace_code") or "n/a"))
        .replace("{target_nace_desc}", str(target.get("nace_desc") or "n/a"))
        .replace("{target_insight_block}", build_target_business_profile_block(
            target.get("bulk_summary"),
            target.get("ai_insights"),
            target.get("nace_desc"),
        ))
        .replace("{candidate_blocks}", build_candidate_lines(candidates, include_signals=include_signals))
        .replace("{limit}", str(limit))
    )
    return rendered.replace("{{", "{").replace("}}", "}")


def render_shortlist_prompt(target: dict, candidates: list[dict], limit: int) -> str:
    return _render_prompt(
        SHORTLIST_PROMPT_TEMPLATE,
        target,
        candidates,
        limit,
        include_signals=False,
    )


def render_final_prompt(target: dict, candidates: list[dict], limit: int) -> str:
    return _render_prompt(
        FINAL_PROMPT_TEMPLATE,
        target,
        candidates,
        limit,
        include_signals=True,
    )


def render_prompt(target: dict, candidates: list[dict], limit: int) -> str:
    """Backwards-compatible alias for the final-pass prompt."""
    return render_final_prompt(target, candidates, limit)


# ──────────────────────────────────────────────────────────────────────────
# JSON parsing + validation (§4.3)
# ──────────────────────────────────────────────────────────────────────────

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = _JSON_FENCE_RE.sub("", cleaned).strip()
    return cleaned


def validate_llm_output(raw_text: str, n_candidates: int) -> tuple[list[dict] | None, str | None]:
    """Parse and validate the LLM response. Returns (items, error) with exactly
    one of them non-None.

    ``items`` is a list of {"index": int, "rank": int, "reason": str} with all
    indices known to be in 1..n_candidates. Invalid indices are dropped
    silently (not an error) per §7.5. A parse / structural failure sets
    ``error`` to one of: 'parse', 'not_array', 'bad_item', 'too_few_valid'.
    """
    if not raw_text or not raw_text.strip():
        return None, "parse"

    cleaned = _strip_fences(raw_text)
    # Some models prefix prose before the array; grab the first [...] blob.
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
            # Out-of-range indices are dropped, not a hard error.
            continue
        if rank < 1 or rank > MAX_LLM_ITEMS:
            continue
        reason_stripped = reason.strip()
        if len(reason_stripped) < MIN_REASON_CHARS:
            # Too short is dropped rather than failing the whole response —
            # models occasionally return one weak line among good ones.
            continue
        if len(reason_stripped) > MAX_REASON_CHARS:
            reason_stripped = reason_stripped[:MAX_REASON_CHARS - 1].rstrip() + "\u2026"
        valid.append({"index": idx, "rank": rank, "reason": reason_stripped})

    if not valid:
        return None, "bad_item"
    if len(valid) < 3:
        return None, "too_few_valid"

    # Deduplicate on index (keep the highest rank — i.e. the smallest rank number).
    seen_idx: set[int] = set()
    deduped: list[dict] = []
    valid.sort(key=lambda v: v["rank"])
    for entry in valid:
        if entry["index"] in seen_idx:
            continue
        seen_idx.add(entry["index"])
        deduped.append(entry)

    # Renumber ranks 1..N densely so downstream consumers don't see gaps.
    for pos, entry in enumerate(deduped, start=1):
        entry["rank"] = pos

    return deduped, None


def _parse_output_array(raw_text: str) -> tuple[list | None, str | None]:
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
    return data, None


def _normalize_section_text(value: Any, *, max_chars: int = MAX_SECTION_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()).strip(" |.;:-")
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "\u2026"
    return text


def _is_generic_activity_reason(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    if any(pattern in lowered for pattern in GENERIC_ACTIVITY_PATTERNS):
        return True
    words = re.findall(r"[a-z0-9][a-z0-9&/+.-]*", lowered)
    return len(words) < 3


def _dedupe_ranked_items(items: list[dict]) -> list[dict]:
    seen_idx: set[int] = set()
    deduped: list[dict] = []
    items.sort(key=lambda v: v["rank"])
    for entry in items:
        if entry["index"] in seen_idx:
            continue
        seen_idx.add(entry["index"])
        deduped.append(entry)
    for pos, entry in enumerate(deduped, start=1):
        entry["rank"] = pos
    return deduped


def validate_rank_only_output(raw_text: str, n_candidates: int) -> tuple[list[dict] | None, str | None]:
    data, parse_err = _parse_output_array(raw_text)
    if data is None:
        return None, parse_err

    valid: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        rank = entry.get("rank")
        if not isinstance(idx, int) or not isinstance(rank, int):
            continue
        if idx < 1 or idx > n_candidates:
            continue
        if rank < 1 or rank > MAX_LLM_ITEMS:
            continue
        valid.append({"index": idx, "rank": rank})

    if not valid:
        return None, "bad_item"
    if len(valid) < 3:
        return None, "too_few_valid"
    return _dedupe_ranked_items(valid), None


def validate_structured_reason_output(
    raw_text: str,
    n_candidates: int,
) -> tuple[list[dict] | None, str | None]:
    data, parse_err = _parse_output_array(raw_text)
    if data is None:
        return None, parse_err

    valid: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        rank = entry.get("rank")
        if not isinstance(idx, int) or not isinstance(rank, int):
            continue
        if idx < 1 or idx > n_candidates:
            continue
        if rank < 1 or rank > MAX_LLM_ITEMS:
            continue

        activity = _normalize_section_text(entry.get("activity"))
        size = _normalize_section_text(entry.get("size"))
        geography = _normalize_section_text(entry.get("geography"))
        if len(activity) < MIN_SECTION_CHARS or len(size) < MIN_SECTION_CHARS:
            continue
        if len(geography) < MIN_SECTION_CHARS:
            continue
        if _is_generic_activity_reason(activity):
            continue

        reason = f"Activity: {activity} | Size: {size} | Geography: {geography}"
        if len(reason) < MIN_REASON_CHARS:
            continue
        if len(reason) > MAX_REASON_CHARS:
            reason = reason[: MAX_REASON_CHARS - 1].rstrip() + "\u2026"
        valid.append({
            "index": idx,
            "rank": rank,
            "reason": reason,
            "reason_sections": {
                "activity": activity,
                "size": size,
                "geography": geography,
            },
        })

    if not valid:
        return None, "bad_item"
    if len(valid) < 3:
        return None, "too_few_valid"
    return _dedupe_ranked_items(valid), None


# ──────────────────────────────────────────────────────────────────────────
# LLM call with fallback chain
# ──────────────────────────────────────────────────────────────────────────

_JSON_RETRY_HINT = (
    "\n\nYour previous response was not valid JSON matching the schema. "
    "Return only the JSON array."
)


async def call_rerank_llm(
    prompt: str,
    tier: str,
    n_candidates: int,
    schema: str = "reason_text",
) -> dict:
    """Walk the fallback chain. Returns a dict:

        items:       parsed list (or None if everything failed)
        model_used:  the model that produced the returned items (or None)
        attempted:   list of model ids we tried, in order
        latencies:   {model_id: latency_ms} for each attempt
        usage:       {model_id: {input_tokens, output_tokens}} for each attempt
        error:       short reason if items is None
        errors:      list of per-attempt error strings (same length as attempted)

    The function never raises; the caller uses ``items`` and ``error`` to
    decide whether to degrade the response.
    """
    cfg = get_tier_config(tier)
    primary = cfg["model"]
    max_tokens = cfg.get("max_tokens", 1200)
    temperature = cfg.get("temperature", 0.2)
    timeout_s = float(SIMILAR_COMPANIES_ROUTING.get("REQUEST_TIMEOUT_S", 12))
    max_retries = int(SIMILAR_COMPANIES_ROUTING.get("MAX_RETRIES_PER_MODEL", 1))

    chain = get_fallback_chain(primary, tier=tier)
    attempted: list[str] = []
    errors: list[str] = []
    latencies: dict[str, int] = {}
    usage: dict[str, dict] = {}

    for model in chain:
        for attempt in range(max_retries + 1):
            # Retry prompt: append the JSON hint on the second shot only.
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
                # 5xx / timeout / empty → try the retry slot on the same model,
                # then move to the next model in the chain.
                continue

            if schema == "rank_only":
                items, parse_err = validate_rank_only_output(meta["text"], n_candidates)
            elif schema == "structured_reason":
                items, parse_err = validate_structured_reason_output(meta["text"], n_candidates)
            else:
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
            # Parse failure counts as an attempt; the retry slot appends the
            # JSON hint. If that still fails, the outer loop moves on.
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
