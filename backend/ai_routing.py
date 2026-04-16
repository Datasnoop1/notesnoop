"""Routes LLM calls through OpenRouter for the similar-companies endpoint.

Tiers:
  DEFAULT — standard interactive calls.
  CHEAP   — cache-warm refreshes, background re-scoring.

Premium models are explicitly not used on this endpoint; cost control
takes priority over marginal ranking-quality gains.

All costs are approximate $/1M tokens from OpenRouter public pricing
at time of writing; verify before committing to SLAs.
"""

SIMILAR_COMPANIES_ROUTING = {
    "DEFAULT": {
        "model": "anthropic/claude-haiku-4-5",
        "max_tokens": 1200,
        "temperature": 0.2,
        # Strong JSON instruction-following, reliable structured output,
        # mid-tier cost. The task is exactly the kind of bounded ranking
        # Haiku-class models excel at without Flash's occasional JSON drift.
    },
    "CHEAP": {
        "model": "google/gemini-2.5-flash-lite",
        "max_tokens": 1200,
        "temperature": 0.2,
        # Cheapest tier with acceptable JSON compliance for cache-warm
        # refreshes where latency and cost matter more than nuance.
        # Used for background recomputes and low-signal targets.
    },
    "FALLBACK_CHAIN": [
        "anthropic/claude-haiku-4-5",
        "google/gemini-2.5-flash",
        "openai/gpt-4o-mini",
        "deepseek/deepseek-chat-v3",
    ],
    # Chain is tried in order on timeout, 5xx, or JSON-parse failure.
    # Gemini 2.5 Flash is the primary fallback: different provider,
    # proven on this exact prompt shape in the existing implementation.
    # gpt-4o-mini is third for provider diversity. DeepSeek is last-
    # resort — cheap, adequate JSON, occasionally slow.
    "REQUEST_TIMEOUT_S": 12,
    "MAX_RETRIES_PER_MODEL": 1,
}


# Approximate OpenRouter pricing per 1M tokens (USD). Used only for
# cost estimation in observability logs — not for billing. Update as
# upstream pricing changes.
MODEL_PRICING_USD_PER_1M = {
    "anthropic/claude-haiku-4-5":    {"input": 1.00, "output": 5.00},
    "google/gemini-2.5-flash":       {"input": 0.30, "output": 2.50},
    "google/gemini-2.5-flash-lite":  {"input": 0.10, "output": 0.40},
    "openai/gpt-4o-mini":            {"input": 0.15, "output": 0.60},
    "deepseek/deepseek-chat-v3":     {"input": 0.27, "output": 1.10},
}


# Premium model substrings that must never appear in the routing table.
# Used by self-tests and the assertion below to enforce the cost policy.
_PREMIUM_SUBSTRINGS = (
    "claude-sonnet", "claude-opus", "sonnet-4", "opus-4",
    "gpt-4-turbo", "gpt-4o-2024", "gpt-4.1", "gpt-4.5",
    "gemini-2.5-pro", "gemini-1.5-pro",
    "o1-", "o3-",
)


def _assert_no_premium_models() -> None:
    """Fail at import time if a premium model has leaked into the routing table.

    The cost policy in §11 of the implementation spec forbids Sonnet/Opus/GPT-4-
    class models on this endpoint. This guard makes that policy enforceable at
    the code level instead of at review time.
    """
    models: list[str] = [
        SIMILAR_COMPANIES_ROUTING["DEFAULT"]["model"],
        SIMILAR_COMPANIES_ROUTING["CHEAP"]["model"],
        *SIMILAR_COMPANIES_ROUTING["FALLBACK_CHAIN"],
    ]
    for m in models:
        lower = m.lower()
        for bad in _PREMIUM_SUBSTRINGS:
            if bad in lower:
                raise AssertionError(
                    f"Premium model {m!r} is not allowed on the similar-companies "
                    f"endpoint (matched substring {bad!r}). See §11 of the spec."
                )


_assert_no_premium_models()


def select_tier(cheap_mode: bool = False) -> str:
    """Select tier for the similar-companies endpoint.

    CHEAP is reserved for background or cache-warm calls only.
    Interactive requests always use DEFAULT. Premium is not an option.
    """
    return "CHEAP" if cheap_mode else "DEFAULT"


def get_tier_config(tier: str) -> dict:
    """Return the config dict for a named tier. Raises KeyError if unknown."""
    if tier not in ("DEFAULT", "CHEAP"):
        raise KeyError(f"Unknown tier {tier!r}; must be 'DEFAULT' or 'CHEAP'.")
    return SIMILAR_COMPANIES_ROUTING[tier]


def get_fallback_chain(primary_model: str) -> list[str]:
    """Return the fallback chain with the primary pulled to the front.

    The chain in SIMILAR_COMPANIES_ROUTING is the canonical order; if the
    caller's primary model sits mid-chain (e.g. CHEAP tier's flash-lite),
    we still want to try the primary first, then walk the rest of the
    chain in order, skipping any duplicate.
    """
    chain = list(SIMILAR_COMPANIES_ROUTING["FALLBACK_CHAIN"])
    ordered: list[str] = [primary_model]
    for m in chain:
        if m != primary_model:
            ordered.append(m)
    return ordered


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a single OpenRouter call.

    Returns 0.0 if the model is not in MODEL_PRICING_USD_PER_1M (so the log
    line stays populated rather than crashing the endpoint).
    """
    pricing = MODEL_PRICING_USD_PER_1M.get(model)
    if not pricing:
        return 0.0
    return (
        (input_tokens / 1_000_000.0) * pricing["input"]
        + (output_tokens / 1_000_000.0) * pricing["output"]
    )
