"""Admin router — user management, usage stats, feedback review."""

import logging
from fastapi import APIRouter, HTTPException, Depends

from db import fetch_all, fetch_one, execute
from auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    user_id = user.get("id", "")
    logger.info("Admin check: email=%s id=%s", email, user_id)

    # Check by email or user_id
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
    """Platform stats for admin dashboard."""
    try:
        stats = fetch_one("""
            SELECT
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'enterprise') AS total_enterprises,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_latest') AS companies_with_financials,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'administrator') AS admin_records,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_data') AS financial_rows,
                (SELECT COUNT(*) FROM user_roles) AS total_users,
                (SELECT COUNT(*) FROM user_roles WHERE role = 'admin') AS admin_users,
                (SELECT COUNT(*) FROM favourite) AS total_favourites,
                (SELECT COUNT(*) FROM feedback) AS total_feedback,
                (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size
        """)
        return stats
    except Exception as e:
        logger.exception("Admin stats failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users(user=Depends(_require_admin)):
    """List all known users (from user_roles + favourites + feedback)."""
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
    """List all feedback for admin review."""
    try:
        rows = fetch_all("""
            SELECT id, type, page, description, user_email, created_at
            FROM feedback ORDER BY created_at DESC LIMIT 100
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
        return rows
    except Exception as e:
        logger.exception("List feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{email}/role")
async def set_user_role(email: str, role: str = "user", user=Depends(_require_admin)):
    """Set a user's role (admin/user)."""
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")
    try:
        execute(
            """INSERT INTO user_roles (email, role) VALUES (%s, %s)
               ON CONFLICT (email) DO UPDATE SET role = %s""",
            (email, role, role),
        )
        return {"email": email, "role": role}
    except Exception as e:
        logger.exception("Set role failed")
        raise HTTPException(status_code=500, detail=str(e))
