"""OpenRouter AI client — multi-step company intelligence pipeline."""

import json
import os
import logging
import re
import time
from contextvars import ContextVar
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

# Request-scoped contextvar holding the current API endpoint path, set by
# middleware in main.py. Threads the endpoint identifier down to `ai_complete`
# so every LLM call can be attributed to the user-facing feature that
# triggered it without polluting every caller signature with an extra arg.
_current_endpoint: ContextVar[str | None] = ContextVar(
    "ai_current_endpoint", default=None
)


def set_current_endpoint(path: str | None):
    """Set the request-scoped endpoint label. Returns a token for reset."""
    return _current_endpoint.set(path)


def reset_current_endpoint(token) -> None:
    """Reset the endpoint contextvar using the token from set_current_endpoint."""
    try:
        _current_endpoint.reset(token)
    except Exception:
        # Token mismatch across contexts — non-fatal for observability.
        pass


# Lazy guards for schema migrations. Each flag flips True after a successful
# CREATE TABLE IF NOT EXISTS, so the DDL runs at most once per process.
_translation_cache_migrated = False
_llm_call_log_migrated = False


def _ensure_translation_cache_table() -> None:
    """Create the translation_cache table if missing (idempotent)."""
    global _translation_cache_migrated
    if _translation_cache_migrated:
        return
    try:
        from db import execute
        execute(
            """
            CREATE TABLE IF NOT EXISTS translation_cache (
                cbe             TEXT NOT NULL,
                kind            TEXT NOT NULL,
                lang            TEXT NOT NULL,
                value           TEXT NOT NULL,
                generated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                PRIMARY KEY (cbe, kind, lang)
            )
            """
        )
        execute(
            "CREATE INDEX IF NOT EXISTS idx_translation_cache_gen "
            "ON translation_cache(generated_at)"
        )
        _translation_cache_migrated = True
    except Exception:
        logger.exception("translation_cache table migration failed (non-fatal)")


def _ensure_llm_call_log_table() -> None:
    """Create the llm_call_log table if missing (idempotent)."""
    global _llm_call_log_migrated
    if _llm_call_log_migrated:
        return
    try:
        from db import execute
        execute(
            """
            CREATE TABLE IF NOT EXISTS llm_call_log (
                id                  SERIAL PRIMARY KEY,
                ts                  TIMESTAMP NOT NULL DEFAULT NOW(),
                endpoint            TEXT,
                model               TEXT,
                prompt_tokens       INTEGER,
                completion_tokens   INTEGER,
                cost_usd            REAL
            )
            """
        )
        execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_call_log_ts ON llm_call_log(ts)"
        )
        execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_call_log_endpoint "
            "ON llm_call_log(endpoint)"
        )
        _llm_call_log_migrated = True
    except Exception:
        logger.exception("llm_call_log table migration failed (non-fatal)")


def _log_llm_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float | None,
) -> None:
    """Insert one row into llm_call_log. Best-effort — never raises."""
    try:
        _ensure_llm_call_log_table()
        from db import execute
        execute(
            "INSERT INTO llm_call_log (endpoint, model, prompt_tokens, "
            "completion_tokens, cost_usd) VALUES (%s, %s, %s, %s, %s)",
            (
                _current_endpoint.get(),
                model,
                int(prompt_tokens) if prompt_tokens else 0,
                int(completion_tokens) if completion_tokens else 0,
                float(cost_usd) if cost_usd is not None else None,
            ),
        )
    except Exception:
        logger.debug("llm_call_log insert failed", exc_info=True)

# ── Model routing per pipeline step ────────────────────────
MODELS = {
    "url_discovery":       {"primary": "google/gemini-2.5-flash", "fallback": "openai/gpt-4o-mini"},
    "website_validation":  {"primary": "openai/gpt-4o-mini", "fallback": "google/gemini-2.5-flash"},
    "insight_generation":  {"primary": "deepseek/deepseek-chat-v3", "fallback": "google/gemini-2.5-flash"},
    "review":              {"primary": "openai/gpt-4o-mini", "fallback": "google/gemini-2.5-flash"},
}
MAX_TOKENS = {
    "url_discovery": 150,
    "website_validation": 400,
    "insight_generation": 2000,
    "review": 1500,
}

# Financial terms that must not appear in the company brief
FORBIDDEN_TERMS_RE = re.compile(
    r"\b(?:revenue|turnover|omzet|chiffre\s+d['\u2019]affaires|ebitda|profit|margin|"
    r"sales\s+figures|growth\s+percentages|ownership\s+percentages|transaction\s+values)\b",
    re.IGNORECASE,
)


_LANG_INSTRUCTION = {
    "nl": "Antwoord in het Nederlands.",
    "fr": "R\u00e9ponds en fran\u00e7ais.",
    "en": "Respond in English.",
}

_LANG_NAME = {
    "nl": "Dutch",
    "fr": "French",
    "en": "English",
}


def _normalise_lang(lang: str | None) -> str | None:
    """Reduce locale-ish strings (`nl-BE`, `NL`, ` fr `) to one of nl/fr/en."""
    if not lang:
        return None
    code = lang.strip().lower().split("-")[0]
    return code if code in _LANG_INSTRUCTION else None


async def translate_text(text: str, target_lang: str, max_tokens: int = 1200) -> str:
    """Translate ``text`` to ``target_lang`` (nl/fr/en) using a cheap model.

    Used to honour the user's site language for cached AI outputs without
    regenerating the whole response. Returns empty string on failure or
    when no API key is configured. Caller should fall back to the original
    text in that case so the user still sees something.
    """
    target = _normalise_lang(target_lang)
    if not target or not text:
        return ""
    name = _LANG_NAME[target]
    system = (
        f"You are a professional translator. Translate the user's text into {name}. "
        "Preserve formatting, line breaks, JSON structure, numbers, and proper "
        "nouns (people, company, brand names). Do NOT add commentary."
    )
    return await ai_complete(
        prompt=text,
        system=system,
        model="google/gemini-2.5-flash",
        max_tokens=max_tokens,
    )


# Two-tier translation cache:
#   - In-process OrderedDict (hot tier) keyed by (cbe, kind, target_lang)
#   - Postgres `translation_cache` table (cold tier) with a 30-day TTL
# The DB tier survives container restarts so anonymous visitors don't
# re-pay OpenRouter for the same cached enrichment after every deploy.
# In-process TTL stays shorter so a long-lived worker picks up the latest
# DB refresh rather than serving indefinitely-old strings from RAM.
from collections import OrderedDict as _OD
from time import time as _ttime
_TRANSLATION_CACHE: "_OD[tuple[str, str, str], tuple[float, str]]" = _OD()
_TRANSLATION_CACHE_TTL = 3600 * 24  # 24h hot-tier freshness
_TRANSLATION_CACHE_MAX = 10_000
_TRANSLATION_DB_TTL_DAYS = 30


def _hot_cache_set(key: tuple[str, str, str], value: str) -> None:
    if len(_TRANSLATION_CACHE) >= _TRANSLATION_CACHE_MAX:
        _TRANSLATION_CACHE.popitem(last=False)
    _TRANSLATION_CACHE[key] = (_ttime(), value)


def _translation_db_get(cbe: str, kind: str, lang: str) -> str | None:
    """Return a fresh cached translation from Postgres, or None on miss/stale."""
    try:
        _ensure_translation_cache_table()
        from db import fetch_one
        row = fetch_one(
            "SELECT value FROM translation_cache "
            "WHERE cbe = %s AND kind = %s AND lang = %s "
            "  AND generated_at >= NOW() - INTERVAL %s",
            (cbe, kind, lang, f"{_TRANSLATION_DB_TTL_DAYS} days"),
        )
        return row["value"] if row and row.get("value") is not None else None
    except Exception:
        logger.debug("translation_cache DB read failed", exc_info=True)
        return None


def _translation_db_put(cbe: str, kind: str, lang: str, value: str) -> None:
    """Upsert a translation into Postgres. Best-effort — never raises."""
    try:
        _ensure_translation_cache_table()
        from db import execute
        execute(
            "INSERT INTO translation_cache (cbe, kind, lang, value, generated_at) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON CONFLICT (cbe, kind, lang) DO UPDATE SET "
            "  value = EXCLUDED.value, generated_at = NOW()",
            (cbe, kind, lang, value),
        )
    except Exception:
        logger.debug("translation_cache DB write failed", exc_info=True)


async def translate_cached(cbe: str, kind: str, text: str, target_lang: str | None) -> str:
    """Return ``text`` translated into ``target_lang``, or the original.

    Two-tier cache: in-process OrderedDict (24h) in front of a
    Postgres table (30d). No-ops when ``target_lang`` is missing, empty,
    or invalid — caller gets the source text back unchanged.
    """
    target = _normalise_lang(target_lang)
    if not target or not text:
        return text
    key = (cbe, kind, target)
    entry = _TRANSLATION_CACHE.get(key)
    if entry and (_ttime() - entry[0]) < _TRANSLATION_CACHE_TTL:
        _TRANSLATION_CACHE.move_to_end(key)
        return entry[1]

    db_value = _translation_db_get(cbe, kind, target)
    if db_value:
        _hot_cache_set(key, db_value)
        return db_value

    translated = await translate_text(text, target)
    if not translated:
        return text  # graceful degradation — show source text
    _hot_cache_set(key, translated)
    _translation_db_put(cbe, kind, target, translated)
    return translated


async def translate_cached_json(
    cbe: str,
    kind: str,
    json_text: str,
    target_lang: str | None,
    *,
    value_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
) -> str:
    """Translate selected string fields inside a JSON blob, preserving keys.

    Naive whole-blob translation lets the LLM rename JSON keys
    (``business_description`` → ``bedrijfsbeschrijving``) which silently
    breaks consumers that destructure those keys. This walks the parsed
    JSON, translates only the named scalar fields (``value_fields``) and
    each string item of the named list fields (``list_fields``), then
    re-serialises. Other keys, numbers, and structural fields are
    preserved exactly. Backed by the same two-tier cache as
    ``translate_cached``.
    """
    import json as _json

    target = _normalise_lang(target_lang)
    if not target or not json_text:
        return json_text

    key = (cbe, kind, target)
    entry = _TRANSLATION_CACHE.get(key)
    if entry and (_ttime() - entry[0]) < _TRANSLATION_CACHE_TTL:
        _TRANSLATION_CACHE.move_to_end(key)
        return entry[1]

    db_value = _translation_db_get(cbe, kind, target)
    if db_value:
        _hot_cache_set(key, db_value)
        return db_value

    try:
        data = _json.loads(json_text) if isinstance(json_text, str) else json_text
    except Exception:
        return json_text  # not parseable — leave as source

    if not isinstance(data, dict):
        return json_text  # only handle dict shapes for now

    # Translate scalar string fields one at a time, preserving keys.
    for f in value_fields:
        v = data.get(f)
        if isinstance(v, str) and v.strip():
            t = await translate_text(v, target, max_tokens=600)
            if t:
                data[f] = t

    for f in list_fields:
        items = data.get(f)
        if isinstance(items, list):
            translated_items = []
            for item in items:
                if isinstance(item, str) and item.strip():
                    t = await translate_text(item, target, max_tokens=200)
                    translated_items.append(t or item)
                else:
                    translated_items.append(item)
            data[f] = translated_items

    out = _json.dumps(data, ensure_ascii=False)
    _hot_cache_set(key, out)
    _translation_db_put(cbe, kind, target, out)
    return out


async def ai_complete(
    prompt: str,
    system: str = "",
    model: str = "google/gemini-2.5-flash",
    max_tokens: int = 500,
    lang: str | None = None,
) -> str:
    """Call OpenRouter with the specified model.

    ``lang`` (``nl``/``fr``/``en``) prepends a one-line language instruction
    to the system prompt so the model replies in the user's site language.
    Unknown values are ignored — model defaults apply (typically English).

    Returns the model's text response, or empty string on failure / no API key.
    """
    if not OPENROUTER_API_KEY:
        return ""

    messages: list[dict] = []
    lang_norm = _normalise_lang(lang)
    if lang_norm:
        instruction = _LANG_INSTRUCTION[lang_norm]
        system = f"{instruction}\n\n{system}" if system else instruction
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        # Ask OpenRouter to include billed cost + token usage on the
        # response so we can log real spend, not estimates. Flag is a
        # no-op for providers that don't support it.
        "usage": {"include": True},
    }

    # DeepSeek provider routing for better reliability
    if "deepseek" in model:
        payload["provider"] = {
            "order": ["Fireworks", "Together", "DeepSeek"],
            "allow_fallbacks": True,
        }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_BASE,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://datasnoop.be",
                    "X-Title": "Datasnoop",
                },
                json=payload,
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage") or {}
                _log_llm_call(
                    model=model,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    cost_usd=usage.get("cost"),
                )
                return data["choices"][0]["message"]["content"]
            logger.warning(
                "OpenRouter returned %s: %s", resp.status_code, resp.text[:200]
            )
    except Exception as e:
        logger.exception("OpenRouter request failed: %s", e)

    return ""


async def ai_complete_with_meta(
    prompt: str,
    system: str = "",
    model: str = "google/gemini-2.5-flash",
    max_tokens: int = 500,
    temperature: float | None = None,
    timeout_s: float = 60.0,
) -> dict:
    """Call OpenRouter and return text plus metadata (tokens, latency, error).

    Returned dict:
        text:          model output string (empty on any failure)
        model:         echoed model id
        input_tokens:  prompt tokens reported by OpenRouter, or 0 if unknown
        output_tokens: completion tokens reported by OpenRouter, or 0 if unknown
        ok:            True iff HTTP 200 and non-empty text
        error:         short reason string when ok is False, else None
        status_code:   HTTP status code, or None on network error
        latency_ms:    wall-clock time for the call

    Does NOT walk any fallback chain — the caller is responsible for retrying
    on a different model when ok is False. Keeping the retry policy in the
    caller lets the similar-companies router log which models were attempted
    for observability (§8).
    """
    started = time.monotonic()
    meta = {
        "text": "",
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "ok": False,
        "error": None,
        "status_code": None,
        "latency_ms": 0,
    }

    if not OPENROUTER_API_KEY:
        meta["error"] = "no_api_key"
        meta["latency_ms"] = int((time.monotonic() - started) * 1000)
        return meta

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    if temperature is not None:
        payload["temperature"] = temperature

    if "deepseek" in model:
        payload["provider"] = {
            "order": ["Fireworks", "Together", "DeepSeek"],
            "allow_fallbacks": True,
        }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_BASE,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://datasnoop.be",
                    "X-Title": "Datasnoop",
                },
                json=payload,
                timeout=timeout_s,
            )
            meta["status_code"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "") or ""
                usage = data.get("usage") or {}
                meta["text"] = content
                meta["input_tokens"] = int(usage.get("prompt_tokens") or 0)
                meta["output_tokens"] = int(usage.get("completion_tokens") or 0)
                meta["ok"] = bool(content.strip())
                if not meta["ok"]:
                    meta["error"] = "empty_completion"
                _log_llm_call(
                    model=model,
                    prompt_tokens=meta["input_tokens"],
                    completion_tokens=meta["output_tokens"],
                    cost_usd=usage.get("cost"),
                )
            else:
                meta["error"] = f"http_{resp.status_code}"
                logger.warning(
                    "OpenRouter returned %s for model %s: %s",
                    resp.status_code, model, resp.text[:200],
                )
    except httpx.TimeoutException:
        meta["error"] = "timeout"
        logger.warning("OpenRouter timeout for model %s after %.1fs", model, timeout_s)
    except Exception as e:
        meta["error"] = f"exception:{type(e).__name__}"
        logger.exception("OpenRouter request failed for model %s", model)

    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    return meta


def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from LLM text that may contain markdown fences."""
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Try to find first { ... } block
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _clean_scraped_text(text: str) -> str:
    """Pre-clean scraped website/LinkedIn text before passing to the LLM.

    - Strips nav/footer/cookie banner boilerplate
    - Drops paragraphs shorter than 50 chars
    - Deduplicates repeated lines
    - Collapses whitespace
    """
    if not text:
        return ""

    # Remove common boilerplate patterns (nav, footer, cookie banners)
    boilerplate_patterns = [
        r"(?i)(?:accept|reject)\s+(?:all\s+)?cookies?.*",
        r"(?i)we\s+use\s+cookies.*?(?:accept|learn more|privacy policy).*",
        r"(?i)cookie\s+(?:policy|preferences|settings|consent).*",
        r"(?i)privacy\s+(?:policy|notice|statement)\s*[\|\-].*",
        r"(?i)(?:skip\s+to\s+(?:main\s+)?content|jump\s+to\s+navigation).*",
        r"(?i)\b(?:copyright|all\s+rights\s+reserved)\s*\d{4}.*",
        r"(?i)terms\s+(?:of\s+use|and\s+conditions|of\s+service)\s*[\|\-].*",
        r"(?i)follow\s+us\s+on\s+(?:twitter|facebook|instagram|linkedin).*",
        r"(?i)subscribe\s+to\s+our\s+newsletter.*",
        r"(?i)sign\s+up\s+for\s+(?:our|the)\s+newsletter.*",
    ]
    for pattern in boilerplate_patterns:
        text = re.sub(pattern, "", text)

    # Split into lines and process
    lines = text.split("\n")

    # Drop paragraphs shorter than 50 chars
    lines = [line for line in lines if len(line.strip()) >= 50 or line.strip() == ""]

    # Deduplicate repeated lines (preserve order)
    seen: set[str] = set()
    unique_lines = []
    for line in lines:
        normalized = line.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_lines.append(line)
        elif not normalized:
            unique_lines.append(line)

    text = "\n".join(unique_lines)

    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def _extract_linkedin_from_html(html: str) -> str:
    """Extract a LinkedIn company URL from raw HTML (e.g. footer social links)."""
    matches = re.findall(r'https?://(?:www\.)?linkedin\.com/company/[a-zA-Z0-9_-]+', html)
    if matches:
        # Deduplicate and return the first unique one
        return matches[0].split("?")[0].rstrip("/")
    return ""


def _normalize_domain(s: str) -> str:
    """Normalize a domain or company name to a comparable slug."""
    s = s.lower().strip()
    # Remove common company suffixes
    for suffix in [" nv", " bv", " sa", " bvba", " sprl", " srl", " cvba", " scrl"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    # Strip scheme and www if it looks like a URL
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    # Take only the domain part if there's a path
    s = s.split("/")[0]
    # Remove TLD
    s = re.sub(r"\.\w{2,6}$", "", s)
    # Collapse to alphanumeric
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _summarize_feedback(fetch_all, cbe: str) -> dict:
    """Query ai_insights_feedback and build a summary for prompt injection.

    Returns a dict with:
        - ``text``: human-readable summary string (empty if no feedback)
        - ``website_flagged``: True if any user marked website as incorrect
        - ``linkedin_flagged``: True if any user marked LinkedIn as incorrect
        - ``old_website_url``: the website URL from the previous insight (if any)
    """
    rows = fetch_all(
        """SELECT overall, website_correct, linkedin_correct, insight_correct, comment
           FROM ai_insights_feedback
           WHERE enterprise_number = %s
           ORDER BY created_at DESC""",
        (cbe,),
    )
    if not rows:
        return {"text": "", "website_flagged": False, "linkedin_flagged": False, "old_website_url": ""}

    total = len(rows)
    down_count = sum(1 for r in rows if r.get("overall") == "down")
    up_count = total - down_count
    website_wrong = sum(1 for r in rows if r.get("website_correct") is False)
    website_right = sum(1 for r in rows if r.get("website_correct") is True)
    linkedin_wrong = sum(1 for r in rows if r.get("linkedin_correct") is False)
    linkedin_right = sum(1 for r in rows if r.get("linkedin_correct") is True)
    insight_wrong = sum(1 for r in rows if r.get("insight_correct") is False)
    insight_right = sum(1 for r in rows if r.get("insight_correct") is True)

    parts = []
    if down_count:
        parts.append(f"Previous AI insight was flagged as incorrect by {down_count} user(s) (and approved by {up_count}).")
    if website_wrong:
        parts.append(f"Website URL was marked wrong by {website_wrong} user(s), correct by {website_right}.")
    if linkedin_wrong:
        parts.append(f"LinkedIn URL was marked wrong by {linkedin_wrong} user(s), correct by {linkedin_right}.")
    if insight_wrong:
        parts.append(f"Insight content was marked wrong by {insight_wrong} user(s), correct by {insight_right}.")

    # Collect user comments (most recent first, max 3)
    comments = [r["comment"] for r in rows if r.get("comment")]
    if comments:
        parts.append("User comments: " + " | ".join(comments[:3]))

    return {
        "text": " ".join(parts),
        "website_flagged": website_wrong > 0,
        "linkedin_flagged": linkedin_wrong > 0,
        "old_website_url": "",
    }


def _build_corporate_graph(fetch_all, cbe: str) -> dict:
    """Query shareholder, participating_interest, and administrator tables once.

    Returns a dict with:
        - shareholders: list of dicts with name, type, ownership_pct
        - subsidiaries: list of dicts with name, country, ownership_pct
        - administrators: list of dicts with name, role_label
        - admin_names_str: comma-separated string for quick prompt embedding
    """
    shareholders = []
    try:
        rows = fetch_all(
            """SELECT name, shareholder_type, ownership_pct FROM shareholder
               WHERE enterprise_number = %s
               ORDER BY ownership_pct DESC NULLS LAST LIMIT 10""",
            (cbe,),
        )
        if rows:
            shareholders = [
                {
                    "name": r["name"],
                    "type": "individual" if r.get("shareholder_type") == "individual" else "entity",
                    "ownership_pct": r.get("ownership_pct"),
                }
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch shareholders for %s: %s", cbe, e)

    subsidiaries = []
    try:
        rows = fetch_all(
            """SELECT name, country, ownership_pct FROM participating_interest
               WHERE enterprise_number = %s
               ORDER BY ownership_pct DESC NULLS LAST LIMIT 10""",
            (cbe,),
        )
        if rows:
            subsidiaries = [
                {
                    "name": r["name"],
                    "country": r.get("country"),
                    "ownership_pct": r.get("ownership_pct"),
                }
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch subsidiaries for %s: %s", cbe, e)

    administrators = []
    try:
        rows = fetch_all(
            """SELECT DISTINCT name, role_label FROM administrator
               WHERE enterprise_number = %s AND mandate_end IS NULL
               LIMIT 10""",
            (cbe,),
        )
        if rows:
            administrators = [
                {"name": r["name"], "role_label": r.get("role_label", "")}
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch administrators for %s: %s", cbe, e)

    admin_names_str = ", ".join(a["name"] for a in administrators) if administrators else ""

    return {
        "shareholders": shareholders,
        "subsidiaries": subsidiaries,
        "administrators": administrators,
        "admin_names_str": admin_names_str,
    }


def _recent_staatsblad_events(fetch_all, cbe: str, limit: int = 6) -> list[dict]:
    """Fetch recent structured Staatsblad events for inclusion in the
    ai_insights_pipeline prompt — feeds the AI concrete filing history
    instead of re-calling the gazette.

    Returns up to `limit` most-recent events across all 8 categories.
    """
    try:
        rows = fetch_all(
            """SELECT pub_date, event_type, sub_type, event_date,
                      person_name, person_role, entity_name,
                      amount_eur, summary
               FROM staatsblad_event
               WHERE enterprise_number = %s
               ORDER BY pub_date DESC, id DESC
               LIMIT %s""",
            (cbe, limit),
        )
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.warning("Failed to fetch Staatsblad events for %s: %s", cbe, e)
        return []


def _format_staatsblad_events_block(events: list[dict]) -> str:
    """Format recent Staatsblad events as a <recent_filings> block."""
    if not events:
        return ""
    lines = ["<recent_filings>"]
    for ev in events:
        date = str(ev.get("pub_date") or "")
        t = ev.get("event_type") or ""
        sub = ev.get("sub_type") or ""
        summary = ev.get("summary") or ""
        parts = [f"  - {date} [{t}/{sub}]"] if sub else [f"  - {date} [{t}]"]
        parts.append(summary or "(no summary)")
        lines.append(" ".join(parts))
    lines.append("</recent_filings>")
    return "\n".join(lines)


def _format_corporate_graph_block(graph: dict) -> str:
    """Format the corporate graph as a <corporate_graph> XML block for prompts.

    Returns an empty string if the graph has no shareholders, subsidiaries, or
    administrators — avoids padding prompts with empty data for standalone SMEs.
    """
    if not graph["shareholders"] and not graph["subsidiaries"] and not graph["administrators"]:
        return ""

    parts = ["<corporate_graph>"]
    if graph["shareholders"]:
        sh_lines = []
        for s in graph["shareholders"]:
            pct = f" ({s['ownership_pct']}%)" if s.get("ownership_pct") else ""
            sh_lines.append(f"  - {s['name']} [{s['type']}]{pct}")
        parts.append("Shareholders:\n" + "\n".join(sh_lines))
    if graph["subsidiaries"]:
        sub_lines = []
        for s in graph["subsidiaries"]:
            pct = f" ({s['ownership_pct']}%)" if s.get("ownership_pct") else ""
            country = f", {s['country']}" if s.get("country") else ""
            sub_lines.append(f"  - {s['name']}{country}{pct}")
        parts.append("Subsidiaries:\n" + "\n".join(sub_lines))
    if graph["administrators"]:
        adm_lines = []
        for a in graph["administrators"]:
            role = f" — {a['role_label']}" if a.get("role_label") else ""
            adm_lines.append(f"  - {a['name']}{role}")
        parts.append("Administrators:\n" + "\n".join(adm_lines))
    parts.append("</corporate_graph>")
    return "\n".join(parts)


def _needs_review(insights: dict) -> bool:
    """Decide whether the review step (Step 4) should run.

    Returns True if ANY of these conditions hold:
    - Brief contains forbidden financial terms
    - Any field is missing source attribution
    - business_description is shorter than 80 chars
    - history is longer than 1500 chars
    - confidence is "low"
    """
    # Check forbidden financial terms in all text fields
    text_fields = [
        "business_description", "products", "customers",
        "market_position", "history", "group_context",
    ]
    for field in text_fields:
        val = insights.get(field, "")
        if isinstance(val, list):
            val = " ".join(val)
        if val and FORBIDDEN_TERMS_RE.search(val):
            return True

    # Check source attribution completeness
    attribution = insights.get("source_attribution", {})
    if not attribution or not isinstance(attribution, dict):
        return True
    for field in ["business_description", "products", "customers", "market_position", "history"]:
        if insights.get(field) and field not in attribution:
            return True

    # business_description too short
    desc = insights.get("business_description", "")
    if len(desc) < 80:
        return True

    # history too long
    history = insights.get("history", "")
    if len(history) > 1500:
        return True

    # low confidence
    if insights.get("confidence") == "low":
        return True

    return False


def _apply_review_diff(insights: dict, diff_items: list[dict]) -> dict:
    """Apply a review diff (list of corrections) to the insights dict."""
    for item in diff_items:
        field = item.get("field", "")
        corrected = item.get("corrected")
        if field and corrected is not None and field in insights:
            insights[field] = corrected
    return insights


async def ai_insights_pipeline(cbe: str, conn_helpers: dict, lang: str | None = None) -> dict:
    """Multi-step AI pipeline to generate structured company insights.

    Parameters
    ----------
    cbe : str
        The 10-digit enterprise number.
    conn_helpers : dict
        Must contain ``fetch_one``, ``fetch_all``, and ``execute`` callables.
    lang : str | None
        Site language (``nl``/``fr``/``en``). When supplied, the user-visible
        narrative is generated in that language so the AI insight matches the
        rest of the page. Internal reasoning steps (URL discovery, JSON
        validation) stay locale-neutral.

    Returns a dict with structured insight fields, suitable for JSON storage.
    """
    from scraper import (
        scrape_url,
        _strip_html,
        slugify_company_name,
        duckduckgo_search_linkedin_url,
        duckduckgo_search_website_url,
        zenrows_search_website_url,
    )

    fetch_one = conn_helpers["fetch_one"]
    fetch_all = conn_helpers.get("fetch_all", lambda q, p: [])
    execute = conn_helpers["execute"]

    # ── Gather company context from DB ──────────────────────────
    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code, ci.zipcode,
               a.street_nl AS street, a.house_number,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN address a ON a.entity_number = ci.enterprise_number AND a.type_of_address = 'REGO'
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))

    if not company or not company.get("name"):
        return {"error": "Company not found"}

    name = company["name"]
    city = company.get("city", "Belgium")
    zipcode = company.get("zipcode", "")
    street = company.get("street", "")
    house_number = company.get("house_number", "")
    sector = company.get("sector", "")
    revenue = company.get("revenue")
    ebitda = company.get("ebitda")
    fte = company.get("fte_total")
    fiscal_year = company.get("fiscal_year")
    kbo_address = " ".join(filter(None, [street, house_number, zipcode, city]))

    # Check for existing website in contact table
    contact_row = fetch_one("""
        SELECT value FROM contact
        WHERE entity_number = %s AND contact_type = 'WEB'
        LIMIT 1
    """, (cbe,))
    known_website = (contact_row.get("value", "").strip() if contact_row else "") or ""

    # ── Gather user feedback on previous attempts ──────────────
    feedback = _summarize_feedback(fetch_all, cbe)
    feedback_text = feedback["text"]

    # If users flagged the website, grab the old URL from the previous insight
    if feedback["website_flagged"]:
        prev_insight_row = fetch_one(
            "SELECT ai_insights FROM company_enrichment WHERE enterprise_number = %s",
            (cbe,),
        )
        if prev_insight_row and prev_insight_row.get("ai_insights"):
            try:
                prev = json.loads(prev_insight_row["ai_insights"]) if isinstance(prev_insight_row["ai_insights"], str) else prev_insight_row["ai_insights"]
                feedback["old_website_url"] = prev.get("website_url", "")
            except (json.JSONDecodeError, TypeError):
                pass

    # ── Build corporate graph ONCE, reuse everywhere ───────────
    graph = _build_corporate_graph(fetch_all, cbe)
    admin_names = graph["admin_names_str"]
    graph_block = _format_corporate_graph_block(graph)

    # ── Stage 3d: fold recent Staatsblad events into the context ──
    # Feeds the AI concrete filing history (structured, already LLM-
    # parsed) instead of asking a downstream LLM to guess from labels.
    staatsblad_events = _recent_staatsblad_events(fetch_all, cbe, limit=6)
    staatsblad_block = _format_staatsblad_events_block(staatsblad_events)
    if staatsblad_block:
        # Append to graph_block so both contexts ride together in the
        # same <context>...</context> prompt section downstream.
        graph_block = (graph_block + "\n\n" + staatsblad_block) if graph_block else staatsblad_block

    # ══════════════════════════════════════════════════════════════
    # STEP 1: URL Discovery  (KBO → Google → LLM fallback)
    # ══════════════════════════════════════════════════════════════
    website_url = known_website
    linkedin_url = ""
    url_source_website = ""
    url_source_linkedin = ""

    if website_url:
        url_source_website = "KBO"
        logger.info("URL discovery for %s: website from KBO contact table — %s", name, website_url)

    # ── Try DuckDuckGo search for WEBSITE only ──────────────────
    # LinkedIn discovery happens later: website HTML → search → slug
    use_zenrows = feedback.get("website_flagged", False)

    if not website_url:
        try:
            if use_zenrows:
                logger.info("URL discovery for %s: using Zenrows (previous website was flagged wrong)", name)
                website_candidate = await zenrows_search_website_url(name, city=city)
            else:
                website_candidate = await duckduckgo_search_website_url(name, city=city)
            search_source = "Zenrows" if use_zenrows else "DuckDuckGo"
            if website_candidate:
                website_url = website_candidate
                url_source_website = search_source
                logger.info("URL discovery for %s: website from %s — %s", name, search_source, website_url)
            # Don't grab LinkedIn from search yet — website HTML is checked first
        except Exception as e:
            logger.warning("Search failed for %s, falling back to LLM: %s", name, e)

    # ── LLM fallback (only if search didn't find a website) ──────
    if not website_url:
        url_prompt = (
            f"Given a Belgian company:\n"
            f"- Name: {name}\n"
            f"- City: {city}\n"
            f"- Sector: {sector}\n"
            f"- Registered address: {kbo_address}\n"
        )
        if admin_names:
            url_prompt += f"- Administrators: {admin_names}\n"
        if graph_block:
            url_prompt += f"\n{graph_block}\n\n"
        url_prompt += (
            "The target company may share a website or LinkedIn page with a parent, "
            "holding, or operating subsidiary. Consider brand names of parents and active "
            "subsidiaries. Prefer a URL that clearly covers the target entity's activity; "
            "if only a group-level URL exists, return it.\n\n"
            'Return ONLY JSON: {{"website_url": "...", "linkedin_url": "...", '
            '"website_shared_with": "parent/subsidiary name or empty string", '
            '"linkedin_shared_with": "parent/subsidiary name or empty string", '
            '"confidence": "high"|"medium"|"low"}}\n'
            "If you cannot determine a URL, use empty strings."
        )
        # Try primary model
        url_resp = await ai_complete(
            url_prompt,
            system="You are a data lookup assistant. Return only valid JSON.",
            model=MODELS["url_discovery"]["primary"],
            max_tokens=MAX_TOKENS["url_discovery"],
        )
        # Fallback on empty response
        if not url_resp:
            url_resp = await ai_complete(
                url_prompt,
                system="You are a data lookup assistant. Return only valid JSON.",
                model=MODELS["url_discovery"]["fallback"],
                max_tokens=MAX_TOKENS["url_discovery"],
            )
        if url_resp:
            parsed = _extract_json(url_resp)
            if parsed:
                if not website_url and parsed.get("website_url"):
                    website_url = parsed.get("website_url", "") or ""
                    url_source_website = "LLM"
                    logger.info("URL discovery for %s: website from LLM fallback — %s", name, website_url)
                if not linkedin_url and parsed.get("linkedin_url"):
                    linkedin_url = parsed.get("linkedin_url", "") or ""
                    url_source_linkedin = "LLM"

    # Ensure scheme on website URL
    if website_url and not website_url.startswith("http"):
        website_url = "https://" + website_url

    # ══════════════════════════════════════════════════════════════
    # Scrape website → extract LinkedIn from HTML → then search
    # ══════════════════════════════════════════════════════════════
    website_text = ""
    linkedin_text = ""

    if website_url:
        try:
            html = await scrape_url(website_url)
            if html:
                website_text = _strip_html(html, max_chars=8000)
                # Extract LinkedIn from website HTML (footer links, social icons)
                found_li = _extract_linkedin_from_html(html)
                if found_li:
                    linkedin_url = found_li
                    url_source_linkedin = "website"
                    logger.info("URL discovery for %s: LinkedIn found on company website — %s", name, found_li)
        except Exception as e:
            logger.warning("Website scrape failed for %s: %s", website_url, e)

    # ── LinkedIn search only if website didn't have it ────────────
    if not linkedin_url:
        try:
            linkedin_candidate = await duckduckgo_search_linkedin_url(name, city=city)
            if linkedin_candidate:
                linkedin_url = linkedin_candidate
                url_source_linkedin = "DuckDuckGo"
                logger.info("URL discovery for %s: LinkedIn from DuckDuckGo — %s", name, linkedin_url)
        except Exception as e:
            logger.warning("LinkedIn DuckDuckGo search failed for %s: %s", name, e)

    if not linkedin_url:
        slug = slugify_company_name(name)
        if slug:
            linkedin_url = f"https://www.linkedin.com/company/{slug}"
            url_source_linkedin = "slug"

    logger.info(
        "URL discovery summary for %s: website=%s (source=%s), linkedin=%s (source=%s)",
        name,
        website_url or "(none)", url_source_website or "none",
        linkedin_url or "(none)", url_source_linkedin or "none",
    )

    if linkedin_url:
        try:
            html = await scrape_url(linkedin_url, js_render=True, premium_proxy=True)
            if html:
                linkedin_text = _strip_html(html, max_chars=8000)
        except Exception as e:
            logger.warning("LinkedIn scrape failed for %s: %s", linkedin_url, e)

    # ══════════════════════════════════════════════════════════════
    # STEP 2: Website Validation
    # ══════════════════════════════════════════════════════════════
    website_verified = bool(known_website)  # Trust KBO-registered websites

    if website_text and not website_verified:
        # Deterministic shortcut: if domain matches company name AND
        # (scraped text mentions registered city OR domain ends in .be)
        domain_norm = _normalize_domain(website_url)
        name_norm = _normalize_domain(name)
        city_lower = city.lower() if city else ""
        domain_is_be = website_url.rstrip("/").endswith(".be") or ".be/" in website_url

        if domain_norm == name_norm and (
            (city_lower and city_lower in website_text.lower()) or domain_is_be
        ):
            logger.info(
                "Website %s deterministically validated for %s (domain match + city/BE)",
                website_url, name,
            )
            website_verified = True

    if website_text and not website_verified:
        verify_prompt = (
            f"I scraped the website {website_url} and need to verify it belongs to this Belgian company:\n"
            f"- Company name: {name}\n"
            f"- Registered address: {kbo_address}\n"
            f"- Sector/activity: {sector}\n"
            f"- Country: Belgium\n"
            f"- Known administrators: {admin_names}\n"
        )
        if graph_block:
            verify_prompt += f"\n{graph_block}\n"
        verify_prompt += (
            f"\nWebsite text (first 3000 chars):\n{website_text[:3000]}\n\n"
            "Does this website belong to THIS company or its corporate group? Check each:\n"
            "1. address_match: Does the website mention the registered address or city?\n"
            "2. activity_match: Does the website describe the same business activity/sector?\n"
            "3. country_match: Is at least one entity Belgian?\n"
            "4. name_match: Does the company name, parent name, or subsidiary name appear?\n"
            "5. people_match: Do administrator names or major shareholders appear?\n\n"
            "Return ONLY JSON with this exact structure:\n"
            '{"matches": [\n'
            '  {"check": "address_match", "found": true/false, "match_source": "brief explanation"},\n'
            '  {"check": "activity_match", "found": true/false, "match_source": "brief explanation"},\n'
            '  {"check": "country_match", "found": true/false, "match_source": "brief explanation"},\n'
            '  {"check": "name_match", "found": true/false, "match_source": "brief explanation"},\n'
            '  {"check": "people_match", "found": true/false, "match_source": "brief explanation"}\n'
            "]}"
        )
        # Inject feedback about previously wrong website
        if feedback["website_flagged"]:
            old_url = feedback.get("old_website_url", "")
            flag_note = "\n\nNote: A previous attempt"
            if old_url:
                flag_note += f" found website {old_url} but"
            flag_note += " users flagged the website as incorrect. Please be extra careful in verifying the website."
            verify_prompt += flag_note

        verify_resp = await ai_complete(
            verify_prompt,
            system="You are a data validation assistant. Be strict — if unsure, mark the check as false.",
            model=MODELS["website_validation"]["primary"],
            max_tokens=MAX_TOKENS["website_validation"],
        )
        # Fallback on empty response
        if not verify_resp:
            verify_resp = await ai_complete(
                verify_prompt,
                system="You are a data validation assistant. Be strict — if unsure, mark the check as false.",
                model=MODELS["website_validation"]["fallback"],
                max_tokens=MAX_TOKENS["website_validation"],
            )

        if verify_resp:
            verify_parsed = _extract_json(verify_resp)
            if verify_parsed:
                # Compute is_valid in code: need at least 2 of 5 checks to match
                matches_list = verify_parsed.get("matches", [])
                match_count = sum(
                    1 for m in matches_list if m.get("found") is True
                )
                is_valid = match_count >= 2

                if not is_valid:
                    reasons = [
                        m.get("match_source", "")
                        for m in matches_list if m.get("found") is True
                    ]
                    logger.info(
                        "Website %s rejected for %s: only %d/5 checks passed (%s)",
                        website_url, name, match_count,
                        "; ".join(reasons) if reasons else "no matches",
                    )
                    website_text = ""  # Don't use this website's content
                    website_url = ""   # Clear the bad URL
            else:
                # Couldn't parse structured response — reject to be safe
                logger.info("Website validation response unparseable for %s, rejecting %s", name, website_url)
                website_text = ""
                website_url = ""

    # ══════════════════════════════════════════════════════════════
    # STEP 3: Insight Generation
    # ══════════════════════════════════════════════════════════════

    # Pre-clean scraped text
    cleaned_website_text = _clean_scraped_text(website_text)
    cleaned_linkedin_text = _clean_scraped_text(linkedin_text)

    # Build financial summary for context
    fin_parts = []
    if revenue:
        fin_parts.append(f"Revenue: EUR {revenue:,.0f}")
    if ebitda:
        fin_parts.append(f"EBITDA: EUR {ebitda:,.0f}")
    if revenue and ebitda and revenue > 0:
        margin = round(ebitda / revenue * 100, 1)
        fin_parts.append(f"EBITDA margin: {margin}%")
    if fte:
        fin_parts.append(f"Employees (FTE): {fte:,.0f}")
    if fiscal_year:
        fin_parts.append(f"Fiscal year: {fiscal_year}")
    financial_summary = "; ".join(fin_parts) if fin_parts else "No financial data available."

    insight_prompt = (
        f"Company: {name}\n"
        f"Location: {city}, Belgium\n"
        f"Sector (NACE): {sector}\n"
        f"Financials: {financial_summary}\n"
    )
    if admin_names:
        insight_prompt += f"Current administrators: {admin_names}\n"
    if graph_block:
        insight_prompt += f"\n{graph_block}\n"
        insight_prompt += (
            "\nIf the website/LinkedIn content describes group-level activity, "
            "distinguish what applies to the target entity vs. the broader group. "
            "Ownership structure may be mentioned factually (parent, subsidiaries) "
            "but do NOT include ownership percentages or transaction values.\n"
        )
    if cleaned_website_text:
        insight_prompt += f"\n--- <website> Company website text ---\n{cleaned_website_text}\n--- </website> ---\n"
    if cleaned_linkedin_text:
        insight_prompt += f"\n--- <linkedin> LinkedIn page text ---\n{cleaned_linkedin_text}\n--- </linkedin> ---\n"
    if graph_block:
        insight_prompt += "\n--- <corporate_graph> (see above) ---\n"

    insight_prompt += (
        "\nBased on the above, create a company intelligence brief.\n\n"
        "CRITICAL RULES:\n"
        "- Do NOT include: revenue, turnover, omzet, chiffre d'affaires, EBITDA, profit, "
        "margin, sales figures, growth percentages, ownership percentages, transaction values.\n"
        "- NEVER restate the NACE sector description — the user already sees that.\n"
        "- Focus ONLY on: what the company actually does day-to-day, what products/services "
        "they sell, who buys from them, what makes them different, and their history.\n"
        "- Use specific details from the website and LinkedIn content.\n"
        "- Every extracted fact MUST cite its source tag (website/linkedin/corporate_graph).\n\n"
        "Return a JSON object with exactly these fields:\n"
        '- "business_description": What the company does in 2-3 sentences (no financials!)\n'
        '- "products": Array of their main products/services as strings, e.g. ["product A", "service B"]\n'
        '- "customers": Who their customers are (industries, segments, B2B/B2C)\n'
        '- "market_position": Market position and key differentiators\n'
        '- "history": Brief history/milestones (founding, acquisitions, growth)\n'
        '- "key_management": Array of key people found, each as {"name": "...", "role": "...", "linkedin_url": "..."} — extract from LinkedIn page or website team page. If none found, use empty array []\n'
        '- "group_context": If this company is part of a group, describe the parent/subsidiary relationship in one sentence. If standalone, use empty string.\n'
        '- "confidence": "high"|"medium"|"low" — how confident you are in the accuracy of this brief\n'
        '- "source_attribution": Object mapping each field name to its primary source, e.g. {"business_description": "website", "products": "website+linkedin", "history": "corporate_graph"}\n'
        '- "website_url": The company website URL (or empty string if unknown)\n'
        '- "linkedin_url": The LinkedIn company page URL (or empty string if unknown)\n\n'
        "Return ONLY valid JSON, no markdown fences."
    )

    # Inject user feedback into insight prompt
    if feedback_text:
        insight_prompt += (
            f"\n--- User feedback on previous attempt ---\n"
            f"{feedback_text}\n"
            "Please take this feedback into account and avoid the same mistakes.\n"
        )

    insight_system = (
        "You are a private equity analyst creating a company intelligence brief. "
        "You must NEVER include financial figures (revenue, EBITDA, margins, profit, "
        "employee counts) — the user already has those. Focus exclusively on qualitative "
        "business insights: what the company does, their products, customers, and history. "
        "If website or LinkedIn text is available, extract specific details. "
        "Every fact must cite its source (website/linkedin/corporate_graph)."
    )

    def _build_insight_prompt_with_review_feedback(base_prompt: str, review_feedback: str) -> str:
        """Append review feedback to the insight prompt for a retry."""
        return (
            base_prompt
            + f"\n--- Review feedback from quality check ---\n"
            + review_feedback
            + "\nPlease fix the issues identified above and return corrected JSON.\n"
        )

    # Try primary model. ``lang`` only flows into the user-visible
    # insight generation; URL discovery / review steps stay locale-neutral
    # because their output is JSON consumed by code, not by the user.
    insight_resp = await ai_complete(
        insight_prompt,
        system=insight_system,
        model=MODELS["insight_generation"]["primary"],
        max_tokens=MAX_TOKENS["insight_generation"],
        lang=lang,
    )

    if not insight_resp:
        # Fallback model
        insight_resp = await ai_complete(
            insight_prompt,
            system=insight_system,
            model=MODELS["insight_generation"]["fallback"],
            max_tokens=MAX_TOKENS["insight_generation"],
            lang=lang,
        )

    insights = _extract_json(insight_resp) if insight_resp else None

    if not insights:
        # Build a minimal fallback from whatever we have
        insights = {
            "business_description": insight_resp.strip() if insight_resp else "Unable to generate insights.",
            "products": [],
            "customers": "",
            "market_position": "",
            "history": "",
            "group_context": "",
            "confidence": "low",
            "source_attribution": {},
            "website_url": website_url,
            "linkedin_url": linkedin_url,
        }

    # Normalize products field: ensure it's a list
    products = insights.get("products", [])
    if isinstance(products, str):
        # Split comma-separated string into list
        insights["products"] = [p.strip() for p in products.split(",") if p.strip()] if products else []

    # Ensure URL fields are populated from our discovery
    if not insights.get("website_url"):
        insights["website_url"] = website_url
    if not insights.get("linkedin_url"):
        insights["linkedin_url"] = linkedin_url

    # ══════════════════════════════════════════════════════════════
    # STEP 4: Conditional Review
    # ══════════════════════════════════════════════════════════════
    if _needs_review(insights):
        review_prompt = (
            "Review this company intelligence brief about a Belgian company. "
            "Check for:\n"
            "1. Forbidden financial terms (revenue, turnover, omzet, chiffre d'affaires, EBITDA, "
            "profit, margin, sales figures, growth percentages, ownership percentages, transaction values)\n"
            "2. Missing source attribution on any field\n"
            "3. Hallucinated claims not supported by the source data\n"
            "4. Content that conflates target-entity activity with parent/group activity\n"
            "5. business_description shorter than 80 characters\n"
            "6. history longer than 1500 characters\n\n"
            f"Company name: {name}\n"
            f"Sector: {sector}\n"
            f"Location: {city}, Belgium\n\n"
            f"Brief to review:\n{json.dumps(insights, indent=2)}\n\n"
            "Return a JSON object with exactly this structure:\n"
            '{"issues": [\n'
            '  {"field": "field_name", "original": "original text", "issue_type": "forbidden_term|missing_source|hallucination|too_short|too_long", "corrected": "corrected text"}\n'
            "]}\n"
            "If no issues found, return {\"issues\": []}.\n"
            "Return ONLY valid JSON, no markdown fences."
        )

        # Inject user feedback into review prompt
        if feedback_text:
            review_prompt += (
                f"\n--- User feedback on previous attempt ---\n"
                f"{feedback_text}\n"
                "Pay special attention to the issues flagged by users.\n"
            )

        review_resp = await ai_complete(
            review_prompt,
            system="You are a quality reviewer. Identify specific issues and provide corrections. Return only valid JSON.",
            model=MODELS["review"]["primary"],
            max_tokens=MAX_TOKENS["review"],
        )
        # Fallback on empty response
        if not review_resp:
            review_resp = await ai_complete(
                review_prompt,
                system="You are a quality reviewer. Identify specific issues and provide corrections. Return only valid JSON.",
                model=MODELS["review"]["fallback"],
                max_tokens=MAX_TOKENS["review"],
            )

        if review_resp:
            review_parsed = _extract_json(review_resp)
            if review_parsed:
                issues = review_parsed.get("issues", [])
                has_hallucination = any(
                    i.get("issue_type") == "hallucination" for i in issues
                )

                if len(issues) > 3 or has_hallucination:
                    # Retry Step 3 ONCE with review feedback appended
                    review_feedback = json.dumps(issues, indent=2)
                    retry_prompt = _build_insight_prompt_with_review_feedback(
                        insight_prompt, review_feedback
                    )
                    retry_resp = await ai_complete(
                        retry_prompt,
                        system=insight_system,
                        model=MODELS["insight_generation"]["primary"],
                        max_tokens=MAX_TOKENS["insight_generation"],
                        lang=lang,
                    )
                    if not retry_resp:
                        retry_resp = await ai_complete(
                            retry_prompt,
                            system=insight_system,
                            model=MODELS["insight_generation"]["fallback"],
                            max_tokens=MAX_TOKENS["insight_generation"],
                            lang=lang,
                        )
                    retry_insights = _extract_json(retry_resp) if retry_resp else None

                    if retry_insights:
                        # Normalize products on retry too
                        retry_products = retry_insights.get("products", [])
                        if isinstance(retry_products, str):
                            retry_insights["products"] = [
                                p.strip() for p in retry_products.split(",") if p.strip()
                            ] if retry_products else []
                        if not retry_insights.get("website_url"):
                            retry_insights["website_url"] = website_url
                        if not retry_insights.get("linkedin_url"):
                            retry_insights["linkedin_url"] = linkedin_url
                        insights = retry_insights
                    else:
                        # Retry failed — apply original diff and flag quality warning
                        insights = _apply_review_diff(insights, issues)
                        insights["quality_warning"] = True
                else:
                    # Apply the diff corrections
                    insights = _apply_review_diff(insights, issues)

    # Preserve URL fields (reviewer/retry might drop them)
    if not insights.get("website_url"):
        insights["website_url"] = website_url
    if not insights.get("linkedin_url"):
        insights["linkedin_url"] = linkedin_url

    # Tag how each URL was discovered (KBO / Google / LLM / slug)
    insights["url_source_website"] = url_source_website
    insights["url_source_linkedin"] = url_source_linkedin

    # ══════════════════════════════════════════════════════════════
    # Store in database
    # ══════════════════════════════════════════════════════════════
    insights_json = json.dumps(insights, ensure_ascii=False)
    try:
        execute("""
            INSERT INTO company_enrichment (enterprise_number, ai_insights, generated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (enterprise_number)
            DO UPDATE SET ai_insights = EXCLUDED.ai_insights, generated_at = NOW()
        """, (cbe, insights_json))
    except Exception as e:
        logger.warning("Failed to store AI insights for %s: %s", cbe, e)

    return insights


# ══════════════════════════════════════════════════════════════════════
# Phase 1 — bulk enrichment helpers (Q2 + Haiku escalation)
#
# Callable by `backend/enrichment_worker.py` and (eventually Phase 5)
# by the on-profile elaboration step. These helpers are intentionally
# small and composable so the worker owns the per-company orchestration
# while this module owns the model-facing primitives.
#
# IMPORTANT: the legacy `ai_insights_pipeline()` above remains the
# canonical on-profile flow for the rest of Phase 1. Phase 5 refactors
# the profile path to call `call_elaboration_narrative()` on top of a
# cached bulk_summary. Don't remove the old pipeline yet.
# ══════════════════════════════════════════════════════════════════════

# Model choices fixed from the Spike 2 matrix (see
# `scripts/research/v2/REPORT_v2.md`). Q2 = GPT-4o-mini with structured
# KBO context wins on quality AND cost; Haiku 4.5 is the escalation.
BULK_Q2_MODEL = "openai/gpt-4o-mini"
BULK_HAIKU_MODEL = "anthropic/claude-haiku-4.5"


def _nn(v) -> str:
    """Render a KBO fact line. Empty on None/blank so context stays tight."""
    if v is None:
        return ""
    s = str(v).strip()
    return s


def build_kbo_context_block(kbo: dict) -> str:
    """Format the KBO fact block that every bulk Q2 call prepends.

    Input keys (all optional):
      name, parent, majority_shareholders (list[str]),
      key_subsidiaries (list[str]), admins_top3 (list[str]),
      revenue_band (str like '5-50M EUR'), fte_band (str),
      hq_city, primary_nace, nace_description, juridical_situation,
      notes (freeform, e.g. NACE/website-mismatch warning).

    Output is a compact `[KBO FACTS]` block (≤~400 tokens typical).
    Spike 2 §5 found this block drives +0.77 avg quality vs scrape-only.
    """

    def _list(vals):
        if not vals:
            return ""
        clean = [str(v).strip() for v in vals if v]
        return "; ".join(clean[:5])

    lines = [
        f"Name: {_nn(kbo.get('name'))}",
        f"HQ city: {_nn(kbo.get('hq_city'))}",
        f"Primary NACE: {_nn(kbo.get('primary_nace'))}"
        + (f" — {_nn(kbo.get('nace_description'))}"
           if kbo.get("nace_description") else ""),
        f"Parent: {_nn(kbo.get('parent'))}",
        f"Majority shareholders: {_list(kbo.get('majority_shareholders'))}",
        f"Key subsidiaries: {_list(kbo.get('key_subsidiaries'))}",
        f"Top administrators: {_list(kbo.get('admins_top3'))}",
        f"Revenue band: {_nn(kbo.get('revenue_band'))}",
        f"FTE band: {_nn(kbo.get('fte_band'))}",
        f"Juridical situation: {_nn(kbo.get('juridical_situation'))}",
        f"Notes: {_nn(kbo.get('notes'))}",
    ]
    # Drop empty 'Key: ' lines so the block is legible at short KBO
    # records.
    rendered = [ln for ln in lines if ln.rsplit(":", 1)[-1].strip()]
    return "[KBO STRUCTURED FACTS]\n" + "\n".join(rendered) + "\n[/KBO]"


_Q2_SCHEMA_INSTRUCTION = (
    "Return ONE JSON object matching this schema, nothing else — no prose, "
    "no markdown fences, no trailing commentary:\n"
    "{\n"
    '  "business_description": "<one paragraph, 2-4 sentences>",\n'
    '  "products_services": ["<string>", ...],\n'
    '  "customer_segments": ["<string>", ...],\n'
    '  "confidence": "high|medium|low|insufficient_information"\n'
    "}\n\n"
    "Rules:\n"
    "- Trust the KBO facts over scraped website content when they conflict.\n"
    "- `business_description` must describe the Belgian entity named above, "
    "not a same-named company elsewhere. If the scrape clearly describes a "
    "different company, set confidence=low and say so briefly.\n"
    "- `products_services` and `customer_segments` are 2-6 short phrases each; "
    "lowercase, no marketing fluff.\n"
    "- `confidence=high` only if the website was substantive and the KBO facts "
    "are consistent with it. Use `insufficient_information` when the scrape "
    "returned nothing useful."
)


def _clip(text: str | None, limit: int = 3000) -> str:
    if not text:
        return ""
    t = text.strip()
    return t if len(t) <= limit else t[:limit - 1] + "…"


async def call_q2(
    *, kbo: dict, scraped_text: str | None, model: str = BULK_Q2_MODEL
) -> dict:
    """Run the Q2 bulk enrichment call (GPT-4o-mini + KBO context).

    Returns a dict
        `{summary: dict|None, raw_text: str, meta: dict, ok: bool,
          error: str|None}`.

    `summary` is the parsed 4-field object; None on JSON parse failure
    or empty completion. `meta` carries latency / tokens for the admin
    observability panel. Caller persists the parsed object into
    `company_enrichment.bulk_summary`.
    """
    kbo_block = build_kbo_context_block(kbo)
    body = (
        f"{kbo_block}\n\n"
        f"[SCRAPED WEBSITE TEXT — 3k char cap]\n"
        f"{_clip(scraped_text, 3000)}\n[/SCRAPE]\n\n"
        f"{_Q2_SCHEMA_INSTRUCTION}"
    )
    system = (
        "You write factual one-paragraph company briefs for a Belgian private-"
        "equity screener. Keep descriptions specific (what they make, who buys) "
        "and never invent financials, headcounts, or ownership percentages."
    )

    meta = await ai_complete_with_meta(
        prompt=body,
        system=system,
        model=model,
        max_tokens=500,
        temperature=0.1,
        timeout_s=45.0,
    )
    if not meta.get("ok"):
        return {
            "summary": None,
            "raw_text": meta.get("text") or "",
            "meta": meta,
            "ok": False,
            "error": meta.get("error") or "call_failed",
        }

    text = meta.get("text") or ""
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        return {
            "summary": None,
            "raw_text": text,
            "meta": meta,
            "ok": False,
            "error": "json_parse_failed",
        }

    # Coerce confidence to a known label, then coerce fields to the
    # expected shapes. Tolerate string-joined lists from less-rigorous
    # models.
    conf = (parsed.get("confidence") or "").strip().lower()
    if conf not in ("high", "medium", "low", "insufficient_information"):
        conf = "low"
    summary = {
        "business_description": (parsed.get("business_description") or "").strip(),
        "products_services": _coerce_list(parsed.get("products_services")),
        "customer_segments": _coerce_list(parsed.get("customer_segments")),
        "confidence": conf,
    }

    return {
        "summary": summary,
        "raw_text": text,
        "meta": meta,
        "ok": True,
        "error": None,
    }


def _coerce_list(val) -> list[str]:
    """Normalise model output to a short list of short strings."""
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
    elif isinstance(val, str) and val.strip():
        items = [p.strip() for p in re.split(r"[,;\n]", val) if p.strip()]
    else:
        return []
    # Dedup case-insensitively, preserve order, cap to 8.
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        k = it.lower()
        if k not in seen:
            seen.add(k)
            out.append(it)
        if len(out) >= 8:
            break
    return out


async def call_haiku_escalation(
    *, kbo: dict, scraped_text: str | None,
    q2_summary: dict | None = None,
    model: str = BULK_HAIKU_MODEL,
) -> dict:
    """Rerun the Q2 prompt through Haiku 4.5, optionally seeded with Q2's output.

    Returns the same shape as `call_q2`. Called from the worker when
    `enrichment_routing.should_escalate` fires.

    Haiku's advantage here is group/parent disambiguation and tier-1
    quality — Spike 1 §5 and Spike 2 §6 are the source for this choice.
    OpenRouter exposes Haiku via its Anthropic integration; we do NOT
    use Anthropic Batch here in Phase 1 (Phase 3 optimisation).
    """
    kbo_block = build_kbo_context_block(kbo)
    seed = ""
    if q2_summary:
        try:
            seed = (
                "\n[Q2 FIRST-PASS — use as a draft to refine]\n"
                + json.dumps(q2_summary, ensure_ascii=False)
                + "\n[/Q2]\n"
            )
        except Exception:
            seed = ""

    body = (
        f"{kbo_block}\n\n"
        f"[SCRAPED WEBSITE TEXT — 8k char cap]\n"
        f"{_clip(scraped_text, 8000)}\n[/SCRAPE]\n"
        f"{seed}\n"
        f"{_Q2_SCHEMA_INSTRUCTION}"
    )
    system = (
        "You write factual one-paragraph company briefs for a Belgian private-"
        "equity screener. Treat the KBO facts as authoritative when they "
        "conflict with the scrape. When the scrape's entity does not match the "
        "KBO record (e.g. same-named company in a different country or sector), "
        "mark confidence=low and say so in the description."
    )

    meta = await ai_complete_with_meta(
        prompt=body,
        system=system,
        model=model,
        max_tokens=700,
        temperature=0.1,
        timeout_s=60.0,
    )
    if not meta.get("ok"):
        return {
            "summary": None,
            "raw_text": meta.get("text") or "",
            "meta": meta,
            "ok": False,
            "error": meta.get("error") or "call_failed",
        }

    text = meta.get("text") or ""
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        return {
            "summary": None,
            "raw_text": text,
            "meta": meta,
            "ok": False,
            "error": "json_parse_failed",
        }

    conf = (parsed.get("confidence") or "").strip().lower()
    if conf not in ("high", "medium", "low", "insufficient_information"):
        conf = "low"
    summary = {
        "business_description": (parsed.get("business_description") or "").strip(),
        "products_services": _coerce_list(parsed.get("products_services")),
        "customer_segments": _coerce_list(parsed.get("customer_segments")),
        "confidence": conf,
    }
    return {
        "summary": summary,
        "raw_text": text,
        "meta": meta,
        "ok": True,
        "error": None,
    }


def build_template_summary(kbo: dict) -> dict:
    """Deterministic template fallback — used for dormant / no-web rows.

    No LLM call. Output shape matches `call_q2`/`call_haiku_escalation`
    so the downstream embedder and search code treat it uniformly. A
    template-only row still gets embedded (NACE + city anchor) but is
    filtered out of the default search results by the confidence floor.
    """
    nace = (kbo.get("nace_description") or "").strip()
    hq = (kbo.get("hq_city") or "").strip()
    name = (kbo.get("name") or "").strip() or "This company"
    dormant = (kbo.get("juridical_situation") or "").strip() in {
        "010", "012", "013", "014",
    }

    if dormant:
        desc = (
            f"{name} is a Belgian legal entity currently in dissolution or "
            f"liquidation (KBO status {kbo.get('juridical_situation')})."
        )
        if nace:
            desc += f" Last registered activity: {nace}."
    else:
        parts = [f"{name} is a Belgian company"]
        if nace:
            parts.append(f"active in {nace.lower()}")
        if hq:
            parts.append(f"based in {hq}")
        desc = " ".join(parts).rstrip(".") + "."

    return {
        "business_description": desc,
        "products_services": [nace.lower()] if nace else [],
        "customer_segments": [],
        "confidence": (
            "insufficient_information" if dormant or not (nace and hq) else "low"
        ),
    }


def build_bulk_embedding_text(summary: dict, kbo: dict | None = None) -> str:
    """Compose the text fed to the embedder from a bulk_summary row.

    Priority order:
      1. Factual business_description (the embedding workhorse)
      2. Products/services, customer segments
      3. NACE + HQ city anchors (helps templated rows retrieve)

    Spike 2 §12 fixed the lean schema for bulk; this builder mirrors it.
    """
    bits: list[str] = []
    desc = (summary or {}).get("business_description") if summary else None
    if desc:
        bits.append(str(desc).strip())
    ps = (summary or {}).get("products_services") or []
    if ps:
        bits.append("Products/services: " + ", ".join(str(p) for p in ps))
    cs = (summary or {}).get("customer_segments") or []
    if cs:
        bits.append("Customers: " + ", ".join(str(c) for c in cs))
    if kbo:
        nace = (kbo.get("nace_description") or "").strip()
        hq = (kbo.get("hq_city") or "").strip()
        if nace:
            bits.append(f"Sector (NACE): {nace}")
        if hq:
            bits.append(f"Headquartered in {hq}, Belgium")
    return " \n".join(bits).strip()
