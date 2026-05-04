#!/usr/bin/env bash
# Take a local PostgreSQL base backup into DS_BACKUP_DIR.
#
# Intended to run on the Hetzner host after WAL archiving is enabled.
# Never prints DATABASE_URL or application secrets.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/leadpeek}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
PG_BIN_DIR="${PG_BIN_DIR:-}"
if [ -z "$PG_BIN_DIR" ]; then
  PG_BIN_DIR=$(dirname "$(command -v psql)")
fi
PSQL="$PG_BIN_DIR/psql"
PG_BASEBACKUP="$PG_BIN_DIR/pg_basebackup"
LOCK_FILE="${LOCK_FILE:-/var/lock/datasnoop-base-backup.lock}"
MIN_FREE_MARGIN_GB="${MIN_FREE_MARGIN_GB:-5}"
KEEP_BASE_BACKUPS="${KEEP_BASE_BACKUPS:-2}"
TARGET_DIR=""

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

cleanup() {
  if [ -n "${TARGET_DIR:-}" ] && [ -d "$TARGET_DIR.inprogress" ]; then
    rm -rf -- "$TARGET_DIR.inprogress"
  fi
}

trap cleanup EXIT

preflight() {
  [ -f "$ENV_FILE" ] || fail "$ENV_FILE missing"
  [ -x "$PSQL" ] || fail "psql not executable at $PSQL"
  [ -x "$PG_BASEBACKUP" ] || fail "pg_basebackup not executable at $PG_BASEBACKUP"
  BACKUP_DIR=$(env_value "$ENV_FILE" DS_BACKUP_DIR) || fail "DS_BACKUP_DIR missing"
  [ -n "$BACKUP_DIR" ] || fail "DS_BACKUP_DIR empty"
  export BACKUP_DIR
  install -d -o postgres -g postgres -m 700 "$BACKUP_DIR"

  local data_dir data_gb free_gb required_gb
  data_dir=$(pg_scalar "SHOW data_directory;")
  data_gb=$(du -sBG "$data_dir" | awk '{gsub(/G/, "", $1); print $1}')
  free_gb=$(df -BG "$BACKUP_DIR" | awk 'NR==2 {gsub(/G/, "", $4); print $4}')
  required_gb=$((data_gb + MIN_FREE_MARGIN_GB))
  log "preflight data_gb=$data_gb free_gb=$free_gb required_gb=$required_gb"
  if [ "${free_gb:-0}" -lt "$required_gb" ]; then
    fail "backup volume has ${free_gb}GB free; need at least ${required_gb}GB"
  fi
}

take_backup() {
  local ts tmp_dir
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  TARGET_DIR="$BACKUP_DIR/base-$ts"
  tmp_dir="$TARGET_DIR.inprogress"
  log "base_backup_start target=$TARGET_DIR format=tar-gzip"
  sudo -u postgres "$PG_BASEBACKUP" \
    --pgdata="$tmp_dir" \
    --format=tar \
    --gzip \
    --wal-method=stream \
    --checkpoint=fast \
    --progress \
    --label="datasnoop-base-$ts"
  mv "$tmp_dir" "$TARGET_DIR"
  ln -sfn "$(basename "$TARGET_DIR")" "$BACKUP_DIR/base-latest"
  chmod 700 "$TARGET_DIR"
  log "base_backup_complete target=$TARGET_DIR"
  log "base_backup_size=$(du -sh "$TARGET_DIR" | awk '{print $1}')"
  if [ -f "$TARGET_DIR/backup_manifest" ] || [ -f "$TARGET_DIR/backup_manifest.tar" ]; then
    log "backup_manifest=present"
  else
    log "backup_manifest=missing"
  fi
}

prune_old_backups() {
  # Keep the KEEP_BASE_BACKUPS most recent base-* dirs (sorted by name —
  # names are timestamps so newest sorts last). Never delete what
  # base-latest points to, even if it would otherwise fall outside the
  # keep window.
  local keep="$KEEP_BASE_BACKUPS"
  if ! [[ "$keep" =~ ^[0-9]+$ ]] || [ "$keep" -lt 1 ]; then
    log "prune skipped: KEEP_BASE_BACKUPS=$keep is not a positive integer"
    return 0
  fi
  local current_target=""
  if [ -L "$BACKUP_DIR/base-latest" ]; then
    current_target=$(readlink "$BACKUP_DIR/base-latest")
  fi
  local all_backups
  mapfile -t all_backups < <(find "$BACKUP_DIR" -maxdepth 1 -type d -name 'base-*' -printf '%f\n' | sort)
  local total=${#all_backups[@]}
  if [ "$total" -le "$keep" ]; then
    log "prune skipped: total=$total keep=$keep"
    return 0
  fi
  local cutoff=$((total - keep))
  local i=0
  for name in "${all_backups[@]}"; do
    i=$((i + 1))
    if [ "$i" -gt "$cutoff" ]; then
      break
    fi
    if [ "$name" = "$current_target" ]; then
      log "prune SKIP base-latest target: $name"
      continue
    fi
    log "pruning old backup: $name"
    rm -rf -- "$BACKUP_DIR/$name"
  done
}

main() {
  preflight
  take_backup
  prune_old_backups
}

(
  flock -n 9 || fail "another base backup is already running"
  main "$@"
) 9>"$LOCK_FILE"
