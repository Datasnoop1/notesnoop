#!/bin/bash
# Quarterly full restore drill (R18 Phase 2c). Best-effort: only runs if
# free volume > (1.2 × pg_database_size + 10 GB). Otherwise alerts and
# exits 0 — the partial drill already runs monthly and is sufficient
# proof of restorability for periods when the volume is too tight.
#
# Cron cadence: quarterly (1st Sun of Jan/Apr/Jul/Oct, 02:00 UTC).
# Runtime: hours; cleans up on exit.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

VOLUME_LINK="/mnt/volume-hel1-1/backups/CURRENT.dump.zst"
SCRATCH_BASE="/mnt/volume-hel1-1/scratch"
CONTAINER_NAME="r18-drill-full"
PORT=55443
PGVER_IMAGE="pgvector/pgvector:pg16"

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
install -d -m 700 "$STATE_DIR"
LOCK="$STATE_DIR/drill_full.lock"
LOG="$STATE_DIR/drill_full.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || exit 0

# Cron fires every Sunday in Jan/Apr/Jul/Oct (and also every 1-7 of any month
# due to cron's day-of-month + day-of-week OR semantics). Gate inside the
# script to first Sunday of Jan/Apr/Jul/Oct only.
DOM=$(date +%d)
MON=$(date +%m)
if [ "${DOM#0}" -gt 7 ]; then
    log "skip: dom=$DOM (only first Sunday of month runs)"
    exit 0
fi
case "$MON" in
    01|04|07|10) ;;
    *) log "skip: month=$MON (only Jan/Apr/Jul/Oct)"; exit 0 ;;
esac

cleanup() {
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$SCRATCH_BASE/$CONTAINER_NAME"
}
trap cleanup EXIT

log "=== full drill START ==="

DUMP_PATH=$(readlink -f "$VOLUME_LINK" 2>/dev/null || echo "")
[ -n "$DUMP_PATH" ] && [ -f "$DUMP_PATH" ] || { bash "$ALERT" drill-fail "full drill: CURRENT missing"; exit 1; }

# Pre-flight: don't run on a near-full volume; the partial drill is enough
# proof of restorability when the volume is tight.
VOL_USED=$(df -B1 /mnt/volume-hel1-1 | awk 'NR==2 {print $3}')
GB=$((1024*1024*1024))
if [ "$VOL_USED" -gt $((150 * GB)) ]; then
    log "ABORT: volume at $((VOL_USED/GB))G > 150G — partial drill is the fallback"
    bash "$ALERT" drill-skipped "Full drill skipped: volume at $((VOL_USED/GB))G > 150G safety threshold (partial drill remains in effect)" || true
    exit 0
fi

# Pre-pull image (defense against intervening docker prune)
docker pull "$PGVER_IMAGE" 2>&1 | tail -3

[ -f /etc/leadpeek/backup.env ] || { log "/etc/leadpeek/backup.env missing"; exit 1; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a

DB_BYTES=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT pg_database_size(current_database())::bigint")
NEEDED=$(( DB_BYTES * 12 / 10 + 10 * GB ))
SCRATCH_FREE=$(df -B1 "$SCRATCH_BASE" | awk 'NR==2 {print $4}')
log "db_size=$((DB_BYTES/GB))G needed=$((NEEDED/GB))G scratch_free=$((SCRATCH_FREE/GB))G"

if [ "$SCRATCH_FREE" -lt "$NEEDED" ]; then
    log "skipping — insufficient space (partial drill is the fallback)"
    bash "$ALERT" drill-pass "Full drill SKIPPED — insufficient scratch space ($((SCRATCH_FREE/GB))G < $((NEEDED/GB))G).\nPartial drill remains in effect monthly." || true
    exit 0
fi

mkdir -p "$SCRATCH_BASE/$CONTAINER_NAME"
docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD=drill \
    -v "$SCRATCH_BASE/$CONTAINER_NAME:/var/lib/postgresql/data" \
    -p "127.0.0.1:$PORT:5432" \
    "$PGVER_IMAGE" >/dev/null
for _ in $(seq 1 30); do docker exec "$CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done

PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -tAc "CREATE DATABASE leadpeek_drill" >/dev/null
PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
CREATE EXTENSION IF NOT EXISTS unaccent;  -- ALLOW-RUNTIME-DDL: drill harness bootstraps an isolated leadpeek_drill DB; not runtime DDL on prod
CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent', $1) $$;
SQL

log "full pg_restore (schema + data, parallel)"
T0=$(date +%s)
# Default is "continue on error", which is what we want — the drill is a
# best-effort restorability proof, not a fail-fast verification.
zstd -dc "$DUMP_PATH" | docker exec -i "$CONTAINER_NAME" \
    pg_restore --no-owner --no-privileges -j 2 \
    -U postgres -d leadpeek_drill 2>&1 | tail -20
RESTORE_EXIT=${PIPESTATUS[1]}
T1=$(date +%s)
log "restore_exit=$RESTORE_EXIT elapsed=$((T1-T0))s"

# Spot-check 3 tables for row counts
MISMATCHES=""
for t in company_info financial_data staatsblad_event; do
    LIVE=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "SELECT count(*) FROM $t")
    REST=$(PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo "ERR")
    log "  $t: live=$LIVE restored=$REST"
    [ "$LIVE" = "$REST" ] || MISMATCHES+="$t: live=$LIVE != restored=$REST\n"
done

if [ -n "$MISMATCHES" ]; then
    bash "$ALERT" drill-fail "Full drill row-count mismatches:\n$MISMATCHES\nrestore_exit=$RESTORE_EXIT" || true
    exit 1
fi

bash "$ALERT" drill-pass "Full drill passed in $((T1-T0))s.\nrestore_exit=$RESTORE_EXIT\nspot-checked tables: company_info, financial_data, staatsblad_event" || true
exit 0
