#!/bin/bash
# pg_wal size watchdog (R18 Phase 2b). Two thresholds:
#   - 6 GB sustained → ALERT (operator action)
#   - 8 GB sustained 5+ min → CANCEL the oldest non-backup_user query
#     holding xmin (the most likely cause of unbounded WAL growth post
#     archive_mode=off is a long-running transaction pinning xmin)
#
# Cron cadence: every minute. Sustain check via two-strike state file.
#
# IMPORTANT: backup_user is exempted from cancellation. During pg_dump,
# the backup connection legitimately holds the oldest xmin; cancelling it
# would defeat the entire backup strategy.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

PG_WAL_DIR="/mnt/volume-hel1-1/pgsql-prod/main/pg_wal"
WARN_BYTES=$((6 * 1024 * 1024 * 1024))
ACTION_BYTES=$((8 * 1024 * 1024 * 1024))
ACTION_SUSTAIN_MINUTES=5

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/pgwal.lock"
LAST_ALERT="$STATE_DIR/pgwal.last_alert"
ACTION_STREAK="$STATE_DIR/pgwal.action_streak"
LOG="$STATE_DIR/pgwal.log"
ALERT_REPEAT_MIN="${PGWAL_ALERT_REPEAT_MIN:-30}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

if [ ! -d "$PG_WAL_DIR" ]; then
    log "pg_wal dir $PG_WAL_DIR not found; nothing to monitor"
    exit 0
fi

WAL_BYTES=$(du -sb "$PG_WAL_DIR" 2>/dev/null | awk '{print $1}')
[ -n "$WAL_BYTES" ] || { log "could not size pg_wal"; exit 0; }
GB=$((1024*1024*1024))
log "pg_wal_bytes=$WAL_BYTES ($((WAL_BYTES/GB))G)"

if [ "$WAL_BYTES" -lt "$WARN_BYTES" ]; then
    rm -f "$ACTION_STREAK"
    exit 0
fi

# At or above warn threshold — emit alert with cooldown
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
if [ "$should_alert" = "1" ]; then
    bash "$ALERT" pgwal-warn "pg_wal at $((WAL_BYTES/GB))G > 6G warn threshold; investigate long-running transactions" || true
    ts > "$LAST_ALERT"
fi

# Action threshold — sustained 5+ min before cancelling
if [ "$WAL_BYTES" -lt "$ACTION_BYTES" ]; then
    rm -f "$ACTION_STREAK"
    exit 0
fi

streak=0
[ -f "$ACTION_STREAK" ] && streak=$(cat "$ACTION_STREAK" 2>/dev/null || echo 0)
[[ "$streak" =~ ^[0-9]+$ ]] || streak=0
streak=$((streak + 1))
echo "$streak" > "$ACTION_STREAK"
log "action threshold $((WAL_BYTES/GB))G > 8G; streak=$streak/$ACTION_SUSTAIN_MINUTES"

if [ "$streak" -lt "$ACTION_SUSTAIN_MINUTES" ]; then
    log "below action sustain threshold ($streak min); waiting"
    exit 0
fi

# Sustained ≥ 5 min: cancel the oldest non-backup_user backend holding the
# global xmin. Strict exemption for backup_user.
log "ACTION: cancelling oldest non-backup_user backend holding xmin"
[ -f /etc/leadpeek/backup.env ] || { log "ABORT: /etc/leadpeek/backup.env missing"; exit 0; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a
: "${PGHOST:?}" "${PGPORT:?}" "${PGUSER:?}" "${PGDATABASE:?}" "${PGPASSFILE:?}"

CANCEL_OUT=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    WITH cand AS (
        SELECT pid, usename, state, query_start, xact_start,
               left(coalesce(query,''), 200) AS qhead
        FROM pg_stat_activity
        WHERE backend_xmin IS NOT NULL
          AND usename IS DISTINCT FROM 'backup_user'
          AND pid <> pg_backend_pid()
        ORDER BY xact_start NULLS LAST, query_start NULLS LAST
        LIMIT 1
    )
    SELECT pid, pg_cancel_backend(pid), usename, state, qhead FROM cand;
" 2>&1)

log "cancel result: $CANCEL_OUT"
SCRUB="$SCRIPTS_DIR/r18_scrub_journal.sh"
SCRUBBED=$(printf '%s' "$CANCEL_OUT" | bash "$SCRUB" 2>/dev/null || printf '%s' "$CANCEL_OUT")
bash "$ALERT" pgwal-action "pg_wal at $((WAL_BYTES/GB))G sustained > 8G for $streak min.\nCancelled oldest non-backup_user backend holding xmin:\n$SCRUBBED" || true
rm -f "$ACTION_STREAK"
exit 1
