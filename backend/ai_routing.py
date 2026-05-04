"""Routes LLM calls through OpenRouter or Ollama for the similar-companies endpoint.

Tiers:
  DEFAULT - interactive shortlist pass.
  FINAL   - premium final judgment pass for the top shortlist.
  CHEAP   - cache-warm refreshes, background re-scoring.

All costs are approximate $/1M tokens from vendor public pricing at time
of writing; verify before committing to SLAs.
"""

import os


def _env_model(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_chain(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default)
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or list(default)


_DEFAULT_FALLBACK_CHAIN = [
    "anthropic/claude-haiku-4-5",
]

_FINAL_FALLBACK_CHAIN = [
    "anthropic/claude-haiku-4-5",
]


SIMILAR_COMPANIES_ROUTING = {
    "DEFAULT": {
        "model": _env_model(
            "SIMILAR_COMPANIES_DEFAULT_MODEL",
            "ollama:kimi-k2.6",
        ),
        "max_tokens": 1000,
        "temperature": 0.1,
        # Interactive shortlist pass. This stage trims the candidate set
        # before the premium final judge is called.
    },
    "FINAL": {
        "model": _env_model(
            "SIMILAR_COMPANIES_FINAL_MODEL",
            "anthropic/claude-sonnet-4.6",
        ),
        "max_tokens": 1600,
        "temperature": 0.1,
        # Final ranking + explanation pass over the shortlisted candidates.
    },
    "CHEAP": {
        "model": _env_model(
            "SIMILAR_COMPANIES_CHEAP_MODEL",
            "google/gemini-2.5-flash-lite",
        ),
        "max_tokens": 1200,
        "temperature": 0.2,
        # Cheapest tier with acceptable JSON compliance for cache-warm
        # refreshes where latency and cost matter more than nuance.
        # Used for background recomputes and low-signal targets.
    },
    "FALLBACK_CHAIN": _env_chain(
        "SIMILAR_COMPANIES_FALLBACK_CHAIN",
        _DEFAULT_FALLBACK_CHAIN,
    ),
    "FINAL_FALLBACK_CHAIN": _env_chain(
        "SIMILAR_COMPANIES_FINAL_FALLBACK_CHAIN",
        _FINAL_FALLBACK_CHAIN,
    ),
    # Chains are tried in order on 5xx or JSON-parse failure. User-adjacent
    # timeout handling is stricter in rerank.py: Ollama timeouts jump straight
    # to Haiku, while OpenRouter timeouts return the raw scored candidates.
    # Models prefixed with `ollama:` route through OLLAMA_BASE_URL using
    # OLLAMA_API_KEY (for example `ollama:kimi-k2.6`).
    "SHORTLIST_SIZE": 15,
    "REQUEST_TIMEOUT_S": 8,
    # Asyncio.wait_for backstop around each provider call. NOT a budget
    # cap — the inner httpx timeout (REQUEST_TIMEOUT_S) is what bounds
    # request latency in practice. This kicks in only when the inner
    # client wedges past its own timeout (eg. CPU-stuck tokenizer,
    # connection in CLOSE_WAIT). Set ~0.5-1s above REQUEST_TIMEOUT_S so
    # the backstop never preempts a healthy request.
    "WALL_BACKSTOP_S": 8.5,
    "MAX_RETRIES_PER_MODEL": 1,
    "RETRY_BACKOFF_S": 1.0,
    "USERPATH_FALLBACK_MODEL": "anthropic/claude-haiku-4-5",
}


# Approximate OpenRouter pricing per 1M tokens (USD). Used only for
# cost estimation in observability logs - not for billing. Update as
# upstream pricing changes.
MODEL_PRICING_USD_PER_1M = {
    "ollama:kimi-k2.6":              {"input": 0.95, "output": 4.00},
    "anthropic/claude-sonnet-4.6":   {"input": 3.00, "output": 15.00},
    "anthropic/claude-haiku-4-5":    {"input": 1.00, "output": 5.00},
    "google/gemini-2.5-flash":       {"input": 0.30, "output": 2.50},
    "google/gemini-2.5-flash-lite":  {"input": 0.10, "output": 0.40},
    "openai/gpt-4o-mini":            {"input": 0.15, "output": 0.60},
    "deepseek/deepseek-chat-v3":     {"input": 0.27, "output": 1.10},
}


def select_tier(cheap_mode: bool = False) -> str:
    """Select tier for the similar-companies endpoint.

    CHEAP is reserved for background or cache-warm calls only.
    Interactive requests start with DEFAULT; the caller may then run a
    second FINAL pass for the shortlisted candidates.
    """
    return "CHEAP" if cheap_mode else "DEFAULT"


def get_tier_config(tier: str) -> dict:
    """Return the config dict for a named tier. Raises KeyError if unknown."""
    if tier not in ("DEFAULT", "FINAL", "CHEAP"):
        raise KeyError(f"Unknown tier {tier!r}; must be 'DEFAULT', 'FINAL', or 'CHEAP'.")
    return SIMILAR_COMPANIES_ROUTING[tier]


def get_fallback_chain(primary_model: str, tier: str = "DEFAULT") -> list[str]:
    """Return the fallback chain with the primary pulled to the front.

    The configured chain is the canonical order for the chosen tier; if the
    caller's primary model sits mid-chain, we still want to try the primary
    first, then walk the rest of the chain in order, skipping any duplicate.
    """
    if tier == "FINAL":
        chain = list(SIMILAR_COMPANIES_ROUTING["FINAL_FALLBACK_CHAIN"])
    else:
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
