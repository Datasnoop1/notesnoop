#!/usr/bin/env bash
# Refresh leadpeek_staging from prod, scrub sensitive state, and atomically swap.
# Designed for root's cron on the Hetzner host. Never prints connection strings.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/leadpeek}"
PROD_ENV_FILE="${PROD_ENV_FILE:-$REPO_DIR/.env.production}"
STAGING_ENV_FILE="${STAGING_ENV_FILE:-$REPO_DIR/.env.staging}"
SCRUB_SQL="${SCRUB_SQL:-$REPO_DIR/scripts/staging_scrub.sql}"
LOCK_FILE="${LOCK_FILE:-/var/lock/leadpeek-staging-snapshot.lock}"
LOG_DIR="${LOG_DIR:-/var/log/leadpeek}"
MIN_ROOT_FREE_GB="${MIN_ROOT_FREE_GB:-15}"
STAGING_TABLESPACE="${STAGING_TABLESPACE:-staging_data}"
STAGING_DATA_DIR="${DS_STAGING_DATA_DIR:-/mnt/volume-hel1-1/pgsql-staging}"
DUMP_PREFIX="${DUMP_PREFIX:-$STAGING_DATA_DIR/leadpeek_prod_snapshot}"
SNAPSHOT_DUMP_FILE=""
SNAPSHOT_RESTORE_LIST=""

PG_BIN_DIR="${PG_BIN_DIR:-}"
if [ -z "$PG_BIN_DIR" ]; then
  PG_BIN_DIR=$(dirname "$(command -v pg_dump)")
fi
PSQL="$PG_BIN_DIR/psql"
PG_DUMP="$PG_BIN_DIR/pg_dump"
PG_RESTORE="$PG_BIN_DIR/pg_restore"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "FAIL: $*"
  exit 1
}

cleanup_restore_artifacts() {
  if [ -n "${SNAPSHOT_DUMP_FILE:-}" ]; then
    rm -f -- "$SNAPSHOT_DUMP_FILE" || true
    SNAPSHOT_DUMP_FILE=""
  fi
  if [ -n "${SNAPSHOT_RESTORE_LIST:-}" ]; then
    rm -f -- "$SNAPSHOT_RESTORE_LIST" || true
    SNAPSHOT_RESTORE_LIST=""
  fi
}

trap cleanup_restore_artifacts EXIT

env_value() {
  local file="$1"
  local key="$2"
  python3 - "$file" "$key" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
target = sys.argv[2]

for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].lstrip()
    key, sep, value = line.partition("=")
    if not sep or key.strip() != target:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    print(value)
    raise SystemExit(0)

raise SystemExit(1)
PY
}

rewrite_db_url() {
  local url="$1"
  local db_name="$2"
  python3 - "$url" "$db_name" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

url = sys.argv[1]
db_name = sys.argv[2]
parts = urlsplit(url)
prefix = parts.path.rsplit("/", 1)[0]
path = f"{prefix}/{db_name}" if prefix else f"/{db_name}"
print(urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment)))
PY
}

host_db_url() {
  local url="$1"
  python3 - "$url" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

parts = urlsplit(sys.argv[1])
netloc = parts.netloc
userinfo = ""
hostport = netloc
if "@" in netloc:
    userinfo, hostport = netloc.rsplit("@", 1)
    userinfo += "@"

if hostport.startswith("["):
    print(sys.argv[1])
    raise SystemExit(0)

host, sep, port = hostport.partition(":")
if host == "host.docker.internal":
    host = "127.0.0.1"
    netloc = userinfo + host + (sep + port if sep else "")

print(urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)))
PY
}

db_user_from_url() {
  local url="$1"
  python3 - "$url" <<'PY'
import sys
from urllib.parse import unquote, urlsplit

user = urlsplit(sys.argv[1]).username
if not user:
    raise SystemExit(1)
print(unquote(user))
PY
}

quote_ident() {
  python3 - "$1" <<'PY'
import sys

value = sys.argv[1]
print('"' + value.replace('"', '""') + '"')
PY
}

quote_literal() {
  python3 - "$1" <<'PY'
import sys

value = sys.argv[1]
print("'" + value.replace("'", "''") + "'")
PY
}

admin_psql() {
  sudo -u postgres "$PSQL" -v ON_ERROR_STOP=1 -d postgres "$@"
}

db_exists() {
  local db_name="$1"
  local result
  result=$(sudo -u postgres "$PSQL" -At -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$db_name'")
  [ "$result" = "1" ]
}

terminate_db() {
  local db_name="$1"
  admin_psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db_name' AND pid <> pg_backend_pid();" >/dev/null
}

prepare_restore_prereqs() {
  local db_name="$1"
  local owner_ident="$2"
  sudo -u postgres "$PSQL" -v ON_ERROR_STOP=1 -d "$db_name" <<'SQL' >/dev/null
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;
SQL
  sudo -u postgres "$PSQL" -v ON_ERROR_STOP=1 -d "$db_name" \
    -c "ALTER FUNCTION public.f_unaccent(text) OWNER TO $owner_ident;" >/dev/null
}

write_filtered_restore_list() {
  local dump_file="$1"
  local restore_list="$2"
  "$PG_RESTORE" --list "$dump_file" \
    | grep -vE 'FUNCTION public f_unaccent\(text\)| EXTENSION .* (fuzzystrmatch|pg_trgm|unaccent|vector)( |$)| COMMENT .* EXTENSION (fuzzystrmatch|pg_trgm|unaccent|vector)( |$)' \
    > "$restore_list"
}

preflight() {
  [ -f "$PROD_ENV_FILE" ] || fail "$PROD_ENV_FILE missing"
  [ -f "$STAGING_ENV_FILE" ] || fail "$STAGING_ENV_FILE missing"
  [ -f "$SCRUB_SQL" ] || fail "$SCRUB_SQL missing"
  [ -x "$PSQL" ] || fail "psql not executable at $PSQL"
  [ -x "$PG_DUMP" ] || fail "pg_dump not executable at $PG_DUMP"
  [ -x "$PG_RESTORE" ] || fail "pg_restore not executable at $PG_RESTORE"

  local free_gb
  free_gb=$(df -BG / | awk 'NR==2 {gsub(/G/, "", $4); print $4}')
  if [ "${free_gb:-0}" -lt "$MIN_ROOT_FREE_GB" ]; then
    fail "root filesystem has ${free_gb}GB free; need at least ${MIN_ROOT_FREE_GB}GB"
  fi

  install -d -o postgres -g postgres -m 700 "$STAGING_DATA_DIR"
}

ensure_tablespace() {
  local tablespace_literal
  tablespace_literal=$(quote_literal "$STAGING_TABLESPACE")
  if sudo -u postgres "$PSQL" -At -d postgres -c "SELECT 1 FROM pg_tablespace WHERE spcname = $tablespace_literal" | grep -qx 1; then
    log "tablespace_exists=$STAGING_TABLESPACE"
    return
  fi
  log "creating_tablespace=$STAGING_TABLESPACE"
  local tablespace_ident location_literal
  tablespace_ident=$(quote_ident "$STAGING_TABLESPACE")
  location_literal=$(quote_literal "$STAGING_DATA_DIR")
  admin_psql -c "CREATE TABLESPACE $tablespace_ident LOCATION $location_literal;" >/dev/null
}

refresh_snapshot() {
  local prod_database_url staging_database_url next_database_url owner owner_ident tablespace_ident old_umask
  prod_database_url=$(host_db_url "$(env_value "$PROD_ENV_FILE" DATABASE_URL)")
  staging_database_url=$(host_db_url "$(env_value "$STAGING_ENV_FILE" DATABASE_URL)")
  next_database_url=$(rewrite_db_url "$staging_database_url" leadpeek_staging_next)
  owner=$(db_user_from_url "$prod_database_url")
  owner_ident=$(quote_ident "$owner")
  tablespace_ident=$(quote_ident "$STAGING_TABLESPACE")
  old_umask=$(umask)
  umask 077
  SNAPSHOT_DUMP_FILE=$(mktemp "${DUMP_PREFIX}.XXXXXX.dump")
  SNAPSHOT_RESTORE_LIST=$(mktemp "${DUMP_PREFIX}.XXXXXX.list")
  umask "$old_umask"
  chmod 600 "$SNAPSHOT_DUMP_FILE" "$SNAPSHOT_RESTORE_LIST"

  log "dropping_next_if_exists"
  terminate_db leadpeek_staging_next || true
  admin_psql -c "DROP DATABASE IF EXISTS leadpeek_staging_next WITH (FORCE);" >/dev/null

  log "creating_next_database"
  admin_psql -c "CREATE DATABASE leadpeek_staging_next OWNER $owner_ident TABLESPACE $tablespace_ident;" >/dev/null

  log "preparing_next_restore_prereqs"
  prepare_restore_prereqs leadpeek_staging_next "$owner_ident"

  log "dumping_prod_archive"
  "$PG_DUMP" --format=custom --no-owner --no-acl --file "$SNAPSHOT_DUMP_FILE" "$prod_database_url"

  log "filtering_restore_list"
  write_filtered_restore_list "$SNAPSHOT_DUMP_FILE" "$SNAPSHOT_RESTORE_LIST"

  log "restoring_prod_into_next"
  "$PG_RESTORE" --exit-on-error --no-owner --no-acl --use-list "$SNAPSHOT_RESTORE_LIST" --dbname "$next_database_url" "$SNAPSHOT_DUMP_FILE"
  cleanup_restore_artifacts

  log "scrubbing_next"
  "$PSQL" "$next_database_url" -v ON_ERROR_STOP=1 -f "$SCRUB_SQL" >/dev/null

  log "swapping_databases"
  terminate_db leadpeek_staging || true
  terminate_db leadpeek_staging_old || true
  admin_psql -c "DROP DATABASE IF EXISTS leadpeek_staging_old WITH (FORCE);" >/dev/null
  if db_exists leadpeek_staging; then
    admin_psql -c "ALTER DATABASE leadpeek_staging RENAME TO leadpeek_staging_old;" >/dev/null
  fi
  admin_psql -c "ALTER DATABASE leadpeek_staging_next RENAME TO leadpeek_staging;" >/dev/null
  admin_psql -c "DROP DATABASE IF EXISTS leadpeek_staging_old WITH (FORCE);" >/dev/null

  log "snapshot_refresh_complete"
}

main() {
  cd "$REPO_DIR"
  preflight
  ensure_tablespace
  refresh_snapshot
}

(
  flock -n 9 || fail "another staging snapshot is already running"
  main "$@"
) 9>"$LOCK_FILE"
