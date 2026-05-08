#!/bin/bash
# Disk-space watchdog (R18 Phase 2b). Alerting only — does NOT take action.
# Tier breakers (175 / 185 GB) live in separate scripts that run on a tighter
# cadence; this one runs every 5 min and exists to give the operator
# advance warning at the soft thresholds (volume > 165 GB / root > 55 GB).
#
# Cron cadence: every 5 minutes. Cooldown via 60-min email-repeat window.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

VOLUME_WARN_BYTES=$((165 * 1024 * 1024 * 1024))
ROOT_WARN_BYTES=$((55 * 1024 * 1024 * 1024))

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/disk.lock"
LAST_ALERT="$STATE_DIR/disk.last_alert"
LOG="$STATE_DIR/disk.log"
ALERT_REPEAT_MIN="${DISK_ALERT_REPEAT_MIN:-60}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || { log "another instance running, exiting"; exit 0; }

used_bytes() { df -B1 "$1" | awk 'NR==2 {print $3}'; }

VOL_USED=$(used_bytes /mnt/volume-hel1-1)
ROOT_USED=$(used_bytes /)
GB=$((1024*1024*1024))
log "vol_used=$((VOL_USED/GB))G root_used=$((ROOT_USED/GB))G"

PROBLEMS=""
[ "$VOL_USED" -gt "$VOLUME_WARN_BYTES" ] && PROBLEMS+="VOLUME used $((VOL_USED/GB))G > 165G warn threshold\n"
[ "$ROOT_USED" -gt "$ROOT_WARN_BYTES" ]   && PROBLEMS+="ROOT used $((ROOT_USED/GB))G > 55G warn threshold\n"

if [ -z "$PROBLEMS" ]; then
    exit 0
fi

# Cooldown
should_alert=1
if [ -f "$LAST_ALERT" ]; then
    la_ts=$(cat "$LAST_ALERT" 2>/dev/null || echo "")
    if [ -n "$la_ts" ]; then
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( ($(date +%s) - la_epoch) / 60 )) -lt "$ALERT_REPEAT_MIN" ]; then
            should_alert=0
        fi
    fi
fi

log "RED — $PROBLEMS"
if [ "$should_alert" = "1" ]; then
    bash "$ALERT" disk-warn "$(printf '%bvol_used_bytes=%s\nroot_used_bytes=%s\nthresholds: volume>165G or root>55G' "$PROBLEMS" "$VOL_USED" "$ROOT_USED")" || true
    ts > "$LAST_ALERT"
else
    log "alert suppressed (within ${ALERT_REPEAT_MIN}m repeat window)"
fi
exit 1
