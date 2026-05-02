#!/usr/bin/env bash
# Monthly DataSnoop restore drill.
#
# This is intentionally safe to run from root cron on the Hetzner host.
# It never prints DATABASE_URL or application secrets.
#
# What it verifies:
#   1. The latest physical base-backup directory is present.
#   2. The backup manifest parses and reports expected payload size.
#   3. The compressed tar payloads are readable.
#   4. A schema-only logical dump restores into a scratch database.
#
# A full same-host physical restore is capacity-gated separately: the current
# backup manifest is larger than the free scratch space on the attached volume.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/leadpeek}"
PROD_ENV_FILE="${PROD_ENV_FILE:-$REPO_DIR/.env.production}"
LOCK_FILE="${LOCK_FILE:-/var/lock/datasnoop-restore-drill.lock}"
LOG_DIR="${LOG_DIR:-$REPO_DIR/scripts/_watchdog_state}"
RESTORE_DB_PREFIX="${RESTORE_DB_PREFIX:-leadpeek_restore_drill}"
RESTORE_DRILL_WORK_DIR="${RESTORE_DRILL_WORK_DIR:-/tmp/datasnoop-restore-drill}"
RESTORE_FREE_MARGIN_GB="${RESTORE_FREE_MARGIN_GB:-5}"
RESTORE_MAINTENANCE_WORK_MEM="${RESTORE_MAINTENANCE_WORK_MEM:-1GB}"
VERIFY_COMPRESSED_TARS="${VERIFY_COMPRESSED_TARS:-true}"
MODE="run"

PG_BIN_DIR="${PG_BIN_DIR:-}"
if [ -z "$PG_BIN_DIR" ]; then
  PG_BIN_DIR=$(dirname "$(command -v pg_dump)")
fi
PSQL="$PG_BIN_DIR/psql"
PG_DUMP="$PG_BIN_DIR/pg_dump"
PG_RESTORE="$PG_BIN_DIR/pg_restore"

RESTORE_DB=""
DUMP_FILE=""
RESTORE_LIST=""
BACKUP_DIR=""
LATEST_BACKUP=""

for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --run) MODE="run" ;;
    --skip-gzip-test) VERIFY_COMPRESSED_TARS="false" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$LOG_DIR" "$RESTORE_DRILL_WORK_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  write_status "fail" "$*"
  log "FAIL: $*"
  exit 1
}

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

admin_psql() {
  sudo -u postgres "$PSQL" -v ON_ERROR_STOP=1 -d postgres "$@"
}

restore_psql() {
  sudo -u postgres "$PSQL" -v ON_ERROR_STOP=1 -d "$RESTORE_DB" "$@"
}

terminate_restore_db() {
  [ -n "$RESTORE_DB" ] || return 0
  admin_psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$RESTORE_DB' AND pid <> pg_backend_pid();" >/dev/null || true
}

cleanup() {
  if [ -n "${RESTORE_DB:-}" ]; then
    terminate_restore_db
    local restore_ident
    restore_ident=$(quote_ident "$RESTORE_DB")
    admin_psql -c "DROP DATABASE IF EXISTS $restore_ident WITH (FORCE);" >/dev/null || true
  fi
  rm -f -- "${DUMP_FILE:-}" "${RESTORE_LIST:-}" || true
}

trap cleanup EXIT

write_status() {
  local status="$1"
  local detail="${2:-}"
  python3 - "$LOG_DIR/restore_drill_last.json" "$status" "$detail" "${RESTORE_DB:-}" "${LATEST_BACKUP:-}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": sys.argv[2],
    "detail": sys.argv[3],
    "restore_db": sys.argv[4],
    "backup": sys.argv[5],
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

manifest_total_gb() {
  python3 - "$LATEST_BACKUP/backup_manifest" <<'PY'
import json
import math
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
total = sum(int(item.get("Size", 0)) for item in manifest.get("Files", []))
print(math.ceil(total / (1024 ** 3)))
PY
}

compressed_backup_gb() {
  du -sBG "$LATEST_BACKUP" | awk '{gsub(/G/, "", $1); print $1}'
}

free_gb_for_workdir() {
  df -BG "$RESTORE_DRILL_WORK_DIR" | awk 'NR==2 {gsub(/G/, "", $4); print $4}'
}

preflight() {
  [ -f "$PROD_ENV_FILE" ] || fail "$PROD_ENV_FILE missing"
  [ -x "$PSQL" ] || fail "psql not executable at $PSQL"
  [ -x "$PG_DUMP" ] || fail "pg_dump not executable at $PG_DUMP"
  [ -x "$PG_RESTORE" ] || fail "pg_restore not executable at $PG_RESTORE"
  command -v gzip >/dev/null 2>&1 || fail "gzip missing"

  BACKUP_DIR=$(env_value "$PROD_ENV_FILE" DS_BACKUP_DIR) || fail "DS_BACKUP_DIR missing"
  [ -n "$BACKUP_DIR" ] || fail "DS_BACKUP_DIR empty"
  LATEST_BACKUP="${RESTORE_DRILL_BACKUP:-$BACKUP_DIR/base-latest}"
  [ -e "$LATEST_BACKUP" ] || fail "$LATEST_BACKUP missing"
  LATEST_BACKUP=$(readlink -f "$LATEST_BACKUP")
  [ -d "$LATEST_BACKUP" ] || fail "$LATEST_BACKUP is not a directory"
  [ -f "$LATEST_BACKUP/backup_manifest" ] || fail "backup_manifest missing"
  [ -f "$LATEST_BACKUP/base.tar.gz" ] || fail "base.tar.gz missing"
  [ -f "$LATEST_BACKUP/pg_wal.tar.gz" ] || fail "pg_wal.tar.gz missing"
}

verify_backup_payload() {
  local manifest_gb compressed_gb free_gb required_gb
  manifest_gb=$(manifest_total_gb)
  compressed_gb=$(compressed_backup_gb)
  free_gb=$(free_gb_for_workdir)
  required_gb=$((manifest_gb + RESTORE_FREE_MARGIN_GB))
  log "backup=$LATEST_BACKUP compressed_gb=$compressed_gb manifest_uncompressed_gb=$manifest_gb scratch_free_gb=$free_gb physical_required_gb=$required_gb"
  if [ "${free_gb:-0}" -lt "$required_gb" ]; then
    log "physical_restore_capacity=insufficient"
  else
    log "physical_restore_capacity=sufficient"
  fi

  python3 -m json.tool "$LATEST_BACKUP/backup_manifest" >/dev/null
  log "backup_manifest=parse_ok"

  if [ "$VERIFY_COMPRESSED_TARS" = "true" ]; then
    local archive
    for archive in "$LATEST_BACKUP"/*.tar.gz; do
      log "gzip_test_start file=$(basename "$archive")"
      gzip -t "$archive"
      log "gzip_test_ok file=$(basename "$archive")"
    done
  else
    log "gzip_test=skipped"
  fi
}

prepare_restore_prereqs() {
  local owner_ident="$1"
  restore_psql <<'SQL' >/dev/null
CREATE EXTENSION IF NOT EXISTS vector; -- ALLOW-RUNTIME-DDL: scratch restore DB prerequisite
CREATE EXTENSION IF NOT EXISTS unaccent; -- ALLOW-RUNTIME-DDL: scratch restore DB prerequisite
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch; -- ALLOW-RUNTIME-DDL: scratch restore DB prerequisite
CREATE EXTENSION IF NOT EXISTS pg_stat_statements; -- ALLOW-RUNTIME-DDL: scratch restore DB prerequisite
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- ALLOW-RUNTIME-DDL: scratch restore DB prerequisite

CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;

CREATE OR REPLACE FUNCTION public.search_normalize(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    TRIM(
      REGEXP_REPLACE(
        LOWER(public.f_unaccent(
          REGEXP_REPLACE(
            COALESCE(s, ''),
            '[[:space:][:punct:]]*(' ||
              'nv|sa|bvba|sprl|bv|srl|cvba|scrl|vof|snc|se|scs|gcv|' ||
              'comm\.?\s*v|scomm|asbl|vzw|aisbl|ivzw|' ||
              'gmbh|ag|ltd|inc|sas|sarl|llc|plc|corp|spa|kg|ohg|ug|eurl' ||
            ')[[:space:][:punct:]]*$',
            '', 'gi'
          )
        )),
        '\s+', ' ', 'g'
      )
    ),
    ''
  )
$$;

CREATE OR REPLACE FUNCTION public.search_name_reversed(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(tok ORDER BY tok)
       FROM regexp_split_to_table(COALESCE(public.search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;

CREATE OR REPLACE FUNCTION public.search_phonetic_key(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(public.dmetaphone(tok))
       FROM regexp_split_to_table(COALESCE(public.search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;
SQL
  restore_psql \
    -c "ALTER FUNCTION public.f_unaccent(text) OWNER TO $owner_ident;" \
    -c "ALTER FUNCTION public.search_normalize(text) OWNER TO $owner_ident;" \
    -c "ALTER FUNCTION public.search_name_reversed(text) OWNER TO $owner_ident;" \
    -c "ALTER FUNCTION public.search_phonetic_key(text) OWNER TO $owner_ident;" >/dev/null
}

write_filtered_restore_list() {
  local dump_file="$1"
  local restore_list="$2"
  "$PG_RESTORE" --list "$dump_file" \
    | grep -vE 'FUNCTION public (f_unaccent|search_name_reversed|search_normalize|search_phonetic_key)\(text\)| EXTENSION .* (fuzzystrmatch|pg_stat_statements|pg_trgm|plpgsql|unaccent|vector)( |$)| COMMENT .* EXTENSION (fuzzystrmatch|pg_stat_statements|pg_trgm|plpgsql|unaccent|vector)( |$)' \
    > "$restore_list"
}

run_logical_schema_restore() {
  local prod_database_url owner owner_ident restore_ident ts missing
  prod_database_url=$(host_db_url "$(env_value "$PROD_ENV_FILE" DATABASE_URL)")
  owner=$(db_user_from_url "$prod_database_url") || fail "could not derive DB owner"
  owner_ident=$(quote_ident "$owner")
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  RESTORE_DB="${RESTORE_DB_PREFIX}_$ts"
  restore_ident=$(quote_ident "$RESTORE_DB")
  DUMP_FILE="$RESTORE_DRILL_WORK_DIR/$RESTORE_DB.dump"
  RESTORE_LIST="$RESTORE_DRILL_WORK_DIR/$RESTORE_DB.list"

  log "logical_restore_db_create name=$RESTORE_DB"
  admin_psql -c "CREATE DATABASE $restore_ident OWNER $owner_ident;" >/dev/null

  log "logical_restore_prereqs"
  prepare_restore_prereqs "$owner_ident"

  log "logical_schema_dump_start"
  "$PG_DUMP" --schema-only --format=custom --no-owner --no-acl --file "$DUMP_FILE" "$prod_database_url"

  log "logical_restore_list_filter"
  write_filtered_restore_list "$DUMP_FILE" "$RESTORE_LIST"

  log "logical_schema_restore_start"
  sudo -u postgres env PGOPTIONS="-c maintenance_work_mem=$RESTORE_MAINTENANCE_WORK_MEM" \
    "$PG_RESTORE" --exit-on-error --no-owner --no-acl --use-list "$RESTORE_LIST" --dbname "$RESTORE_DB" "$DUMP_FILE"

  missing=$(restore_psql -At <<'SQL'
WITH expected(rel) AS (
  VALUES ('company_info'), ('enterprise'), ('financial_data'), ('administrator')
)
SELECT string_agg(rel, ',')
FROM expected
WHERE to_regclass('public.' || rel) IS NULL;
SQL
)
  if [ -n "${missing:-}" ]; then
    fail "logical restore missing expected relations: $missing"
  fi
  log "logical_restore_smoke=ok"
}

main() {
  preflight
  log "mode=$MODE"
  verify_backup_payload
  if [ "$MODE" = "run" ]; then
    run_logical_schema_restore
  fi
  write_status "ok" "restore drill completed"
  log "restore_drill_complete"
}

{
  flock -n 9 || fail "another restore drill is already running"
  main "$@"
} 9>"$LOCK_FILE"
