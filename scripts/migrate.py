#!/usr/bin/env python3
"""Minimal DataSnoop schema migration runner.

Week-1a scope only: baseline registration, status, up, and mark-applied.
Dry-run, checksum enforcement, deploy hooks, and CI style gates land later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg2
import psycopg2.extras


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
SCHEMA_SQL = REPO_ROOT / "src" / "schema.sql"
LOCK_ID = 742650198842601001

TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations ( -- ALLOW-RUNTIME-DDL: migration runner bootstrap table
    filename       TEXT PRIMARY KEY,
    applied_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum       TEXT,
    applied_by_env TEXT NOT NULL
);
"""

TX_RE = re.compile(
    r"^\s*(BEGIN(?:\s+(?:WORK|TRANSACTION))?|START\s+TRANSACTION|"
    r"COMMIT(?:\s+(?:WORK|TRANSACTION))?|ROLLBACK(?:\s+(?:WORK|TRANSACTION))?)\s*;",
    re.IGNORECASE | re.MULTILINE,
)
HEADER_RE = re.compile(r"^--\s*@migration:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
BASELINE_RE = re.compile(r"^--\s*BASELINE_AS_OF:\s*(?P<date>\S+)", re.MULTILINE)


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
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_target_env(target: str) -> tuple[dict[str, str], str | None]:
    env = dict(os.environ)
    staging_database_url: str | None = None

    for path in (REPO_ROOT / ".env",):
        env.update({k: v for k, v in parse_env_file(path).items() if k not in env})

    if target == "prod":
        for path in (REPO_ROOT / ".env.production", Path("/opt/leadpeek/.env.production")):
            env.update(parse_env_file(path))
    elif target == "staging":
        for path in (REPO_ROOT / ".env.staging", Path("/opt/leadpeek/.env.staging")):
            parsed = parse_env_file(path)
            if parsed.get("DATABASE_URL"):
                staging_database_url = parsed["DATABASE_URL"]
            env.update(parsed)

    return env, staging_database_url


def database_url_for_target(target: str) -> str:
    env, staging_database_url = load_target_env(target)

    if target == "prod":
        for key in ("MIGRATE_PROD_DATABASE_URL", "PROD_DATABASE_URL", "HETZNER_PG_URL", "DATABASE_URL"):
            if env.get(key):
                return env[key]
    elif target == "staging":
        for key in (
            "MIGRATE_STAGING_DATABASE_URL",
            "STAGING_DATABASE_URL",
            "DATABASE_URL_STAGING",
            "HETZNER_STAGING_PG_URL",
        ):
            if env.get(key):
                return env[key]
        if staging_database_url:
            return staging_database_url
    elif target in {"ci", "local"}:
        for key in ("MIGRATE_DATABASE_URL", "DATABASE_URL"):
            if env.get(key):
                return env[key]
    else:
        raise SystemExit(f"Unsupported target: {target}")

    raise SystemExit(f"Database URL not configured for target {target!r}")


def connect(target: str):
    return psycopg2.connect(
        database_url_for_target(target),
        connect_timeout=10,
        application_name=f"datasnoop:migrate:{target}",
    )


def baseline_as_of() -> str:
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    match = BASELINE_RE.search(text)
    if not match:
        raise SystemExit("src/schema.sql is missing -- BASELINE_AS_OF header")
    return match.group("date")


def migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(
        path
        for path in MIGRATIONS_DIR.glob("*.sql")
        if path.is_file() and not path.name.endswith("_rollback.sql")
    )


def parse_migration(path: Path) -> Migration:
    sql = path.read_text(encoding="utf-8")
    header_values: list[str] = []
    for line in sql.splitlines()[:20]:
        match = HEADER_RE.match(line)
        if match:
            header_values.append(match.group("value").strip())

    mode = "tx"
    lock_timeout = "5s"
    statement_timeout = "60s"
    for value in header_values:
        lower = value.lower()
        if lower in {"tx", "no-tx"}:
            mode = lower
        elif lower.startswith("lock_timeout="):
            lock_timeout = value.split("=", 1)[1].strip()
        elif lower.startswith("statement_timeout="):
            statement_timeout = value.split("=", 1)[1].strip()

    if mode not in {"tx", "no-tx"}:
        raise SystemExit(f"{path}: invalid migration mode {mode!r}")
    if mode == "tx" and TX_RE.search(strip_sql_comments(sql)):
        raise SystemExit(f"{path}: tx migration contains explicit BEGIN/COMMIT/ROLLBACK")

    return Migration(
        path=path,
        filename=path.name,
        sql=sql,
        checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
        mode=mode,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
    )


def strip_sql_comments(sql: str) -> str:
    lines = []
    for line in sql.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    quote: str | None = None
    dollar_tag: str | None = None
    line_comment = False
    block_comment = False

    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if line_comment:
            buf.append(ch)
            if ch == "\n":
                line_comment = False
            i += 1
            continue

        if block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                block_comment = False
                i += 2
            else:
                i += 1
            continue

        if quote:
            buf.append(ch)
            if ch == quote:
                if nxt == quote:
                    buf.append(nxt)
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue

        if ch == "-" and nxt == "-":
            buf.extend([ch, nxt])
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            buf.extend([ch, nxt])
            block_comment = True
            i += 2
            continue
        if ch in {"'", '"'}:
            buf.append(ch)
            quote = ch
            i += 1
            continue
        if ch == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if match:
                dollar_tag = match.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def table_exists(cur) -> bool:
    cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
    return bool(first_column(cur.fetchone()))


def ensure_tracking_table(cur, baseline: str) -> None:
    cur.execute(TRACKING_DDL)
    cur.execute(
        "COMMENT ON TABLE schema_migrations IS %s",
        (f"DataSnoop schema baseline: BASELINE_AS_OF={baseline}",),
    )


def applied_rows(cur) -> dict[str, dict]:
    if not table_exists(cur):
        return {}
    cur.execute(
        """
        SELECT filename, applied_at, checksum, applied_by_env
        FROM schema_migrations
        ORDER BY filename
        """
    )
    return {row["filename"]: dict(row) for row in cur.fetchall()}


def checksum_mismatches(migrations: list[Migration], applied: dict[str, dict]) -> list[dict[str, str | None]]:
    mismatches: list[dict[str, str | None]] = []
    for migration in migrations:
        row = applied.get(migration.filename)
        if not row:
            continue
        applied_checksum = row.get("checksum")
        if applied_checksum != migration.checksum:
            mismatches.append(
                {
                    "filename": migration.filename,
                    "applied_checksum": applied_checksum,
                    "file_checksum": migration.checksum,
                }
            )
    return mismatches


def require_clean_checksums(migrations: list[Migration], applied: dict[str, dict]) -> None:
    mismatches = checksum_mismatches(migrations, applied)
    if not mismatches:
        return
    names = ", ".join(item["filename"] or "<unknown>" for item in mismatches)
    raise SystemExit(f"Applied migration checksum mismatch: {names}")


@contextmanager
def advisory_lock(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
        locked = bool(cur.fetchone()[0])
    if not locked:
        raise SystemExit("Another schema migration run holds the advisory lock")
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def current_database(cur) -> str:
    cur.execute("SELECT current_database()")
    return str(first_column(cur.fetchone()))


def first_column(row):
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def set_timeouts(cur, lock_timeout: str, statement_timeout: str, local: bool) -> None:
    scope = "LOCAL " if local else ""
    cur.execute(f"SET {scope}lock_timeout = %s", (lock_timeout,))
    cur.execute(f"SET {scope}statement_timeout = %s", (statement_timeout,))


def command_baseline(args) -> int:
    target = require_target(args)
    baseline = baseline_as_of()
    migrations = [parse_migration(path) for path in migration_files()]

    conn = connect(target)
    try:
        with advisory_lock(conn):
            with conn:
                with conn.cursor() as cur:
                    db_name = current_database(cur)
                    ensure_tracking_table(cur, baseline)
                    for migration in migrations:
                        cur.execute(
                            """
                            INSERT INTO schema_migrations (filename, checksum, applied_by_env)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (filename) DO NOTHING
                            """,
                            (migration.filename, migration.checksum, target),
                        )
            print(f"database: {db_name}")
            print(f"baseline_as_of: {baseline}")
            print(f"registered_migrations: {len(migrations)}")
    finally:
        conn.close()
    return 0


def command_status(args) -> int:
    target = args.target or os.getenv("MIGRATE_TARGET") or "prod"
    args.target = target
    baseline = baseline_as_of()
    migrations = [parse_migration(path) for path in migration_files()]

    conn = connect(target)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            db_name = current_database(cur)
            exists = table_exists(cur)
            applied = applied_rows(cur) if exists else {}
    finally:
        conn.close()

    filenames = [m.filename for m in migrations]
    pending = [name for name in filenames if name not in applied]
    extra = [name for name in applied if name not in filenames]
    mismatches = checksum_mismatches(migrations, applied)

    result = {
        "target": target,
        "database": db_name,
        "baseline_as_of": baseline,
        "schema_migrations_exists": exists,
        "counts": {
            "files": len(filenames),
            "applied": len([name for name in filenames if name in applied]),
            "pending": len(pending),
            "extra_applied": len(extra),
            "checksum_mismatches": len(mismatches),
        },
        "migration_files": filenames,
        "pending": pending,
        "extra_applied": extra,
        "checksum_mismatches": mismatches,
    }

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"target: {target}")
        print(f"database: {db_name}")
        print(f"baseline_as_of: {baseline}")
        print(f"schema_migrations_exists: {exists}")
        print(f"files: {len(filenames)}")
        print(f"applied: {result['counts']['applied']}")
        print(f"pending: {len(pending)}")
        print(f"checksum_mismatches: {len(mismatches)}")
        if pending:
            for name in pending:
                print(f"  pending: {name}")
        if mismatches:
            for item in mismatches:
                print(f"  checksum_mismatch: {item['filename']}")
    return 1 if mismatches else 0


def command_dry_run(args) -> int:
    target = require_target(args)
    baseline = baseline_as_of()
    migrations = [parse_migration(path) for path in migration_files()]

    conn = connect(target)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            db_name = current_database(cur)
            exists = table_exists(cur)
            applied = applied_rows(cur) if exists else {}
    finally:
        conn.close()

    pending = [migration for migration in migrations if migration.filename not in applied]
    mismatches = checksum_mismatches(migrations, applied)

    print(f"target: {target}")
    print(f"database: {db_name}")
    print(f"baseline_as_of: {baseline}")
    print(f"schema_migrations_exists: {exists}")
    print(f"pending: {len(pending)}")
    for migration in pending:
        print(f"  would_apply: {migration.filename} ({migration.mode})")
    if mismatches:
        print(f"checksum_mismatches: {len(mismatches)}")
        for item in mismatches:
            print(f"  checksum_mismatch: {item['filename']}")
        return 1
    return 0


def command_up(args) -> int:
    target = require_target(args)
    baseline = baseline_as_of()
    migrations = [parse_migration(path) for path in migration_files()]

    conn = connect(target)
    applied_count = 0
    try:
        with advisory_lock(conn):
            with conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    db_name = current_database(cur)
                    ensure_tracking_table(cur, baseline)
                    applied = applied_rows(cur)
                    require_clean_checksums(migrations, applied)

            for migration in migrations:
                if migration.filename in applied:
                    continue
                apply_migration(conn, migration, target)
                applied_count += 1

        print(f"database: {db_name}")
        if applied_count == 0:
            print("No pending migrations.")
        else:
            print(f"Applied {applied_count} migration(s).")
    finally:
        conn.close()
    return 0


def apply_migration(conn, migration: Migration, target: str) -> None:
    if migration.mode == "tx":
        with conn:
            with conn.cursor() as cur:
                set_timeouts(cur, migration.lock_timeout, migration.statement_timeout, local=True)
                cur.execute(migration.sql)
                record_applied(cur, migration, target)
        return

    old_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            set_timeouts(cur, migration.lock_timeout, migration.statement_timeout, local=False)
            for statement in split_sql_statements(migration.sql):
                cur.execute(statement)
            record_applied(cur, migration, target)
    finally:
        conn.autocommit = old_autocommit


def record_applied(cur, migration: Migration, target: str) -> None:
    cur.execute(
        """
        INSERT INTO schema_migrations (filename, checksum, applied_by_env)
        VALUES (%s, %s, %s)
        """,
        (migration.filename, migration.checksum, target),
    )


def command_mark_applied(args) -> int:
    target = require_target(args)
    baseline = baseline_as_of()
    path = MIGRATIONS_DIR / args.filename
    if not path.exists() or path.parent != MIGRATIONS_DIR:
        raise SystemExit(f"Migration file not found in migrations/: {args.filename}")
    migration = parse_migration(path)

    conn = connect(target)
    try:
        with advisory_lock(conn):
            with conn:
                with conn.cursor() as cur:
                    db_name = current_database(cur)
                    ensure_tracking_table(cur, baseline)
                    cur.execute(
                        """
                        INSERT INTO schema_migrations (filename, checksum, applied_by_env)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (filename) DO NOTHING
                        """,
                        (migration.filename, migration.checksum, target),
                    )
        print(f"database: {db_name}")
        print(f"marked_applied: {migration.filename}")
    finally:
        conn.close()
    return 0


def require_target(args) -> str:
    if not args.target:
        raise SystemExit(f"{args.command} requires explicit --target")
    return args.target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline = subparsers.add_parser("baseline", help="create schema_migrations and mark current files applied")
    baseline.add_argument("--target", choices=["prod", "staging", "ci", "local"])
    baseline.set_defaults(func=command_baseline)

    status = subparsers.add_parser("status", help="show migration status without mutating the database")
    status.add_argument("--target", choices=["prod", "staging", "ci", "local"])
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    up = subparsers.add_parser("up", help="apply pending post-baseline migrations")
    up.add_argument("--target", choices=["prod", "staging", "ci", "local"])
    up.set_defaults(func=command_up)

    dry_run = subparsers.add_parser("dry-run", help="show pending migrations without applying them")
    dry_run.add_argument("--target", choices=["prod", "staging", "ci", "local"])
    dry_run.set_defaults(func=command_dry_run)

    mark = subparsers.add_parser("mark-applied", help="record one migration without running it")
    mark.add_argument("filename")
    mark.add_argument("--target", choices=["prod", "staging", "ci", "local"])
    mark.set_defaults(func=command_mark_applied)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except psycopg2.Error as exc:
        first_line = str(exc).splitlines()[0] if str(exc).splitlines() else exc.__class__.__name__
        print(
            f"ERROR: database operation failed for {getattr(args, 'target', None) or 'default target'}: {first_line}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
