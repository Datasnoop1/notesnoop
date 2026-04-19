"""Tier classification + escalation-decision helpers for the bulk enrichment
worker.

Two related questions the worker asks per company:

1. **Priority / tier.** Which enrichment bucket does this CBE belong to?
   Tier-1 big (revenue ≥ €50M) always runs first and always escalates to
   Haiku; tier-2 and tier-3 are Q2-only unless structural flags fire.

2. **Should we escalate to Haiku 4.5?** The matrix verdict (Spike 2 §6)
   is that GPT-4o-mini's `confidence` field alone is a poor gate — it
   fires on web-fetch failures (obvious) and stays silent on confidently-
   wrong entity collisions (the case where a human would want a second
   pass). Production combines it with structural signals: tier-1 big +
   KBO notes warning + low confidence.

Thresholds live here as module constants so the admin UI can tune them
later without a deploy. For Phase 1 they are fixed.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Tier revenue bands (EUR). Aligned with Spike 1 §5.
TIER1_REVENUE_FLOOR = 50_000_000
TIER2_REVENUE_FLOOR = 5_000_000
TIER3_REVENUE_FLOOR = 500_000

# Priority values written to `enrichment_job.priority`. Higher = sooner.
PRIORITY_TIER1 = 100
PRIORITY_TIER2 = 50
PRIORITY_TIER3_WEB = 20
PRIORITY_TIER3_NOWEB = 10
PRIORITY_TEMPLATE = 5

# Juridical-situation codes that skip the LLM entirely (dissolved / in-
# liquidation / struck off). Source: Spike 1 §4 finding 1.
DISSOLVED_SITUATION_CODES = frozenset({"010", "012", "013", "014"})


def classify_tier(revenue_eur: Optional[float], fte: Optional[float]) -> str:
    """Return one of {`tier1`, `tier2`, `tier3`, `template`}.

    `revenue_eur` is the latest filed revenue in EUR (rubric 70). `fte`
    is the filed FTE count (rubric 9087). Either signal crossing the
    tier floor qualifies — a company with revenue <€5M but 20 FTE still
    belongs in tier-2 territory.
    """
    r = float(revenue_eur or 0)
    f = float(fte or 0)

    if r >= TIER1_REVENUE_FLOOR:
        return "tier1"
    if r >= TIER2_REVENUE_FLOOR or f >= 10:
        return "tier2"
    if r >= TIER3_REVENUE_FLOOR or f >= 1:
        return "tier3"
    return "template"


def priority_for_tier(tier: str, has_website: bool) -> int:
    """Map a tier label to the integer priority stored in the queue."""
    if tier == "tier1":
        return PRIORITY_TIER1
    if tier == "tier2":
        return PRIORITY_TIER2
    if tier == "tier3":
        return PRIORITY_TIER3_WEB if has_website else PRIORITY_TIER3_NOWEB
    return PRIORITY_TEMPLATE


def is_dormant(juridical_situation: Optional[str]) -> bool:
    """True when the KBO record marks the company as dissolved / in liquidation.

    When True the worker writes a deterministic template and skips every
    LLM call, per Spike 1 §4 finding 1 + Spike 2 §12 rollout rule 3.
    """
    if not juridical_situation:
        return False
    return juridical_situation.strip() in DISSOLVED_SITUATION_CODES


def should_escalate(
    tier: str,
    q2_confidence: Optional[str],
    kbo_notes: Optional[str] = None,
) -> tuple[bool, str]:
    """Decide whether to rerun the Q2 output through Haiku 4.5.

    Returns (should_escalate, reason). The structural triggers are the
    ones that were justified post-hoc in Spike 2 §6:
      - tier-1 big  → always escalate
      - KBO notes flagging a NACE/website mismatch → escalate
      - Q2 returned `low` or `insufficient_information` → escalate

    The `high` and `medium` bands are trusted for tier-2/3 unless a
    structural flag fires. See `plans/i-want-to-explore-delightful-
    storm.md` §Bulk enrichment pipeline step 7.
    """
    if tier == "tier1":
        return True, "tier1_big"

    if kbo_notes:
        low = kbo_notes.lower()
        if (
            "nace" in low and ("mismatch" in low or "mis-match" in low
                               or "incorrect" in low or "werkelijk" in low)
        ) or "website-mismatch" in low:
            return True, "kbo_nace_warning"

    conf = (q2_confidence or "").strip().lower()
    if conf in ("low", "insufficient_information", "insufficient"):
        return True, f"low_confidence:{conf}"

    return False, ""


def confidence_is_publishable(confidence: Optional[str]) -> bool:
    """The quality floor used by the search endpoint and profile page.

    `high` and `medium` are surfaced publicly; `low` /
    `insufficient_information` are rendered as NACE templates even if
    the raw Q2 text exists. Used both by
    `backend/routers/search.py` and the (later Phase 5) on-profile
    elaboration step.
    """
    return (confidence or "").strip().lower() in ("high", "medium")
