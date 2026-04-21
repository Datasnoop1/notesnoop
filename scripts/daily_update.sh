#!/bin/bash
# Host-side daily loader wrapper.
#
# Replaces the old untracked Hetzner-only daily_update.sh that hardcoded
# DATABASE_URL and NBB keys. This version executes the tracked loaders inside
# the backend container so they inherit the live runtime environment, including
# rotated NBB keys and the current database credentials.
#
# Intended cron:
#   0 3 * * * bash /opt/leadpeek/scripts/daily_update.sh >> /var/log/datapeak_daily.log 2>&1

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-leadpeek-backend-1}"
PYTHONPATH_IN_CONTAINER="${PYTHONPATH_IN_CONTAINER:-/app}"
STAATSBLAD_LIMIT="${STAATSBLAD_LIMIT:-200}"
STATE_LOG="${STATE_LOG:-$LEADPEEK_DIR/scripts/_watchdog_state/daily_update.log}"

mkdir -p "$(dirname "$STATE_LOG")"
exec > >(tee -a "$STATE_LOG") 2>&1

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(ts) $*"; }

if ! command -v docker >/dev/null 2>&1; then
    log "ERROR docker not installed on host"
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Fx "$BACKEND_CONTAINER" >/dev/null 2>&1; then
    log "ERROR backend container $BACKEND_CONTAINER is not running"
    exit 1
fi

run_job() {
    local name="$1"
    shift

    log "Starting $name"
    if docker exec -e PYTHONPATH="$PYTHONPATH_IN_CONTAINER" "$BACKEND_CONTAINER" "$@"; then
        log "Completed $name"
        return 0
    fi

    local exit_code=$?
    log "ERROR $name failed with exit $exit_code"
    return "$exit_code"
}

overall_exit=0

run_job "nbb_loader_hetzner.py" python /app/scripts/nbb_loader_hetzner.py || overall_exit=$?
run_job "staatsblad_hetzner.py" python /app/scripts/staatsblad_hetzner.py --limit "$STAATSBLAD_LIMIT" || overall_exit=$?

log "daily_update complete with exit $overall_exit"
exit "$overall_exit"
