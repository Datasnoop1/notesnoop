from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request

from ..db import transaction
from ..email_ingest import mailgun_envelope, postmark_envelope, save_inbound_envelope


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_postmark_auth(raw: bytes, authorization: str | None, signature: str | None) -> None:
    allow_unsigned = os.getenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
    if allow_unsigned:
        return

    basic_auth = os.getenv("NOTESNOOP_POSTMARK_BASIC_AUTH", "")
    if basic_auth:
        expected = "Basic " + base64.b64encode(basic_auth.encode("utf-8")).decode("ascii")
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=403, detail="Invalid Postmark webhook credentials")
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


@router.post("/email/inbound")
async def inbound_email(
    request: Request,
    authorization: str | None = Header(default=None),
    x_postmark_signature: str | None = Header(default=None),
    x_notesnoop_provider: str | None = Header(default=None),
):
    raw = await request.body()
    provider = (x_notesnoop_provider or "postmark").lower()
    if provider == "postmark":
        _verify_postmark_auth(raw, authorization, x_postmark_signature)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    envelope = mailgun_envelope(payload) if provider == "mailgun" else postmark_envelope(payload)
    if not envelope["message_id"]:
        raise HTTPException(status_code=400, detail="Provider message id is required")

    with transaction(provider_webhook=True) as cur:
        try:
            return {"data": save_inbound_envelope(cur, envelope)}
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
