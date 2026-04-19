"""Changes router — "what changed since your last visit" for a company.

Every time an authenticated user loads a company profile, the frontend posts
to `/api/changes/{cbe}/view`. We upsert `company_view_history`, shifting
the previous `last_viewed_at` into `prev_viewed_at`. On the next visit the
frontend asks `/api/changes/{cbe}/since` which returns anything new
(NBB filings, Staatsblad publications, administrator / shareholder
additions) between `prev_viewed_at` and now.

Anonymous users are NOT tracked — no per-IP view history (privacy +
storage bloat). The endpoints gracefully no-op / return empty for them.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from db import fetch_all, fetch_one, execute
from auth import optional_user
from serializers import serialize_row as _serialize  # noqa: F401 (kept for future use)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/changes", tags=["changes"])


@router.post("/{cbe}/view")
async def record_view(cbe: str, user=Depends(optional_user)):
    """Record that the current user has viewed this company. Idempotent.

    Shifts any existing last_viewed_at into prev_viewed_at so the NEXT
    "since last visit" diff uses this visit as baseline.
    """
    if not user:
        # Anonymous — skip tracking, pretend it worked
        return {"status": "anonymous"}
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        execute(
            """
            INSERT INTO company_view_history
                (user_email, enterprise_number, last_viewed_at, prev_viewed_at)
            VALUES (%s, %s, NOW(), NULL)
            ON CONFLICT (user_email, enterprise_number)
            DO UPDATE SET
                prev_viewed_at = company_view_history.last_viewed_at,
                last_viewed_at = NOW()
            """,
            (user["email"], cbe),
        )
        return {"status": "recorded"}
    except Exception as e:
        logger.exception("record_view failed")
        raise HTTPException(500, "Internal server error")


@router.get("/{cbe}/since")
async def changes_since(cbe: str, user=Depends(optional_user)):
    """Return what's changed on this company since the user's prev visit.

    If the user has no prior view record, returns {since: null, changes: []}
    so the frontend can render a friendly "first visit" state instead of
    flooding with historical noise. If user is anonymous, same.
    """
    if not user:
        return {"since": None, "changes": []}
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        rec = fetch_one(
            """SELECT prev_viewed_at, last_viewed_at
               FROM company_view_history
               WHERE user_email = %s AND enterprise_number = %s""",
            (user["email"], cbe),
        )
        if not rec or not rec.get("prev_viewed_at"):
            return {"since": None, "changes": []}

        since = rec["prev_viewed_at"]
        # Convert to ISO string once so TEXT columns can compare lexically
        # (all date/timestamp columns in nbb_load_log / staatsblad / admin
        # are TEXT in the live schema — ISO strings sort correctly).
        since_iso = since.isoformat() if hasattr(since, "isoformat") else str(since)
        changes: list[dict] = []

        # New NBB filings since last visit. loaded_at is TEXT, ISO-format.
        filings = fetch_all(
            """SELECT deposit_key, rubric_count, loaded_at
               FROM nbb_load_log
               WHERE enterprise_number = %s
                 AND loaded_at > %s
                 AND deposit_key NOT IN ('NO_FILINGS', 'PDF_ONLY')
               ORDER BY loaded_at DESC
               LIMIT 5""",
            (cbe, since_iso),
        )
        for f in filings:
            at_val = f.get("loaded_at")
            at_str = at_val.isoformat() if hasattr(at_val, "isoformat") else (str(at_val) if at_val else None)
            changes.append({
                "type": "filing",
                "at": at_str,
                "label": f"New NBB filing loaded ({f.get('rubric_count') or 0} rubrics)",
                "meta": {"deposit_key": f.get("deposit_key")},
            })

        # New Staatsblad publications — columns are pub_date (TEXT YYYY-MM-DD),
        # pub_type, reference, entity_name.
        pubs = fetch_all(
            """SELECT reference, pub_date, pub_type, entity_name
               FROM staatsblad_publication
               WHERE enterprise_number = %s
                 AND reference != 'NO_DATA'
                 AND pub_date > %s
               ORDER BY pub_date DESC
               LIMIT 10""",
            (cbe, since_iso[:10]),   # YYYY-MM-DD slice for date comparison
        )
        for p in pubs:
            changes.append({
                "type": "publication",
                "at": p.get("pub_date"),
                "label": p.get("pub_type") or p.get("entity_name") or "Staatsblad publication",
                "meta": {"reference": p.get("reference")},
            })

        # Administrator changes — columns are name, role, mandate_start (TEXT),
        # mandate_end, identifier, person_type. mandate_start is a rough proxy
        # for "new admin appeared" — not perfect but it's the only date column.
        admins = fetch_all(
            """SELECT DISTINCT name, role, mandate_start, identifier
               FROM administrator
               WHERE enterprise_number = %s
                 AND mandate_start IS NOT NULL
                 AND mandate_start > %s
               ORDER BY mandate_start DESC
               LIMIT 10""",
            (cbe, since_iso[:10]),
        )
        for a in admins:
            changes.append({
                "type": "administrator",
                "at": a.get("mandate_start"),
                "label": f"New {a.get('role') or 'administrator'}: {a.get('name') or '—'}",
                "meta": {"identifier": a.get("identifier")},
            })

        # Sort by date desc so most recent surfaces first
        changes.sort(key=lambda c: c.get("at") or "", reverse=True)

        return {
            "since": since.isoformat(),
            "last_viewed": rec["last_viewed_at"].isoformat() if rec.get("last_viewed_at") else None,
            "changes": changes,
        }
    except Exception as e:
        logger.exception("changes_since failed")
        raise HTTPException(500, "Internal server error")
