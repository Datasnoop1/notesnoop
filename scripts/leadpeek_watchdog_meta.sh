#!/bin/bash
# Meta-watchdog (R18 Phase 2c). Confirms that each managed watchdog has
# logged within 2× its expected cadence. If not, alerts — usually means
# either cron is broken or the watchdog itself has bash-error'd silently.
#
# Cron cadence: every 30 minutes.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/meta.lock"
LAST_ALERT="$STATE_DIR/meta.last_alert"
LOG="$STATE_DIR/meta.log"
ALERT_REPEAT_MIN="${META_ALERT_REPEAT_MIN:-180}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

# Each entry: <log_file>:<max_age_minutes>
# max_age_minutes = 2× expected cadence (cron interval × 2 + 5 min safety)
declare -a CHECKS=(
    "$STATE_DIR/backupfresh.log:130"          # hourly  → 130 min budget
    "$STATE_DIR/disk.log:15"                  # 5min    → 15 min
    "$STATE_DIR/pgwal.log:5"                  # 1min    → 5 min
    "$STATE_DIR/longtx.log:15"                # 5min    → 15 min
    "$STATE_DIR/root_disk_action.log:25"      # 10min   → 25 min (only logs when triggered)
    "$STATE_DIR/breaker_tier1.log:5"          # 1min
    "$STATE_DIR/breaker_tier2.log:5"          # 1min
)

PROBLEMS=""
NOW=$(date +%s)
for entry in "${CHECKS[@]}"; do
    LF="${entry%%:*}"
    BUDGET="${entry##*:}"

    # Watchdogs that only write on event (root_disk_action) won't have a
    # log file unless they've fired. Skip if file doesn't exist AND budget
    # is the on-event one.
    if [ ! -f "$LF" ]; then
        case "$LF" in
            *root_disk_action.log)  continue ;;
            *breaker_tier1.log|*breaker_tier2.log)
                # Breakers also log on cron tick (line "vol_used=...");
                # absence after 5 min IS a real problem
                PROBLEMS+="$(basename "$LF"): missing — never ran?\n"
                continue ;;
            *)  PROBLEMS+="$(basename "$LF"): missing\n"; continue ;;
        esac
    fi

    MTIME=$(stat -c '%Y' "$LF")
    AGE_MIN=$(( (NOW - MTIME) / 60 ))
    if [ "$AGE_MIN" -gt "$BUDGET" ]; then
        PROBLEMS+="$(basename "$LF"): last write ${AGE_MIN}m ago (budget ${BUDGET}m)\n"
    fi
done

if [ -z "$PROBLEMS" ]; then
    log "GREEN — all watchdog logs within budget"
    exit 0
fi

log "RED:\n$PROBLEMS"

should_alert=1
if [ -f "$LAST_ALERT" ]; then
    la_ts=$(cat "$LAST_ALERT" 2>/dev/null || echo "")
    if [ -n "$la_ts" ]; then
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( (NOW - la_epoch) / 60 )) -lt "$ALERT_REPEAT_MIN" ]; then
            should_alert=0
        fi
    fi
fi
if [ "$should_alert" = "1" ]; then
    bash "$ALERT" meta-watchdog-stale "$PROBLEMS" || true
    ts > "$LAST_ALERT"
fi
exit 1
