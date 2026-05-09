from __future__ import annotations

import hashlib
import hmac
import json
import os
from email.utils import parseaddr

from bs4 import BeautifulSoup
from fastapi import APIRouter, Header, HTTPException, Request

from ..db import one, transaction
from ..services import derive_title, enqueue_ai_if_allowed


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(raw: bytes, signature: str | None) -> None:
    secret = os.getenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET", "")
    allow_unsigned = os.getenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
    if not secret:
        if allow_unsigned:
            return
        raise HTTPException(status_code=500, detail="Postmark webhook secret is not configured")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing Postmark signature")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=401, detail="Invalid Postmark signature")


def _html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text("\n", strip=True)


def _postmark_envelope(payload: dict) -> dict:
    to_address = ""
    recipients = payload.get("Recipients") or []
    if recipients and isinstance(recipients[0], str):
        to_address = recipients[0]
    if not to_address:
        to_address = payload.get("OriginalRecipient") or payload.get("To") or ""
    sender = payload.get("From") or payload.get("FromFull", {}).get("Email") or ""
    text = payload.get("TextBody") or _html_to_text(payload.get("HtmlBody"))
    return {
        "provider": "postmark",
        "message_id": payload.get("MessageID") or payload.get("MessageId"),
        "rfc_message_id": payload.get("Headers", [{}])[0].get("Message-ID") if isinstance(payload.get("Headers"), list) and payload.get("Headers") else None,
        "recipient": parseaddr(to_address)[1].lower(),
        "sender": parseaddr(sender)[1].lower() or sender,
        "subject": payload.get("Subject") or "(no subject)",
        "body": text or "",
        "raw": payload,
    }


def _mailgun_envelope(payload: dict) -> dict:
    return {
        "provider": "mailgun",
        "message_id": payload.get("Message-Id") or payload.get("message-id") or payload.get("token"),
        "rfc_message_id": payload.get("Message-Id") or payload.get("message-id"),
        "recipient": parseaddr(payload.get("recipient") or payload.get("To") or "")[1].lower(),
        "sender": parseaddr(payload.get("sender") or payload.get("From") or "")[1].lower(),
        "subject": payload.get("subject") or payload.get("Subject") or "(no subject)",
        "body": payload.get("stripped-text") or payload.get("body-plain") or _html_to_text(payload.get("body-html")),
        "raw": payload,
    }


@router.post("/email/inbound")
async def inbound_email(
    request: Request,
    x_postmark_signature: str | None = Header(default=None),
    x_notesnoop_provider: str | None = Header(default=None),
):
    raw = await request.body()
    provider = (x_notesnoop_provider or "postmark").lower()
    if provider == "postmark":
        _verify_signature(raw, x_postmark_signature)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    envelope = _mailgun_envelope(payload) if provider == "mailgun" else _postmark_envelope(payload)
    if not envelope["message_id"]:
        raise HTTPException(status_code=400, detail="Provider message id is required")

    with transaction(provider_webhook=True) as cur:
        cur.execute(
            """
            INSERT INTO inbound_email_log (message_id, rfc_message_id, recipient_address, outcome)
            VALUES (%s, %s, %s, 'error')
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
            """,
            (envelope["message_id"], envelope["rfc_message_id"], envelope["recipient"]),
        )
        if cur.fetchone() is None:
            return {"data": {"duplicate": True}}

        recipient = one(
            cur,
            "SELECT * FROM inbound_email_addresses WHERE lower(address) = lower(%s)",
            (envelope["recipient"],),
        )
        if not recipient:
            cur.execute(
                "UPDATE inbound_email_log SET outcome = 'no_recipient_match' WHERE message_id = %s",
                (envelope["message_id"],),
            )
            return {"data": {"outcome": "no_recipient_match"}}

        user_id = recipient["clerk_user_id"]
        cur.execute("SET LOCAL notesnoop.current_user_id = %s", (user_id,))
        block = one(
            cur,
            "SELECT 1 FROM email_blocks WHERE clerk_user_id = %s AND %s ILIKE sender_pattern LIMIT 1",
            (user_id, envelope["sender"]),
        )
        if block:
            cur.execute(
                "UPDATE inbound_email_log SET outcome = 'blocked_sender' WHERE message_id = %s",
                (envelope["message_id"],),
            )
            return {"data": {"outcome": "blocked_sender"}}

        membership = one(
            cur,
            """
            SELECT w.id AS workspace_id, wm.email_ai_mode, w.ai_mode
            FROM workspace_members wm
            JOIN workspaces w ON w.id = wm.workspace_id
            WHERE wm.clerk_user_id = %s
            ORDER BY wm.joined_at
            LIMIT 1
            """,
            (user_id,),
        )
        if not membership:
            cur.execute(
                "UPDATE inbound_email_log SET outcome = 'no_recipient_match' WHERE message_id = %s",
                (envelope["message_id"],),
            )
            return {"data": {"outcome": "no_workspace"}}

        inbox = one(
            cur,
            """
            SELECT id, ai_mode
            FROM projects
            WHERE workspace_id = %s
              AND kind = 'inbox'
              AND (shared = TRUE OR created_by = %s)
            ORDER BY shared ASC, created_at
            LIMIT 1
            """,
            (membership["workspace_id"], user_id),
        )
        if not inbox:
            raise HTTPException(status_code=500, detail="Inbox project is missing")
        body = envelope["body"] or "(empty email)"
        title, derived = derive_title(body, envelope["subject"])
        metadata = {
            "provider": envelope["provider"],
            "message_id": envelope["message_id"],
            "sender": envelope["sender"],
            "subject": envelope["subject"],
        }
        cur.execute(
            """
            INSERT INTO notes (workspace_id, title, title_is_derived, body, raw_email_metadata, created_by)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (membership["workspace_id"], title, derived, body, json.dumps(metadata), user_id),
        )
        note_id = str(cur.fetchone()["id"])
        cur.execute(
            "INSERT INTO note_projects (note_id, project_id, linked_by) VALUES (%s, %s, %s)",
            (note_id, inbox["id"], user_id),
        )
        cur.execute(
            "UPDATE inbound_email_log SET outcome = 'saved', note_id = %s WHERE message_id = %s",
            (note_id, envelope["message_id"]),
        )
        if membership["email_ai_mode"] == "auto" and membership["ai_mode"] == "on" and inbox["ai_mode"] == "on":
            enqueue_ai_if_allowed(cur, str(membership["workspace_id"]), note_id, user_id, [str(inbox["id"])])
        return {"data": {"outcome": "saved", "note_id": note_id}}
