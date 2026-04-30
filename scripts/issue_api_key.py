"""Issue a new public-API key for a customer.

Generates a high-entropy random token, stores its SHA-256 hash in the
`api_keys` table, and prints the raw token ONCE. The raw token is never
written anywhere persistent — copy it from the script output and hand it
to the customer immediately. If you lose it, revoke and reissue.

Usage:
    python scripts/issue_api_key.py --label "Customer X webshop"
    python scripts/issue_api_key.py --label "Test client" --daily-cap 1000
    python scripts/issue_api_key.py --label "Foo" --notes "rotated 2026-05-01"

Token format: ``dsk_live_<32-base64url-chars>``
    - ``dsk_`` = "DataSnoop key" prefix, easy to spot in logs / leaked secrets
    - ``live`` = environment marker (reserved for future ``test`` keys)
    - 32 random base64url chars = ~192 bits of entropy
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from pathlib import Path

# Resolve import paths for both `python scripts/...` and inside-container use.
ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

for env_path in (ROOT / ".env", ROOT / ".env.production"):
    if env_path.exists():
        load_dotenv(env_path)
        break

from db import execute, fetch_one  # noqa: E402


def _generate_token() -> str:
    """Return a fresh ``dsk_live_<32-chars>`` token."""
    # token_urlsafe(24) returns ~32 base64url characters (no padding)
    return f"dsk_live_{secrets.token_urlsafe(24)}"


def _hash(token: str) -> str:
    """Hex-encoded SHA-256 of the token bytes — what we store in the DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_table() -> None:
    """Legacy hook retained for call-site compatibility.

    The api_keys table is managed by tracked migrations now; operators should
    run migrations before issuing keys in a new environment.
    """


def main() -> int:
    ap = argparse.ArgumentParser(description="Issue a new public-API key")
    ap.add_argument("--label", required=True, help="Human-readable label, e.g. 'Customer X webshop'")
    ap.add_argument("--daily-cap", type=int, default=10000, help="Max calls/24h (circuit breaker, default 10000)")
    ap.add_argument("--notes", default=None, help="Optional notes (e.g. contact email, rotation reason)")
    args = ap.parse_args()

    if args.daily_cap <= 0:
        print("ERROR: --daily-cap must be > 0", file=sys.stderr)
        return 2

    _ensure_table()

    # Loop on collision (vanishingly unlikely with 192-bit entropy, but cheap to guard).
    for _ in range(5):
        token = _generate_token()
        token_hash = _hash(token)
        existing = fetch_one("SELECT 1 FROM api_keys WHERE key_hash = %s", (token_hash,))
        if not existing:
            break
    else:
        print("ERROR: 5 token collisions in a row — entropy source broken?", file=sys.stderr)
        return 1

    prefix = token[:12]  # e.g. 'dsk_live_K9p'
    execute(
        """
        INSERT INTO api_keys (key_hash, key_prefix, label, daily_cap, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (token_hash, prefix, args.label, args.daily_cap, args.notes),
    )

    row = fetch_one(
        "SELECT id, created_at FROM api_keys WHERE key_hash = %s",
        (token_hash,),
    )

    print()
    print("=" * 64)
    print("  NEW PUBLIC-API KEY ISSUED")
    print("=" * 64)
    print(f"  ID         : {row['id']}")
    print(f"  Label      : {args.label}")
    print(f"  Prefix     : {prefix}…")
    print(f"  Daily cap  : {args.daily_cap} calls / 24h")
    print(f"  Created    : {row['created_at']}")
    print()
    print("  Raw token (copy NOW — will never be shown again):")
    print()
    print(f"    {token}")
    print()
    print("  Hand this to the customer. They send it as:")
    print(f"    Authorization: Bearer {token}")
    print("=" * 64)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
