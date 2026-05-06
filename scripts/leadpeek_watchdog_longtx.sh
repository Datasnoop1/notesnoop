#!/bin/bash
# Long-transaction watchdog (R18 Phase 2b).
#   - idle-in-transaction > 1h, NOT backup_user → pg_cancel_backend
#   - any active transaction > 2h → ALERT only (don't auto-kill, may be
#     a legitimate migration or analysis)
#
# Cron cadence: every 5 minutes.
#
# IMPORTANT: backup_user is strictly exempted. Long-running pg_dump
# legitimately holds an open transaction during the dump.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

IDLE_CANCEL_MIN=60
ANY_TX_WARN_MIN=120

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/longtx.lock"
LAST_WARN_ALERT="$STATE_DIR/longtx_warn.last_alert"
LOG="$STATE_DIR/longtx.log"
ALERT_REPEAT_MIN="${LONGTX_ALERT_REPEAT_MIN:-60}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

# Log a tick on every invocation so the meta-watchdog sees fresh mtime even
# when there's nothing to cancel. Without this line, the meta would alert
# "stale" forever when the cluster has no long transactions.
log "tick: scanning for long transactions"

[ -f /etc/leadpeek/backup.env ] || { log "/etc/leadpeek/backup.env missing"; exit 0; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a

# 1. Cancel idle-in-transaction > 1h, exempt backup_user
CANCELLED=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    WITH targets AS (
        SELECT pid, usename, state,
               EXTRACT(EPOCH FROM (now() - state_change))::int AS state_age_s,
               left(coalesce(query,''), 200) AS qhead
        FROM pg_stat_activity
        WHERE state = 'idle in transaction'
          AND usename IS DISTINCT FROM 'backup_user'
          AND now() - state_change > interval '${IDLE_CANCEL_MIN} minutes'
    )
    SELECT pid || '|' || usename || '|' || state_age_s || '|' || qhead || '|cancelled=' || pg_cancel_backend(pid)
    FROM targets;
" 2>&1)

SCRUB="$SCRIPTS_DIR/r18_scrub_journal.sh"
if [ -n "$CANCELLED" ]; then
    SCRUBBED=$(printf '%s' "$CANCELLED" | bash "$SCRUB" 2>/dev/null || printf '%s' "$CANCELLED")
    log "cancelled idle-in-tx: $SCRUBBED"
    bash "$ALERT" longtx-cancel "Cancelled idle-in-transaction sessions older than ${IDLE_CANCEL_MIN}m:\n$SCRUBBED" || true
fi

# 2. Alert on any active transaction > 2h (no auto-cancel)
LONG_TX=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    SELECT pid || '|' || usename || '|' || state || '|' ||
           EXTRACT(EPOCH FROM (now() - xact_start))::int || '|' ||
           left(coalesce(query,''), 200)
    FROM pg_stat_activity
    WHERE xact_start IS NOT NULL
      AND now() - xact_start > interval '${ANY_TX_WARN_MIN} minutes'
      AND usename IS DISTINCT FROM 'backup_user'
      AND pid <> pg_backend_pid();
" 2>&1)

if [ -z "$LONG_TX" ]; then
    exit 0
fi

# Cooldown for the warn alert (cancel alert always fires; warn de-dupes)
should_alert=1
if [ -f "$LAST_WARN_ALERT" ]; then
    la_ts=$(cat "$LAST_WARN_ALERT" 2>/dev/null || echo "")
    if [ -n "$la_ts" ]; then
        la_epoch=$(date -d "$la_ts" +%s 2>/dev/null || echo 0)
        if [ $(( ($(date +%s) - la_epoch) / 60 )) -lt "$ALERT_REPEAT_MIN" ]; then
            should_alert=0
        fi
    fi
fi

SCRUBBED_LONG=$(printf '%s' "$LONG_TX" | bash "$SCRUB" 2>/dev/null || printf '%s' "$LONG_TX")
log "long-tx > ${ANY_TX_WARN_MIN}m: $SCRUBBED_LONG"
if [ "$should_alert" = "1" ]; then
    bash "$ALERT" longtx-warn "Active transactions running > ${ANY_TX_WARN_MIN}m (NOT auto-cancelled — investigate):\n$SCRUBBED_LONG" || true
    ts > "$LAST_WARN_ALERT"
fi
exit 0
