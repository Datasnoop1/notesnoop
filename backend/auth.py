"""Supabase Auth JWT verification middleware for FastAPI.

Supports ES256 (P-256) JWTs used by newer Supabase projects.
Fetches the JWKS public key from Supabase to verify tokens.
"""

import os
import logging
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt, jwk
from jose.utils import base64url_decode
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

security = HTTPBearer(auto_error=True)
security_optional = HTTPBearer(auto_error=False)

# Cache the JWKS keys
_jwks_cache: dict = {}


def _get_jwks() -> dict:
    """Fetch JWKS from Supabase (cached)."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    if SUPABASE_URL:
        try:
            resp = httpx.get(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", timeout=5)
            if resp.status_code == 200:
                _jwks_cache = resp.json()
                logger.info("Fetched JWKS from Supabase: %d keys", len(_jwks_cache.get("keys", [])))
                return _jwks_cache
        except Exception as e:
            logger.warning("Failed to fetch JWKS: %s", e)
    return {}


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

            # Find the matching key
            key_data = None
            for k in jwks["keys"]:
                if k.get("kid") == kid:
                    key_data = k
                    break
            if not key_data and jwks["keys"]:
                key_data = jwks["keys"][0]  # Use first key as fallback

            if key_data:
                public_key = jwk.construct(key_data, algorithm=alg)
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=[alg],
                    options={"verify_aud": False},
                )
                return payload
        except JWTError as e:
            logger.warning("JWKS verification failed: %s", e)

    # Try 2: HS256 with secret (legacy)
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            return payload
        except JWTError as e:
            logger.warning("HS256 verification failed: %s", e)

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
