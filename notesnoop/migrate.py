#!/usr/bin/env python3
"""NoteSnoop migration runner.

This mirrors the platform migration pattern while keeping NoteSnoop's schema
history separate from Datasnoop. It applies SQL files from notesnoop/migrations
and records checksums in notesnoop.schema_migrations.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
import psycopg2.extras


ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = ROOT / "migrations"
LOCK_ID = 8819220509

HEADER_RE = re.compile(r"^--\s*@migration:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
TX_RE = re.compile(
    r"^\s*(BEGIN(?:\s+(?:WORK|TRANSACTION))?|START\s+TRANSACTION|"
    r"COMMIT(?:\s+(?:WORK|TRANSACTION))?|ROLLBACK(?:\s+(?:WORK|TRANSACTION))?)\s*;",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Migration:
    path: Path
    filename: str
    sql: str
    checksum: str
    mode: str
    lock_timeout: str
    statement_timeout: str


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except PermissionError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def database_url(target: str) -> str:
    repo_root = ROOT.parent
    env = dict(os.environ)
    for path in (repo_root / ".env", repo_root / ".env.local"):
        env.update({k: v for k, v in parse_env_file(path).items() if k not in env})
    if target == "staging":
        for path in (repo_root / ".env.staging", Path("/opt/leadpeek/.env.staging")):
            env.update(parse_env_file(path))
        keys = ("NOTESNOOP_DATABASE_URL", "MIGRATE_STAGING_DATABASE_URL", "STAGING_DATABASE_URL", "DATABASE_URL")
    elif target == "prod":
        for path in (repo_root / ".env.production", Path("/opt/leadpeek/.env.production")):
            env.update(parse_env_file(path))
        keys = ("NOTESNOOP_DATABASE_URL", "MIGRATE_PROD_DATABASE_URL", "PROD_DATABASE_URL", "DATABASE_URL")
    else:
        keys = ("NOTESNOOP_TEST_DATABASE_URL", "MIGRATE_DATABASE_URL", "DATABASE_URL")
    for key in keys:
        if env.get(key):
            return env[key]
    raise SystemExit(f"No database URL configured for target {target!r}")


def connect(target: str):
    return psycopg2.connect(
        database_url(target),
        connect_timeout=10,
        application_name=f"notesnoop:migrate:{target}",
    )


def strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def parse_migration(path: Path) -> Migration:
    sql = path.read_text(encoding="utf-8")
    mode = "tx"
    lock_timeout = "5s"
    statement_timeout = "60s"
    for line in sql.splitlines()[:20]:
        match = HEADER_RE.match(line)
        if not match:
            continue
        value = match.group("value").strip()
        lower = value.lower()
        if lower in {"tx", "no-tx"}:
            mode = lower
        elif lower.startswith("lock_timeout="):
            lock_timeout = value.split("=", 1)[1].strip()
        elif lower.startswith("statement_timeout="):
            statement_timeout = value.split("=", 1)[1].strip()
    if mode == "tx" and TX_RE.search(strip_sql_comments(sql)):
        raise SystemExit(f"{path}: tx migration contains explicit transaction control")
    return Migration(
        path=path,
        filename=path.name,
        sql=sql,
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        mode=mode,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
    )


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())


def migrations() -> list[Migration]:
    return [parse_migration(path) for path in migration_files()]


def ensure_tracking(cur) -> None:
    cur.execute("CREATE SCHEMA IF NOT EXISTS notesnoop")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notesnoop.schema_migrations (
          filename TEXT PRIMARY KEY,
          checksum TEXT NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          applied_by_env TEXT NOT NULL
        )
        """
    )


def applied(cur) -> dict[str, dict]:
    ensure_tracking(cur)
    cur.execute(
        "SELECT filename, checksum, applied_at, applied_by_env FROM notesnoop.schema_migrations ORDER BY filename"
    )
    return {row["filename"]: dict(row) for row in cur.fetchall()}


def set_timeouts(cur, migration: Migration) -> None:
    cur.execute("SET LOCAL lock_timeout = %s", (migration.lock_timeout,))
    cur.execute("SET LOCAL statement_timeout = %s", (migration.statement_timeout,))


def first_column(row):
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def advisory_lock(cur) -> None:
    cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
    if not first_column(cur.fetchone()):
        raise SystemExit("Another NoteSnoop migration run holds the advisory lock")


def advisory_unlock(cur) -> None:
    cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def command_status(args) -> int:
    conn = connect(args.target)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows = applied(cur)
            files = migrations()
            mismatches = [
                m.filename for m in files if m.filename in rows and rows[m.filename]["checksum"] != m.checksum
            ]
            pending = [m.filename for m in files if m.filename not in rows]
            cur.execute("SELECT current_database()")
            print(f"target: {args.target}")
            print(f"database: {cur.fetchone()['current_database']}")
            print(f"files: {len(files)}")
            print(f"applied: {len(files) - len(pending)}")
            print(f"pending: {len(pending)}")
            print(f"checksum_mismatches: {len(mismatches)}")
            for name in pending:
                print(f"  pending: {name}")
            for name in mismatches:
                print(f"  checksum_mismatch: {name}")
            return 1 if mismatches else 0
    finally:
        conn.close()


def command_up(args) -> int:
    conn = connect(args.target)
    count = 0
    try:
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                advisory_lock(cur)
        try:
            for migration in migrations():
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    rows = applied(cur)
                    if migration.filename in rows:
                        if rows[migration.filename]["checksum"] != migration.checksum:
                            raise SystemExit(f"Checksum mismatch for {migration.filename}")
                        continue
                with conn:
                    with conn.cursor() as cur:
                        set_timeouts(cur, migration)
                        cur.execute(migration.sql)
                        cur.execute(
                            """
                            INSERT INTO notesnoop.schema_migrations (filename, checksum, applied_by_env)
                            VALUES (%s, %s, %s)
                            """,
                            (migration.filename, migration.checksum, args.target),
                        )
                        count += 1
        finally:
            with conn:
                with conn.cursor() as cur:
                    advisory_unlock(cur)
        print(f"Applied {count} NoteSnoop migration(s).")
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, func in (("status", command_status), ("up", command_up)):
        p = sub.add_parser(command)
        p.add_argument("--target", choices=["local", "ci", "staging", "prod"], default="local")
        p.set_defaults(func=func)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except psycopg2.Error as exc:
        print(f"ERROR: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
