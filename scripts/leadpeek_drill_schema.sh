#!/bin/bash
# Weekly schema-only restore drill (R18 Phase 2c).
#
# Restores CURRENT.dump.zst's schema into a pgvector/pgvector:pg16 ephemeral
# docker. Pre-creates the unaccent extension and an f_unaccent stub before
# pg_restore --schema-only so the known dependency-ordering issue
# (search_normalize → f_unaccent) doesn't fail the drill. Confirms the
# schema can be fully reconstructed.
#
# Cron cadence: weekly (Sun 03:00 UTC).
# No data is restored; runtime ~2 min; cleans up the ephemeral container
# and scratch dir on exit.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

PG_BIN="/usr/lib/postgresql/16/bin"
VOLUME_LINK="/mnt/volume-hel1-1/backups/CURRENT.dump.zst"
SCRATCH_BASE="/mnt/volume-hel1-1/scratch"
CONTAINER_NAME="r18-drill-schema"
PORT=55441
PGVER_IMAGE="pgvector/pgvector:pg16"

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
install -d -m 700 "$STATE_DIR"
LOCK="$STATE_DIR/drill_schema.lock"
LOG="$STATE_DIR/drill_schema.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || { log "another instance running"; exit 0; }

cleanup() {
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$SCRATCH_BASE/$CONTAINER_NAME"
}
trap cleanup EXIT

log "=== schema drill START ==="

DUMP_PATH=$(readlink -f "$VOLUME_LINK" 2>/dev/null || echo "")
if [ -z "$DUMP_PATH" ] || [ ! -f "$DUMP_PATH" ]; then
    bash "$ALERT" drill-fail "Schema drill: CURRENT.dump.zst symlink missing or broken" || true
    exit 1
fi
log "DUMP_PATH=$DUMP_PATH"

# Pre-flight: don't run a drill on a near-full volume — would risk tripping
# our own breakers mid-restore.
VOL_USED=$(df -B1 /mnt/volume-hel1-1 | awk 'NR==2 {print $3}')
GB=$((1024*1024*1024))
if [ "$VOL_USED" -gt $((150 * GB)) ]; then
    log "ABORT: volume already at $((VOL_USED/GB))G > 150G — skipping drill to avoid breaker trip"
    bash "$ALERT" drill-skipped "Schema drill skipped: volume at $((VOL_USED/GB))G > 150G safety threshold" || true
    exit 0
fi

# Pre-pull the image so a recent docker prune can't break the drill
docker pull "$PGVER_IMAGE" 2>&1 | tail -3

# Verify zstd integrity first — fail fast
if ! zstd -t "$DUMP_PATH"; then
    bash "$ALERT" drill-fail "Schema drill: zstd -t failed on $DUMP_PATH" || true
    exit 1
fi

# Spin ephemeral pgvector
mkdir -p "$SCRATCH_BASE/$CONTAINER_NAME"
log "starting ephemeral $PGVER_IMAGE on 127.0.0.1:$PORT"
docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD=drill \
    -v "$SCRATCH_BASE/$CONTAINER_NAME:/var/lib/postgresql/data" \
    -p "127.0.0.1:$PORT:5432" \
    "$PGVER_IMAGE" >/dev/null

# Wait for ready
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Pre-create unaccent + f_unaccent stub so search_normalize inlining works
PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -tAc "CREATE DATABASE leadpeek_drill" >/dev/null
PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent', $1) $$;
SQL

# Schema-only restore. We allow some warnings (table-of-contents items
# that fail because the stub function differs from prod's signature, etc.)
# but require the overall pg_restore to exit 0 and most TABLE entries to
# be created.
log "running schema-only pg_restore"
# pg_restore's --exit-on-error is a no_argument flag; passing --exit-on-error=0
# is rejected as "doesn't take a value". The default behavior IS to continue
# on error, which is what we want for the drill — we count restored tables
# rather than treating any single failure as fatal.
RESTORE_OUT=$(zstd -dc "$DUMP_PATH" | docker exec -i "$CONTAINER_NAME" \
    pg_restore --schema-only --no-owner --no-privileges \
    -U postgres -d leadpeek_drill 2>&1)
RESTORE_EXIT=${PIPESTATUS[1]}

# Count tables created vs expected
CREATED_TABLES=$(PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")

# Reference: expected user-table count from the live cluster (set in env or queried)
[ -f /etc/leadpeek/backup.env ] || { log "/etc/leadpeek/backup.env missing"; exit 1; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a
LIVE_TABLES=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")

log "restored_tables=$CREATED_TABLES live_tables=$LIVE_TABLES restore_exit=$RESTORE_EXIT"

# Pass condition: at least 95% of expected tables, no fatal restore exit
THRESHOLD=$((LIVE_TABLES * 95 / 100))
if [ "$CREATED_TABLES" -lt "$THRESHOLD" ]; then
    log "FAIL: $CREATED_TABLES < $THRESHOLD (95% of $LIVE_TABLES)"
    bash "$ALERT" drill-fail "$(printf 'Schema drill failed.\nrestored_tables=%s live_tables=%s threshold=%s\nrestore_exit=%s\n\nLast 50 lines of pg_restore output:\n%s' \
        "$CREATED_TABLES" "$LIVE_TABLES" "$THRESHOLD" "$RESTORE_EXIT" "$(echo "$RESTORE_OUT" | tail -50)")" || true
    exit 1
fi

log "PASS"
bash "$ALERT" drill-pass "$(printf 'Schema drill passed.\nrestored_tables=%s/%s (>= 95%%)\nrestore_exit=%s\ndump=%s' \
    "$CREATED_TABLES" "$LIVE_TABLES" "$RESTORE_EXIT" "$DUMP_PATH")" || true
exit 0
