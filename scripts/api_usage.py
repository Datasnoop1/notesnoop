"""Print usage stats for public-API keys.

Quick operator helper — saves typing SQL when you want to glance at how
much each key is being called. No admin dashboard needed for the v1 test.

Usage:
    python scripts/api_usage.py                  # all keys, summary
    python scripts/api_usage.py --key-id 3       # one key, daily breakdown for last 30 days
    python scripts/api_usage.py --days 7         # change window for the daily breakdown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv  # noqa: E402

for env_path in (ROOT / ".env", ROOT / ".env.production"):
    if env_path.exists():
        load_dotenv(env_path)
        break

from db import fetch_all  # noqa: E402


def _print_summary() -> None:
    """One row per key: total calls, today, last-7d, last-used."""
    rows = fetch_all(
        """
        SELECT k.id,
               k.label,
               k.key_prefix,
               k.daily_cap,
               k.disabled_at,
               k.created_at,
               COUNT(l.id)                                                   AS calls_total,
               COUNT(l.id) FILTER (WHERE l.created_at >= CURRENT_DATE)       AS calls_today,
               COUNT(l.id) FILTER (WHERE l.created_at >= NOW() - INTERVAL '7 days') AS calls_7d,
               MAX(l.created_at)                                             AS last_used,
               COUNT(l.id) FILTER (WHERE l.status_code >= 400)               AS errors
        FROM api_keys k
        LEFT JOIN api_call_log l ON l.api_key_id = k.id
        GROUP BY k.id
        ORDER BY k.id
        """
    )
    if not rows:
        print("No API keys issued yet.")
        return

    print()
    print(f"{'ID':>3}  {'PREFIX':<14}  {'LABEL':<32}  {'TODAY':>7}  {'CAP':>6}  {'7D':>7}  {'TOTAL':>8}  {'ERR':>5}  LAST USED")
    print("-" * 120)
    for r in rows:
        status = "" if r["disabled_at"] is None else " [DISABLED]"
        last = str(r["last_used"])[:19] if r["last_used"] else "(never)"
        print(
            f"{r['id']:>3}  "
            f"{r['key_prefix']:<14}  "
            f"{(r['label'] + status)[:32]:<32}  "
            f"{r['calls_today']:>7}  "
            f"{r['daily_cap']:>6}  "
            f"{r['calls_7d']:>7}  "
            f"{r['calls_total']:>8}  "
            f"{r['errors']:>5}  "
            f"{last}"
        )
    print()


def _print_key_detail(key_id: int, days: int) -> None:
    """Daily call breakdown + top VATs queried for one key."""
    meta = fetch_all(
        "SELECT id, label, key_prefix, daily_cap, disabled_at, created_at "
        "FROM api_keys WHERE id = %s",
        (key_id,),
    )
    if not meta:
        print(f"No key with id={key_id}", file=sys.stderr)
        sys.exit(1)
    k = meta[0]

    print()
    print(f"Key #{k['id']} — {k['label']}")
    print(f"  Prefix    : {k['key_prefix']}…")
    print(f"  Daily cap : {k['daily_cap']}")
    print(f"  Created   : {k['created_at']}")
    print(f"  Status    : {'DISABLED at ' + str(k['disabled_at']) if k['disabled_at'] else 'active'}")
    print()

    daily = fetch_all(
        """
        SELECT created_at::date AS day,
               COUNT(*)                                  AS total,
               COUNT(*) FILTER (WHERE status_code >= 400) AS errors,
               ROUND(AVG(latency_ms)::numeric, 0)        AS avg_ms
        FROM api_call_log
        WHERE api_key_id = %s
          AND created_at >= NOW() - (%s || ' days')::interval
        GROUP BY day
        ORDER BY day DESC
        """,
        (key_id, str(days)),
    )
    print(f"Daily calls (last {days} days):")
    if not daily:
        print("  (no calls yet)")
    else:
        print(f"  {'DAY':<12}  {'CALLS':>7}  {'ERRORS':>7}  {'AVG_MS':>7}")
        for d in daily:
            print(f"  {str(d['day']):<12}  {d['total']:>7}  {d['errors']:>7}  {d['avg_ms'] or 0:>7}")
    print()

    top_vats = fetch_all(
        """
        SELECT vat_queried, COUNT(*) AS n
        FROM api_call_log
        WHERE api_key_id = %s
          AND vat_queried IS NOT NULL
          AND created_at >= NOW() - (%s || ' days')::interval
        GROUP BY vat_queried
        ORDER BY n DESC
        LIMIT 10
        """,
        (key_id, str(days)),
    )
    print(f"Top VATs queried (last {days} days):")
    if not top_vats:
        print("  (no VATs queried)")
    else:
        for r in top_vats:
            print(f"  {r['vat_queried']}  ({r['n']} calls)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Public-API usage stats")
    ap.add_argument("--key-id", type=int, default=None, help="Show detail for one key")
    ap.add_argument("--days", type=int, default=30, help="Window for the daily breakdown (default 30)")
    args = ap.parse_args()

    if args.key_id is not None:
        _print_key_detail(args.key_id, args.days)
    else:
        _print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
