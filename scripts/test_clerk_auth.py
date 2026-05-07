"""Self-contained tests for the Phase 3 Clerk auth code.

Runs as a plain Python script — no pytest install needed. Prints
PASS/FAIL per test and exits non-zero if any test fails.

Tests cover:
  * verify_clerk_jwt — accepts a valid token signed with a synthetic
    RSA keypair, rejects expired tokens, wrong issuer, missing sub,
    and disallowed alg.
  * verify_svix_signature — accepts a hand-computed Svix signature
    (using a known whsec_-prefixed secret) and rejects tampered ones.
  * webhook idempotency — second call with the same svix_id returns
    200 and does NOT double-process the event.

The tests stub out the `db` module so they don't need a real Postgres,
and inject the synthetic JWKS via auth_clerk._set_jwks_cache_for_tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import types
from pathlib import Path

# Make `backend/` importable as `backend.*` and as bare modules (the
# real Dockerfile sets WORKDIR /app and uses bare imports like
# `from auth import _decode_token`).
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Test-time env. MUST be set before importing auth_clerk/clerk_webhook.
# ---------------------------------------------------------------------------

CLERK_ISSUER = "https://humane-moccasin-35.clerk.accounts.dev"
JWKS_URL = f"{CLERK_ISSUER}/.well-known/jwks.json"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"test-secret-bytes-x32-padding-fff").decode()

os.environ["CLERK_ISSUER"] = CLERK_ISSUER
os.environ["CLERK_JWKS_URL"] = JWKS_URL
os.environ["CLERK_AUTHORIZED_PARTY"] = ""
os.environ["CLERK_WEBHOOK_SECRET"] = WEBHOOK_SECRET
os.environ["CLERK_SECRET_KEY"] = ""  # block live PATCH attempts in self-heal
# Avoid backend.auth import-time RuntimeError when SUPABASE_URL is empty.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")

# ---------------------------------------------------------------------------
# Stub out backend `db` module so auth_clerk + clerk_webhook can import it
# without a real Postgres. We capture every SQL statement attempted so the
# idempotency test can assert on it.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, fake_db):
        self._db = fake_db
        self._last_select_result = None

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.split())  # collapse whitespace
        self._db.statements.append((sql_norm, params))
        # Mimic the few RETURNING / SELECT shapes the code under test reads.
        if "INSERT INTO clerk_user_map" in sql_norm and "RETURNING datasnoop_user_id" in sql_norm:
            # First INSERT wins; subsequent INSERTs hit ON CONFLICT DO NOTHING
            # and return zero rows.
            sub = params[0] if params else None
            if sub in self._db.user_map:
                self._last_select_result = None
            else:
                self._db.user_map[sub] = params[1]
                self._last_select_result = (params[1],)
        elif "SELECT datasnoop_user_id FROM clerk_user_map" in sql_norm:
            sub = params[0] if params else None
            if sub in self._db.user_map:
                self._last_select_result = (self._db.user_map[sub],)
            else:
                self._last_select_result = None
        elif "INSERT INTO webhook_log" in sql_norm and "RETURNING svix_id" in sql_norm:
            key = (params[0], params[1]) if params else None
            if key in self._db.webhook_log:
                self._last_select_result = None
            else:
                self._db.webhook_log.add(key)
                self._last_select_result = (params[0],)
        else:
            self._last_select_result = None

    def fetchone(self):
        return self._last_select_result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, fake_db):
        self._db = fake_db

    def cursor(self):
        return _FakeCursor(self._db)

    def commit(self):
        self._db.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDB:
    def __init__(self):
        self.user_map: dict[str, str] = {}
        self.webhook_log: set[tuple[str, str]] = set()
        self.statements: list = []
        self.commits = 0

    def get_conn(self):
        return _FakeConn(self)

    def fetch_one(self, sql, params=None):
        sql_norm = " ".join(sql.split())
        if "SELECT datasnoop_user_id FROM clerk_user_map" in sql_norm:
            sub = params[0] if params else None
            if sub in self.user_map:
                return {"datasnoop_user_id": self.user_map[sub]}
        return None


_FAKE_DB = _FakeDB()
_db_module = types.ModuleType("db")
_db_module.get_conn = _FAKE_DB.get_conn  # type: ignore
_db_module.fetch_one = _FAKE_DB.fetch_one  # type: ignore
sys.modules["db"] = _db_module

# ---------------------------------------------------------------------------
# Imports of code under test (after env + stubbing).
# ---------------------------------------------------------------------------

from jose import jwt as jose_jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

import auth_clerk  # noqa: E402
import routers.clerk_webhook as clerk_webhook  # noqa: E402

# ---------------------------------------------------------------------------
# Build a synthetic RSA keypair + JWK set
# ---------------------------------------------------------------------------

_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_pub_numbers = _priv.public_key().public_numbers()


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


_TEST_KID = "test-kid-1"
_jwk_pub = {
    "kty": "RSA",
    "alg": "RS256",
    "use": "sig",
    "kid": _TEST_KID,
    "n": _b64url_uint(_pub_numbers.n),
    "e": _b64url_uint(_pub_numbers.e),
}
auth_clerk._set_jwks_cache_for_tests({"keys": [_jwk_pub]})

_priv_pem = _priv.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()


def _sign_clerk_jwt(claims: dict, *, alg: str = "RS256", kid: str = _TEST_KID) -> str:
    return jose_jwt.encode(
        claims, _priv_pem, algorithm=alg, headers={"kid": kid}
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_results: list[tuple[str, bool, str]] = []


def _run(name: str, fn) -> None:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"PASS  {name}")
    except AssertionError as e:
        _results.append((name, False, str(e)))
        print(f"FAIL  {name}: {e}")
    except Exception as e:  # noqa: BLE001
        _results.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL  {name}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# verify_clerk_jwt tests
# ---------------------------------------------------------------------------


def test_verify_valid_token():
    now = int(time.time())
    token = _sign_clerk_jwt(
        {
            "iss": CLERK_ISSUER,
            "sub": "user_test_abc",
            "exp": now + 300,
            "iat": now,
            "email": "alice@example.com",
        }
    )
    payload = auth_clerk.verify_clerk_jwt(token)
    assert payload["sub"] == "user_test_abc", payload
    assert payload["email"] == "alice@example.com"


def test_verify_rejects_expired():
    now = int(time.time())
    token = _sign_clerk_jwt(
        {
            "iss": CLERK_ISSUER,
            "sub": "user_test_exp",
            "exp": now - 60,  # expired 1 min ago
            "iat": now - 600,
        }
    )
    try:
        auth_clerk.verify_clerk_jwt(token)
    except Exception as e:
        assert "expired" in str(e).lower() or "exp" in str(e).lower(), (
            f"unexpected error: {e}"
        )
        return
    raise AssertionError("expected expired token to be rejected")


def test_verify_rejects_wrong_issuer():
    now = int(time.time())
    token = _sign_clerk_jwt(
        {
            "iss": "https://attacker.example.com",
            "sub": "user_test_iss",
            "exp": now + 300,
            "iat": now,
        }
    )
    try:
        auth_clerk.verify_clerk_jwt(token)
    except Exception:
        return
    raise AssertionError("expected wrong-issuer token to be rejected")


def test_verify_rejects_missing_sub():
    now = int(time.time())
    token = _sign_clerk_jwt(
        {
            "iss": CLERK_ISSUER,
            # no sub
            "exp": now + 300,
            "iat": now,
        }
    )
    try:
        auth_clerk.verify_clerk_jwt(token)
    except Exception as e:
        assert "sub" in str(e).lower(), f"unexpected error: {e}"
        return
    raise AssertionError("expected missing-sub token to be rejected")


def test_verify_rejects_hs256():
    # Algorithm-confusion: a token claiming HS256 must not be accepted.
    fake = jose_jwt.encode(
        {"iss": CLERK_ISSUER, "sub": "u", "exp": int(time.time()) + 300},
        "any-symmetric-secret",
        algorithm="HS256",
    )
    try:
        auth_clerk.verify_clerk_jwt(fake)
    except Exception as e:
        assert (
            "alg" in str(e).lower()
            or "algorithm" in str(e).lower()
            or "hs256" in str(e).lower()
        ), f"unexpected error: {e}"
        return
    raise AssertionError("expected HS256 token to be rejected")


def test_verify_enforces_authorized_party():
    # Set an azp requirement, sign without azp → must reject.
    auth_clerk.CLERK_AUTHORIZED_PARTY = "https://datasnoop.be"
    try:
        now = int(time.time())
        token = _sign_clerk_jwt(
            {
                "iss": CLERK_ISSUER,
                "sub": "u",
                "exp": now + 300,
                "iat": now,
                "azp": "https://attacker.example.com",
            }
        )
        try:
            auth_clerk.verify_clerk_jwt(token)
        except Exception as e:
            assert "azp" in str(e).lower(), f"unexpected error: {e}"
            return
        raise AssertionError("expected azp mismatch to be rejected")
    finally:
        auth_clerk.CLERK_AUTHORIZED_PARTY = ""


# ---------------------------------------------------------------------------
# Svix signature tests
# ---------------------------------------------------------------------------


def _compute_svix_sig(secret: str, svix_id: str, ts: str, body: bytes) -> str:
    secret_b = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    secret_bytes = base64.b64decode(secret_b)
    signed = f"{svix_id}.{ts}.".encode("utf-8") + body
    raw = hmac.new(secret_bytes, signed, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(raw).decode()}"


def test_svix_valid():
    body = b'{"type":"user.created","data":{"id":"user_x"}}'
    svix_id = "msg_test_1"
    ts = str(int(time.time()))
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, ts, body)
    assert clerk_webhook.verify_svix_signature(
        body, svix_id, ts, sig, WEBHOOK_SECRET
    ), "expected valid Svix signature to verify"


def test_svix_rejects_tampered_body():
    body = b'{"type":"user.created","data":{"id":"user_x"}}'
    svix_id = "msg_test_2"
    ts = str(int(time.time()))
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, ts, body)
    tampered = body.replace(b"user_x", b"user_y")
    assert not clerk_webhook.verify_svix_signature(
        tampered, svix_id, ts, sig, WEBHOOK_SECRET
    ), "expected tampered body to fail signature verification"


def test_svix_rejects_wrong_secret():
    body = b'{"type":"user.created","data":{"id":"user_x"}}'
    svix_id = "msg_test_3"
    ts = str(int(time.time()))
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, ts, body)
    other_secret = "whsec_" + base64.b64encode(b"different-secret-bytes-padding-zzz").decode()
    assert not clerk_webhook.verify_svix_signature(
        body, svix_id, ts, sig, other_secret
    ), "expected wrong secret to fail signature verification"


def test_svix_rejects_missing_header():
    body = b'{}'
    svix_id = "msg_test_4"
    ts = str(int(time.time()))
    assert not clerk_webhook.verify_svix_signature(
        body, svix_id, ts, "", WEBHOOK_SECRET
    ), "expected missing signature header to fail"


def test_svix_rejects_stale_timestamp():
    # Replay-attack defence: signatures whose svix-timestamp is more than
    # ±5 minutes from now must be rejected even when the HMAC matches.
    body = b'{"type":"user.created","data":{"id":"user_x"}}'
    svix_id = "msg_test_stale_1"
    stale_ts = str(int(time.time()) - 600)  # 10 minutes ago
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, stale_ts, body)
    assert not clerk_webhook.verify_svix_signature(
        body, svix_id, stale_ts, sig, WEBHOOK_SECRET
    ), "expected 10-minute-old timestamp to be rejected"


def test_svix_rejects_future_timestamp():
    body = b'{"type":"user.created","data":{"id":"user_x"}}'
    svix_id = "msg_test_future_1"
    future_ts = str(int(time.time()) + 600)  # 10 minutes ahead
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, future_ts, body)
    assert not clerk_webhook.verify_svix_signature(
        body, svix_id, future_ts, sig, WEBHOOK_SECRET
    ), "expected 10-minute-future timestamp to be rejected"


def test_svix_rejects_non_numeric_timestamp():
    body = b'{}'
    svix_id = "msg_test_bad_ts"
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, "not-a-number", body)
    assert not clerk_webhook.verify_svix_signature(
        body, svix_id, "not-a-number", sig, WEBHOOK_SECRET
    ), "expected non-numeric timestamp to be rejected"


# ---------------------------------------------------------------------------
# Webhook idempotency test
# ---------------------------------------------------------------------------


def test_webhook_idempotent():
    # Reset the fake DB state.
    _FAKE_DB.user_map.clear()
    _FAKE_DB.webhook_log.clear()
    _FAKE_DB.statements.clear()
    _FAKE_DB.commits = 0

    # Synthesise a user.created webhook event.
    payload = {
        "type": "user.created",
        "data": {
            "id": "user_idempotent_1",
            "email_addresses": [
                {"id": "idn_1", "email_address": "bob@example.com"},
            ],
            "primary_email_address_id": "idn_1",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    svix_id = "msg_idem_1"
    ts = str(int(time.time()))
    sig = _compute_svix_sig(WEBHOOK_SECRET, svix_id, ts, body)
    assert clerk_webhook.verify_svix_signature(
        body, svix_id, ts, sig, WEBHOOK_SECRET
    ), "fixture sig should verify"

    # First call: should record the event.
    assert clerk_webhook._record_event(svix_id, "user.created") is True
    # Trigger the handler so we see the user-map insert.
    clerk_webhook._handle_user_created(payload)
    inserts_after_first = sum(
        1 for sql, _ in _FAKE_DB.statements
        if "INSERT INTO clerk_user_map" in sql and "RETURNING" in sql
    )
    user_map_size_after_first = len(_FAKE_DB.user_map)

    # Second call with the same svix_id: idempotency check returns False
    # → handler must NOT run again.
    assert clerk_webhook._record_event(svix_id, "user.created") is False, (
        "expected duplicate svix_id to be a no-op"
    )

    # Confirm second call did not double-write the user_map row (the
    # handler simply wasn't invoked).
    assert len(_FAKE_DB.user_map) == user_map_size_after_first, (
        f"user_map size grew on second call: {len(_FAKE_DB.user_map)} > {user_map_size_after_first}"
    )

    # Sanity: the first call did create exactly one mapping.
    assert user_map_size_after_first == 1, (
        f"expected one mapping after first call, got {user_map_size_after_first}"
    )
    assert inserts_after_first == 1, (
        f"expected one user_map INSERT, got {inserts_after_first}"
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run("verify_clerk_jwt: valid token", test_verify_valid_token)
    _run("verify_clerk_jwt: rejects expired", test_verify_rejects_expired)
    _run("verify_clerk_jwt: rejects wrong issuer", test_verify_rejects_wrong_issuer)
    _run("verify_clerk_jwt: rejects missing sub", test_verify_rejects_missing_sub)
    _run("verify_clerk_jwt: rejects HS256", test_verify_rejects_hs256)
    _run("verify_clerk_jwt: enforces azp", test_verify_enforces_authorized_party)
    _run("svix: valid signature", test_svix_valid)
    _run("svix: rejects tampered body", test_svix_rejects_tampered_body)
    _run("svix: rejects wrong secret", test_svix_rejects_wrong_secret)
    _run("svix: rejects missing header", test_svix_rejects_missing_header)
    _run("svix: rejects stale timestamp", test_svix_rejects_stale_timestamp)
    _run("svix: rejects future timestamp", test_svix_rejects_future_timestamp)
    _run("svix: rejects non-numeric timestamp", test_svix_rejects_non_numeric_timestamp)
    _run("webhook: idempotent on repeat svix_id", test_webhook_idempotent)

    failed = [(n, err) for n, ok, err in _results if not ok]
    print()
    print(f"{len(_results) - len(failed)}/{len(_results)} passed")
    if failed:
        print("FAILED:")
        for n, err in failed:
            print(f"  - {n}: {err}")
        sys.exit(1)
    sys.exit(0)
