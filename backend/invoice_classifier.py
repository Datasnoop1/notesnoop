"""LLM-based invoice classifier and extractor for the admin P&L.

Given an invoice email (sender, subject, body/PDF excerpt), ask OpenRouter
to return vendor, category, amount (in cents), invoice date, and currency.
Called from both:

1. `scripts/invoice_ingest.py` — classifies each newly ingested invoice
   as part of the nightly cron run. The regex amount/date parser runs
   first; the LLM fills in whichever fields the regex missed.
2. `backend/routers/admin.py` — backfill endpoint to classify invoices
   that have NULL vendor / category / amount / date (e.g. rows stored
   before the classifier existed, or when OpenRouter was unavailable at
   ingest time).

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
import re
from datetime import datetime
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
    "You extract structured data from supplier invoices for a small Belgian "
    "SaaS company called DataSnoop (company-intelligence platform, hosted on "
    "Hetzner, uses OpenRouter for AI, Supabase for auth, Stripe for payments). "
    "Return a JSON object with EXACTLY these fields: "
    '{"vendor": "<short company name, 1-3 words>", '
    '"category": "<exact label>", '
    '"amount_cents": <integer total invoice amount in cents, VAT-inclusive if shown, or null>, '
    '"invoice_date": "<YYYY-MM-DD>" or null, '
    '"currency": "EUR" or other ISO-4217 code}. '
    "Vendor is the entity being PAID, not DataSnoop. Category MUST be exactly "
    "one of: " + " | ".join(CATEGORIES) + ". "
    "For amount_cents: report the TOTAL amount payable in cents (1234.56 EUR -> 123456). "
    "Accept any label — 'Total', 'Amount due', 'Te betalen', 'Montant TTC', "
    "'Zu zahlen', 'Total amount', 'Subtotal' (only if no higher total shown), "
    "'Balance due', a prominent unlabeled headline number — whatever the "
    "invoice uses. Prefer VAT-inclusive totals. Do not infer if truly ambiguous; "
    "return null. For invoice_date: the issue date of the invoice (not the due "
    "date, not today's date). "
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


_EMPTY: dict = {
    "vendor": None,
    "category": "Other",
    "amount_cents": None,
    "invoice_date": None,
    "currency": None,
}


def _coerce_amount_cents(raw) -> Optional[int]:
    """Coerce an LLM-returned amount into integer cents. Accepts int, float,
    or numeric string (euro-style or english-style decimal)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 < raw < 10**11 else None
    if isinstance(raw, float):
        c = int(round(raw))
        return c if 0 < c < 10**11 else None
    if isinstance(raw, str):
        s = raw.strip().replace(" ", "").replace("€", "").replace("EUR", "")
        if "," in s and "." in s:
            last = max(s.rfind(","), s.rfind("."))
            if s[last] == ",":
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            # If the string is already an integer (cents) the LLM followed
            # instructions; if it has a decimal, treat as euros.
            if "." in s:
                return int(round(float(s) * 100))
            v = int(s)
            return v if 0 < v < 10**11 else None
        except ValueError:
            return None
    return None


def _coerce_invoice_date(raw) -> Optional[str]:
    """Coerce an LLM date into ISO YYYY-MM-DD."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s.lower() == "null":
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    # Pull the first ISO-shaped substring
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    return None


def classify_invoice(
    sender: Optional[str],
    subject: Optional[str],
    body: Optional[str],
    *,
    model: str = _DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict:
    """Return a dict with keys ``vendor`` (str | None), ``category`` (str,
    always one of CATEGORIES — defaults to "Other"), ``amount_cents``
    (int | None), ``invoice_date`` (ISO YYYY-MM-DD | None), ``currency``
    (str | None).

    On ANY failure (missing key, bad response, HTTP error, unparseable JSON)
    returns a dict with the same keys, all None except category="Other".
    Never raises — a partially extractable invoice is fine; the operator
    can refine via the backfill endpoint or by editing directly.
    """
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return dict(_EMPTY)

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
        "max_tokens": 200,
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
            return dict(_EMPTY)
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content)
        # LLM sometimes returns [{...}] instead of the requested object.
        # Unwrap single-element lists; anything else falls back to the default.
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else {}
        if not isinstance(parsed, dict):
            return dict(_EMPTY)

        vendor = parsed.get("vendor")
        if isinstance(vendor, str):
            vendor = vendor.strip()[:80] or None
        else:
            vendor = None

        category = parsed.get("category")
        if category not in CATEGORIES:
            category = "Other"

        amount_cents = _coerce_amount_cents(parsed.get("amount_cents"))
        invoice_date = _coerce_invoice_date(parsed.get("invoice_date"))

        currency = parsed.get("currency")
        if isinstance(currency, str):
            currency = currency.strip().upper()[:3] or None
            if currency and not re.fullmatch(r"[A-Z]{3}", currency):
                currency = None
        else:
            currency = None

        return {
            "vendor": vendor,
            "category": category,
            "amount_cents": amount_cents,
            "invoice_date": invoice_date,
            "currency": currency,
        }
    except Exception as e:  # JSON decode / network / schema
        log.warning("classify_invoice: %s", e)
        return dict(_EMPTY)
