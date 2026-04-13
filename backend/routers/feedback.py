"""Feedback router — bug reports and feature suggestions."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import fetch_all, execute

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackCreate(BaseModel):
    type: str  # "bug" or "suggestion"
    page: Optional[str] = None
    description: str
    user_email: Optional[str] = None


@router.post("")
async def submit_feedback(body: FeedbackCreate):
    """Submit a bug report or feature suggestion."""
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")
    if body.type not in ("bug", "suggestion"):
        raise HTTPException(status_code=400, detail="Type must be 'bug' or 'suggestion'")

    try:
        execute(
            """INSERT INTO feedback (type, page, description, user_email, created_at)
               VALUES (%s, %s, %s, %s, NOW())""",
            (body.type, body.page, body.description.strip(), body.user_email),
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to submit feedback: %s", e)
        raise HTTPException(status_code=500, detail="Failed to submit feedback")


@router.get("")
async def list_feedback():
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
