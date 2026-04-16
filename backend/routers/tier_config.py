"""Tier configuration router — manage user tier limits from the admin panel."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/tiers", tags=["tier-config"])

_table_ensured = False


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    user_id = user.get("id", "")
    role_row = fetch_one(
        "SELECT role FROM user_roles WHERE email = %s OR email = %s",
        (email, user_id),
    )
    if not role_row or role_row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def _ensure_table():
    """Create the tier_config table and seed defaults on first access."""
    global _table_ensured
    if _table_ensured:
        return
    try:
        execute("""
            CREATE TABLE IF NOT EXISTS tier_config (
                tier VARCHAR(20) PRIMARY KEY,
                page_views_per_day INT DEFAULT -1,
                searches_per_day INT DEFAULT -1,
                company_views_per_day INT DEFAULT -1,
                ai_enrichments_per_day INT DEFAULT 0,
                export_per_day INT DEFAULT 0,
                screener_results_limit INT DEFAULT 20,
                enabled BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Seed default rows if table is empty
        existing = fetch_one("SELECT COUNT(*) AS cnt FROM tier_config")
        if not existing or existing["cnt"] == 0:
            execute("""
                INSERT INTO tier_config (tier, page_views_per_day, searches_per_day, company_views_per_day, ai_enrichments_per_day, export_per_day, screener_results_limit, enabled)
                VALUES
                    ('guest', 50, 10, 5, 0, 0, 20, FALSE),
                    ('registered', -1, -1, -1, 5, 10, 100, FALSE),
                    ('premium', -1, -1, -1, -1, -1, -1, FALSE)
                ON CONFLICT (tier) DO NOTHING
            """)
            logger.info("Seeded default tier_config rows")
        _table_ensured = True
    except Exception:
        logger.exception("Failed to ensure tier_config table")
        _table_ensured = True  # Don't retry on every request


def _serialize_row(row: dict) -> dict:
    """Serialize a tier_config row for JSON response."""
    import datetime
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime.datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_tiers(user=Depends(_require_admin)):
    """Return all tier configurations."""
    _ensure_table()
    try:
        rows = fetch_all(
            "SELECT * FROM tier_config ORDER BY CASE tier WHEN 'guest' THEN 1 WHEN 'registered' THEN 2 WHEN 'premium' THEN 3 END"
        )
        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("Get tiers failed")
        raise HTTPException(status_code=500, detail=str(e))


class TierUpdate(BaseModel):
    page_views_per_day: Optional[int] = None
    searches_per_day: Optional[int] = None
    company_views_per_day: Optional[int] = None
    ai_enrichments_per_day: Optional[int] = None
    export_per_day: Optional[int] = None
    screener_results_limit: Optional[int] = None


@router.put("/{tier}")
async def update_tier(tier: str, body: TierUpdate, user=Depends(_require_admin)):
    """Update a tier's limits (partial update — only provided fields)."""
    _ensure_table()
    if tier not in ("guest", "registered", "premium"):
        raise HTTPException(status_code=400, detail="Tier must be guest, registered, or premium")

    # Build dynamic SET clause from provided fields only
    updates = {}
    for field in ("page_views_per_day", "searches_per_day", "company_views_per_day",
                  "ai_enrichments_per_day", "export_per_day", "screener_results_limit"):
        value = getattr(body, field)
        if value is not None:
            updates[field] = value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values())
    values.append(tier)

    try:
        execute(
            f"UPDATE tier_config SET {set_clause}, updated_at = NOW() WHERE tier = %s",
            tuple(values),
        )
        row = fetch_one("SELECT * FROM tier_config WHERE tier = %s", (tier,))
        return _serialize_row(row) if row else {"status": "updated"}
    except Exception as e:
        logger.exception("Update tier failed")
        raise HTTPException(status_code=500, detail=str(e))


class ToggleBody(BaseModel):
    enabled: bool


@router.post("/toggle")
async def toggle_limits(body: ToggleBody, user=Depends(_require_admin)):
    """Master switch to enable/disable all tier limits."""
    _ensure_table()
    try:
        execute(
            "UPDATE tier_config SET enabled = %s, updated_at = NOW()",
            (body.enabled,),
        )
        return {"enabled": body.enabled, "status": "all tiers updated"}
    except Exception as e:
        logger.exception("Toggle limits failed")
        raise HTTPException(status_code=500, detail=str(e))
