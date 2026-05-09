#!/bin/bash
# Restore-drill the dedicated NoteSnoop Postgres base backup into a disposable
# Docker volume/container. This script never prints database credentials.

set -euo pipefail

ENV_FILE="${NOTESNOOP_ENV_FILE:-/opt/leadpeek/.env.staging}"
POSTGRES_IMAGE="${NOTESNOOP_POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
RESTORE_PORT="${NOTESNOOP_RESTORE_DRILL_PORT:-15434}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
VOLUME_NAME="notesnoop_restore_drill_${TS}"
CONTAINER_NAME="notesnoop-restore-drill-${TS}"

while [ "${1:-}" != "" ]; do
  case "$1" in
    --env-file)
      ENV_FILE="${2:?--env-file requires a path}"
      shift 2
      ;;
    --backup)
      NOTESNOOP_RESTORE_BACKUP="${2:?--backup requires a path}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--env-file /path/to/env] [--backup /path/to/base-backup]" >&2
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
        print(value.strip().strip('"').strip("'"))
        raise SystemExit(0)
raise SystemExit(1)
PY
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -f "$ENV_FILE" ] || fail "$ENV_FILE missing"
command -v docker >/dev/null 2>&1 || fail "docker missing"

BASE_BACKUP_DIR="$(env_value NOTESNOOP_BASE_BACKUP_DIR || echo /mnt/volume-hel1-1/notesnoop-base-backup)"
BACKUP_PATH="${NOTESNOOP_RESTORE_BACKUP:-$BASE_BACKUP_DIR/base-latest}"
BACKUP_PATH="$(readlink -f "$BACKUP_PATH")"
[ -d "$BACKUP_PATH" ] || fail "backup directory missing: $BACKUP_PATH"
[ -f "$BACKUP_PATH/PG_VERSION" ] || fail "PG_VERSION missing in $BACKUP_PATH"

DB_NAME="$(env_value NOTESNOOP_POSTGRES_DB || echo notesnoop_staging)"
DB_USER="$(env_value NOTESNOOP_POSTGRES_ADMIN_USER || echo notesnoop_admin)"
DB_PASSWORD="$(env_value NOTESNOOP_POSTGRES_ADMIN_PASSWORD || true)"
[ -n "$DB_PASSWORD" ] || fail "NOTESNOOP_POSTGRES_ADMIN_PASSWORD missing in $ENV_FILE"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "NoteSnoop restore drill: backup=$BACKUP_PATH image=$POSTGRES_IMAGE"
docker volume create "$VOLUME_NAME" >/dev/null
docker run --rm \
  -v "$BACKUP_PATH:/backup:ro" \
  -v "$VOLUME_NAME:/restore" \
  busybox sh -c "cp -a /backup/. /restore/ && chown -R 999:999 /restore"

docker run -d \
  --name "$CONTAINER_NAME" \
  -p "127.0.0.1:${RESTORE_PORT}:5432" \
  -v "$VOLUME_NAME:/var/lib/postgresql/data" \
  "$POSTGRES_IMAGE" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null

smoke="$(
  docker exec -i -e PGPASSWORD="$DB_PASSWORD" "$CONTAINER_NAME" \
    psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -At <<'SQL'
SELECT count(*) FROM schema_migrations;
SELECT coalesce(to_regclass('public.notes')::text, '');
SELECT coalesce(to_regclass('public.project_invites')::text, '');
SQL
)"

schema_count="$(printf '%s\n' "$smoke" | sed -n '1p')"
notes_table="$(printf '%s\n' "$smoke" | sed -n '2p')"
invites_table="$(printf '%s\n' "$smoke" | sed -n '3p')"
case "$notes_table" in
  notes|public.notes) ;;
  *) fail "public.notes missing after restore" ;;
esac
case "$invites_table" in
  project_invites|public.project_invites) ;;
  *) fail "public.project_invites missing after restore" ;;
esac

echo "NoteSnoop restore drill OK: schema_migrations=$schema_count"
