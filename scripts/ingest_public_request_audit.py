#!/usr/bin/env python3
"""Ingest nginx access logs into public_request_audit.

Run this on the server, outside the request path. It stores hashed client IDs
and classified request facts only; raw IP addresses and raw user agents are not
written to Postgres.

Examples:
    python scripts/ingest_public_request_audit.py --source docker --since 24h
    docker logs leadpeek-nginx-1 | python scripts/ingest_public_request_audit.py --source stdin
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from request_audit import (  # noqa: E402
    client_type,
    event_hash,
    hash_client_ip,
    network_label_from_ptr,
    parse_nginx_access_line,
    safe_ip,
    verify_declared_bot,
)


INSERT_SQL = """
INSERT INTO public_request_audit (
    event_hash, source, client_hash, client_network, client_type,
    method, path, route_kind, cbe, status_code, response_bytes, referrer_path,
    ua_family, device_type, bot_family, is_verified_bot, is_ai_crawler,
    is_rsc_prefetch, created_at
) VALUES (
    %(event_hash)s, %(source)s, %(client_hash)s, %(client_network)s,
    %(client_type)s, %(method)s, %(path)s, %(route_kind)s, %(cbe)s,
    %(status_code)s, %(response_bytes)s, %(referrer_path)s, %(ua_family)s,
    %(device_type)s, %(bot_family)s, %(is_verified_bot)s, %(is_ai_crawler)s,
    %(is_rsc_prefetch)s, %(created_at)s
)
ON CONFLICT (event_hash) DO NOTHING
"""


def resolve_network_label(ip: str) -> str | None:
    try:
        import socket

        return network_label_from_ptr(socket.gethostbyaddr(ip)[0])
    except Exception:
        return None


def iter_lines(args: argparse.Namespace):
    if args.source == "stdin":
        yield from sys.stdin
        return

    if args.source == "file":
        with open(args.file, "r", encoding="utf-8", errors="replace") as handle:
            yield from handle
        return

    cmd = ["docker", "logs"]
    if args.since:
        cmd.extend(["--since", args.since])
    if args.tail:
        cmd.extend(["--tail", str(args.tail)])
    cmd.append(args.container)
    proc = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit(f"docker logs failed with exit code {proc.returncode}")
    yield from proc.stdout.splitlines()


def event_to_row(event, args: argparse.Namespace, salt: str) -> dict:
    verified_bot = False
    network_label = None
    can_resolve = safe_ip(event.client_ip)
    if args.verify_bots and can_resolve:
        verified_bot, network_label = verify_declared_bot(event.client_ip, event.bot_family)
    if can_resolve and network_label is None and (args.verify_bots or args.resolve_network):
        network_label = resolve_network_label(event.client_ip)

    ctype = client_type(event, verified_bot=verified_bot, network_label=network_label)
    return {
        "event_hash": event_hash(event, salt),
        "source": args.label,
        "client_hash": hash_client_ip(event.client_ip, salt),
        "client_network": network_label,
        "client_type": ctype,
        "method": event.method,
        "path": event.path[:1024],
        "route_kind": event.route_kind,
        "cbe": event.cbe,
        "status_code": event.status_code,
        "response_bytes": event.response_bytes,
        "referrer_path": event.referrer_path,
        "ua_family": event.ua_family,
        "device_type": event.device_type,
        "bot_family": event.bot_family,
        "is_verified_bot": verified_bot,
        "is_ai_crawler": event.is_ai_crawler,
        "is_rsc_prefetch": event.is_rsc_prefetch,
        "created_at": event.created_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["docker", "file", "stdin"], default="docker")
    parser.add_argument("--container", default="leadpeek-nginx-1")
    parser.add_argument("--file")
    parser.add_argument("--since", default="24h")
    parser.add_argument("--tail")
    parser.add_argument("--label", default="nginx")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-bots", action="store_true")
    parser.add_argument("--resolve-network", action="store_true")
    args = parser.parse_args()

    if args.source == "file" and not args.file:
        parser.error("--file is required when --source=file")

    salt = os.getenv("ACTIVITY_LOG_IP_SALT")
    if not salt or salt == "change_me_to_a_long_random_string":
        raise SystemExit("ACTIVITY_LOG_IP_SALT must be set for stable hashed client IDs")

    rows = []
    scanned = 0
    skipped = 0
    route_counts = Counter()
    client_counts = Counter()
    for line in iter_lines(args):
        if args.limit and scanned >= args.limit:
            break
        scanned += 1
        event = parse_nginx_access_line(line.rstrip("\n"))
        if event is None:
            skipped += 1
            continue
        if event.route_kind == "asset":
            continue
        row = event_to_row(event, args, salt)
        route_counts[row["route_kind"]] += 1
        client_counts[row["client_type"]] += 1
        rows.append(row)

    inserted = 0
    if args.dry_run:
        inserted = 0
    else:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise SystemExit("DATABASE_URL is required unless --dry-run is used")
        conn = psycopg2.connect(database_url)
        try:
            with conn, conn.cursor() as cur:
                for row in rows:
                    cur.execute(INSERT_SQL, row)
                    inserted += cur.rowcount
        finally:
            conn.close()

    print(f"scanned={scanned} parsed={len(rows)} skipped={skipped} inserted={inserted}")
    print("routes=" + ",".join(f"{k}:{v}" for k, v in route_counts.most_common()))
    print("clients=" + ",".join(f"{k}:{v}" for k, v in client_counts.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
