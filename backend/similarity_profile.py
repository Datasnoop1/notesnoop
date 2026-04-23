"""Helpers for factual company-similarity profiles.

The similar-company pipeline wants a compact, business-only description of a
company. We prefer the factual bulk_summary shape when it exists, and fall back
to the older ai_insights narrative when needed.
"""

from __future__ import annotations

import json
import re
from typing import Any


_PROFILE_BLOCK_FIELDS = ("business_description", "products", "customers", "market_position")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9&+./-]{2,}")
_WHITESPACE_RE = re.compile(r"\s+")
_GENERIC_PHRASES = {
    "same sector",
    "similar sector",
    "same activity",
    "similar activity",
    "same industry",
    "similar industry",
    "related industry",
    "related activities",
    "business services",
    "industrial services",
}
_STOPWORDS = {
    "about", "across", "among", "and", "avec", "been", "belgian", "between",
    "business", "clients", "company", "companies", "customer", "customers",
    "dans", "de", "des", "distribution", "door", "een", "een", "for", "from",
    "group", "het", "into", "les", "met", "naar", "voor", "with",
}


def parse_json_dict(raw: Any) -> dict:
    """Coerce a JSON string or dict to a dict."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else re.split(r"[;|]", str(value))
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def build_similarity_profile(bulk_summary_raw: Any, ai_insights_raw: Any) -> dict:
    """Return the best available business-only profile for similarity work."""
    bulk = parse_json_dict(bulk_summary_raw)
    bulk_desc = _clean_text(bulk.get("business_description"))
    bulk_products = _clean_list(bulk.get("products_services"))
    bulk_customers = _clean_list(bulk.get("customer_segments"))
    if bulk_desc or bulk_products or bulk_customers:
        return {
            "source": "bulk",
            "business_description": bulk_desc,
            "products": bulk_products,
            "customers": bulk_customers,
            "market_position": "",
        }

    ai = parse_json_dict(ai_insights_raw)
    return {
        "source": "ai_insights" if ai else "none",
        "business_description": _clean_text(ai.get("business_description")),
        "products": _clean_list(ai.get("products")),
        "customers": _clean_list(ai.get("customers")),
        "market_position": _clean_text(ai.get("market_position")),
    }


def has_similarity_profile(profile: dict | None) -> bool:
    profile_map = profile or {}
    return any(
        profile_map.get(field)
        for field in _PROFILE_BLOCK_FIELDS
    )


def build_similarity_profile_block(
    profile: dict | None,
    nace_desc: str | None,
    *,
    max_chars: int,
    max_field_chars: int,
) -> str:
    """Render a compact profile block for the reranker prompt."""
    profile_map = profile or {}
    if not has_similarity_profile(profile_map):
        nace_clean = _clean_text(nace_desc)
        fallback = f"[NACE-only] {nace_clean}" if nace_clean else "[NACE-only] n/a"
        return fallback[:max_chars]

    pieces: list[str] = []
    for field in _PROFILE_BLOCK_FIELDS:
        raw_value = profile_map.get(field)
        if field in ("products", "customers"):
            text = ", ".join(raw_value or [])
        else:
            text = _clean_text(raw_value)
        if not text:
            continue
        if len(text) > max_field_chars:
            text = text[: max_field_chars - 3].rstrip() + "..."
        pieces.append(text)

    if not pieces:
        nace_clean = _clean_text(nace_desc)
        fallback = f"[NACE-only] {nace_clean}" if nace_clean else "[NACE-only] n/a"
        return fallback[:max_chars]

    joined = " | ".join(pieces)
    if len(joined) > max_chars:
        joined = joined[: max_chars - 3].rstrip() + "..."
    return joined


def _normalize_phrase(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _phrase_set(values: list[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        phrase = _normalize_phrase(value)
        if len(phrase) < 4 or phrase in _GENERIC_PHRASES:
            continue
        if len(phrase.split()) > 8:
            continue
        out.add(phrase)
    return out


def _description_token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(_normalize_phrase(text)):
        if len(token) < 4 or token in _STOPWORDS or token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def compute_activity_overlap_score(target_profile: dict | None, candidate_profile: dict | None) -> float:
    """Return a 0..1 score for concrete business overlap."""
    target = target_profile or {}
    candidate = candidate_profile or {}

    product_score = _jaccard(
        _phrase_set(target.get("products") or []),
        _phrase_set(candidate.get("products") or []),
    )
    customer_score = _jaccard(
        _phrase_set(target.get("customers") or []),
        _phrase_set(candidate.get("customers") or []),
    )
    description_score = _jaccard(
        _description_token_set(_clean_text(target.get("business_description"))),
        _description_token_set(_clean_text(candidate.get("business_description"))),
    )

    weighted = 0.0
    weight_sum = 0.0
    if target.get("products") and candidate.get("products"):
        weighted += 0.5 * product_score
        weight_sum += 0.5
    if target.get("customers") and candidate.get("customers"):
        weighted += 0.3 * customer_score
        weight_sum += 0.3
    if target.get("business_description") and candidate.get("business_description"):
        weighted += 0.2 * description_score
        weight_sum += 0.2

    if weight_sum == 0:
        return 0.0
    return round(max(0.0, min(1.0, weighted / weight_sum)), 4)


def describe_activity_overlap(
    target_profile: dict | None,
    candidate_profile: dict | None,
    *,
    candidate_nace_desc: str | None = None,
) -> str | None:
    """Return a concrete activity phrase for structured explanations."""
    target = target_profile or {}
    candidate = candidate_profile or {}

    target_products = _phrase_set(target.get("products") or [])
    candidate_products = _phrase_set(candidate.get("products") or [])
    shared_products = sorted(target_products & candidate_products)
    if shared_products:
        return shared_products[0]

    target_customers = _phrase_set(target.get("customers") or [])
    candidate_customers = _phrase_set(candidate.get("customers") or [])
    shared_customers = sorted(target_customers & candidate_customers)
    if shared_customers:
        return shared_customers[0]

    if candidate_products:
        return sorted(candidate_products)[0]
    if candidate_customers:
        return sorted(candidate_customers)[0]

    desc = _clean_text(candidate.get("business_description"))
    if desc:
        sentence = re.split(r"[.!?;:]", desc, maxsplit=1)[0].strip()
        if len(sentence) > 96:
            sentence = sentence[:93].rstrip() + "..."
        return sentence

    nace_clean = _clean_text(candidate_nace_desc)
    return nace_clean or None
