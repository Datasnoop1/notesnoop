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
SUPABASE_JWKS_BOOTSTRAP_REQUIRED = (
    os.getenv("SUPABASE_JWKS_BOOTSTRAP_REQUIRED", "true").lower() in ("1", "true", "yes")
)

# Accepted JWT audiences: Supabase project URL + project ref (bare ID)
_SUPABASE_AUDIENCES = [
    SUPABASE_URL,  # e.g. https://nvtopretdjlxabsmqxvk.supabase.co
    "authenticated",  # Supabase default audience claim
]
_SUPABASE_AUDIENCES = [a for a in _SUPABASE_AUDIENCES if a]

# Expected JWT issuer (Supabase's auth signing service). When set, decode must
# enforce `iss` verification to prevent tokens minted by any other Supabase
# project with a matching audience from passing verification.
_SUPABASE_ISSUER = f"{SUPABASE_URL.rstrip('/')}/auth/v1" if SUPABASE_URL else ""
_issuer_warning_emitted = False

# Fail-closed behavior: if SUPABASE_URL is empty and HS256 fallback is NOT
# enabled, we cannot verify tokens at all. Raise at import time.
if not SUPABASE_URL and not SUPABASE_HS256_FALLBACK:
    raise RuntimeError(
        "SUPABASE_URL is empty and SUPABASE_HS256_FALLBACK is disabled. "
        "No token verification path available."
    )


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
            # 1.25× TTL caps blast radius on key rotations where Supabase is
            # briefly unreachable during the rotation window (~75 min with 1h TTL).
            if _jwks_cache and (now - _jwks_fetched_at) < (_JWKS_TTL_SECONDS * 1.25):
                return _jwks_cache
            if _jwks_cache:
                logger.warning("JWKS cache too stale after fetch failure; clearing cached keys")
                _jwks_cache = {}
    return {}


def ensure_jwks_bootstrapped() -> None:
    """Fail fast at startup if Supabase JWKS cannot be fetched at least once.

    NOTE: `backend/main.py`'s startup hook should call this so the backend
    refuses to start when it cannot verify JWTs. Not wired here to keep this
    patch confined to `backend/auth.py`.
    """
    jwks = _get_jwks()
    if not jwks.get("keys") and SUPABASE_URL:
        if not SUPABASE_JWKS_BOOTSTRAP_REQUIRED:
            logger.warning(
                "JWKS bootstrap failed but SUPABASE_JWKS_BOOTSTRAP_REQUIRED is false; "
                "starting anyway (JWT verification may fail until JWKS is reachable)"
            )
            return
        # SEC-HIGH: Handle HS256-only dev/legacy environments gracefully.
        # Skip the raise when SUPABASE_HS256_FALLBACK is enabled AND
        # SUPABASE_JWT_SECRET is present AND SUPABASE_URL is empty.
        if SUPABASE_HS256_FALLBACK and SUPABASE_JWT_SECRET:
            logger.warning(
                "JWKS bootstrap failed but SUPABASE_HS256_FALLBACK + SUPABASE_JWT_SECRET present; "
                "proceeding with HS256-only verification"
            )
            return
        # CORR-HIGH: If SUPABASE_URL is empty AND HS256 fallback is NOT enabled,
        # we have no way to verify tokens at all.
        elif not SUPABASE_HS256_FALLBACK:
            raise RuntimeError(
                "JWKS bootstrap failed: cannot verify JWTs without Supabase JWKS "
                "and HS256 fallback is disabled"
            )


_ALLOWED_ALGS = {"RS256", "ES256"}


def _decode_with_audiences(token: str, key, algorithms: list[str]) -> dict:
    """Try JWT decode against configured audiences, one-by-one.

    python-jose expects `audience` to be a single string (or None), not a list.
    """
    global _issuer_warning_emitted
    audiences = _SUPABASE_AUDIENCES or ["authenticated"]
    decode_options = {"verify_aud": True}
    decode_kwargs: dict = {}
    if _SUPABASE_ISSUER:
        decode_options["verify_iss"] = True
        decode_kwargs["issuer"] = _SUPABASE_ISSUER
    elif SUPABASE_URL:
        # Only warn when SUPABASE_URL was expected but empty
        if not _issuer_warning_emitted:
            logger.warning(
                "SUPABASE_URL not set; JWT `iss` claim will not be verified"
            )
            _issuer_warning_emitted = True
    else:
        # SEC-HIGH: Fail closed when _SUPABASE_ISSUER is empty and HS256 fallback is NOT enabled
        if not SUPABASE_HS256_FALLBACK:
            raise JWTError("Cannot verify issuer: SUPABASE_URL is empty and HS256 fallback not enabled")
        _issuer_warning_emitted = True
    last_error: JWTError | None = None
    for aud in audiences:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=aud,
                options=decode_options,
                **decode_kwargs,
            )
        except JWTError as e:
            last_error = e
            continue
    if last_error:
        raise last_error
    raise JWTError("JWT audience verification failed")


def _is_clerk_issuer(token: str) -> bool:
    """Return True if the JWT's `iss` claim matches the Clerk issuer.

    Reads `iss` from the unverified payload — we have not yet checked
    the signature — but the routing decision is safe because we re-verify
    `iss` after fetching the right JWKS in either branch. An attacker
    forging a Clerk-shaped `iss` cannot forge a Clerk signature.
    """
    try:
        from auth_clerk import CLERK_ISSUER, is_clerk_enabled
        if not is_clerk_enabled():
            return False
        unverified = jwt.get_unverified_claims(token)
        return unverified.get("iss") == CLERK_ISSUER
    except Exception:
        return False


def _decode_token(token: str) -> dict:
    """Verify and decode a Supabase or Clerk JWT.

    Routing: if the JWT `iss` claim matches CLERK_ISSUER (and Clerk is
    enabled), verify via auth_clerk.verify_clerk_jwt(). Otherwise fall
    through to the existing Supabase JWKS / HS256 logic — Supabase
    callers see no behaviour change.
    """
    # Phase 3: route to Clerk verifier when issuer matches.
    if _is_clerk_issuer(token):
        try:
            from auth_clerk import verify_clerk_jwt
            return verify_clerk_jwt(token)
        except JWTError as e:
            logger.warning("Clerk JWT verification failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

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
                payload = _decode_with_audiences(
                    token,
                    public_key,
                    algorithms=[alg],
                )
                return payload
        except JWTError as e:
            logger.warning("JWKS verification failed: %s", e)

    # Try 2: HS256 with secret (legacy, explicit opt-in only)
    if SUPABASE_HS256_FALLBACK and SUPABASE_JWT_SECRET:
        try:
            payload = _decode_with_audiences(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
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


def _user_from_payload(payload: dict) -> dict:
    """Map a verified JWT payload to the user dict returned by
    get_current_user / optional_user.

    Public function signatures don't change between Supabase and Clerk
    callers. For Clerk we route through auth_clerk.get_clerk_user_from_payload
    so the `id` field is the canonical DataSnoop UUID (not Clerk's `sub`),
    matching everything downstream that already runs against Supabase
    UUIDs.
    """
    iss = payload.get("iss") or ""
    try:
        from auth_clerk import CLERK_ISSUER, is_clerk_enabled, get_clerk_user_from_payload
        if is_clerk_enabled() and iss == CLERK_ISSUER:
            return get_clerk_user_from_payload(payload)
    except Exception:
        # If the Clerk path explodes after a successful signature check,
        # we still have a verified payload — fall through to the generic
        # mapping so the request isn't blackholed. The webhook + worker
        # will reconcile state on the next event.
        logger.exception("Clerk user resolution failed; falling back to payload sub")

    return {
        "id": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
        "payload": payload,
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Requires a valid Bearer token. Returns user info."""
    payload = _decode_token(credentials.credentials)
    return _user_from_payload(payload)


async def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
) -> Optional[dict]:
    """Returns user info if valid token present, None otherwise."""
    if credentials is None:
        return None
    try:
        payload = _decode_token(credentials.credentials)
        return _user_from_payload(payload)
    except HTTPException:
        return None
