# Storage architecture (Hetzner)

## Disks

The prod box has two physically separate disks. Files on one don't help
the other; you can't pool free space.

| Mount | Device | Size | Used now | Purpose |
|---|---|---:|---:|---|
| `/` | `/dev/sda1` | 75 GB | ~22 GB | OS, Docker images + overlays, WAL archive (post-migration), runtime logs |
| `/mnt/volume-hel1-1` | `/dev/sdb` | 148 GB | ~125 GB | Live PG data, base backups |

## What lives where

After the WAL archive migration (`scripts/migrate_wal_archive_to_root.sh`):

**On the volume `/mnt/volume-hel1-1`:**
- `pgsql-prod/main/` — live prod database (~48 GB, slow growth)
- `pgsql-staging/` — staging tablespace (~30 GB; refreshed nightly from prod)
- `backups/base-*` — daily base backups (~23 GB each, last 2 retained = ~46 GB steady state)
- `wal-archive` — symlink to `/var/lib/postgresql/wal-archive` (no real storage)

**On root `/`:**
- `/var/lib/postgresql/wal-archive` — actual WAL archive directory (~25-50 GB during heavy-write days)
- Docker images and container overlays (~15-20 GB)
- OS, logs, scripts (small)

## Why WAL archive on root, not on volume

The WAL archive is sequential append-only and tolerates being on a
different disk than the live database. Putting it on root uses
otherwise-idle space and frees the volume for the things that genuinely
need to be near the live tablespaces (prod, staging, base backups).

PostgreSQL still writes via the same path (`/mnt/volume-hel1-1/wal-archive/`)
because that path is now a symlink. `archive_command` in `postgresql.conf`
is unchanged.

## Steady-state math

The 148 GB volume is sized to hold:

| Component | Steady-state size |
|---|---:|
| `pgsql-prod` | ~48 GB (slow growth, ~1 GB/month) |
| `pgsql-staging` | ~30 GB (depends on how prod grows; refreshed nightly) |
| `backups/` (2 base backups retained) | ~46 GB |
| `wal-archive` (symlink) | 0 GB |
| Headroom for staging snapshot intermediate state | ~16 GB peak |
| **Total** | **~140 GB** with ~8 GB margin |

If the prod DB grows past ~55 GB or the staging tablespace past ~35 GB,
the margin disappears and the volume needs to be expanded (Hetzner UI,
30 seconds, ~€10/month per 100 GB).

The root disk is sized to hold:

| Component | Steady-state size |
|---|---:|
| OS + base packages | ~5 GB |
| Docker images and overlays | ~15-20 GB (with daily prune) |
| `/var/lib/postgresql/wal-archive` | ~25-50 GB (2-day retention; spiky during migration days) |
| Logs in `/var/log` | ~1 GB |
| **Total** | **~45-75 GB** |

Without the daily docker prune, root drifts toward full (cron log showed
11 GB → 7 GB → 1 GB free over May 2-4). The prune cron is essential.

## Crons that affect storage

| When | What | Why |
|---|---|---|
| 00:30 UTC | `take_base_backup.sh` (volume) | Daily base backup, auto-prunes to last 2 |
| 02:30 UTC | `refresh_staging_snapshot.sh` (volume) | Staging refresh — needs ~16 GB peak intermediate space; **safety check is currently broken (checks root, should check volume)** — see ops to-do |
| 03:00 UTC | WAL retention `find -mtime +2 -delete` (root post-migration) | 2-day PITR window |
| 04:30 UTC | `docker system prune -af` (root) | **NEW after 2026-05-05 outage** — keeps Docker overlays from filling root |
| Sunday 04:00 | `docker system prune -af && docker buildx prune -af` (root) | Weekly hard prune; can be removed once daily prune is in place |

## What to do when disk fills again

1. `df -h` — which mount is full?
2. If volume: `du -sh /mnt/volume-hel1-1/*` and check whether base backups, WAL retention, or staging tablespace bloated unexpectedly.
3. If root: `du -sh /var/lib/docker /var/lib/postgresql/wal-archive /var/log` — usually Docker.
4. Quick wins: `DROP DATABASE leadpeek_staging_next` if it exists (orphaned from a failed staging refresh); `docker system prune -af`.

## Unwind: how to reverse the WAL archive migration

If the migration script fails verification or you need to roll back for any
reason, the procedure depends on which phase the script completed:

**Before Phase 6 (script aborted, `OLD.bak` still exists):**

```bash
# Restore the original directory
rm /mnt/volume-hel1-1/wal-archive       # remove the symlink
mv /mnt/volume-hel1-1/wal-archive.bak /mnt/volume-hel1-1/wal-archive
# Optional: remove the destination if you're abandoning the migration
rm -rf /var/lib/postgresql/wal-archive
```

PG continues writing to the original path (now restored to a real directory)
on its next archive cycle. No restart needed.

**After Phase 6 (script completed, `OLD.bak` deleted):**

The migration is complete. To roll back:

```bash
# Move WAL archive back to the volume
mkdir /mnt/volume-hel1-1/wal-archive.tmp
chown postgres:postgres /mnt/volume-hel1-1/wal-archive.tmp
chmod 700 /mnt/volume-hel1-1/wal-archive.tmp
rsync -aW /var/lib/postgresql/wal-archive/ /mnt/volume-hel1-1/wal-archive.tmp/
rm /mnt/volume-hel1-1/wal-archive  # remove the symlink
mv /mnt/volume-hel1-1/wal-archive.tmp /mnt/volume-hel1-1/wal-archive
rm -rf /var/lib/postgresql/wal-archive
```

This requires ~25 GB free on the volume — which only exists post-migration
if nothing else has filled it. Practically: if you need to unwind after
Phase 6, you may need to free space first (drop staging snapshot's orphan,
reduce backup retention, etc.).

**If WAL archives appear corrupted post-migration (very unlikely; Phase 5
guards against this):** the safety net is the daily base backup at
`/mnt/volume-hel1-1/backups/base-latest`. PITR can restore from base
backup + remaining WAL files in `pg_wal` (not yet archived).

## Symlink security note

The new layout has `/mnt/volume-hel1-1/wal-archive` as a symlink to
`/var/lib/postgresql/wal-archive`. The parent `/mnt/volume-hel1-1/` is
root-owned mode 755, so non-root users cannot replace the symlink with
one pointing elsewhere. No symlink-swap-attack surface on this box.

## History

- **2026-05-04**: First disk-full outage (4.5h). Root cause: prod data on root disk, no WAL retention. Fix: moved prod data to volume, expanded volume 98 → 150 GB, added 2-day WAL retention cron + daily base backup cron with auto-prune.
- **2026-05-05**: Second disk-full outage. Root cause: volume undersized for the steady-state sum (the 2026-05-04 fix didn't account for base backup steady-state of 2× one backup, staging tablespace, or staging snapshot intermediate state). Fix: dropped orphan `leadpeek_staging_next` (-9.5 GB), moved WAL archive to root disk via this PR (-25 GB on volume), added daily docker prune cron.
