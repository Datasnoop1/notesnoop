"""Lightweight identity endpoint used by the frontend to decide whether
to render admin-only UI (e.g. the staging blocker, admin nav links).

Kept in its own router because it doesn't belong under /api/admin/*
— that namespace requires admin and would 403 the very users whose
status we're trying to check. This one accepts any signed-in user.
"""

import logging
import os

from fastapi import APIRouter, Depends

from auth import get_current_user
from db import fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["me"])


def _staging_mode_active() -> bool:
    """True iff the backend is running with STAGING_MODE set. Kept as a
    small function so tests can monkeypatch it cleanly."""
    return os.getenv("STAGING_MODE", "").lower() in ("1", "true", "yes")


@router.get("/is-admin")
async def is_admin(user=Depends(get_current_user)):
    """Return the current user's email, admin status, and whether the
    deployment is in staging-gated mode.

    The frontend calls this to pick between the normal app shell and
    the "Staging is restricted to admins" blocker. It's allowlisted by
    the StagingGateMiddleware so non-admins can reach it without tripping
    the 403; the payload tells them why they're blocked.
    """
    email = (user or {}).get("email") if isinstance(user, dict) else None
    is_admin_flag = False
    if email:
        try:
            row = fetch_one(
                "SELECT role FROM user_roles WHERE email = %s", (email,),
            )
            is_admin_flag = bool(row and row.get("role") == "admin")
        except Exception:
            # Fail closed — don't leak admin status on a DB hiccup.
            logger.exception("is-admin role lookup failed for %s", email)
            is_admin_flag = False

    return {
        "email": email,
        "is_admin": is_admin_flag,
        "staging_mode": _staging_mode_active(),
    }
