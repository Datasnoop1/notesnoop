#!/usr/bin/env bash
# Configure PostgreSQL WAL archiving for the DataSnoop host.
#
# Safe modes:
#   --check                 read-only audit
#   --apply                 write ALTER SYSTEM settings and reload
#   --apply --restart-if-required
#                           also restart PostgreSQL when archive_mode needs it
#
# This script never prints DATABASE_URL or other application secrets.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/leadpeek}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
PG_BIN_DIR="${PG_BIN_DIR:-}"
if [ -z "$PG_BIN_DIR" ]; then
  PG_BIN_DIR=$(dirname "$(command -v psql)")
fi
PSQL="$PG_BIN_DIR/psql"
LOCK_FILE="${LOCK_FILE:-/var/lock/datasnoop-wal-archive-config.lock}"

MODE="check"
RESTART_IF_REQUIRED="false"
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    --restart-if-required) RESTART_IF_REQUIRED="true" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
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

pg_scalar() {
  sudo -u postgres "$PSQL" -X -At -d postgres -c "$1"
}

pg_exec() {
  sudo -u postgres "$PSQL" -X -v ON_ERROR_STOP=1 -d postgres "$@"
}

show_settings() {
  pg_scalar "
    SELECT name || '=' || setting || ';pending_restart=' || pending_restart
    FROM pg_settings
    WHERE name IN ('archive_mode', 'archive_command', 'wal_level', 'max_wal_senders')
    ORDER BY name;
  "
}

preflight() {
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE missing"
  [ -x "$PSQL" ] || fail "psql not executable at $PSQL"
  WAL_DIR=$(env_value "$ENV_FILE" DS_WAL_ARCHIVE_DIR) || fail "DS_WAL_ARCHIVE_DIR missing"
  BACKUP_DIR=$(env_value "$ENV_FILE" DS_BACKUP_DIR) || fail "DS_BACKUP_DIR missing"
  [ -n "$WAL_DIR" ] || fail "DS_WAL_ARCHIVE_DIR empty"
  [ -n "$BACKUP_DIR" ] || fail "DS_BACKUP_DIR empty"
  export WAL_DIR BACKUP_DIR
}

ensure_dirs() {
  install -d -o postgres -g postgres -m 700 "$WAL_DIR"
  install -d -o postgres -g postgres -m 700 "$BACKUP_DIR"
}

apply_settings() {
  local archive_command
  archive_command="test ! -f '$WAL_DIR/%f' && cp '%p' '$WAL_DIR/%f'"
  log "writing_wal_archive_settings"
  pg_exec -v archive_command="$archive_command" <<'SQL' >/dev/null
ALTER SYSTEM SET wal_level = 'replica';
ALTER SYSTEM SET archive_mode = 'on';
ALTER SYSTEM SET archive_command = :'archive_command';
SQL
  log "reloading_postgres_config"
  pg_scalar "SELECT pg_reload_conf();" | grep -qx t || fail "pg_reload_conf returned false"
}

restart_if_needed() {
  local pending
  pending=$(pg_scalar "SELECT pending_restart FROM pg_settings WHERE name = 'archive_mode';")
  if [ "$pending" != "t" ]; then
    log "postgres_restart_required=false"
    return
  fi
  log "postgres_restart_required=true"
  if [ "$RESTART_IF_REQUIRED" != "true" ]; then
    fail "archive_mode change is pending restart; rerun with --restart-if-required during a quiet window"
  fi
  log "restarting_postgresql"
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    local version
    version=$(pg_scalar "SHOW server_version_num;" | cut -c1-2)
    pg_ctlcluster "$version" main restart
  else
    systemctl restart postgresql
  fi
}

force_archive_probe() {
  local wal_file
  wal_file=$(pg_scalar "SELECT pg_walfile_name(pg_switch_wal());")
  log "forced_wal_switch=$wal_file"
  for _ in $(seq 1 30); do
    if [ -f "$WAL_DIR/$wal_file" ]; then
      log "archive_probe=ok file=$wal_file"
      return
    fi
    sleep 1
  done
  fail "archive probe did not find $WAL_DIR/$wal_file within 30s"
}

main() {
  preflight
  log "mode=$MODE wal_dir=$WAL_DIR backup_dir=$BACKUP_DIR"
  log "settings_before"
  show_settings
  if [ "$MODE" = "apply" ]; then
    ensure_dirs
    apply_settings
    restart_if_needed
    force_archive_probe
  fi
  log "settings_after"
  show_settings
}

(
  flock -n 9 || fail "another WAL archive configuration run is active"
  main "$@"
) 9>"$LOCK_FILE"
