"""Admin router — user management, usage stats, feedback review."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from db import fetch_all, fetch_one, execute
from auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

_feedback_columns_migrated = False


def _ensure_feedback_columns():
    """Add reply and replied_at columns to feedback table if missing (migration-style)."""
    global _feedback_columns_migrated
    if _feedback_columns_migrated:
        return
    try:
        execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS reply TEXT")
        execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP")
        _feedback_columns_migrated = True
        logger.info("Feedback table columns ensured (reply, replied_at)")
    except Exception:
        logger.debug("Feedback columns already exist or migration skipped")
        _feedback_columns_migrated = True


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    user_id = user.get("id", "")
    logger.info("Admin check: email=%s id=%s", email, user_id)

    role_row = fetch_one(
        "SELECT role FROM user_roles WHERE email = %s OR email = %s",
        (email, user_id),
    )
    if not role_row or role_row["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Admin access required. Your email: {email}"
        )
    return user


@router.get("/stats")
async def admin_stats(user=Depends(_require_admin)):
    """Platform stats including data loading progress."""
    # Migrate feedback table columns if needed (adds reply + replied_at)
    _ensure_feedback_columns()

    try:
        stats = fetch_one("""
            SELECT
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'enterprise') AS total_enterprises,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_latest') AS companies_with_financials,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'administrator') AS admin_records,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_data') AS financial_rows,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'activity') AS activity_rows,
                (SELECT COUNT(*) FROM user_roles) AS total_users,
                (SELECT COUNT(*) FROM user_roles WHERE role = 'admin') AS admin_users,
                (SELECT COUNT(*) FROM user_roles WHERE role = 'blocked') AS blocked_users,
                (SELECT COUNT(*) FROM favourite) AS total_favourites,
                (SELECT COUNT(*) FROM feedback) AS total_feedback,
                (SELECT COUNT(*) FROM feedback WHERE type = 'bug') AS bug_count,
                (SELECT COUNT(*) FROM feedback WHERE type = 'suggestion') AS suggestion_count,
                (SELECT COUNT(*) FROM feedback WHERE type = 'survey') AS survey_count,
                (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '24 hours') AS daily_active_users,
                (SELECT endpoint FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND endpoint != '/api/health'
                 GROUP BY endpoint ORDER BY COUNT(*) DESC LIMIT 1) AS most_visited_page,
                (SELECT COUNT(DISTINCT enterprise_number) FROM staatsblad_publication) AS companies_with_staatsblad,

                -- Dataset coverage KPIs
                (SELECT COUNT(DISTINCT fl.enterprise_number) FROM financial_latest fl) AS companies_with_latest_financials,
                (SELECT COUNT(DISTINCT fby.enterprise_number) FROM financial_by_year fby) AS companies_with_history,
                (SELECT COUNT(DISTINCT sp.enterprise_number) FROM staatsblad_publication sp WHERE sp.reference != 'NO_DATA') AS companies_with_publications,
                (SELECT COUNT(DISTINCT a.enterprise_number) FROM administrator a) AS companies_with_admins,
                (SELECT COUNT(DISTINCT sh.enterprise_number) FROM shareholder sh) AS companies_with_shareholders,
                (SELECT COUNT(DISTINCT pi.enterprise_number) FROM participating_interest pi) AS companies_with_subsidiaries,

                -- Data completeness: companies with ALL data types loaded
                (SELECT COUNT(*) FROM (
                    SELECT ci.enterprise_number
                    FROM company_info ci
                    JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                    JOIN (SELECT DISTINCT enterprise_number FROM administrator) a ON a.enterprise_number = ci.enterprise_number
                    JOIN (SELECT DISTINCT enterprise_number FROM staatsblad_publication WHERE reference != 'NO_DATA') sp ON sp.enterprise_number = ci.enterprise_number
                ) complete) AS fully_loaded_companies,

                -- Conservative target: all active legal-person enterprises
                (SELECT COUNT(*) FROM enterprise WHERE type_of_enterprise = '1' AND status = 'AC') AS target_universe
        """)
        # Add target totals for progress bars
        stats["target_enterprises"] = 1941155
        stats["target_financial_rows"] = 61714163
        stats["target_activity_rows"] = 34874572
        stats["target_companies"] = stats.get("target_universe") or 170000  # active legal-person enterprises
        return stats
    except Exception as e:
        logger.exception("Admin stats failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/financials-by-year")
async def financials_by_year(user=Depends(_require_admin)):
    """Breakdown of companies with financials per fiscal year."""
    try:
        rows = fetch_all("""
            SELECT fiscal_year,
                   COUNT(DISTINCT enterprise_number) AS companies,
                   COUNT(*) AS filings
            FROM financial_by_year
            WHERE fiscal_year >= 2020
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
        """)
        return rows
    except Exception as e:
        logger.exception("Financials by year query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users(user=Depends(_require_admin)):
    """List all known users."""
    try:
        users = fetch_all("""
            SELECT ur.email, ur.role, ur.created_at,
                   (SELECT COUNT(*) FROM favourite f WHERE f.user_id = ur.email) AS favourites_count,
                   (SELECT COUNT(*) FROM feedback fb WHERE fb.user_email = ur.email) AS feedback_count
            FROM user_roles ur
            ORDER BY ur.created_at DESC
        """)
        for u in users:
            if u.get("created_at"):
                u["created_at"] = str(u["created_at"])
        return users
    except Exception as e:
        logger.exception("List users failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback")
async def list_feedback(user=Depends(_require_admin)):
    """List all feedback."""
    try:
        rows = fetch_all("""
            SELECT id, type, page, description, user_email, created_at, reply, replied_at
            FROM feedback ORDER BY created_at DESC LIMIT 200
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
            if r.get("replied_at"):
                r["replied_at"] = str(r["replied_at"])
        return rows
    except Exception as e:
        logger.exception("List feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


class ReplyBody(BaseModel):
    message: str


@router.post("/feedback/{feedback_id}/reply")
async def reply_feedback(feedback_id: int, body: ReplyBody, user=Depends(_require_admin)):
    """Store a reply to feedback."""
    try:
        execute(
            "UPDATE feedback SET reply = %s, replied_at = NOW() WHERE id = %s",
            (body.message, feedback_id),
        )
        return {"status": "replied"}
    except Exception as e:
        logger.exception("Reply failed")
        raise HTTPException(status_code=500, detail=str(e))


class RoleUpdate(BaseModel):
    role: str


@router.post("/users/{email}/role")
async def set_user_role(email: str, body: RoleUpdate, user=Depends(_require_admin)):
    """Set a user's role (admin/user/blocked)."""
    if body.role not in ("admin", "user", "blocked"):
        raise HTTPException(status_code=400, detail="Role must be admin, user, or blocked")
    try:
        execute(
            """INSERT INTO user_roles (email, role) VALUES (%s, %s)
               ON CONFLICT (email) DO UPDATE SET role = %s""",
            (email, body.role, body.role),
        )
        return {"email": email, "role": body.role}
    except Exception as e:
        logger.exception("Set role failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{email}")
async def delete_user(email: str, user=Depends(_require_admin)):
    """Remove a user entirely."""
    if email == user.get("email"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    try:
        execute("DELETE FROM user_roles WHERE email = %s", (email,))
        execute("DELETE FROM favourite WHERE user_id = %s", (email,))
        return {"email": email, "status": "deleted"}
    except Exception as e:
        logger.exception("Delete user failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/feedback/{feedback_id}")
async def delete_feedback(feedback_id: int, user=Depends(_require_admin)):
    """Delete a single feedback entry."""
    try:
        execute("DELETE FROM feedback WHERE id = %s", (feedback_id,))
        return {"id": feedback_id, "status": "deleted"}
    except Exception as e:
        logger.exception("Delete feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/feedback")
async def clear_feedback(user=Depends(_require_admin)):
    """Clear all feedback."""
    try:
        execute("DELETE FROM feedback")
        return {"status": "cleared"}
    except Exception as e:
        logger.exception("Clear feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity")
async def get_activity(user=Depends(_require_admin)):
    """Recent user activity across the platform."""
    try:
        rows = fetch_all("""
            SELECT user_email, endpoint, method, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 200
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
        return rows
    except Exception as e:
        logger.exception("Activity log failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity/summary")
async def activity_summary(user=Depends(_require_admin)):
    """Activity summary: requests per user in last 24h."""
    try:
        rows = fetch_all("""
            SELECT user_email,
                   COUNT(*) AS total_requests,
                   COUNT(DISTINCT endpoint) AS unique_pages,
                   MAX(created_at) AS last_active
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY user_email
            ORDER BY total_requests DESC
        """)
        for r in rows:
            if r.get("last_active"):
                r["last_active"] = str(r["last_active"])
        return rows
    except Exception as e:
        logger.exception("Activity summary failed")
        raise HTTPException(status_code=500, detail=str(e))
