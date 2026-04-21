#!/bin/bash
# NBB key watchdog - runs every 15 min from cron.
#
# Logic:
#   1. Probe NBB (AuthenticData + Extracts) via alert_digest.py --health-check.
#      Exit codes:
#        0  = green
#        10 = auth failure, worth rotating
#        11 = transient/upstream failure, do NOT rotate
#   2. If green: silent (log line only). Done.
#   3. If transient red: alert once per repeat window, but do NOT rotate.
#   4. If auth red AND we haven't auto-rotated in the last $COOLDOWN_MIN minutes:
#        a. Email "rotation in progress" (informational).
#        b. Run the rotator script.
#        c. Probe again.
#        d. Email "rotation succeeded" or "rotation FAILED - manual fix needed".
#   5. If auth red AND we ARE within the cooldown window:
#        - Email "still red after recent auto-rotate; investigate" - but only
#          ONCE per cooldown window (lock prevents repeated emails).
#
# Files:
#   /opt/leadpeek/scripts/_watchdog.lock      flock guard - only one
#                                             watchdog runs at a time
#   /opt/leadpeek/scripts/_watchdog.last_rot  ISO timestamp of last rotate
#   /opt/leadpeek/scripts/_watchdog.last_alert  ISO timestamp of last "still red" alert
#
# Exit codes:
#   0 green or recovered after auto-rotate
#   2 auth red, auto-rotate fired and FAILED      (operator action needed)
#   3 auth red but in cooldown - alerted but did not auto-rotate
#   4 transient red - alerted but deliberately did not auto-rotate

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"

LOCK="$STATE_DIR/lock"
LAST_ROTATE="$STATE_DIR/last_rotate"
LAST_ALERT="$STATE_DIR/last_alert"
LOG="$STATE_DIR/watchdog.log"

COOLDOWN_MIN="${WATCHDOG_COOLDOWN_MIN:-30}"
ALERT_REPEAT_MIN="${WATCHDOG_ALERT_REPEAT_MIN:-60}"
AUTH_FAILURE_EXIT=10

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(ts) $*" | tee -a "$LOG"; }

# Fail to acquire lock = a previous run is still in flight; bail silently.
exec 9>"$LOCK"
if ! flock -n 9; then
    log "another watchdog instance is running - exiting"
    exit 0
fi

# --- 1. Probe ---
HEALTH_OUTPUT=$(docker exec leadpeek-backend-1 python /app/scripts/alert_digest.py --health-check 2>&1)
HEALTH_EXIT=$?

if [ $HEALTH_EXIT -eq 0 ]; then
    log "GREEN"
    exit 0
fi

log "RED - output: $HEALTH_OUTPUT"

# --- 2. Transient-vs-auth split ---
if [ $HEALTH_EXIT -ne $AUTH_FAILURE_EXIT ]; then
    log "transient/upstream probe failure (exit $HEALTH_EXIT) - not auto-rotating"

    should_alert=1
    if [ -f "$LAST_ALERT" ]; then
        la_ts=$(cat "$LAST_ALERT")
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( ($(date +%s) - la_epoch) / 60 )) -lt $ALERT_REPEAT_MIN ]; then
            should_alert=0
        fi
    fi
    if [ $should_alert -eq 1 ]; then
        bash "$SCRIPTS_DIR/_watchdog_send_alert.sh" "probe-transient-no-rotate" "$HEALTH_OUTPUT"
        ts > "$LAST_ALERT"
    else
        log "skipping repeat alert (within $ALERT_REPEAT_MIN-min repeat window)"
    fi
    exit 4
fi

# --- 3. Cooldown check (auth failures only) ---
in_cooldown=0
if [ -f "$LAST_ROTATE" ]; then
    last_ts=$(cat "$LAST_ROTATE")
    last_epoch=$(date -d "$last_ts" +%s 2>/dev/null || echo 0)
    now_epoch=$(date +%s)
    age_min=$(( (now_epoch - last_epoch) / 60 ))
    if [ $age_min -lt $COOLDOWN_MIN ]; then
        in_cooldown=1
        log "in cooldown ($age_min min since last rotate, threshold $COOLDOWN_MIN min)"
    fi
fi

if [ $in_cooldown -eq 1 ]; then
    # Don't auto-rotate again, but DO email if we haven't recently alerted.
    should_alert=1
    if [ -f "$LAST_ALERT" ]; then
        la_ts=$(cat "$LAST_ALERT")
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( ($(date +%s) - la_epoch) / 60 )) -lt $ALERT_REPEAT_MIN ]; then
            should_alert=0
        fi
    fi
    if [ $should_alert -eq 1 ]; then
        bash "$SCRIPTS_DIR/_watchdog_send_alert.sh" "still-red-after-rotate" "$HEALTH_OUTPUT"
        ts > "$LAST_ALERT"
    else
        log "skipping repeat alert (within $ALERT_REPEAT_MIN-min repeat window)"
    fi
    exit 3
fi

# --- 4. Auto-rotate ---
log "auto-rotating..."
bash "$SCRIPTS_DIR/_watchdog_send_alert.sh" "rotating" "$HEALTH_OUTPUT"

ROTATE_OUT=$(bash "$SCRIPTS_DIR/nbb_rotate_and_restart.sh" 2>&1)
ROTATE_EXIT=$?
ts > "$LAST_ROTATE"

if [ $ROTATE_EXIT -eq 0 ]; then
    log "auto-rotate SUCCESS"
    bash "$SCRIPTS_DIR/_watchdog_send_alert.sh" "rotated-ok" "$ROTATE_OUT"
    exit 0
fi

log "auto-rotate FAILED with exit $ROTATE_EXIT"
bash "$SCRIPTS_DIR/_watchdog_send_alert.sh" "rotate-failed" "$ROTATE_OUT"
exit 2
