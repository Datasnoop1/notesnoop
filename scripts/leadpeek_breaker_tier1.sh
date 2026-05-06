#!/bin/bash
# Tier-1 disk circuit breaker (R18 Phase 2b). At volume usage > 175 GB,
# stops the enrichment-worker compose service — the highest disk-IO writer.
# This buys headroom while keeping the user-facing site (backend, frontend,
# staatsblad-bulk-worker, nbb-backload-worker) up.
#
# Cron cadence: every minute.
# Action is reversible via `docker compose start enrichment-worker`.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"
COMPOSE="docker compose -f $LEADPEEK_DIR/docker-compose.yml"

TIER1_BYTES=$((175 * 1024 * 1024 * 1024))
SUSTAIN_MINUTES=2  # sustained 2 min before tripping (avoid one-tick blips)

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/breaker_tier1.lock"
TRIPPED_FLAG="$STATE_DIR/breaker_tier1.tripped"
SUSTAIN_FILE="$STATE_DIR/breaker_tier1.streak"
LOG="$STATE_DIR/breaker_tier1.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

VOL_USED=$(df -B1 /mnt/volume-hel1-1 | awk 'NR==2 {print $3}')
GB=$((1024*1024*1024))

if [ -f "$TRIPPED_FLAG" ]; then
    # Already tripped. Just log; recovery is operator-driven.
    log "tier1 already tripped; vol_used=$((VOL_USED/GB))G; awaiting manual reset"
    exit 0
fi

if [ "$VOL_USED" -le "$TIER1_BYTES" ]; then
    rm -f "$SUSTAIN_FILE"
    exit 0
fi

streak=0
[ -f "$SUSTAIN_FILE" ] && streak=$(cat "$SUSTAIN_FILE" 2>/dev/null || echo 0)
[[ "$streak" =~ ^[0-9]+$ ]] || streak=0
streak=$((streak + 1))
echo "$streak" > "$SUSTAIN_FILE"
log "vol_used=$((VOL_USED/GB))G > 175G; sustain=$streak/$SUSTAIN_MINUTES"

if [ "$streak" -lt "$SUSTAIN_MINUTES" ]; then
    exit 0
fi

# TRIP — stop the enrichment worker and mark tripped
log "TRIPPING: stopping enrichment-worker compose service"
STOP_OUT=$($COMPOSE stop enrichment-worker 2>&1 || true)
log "stop output: $STOP_OUT"
ts > "$TRIPPED_FLAG"
rm -f "$SUSTAIN_FILE"

bash "$ALERT" disk-tier1 "$(printf 'TIER-1 BREAKER TRIPPED.\nvol_used=%sG > 175G threshold (sustained %s min)\n\nstopped: enrichment-worker\n\noutput:\n%s\n\nManual reset:\n  docker compose -f /opt/leadpeek/docker-compose.yml start enrichment-worker\n  rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier1.tripped' \
    "$((VOL_USED/GB))" "$streak" "$STOP_OUT")" || true

exit 1
