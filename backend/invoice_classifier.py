"""LLM-based invoice classifier and extractor for the admin P&L.

Phase-22 rewrite: deeper category taxonomy (parent → child),
confidence scoring, model-explained reasoning, vendor-pattern hints,
and best-effort line-item extraction. Backwards-compatible with the
v1 ``classify_invoice()`` callers — that shim now wraps the v2 path
and downcasts to the legacy 5-field shape.

Callers:

1. ``scripts/invoice_ingest.py`` — classifies each newly ingested
   invoice as part of the nightly cron run. Regex amount/date
   parsers run first; the LLM fills in fields the regex missed.
2. ``backend/routers/admin.py`` — backfill endpoint to re-classify
   invoices with NULL or "Other" categories.

Stay sync (not async) because the primary caller is a standalone
cron script. When called from the FastAPI path, wrap the call in
``asyncio.to_thread``.

The taxonomy lives in ``TAXONOMY``. New categories should be
added there first. The P&L aggregates by parent category, so adding
a child under an existing parent is fully backwards-compatible.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

import httpx

log = logging.getLogger("invoice_classifier")

# ---------------------------------------------------------------------------
# Taxonomy — parent → children, ordered by typical P&L weight.
# ---------------------------------------------------------------------------
# Keep parent labels stable (they aggregate the historical P&L). Children
# can grow over time without backfill — the P&L renders parent totals by
# default and a per-child drill-down on demand.
TAXONOMY: dict[str, list[str]] = {
    "AI / LLM": [
        "OpenRouter",
        "Anthropic",
        "OpenAI",
        "Google AI",
        "NVIDIA",
        "HuggingFace",
        "Other LLM",
    ],
    "Hosting / Infrastructure": [
        "Hetzner",
        "AWS",
        "Cloudflare",
        "RunPod",
        "Other compute",
        "CDN / DNS",
    ],
    "Domain & Email": [
        "Domain registrar",
        "Email hosting",
        "Mailing / Newsletter",
    ],
    "SaaS / Tools": [
        "IDE / Dev tools",
        "Productivity",
        "Design",
        "Analytics",
        "Other SaaS",
    ],
    "Data subscriptions": [
        "Belgian registry / NBB",
        "Other data feed",
    ],
    "Accounting / Legal / Finance": [
        "Accounting software",
        "Bookkeeper / Tax advisor",
        "Lawyer / Notary",
        "Insurance",
    ],
    "Marketing / Ads": [
        "Search ads",
        "Social ads",
        "Content / Copy",
        "PR / Sponsorship",
    ],
    "Banking / Payment fees": [
        "Stripe fees",
        "Bank fees",
        "Currency conversion",
    ],
    "Hardware": [
        "Laptop / Desktop",
        "Peripherals",
        "Office furniture",
    ],
    "Travel / Entertainment": [
        "Travel",
        "Conferences",
        "Meals",
    ],
    "Other": [
        "Other",
    ],
}

PARENT_CATEGORIES: list[str] = list(TAXONOMY.keys())

# Flatten to "Parent / Child" for the LLM prompt (avoids the model having
# to invent a hierarchy from a flat list).
_FLAT_LABELS: list[str] = [
    f"{parent} / {child}" for parent, children in TAXONOMY.items() for child in children
]


# ---------------------------------------------------------------------------
# Vendor-pattern heuristics — short-circuits the LLM on known senders.
# ---------------------------------------------------------------------------
# Loaded lazily from the DB on first use. Falls back to this hardcoded
# list when the DB is unreachable (cron context, schema not yet applied).
# Operator can curate via the admin UI; the table seeds itself with this
# list on first boot.

_FALLBACK_PATTERNS: list[dict[str, str]] = [
    # AI / LLM
    {"pattern": "openrouter", "vendor": "OpenRouter", "parent": "AI / LLM", "child": "OpenRouter"},
    {"pattern": "anthropic", "vendor": "Anthropic", "parent": "AI / LLM", "child": "Anthropic"},
    {"pattern": "openai", "vendor": "OpenAI", "parent": "AI / LLM", "child": "OpenAI"},
    {"pattern": "nvidia", "vendor": "NVIDIA", "parent": "AI / LLM", "child": "NVIDIA"},
    {"pattern": "huggingface", "vendor": "HuggingFace", "parent": "AI / LLM", "child": "HuggingFace"},
    # Hosting
    {"pattern": "hetzner", "vendor": "Hetzner", "parent": "Hosting / Infrastructure", "child": "Hetzner"},
    {"pattern": "amazonaws", "vendor": "AWS", "parent": "Hosting / Infrastructure", "child": "AWS"},
    {"pattern": "aws.amazon", "vendor": "AWS", "parent": "Hosting / Infrastructure", "child": "AWS"},
    {"pattern": "cloudflare", "vendor": "Cloudflare", "parent": "Hosting / Infrastructure", "child": "Cloudflare"},
    {"pattern": "runpod", "vendor": "RunPod", "parent": "Hosting / Infrastructure", "child": "RunPod"},
    {"pattern": "webshare", "vendor": "Webshare", "parent": "Hosting / Infrastructure", "child": "Other compute"},
    # SaaS / Tools
    {"pattern": "cursor.sh", "vendor": "Cursor", "parent": "SaaS / Tools", "child": "IDE / Dev tools"},
    {"pattern": "anthropic.com/claude-code", "vendor": "Claude Code", "parent": "SaaS / Tools", "child": "IDE / Dev tools"},
    {"pattern": "github", "vendor": "GitHub", "parent": "SaaS / Tools", "child": "IDE / Dev tools"},
    {"pattern": "vercel", "vendor": "Vercel", "parent": "Hosting / Infrastructure", "child": "Other compute"},
    {"pattern": "supabase", "vendor": "Supabase", "parent": "SaaS / Tools", "child": "Other SaaS"},
    {"pattern": "notion", "vendor": "Notion", "parent": "SaaS / Tools", "child": "Productivity"},
    {"pattern": "linear", "vendor": "Linear", "parent": "SaaS / Tools", "child": "Productivity"},
    # Domain / Email
    {"pattern": "namecheap", "vendor": "Namecheap", "parent": "Domain & Email", "child": "Domain registrar"},
    {"pattern": "godaddy", "vendor": "GoDaddy", "parent": "Domain & Email", "child": "Domain registrar"},
    {"pattern": "gandi", "vendor": "Gandi", "parent": "Domain & Email", "child": "Domain registrar"},
    # Banking / Payment fees
    {"pattern": "stripe.com", "vendor": "Stripe", "parent": "Banking / Payment fees", "child": "Stripe fees"},
    {"pattern": "wise.com", "vendor": "Wise", "parent": "Banking / Payment fees", "child": "Currency conversion"},
    # Belgian
    {"pattern": "kbo.be", "vendor": "FOD Economie / KBO", "parent": "Data subscriptions", "child": "Belgian registry / NBB"},
    {"pattern": "nbb.be", "vendor": "Nationale Bank van België", "parent": "Data subscriptions", "child": "Belgian registry / NBB"},
    {"pattern": "belnet", "vendor": "Belnet", "parent": "Hosting / Infrastructure", "child": "Other compute"},
]


def _load_patterns_from_db() -> list[dict[str, Any]]:
    """Return the active vendor-pattern list, fetching from the DB once
    and falling back to the hardcoded list on any error.
    """
    try:
        from db import fetch_all  # local import — keeps cron callers DB-agnostic
        rows = fetch_all(
            """
            SELECT id, pattern, vendor_canonical AS vendor,
                   parent_category AS parent, child_category AS child,
                   priority
            FROM invoice_vendor_pattern
            ORDER BY priority DESC, id ASC
            """
        )
        if rows:
            return [dict(r) for r in rows]
    except Exception:
        log.debug("invoice_vendor_pattern unavailable; using fallback list")
    return _FALLBACK_PATTERNS


def match_vendor_pattern(sender: str | None, subject: str | None,
                          body: str | None) -> Optional[dict[str, Any]]:
    """Return the first vendor pattern that matches the sender/subject/body
    (case-insensitive substring) or None.

    Patterns are tried in priority order; the first hit wins.
    """
    haystacks = [
        (sender or "").lower(),
        (subject or "").lower(),
        (body or "").lower()[:1000],  # subject + small body slice is enough
    ]
    text = " ".join(haystacks)
    for p in _load_patterns_from_db():
        needle = (p.get("pattern") or "").lower().strip()
        if needle and needle in text:
            return p
    return None


def record_pattern_hit(pattern_id: int) -> None:
    """Increment hit_count + last_used_at on a vendor pattern (best effort)."""
    try:
        from db import execute
        execute(
            "UPDATE invoice_vendor_pattern "
            "SET hit_count = hit_count + 1, last_used_at = NOW() "
            "WHERE id = %s",
            (pattern_id,),
        )
    except Exception:
        log.debug("record_pattern_hit failed")


# ---------------------------------------------------------------------------
# LLM prompt (v2)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_V2 = (
    "You extract structured data from supplier invoices for a small "
    "Belgian SaaS company called DataSnoop. Return ONLY a JSON object "
    "with these fields:\n"
    '  "vendor"          : short company name (1-3 words)\n'
    '  "parent_category" : one of the parent labels in the taxonomy\n'
    '  "child_category"  : one of the child labels under that parent\n'
    '  "confidence"      : 0.0-1.0 number (how sure are you)\n'
    '  "reason"          : 1 sentence explaining the choice\n'
    '  "amount_cents"    : total payable amount in cents (VAT-inclusive '
    "if shown), or null\n"
    '  "invoice_date"    : YYYY-MM-DD or null\n'
    '  "currency"        : ISO-4217 like EUR / USD or null\n'
    '  "line_items"      : array of {description, amount_cents} when the '
    "invoice clearly itemises lines; otherwise []\n\n"
    "Taxonomy (Parent / Child):\n  - "
    + "\n  - ".join(_FLAT_LABELS)
    + "\n\nRules:\n"
    "* `vendor` is the entity being PAID, not DataSnoop.\n"
    "* `parent_category` MUST be one of the parents above; `child_category` "
    "MUST be a child under the chosen parent. If unsure, use 'Other / Other' "
    "with low confidence.\n"
    "* Amount: report the total payable in cents (1234.56 EUR -> 123456). "
    "Accept any label. Do not infer if truly ambiguous; return null.\n"
    "* `line_items`: only fill when the invoice has discrete lines with "
    "amounts. Don't synthesise. Empty array if not present.\n"
    "* `confidence`: 0.9+ when sender+subject clearly identify a known "
    "vendor; 0.6-0.8 when you inferred from body; <0.5 when guessing.\n"
    "* `reason`: tell me what tipped you off (\"sender domain anthropic.com "
    "and 'usage credits' in subject\"). 1 sentence.\n"
    "Reply with JSON only, no prose, no code fences."
)

_DEFAULT_MODEL = "google/gemini-2.5-flash"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_BODY_CHAR_CAP = 3500  # bigger than v1 to capture line-items


def _truncate(s: Optional[str], cap: int) -> str:
    if not s:
        return ""
    s = s.replace("\x00", "")
    return s if len(s) <= cap else s[:cap] + " …[truncated]"


_EMPTY_V2: dict[str, Any] = {
    "vendor": None,
    "parent_category": "Other",
    "child_category": "Other",
    "category": "Other",  # legacy field for v1 callers
    "confidence": 0.0,
    "reason": None,
    "amount_cents": None,
    "invoice_date": None,
    "currency": None,
    "line_items": [],
    "source": "fallback",
    "vendor_pattern_id": None,
    "model": None,
}


def _coerce_amount_cents(raw) -> Optional[int]:
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
            if "." in s:
                return int(round(float(s) * 100))
            v = int(s)
            return v if 0 < v < 10**11 else None
        except ValueError:
            return None
    return None


def _coerce_invoice_date(raw) -> Optional[str]:
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
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    return None


def _validate_taxonomy(parent: Any, child: Any) -> tuple[str, str]:
    """Coerce a (parent, child) into the closest valid TAXONOMY pair.

    On any unknown parent → "Other / Other". On valid parent + unknown
    child → keep the parent + first child under it.
    """
    if not isinstance(parent, str) or parent not in TAXONOMY:
        return "Other", "Other"
    children = TAXONOMY[parent]
    if not isinstance(child, str) or child not in children:
        return parent, children[0] if children else "Other"
    return parent, child


def _coerce_line_items(raw) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:25]:  # hard cap — invoices over 25 lines are abnormal
        if not isinstance(item, dict):
            continue
        desc = item.get("description")
        amt = _coerce_amount_cents(item.get("amount_cents"))
        if isinstance(desc, str) and desc.strip():
            out.append({
                "description": desc.strip()[:200],
                "amount_cents": amt,
            })
    return out


def classify_invoice_v2(
    sender: Optional[str],
    subject: Optional[str],
    body: Optional[str],
    *,
    model: str = _DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return a dict with v2 classification fields.

    Workflow:
      1. Try the deterministic vendor-pattern table. On a hit, set
         confidence to 0.95 and skip the LLM (free + instant + auditable).
      2. Otherwise call the LLM with the v2 prompt.
      3. Coerce output, validate taxonomy, and degrade to the fallback
         dict on any failure (parse / network / schema).

    Always returns a dict shaped like ``_EMPTY_V2``. Never raises.
    """
    # ---- Pattern shortcut ---------------------------------------------------
    pat = match_vendor_pattern(sender, subject, body)
    if pat is not None:
        parent, child = _validate_taxonomy(pat.get("parent"), pat.get("child"))
        out = dict(_EMPTY_V2)
        out.update({
            "vendor": pat.get("vendor"),
            "parent_category": parent,
            "child_category": child,
            "category": parent,
            "confidence": 0.95,
            "reason": f"Matched vendor pattern '{pat.get('pattern')}'.",
            "source": "pattern",
            "vendor_pattern_id": pat.get("id"),
        })
        if pat.get("id"):
            record_pattern_hit(pat["id"])
        # We still want amount + date — patterns don't carry them. Best-
        # effort: try LLM if we have a key, otherwise return without
        # numbers (regex parser in invoice_ingest.py usually fills these).
        # Rather than burn an LLM call on every known vendor, leave them
        # to the caller's regex pass — patterns are about category, not
        # amounts.
        return out

    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return dict(_EMPTY_V2)

    user_prompt = (
        f"Sender: {sender or ''}\n"
        f"Subject: {subject or ''}\n\n"
        f"Body excerpt:\n{_truncate(body, _BODY_CHAR_CAP)}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT_V2},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 600,
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
                    "X-Title": "Datasnoop invoice-classifier-v2",
                },
                json=payload,
            )
        if resp.status_code != 200:
            log.warning("classify_invoice_v2: HTTP %s — %s", resp.status_code, resp.text[:180])
            return dict(_EMPTY_V2)
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = json.loads(content)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else {}
        if not isinstance(parsed, dict):
            return dict(_EMPTY_V2)

        vendor = parsed.get("vendor")
        if isinstance(vendor, str):
            vendor = vendor.strip()[:80] or None
        else:
            vendor = None

        parent, child = _validate_taxonomy(
            parsed.get("parent_category"), parsed.get("child_category")
        )

        try:
            confidence = float(parsed.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        reason = parsed.get("reason")
        if not isinstance(reason, str):
            reason = None
        else:
            reason = reason.strip()[:300] or None

        amount_cents = _coerce_amount_cents(parsed.get("amount_cents"))
        invoice_date = _coerce_invoice_date(parsed.get("invoice_date"))

        currency = parsed.get("currency")
        if isinstance(currency, str):
            currency = currency.strip().upper()[:3] or None
            if currency and not re.fullmatch(r"[A-Z]{3}", currency):
                currency = None
        else:
            currency = None

        line_items = _coerce_line_items(parsed.get("line_items"))

        return {
            "vendor": vendor,
            "parent_category": parent,
            "child_category": child,
            "category": parent,
            "confidence": confidence,
            "reason": reason,
            "amount_cents": amount_cents,
            "invoice_date": invoice_date,
            "currency": currency,
            "line_items": line_items,
            "source": "llm",
            "vendor_pattern_id": None,
            "model": model,
        }
    except Exception as e:
        log.warning("classify_invoice_v2: %s", e)
        return dict(_EMPTY_V2)


# ---------------------------------------------------------------------------
# v1 compatibility shim — keeps existing call-sites working.
# ---------------------------------------------------------------------------

# Public legacy alias kept for backwards compatibility with code that
# imports the original 9-element flat list (e.g. older admin routes /
# tests). New code should reference TAXONOMY / PARENT_CATEGORIES.
CATEGORIES: list[str] = list(TAXONOMY.keys())


def classify_invoice(
    sender: Optional[str],
    subject: Optional[str],
    body: Optional[str],
    *,
    model: str = _DEFAULT_MODEL,
    timeout: float = 30.0,
) -> dict:
    """Legacy entry point — returns the v1 5-field dict.

    Internally calls :func:`classify_invoice_v2` and downcasts. The v1
    "category" maps to the v2 parent category — same labels.
    """
    v2 = classify_invoice_v2(sender, subject, body, model=model, timeout=timeout)
    return {
        "vendor": v2.get("vendor"),
        "category": v2.get("parent_category") or "Other",
        "amount_cents": v2.get("amount_cents"),
        "invoice_date": v2.get("invoice_date"),
        "currency": v2.get("currency"),
    }


def seed_default_patterns() -> int:
    """Insert the hardcoded fallback patterns into invoice_vendor_pattern
    if the table is empty. Returns the number of rows inserted.

    Called at boot from db.ensure_phase22_schema so a fresh deploy has a
    starter set without operator input after migrations create the table.
    """
    try:
        from db import fetch_one, execute
        existing = fetch_one(
            "SELECT COUNT(*) AS n FROM invoice_vendor_pattern"
        )
        if existing and int(existing.get("n", 0)) > 0:
            return 0
        n = 0
        for p in _FALLBACK_PATTERNS:
            execute(
                """
                INSERT INTO invoice_vendor_pattern
                    (pattern, vendor_canonical, parent_category, child_category,
                     priority, created_by)
                VALUES (%s, %s, %s, %s, %s, 'system')
                """,
                (
                    p["pattern"], p["vendor"],
                    p["parent"], p["child"],
                    100,  # default seed priority
                ),
            )
            n += 1
        return n
    except Exception:
        log.exception("seed_default_patterns failed (non-fatal)")
        return 0
