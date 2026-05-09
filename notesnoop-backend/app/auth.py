from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError, jwk, jwt

from .config import get_settings


@dataclass(frozen=True)
class CurrentUser:
    clerk_user_id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


_jwks_cache: dict = {}
_jwks_fetched_at = 0.0


def _jwks_url() -> str:
    settings = get_settings()
    if settings.clerk_jwks_url:
        return settings.clerk_jwks_url
    if settings.clerk_issuer:
        return f"{settings.clerk_issuer.rstrip('/')}/.well-known/jwks.json"
    return ""


def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_cache and now - _jwks_fetched_at < 3600:
        return _jwks_cache
    url = _jwks_url()
    if not url:
        raise HTTPException(status_code=500, detail="Clerk issuer is not configured")
    resp = httpx.get(url, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data.get("keys"), list):
        raise HTTPException(status_code=500, detail="Invalid Clerk JWKS response")
    _jwks_cache = data
    _jwks_fetched_at = now
    return data


def _verify_clerk_token(token: str) -> dict:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise JWTError("Unsupported Clerk JWT algorithm")
        kid = header.get("kid")
        key_data = next((key for key in _get_jwks().get("keys", []) if key.get("kid") == kid), None)
        if not key_data:
            raise JWTError("No matching Clerk JWKS key")
        public_key = jwk.construct(key_data, algorithm="RS256")
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer.rstrip("/") if settings.clerk_issuer else None,
            options={"verify_aud": False, "verify_iss": bool(settings.clerk_issuer)},
        )
        if settings.clerk_authorized_party and payload.get("azp") != settings.clerk_authorized_party:
            raise JWTError("Clerk authorized-party mismatch")
        if not payload.get("sub"):
            raise JWTError("Clerk JWT missing sub")
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Clerk token") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Unable to verify Clerk token") from exc


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    x_notesnoop_user_id: str | None = Header(default=None),
    x_notesnoop_email: str | None = Header(default=None),
    x_notesnoop_name: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    if settings.dev_auth:
        user_id = x_notesnoop_user_id or "dev_user"
        return CurrentUser(
            clerk_user_id=user_id,
            email=x_notesnoop_email or f"{user_id}@example.test",
            display_name=x_notesnoop_name or "Dev User",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = _verify_clerk_token(authorization.split(" ", 1)[1].strip())
    email = payload.get("email") or payload.get("primary_email_address") or payload.get("email_address")
    return CurrentUser(
        clerk_user_id=payload["sub"],
        email=email,
        display_name=payload.get("name") or payload.get("given_name"),
        avatar_url=payload.get("picture") or payload.get("image_url"),
    )


CurrentUserDep = Depends(current_user)
