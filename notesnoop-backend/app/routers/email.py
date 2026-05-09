from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import many, one, transaction
from ..email_ingest import save_inbound_envelope
from ..schemas import EmailBlockRequest
from ..services import inbound_address_for


router = APIRouter(prefix="/api", tags=["email"])


@router.get("/email-blocks")
def list_email_blocks(user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        return {
            "data": many(
                cur,
                """
                SELECT sender_pattern, blocked_at
                FROM email_blocks
                WHERE clerk_user_id = %s
                ORDER BY blocked_at DESC
                """,
                (user.clerk_user_id,),
            )
        }


@router.post("/email-blocks")
def block_sender(payload: EmailBlockRequest, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        sender_pattern = (payload.sender_pattern or "").strip().lower()
        note = None
        if payload.note_id:
            note = one(cur, "SELECT id, raw_email_metadata FROM notes WHERE id = %s", (payload.note_id,))
            if not note:
                raise HTTPException(status_code=404, detail="Email note not found")
            metadata = note.get("raw_email_metadata") or {}
            sender_pattern = sender_pattern or str(metadata.get("sender") or "").lower()
        if not sender_pattern:
            raise HTTPException(status_code=422, detail="Sender is required")
        cur.execute(
            """
            INSERT INTO email_blocks (clerk_user_id, sender_pattern)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (user.clerk_user_id, sender_pattern),
        )
        if note:
            cur.execute("DELETE FROM notes WHERE id = %s", (note["id"],))
        return {"data": {"sender_pattern": sender_pattern, "blocked": True, "deleted_note_id": payload.note_id}}


@router.delete("/email-blocks")
def unblock_sender(sender_pattern: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        cur.execute(
            "DELETE FROM email_blocks WHERE clerk_user_id = %s AND sender_pattern = %s",
            (user.clerk_user_id, sender_pattern.lower()),
        )
        return {"data": {"sender_pattern": sender_pattern, "blocked": False}}


@router.post("/workspaces/{workspace_id}/send-test-email")
def send_test_email(workspace_id: str, user: CurrentUser = Depends(current_user)):
    with transaction(user.clerk_user_id) as cur:
        workspace = one(cur, "SELECT id FROM workspaces WHERE id = %s", (workspace_id,))
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        inbound = one(
            cur,
            "SELECT address FROM inbound_email_addresses WHERE clerk_user_id = %s ORDER BY created_at LIMIT 1",
            (user.clerk_user_id,),
        )
        recipient = inbound["address"] if inbound else inbound_address_for(user.clerk_user_id)
        envelope = {
            "provider": "notesnoop-test",
            "message_id": f"test-{uuid.uuid4()}",
            "rfc_message_id": None,
            "recipient": recipient,
            "sender": "test@notesnoop.app",
            "subject": "NoteSnoop test email",
            "body": "This is a test inbound email for NoteSnoop. It lands in Inbox and follows your Email AI setting.",
            "raw": {},
        }
        try:
            return {"data": save_inbound_envelope(cur, envelope)}
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
