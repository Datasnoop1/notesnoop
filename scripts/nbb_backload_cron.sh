#!/bin/bash
# Run the historical NBB backloader under a host-side lock so cron-triggered
# daytime/nightly runs never overlap.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
STATE_DIR="${STATE_DIR:-$LEADPEEK_DIR/scripts/_watchdog_state}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-leadpeek-backend-1}"
PYTHONPATH_IN_CONTAINER="${PYTHONPATH_IN_CONTAINER:-/app}"
LOCK_FILE="${LOCK_FILE:-$STATE_DIR/nbb_backload.lock}"
LOG_FILE="${LOG_FILE:-$STATE_DIR/nightly.log}"

MAX_CALLS="${MAX_CALLS:-3500}"
START_YEAR="${START_YEAR:-2025}"
END_YEAR="${END_YEAR:-2022}"
PER_YEAR_CAP="${PER_YEAR_CAP:-3500}"
SKIP_REBUILD="${SKIP_REBUILD:-1}"

mkdir -p "$STATE_DIR"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(ts) $*" | tee -a "$LOG_FILE"; }

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "nbb backload already running - skipping cron trigger (max_calls=$MAX_CALLS)"
    exit 0
fi

REBUILD_FLAG=""
[ "${SKIP_REBUILD:-1}" = "1" ] && REBUILD_FLAG="--skip-rebuild"

log "starting nbb backload (max_calls=$MAX_CALLS start_year=$START_YEAR end_year=$END_YEAR per_year_cap=$PER_YEAR_CAP skip_rebuild=$SKIP_REBUILD)"
docker exec -e PYTHONPATH="$PYTHONPATH_IN_CONTAINER" "$BACKEND_CONTAINER" \
    python /app/scripts/nbb_nightly_backload.py \
    --max-calls "$MAX_CALLS" \
    --start-year "$START_YEAR" \
    --end-year "$END_YEAR" \
    --per-year-cap "$PER_YEAR_CAP" \
    $REBUILD_FLAG >> "$LOG_FILE" 2>&1
exit_code=$?

if [ $exit_code -eq 0 ]; then
    log "nbb backload finished cleanly"
else
    log "nbb backload exited with code $exit_code"
fi

exit $exit_code
