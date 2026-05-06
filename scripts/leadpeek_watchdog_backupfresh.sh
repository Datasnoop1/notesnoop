#!/bin/bash
# Backup-freshness watchdog (R18). Alerts if the newest dump on either
# CURRENT (volume) or PREVIOUS (root) is older than the freshness budget.
#
# The systemd timer runs every 2 days, so a healthy steady-state has
# CURRENT.dump.zst less than ~50h old. We alert at 3 days (72h) to give a
# full timer cycle plus 24h of slack before we wake the operator. PREVIOUS
# is best-effort and may legitimately stay stale during root-disk pressure;
# we still alert at 5 days for it.
#
# Cron cadence: hourly (the alert helper de-dupes via cooldown).

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

VOLUME_LINK="/mnt/volume-hel1-1/backups/CURRENT.dump.zst"
ROOT_LINK="/var/lib/postgresql/backups/PREVIOUS.dump.zst"

VOLUME_BUDGET_HOURS=72
ROOT_BUDGET_HOURS=120

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/backupfresh.lock"
LAST_ALERT="$STATE_DIR/backupfresh.last_alert"
LOG="$STATE_DIR/backupfresh.log"
COOLDOWN_HOURS="${BACKUPFRESH_COOLDOWN_HOURS:-12}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || { log "another instance running, exiting"; exit 0; }

age_hours() {
    local link="$1"
    if [ ! -L "$link" ]; then
        echo "missing"; return
    fi
    local target
    target=$(readlink -f "$link" 2>/dev/null || echo "")
    if [ -z "$target" ] || [ ! -f "$target" ]; then
        echo "broken"; return
    fi
    local mtime now age
    mtime=$(stat -c '%Y' "$target")
    now=$(date +%s)
    age=$(( (now - mtime) / 3600 ))
    # Clock skew (e.g. fresh restore with a future-dated mtime) yields a
    # negative age; clamp to 0 so the budget comparison still flags it via
    # the "missing/broken" path elsewhere rather than silently green-ing.
    if [ "$age" -lt 0 ]; then
        echo "skew"; return
    fi
    echo "$age"
}

VOL_AGE=$(age_hours "$VOLUME_LINK")
ROOT_AGE=$(age_hours "$ROOT_LINK")
log "vol_age_hours=$VOL_AGE root_age_hours=$ROOT_AGE budgets=v${VOLUME_BUDGET_HOURS}h/r${ROOT_BUDGET_HOURS}h"

PROBLEMS=""
case "$VOL_AGE" in
    missing|broken|skew)
        PROBLEMS+="VOLUME backup symlink $VOL_AGE\n" ;;
    *)
        if [ "$VOL_AGE" -gt "$VOLUME_BUDGET_HOURS" ]; then
            PROBLEMS+="VOLUME backup is ${VOL_AGE}h old (budget ${VOLUME_BUDGET_HOURS}h)\n"
        fi ;;
esac

case "$ROOT_AGE" in
    missing|broken|skew)
        PROBLEMS+="ROOT backup symlink $ROOT_AGE (degraded; volume primary may still be OK)\n" ;;
    *)
        if [ "$ROOT_AGE" -gt "$ROOT_BUDGET_HOURS" ]; then
            PROBLEMS+="ROOT backup is ${ROOT_AGE}h old (budget ${ROOT_BUDGET_HOURS}h)\n"
        fi ;;
esac

if [ -z "$PROBLEMS" ]; then
    log "GREEN"
    exit 0
fi

# Cooldown so we don't email every hour during a sustained stale window
should_alert=1
if [ -f "$LAST_ALERT" ]; then
    la_ts=$(cat "$LAST_ALERT" 2>/dev/null || echo "")
    if [ -n "$la_ts" ]; then
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        age_min=$(( ($(date +%s) - la_epoch) / 60 ))
        if [ "$age_min" -lt $((COOLDOWN_HOURS * 60)) ]; then
            should_alert=0
        fi
    fi
fi

log "RED — problems:\n$PROBLEMS"
if [ "$should_alert" = "1" ]; then
    bash "$ALERT" backup-stale "$(printf '%bvolume_link=%s\nvolume_age_hours=%s\nroot_link=%s\nroot_age_hours=%s' \
        "$PROBLEMS" "$VOLUME_LINK" "$VOL_AGE" "$ROOT_LINK" "$ROOT_AGE")" || true
    ts > "$LAST_ALERT"
else
    log "alert suppressed (within ${COOLDOWN_HOURS}h cooldown)"
fi
exit 1
