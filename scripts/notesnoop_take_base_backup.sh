#!/bin/bash
# Physical base backup for the dedicated NoteSnoop Postgres instance.

set -euo pipefail

ENV_FILE="${NOTESNOOP_ENV_FILE:-/opt/leadpeek/.env.production}"
PG_BIN_DIR="${PG_BIN_DIR:-/usr/lib/postgresql/16/bin}"
PG_BASEBACKUP="${PG_BIN_DIR}/pg_basebackup"
LOCK_FILE="${LOCK_FILE:-/var/lock/notesnoop-base-backup.lock}"
KEEP_BASE_BACKUPS="${KEEP_BASE_BACKUPS:-2}"

while [ "${1:-}" != "" ]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--env-file /path/to/env]" >&2
      exit 2
      ;;
  esac
done

env_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 1
  python3 - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
for raw in path.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() == key:
        value = value.strip().strip('"').strip("'")
        print(value)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -x "$PG_BASEBACKUP" ] || fail "$PG_BASEBACKUP not executable"

BACKUP_DIR="$(env_value NOTESNOOP_BASE_BACKUP_DIR || echo /mnt/volume-hel1-1/notesnoop-base-backup)"
PGHOST="$(env_value NOTESNOOP_POSTGRES_BACKUP_HOST || echo 127.0.0.1)"
PGPORT="$(env_value NOTESNOOP_POSTGRES_HOST_PORT || echo 5433)"
PGUSER="$(env_value NOTESNOOP_POSTGRES_ADMIN_USER || echo notesnoop_admin)"
PGDATABASE="$(env_value NOTESNOOP_POSTGRES_DB || echo notesnoop)"
PGPASSWORD="$(env_value NOTESNOOP_POSTGRES_ADMIN_PASSWORD || true)"

[ -n "$PGPASSWORD" ] || fail "NOTESNOOP_POSTGRES_ADMIN_PASSWORD missing in $ENV_FILE"
case "$BACKUP_DIR" in
  /|/bin|/boot|/dev|/etc|/home|/mnt|/opt|/proc|/root|/run|/srv|/sys|/tmp|/usr|/var)
    fail "NOTESNOOP_BASE_BACKUP_DIR=$BACKUP_DIR refuses prune"
    ;;
esac

install -d -m 700 "$BACKUP_DIR"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/base-$ts"
partial="$target.partial"

cleanup() {
  rm -rf -- "$partial"
}
trap cleanup EXIT

(
  flock -n 9 || fail "another NoteSnoop base backup is already running"
  rm -rf -- "$partial"
  PGPASSWORD="$PGPASSWORD" "$PG_BASEBACKUP" \
    -h "$PGHOST" \
    -p "$PGPORT" \
    -U "$PGUSER" \
    -D "$partial" \
    -Fp \
    -Xs \
    -P \
    -c fast \
    -d "dbname=$PGDATABASE"
  mv "$partial" "$target"
  ln -sfn "$(basename "$target")" "$BACKUP_DIR/base-latest"

  if [[ "$KEEP_BASE_BACKUPS" =~ ^[0-9]+$ ]] && [ "$KEEP_BASE_BACKUPS" -gt 0 ]; then
    mapfile -t backups < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'base-*' -printf '%f\n' | sort)
    prune_count=$((${#backups[@]} - KEEP_BASE_BACKUPS))
    if [ "$prune_count" -gt 0 ]; then
      for name in "${backups[@]:0:$prune_count}"; do
        rm -rf -- "$BACKUP_DIR/$name"
      done
    fi
  fi
  echo "NoteSnoop base backup complete: $target"
) 9>"$LOCK_FILE"
