#!/bin/bash
# Host-side KBO daily update wrapper.
#
# Intended cron:
#   0 6 * * * bash /opt/leadpeek/scripts/kbo_update.sh
#
# Runs the tracked KBO updater inside the backend container so database
# credentials and rotated service keys come from the live container env.
# After a successful updater run, refresh planner stats for the large KBO
# tables that the loader mutates.

set -euo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-leadpeek-backend-1}"
PYTHONPATH_IN_CONTAINER="${PYTHONPATH_IN_CONTAINER:-/app}"
STATE_LOG="${STATE_LOG:-$LEADPEEK_DIR/scripts/_watchdog_state/kbo_update.log}"
LOCK_FILE="${LOCK_FILE:-$LEADPEEK_DIR/scripts/_watchdog_state/kbo_update.lock}"
MAX_LOG_BYTES="${MAX_LOG_BYTES:-10485760}"

KBO_TABLES=(
    activity
    address
    enterprise
    establishment
    contact
    code
    branch
)

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(ts) $*"; }

mkdir -p "$(dirname "$STATE_LOG")"
if [ -f "$STATE_LOG" ] && [ "$(wc -c < "$STATE_LOG")" -gt "$MAX_LOG_BYTES" ]; then
    mv "$STATE_LOG" "$STATE_LOG.$(date -u +%Y%m%dT%H%M%SZ)"
fi
exec > >(tee -a "$STATE_LOG") 2>&1

if ! command -v flock >/dev/null 2>&1; then
    log "ERROR flock not installed on host"
    exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "KBO daily update already running; exiting"
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    log "ERROR docker not installed on host"
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Fx "$BACKEND_CONTAINER" >/dev/null 2>&1; then
    log "ERROR backend container $BACKEND_CONTAINER is not running"
    exit 1
fi

run_backend() {
    docker exec -i -e PYTHONPATH="$PYTHONPATH_IN_CONTAINER" "$BACKEND_CONTAINER" "$@"
}

log "Starting KBO daily update"
if run_backend python /app/backend/kbo_daily_update.py; then
    log "KBO updater finished"
else
    exit_code=$?
    log "ERROR KBO daily update failed with exit $exit_code"
    exit "$exit_code"
fi

log "Refreshing KBO planner statistics"
tables_literal=$(printf "'%s', " "${KBO_TABLES[@]}")
tables_literal="${tables_literal%, }"

if run_backend python - "$tables_literal" <<'PY'
import sys
sys.path.insert(0, "/app/backend")
from db import get_connection, put_connection

tables = [name.strip().strip("'") for name in sys.argv[1].split(",")]
conn = get_connection()
try:
    conn.autocommit = True
    with conn.cursor() as cur:
        for table in tables:
            print(f"ANALYZE {table}")
            cur.execute(f"ANALYZE VERBOSE {table}")
finally:
    put_connection(conn)
PY
then
    log "KBO planner statistics refreshed"
else
    exit_code=$?
    log "ERROR KBO ANALYZE failed with exit $exit_code"
    exit "$exit_code"
fi

log "KBO daily update complete"
