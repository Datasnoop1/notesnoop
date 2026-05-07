"""Clerk JWT verification for FastAPI.

Mirrors backend/auth.py's structure but verifies Clerk-issued tokens
(RS256 only, fetched via JWKS at the Clerk-Frontend-API origin).

Routing in backend/auth.py picks this verifier when the JWT's `iss`
claim matches CLERK_ISSUER.

Self-heal flow (from docs/auth-migration-clerk-final.md Phase 3):
when a Clerk JWT arrives whose `sub` has no row in `clerk_user_map`,
we INSIDE a single Postgres transaction allocate a fresh UUID, write
the mapping row, queue a `clerk_pending_sync` retry record, and
upsert a `user_roles` row. Then best-effort PATCH Clerk's
`external_id` so subsequent JWTs already carry it. PATCH success
clears the pending-sync row; failure keeps it for the worker.
"""

import logging
import os
import time
import uuid
from typing import Optional

import httpx
from jose import JWTError, jwk, jwt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env / configuration
# ---------------------------------------------------------------------------

CLERK_ISSUER = (os.getenv("CLERK_ISSUER") or "").rstrip("/")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL") or (
    f"{CLERK_ISSUER}/.well-known/jwks.json" if CLERK_ISSUER else ""
)
CLERK_AUTHORIZED_PARTY = os.getenv("CLERK_AUTHORIZED_PARTY") or ""
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY") or ""

# Clerk only ever signs with RS256 — pin the algorithm allowlist so nothing
# can downgrade to HS256/`none` via header manipulation.
_CLERK_ALLOWED_ALGS = {"RS256"}

# Used in get_clerk_user_from_payload() — best-effort PATCH timeout.
_CLERK_PATCH_TIMEOUT_S = 5.0


def is_clerk_enabled() -> bool:
    """Phase 3 router uses this to decide whether to attempt Clerk verification."""
    return bool(CLERK_ISSUER) and bool(CLERK_JWKS_URL)


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL_SECONDS = 3600  # 1 hour, matches backend/auth.py


def _get_jwks() -> dict:
    """Fetch Clerk JWKS, cached for 1 hour."""
    global _jwks_cache, _jwks_fetched_at
    if not CLERK_JWKS_URL:
        return {}
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache
    try:
        resp = httpx.get(CLERK_JWKS_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if not isinstance(data.get("keys"), list):
                raise ValueError("Invalid Clerk JWKS response: keys is not a list")
            _jwks_cache = data
            _jwks_fetched_at = now
            logger.info(
                "Fetched Clerk JWKS: %d keys", len(_jwks_cache.get("keys", []))
            )
            return _jwks_cache
    except Exception as e:
        logger.warning("Failed to fetch Clerk JWKS: %s", e)
        # Bounded staleness: keep stale keys for up to 1.25× TTL on fetch
        # failure (mirrors backend/auth.py — covers brief Clerk outages).
        if _jwks_cache and (now - _jwks_fetched_at) < (_JWKS_TTL_SECONDS * 1.25):
            return _jwks_cache
        if _jwks_cache:
            logger.warning(
                "Clerk JWKS cache too stale after fetch failure; clearing cached keys"
            )
            _jwks_cache = {}
    return {}


def _set_jwks_cache_for_tests(data: dict) -> None:
    """Test hook: inject a synthetic JWKS so unit tests don't hit the network."""
    global _jwks_cache, _jwks_fetched_at
    _jwks_cache = data
    _jwks_fetched_at = time.monotonic()


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------


def verify_clerk_jwt(token: str) -> dict:
    """Verify a Clerk-signed JWT.

    - RS256 only (algorithm-confusion defence).
    - `iss` must equal CLERK_ISSUER exactly.
    - `exp` is enforced.
    - `azp` (authorized party) must match CLERK_AUTHORIZED_PARTY when set.

    Returns the decoded payload. Raises JWTError on any failure.
    """
    if not is_clerk_enabled():
        raise JWTError("Clerk verification disabled (CLERK_ISSUER not set)")

    unverified_header = jwt.get_unverified_header(token)
    alg = unverified_header.get("alg", "")
    if alg not in _CLERK_ALLOWED_ALGS:
        raise JWTError(f"Algorithm '{alg}' not allowed for Clerk JWTs")
    kid = unverified_header.get("kid")

    jwks = _get_jwks()
    keys = jwks.get("keys") or []
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if not key_data:
        raise JWTError(f"No matching Clerk JWKS key for kid='{kid}'")

    public_key = jwk.construct(key_data, algorithm="RS256")

    # Clerk JWTs don't always carry an `aud` claim. Disable audience
    # verification — issuer + signature + (optional) azp is the contract.
    decode_options = {"verify_aud": False, "verify_iss": True}
    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=CLERK_ISSUER,
        options=decode_options,
    )

    # `azp` (Authorized Party) — RFC 9068 §3 — restricts which OAuth client
    # may use the token. Only enforced when explicitly configured.
    if CLERK_AUTHORIZED_PARTY:
        azp = payload.get("azp")
        if azp != CLERK_AUTHORIZED_PARTY:
            raise JWTError(
                f"Clerk JWT azp mismatch: expected {CLERK_AUTHORIZED_PARTY}, got {azp}"
            )

    if not payload.get("sub"):
        raise JWTError("Clerk JWT missing sub claim")

    return payload


# ---------------------------------------------------------------------------
# Self-heal: clerk_user_map lookup + atomic write on miss
# ---------------------------------------------------------------------------


def _patch_clerk_external_id(clerk_sub: str, datasnoop_user_id: str) -> bool:
    """Best-effort PATCH /v1/users/{sub} setting external_id.

    Returns True on success, False on any failure. Caller decides what to
    do — we never raise out of this function.
    """
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
            "Clerk PATCH external_id failed: status=%s body=%s",
            resp.status_code,
            (resp.text or "")[:200],
        )
        return False
    except Exception as e:
        logger.warning("Clerk PATCH external_id raised: %s", e)
        return False


def _self_heal_assign_uuid(
    clerk_sub: str, email: Optional[str]
) -> str:
    """Allocate a UUID for this Clerk user.

    Atomic transaction inserts the clerk_user_map row, queues a
    pending-sync retry record, and upserts a user_roles row. Then we
    best-effort PATCH Clerk's external_id; on success we update
    clerk_synced_at and drop the pending-sync row.

    Returns the resolved datasnoop_user_id (str). On any racing
    concurrent insert, returns the row that won the race.
    """
    new_id = str(uuid.uuid4())
    resolved_id = new_id

    try:
        from db import get_conn  # local import — avoids db boot when env missing
    except Exception:
        # If we can't even import db, we cannot self-heal. Surface the new
        # UUID anyway — the caller will treat the JWT as authenticated for
        # this request. The webhook path will reconcile on the next event.
        return new_id

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
                    (clerk_sub, new_id),
                )
                row = cur.fetchone()
                if row is None:
                    # Lost the race — read whatever's there.
                    cur.execute(
                        "SELECT datasnoop_user_id FROM clerk_user_map WHERE clerk_sub = %s",
                        (clerk_sub,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        resolved_id = str(existing[0])
                else:
                    resolved_id = str(row[0])

                # Queue retry record INSIDE the same transaction (gemma4 R19).
                # If we crash between commit + PATCH, the worker still sees this row.
                cur.execute(
                    """
                    INSERT INTO clerk_pending_sync (clerk_sub, datasnoop_user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (clerk_sub) DO NOTHING
                    """,
                    (clerk_sub, resolved_id),
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
        logger.exception("clerk self-heal transaction failed")
        return new_id

    # Best-effort PATCH outside the transaction.
    if _patch_clerk_external_id(clerk_sub, resolved_id):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clerk_user_map SET clerk_synced_at = now() WHERE clerk_sub = %s",
                        (clerk_sub,),
                    )
                    cur.execute(
                        "DELETE FROM clerk_pending_sync WHERE clerk_sub = %s",
                        (clerk_sub,),
                    )
                conn.commit()
        except Exception:
            logger.exception("clerk self-heal post-PATCH cleanup failed")

    return resolved_id


def get_clerk_user_from_payload(
    payload: dict, conn=None
) -> dict:
    """Resolve a Clerk JWT payload to a DataSnoop user dict.

    Returns {id, email, role, payload}. `id` is the canonical
    DataSnoop UUID (from clerk_user_map). `role` is left as None in
    Phase 3 — the existing user_roles flow + admin grant pathway
    continues to be the source of truth. Callers that need a role
    can resolve it via the existing user_roles SELECT.
    """
    sub = payload.get("sub")
    if not sub:
        raise JWTError("Clerk payload missing sub")

    # Email may live under a few claim names depending on JWT template.
    email = (
        payload.get("email")
        or payload.get("primary_email_address")
        or payload.get("email_address")
    )

    datasnoop_id: Optional[str] = None

    # Lookup. Use the supplied conn if given (lets tests inject a mock).
    try:
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT datasnoop_user_id FROM clerk_user_map WHERE clerk_sub = %s",
                    (sub,),
                )
                row = cur.fetchone()
                if row:
                    datasnoop_id = str(row[0])
        else:
            from db import fetch_one
            row = fetch_one(
                "SELECT datasnoop_user_id FROM clerk_user_map WHERE clerk_sub = %s",
                (sub,),
            )
            if row:
                datasnoop_id = str(row.get("datasnoop_user_id"))
    except Exception:
        logger.exception("clerk_user_map lookup failed")

    if not datasnoop_id:
        datasnoop_id = _self_heal_assign_uuid(sub, email)

    return {
        "id": datasnoop_id,
        "email": email,
        "role": None,
        "payload": payload,
    }
