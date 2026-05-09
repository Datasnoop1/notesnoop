from __future__ import annotations

import json
from email.utils import parseaddr

from bs4 import BeautifulSoup

from .db import one
from .services import derive_title, enqueue_ai_if_allowed


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text("\n", strip=True)


def header_value(headers: list[dict] | None, name: str) -> str | None:
    if not isinstance(headers, list):
        return None
    for header in headers:
        if str(header.get("Name") or header.get("name") or "").lower() == name.lower():
            return header.get("Value") or header.get("value")
    return None


def postmark_envelope(payload: dict) -> dict:
    to_address = payload.get("OriginalRecipient") or ""
    if not to_address and isinstance(payload.get("ToFull"), list) and payload["ToFull"]:
        to_address = payload["ToFull"][0].get("Email") or ""
    if not to_address:
        to_address = payload.get("To") or ""
    sender = payload.get("From") or payload.get("FromFull", {}).get("Email") or ""
    text = payload.get("StrippedTextReply") or payload.get("TextBody") or html_to_text(payload.get("HtmlBody"))
    return {
        "provider": "postmark",
        "message_id": payload.get("MessageID") or payload.get("MessageId"),
        "rfc_message_id": header_value(payload.get("Headers"), "Message-ID"),
        "recipient": parseaddr(to_address)[1].lower(),
        "sender": parseaddr(sender)[1].lower() or sender,
        "subject": payload.get("Subject") or "(no subject)",
        "body": text or "",
        "raw": payload,
    }


def mailgun_envelope(payload: dict) -> dict:
    return {
        "provider": "mailgun",
        "message_id": payload.get("Message-Id") or payload.get("message-id") or payload.get("token"),
        "rfc_message_id": payload.get("Message-Id") or payload.get("message-id"),
        "recipient": parseaddr(payload.get("recipient") or payload.get("To") or "")[1].lower(),
        "sender": parseaddr(payload.get("sender") or payload.get("From") or "")[1].lower(),
        "subject": payload.get("subject") or payload.get("Subject") or "(no subject)",
        "body": payload.get("stripped-text") or payload.get("body-plain") or html_to_text(payload.get("body-html")),
        "raw": payload,
    }


def save_inbound_envelope(cur, envelope: dict) -> dict:
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
        return {"duplicate": True}

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
        return {"outcome": "no_recipient_match"}

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
        return {"outcome": "blocked_sender"}

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
        return {"outcome": "no_workspace"}

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
        raise RuntimeError("Inbox project is missing")

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
        INSERT INTO notes (workspace_id, title, title_is_derived, body, raw_email_metadata, note_kind, occurred_at, created_by)
        VALUES (%s, %s, %s, %s, %s::jsonb, 'email', now(), %s)
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
    else:
        cur.execute("UPDATE notes SET ai_processing_status = 'skipped' WHERE id = %s", (note_id,))
    return {"outcome": "saved", "note_id": note_id}
