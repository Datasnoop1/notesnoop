#!/bin/bash
# Install retention and base-backup cron entries for NoteSnoop's dedicated PG.

set -euo pipefail

ENV_FILE="${NOTESNOOP_ENV_FILE:-/opt/leadpeek/.env.production}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_BACKUP_SCRIPT="${NOTESNOOP_BASE_BACKUP_SCRIPT:-${SCRIPT_DIR}/notesnoop_take_base_backup.sh}"
BACKUP_DIR="/root/crontab-backups"

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

WAL_DIR="$(env_value NOTESNOOP_WAL_ARCHIVE_DIR || echo /mnt/volume-hel1-1/notesnoop-wal-archive)"
LOG_DIR="/opt/leadpeek/scripts/_watchdog_state"

[ -f "$BASE_BACKUP_SCRIPT" ] || {
  echo "base backup script missing: $BASE_BACKUP_SCRIPT" >&2
  exit 1
}

install -d -m 700 "$BACKUP_DIR"
install -d -m 755 "$LOG_DIR"

current="$(crontab -l 2>/dev/null || true)"
snapshot="$BACKUP_DIR/crontab.$(date -u +%Y%m%dT%H%M%SZ).bak"
printf '%s\n' "$current" > "$snapshot"
chmod 600 "$snapshot"

filtered="$(printf '%s\n' "$current" | grep -v '# notesnoop-postgres-' || true)"
{
  printf '%s\n' "$filtered"
  printf '12 3 * * * find %s -type f -mtime +2 -delete >> %s/notesnoop_wal_retention.log 2>&1 # notesnoop-postgres-wal-retention\n' "$WAL_DIR" "$LOG_DIR"
  printf '42 2 */2 * * NOTESNOOP_ENV_FILE=%s bash %s >> %s/notesnoop_base_backup.log 2>&1 # notesnoop-postgres-base-backup\n' "$ENV_FILE" "$BASE_BACKUP_SCRIPT" "$LOG_DIR"
} | awk 'NF || seen_blank == 0 { print; seen_blank = (NF ? 0 : 1) }' | crontab -

echo "Installed NoteSnoop Postgres cron entries. Snapshot: $snapshot"
