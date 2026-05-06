#!/bin/bash
# DataSnoop production backup — R18 design.
#
# Replaces the old continuous-WAL-archiving + pg_basebackup approach. Now
# produces two pg_dump-based backups every 2 days, on separate failure
# domains (volume + root), each verified end-to-end.
#
# Lessons baked in (from the 2026-05-06 baseline run):
#   - Pin /usr/lib/postgresql/16/bin/pg_{dump,restore}; pg_dump 17 produces
#     a format pg_restore 16 cannot read.
#   - Resolve CURRENT/PREVIOUS via readlink -f before zstd -dc; zstd refuses
#     symlinks by default and silently produces zero output.
#   - Verify by data-extraction (pg_restore --data-only -f file.sql, count
#     COPY rows). The dump's schema-only restore has a known dependency-
#     ordering issue with public.search_normalize → public.f_unaccent; that
#     is tracked separately. Full schema-restore drills live in a sibling
#     script that pre-installs the helper functions.
#
# Operator gates:
#   This script never enables itself. The systemd timer
#   (deploy/leadpeek-backup.timer) is the activation surface; nothing fires
#   until `systemctl enable --now leadpeek-backup.timer`.
#
# Environment:
#   /etc/leadpeek/backup.env  Required. Must export PGHOST PGPORT PGUSER
#                             PGDATABASE PGPASSFILE for psql/pg_dump.
#   /root/.pgpass             Required, mode 0600. Contains the line
#                             PGHOST:PGPORT:PGDATABASE:PGUSER:<pwd>.
#
# Exit codes:
#   0  fully successful (volume backup + verification + root recompress)
#   0  also if root recompress was skipped due to insufficient root space
#      (volume backup is the primary; root is best-effort with a degraded
#      alert)
#   1  pre-flight aborted, volume backup failed, or sample verification
#      mismatched. The systemd OnFailure= unit emails the operator.

set -uo pipefail
umask 077  # sha256 sidecars + log files default to 0600/0700

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
ALERT="$SCRIPTS_DIR/r18_alert.sh"

VOLUME_DIR="/mnt/volume-hel1-1/backups"
ROOT_DIR="/var/lib/postgresql/backups"
SAMPLE_TABLE="company_info"

PG_BIN="/usr/lib/postgresql/16/bin"
PG_DUMP="$PG_BIN/pg_dump"
PG_RESTORE="$PG_BIN/pg_restore"

LOCK="/var/lock/leadpeek-backup.lock"
LOG_DIR="$SCRIPTS_DIR/_watchdog_state"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/leadpeek_backup.log"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG"; }
fail() { log "FAIL: $*"; bash "$ALERT" backup-fail "$(printf '%s\n\n--- last log ---\n%s\n' "$*" "$(tail -50 "$LOG")")" || true; exit 1; }

# --- single-instance guard --------------------------------------------------

exec 200>"$LOCK"
if ! flock -n 200; then
    log "another backup run is in flight — exiting cleanly"
    exit 0
fi

log "=== leadpeek_backup START ==="

# --- env + binary preflight -------------------------------------------------

[ -f /etc/leadpeek/backup.env ] || fail "/etc/leadpeek/backup.env missing — run r18_install.sh"
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a
: "${PGHOST:?backup.env: PGHOST not set}"
: "${PGPORT:?backup.env: PGPORT not set}"
: "${PGUSER:?backup.env: PGUSER not set}"
: "${PGDATABASE:?backup.env: PGDATABASE not set}"
: "${PGPASSFILE:?backup.env: PGPASSFILE not set}"
[ -r "$PGPASSFILE" ] || fail "PGPASSFILE $PGPASSFILE not readable"
PG_PASS_PERMS=$(stat -c '%a' "$PGPASSFILE" 2>/dev/null || echo 'unknown')
[ "$PG_PASS_PERMS" = "600" ] || fail ".pgpass mode must be 600 (got $PG_PASS_PERMS)"

[ -x "$PG_DUMP" ] || fail "$PG_DUMP not executable"
[ -x "$PG_RESTORE" ] || fail "$PG_RESTORE not executable"

[ -d "$VOLUME_DIR" ] || install -d -m 700 "$VOLUME_DIR"
[ -d "$ROOT_DIR" ] || install -d -m 700 "$ROOT_DIR"

# --- step 0: clean stale partials ------------------------------------------

log "step 0: cleaning stale .partial / .tmp from both backup dirs"
rm -f "$VOLUME_DIR"/*.partial "$VOLUME_DIR"/*.tmp 2>/dev/null || true
rm -f "$ROOT_DIR"/*.partial "$ROOT_DIR"/*.tmp 2>/dev/null || true

# --- pre-flight: fixed-headroom thresholds ---------------------------------

# Use byte-accurate disk-free to avoid `df -BG` whole-GB truncation that fails
# the threshold for e.g. 50.9 GiB free. All thresholds are in bytes internally.
free_bytes() { df -B1 "$1" | awk 'NR==2 {print $4}'; }
GB=$((1024*1024*1024))
THRESH_VOL=$((50 * GB))
THRESH_ROOT=$((20 * GB))

FREE_VOL=$(free_bytes /mnt/volume-hel1-1)
FREE_ROOT=$(free_bytes /)
log "preflight free_volume_bytes=$FREE_VOL ($((FREE_VOL/GB))G) free_root_bytes=$FREE_ROOT ($((FREE_ROOT/GB))G)"
[ "$FREE_VOL" -gt "$THRESH_VOL" ] || fail "preflight: volume free $((FREE_VOL/GB))G < 50G threshold"

# Root threshold is checked again before the recompress step; we don't fail
# the whole run here because the volume backup is the primary. But warn now
# so the operator sees the degraded state in the log.
if [ "$FREE_ROOT" -le "$THRESH_ROOT" ]; then
    log "preflight: root free $((FREE_ROOT/GB))G <= 20G — root copy will be skipped (DEGRADED)"
fi

# --- step 1: volume backup (primary) ---------------------------------------

TIMESTAMP=$(date -u +%Y%m%dT%H%M%S)
VOL_FINAL="$VOLUME_DIR/pgdump-$TIMESTAMP.dump.zst"
VOL_PARTIAL="$VOL_FINAL.partial"
VOL_SHA="$VOL_FINAL.sha256"

log "step 1: pg_dump → zstd -3 → $VOL_PARTIAL"
T0=$(date +%s)
# Run pg_dump as root over TCP so PGPASSFILE / .pgpass on /root resolves
# correctly. Connecting as backup_user (not postgres superuser) means the
# long-tx watchdog can identify and exempt this connection by usename.
PGHOST="$PGHOST" PGPORT="$PGPORT" PGUSER="$PGUSER" PGDATABASE="$PGDATABASE" PGPASSFILE="$PGPASSFILE" \
"$PG_DUMP" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    --format=custom --compress=0 \
  | nice -n 19 ionice -c 3 zstd -T2 -3 -o "$VOL_PARTIAL"
DUMP_PS=("${PIPESTATUS[@]}")
T1=$(date +%s)
if [ "${DUMP_PS[0]}" != "0" ] || [ "${DUMP_PS[1]}" != "0" ]; then
    fail "pg_dump|zstd pipeline failed: pipestatus=${DUMP_PS[*]}"
fi
log "step 1: dump complete in $((T1 - T0))s, size=$(stat -c '%s' "$VOL_PARTIAL")"

# fsync — make sure bytes hit disk before we declare success
sync "$VOL_PARTIAL" 2>/dev/null || true

# zstd integrity
zstd -t "$VOL_PARTIAL" || fail "zstd -t failed on $VOL_PARTIAL"

# pg_restore --list (SIGPIPE-safe: full output, no head)
TOC=$(mktemp /tmp/leadpeek_backup_toc.XXXXXX)
trap 'rm -f "$TOC"' EXIT
zstd -dc "$VOL_PARTIAL" | "$PG_RESTORE" --list > "$TOC"
RESTORE_LIST_EXIT=${PIPESTATUS[1]}
if [ "$RESTORE_LIST_EXIT" != "0" ]; then
    fail "pg_restore --list failed (exit $RESTORE_LIST_EXIT)"
fi
TABLE_DATA_DUMP=$(grep -c "TABLE DATA " "$TOC" || true)
TABLE_DATA_LIVE=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
log "step 1: TOC table_data_in_dump=$TABLE_DATA_DUMP live_user_tables=$TABLE_DATA_LIVE"
# Allow ~5% drift (rare cases where a table is empty and pg_dump skips its TABLE DATA entry)
if [ "$TABLE_DATA_DUMP" -lt $((TABLE_DATA_LIVE * 95 / 100)) ]; then
    fail "TOC TABLE DATA count $TABLE_DATA_DUMP < 95% of live $TABLE_DATA_LIVE"
fi

# --- step 2: sample-data exact-row-count match -----------------------------

log "step 2: sample row-count verification on $SAMPLE_TABLE"
SAMPLE_SQL=$(mktemp /tmp/leadpeek_backup_sample.XXXXXX.sql)
trap 'rm -f "$TOC" "$SAMPLE_SQL"' EXIT
zstd -dc "$VOL_PARTIAL" | "$PG_RESTORE" --data-only --no-owner --no-privileges \
    -t "$SAMPLE_TABLE" -f "$SAMPLE_SQL"
SAMPLE_EXTRACT_EXIT=${PIPESTATUS[1]}
[ "$SAMPLE_EXTRACT_EXIT" = "0" ] || fail "pg_restore --data-only -t $SAMPLE_TABLE exited $SAMPLE_EXTRACT_EXIT"

EXTRACTED=$(awk '/^COPY .* FROM stdin/{flag=1;next} $0=="\\."{flag=0} flag' "$SAMPLE_SQL" | wc -l)
LIVE=$(PGPASSFILE="$PGPASSFILE" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -tAc \
    "SELECT count(*) FROM $SAMPLE_TABLE")
log "step 2: extracted=$EXTRACTED live=$LIVE"
[ "$EXTRACTED" = "$LIVE" ] || fail "sample row-count mismatch: dump=$EXTRACTED live=$LIVE"

# --- step 3: SHA256 + atomic promote to CURRENT ----------------------------

log "step 3: atomic promote to CURRENT, then sha256 sidecar"
mv "$VOL_PARTIAL" "$VOL_FINAL" || fail "rename .partial → final failed for $VOL_FINAL"
# sha256 the FINAL file with basename-only output, so the sidecar is
# verifiable via `cd "$VOLUME_DIR" && sha256sum -c <sha-file>` and never
# embeds an absolute path.
( cd "$VOLUME_DIR" && sha256sum "$(basename "$VOL_FINAL")" ) > "$VOL_SHA" || fail "sha256 sidecar failed"
ln -s "$(basename "$VOL_FINAL")" "$VOLUME_DIR/CURRENT.dump.zst.tmp" || fail "ln -s for CURRENT.tmp failed"
mv -T "$VOLUME_DIR/CURRENT.dump.zst.tmp" "$VOLUME_DIR/CURRENT.dump.zst" \
    || fail "atomic CURRENT symlink swap failed — retention WOULD delete the new dump; aborting before it does"

# --- step 4: root recompression (best-effort) ------------------------------

ROOT_SKIPPED=0
ROOT_FINAL=""
ROOT_PARTIAL=""

log "step 4: evaluating root recompression"
FREE_ROOT_NOW=$(free_bytes /)
EXISTING_PREV_BYTES=0
if [ -L "$ROOT_DIR/PREVIOUS.dump.zst" ]; then
    PREV_TARGET=$(readlink -f "$ROOT_DIR/PREVIOUS.dump.zst" || true)
    if [ -n "$PREV_TARGET" ] && [ -f "$PREV_TARGET" ]; then
        EXISTING_PREV_BYTES=$(stat -c '%s' "$PREV_TARGET")
    fi
fi
EXPECTED_NEW_BYTES=$(( $(stat -c '%s' "$VOL_FINAL") * 115 / 100 ))  # 15% margin
NEEDED_ROOT=$(( EXISTING_PREV_BYTES + EXPECTED_NEW_BYTES + 2 * GB ))
log "step 4: free_root_bytes=$FREE_ROOT_NOW ($((FREE_ROOT_NOW/GB))G) needed_bytes=$NEEDED_ROOT ($((NEEDED_ROOT/GB))G) existing_prev_bytes=$EXISTING_PREV_BYTES"

if [ "$FREE_ROOT_NOW" -le "$THRESH_ROOT" ] || [ "$FREE_ROOT_NOW" -lt "$NEEDED_ROOT" ]; then
    log "step 4: insufficient root space — skipping root copy"
    bash "$ALERT" backup-degraded-no-root \
        "$(printf 'Root recompression skipped.\nfree_root_bytes=%s needed_bytes=%s existing_prev_bytes=%s\nVolume backup at %s is the primary and is verified.' \
            "$FREE_ROOT_NOW" "$NEEDED_ROOT" "$EXISTING_PREV_BYTES" "$VOL_FINAL")" || true
    ROOT_SKIPPED=1
fi

if [ "$ROOT_SKIPPED" = "0" ]; then
    ROOT_FINAL="$ROOT_DIR/pgdump-$TIMESTAMP.dump.zst"
    ROOT_PARTIAL="$ROOT_FINAL.partial"
    ROOT_SHA="$ROOT_FINAL.sha256"

    log "step 4: recompress to root at zstd -12"
    DUMP_PATH=$(readlink -f "$VOLUME_DIR/CURRENT.dump.zst")
    T2=$(date +%s)
    (
        # Subshell: explicit error capture, does NOT abort main script
        set -uo pipefail
        zstd -dc "$DUMP_PATH" \
          | nice -n 19 ionice -c 3 zstd -12 -T2 -o "$ROOT_PARTIAL"
        ROOT_PS=("${PIPESTATUS[@]}")
        if [ "${ROOT_PS[0]}" != "0" ] || [ "${ROOT_PS[1]}" != "0" ]; then
            echo "RECOMPRESS_FAIL pipestatus=${ROOT_PS[*]}"
            exit 1
        fi
        zstd -t "$ROOT_PARTIAL" || { echo "RECOMPRESS_VERIFY_FAIL"; exit 2; }
    )
    ROOT_RC=$?
    T3=$(date +%s)
    if [ "$ROOT_RC" != "0" ]; then
        log "step 4: root recompression FAILED (rc=$ROOT_RC, $((T3 - T2))s) — alerting, leaving volume primary in place"
        rm -f "$ROOT_PARTIAL"
        bash "$ALERT" backup-degraded-no-root \
            "$(printf 'Root recompression failed (rc=%s).\nVolume backup at %s is the primary and is verified.\nLast log:\n%s' \
                "$ROOT_RC" "$VOL_FINAL" "$(tail -30 "$LOG")")" || true
        ROOT_SKIPPED=1
    else
        log "step 4: recompress complete in $((T3 - T2))s, size=$(stat -c '%s' "$ROOT_PARTIAL")"
        if ! mv "$ROOT_PARTIAL" "$ROOT_FINAL"; then
            log "step 4: rename .partial → final failed for root copy — leaving volume primary in place"
            rm -f "$ROOT_PARTIAL"
            ROOT_SKIPPED=1
        else
            ( cd "$ROOT_DIR" && sha256sum "$(basename "$ROOT_FINAL")" ) > "$ROOT_SHA" \
                || log "step 4: sha256 sidecar write failed for root copy (non-fatal)"
            ln -s "$(basename "$ROOT_FINAL")" "$ROOT_DIR/PREVIOUS.dump.zst.tmp" \
                || { log "step 4: ln -s for PREVIOUS.tmp failed; rolling back"; rm -f "$ROOT_FINAL" "$ROOT_SHA"; ROOT_SKIPPED=1; }
            if [ "$ROOT_SKIPPED" = "0" ] && ! mv -T "$ROOT_DIR/PREVIOUS.dump.zst.tmp" "$ROOT_DIR/PREVIOUS.dump.zst"; then
                log "step 4: PREVIOUS symlink swap failed; rolling back"
                rm -f "$ROOT_DIR/PREVIOUS.dump.zst.tmp" "$ROOT_FINAL" "$ROOT_SHA"
                ROOT_SKIPPED=1
            fi
        fi
    fi
fi

# --- step 5: retention — keep only CURRENT (volume) and PREVIOUS (root) ---

log "step 5: retention pruning"
# Defensive: validate the symlink target matches the expected dump filename
# pattern before trusting it as a -name exclusion. If the link points
# anywhere unexpected, refuse to prune (better stale dumps than lost ones).
PUMP_RE='^pgdump-[0-9TZ]+\.dump\.zst$'

prune_dir() {
    local dir="$1" link="$2"
    local target
    target=$(basename "$(readlink -f "$dir/$link" 2>/dev/null || echo "")")
    if [ -z "$target" ] || [[ ! "$target" =~ $PUMP_RE ]]; then
        log "retention: $dir/$link target '$target' did not match $PUMP_RE — skipping prune (no deletions)"
        return
    fi
    find "$dir" -maxdepth 1 -type f \
        ! -name "$target" \
        ! -name "$target.sha256" \
        ! -name "*.partial" \
        ! -name "*.tmp" \
        \( -name 'pgdump-*.dump.zst' -o -name 'pgdump-*.dump.zst.sha256' \) \
        -delete -print | tee -a "$LOG"
}

prune_dir "$VOLUME_DIR" CURRENT.dump.zst
[ "$ROOT_SKIPPED" = "0" ] && prune_dir "$ROOT_DIR" PREVIOUS.dump.zst

# --- step 6: report --------------------------------------------------------

VOL_BYTES=$(stat -c '%s' "$VOL_FINAL")
if [ -n "$ROOT_FINAL" ] && [ -f "$ROOT_FINAL" ]; then
    ROOT_BYTES=$(stat -c '%s' "$ROOT_FINAL")
else
    ROOT_BYTES="n/a"
fi
log "=== leadpeek_backup DONE ==="
log "volume_dump=$VOL_FINAL bytes=$VOL_BYTES"
log "root_dump=${ROOT_FINAL:-(skipped)} bytes=$ROOT_BYTES skipped=$ROOT_SKIPPED"

bash "$ALERT" backup-ok \
    "$(printf 'Backup OK at %s\nVolume primary: %s (%s bytes)\nRoot copy:     %s (%s bytes)%s' \
        "$(ts)" "$VOL_FINAL" "$VOL_BYTES" "${ROOT_FINAL:-(skipped)}" "$ROOT_BYTES" \
        "$([ "$ROOT_SKIPPED" = "1" ] && echo $'\n\n(Root copy skipped or failed; see backup-degraded-no-root alert.)' || true)")" || true

exit 0
