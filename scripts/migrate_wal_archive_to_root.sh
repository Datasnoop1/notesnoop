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
# write a file during the swap window; phase 5 verifies no files were
# lost before deleting the .bak directory.
#
# Idempotent: if the source is already a symlink, the script exits early.

set -euo pipefail

OLD=/mnt/volume-hel1-1/wal-archive
NEW=/var/lib/postgresql/wal-archive
DRY_RUN="${DRY_RUN:-0}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
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
  run "mkdir -p '$NEW'"
  run "chown postgres:postgres '$NEW'"
  run "chmod 700 '$NEW'"
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

# 4. Phase 1 — initial rsync (large copy, source remains intact)
log "Phase 1: rsync $OLD -> $NEW (initial copy)..."
run "rsync -a --info=progress2 '$OLD/' '$NEW/'"

# 5. Phase 2 — catch-up rsync for any files PG wrote during phase 1
log "Phase 2: catch-up rsync..."
run "rsync -a --delete '$OLD/' '$NEW/'"

# 6. Phase 3 — atomic swap
# PG may be mid-write of an archive_command at the swap moment. Worst case:
# one file is created in OLD.bak and not in NEW; phase 5 catches that.
log "Phase 3: swapping $OLD for symlink to $NEW..."
run "mv '$OLD' '${OLD}.bak'"
run "ln -s '$NEW' '$OLD'"

# 7. Phase 4 — verify a new archive lands in the new location
log "Phase 4: waiting up to 90s for next WAL archive operation..."
if [ "$DRY_RUN" != "1" ]; then
  PRE_COUNT=$(ls -1 "$NEW" 2>/dev/null | wc -l)
  for i in 1 2 3 4 5 6 7 8 9; do
    sleep 10
    POST_COUNT=$(ls -1 "$NEW" 2>/dev/null | wc -l)
    if [ "$POST_COUNT" -gt "$PRE_COUNT" ]; then
      log "OK: archive count grew from $PRE_COUNT to $POST_COUNT."
      break
    fi
    log "  waiting... (${i}0s elapsed; archive count still $POST_COUNT)"
  done
fi

# 8. Phase 5 — confirm no files were lost during swap window
log "Phase 5: comparing $OLD.bak and $NEW..."
if [ "$DRY_RUN" != "1" ]; then
  EXTRA=$(comm -23 <(ls "${OLD}.bak" | sort) <(ls "$NEW" | sort) || true)
  if [ -n "$EXTRA" ]; then
    log "FAIL: files exist in ${OLD}.bak but not in $NEW:"
    printf '  %s\n' $EXTRA
    log "Investigate manually before removing ${OLD}.bak."
    exit 1
  fi
  log "OK: ${OLD}.bak fully covered by $NEW; safe to delete."
fi

# 9. Phase 6 — delete the .bak directory
log "Phase 6: removing ${OLD}.bak..."
run "rm -rf '${OLD}.bak'"

log "DONE."
log ""
log "Post-migration manual steps (operator does these via crontab -e):"
log "  1. Update WAL retention cron to point at the new path:"
log "       0 3 * * * find /var/lib/postgresql/wal-archive/ -type f -mtime +2 -delete >> /var/log/wal-cleanup.log 2>&1"
log "  2. Add daily docker prune (prevents root from drifting toward full):"
log "       30 4 * * * docker system prune -af --volumes=false >> /var/log/docker_prune_daily.log 2>&1"
