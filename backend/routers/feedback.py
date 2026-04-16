"""Feedback router — bug reports and feature suggestions."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    role_row = fetch_one(
        "SELECT role FROM user_roles WHERE email = %s",
        (email,),
    )
    if not role_row or role_row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


class FeedbackCreate(BaseModel):
    type: str  # "bug" or "suggestion"
    page: Optional[str] = None
    description: str = Field(..., max_length=5000)
    user_email: Optional[str] = None


@router.post("")
async def submit_feedback(body: FeedbackCreate, user=Depends(optional_user)):
    """Submit a bug report or feature suggestion."""
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")
    if body.type not in ("bug", "suggestion"):
        raise HTTPException(status_code=400, detail="Type must be 'bug' or 'suggestion'")

    # Use authenticated email if available, fall back to body-provided email
    email = (user.get("email") if user else None) or body.user_email

    try:
        execute(
            """INSERT INTO feedback (type, page, description, user_email, created_at)
               VALUES (%s, %s, %s, %s, NOW())""",
            (body.type, body.page, body.description.strip(), email),
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to submit feedback: %s", e)
        raise HTTPException(status_code=500, detail="Failed to submit feedback")


@router.get("")
async def list_feedback(user=Depends(_require_admin)):
    """List all feedback (for admin review)."""
    try:
        rows = fetch_all(
            """SELECT id, type, page, description, user_email, created_at
               FROM feedback ORDER BY created_at DESC LIMIT 100"""
        )
        return rows
    except Exception as e:
        logger.error("Failed to list feedback: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
