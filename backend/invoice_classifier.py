"""LLM-based invoice classifier for the admin P&L.

Given an invoice email (sender, subject, body/PDF excerpt), ask OpenRouter
to return a short vendor name and a category label. Called from both:

1. `scripts/invoice_ingest.py` — classifies each newly ingested invoice
   as part of the nightly cron run.
2. `backend/routers/admin.py` — backfill endpoint to classify invoices
   that have NULL vendor / category (e.g. rows stored before the
   classifier existed, or when OpenRouter was unavailable at ingest time).

Kept as a sync function (not async) because the primary caller is a
standalone cron script; when called from the async FastAPI path we wrap
it in `asyncio.to_thread`.

Categories are a short fixed taxonomy — keeps the P&L compact and makes
dashboarding predictable. New categories should be added here first.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("invoice_classifier")

# Keep this list short and stable. The P&L aggregates by these exact
# strings — changing a label orphans historical rows until a backfill runs.
CATEGORIES: list[str] = [
    "AI / LLM",
    "Hosting / Infrastructure",
    "Domain",
    "Email / Communication",
    "SaaS / Productivity tools",
    "Accounting / Legal / Finance",
    "Marketing / Ads",
    "Banking / Payment fees",
    "Other",
]

_SYSTEM_PROMPT = (
    "You classify supplier invoices for a small Belgian SaaS company "
    "called DataSnoop (company-intelligence platform, hosted on Hetzner, "
    "uses OpenRouter for AI, Supabase for auth, Stripe for payments). "
    "Return a JSON object: "
    '{"vendor": "<short company name, 1-3 words>", "category": "<exact label>"}. '
    "Vendor should be the entity being PAID, not DataSnoop. Category MUST be "
    "exactly one of: " + " | ".join(CATEGORIES) + ". "
    "Reply with JSON only, no prose, no code fences."
)

# Cheap, fast model. Fine for ~50 chars of output.
_DEFAULT_MODEL = "google/gemini-2.5-flash"

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_BODY_CHAR_CAP = 2500


def _truncate(s: Optional[str], cap: int) -> str:
    if not s:
        return ""
    s = s.replace("\x00", "")
    return s if len(s) <= cap else s[:cap] + " …[truncated]"


def classify_invoice(
    sender: Optional[str],
    subject: Optional[str],
    body: Optional[str],
    *,
    model: str = _DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict:
    """Return ``{"vendor": str | None, "category": str}``.

    On ANY failure (missing key, bad response, HTTP error, unparseable JSON)
    returns ``{"vendor": None, "category": "Other"}``. Never raises — an
    unclassifiable invoice is fine, the operator can refine via the
    backfill endpoint or by editing directly.
    """
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return {"vendor": None, "category": "Other"}

    user_prompt = (
        f"Sender: {sender or ''}\n"
        f"Subject: {subject or ''}\n\n"
        f"Body excerpt:\n{_truncate(body, _BODY_CHAR_CAP)}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 100,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "usage": {"include": True},
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                _OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://datasnoop.be",
                    "X-Title": "Datasnoop invoice-classifier",
                },
                json=payload,
            )
        if resp.status_code != 200:
            log.warning("classify_invoice: HTTP %s — %s", resp.status_code, resp.text[:180])
            return {"vendor": None, "category": "Other"}
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content)
    except Exception as e:  # JSON decode / network / schema
        log.warning("classify_invoice: %s", e)
        return {"vendor": None, "category": "Other"}

    vendor = parsed.get("vendor")
    if isinstance(vendor, str):
        vendor = vendor.strip()[:80] or None
    else:
        vendor = None

    category = parsed.get("category")
    if category not in CATEGORIES:
        category = "Other"

    return {"vendor": vendor, "category": category}
