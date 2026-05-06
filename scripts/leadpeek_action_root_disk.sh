#!/bin/bash
# Root disk hygiene action (R18 Phase 2b). At root > 65 GB used,
# proactively prune docker resources (preserving the postgres image used
# by restore drills) and force a logrotate. Does NOT touch postgres data.
#
# Cron cadence: every 10 minutes.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

ROOT_ACTION_BYTES=$((65 * 1024 * 1024 * 1024))

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/root_disk_action.lock"
LAST_ACTION="$STATE_DIR/root_disk_action.last"
LOG="$STATE_DIR/root_disk_action.log"
ACTION_COOLDOWN_MIN="${ROOT_DISK_ACTION_COOLDOWN_MIN:-30}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

ROOT_USED=$(df -B1 / | awk 'NR==2 {print $3}')
[ -n "$ROOT_USED" ] || exit 0
GB=$((1024*1024*1024))

if [ "$ROOT_USED" -le "$ROOT_ACTION_BYTES" ]; then
    # Always log a tick line so the meta-watchdog sees a fresh mtime on
    # this file even when no action fires. Without this line, the meta
    # check would alert "stale" forever after the first triggered run.
    log "below threshold: root_used=$((ROOT_USED/GB))G (threshold=$((ROOT_ACTION_BYTES/GB))G)"
    exit 0
fi

# Cooldown to avoid pruning every cron tick during sustained pressure
in_cooldown=0
if [ -f "$LAST_ACTION" ]; then
    la_ts=$(cat "$LAST_ACTION" 2>/dev/null || echo "")
    if [ -n "$la_ts" ]; then
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( ($(date +%s) - la_epoch) / 60 )) -lt "$ACTION_COOLDOWN_MIN" ]; then
            in_cooldown=1
        fi
    fi
fi
if [ "$in_cooldown" = "1" ]; then
    log "root_used=$((ROOT_USED/GB))G; in cooldown (last action <${ACTION_COOLDOWN_MIN}m ago)"
    exit 0
fi

log "TRIGGER: root_used=$((ROOT_USED/GB))G > 65G threshold"

# Drop the `-a` flag (which removes ALL unused images, including the
# postgres + pgvector images our drills depend on). Plain `docker system
# prune -f` only removes DANGLING images / stopped containers / unused
# networks — that's the cleanup we actually want.
#
# Note: `docker tag` does NOT add labels, only retags, so the previous
# label-based protection was a no-op. We rely on the conservative prune
# instead, plus drills explicitly `docker pull` their image before each run.
PRUNE_OUT=$(docker system prune -f --volumes=false 2>&1 || true)
LOGROTATE_OUT=$(logrotate --force /etc/logrotate.conf 2>&1 || true)

ts > "$LAST_ACTION"
ROOT_USED_AFTER=$(df -B1 / | awk 'NR==2 {print $3}')
log "post-action root_used=$((ROOT_USED_AFTER/GB))G (was $((ROOT_USED/GB))G)"

SCRUB="$SCRIPTS_DIR/r18_scrub_journal.sh"
PRUNE_OUT_SCRUBBED=$(printf '%s' "$PRUNE_OUT" | bash "$SCRUB" 2>/dev/null || printf '%s' "$PRUNE_OUT")
LOGROTATE_OUT_SCRUBBED=$(printf '%s' "$LOGROTATE_OUT" | bash "$SCRUB" 2>/dev/null || printf '%s' "$LOGROTATE_OUT")

bash "$ALERT" root-disk-action "$(printf 'Root disk hygiene fired:\nbefore: %sG used\nafter:  %sG used\n\ndocker prune:\n%s\n\nlogrotate:\n%s' \
    "$((ROOT_USED/GB))" "$((ROOT_USED_AFTER/GB))" "$PRUNE_OUT_SCRUBBED" "$LOGROTATE_OUT_SCRUBBED")" || true
exit 0
