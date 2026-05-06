#!/bin/bash
# Weekly table-bloat check (R18 Phase 2c). Uses pgstattuple to find tables
# whose dead-tuple percentage exceeds the threshold; alerts the operator
# rather than auto-vacuuming (the regular autovacuum tuning from Phase 1
# should keep things in line; this is just an early-warning).
#
# Cron cadence: weekly (Sun 05:00 UTC).
# Read-only against prod.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

DEAD_PCT_THRESHOLD="${BLOAT_DEAD_PCT_THRESHOLD:-30}"
MIN_TABLE_BYTES=$((100 * 1024 * 1024))  # ignore tables < 100 MB (noise)

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/bloat.lock"
LOG="$STATE_DIR/bloat.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

[ -f /etc/leadpeek/backup.env ] || { log "/etc/leadpeek/backup.env missing"; exit 0; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a

# Confirm pgstattuple extension is available; create if missing
HAS_EXT=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT 1 FROM pg_extension WHERE extname='pgstattuple'" 2>/dev/null || echo "")
if [ -z "$HAS_EXT" ]; then
    # backup_user can't create extensions (not superuser). Fail soft:
    log "pgstattuple extension not installed; skipping (operator must run: CREATE EXTENSION pgstattuple as superuser)"
    exit 0
fi

# pgstattuple is expensive; sample only the largest 20 tables
RESULTS=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    WITH big AS (
        SELECT relid, schemaname, relname,
               pg_total_relation_size(relid) AS bytes
        FROM pg_stat_user_tables
        WHERE pg_total_relation_size(relid) > $MIN_TABLE_BYTES
        ORDER BY bytes DESC LIMIT 20
    )
    SELECT relname || '|' || (bytes/1024/1024) || '|' ||
           round((s.dead_tuple_percent)::numeric, 1) || '|' ||
           s.dead_tuple_count
    FROM big, LATERAL pgstattuple(format('%I.%I', schemaname, relname)) s
    WHERE s.dead_tuple_percent > $DEAD_PCT_THRESHOLD
    ORDER BY s.dead_tuple_percent DESC;
" 2>&1)

if [ -z "$RESULTS" ]; then
    log "GREEN — no tables over ${DEAD_PCT_THRESHOLD}% dead-tuple threshold"
    exit 0
fi

log "BLOAT: $RESULTS"
bash "$ALERT" "bloat-warn" "Bloat check found tables over ${DEAD_PCT_THRESHOLD}% dead-tuple threshold:\n\nrelname | size_mb | dead_pct | dead_count\n$RESULTS\n\nManual remediation if persistent: VACUUM (FULL) <table>; (note: takes an exclusive lock — schedule during a quiet window)" || true
exit 1
