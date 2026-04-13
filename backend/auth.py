"""Supabase Auth JWT verification middleware for FastAPI."""

import os
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
ALGORITHMS = ["HS256", "RS256"]

security = HTTPBearer(auto_error=True)
security_optional = HTTPBearer(auto_error=False)


def _decode_token(token: str) -> dict:
    """Verify and decode a Supabase JWT. Returns the payload dict."""
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_JWT_SECRET not configured on server",
        )
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=ALGORITHMS,
            options={"verify_aud": False},
        )
        return payload
    except JWTError as e:
        logger.warning("JWT verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """FastAPI dependency: requires a valid Bearer token.

    Returns the decoded JWT payload containing at minimum:
      - sub: user UUID
      - email: user email
      - role: Supabase role (e.g. "authenticated")
    """
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
    """FastAPI dependency: returns user info if a valid token is present, None otherwise."""
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
