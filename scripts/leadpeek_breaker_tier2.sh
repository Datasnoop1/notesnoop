#!/bin/bash
# Tier-2 emergency circuit breaker (R18 Phase 2b). At volume usage
# > 185 GB sustained, take the platform read-only:
#   1. Stop all writer compose services
#   2. Replace pg_hba.conf with breaker.conf (only postgres + backup_user)
#   3. Reload postgres (no service restart needed)
#   4. Wait up to 60s for active pg_dump to finish gracefully
#   5. pg_terminate_backend on remaining non-postgres/non-backup_user sessions
#   6. SIGTERM remaining pg_dump only after grace expired
#   7. AUTOVACUUM REMAINS ON (essential for draining bloat)
#
# Cron cadence: every minute.
# Action is INTENTIONALLY one-way for safety. Recovery is operator-driven:
#   - Free up disk
#   - mv /etc/postgresql/16/main/pg_hba.conf.normal back into place
#   - systemctl reload postgresql@16-main
#   - docker compose -f /opt/leadpeek/docker-compose.yml start <services>
#   - rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier2.tripped

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"
COMPOSE="docker compose -f $LEADPEEK_DIR/docker-compose.yml"

TIER2_BYTES=$((185 * 1024 * 1024 * 1024))
SUSTAIN_MINUTES=2
PG_HBA_LIVE="/etc/postgresql/16/main/pg_hba.conf"
PG_HBA_NORMAL="/etc/postgresql/16/main/pg_hba.conf.normal"
BREAKER_CONF="$LEADPEEK_DIR/deploy/breaker_pg_hba.conf"
WRITER_SERVICES=(backend enrichment-worker staatsblad-bulk-worker nbb-backload-worker)
PG_DUMP_GRACE_SEC=60

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/breaker_tier2.lock"
TRIPPED_FLAG="$STATE_DIR/breaker_tier2.tripped"
SUSTAIN_FILE="$STATE_DIR/breaker_tier2.streak"
LOG="$STATE_DIR/breaker_tier2.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

VOL_USED=$(df -B1 /mnt/volume-hel1-1 | awk 'NR==2 {print $3}')
GB=$((1024*1024*1024))

if [ -f "$TRIPPED_FLAG" ]; then
    log "tier2 already tripped; vol_used=$((VOL_USED/GB))G; awaiting manual reset"
    exit 0
fi

# Tick log so the meta-watchdog sees the file mtime advance even on quiet
# days. Without this, the breaker_tier2 log would look stale to meta.
log "tick: vol_used=$((VOL_USED/GB))G threshold=$((TIER2_BYTES/GB))G"

if [ "$VOL_USED" -le "$TIER2_BYTES" ]; then
    rm -f "$SUSTAIN_FILE"
    exit 0
fi

streak=0
[ -f "$SUSTAIN_FILE" ] && streak=$(cat "$SUSTAIN_FILE" 2>/dev/null || echo 0)
[[ "$streak" =~ ^[0-9]+$ ]] || streak=0
streak=$((streak + 1))
echo "$streak" > "$SUSTAIN_FILE"
log "vol_used=$((VOL_USED/GB))G > 185G; sustain=$streak/$SUSTAIN_MINUTES"

if [ "$streak" -lt "$SUSTAIN_MINUTES" ]; then
    exit 0
fi

# TRIP — full read-only mode
log "===== TIER-2 BREAKER TRIPPING ====="

# Pre-flight: confirm artifacts are in place
[ -f "$BREAKER_CONF" ] || { log "ABORT: $BREAKER_CONF missing — cannot trip Tier-2"; exit 0; }
[ -f "$PG_HBA_LIVE" ]  || { log "ABORT: $PG_HBA_LIVE missing"; exit 0; }

# Send the alert FIRST, before stopping the backend container that the
# alert helper SMTPs through. r18_alert.sh has a persistent /var/spool
# fallback, but pre-stop alerting is more reliable AND we MUST include
# recovery instructions here — the post-trip alert (line 175 below) goes
# through the same backend container which we're about to stop, so it
# will end up in the spool directory and only reach the operator if they
# specifically check there.
ALERT_BODY=$(cat <<EOF
TIER-2 BREAKER TRIPPING.
vol_used=$((VOL_USED/GB))G > 185G threshold (sustained $streak min)

Actions about to fire:
  1. stop writer compose services (backend, enrichment, staatsblad-bulk, nbb-backload)
  2. swap /etc/postgresql/16/main/pg_hba.conf for breaker config (only postgres + backup_user can connect)
  3. systemctl reload postgresql@16-main (no service restart, autovacuum unaffected)
  4. wait up to 60s for in-flight pg_dump to finish gracefully
  5. pg_terminate_backend on non-postgres/non-backup_user sessions
  6. SIGTERM any remaining pg_dump (post-grace)

RECOVERY (OPERATOR-DRIVEN, fully manual):
  1. Free disk on /mnt/volume-hel1-1 (drop staging cluster, prune dumps, etc.)
  2. Restore the live pg_hba.conf:
       sudo cp /etc/postgresql/16/main/pg_hba.conf.normal \\
              /etc/postgresql/16/main/pg_hba.conf
  3. Reload postgres (no restart needed):
       sudo systemctl reload postgresql@16-main
  4. Restart writer services:
       sudo docker compose -f /opt/leadpeek/docker-compose.yml start \\
            backend enrichment-worker staatsblad-bulk-worker nbb-backload-worker
  5. Clear the tripped flag:
       sudo rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier2.tripped

Full runbook: /opt/leadpeek/docs/r18-operations.md
Spooled post-trip alerts (if backend was down for emails): /var/spool/leadpeek-alerts/
EOF
)
bash "$ALERT" disk-tier2 "$ALERT_BODY" || true

# 1. Stop writer services
for svc in "${WRITER_SERVICES[@]}"; do
    log "stopping $svc"
    $COMPOSE stop "$svc" 2>&1 | tee -a "$LOG" || true
done

# 2. Save current pg_hba.conf and move breaker.conf into place.
# CRITICAL: only save .normal if it doesn't already exist. If breaker
# fires twice (e.g. operator clears tripped-flag without restoring
# pg_hba.conf), the second run would otherwise copy the BREAKER config
# over .normal, destroying the only path back to working pg_hba.
TS=$(date -u +%Y%m%dT%H%M%SZ)
log "snapshotting current pg_hba.conf → $PG_HBA_NORMAL.$TS"
cp "$PG_HBA_LIVE" "$PG_HBA_NORMAL.$TS" 2>&1 | tee -a "$LOG" || true

if [ -f "$PG_HBA_NORMAL" ]; then
    log "$PG_HBA_NORMAL already exists (prior trip) — keeping it; not overwriting"
else
    log "saving baseline pg_hba.conf → $PG_HBA_NORMAL (first trip)"
    cp "$PG_HBA_LIVE" "$PG_HBA_NORMAL"
fi

log "installing breaker config to $PG_HBA_LIVE"
install -m 640 -o postgres -g postgres "$BREAKER_CONF" "$PG_HBA_LIVE"

# 3. Reload postgres (no service restart needed for pg_hba)
log "reloading postgres"
systemctl reload postgresql@16-main 2>&1 | tee -a "$LOG" || true
sleep 2

# 4. Grace period for active pg_dump
log "waiting up to ${PG_DUMP_GRACE_SEC}s for active pg_dump to finish"
GRACE_END=$(( $(date +%s) + PG_DUMP_GRACE_SEC ))
while [ "$(date +%s)" -lt "$GRACE_END" ]; do
    PG_DUMP_PIDS=$(pgrep -f '/usr/lib/postgresql/16/bin/pg_dump' || true)
    if [ -z "$PG_DUMP_PIDS" ]; then
        log "no pg_dump in flight; grace done"
        break
    fi
    sleep 5
done

# 5. Terminate remaining non-superuser, non-backup_user sessions
[ -f /etc/leadpeek/backup.env ] || log "/etc/leadpeek/backup.env missing; skipping pg_terminate"
if [ -f /etc/leadpeek/backup.env ]; then
    # shellcheck disable=SC1091
    set -a; . /etc/leadpeek/backup.env; set +a
    log "pg_terminate_backend on non-superuser, non-backup_user sessions"
    PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
        SELECT pid || '|' || usename || '|terminated=' || pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND usename IS DISTINCT FROM 'postgres'
          AND usename IS DISTINCT FROM 'backup_user'
          AND backend_type = 'client backend';
    " 2>&1 | tee -a "$LOG" || true
fi

# 6. SIGTERM any remaining pg_dump (grace expired)
PG_DUMP_REMAINING=$(pgrep -f '/usr/lib/postgresql/16/bin/pg_dump' || true)
if [ -n "$PG_DUMP_REMAINING" ]; then
    log "grace expired; SIGTERM pg_dump pids: $PG_DUMP_REMAINING"
    for pid in $PG_DUMP_REMAINING; do
        kill -TERM "$pid" 2>/dev/null || true
    done
fi

ts > "$TRIPPED_FLAG"
rm -f "$SUSTAIN_FILE"

bash "$ALERT" disk-tier2 "$(printf 'TIER-2 TRIP COMPLETE.\nvol_used_at_trip=%sG\n\nAll writer services stopped.\npg_hba.conf swapped to breaker config (autovacuum unaffected).\nNon-superuser sessions terminated.\n\nRecovery (operator-only):\n  1. Free volume disk\n  2. cp /etc/postgresql/16/main/pg_hba.conf.normal /etc/postgresql/16/main/pg_hba.conf\n     (or use the timestamped backup written next to it)\n  3. systemctl reload postgresql@16-main\n  4. docker compose -f /opt/leadpeek/docker-compose.yml start backend enrichment-worker staatsblad-bulk-worker nbb-backload-worker\n  5. rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier2.tripped' \
    "$((VOL_USED/GB))")" || true

log "===== TIER-2 BREAKER TRIPPED ====="
exit 1
