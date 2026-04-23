"""Supabase Auth JWT verification middleware for FastAPI.

Supports ES256 (P-256) JWTs used by newer Supabase projects.
Fetches the JWKS public key from Supabase to verify tokens.
"""

import os
import time
import logging
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt, jwk
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_HS256_FALLBACK = os.getenv("SUPABASE_HS256_FALLBACK", "").lower() in ("1", "true", "yes")

# Accepted JWT audiences: Supabase project URL + project ref (bare ID)
_SUPABASE_AUDIENCES = [
    SUPABASE_URL,  # e.g. https://nvtopretdjlxabsmqxvk.supabase.co
    "authenticated",  # Supabase default audience claim
]
_SUPABASE_AUDIENCES = [a for a in _SUPABASE_AUDIENCES if a]

security = HTTPBearer(auto_error=True)
security_optional = HTTPBearer(auto_error=False)

# Cache the JWKS keys with a TTL
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL_SECONDS = 3600  # re-fetch after 1 hour


def _get_jwks() -> dict:
    """Fetch JWKS from Supabase (cached with 1-hour TTL)."""
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache
    if SUPABASE_URL:
        try:
            resp = httpx.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if not isinstance(data.get("keys"), list):
                    raise ValueError("Invalid JWKS response format: keys is not a list")
                _jwks_cache = data
                _jwks_fetched_at = now
                logger.info("Fetched JWKS from Supabase: %d keys", len(_jwks_cache.get("keys", [])))
                return _jwks_cache
        except Exception as e:
            logger.warning("Failed to fetch JWKS: %s", e)
            # Keep stale keys only within a bounded staleness window.
            if _jwks_cache and (now - _jwks_fetched_at) < (_JWKS_TTL_SECONDS * 2):
                return _jwks_cache
            if _jwks_cache:
                logger.warning("JWKS cache too stale after fetch failure; clearing cached keys")
                _jwks_cache = {}
    return {}


_ALLOWED_ALGS = {"RS256", "ES256"}


def _decode_token(token: str) -> dict:
    """Verify and decode a Supabase JWT."""
    # Try 1: JWKS (ES256/RS256)
    jwks = _get_jwks()
    if jwks.get("keys"):
        try:
            # Get the header to find the key ID
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            alg = unverified_header.get("alg", "ES256")

            # Reject tokens that claim an algorithm we don't accept — prevents
            # algorithm-confusion attacks (e.g. alg:none, alg:HS256 with public key).
            if alg not in _ALLOWED_ALGS:
                raise JWTError(f"Algorithm '{alg}' not in allowlist")

            # Find the matching key
            key_data = None
            for k in jwks["keys"]:
                if k.get("kid") == kid:
                    key_data = k
                    break
            if not key_data:
                raise JWTError(f"No matching JWKS key for kid='{kid}'")

            if key_data:
                public_key = jwk.construct(key_data, algorithm=alg)
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=[alg],
                    audience=_SUPABASE_AUDIENCES,
                    options={"verify_aud": True},
                )
                return payload
        except JWTError as e:
            logger.warning("JWKS verification failed: %s", e)

    # Try 2: HS256 with secret (legacy, explicit opt-in only)
    if SUPABASE_HS256_FALLBACK and SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=_SUPABASE_AUDIENCES,
                options={"verify_aud": True},
            )
            return payload
        except JWTError as e:
            logger.warning("HS256 verification failed: %s", e)
    elif SUPABASE_HS256_FALLBACK and not SUPABASE_JWT_SECRET:
        logger.error(
            "SUPABASE_HS256_FALLBACK enabled but SUPABASE_JWT_SECRET is empty; "
            "HS256 fallback disabled"
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Requires a valid Bearer token. Returns user info."""
    payload = _decode_token(credentials.credentials)
    return {
        "id": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
        "payload": payload,
    }


async def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
) -> Optional[dict]:
    """Returns user info if valid token present, None otherwise."""
    if credentials is None:
        return None
    try:
        payload = _decode_token(credentials.credentials)
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
            "payload": payload,
        }
    except HTTPException:
        return None
