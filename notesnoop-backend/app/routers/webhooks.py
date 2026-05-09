from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request

from ..briefing import disable_morning_briefing, disable_morning_briefing_by_email, parse_unsubscribe_token
from ..db import transaction
from ..email_ingest import mailgun_envelope, postmark_envelope, save_inbound_envelope


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _allow_unsigned_webhooks() -> bool:
    return os.getenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}


def _verify_basic_auth(expected_plaintext: str, authorization: str | None, provider: str) -> None:
    expected = "Basic " + base64.b64encode(expected_plaintext.encode("utf-8")).decode("ascii")
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=403, detail=f"Invalid {provider} webhook credentials")


def _verify_postmark_auth(raw: bytes, authorization: str | None, signature: str | None) -> None:
    if _allow_unsigned_webhooks():
        return

    basic_auth = os.getenv("NOTESNOOP_POSTMARK_BASIC_AUTH", "")
    if basic_auth:
        _verify_basic_auth(basic_auth, authorization, "Postmark")
        return

    secret = os.getenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET", "")
    if secret:
        if not signature:
            raise HTTPException(status_code=403, detail="Missing Postmark webhook signature")
        digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, signature):
            return
        raise HTTPException(status_code=403, detail="Invalid Postmark webhook signature")
    raise HTTPException(status_code=500, detail="Postmark webhook auth is not configured")


def _verify_mailgun_auth(
    payload: dict,
    authorization: str | None,
    timestamp: str | None,
    token: str | None,
    signature: str | None,
) -> None:
    if _allow_unsigned_webhooks():
        return

    basic_auth = os.getenv("NOTESNOOP_MAILGUN_BASIC_AUTH", "")
    if basic_auth:
        _verify_basic_auth(basic_auth, authorization, "Mailgun")
        return

    signing_key = os.getenv("NOTESNOOP_MAILGUN_SIGNING_KEY", "")
    if signing_key:
        signature_payload = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
        timestamp = timestamp or signature_payload.get("timestamp") or payload.get("timestamp")
        token = token or signature_payload.get("token") or payload.get("token")
        signature = signature or signature_payload.get("signature")
        if not timestamp or not token or not signature:
            raise HTTPException(status_code=403, detail="Missing Mailgun webhook signature")
        digest = hmac.new(signing_key.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, str(signature)):
            return
        raise HTTPException(status_code=403, detail="Invalid Mailgun webhook signature")

    raise HTTPException(status_code=500, detail="Mailgun webhook auth is not configured")


@router.post("/email/inbound")
async def inbound_email(
    request: Request,
    authorization: str | None = Header(default=None),
    x_postmark_signature: str | None = Header(default=None),
    x_mailgun_timestamp: str | None = Header(default=None),
    x_mailgun_token: str | None = Header(default=None),
    x_mailgun_signature: str | None = Header(default=None),
    x_notesnoop_provider: str | None = Header(default=None),
):
    raw = await request.body()
    provider = (x_notesnoop_provider or "postmark").lower()
    if provider not in {"postmark", "mailgun"}:
        raise HTTPException(status_code=400, detail="Unsupported inbound email provider")
    if provider == "postmark":
        _verify_postmark_auth(raw, authorization, x_postmark_signature)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if provider == "mailgun":
        _verify_mailgun_auth(payload, authorization, x_mailgun_timestamp, x_mailgun_token, x_mailgun_signature)
    envelope = mailgun_envelope(payload) if provider == "mailgun" else postmark_envelope(payload)
    if not envelope["message_id"]:
        raise HTTPException(status_code=400, detail="Provider message id is required")

    with transaction(provider_webhook=True) as cur:
        try:
            return {"data": save_inbound_envelope(cur, envelope)}
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.api_route("/email/unsubscribe", methods=["GET", "POST"])
async def unsubscribe_morning_briefing(token: str):
    payload = parse_unsubscribe_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Invalid unsubscribe token")
    changed = disable_morning_briefing(payload["workspace_id"], payload["user_id"])
    return {"data": {"unsubscribed": True, "changed": changed}}


@router.post("/email/bounce")
async def outbound_bounce(
    request: Request,
    authorization: str | None = Header(default=None),
    x_postmark_signature: str | None = Header(default=None),
):
    raw = await request.body()
    _verify_postmark_auth(raw, authorization, x_postmark_signature)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    email = payload.get("Email") or payload.get("Recipient")
    if not email:
        raise HTTPException(status_code=400, detail="Bounce email is required")
    disabled = disable_morning_briefing_by_email(str(email))
    return {"data": {"disabled_memberships": disabled}}
