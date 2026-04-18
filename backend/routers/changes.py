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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/changes", tags=["changes"])


def _serialize(row: dict) -> dict:
    import datetime, decimal
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


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
        raise HTTPException(500, str(e))


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
        changes: list[dict] = []

        # New NBB filings since last visit. nbb_load_log.loaded_at is TEXT
        # (legacy schema — ISO-format strings, so lexicographic sort matches
        # chronological sort). Cast to timestamp for the comparison.
        filings = fetch_all(
            """SELECT deposit_key, rubric_count, loaded_at
               FROM nbb_load_log
               WHERE enterprise_number = %s
                 AND loaded_at::timestamp > %s
                 AND deposit_key NOT IN ('NO_FILINGS', 'PDF_ONLY')
               ORDER BY loaded_at DESC
               LIMIT 5""",
            (cbe, since),
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

        # New Staatsblad publications
        pubs = fetch_all(
            """SELECT reference, publication_date, title, subject
               FROM staatsblad_publication
               WHERE enterprise_number = %s
                 AND reference != 'NO_DATA'
                 AND publication_date > %s::date
               ORDER BY publication_date DESC
               LIMIT 10""",
            (cbe, since),
        )
        for p in pubs:
            changes.append({
                "type": "publication",
                "at": p["publication_date"].isoformat() if p.get("publication_date") else None,
                "label": p.get("title") or p.get("subject") or "Staatsblad publication",
                "meta": {"reference": p.get("reference")},
            })

        # Administrator changes (track newly-added rows, rough proxy)
        admins = fetch_all(
            """SELECT DISTINCT person_id, full_name, function, start_date
               FROM administrator
               WHERE enterprise_number = %s
                 AND start_date > %s::date
               ORDER BY start_date DESC
               LIMIT 10""",
            (cbe, since),
        )
        for a in admins:
            changes.append({
                "type": "administrator",
                "at": a["start_date"].isoformat() if a.get("start_date") else None,
                "label": f"New {a.get('function') or 'administrator'}: {a.get('full_name') or '—'}",
                "meta": {"person_id": a.get("person_id")},
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
        raise HTTPException(500, str(e))
