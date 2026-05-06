#!/bin/bash
# Monthly partial restore drill (R18 Phase 2c).
#
# Restores schema (with the f_unaccent stub workaround) plus data for the
# 5 largest tables into an ephemeral pgvector/pg16 docker. Compares row
# counts to live; passes if all 5 match exactly. Pre-checks free space
# before starting.
#
# Cron cadence: monthly (1st Sun 04:00 UTC).
# Runtime: 30-90 min depending on largest-table sizes; cleans up on exit.

set -uo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

VOLUME_LINK="/mnt/volume-hel1-1/backups/CURRENT.dump.zst"
SCRATCH_BASE="/mnt/volume-hel1-1/scratch"
CONTAINER_NAME="r18-drill-partial"
PORT=55442
PGVER_IMAGE="pgvector/pgvector:pg16"
N_TABLES=5

STATE_DIR="$SCRIPTS_DIR/_watchdog_state"
install -d -m 700 "$STATE_DIR"
LOCK="$STATE_DIR/drill_partial.lock"
LOG="$STATE_DIR/drill_partial.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }

exec 9>"$LOCK"
flock -n 9 || { log "another instance running"; exit 0; }

# Cron fires every Sunday; gate to first Sunday of the month
DOM=$(date +%d)
if [ "${DOM#0}" -gt 7 ]; then
    log "skip: dom=$DOM (only first Sunday of month runs)"
    exit 0
fi

cleanup() {
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$SCRATCH_BASE/$CONTAINER_NAME"
}
trap cleanup EXIT

log "=== partial drill START ==="

DUMP_PATH=$(readlink -f "$VOLUME_LINK" 2>/dev/null || echo "")
[ -n "$DUMP_PATH" ] && [ -f "$DUMP_PATH" ] || { bash "$ALERT" drill-fail "partial drill: CURRENT missing"; exit 1; }

# Pre-flight: skip if volume is near breaker threshold
VOL_USED=$(df -B1 /mnt/volume-hel1-1 | awk 'NR==2 {print $3}')
GB=$((1024*1024*1024))
if [ "$VOL_USED" -gt $((150 * GB)) ]; then
    log "ABORT: volume at $((VOL_USED/GB))G > 150G — skipping to avoid breaker trip"
    bash "$ALERT" drill-skipped "Partial drill skipped: volume at $((VOL_USED/GB))G > 150G safety threshold" || true
    exit 0
fi

# Pre-pull image (a recent docker prune may have removed it)
docker pull "$PGVER_IMAGE" 2>&1 | tail -3

[ -f /etc/leadpeek/backup.env ] || { log "/etc/leadpeek/backup.env missing"; exit 1; }
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a

# Identify the 5 largest user tables on the live cluster
TOP_TABLES=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    SELECT relname FROM pg_stat_user_tables
    ORDER BY pg_total_relation_size(relid) DESC LIMIT $N_TABLES;
" | grep -v '^$')

if [ -z "$TOP_TABLES" ]; then
    bash "$ALERT" drill-fail "partial drill: could not identify top tables on live cluster" || true
    exit 1
fi
log "top tables: $(echo "$TOP_TABLES" | tr '\n' ' ')"

# Pre-flight: estimate space need (~2x sum of top-N-table sizes for safety).
# Compute server-side with the same ORDER BY ... LIMIT to avoid round-tripping
# the table-name list through bash + sed (the prior version had a quoting
# fragility if a relname ever contained an apostrophe).
NEEDED=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "
    SELECT (COALESCE(SUM(pg_total_relation_size(relid)),0) * 2)::bigint
    FROM (
        SELECT relid FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC LIMIT $N_TABLES
    ) t;
")
SCRATCH_FREE=$(df -B1 "$SCRATCH_BASE" 2>/dev/null | awk 'NR==2 {print $4}')
[ -n "$SCRATCH_FREE" ] || SCRATCH_FREE=0
log "needed=$((NEEDED/GB))G scratch_free=$((SCRATCH_FREE/GB))G"
if [ "$SCRATCH_FREE" -lt "$NEEDED" ]; then
    bash "$ALERT" drill-fail "partial drill: insufficient scratch space ($((SCRATCH_FREE/GB))G < $((NEEDED/GB))G)" || true
    exit 1
fi

# Spin ephemeral pgvector
mkdir -p "$SCRATCH_BASE/$CONTAINER_NAME"
docker run -d --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD=drill \
    -v "$SCRATCH_BASE/$CONTAINER_NAME:/var/lib/postgresql/data" \
    -p "127.0.0.1:$PORT:5432" \
    "$PGVER_IMAGE" >/dev/null
for _ in $(seq 1 30); do docker exec "$CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done

PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -tAc "CREATE DATABASE leadpeek_drill" >/dev/null
PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent', $1) $$;
SQL

# Schema then data — pg_restore's default IS to continue on error; the
# previous --exit-on-error=0 was invalid syntax that broke the drill.
log "schema restore"
zstd -dc "$DUMP_PATH" | docker exec -i "$CONTAINER_NAME" \
    pg_restore --schema-only --no-owner --no-privileges \
    -U postgres -d leadpeek_drill >/dev/null 2>&1 || true

# Validate top-table relnames against a strict identifier pattern before
# interpolating into pg_restore -t flags or psql identifier quoting. Names
# from pg_stat_user_tables are catalog-trusted but a future quoted-identifier
# rename could include surprising characters.
SAFE_RE='^[a-zA-Z_][a-zA-Z0-9_]*$'
SAFE_TABLES=""
for t in $TOP_TABLES; do
    if [[ "$t" =~ $SAFE_RE ]]; then
        SAFE_TABLES+="$t"$'\n'
    else
        log "skipping table with non-safe identifier: $t"
    fi
done
TOP_TABLES="$SAFE_TABLES"

log "data restore for top $N_TABLES tables"
T_FLAGS=$(printf '%s' "$TOP_TABLES" | sed 's/^/-t /' | tr '\n' ' ')
zstd -dc "$DUMP_PATH" | docker exec -i "$CONTAINER_NAME" \
    pg_restore --data-only --no-owner --no-privileges \
    -U postgres -d leadpeek_drill $T_FLAGS 2>&1 | tail -10
DATA_EXIT=${PIPESTATUS[1]}

# Compare counts
MISMATCHES=""
for t in $TOP_TABLES; do
    LIVE=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc "SELECT count(*) FROM \"$t\"")
    REST=$(PGPASSWORD=drill psql -h 127.0.0.1 -p "$PORT" -U postgres -d leadpeek_drill -tAc "SELECT count(*) FROM \"$t\"" 2>/dev/null || echo "ERR")
    log "  $t: live=$LIVE restored=$REST"
    [ "$LIVE" = "$REST" ] || MISMATCHES+="$t: live=$LIVE != restored=$REST\n"
done

if [ -n "$MISMATCHES" ]; then
    log "FAIL: $MISMATCHES"
    bash "$ALERT" drill-fail "Partial drill row-count mismatches:\n$MISMATCHES" || true
    exit 1
fi

log "PASS — all $N_TABLES table counts matched"
bash "$ALERT" drill-pass "Partial drill passed.\nTop $N_TABLES tables restored with exact row-count match:\n$(echo "$TOP_TABLES" | tr '\n' ' ')" || true
exit 0
