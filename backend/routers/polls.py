"""Polls router — admin creates polls, users vote, results in admin panel."""

import json
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/polls", tags=["polls"])


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    role_row = fetch_one(
        "SELECT role FROM user_roles WHERE email = %s",
        (email,),
    )
    if not role_row or role_row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class PollCreate(BaseModel):
    title: str
    question: str
    options: List[str]


class VoteBody(BaseModel):
    choice: str


def _serialize(row: dict) -> dict:
    import datetime, decimal
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = str(v)
        elif isinstance(v, decimal.Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# --- Public endpoints ---

@router.get("/active")
async def get_active_poll():
    """Get the currently active poll (if any)."""
    poll = fetch_one(
        "SELECT id, title, question, options FROM poll WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
    )
    if not poll:
        return None
    poll["options"] = poll["options"] if isinstance(poll["options"], list) else json.loads(poll["options"])
    return _serialize(poll)


@router.post("/{poll_id}/vote")
async def vote(poll_id: int, body: VoteBody, user=Depends(optional_user)):
    """Submit a vote for a poll."""
    poll = fetch_one("SELECT id, options, status FROM poll WHERE id = %s", (poll_id,))
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    if poll["status"] != "active":
        raise HTTPException(status_code=400, detail="Poll is no longer active")

    options = poll["options"] if isinstance(poll["options"], list) else json.loads(poll["options"])
    if body.choice not in options:
        raise HTTPException(status_code=400, detail=f"Invalid choice. Options: {options}")

    email = user["email"] if user else None

    # Check if already voted
    if email:
        existing = fetch_one(
            "SELECT id FROM poll_response WHERE poll_id = %s AND user_email = %s",
            (poll_id, email),
        )
        if existing:
            raise HTTPException(status_code=409, detail="Already voted")

    execute(
        "INSERT INTO poll_response (poll_id, choice, user_email) VALUES (%s, %s, %s)",
        (poll_id, body.choice, email),
    )
    return {"status": "voted", "choice": body.choice}


# --- Admin endpoints ---

@router.get("")
async def list_polls(user=Depends(get_current_user)):
    """List all polls (active + archived) with vote counts."""
    polls = fetch_all("""
        SELECT p.id, p.title, p.question, p.options, p.status, p.created_at, p.archived_at,
               (SELECT COUNT(*) FROM poll_response pr WHERE pr.poll_id = p.id) AS total_votes
        FROM poll p
        ORDER BY p.created_at DESC
    """)
    for p in polls:
        p["options"] = p["options"] if isinstance(p["options"], list) else json.loads(p["options"])
        # Get vote breakdown
        votes = fetch_all(
            "SELECT choice, COUNT(*) AS count FROM poll_response WHERE poll_id = %s GROUP BY choice",
            (p["id"],),
        )
        p["votes"] = {v["choice"]: v["count"] for v in votes}
    return [_serialize(p) for p in polls]


@router.post("")
async def create_poll(body: PollCreate, user=Depends(_require_admin)):
    """Create a new poll. Automatically archives any currently active poll."""
    if len(body.options) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 options")

    # Archive any active polls
    execute("UPDATE poll SET status = 'archived', archived_at = NOW() WHERE status = 'active'")

    execute(
        "INSERT INTO poll (title, question, options) VALUES (%s, %s, %s)",
        (body.title, body.question, json.dumps(body.options)),
    )
    return {"status": "created", "title": body.title}


class AddOptionsBody(BaseModel):
    options: list[str]


@router.post("/{poll_id}/add-options")
async def add_poll_options(poll_id: int, body: AddOptionsBody, user=Depends(_require_admin)):
    """Add new options to an existing poll."""
    if not body.options:
        raise HTTPException(status_code=400, detail="No options provided")

    try:
        poll = fetch_one("SELECT options FROM poll WHERE id = %s", (poll_id,))
        if not poll:
            raise HTTPException(status_code=404, detail="Poll not found")

        existing = json.loads(poll["options"]) if isinstance(poll["options"], str) else poll["options"]
        new_options = [o for o in body.options if o not in existing]
        if not new_options:
            return {"status": "no_change", "message": "All options already exist"}

        updated = existing + new_options
        execute("UPDATE poll SET options = %s WHERE id = %s", (json.dumps(updated), poll_id))
        return {"status": "updated", "added": new_options, "total_options": len(updated)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Add poll options failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{poll_id}/archive")
async def archive_poll(poll_id: int, user=Depends(_require_admin)):
    """Archive a poll (keeps all data, just hides from users)."""
    execute(
        "UPDATE poll SET status = 'archived', archived_at = NOW() WHERE id = %s",
        (poll_id,),
    )
    return {"status": "archived", "poll_id": poll_id}


@router.post("/{poll_id}/activate")
async def activate_poll(poll_id: int, user=Depends(_require_admin)):
    """Re-activate an archived poll. Archives any currently active poll first."""
    execute("UPDATE poll SET status = 'archived', archived_at = NOW() WHERE status = 'active'")
    execute(
        "UPDATE poll SET status = 'active', archived_at = NULL WHERE id = %s",
        (poll_id,),
    )
    return {"status": "activated", "poll_id": poll_id}
