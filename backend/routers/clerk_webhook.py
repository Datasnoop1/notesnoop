"""Clerk webhook endpoint (Svix-signed).

POST /api/_auth/clerk-webhook receives Clerk lifecycle events. Auth is
the Svix HMAC signature on `{svix-id}.{svix-timestamp}.{body}` — this
endpoint MUST be exempt from the Bearer-token middlewares.

Handlers (Phase 3 scope):
  - user.created — assign external_id if missing, write clerk_user_map +
    user_roles. Idempotent on (svix-id, event_type).
  - user.updated — no-op (deferred).
  - user.deleted — log only (deferred).
  - other events — log + 200.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/_auth", tags=["auth"])

CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET") or ""
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY") or ""

_CLERK_PATCH_TIMEOUT_S = 5.0


# ---------------------------------------------------------------------------
# Svix signature verification
# ---------------------------------------------------------------------------


def _decode_secret(secret: str) -> bytes:
    """Strip `whsec_` prefix and base64-decode the signing secret."""
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    # Standard Svix secrets are base64-encoded random bytes.
    try:
        return base64.b64decode(secret)
    except Exception:
        # Fallback: treat as raw bytes (some test fixtures use raw secrets).
        return secret.encode("utf-8")


def verify_svix_signature(
    body: bytes,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    secret: str,
) -> bool:
    """Verify a Svix webhook signature.

    Signed payload: `{svix-id}.{svix-timestamp}.{body}` (body as raw bytes).
    HMAC-SHA256 with the decoded secret. The `svix-signature` header
    contains one or more `v1,<base64-sig>` tokens separated by spaces;
    any one matching the expected signature is sufficient.
    """
    if not (svix_id and svix_timestamp and svix_signature and secret):
        return False

    # Replay-attack defence: reject signatures whose svix-timestamp is more
    # than ±5 minutes from now. Without this check, a captured webhook event
    # whose svix-id has not yet been recorded can be replayed indefinitely
    # by anyone holding the body. ±5 min matches Svix's standard verifier.
    try:
        ts = int(svix_timestamp)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if abs(now - ts) > 300:
        return False

    secret_bytes = _decode_secret(secret)
    signed = f"{svix_id}.{svix_timestamp}.".encode("utf-8") + body
    expected_raw = hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected_raw).decode("utf-8")

    # Header may carry multiple sigs separated by spaces; each is "v1,<sig>".
    for token in svix_signature.split():
        if "," not in token:
            continue
        version, sig = token.split(",", 1)
        if version != "v1":
            continue
        if hmac.compare_digest(sig, expected_b64):
            return True
    return False


# ---------------------------------------------------------------------------
# Idempotency + handlers
# ---------------------------------------------------------------------------


def _is_test_event(payload: dict) -> bool:
    """v18 plan: skip DB writes for synthetic test events.

    Clerk's "send test" feature in the dashboard fires events with
    obvious synthetic markers; we don't want to pollute clerk_user_map +
    user_roles with these.
    """
    data = payload.get("data") or {}
    if data.get("test") is True:
        return True
    instance_id = payload.get("instance_id") or data.get("instance_id") or ""
    if isinstance(instance_id, str) and (
        "test" in instance_id.lower() or "synthetic" in instance_id.lower()
    ):
        return True
    return False


def _record_event(svix_id: str, event_type: str) -> bool:
    """Insert into webhook_log for idempotency. Returns True if newly
    recorded, False if (svix_id, event_type) was already processed."""
    try:
        from db import get_conn
    except Exception:
        # If the DB import fails, fail open: better to potentially
        # double-process than to wedge the webhook entirely.
        return True

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO webhook_log (svix_id, event_type)
                    VALUES (%s, %s)
                    ON CONFLICT (svix_id, event_type) DO NOTHING
                    RETURNING svix_id
                    """,
                    (svix_id, event_type),
                )
                inserted = cur.fetchone() is not None
            conn.commit()
        return inserted
    except Exception:
        logger.exception("webhook_log insert failed")
        return True


def _patch_clerk_external_id(clerk_sub: str, datasnoop_user_id: str) -> bool:
    """Best-effort PATCH /v1/users/{sub}.external_id."""
    if not CLERK_SECRET_KEY:
        return False
    try:
        resp = httpx.patch(
            f"https://api.clerk.com/v1/users/{clerk_sub}",
            headers={
                "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            json={"external_id": str(datasnoop_user_id)},
            timeout=_CLERK_PATCH_TIMEOUT_S,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.warning(
            "Clerk PATCH (webhook) external_id failed: status=%s",
            resp.status_code,
        )
        return False
    except Exception as e:
        logger.warning("Clerk PATCH (webhook) external_id raised: %s", e)
        return False


def _extract_email(user_data: dict) -> str | None:
    """Pull the primary email out of a Clerk user payload."""
    primary_id = user_data.get("primary_email_address_id")
    for addr in user_data.get("email_addresses") or []:
        if not isinstance(addr, dict):
            continue
        if primary_id and addr.get("id") == primary_id:
            return addr.get("email_address")
    # Fallback: first email if no primary marker.
    addrs = user_data.get("email_addresses") or []
    if addrs and isinstance(addrs[0], dict):
        return addrs[0].get("email_address")
    return user_data.get("email_address") or user_data.get("email")


def _handle_user_created(payload: dict) -> None:
    """user.created: assign external_id if missing, write map + role."""
    data = payload.get("data") or {}
    sub = data.get("id")
    if not sub:
        logger.warning("user.created missing data.id")
        return

    existing_external_id = data.get("external_id")
    email = _extract_email(data)

    try:
        from db import get_conn
    except Exception:
        return

    if existing_external_id:
        # Imported user (Phase 4/5.5): nothing to assign. Make sure the
        # local map row exists for completeness.
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO clerk_user_map (clerk_sub, datasnoop_user_id, clerk_synced_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT (clerk_sub) DO NOTHING
                        """,
                        (sub, str(existing_external_id)),
                    )
                    if email:
                        cur.execute(
                            """
                            INSERT INTO user_roles (email, role)
                            VALUES (%s, 'user')
                            ON CONFLICT (email) DO NOTHING
                            """,
                            (email,),
                        )
                conn.commit()
        except Exception:
            logger.exception("user.created (existing external_id) DB upsert failed")
        return

    # Native sign-up: assign a fresh UUID, write the map, then PATCH Clerk.
    new_id = str(uuid.uuid4())
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO clerk_user_map (clerk_sub, datasnoop_user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (clerk_sub) DO NOTHING
                    RETURNING datasnoop_user_id
                    """,
                    (sub, new_id),
                )
                row = cur.fetchone()
                resolved_id = str(row[0]) if row else new_id
                if row is None:
                    cur.execute(
                        "SELECT datasnoop_user_id FROM clerk_user_map WHERE clerk_sub = %s",
                        (sub,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        resolved_id = str(existing[0])

                cur.execute(
                    """
                    INSERT INTO clerk_pending_sync (clerk_sub, datasnoop_user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (clerk_sub) DO NOTHING
                    """,
                    (sub, resolved_id),
                )

                if email:
                    cur.execute(
                        """
                        INSERT INTO user_roles (email, role)
                        VALUES (%s, 'user')
                        ON CONFLICT (email) DO NOTHING
                        """,
                        (email,),
                    )
            conn.commit()
    except Exception:
        logger.exception("user.created DB upsert failed")
        return

    # Best-effort PATCH; reconcile pending-sync on success.
    if _patch_clerk_external_id(sub, resolved_id):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clerk_user_map SET clerk_synced_at = now() WHERE clerk_sub = %s",
                        (sub,),
                    )
                    cur.execute(
                        "DELETE FROM clerk_pending_sync WHERE clerk_sub = %s",
                        (sub,),
                    )
                conn.commit()
        except Exception:
            logger.exception("user.created post-PATCH cleanup failed")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/clerk-webhook")
async def clerk_webhook(request: Request) -> Response:
    """Receive a Clerk webhook event."""
    if not CLERK_WEBHOOK_SECRET:
        # Fail-closed when the signing secret isn't configured —
        # accepting unsigned traffic on this endpoint would be a hole.
        logger.error("Clerk webhook called but CLERK_WEBHOOK_SECRET is unset")
        raise HTTPException(status_code=503, detail="webhook_disabled")

    body = await request.body()
    svix_id = request.headers.get("svix-id", "")
    svix_timestamp = request.headers.get("svix-timestamp", "")
    svix_signature = request.headers.get("svix-signature", "")

    if not verify_svix_signature(
        body, svix_id, svix_timestamp, svix_signature, CLERK_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="invalid_signature")

    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    event_type = (payload.get("type") or "").strip()

    # Idempotency — already-seen (svix-id, event_type) = no-op 200.
    if not _record_event(svix_id, event_type or "unknown"):
        return Response(status_code=200)

    # Test events skip the DB writes (per v18 plan-correction).
    if _is_test_event(payload):
        logger.info("Clerk test event svix_id=%s type=%s skipped", svix_id, event_type)
        return Response(status_code=200)

    if event_type == "user.created":
        try:
            _handle_user_created(payload)
        except Exception:
            logger.exception("user.created handler failed")
    elif event_type == "user.updated":
        # Deferred to a later phase; we still mark the event processed.
        logger.info("user.updated received svix_id=%s — no-op", svix_id)
    elif event_type == "user.deleted":
        logger.info("user.deleted received svix_id=%s — logged only", svix_id)
    else:
        logger.info("Clerk webhook event type=%s svix_id=%s — passthrough", event_type, svix_id)

    return Response(status_code=200)
