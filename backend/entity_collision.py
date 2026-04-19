"""Sector-plausibility check — catches entity-collision hallucinations
where the discovery layer picked a same-named but wrong company.

Spike 3 §4.3 / Phase 0 finding: DuckDuckGo + Q2 confidently produced
`{confidence: high}` summaries of `axis.com` (the Swedish camera
company) for AXIS Belgium — a NACE-81220 building-cleaning SME. Q2's
own confidence field doesn't detect this class of error because the
description is internally consistent; it's just about the wrong entity.

Cheap cross-check: feed the Q2 output back plus the KBO NACE
description + HQ city and ask GPT-4o-mini whether the described
company could plausibly match the KBO record. Costs ~$0.00005/call.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

COLLISION_MODEL = "openai/gpt-4o-mini"


def _short(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    t = text.strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


async def check_entity_collision(
    *,
    company_name: str,
    kbo_nace_description: Optional[str],
    kbo_hq_city: Optional[str],
    q2_summary: dict,
) -> dict:
    """Ask GPT-4o-mini whether `q2_summary` plausibly describes the KBO entity.

    Returns a dict:
        `{plausible: bool, reason: str, confidence: str}`.

    `confidence` here is the model's own self-reported confidence in the
    plausibility verdict (not to be confused with Q2's `bulk_confidence`).
    Failures fall back to `{plausible: True, reason: "check_failed"}` so a
    transient LLM error doesn't downgrade every row on the floor.
    """
    desc = _short(q2_summary.get("business_description"))
    products = _short(
        ", ".join(q2_summary.get("products_services") or []),
        limit=200,
    )
    segments = _short(
        ", ".join(q2_summary.get("customer_segments") or []),
        limit=200,
    )
    nace_desc = _short(kbo_nace_description or "(unknown)")
    hq = _short(kbo_hq_city or "(unknown)")

    if not desc:
        return {"plausible": True, "reason": "no_q2_text", "confidence": "low"}

    prompt = (
        "You are validating whether an AI-generated business summary "
        "plausibly matches the Belgian KBO (official company register) "
        "record for a company. Return one JSON object — no prose.\n\n"
        f"Company name (KBO): {company_name}\n"
        f"KBO primary NACE description: {nace_desc}\n"
        f"KBO registered HQ city: {hq}\n\n"
        "AI-generated summary (from a scraped website):\n"
        f"- Business description: {desc}\n"
        f"- Products/services: {products}\n"
        f"- Customer segments: {segments}\n\n"
        "Does the summary plausibly describe the SAME entity as the KBO "
        "record? Rules:\n"
        "- If the sector in the summary is materially unrelated to the "
        "KBO NACE description (e.g. KBO says 'building cleaning', summary "
        "describes 'IP camera manufacturing'), return plausible=false.\n"
        "- Small NACE mismatches (e.g. wholesale vs retail of the same "
        "product) are NOT a collision — return plausible=true.\n"
        "- If the summary geography contradicts HQ city but sector is "
        "consistent (Belgian HQ + Belgian operations), plausible=true.\n"
        "- Return plausible=true when you cannot tell — false positives "
        "are more harmful than missing a real collision.\n\n"
        'Respond with ONLY: {"plausible": bool, "reason": "<short>",'
        ' "confidence": "high|medium|low"}'
    )

    system = (
        "You return strict JSON matching the user's schema. One line, "
        "double-quoted keys, no markdown."
    )

    try:
        from ai_client import ai_complete_with_meta

        meta = await ai_complete_with_meta(
            prompt=prompt,
            system=system,
            model=COLLISION_MODEL,
            max_tokens=200,
            temperature=0.0,
            timeout_s=20.0,
        )
        if not meta.get("ok"):
            return {
                "plausible": True,
                "reason": f"check_failed:{meta.get('error')}",
                "confidence": "low",
            }
        text = (meta.get("text") or "").strip()
        # Tolerate fenced code blocks if the model ignored the rule.
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        parsed = json.loads(text)
        plausible = bool(parsed.get("plausible", True))
        return {
            "plausible": plausible,
            "reason": str(parsed.get("reason") or ""),
            "confidence": str(parsed.get("confidence") or "low"),
        }
    except json.JSONDecodeError:
        logger.warning("entity-collision check: unparseable JSON response")
        return {"plausible": True, "reason": "parse_failed", "confidence": "low"}
    except Exception as e:
        logger.warning("entity-collision check failed: %s", e)
        return {"plausible": True, "reason": "exception", "confidence": "low"}
