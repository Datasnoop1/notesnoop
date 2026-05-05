#!/usr/bin/env bash
# One-time migration: move PG WAL archive from /mnt/volume-hel1-1/wal-archive
# (the data volume, currently bumping against capacity) to
# /var/lib/postgresql/wal-archive (the root filesystem, which has free space).
#
# Why: the 148 GB data volume is undersized for the steady-state sum of
# (prod DB + staging tablespace + base backups + WAL archive). Moving the
# WAL archive off the volume frees ~25 GB on the volume permanently and
# uses currently-idle space on the root disk. PG keeps writing to the
# original path (now a symlink) so postgresql.conf does not change.
#
# Strategy: rsync source -> destination twice (initial + catch-up), then
# swap the source directory for a symlink. PG's archive_command may
# write a file during the swap window (PG handles this gracefully — it
# logs a WARNING and retries the same WAL segment on next checkpoint;
# no data loss). Phase 5 verifies content equality (not just filename
# presence) before deleting the .bak directory.
#
# Idempotent: if the source is already a symlink, the script exits early.
# If the script crashes between Phase 3 and Phase 6, $OLD.bak is leaked;
# inspect manually and `rm -rf` once you've verified $NEW has all files.
#
# Operator-side timing: do NOT run during the 03:00 UTC WAL retention
# window. Any other hour is fine.

set -euo pipefail

OLD=/mnt/volume-hel1-1/wal-archive
NEW=/var/lib/postgresql/wal-archive
DRY_RUN="${DRY_RUN:-0}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[dry-run]'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# 1. Idempotence guard
if [ -L "$OLD" ]; then
  log "Already migrated: $OLD is a symlink to $(readlink "$OLD")."
  exit 0
fi
if [ ! -d "$OLD" ]; then
  log "Source $OLD does not exist; nothing to migrate."
  exit 0
fi

# 2. Preflight: ensure NEW exists with right ownership
if [ ! -d "$NEW" ]; then
  log "Creating destination $NEW..."
  run mkdir -p "$NEW"
  run chown postgres:postgres "$NEW"
  run chmod 700 "$NEW"
fi

# 3. Preflight: ensure root has enough free space
SRC_KB=$(du -sk "$OLD" | awk '{print $1}')
ROOT_FREE_KB=$(df -k --output=avail / | tail -1)
SRC_GB=$((SRC_KB / 1024 / 1024))
ROOT_FREE_GB=$((ROOT_FREE_KB / 1024 / 1024))
NEEDED_GB=$((SRC_GB + 5))  # +5 GB headroom for new WAL during migration
log "WAL archive size: ${SRC_GB} GB; root free: ${ROOT_FREE_GB} GB; needed: ${NEEDED_GB} GB."
if [ "$ROOT_FREE_GB" -lt "$NEEDED_GB" ]; then
  log "FAIL: not enough free space on root."
  exit 1
fi

# 4. Phase 1 — initial rsync. -W (whole-file) skips the rolling-checksum
# delta-transfer; pointless across filesystems for append-only binaries.
log "Phase 1: rsync $OLD -> $NEW (initial copy)..."
run rsync -aW --info=progress2 "$OLD/" "$NEW/"

# 5. Phase 2 — catch-up rsync. -c (checksum) ensures we re-transfer any
# file whose content changed even if size+mtime look identical (covers the
# rare case where archive_command finished writing AFTER Phase 1 stat'd
# the file but didn't update mtime visibly). --delete keeps NEW in sync
# with OLD if retention pruned a file (safe — pruned files are >2 days
# old and not needed).
log "Phase 2: catch-up rsync (checksum verification)..."
run rsync -aWc --delete "$OLD/" "$NEW/"

# 6. Phase 3 — atomic swap. PG's archive_command may fire during the
# ~100ms window between mv and ln -s. Expected behaviour: the cp fails,
# PG logs ONE WARNING ("archiver process was terminated by signal" or
# similar), and PG retries the same WAL segment on the next checkpoint —
# no data loss because WAL stays in pg_wal until archived. Do not panic
# if you see a single archive_command stderr in the PG log within the
# minute around this script running.
log "Phase 3: swapping $OLD for symlink to $NEW..."
log "  (a single PG archive_command WARNING in the next minute is expected and benign)"
run mv "$OLD" "${OLD}.bak"
run ln -s "$NEW" "$OLD"

# 7. Phase 4 — force PG to rotate WAL so a new archive lands deterministically.
# Without this the script could exit Phase 4 having seen no archive activity
# (idle DB), making "verified" indistinguishable from "no traffic". With
# pg_switch_wal we know exactly what to expect.
log "Phase 4: forcing WAL rotation via pg_switch_wal() and verifying archive..."
if [ "$DRY_RUN" != "1" ]; then
  PRE_COUNT=$(ls -1 "$NEW" 2>/dev/null | wc -l)
  sudo -u postgres psql -At -d postgres -c "SELECT pg_switch_wal()" >/dev/null 2>&1 || \
    log "  WARN: pg_switch_wal failed (PG may be unreachable); falling back to passive wait"
  for i in 1 2 3 4 5 6; do
    sleep 5
    POST_COUNT=$(ls -1 "$NEW" 2>/dev/null | wc -l)
    if [ "$POST_COUNT" -gt "$PRE_COUNT" ]; then
      log "OK: archive count grew from $PRE_COUNT to $POST_COUNT — symlink is wired up correctly."
      break
    fi
    log "  waiting... (${i}*5s elapsed; archive count still $POST_COUNT)"
  done
  if [ "$POST_COUNT" -eq "$PRE_COUNT" ]; then
    log "  WARN: no new archive landed within 30s. Phase 5 (content compare) is the real verification gate; proceeding."
  fi
fi

# 8. Phase 5 — verify $OLD.bak is fully covered by $NEW (presence + content).
# rsync -an --checksum --delete in dry-run mode reports every file that
# WOULD need to be transferred or deleted to make NEW match OLD.bak. If
# the dry-run output names any files, the migration is incomplete: either
# a file is in .bak but not in NEW (data loss risk if we proceed), or a
# file's content differs (corruption risk). We abort and the operator
# investigates manually.
log "Phase 5: content-checksum compare $OLD.bak <-> $NEW..."
if [ "$DRY_RUN" != "1" ]; then
  DIFF=$(rsync -an --checksum --delete --itemize-changes "${OLD}.bak/" "$NEW/" | grep -v '^$' | grep -v '^cd' || true)
  if [ -n "$DIFF" ]; then
    log "FAIL: $OLD.bak and $NEW differ. Will NOT delete .bak. Inspect:"
    printf '  %s\n' "$DIFF"
    log ""
    log "To unwind: rm $OLD && mv $OLD.bak $OLD"
    exit 1
  fi
  log "OK: $OLD.bak and $NEW are byte-identical — safe to delete .bak."
fi

# 9. Phase 6 — delete the .bak directory
log "Phase 6: removing ${OLD}.bak..."
run rm -rf "${OLD}.bak"

log "DONE."
log ""
log "Post-migration manual steps (operator does these via crontab -e):"
log "  1. Update WAL retention cron path for clarity (find follows symlinks,"
log "     so the old path also works, but the explicit new path is cleaner):"
log "       0 3 * * * find /var/lib/postgresql/wal-archive/ -type f -mtime +2 -delete >> /var/log/wal-cleanup.log 2>&1"
log "  2. Add daily docker prune (prevents root from drifting toward full):"
log "       30 4 * * * docker system prune -af --volumes=false >> /var/log/docker_prune_daily.log 2>&1"
log ""
log "If anything looks wrong post-migration, unwind procedure is in"
log "docs/storage-architecture.md (search 'unwind')."
