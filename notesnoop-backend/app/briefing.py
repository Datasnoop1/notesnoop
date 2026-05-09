from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from psycopg2.extras import RealDictCursor

from .config import get_settings
from .db import get_conn, one, put_conn


def _safe_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _json_default(value: Any) -> str:
    return str(value)


def _unsubscribe_secret() -> bytes:
    settings = get_settings()
    secret = settings.unsubscribe_secret or settings.postmark_server_token or "notesnoop-dev-unsubscribe-secret"
    return secret.encode("utf-8")


def make_unsubscribe_token(workspace_id: str, user_id: str) -> str:
    body = json.dumps({"workspace_id": workspace_id, "user_id": user_id}, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_unsubscribe_secret(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")


def parse_unsubscribe_token(token: str) -> dict[str, str] | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(raw) < 34 or raw[-33:-32] != b".":
            return None
        body = raw[:-33]
        signature = raw[-32:]
    except Exception:
        return None
    expected = hmac.new(_unsubscribe_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if not payload.get("workspace_id") or not payload.get("user_id"):
        return None
    return {"workspace_id": str(payload["workspace_id"]), "user_id": str(payload["user_id"])}


def enqueue_due_morning_briefings(now: datetime | None = None) -> dict[str, int]:
    settings = get_settings()
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    conn = get_conn()
    queued = 0
    considered = 0
    skipped_not_due = 0
    skipped_empty = 0
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute(
                """
                SELECT wm.workspace_id,
                       wm.clerk_user_id,
                       w.name AS workspace_name,
                       up.email,
                       up.display_name,
                       up.timezone,
                       count(rq.id) FILTER (WHERE rq.state = 'open') AS pending_count
                FROM workspace_members wm
                JOIN workspaces w ON w.id = wm.workspace_id
                JOIN user_profiles up ON up.clerk_user_id = wm.clerk_user_id
                LEFT JOIN review_queue rq ON rq.workspace_id = wm.workspace_id
                  AND rq.target_user_id = wm.clerk_user_id
                  AND rq.state = 'open'
                WHERE wm.morning_briefing_optin = TRUE
                  AND up.email IS NOT NULL
                  AND up.email <> ''
                GROUP BY wm.workspace_id, wm.clerk_user_id, w.name, up.email, up.display_name, up.timezone
                ORDER BY wm.joined_at
                """
            )
            for row in cur.fetchall():
                considered += 1
                local_now = now_utc.astimezone(_safe_zone(row.get("timezone")))
                if local_now.hour != settings.morning_briefing_hour:
                    skipped_not_due += 1
                    continue
                pending_count = int(row["pending_count"] or 0)
                if pending_count < 1:
                    skipped_empty += 1
                    continue
                local_date = local_now.date().isoformat()
                payload = {
                    "local_date": local_date,
                    "pending_count": pending_count,
                    "email": row["email"],
                    "display_name": row.get("display_name"),
                    "workspace_name": row["workspace_name"],
                    "timezone": row.get("timezone") or "UTC",
                }
                cur.execute(
                    """
                    INSERT INTO ai_jobs (workspace_id, kind, target_user_id, payload, priority, idempotency_key)
                    VALUES (%s, 'briefing', %s, %s::jsonb, 1, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id
                    """,
                    (
                        row["workspace_id"],
                        row["clerk_user_id"],
                        json.dumps(payload, default=_json_default),
                        f"briefing:{row['workspace_id']}:{row['clerk_user_id']}:{local_date}",
                    ),
                )
                if cur.fetchone():
                    queued += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
    return {
        "considered": considered,
        "queued": queued,
        "skipped_not_due": skipped_not_due,
        "skipped_empty": skipped_empty,
    }


async def send_morning_briefing(job: dict) -> dict[str, Any]:
    settings = get_settings()
    workspace_id = str(job["workspace_id"])
    user_id = str(job["target_user_id"])
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            row = one(
                cur,
                """
                SELECT wm.workspace_id,
                       wm.clerk_user_id,
                       wm.morning_briefing_optin,
                       w.name AS workspace_name,
                       up.email,
                       up.display_name,
                       count(rq.id) FILTER (WHERE rq.state = 'open') AS pending_count
                FROM workspace_members wm
                JOIN workspaces w ON w.id = wm.workspace_id
                JOIN user_profiles up ON up.clerk_user_id = wm.clerk_user_id
                LEFT JOIN review_queue rq ON rq.workspace_id = wm.workspace_id
                  AND rq.target_user_id = wm.clerk_user_id
                  AND rq.state = 'open'
                WHERE wm.workspace_id = %s
                  AND wm.clerk_user_id = %s
                GROUP BY wm.workspace_id, wm.clerk_user_id, wm.morning_briefing_optin, w.name, up.email, up.display_name
                """,
                (workspace_id, user_id),
            )
            if not row or not row["morning_briefing_optin"]:
                return {"sent": False, "skipped": "opted_out"}
            if not row.get("email"):
                return {"sent": False, "skipped": "missing_email"}
            pending_count = int(row["pending_count"] or 0)
            if pending_count < 1:
                return {"sent": False, "skipped": "no_pending_items"}

            unsubscribe_url = f"{settings.backend_base_url}/webhooks/email/unsubscribe?token={make_unsubscribe_token(workspace_id, user_id)}"
            postmark_payload = {
                "From": settings.postmark_from,
                "To": row["email"],
                "TemplateAlias": settings.postmark_morning_template_alias,
                "TemplateModel": {
                    "user_name": row.get("display_name") or "there",
                    "workspace_name": row["workspace_name"],
                    "pending_count": pending_count,
                    "open_url": settings.frontend_base_url,
                    "unsubscribe_url": unsubscribe_url,
                },
                "MessageStream": settings.postmark_message_stream,
                "Headers": [
                    {"Name": "List-Unsubscribe", "Value": f"<{unsubscribe_url}>"},
                    {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
                ],
            }

        if settings.postmark_dry_run:
            result = {"sent": True, "dry_run": True, "postmark_payload": postmark_payload}
        elif not settings.postmark_server_token:
            raise RuntimeError("NOTESNOOP_POSTMARK_SERVER_TOKEN is required for Morning briefing delivery")
        else:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    "https://api.postmarkapp.com/email/withTemplate",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-Postmark-Server-Token": settings.postmark_server_token,
                    },
                    json=postmark_payload,
                )
                response.raise_for_status()
                result = {"sent": True, "dry_run": False, "postmark_response": response.json()}

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL search_path = public")
            merged_payload = dict(job.get("payload") or {})
            merged_payload.update({"delivery": result})
            cur.execute(
                "UPDATE ai_jobs SET payload = %s::jsonb WHERE id = %s",
                (json.dumps(merged_payload, default=_json_default), job["id"]),
            )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def disable_morning_briefing(workspace_id: str, user_id: str) -> bool:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute("SELECT disable_morning_briefing(%s, %s)", (workspace_id, user_id))
            changed = bool(cur.fetchone()[0])
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def disable_morning_briefing_by_email(email: str) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL search_path = public")
            cur.execute("SELECT disable_morning_briefing_by_email(%s)", (email,))
            changed = int(cur.fetchone()[0])
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
