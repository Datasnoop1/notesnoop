# R18 backup operations

Production disaster-recovery + capacity-planning architecture for the
DataSnoop Postgres cluster. Replaces the previous continuous-WAL-archiving
approach that crashed the server on 2026-05-06 by filling the volume with
3,707 stuck WAL segments.

This document covers Phase 2a (backup automation + freshness alerting),
shipped on 2026-05-06. Phase 2b (watchdogs + tier breakers) and Phase 2c
(restore drills, bloat checks, meta-watchdog) follow.

## Architecture in one paragraph

Every 2 days at 02:00 UTC, a systemd timer runs `pg_dump` against the
production cluster and writes a zstd-3 compressed custom-format dump
(`CURRENT.dump.zst`) to the attached volume at
`/mnt/volume-hel1-1/backups/`. The dump is verified end-to-end (zstd
integrity + TOC TABLE DATA count vs live + sample row-count match on
`company_info`). On success it is recompressed at zstd-12 to the root disk
(`PREVIOUS.dump.zst` at `/var/lib/postgresql/backups/`), giving two copies
on separate failure domains. There is NO continuous WAL archiving and NO
streaming replication: worst-case data loss is 4 days (one full backup
cycle plus 24 h of unwritten changes); restore time is 3–5 hours.

## Files

| Path                                                         | Purpose                                       |
| ------------------------------------------------------------ | --------------------------------------------- |
| `scripts/leadpeek_backup.sh`                                 | The backup script itself                      |
| `scripts/leadpeek_watchdog_backupfresh.sh`                   | Hourly freshness check                        |
| `scripts/r18_alert.sh`                                       | SMTP via backend container, tmpfs fallback    |
| `scripts/r18_install.sh`                                     | Idempotent installer (does not enable)        |
| `scripts/r18_install_cron.sh`                                | Adds the cron entries (Gate B step)           |
| `deploy/leadpeek-backup.service`                             | systemd oneshot unit                          |
| `deploy/leadpeek-backup.timer`                               | systemd timer (every 2 days)                  |
| `deploy/leadpeek-backup-failure.service`                     | systemd `OnFailure=` alert unit               |
| `/etc/leadpeek/backup.env`                                   | PG connection params (NOT in git)             |
| `/root/.pgpass`                                              | Password for `backup_user` (NOT in git)       |
| `/mnt/volume-hel1-1/backups/CURRENT.dump.zst`                | Current primary backup, symlink               |
| `/var/lib/postgresql/backups/PREVIOUS.dump.zst`              | Off-volume copy, symlink                      |

## Steady-state operations

### Manually trigger a backup

```bash
# Via systemd (recommended; same code path as the timer)
sudo systemctl start leadpeek-backup.service
sudo journalctl -u leadpeek-backup.service -f

# Direct (e.g. mid-debug, lock-respecting)
sudo bash /opt/leadpeek/scripts/leadpeek_backup.sh
```

### Check backup health

```bash
# Newest backup ages
ls -la /mnt/volume-hel1-1/backups/CURRENT.dump.zst
ls -la /var/lib/postgresql/backups/PREVIOUS.dump.zst

# Timer status
systemctl list-timers leadpeek-backup.timer --no-pager

# Recent backup runs
journalctl -u leadpeek-backup.service --since='7 days ago' --no-pager | tail -100

# Freshness watchdog log
tail -50 /opt/leadpeek/scripts/_watchdog_state/backupfresh.log

# SHA256 verify (volume + root)
cd /mnt/volume-hel1-1/backups && sha256sum -c pgdump-*.dump.zst.sha256
cd /var/lib/postgresql/backups && sha256sum -c pgdump-*.dump.zst.sha256
```

### Restore from CURRENT (volume) or PREVIOUS (root)

The dumps are pg_dump custom format. Always use the v16 binary path: pg_dump 17
writes a format pg_restore 16 cannot read.

```bash
# Pick the dump
DUMP=$(readlink -f /mnt/volume-hel1-1/backups/CURRENT.dump.zst)

# Schema + data restore into a fresh ephemeral DB (use pgvector image because
# our schema includes the vector type for company_embedding)
docker run -d --name pg-restore-test \
  -e POSTGRES_PASSWORD=verify \
  -p 127.0.0.1:5440:5432 \
  pgvector/pgvector:pg16
sleep 10
PGPASSWORD=verify psql -h 127.0.0.1 -p 5440 -U postgres \
  -c "CREATE DATABASE leadpeek_restored"

# IMPORTANT: see the "schema-restore ordering" caveat below. For a clean
# restore you must pre-install the f_unaccent helper; see the workaround.
zstd -dc "$DUMP" | docker exec -i pg-restore-test \
  pg_restore --no-owner --no-privileges -U postgres -d leadpeek_restored
```

## Known issue — schema-restore ordering (search_normalize → f_unaccent)

`pg_dump` does not parse SQL function bodies, so it cannot tell that
`public.search_normalize()` calls `public.f_unaccent()`. The TOC ordering
ends up wrong: things using `search_normalize` are restored before
`f_unaccent` exists, and Postgres's planner-time inlining of SQL functions
fails. This produces ~72 schema-restore errors but does NOT corrupt data.

**Workaround for restore drills**: pre-create the `unaccent` extension and
a stub `f_unaccent` BEFORE running `pg_restore --schema-only`:

```sql
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;
```

This is a real production-restore concern. The proper fix is either:

- A schema-side refactor pushing the dependency into a single function, OR
- Switching the backup format to plain SQL (`pg_dump --format=plain`), which
  emits CREATE statements in a strictly correct order — at the cost of a
  larger dump and no parallel restore, OR
- Generating a custom `pg_restore --use-list` that reorders the TOC.

This is tracked separately and will be addressed in a Phase 2c follow-up.

## Rollback

The whole Phase 2a stack can be turned off without affecting anything else:

```bash
# Disable the timer (stops scheduling new runs immediately)
sudo systemctl disable --now leadpeek-backup.timer

# Stop any in-flight backup
sudo systemctl stop leadpeek-backup.service

# Remove the cron entries
sudo bash -c "crontab -l | sed '/^# R18-MANAGED-BEGIN/,/^# R18-MANAGED-END/d' | crontab -"
```

The most recent dumps remain in place and remain valid. Revert the
configure_wal_archiving + WAL archive setup is NOT required: archive_mode
is now off and that decision predates this rollback.

## Phase 2b — watchdogs and circuit breakers

| Script | Cadence | Action |
| --- | --- | --- |
| `leadpeek_watchdog_disk.sh` | every 5 min | Alert if volume > 150 GB or root > 55 GB |
| `leadpeek_watchdog_pgwal.sh` | every 1 min | Alert > 6 GB; cancel oldest non-`backup_user` xmin holder if > 8 GB sustained 5 min |
| `leadpeek_watchdog_longtx.sh` | every 5 min | Cancel `idle in transaction` > 1 h (exempt `backup_user`); warn on any active tx > 2 h |
| `leadpeek_action_root_disk.sh` | every 10 min | At root > 65 GB: tag `postgres:16` + `pgvector:pg16` with `protect`, `docker system prune -af --filter label!=protect`, `logrotate --force` |
| `leadpeek_breaker_tier1.sh` | every 1 min | Volume > 175 GB sustained 2 min: `docker compose stop enrichment-worker`. Reversible. |
| `leadpeek_breaker_tier2.sh` | every 1 min | Volume > 185 GB sustained 2 min: stop ALL writer services, swap `pg_hba.conf` for `breaker_pg_hba.conf` (only postgres + backup_user can connect), `pg_terminate_backend` non-superuser sessions, AUTOVACUUM remains on. **Manual recovery only.** |

### Resetting a tripped breaker

Tier-1:
```bash
sudo docker compose -f /opt/leadpeek/docker-compose.yml start enrichment-worker
sudo rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier1.tripped
```

Tier-2:
```bash
# 1. Free volume disk first (otherwise it'll trip again immediately)
# 2. Restore pg_hba.conf
sudo cp /etc/postgresql/16/main/pg_hba.conf.normal /etc/postgresql/16/main/pg_hba.conf
sudo systemctl reload postgresql@16-main
# 3. Restart writer services
sudo docker compose -f /opt/leadpeek/docker-compose.yml start \
    backend enrichment-worker staatsblad-bulk-worker nbb-backload-worker
# 4. Clear tripped flag
sudo rm /opt/leadpeek/scripts/_watchdog_state/breaker_tier2.tripped
```

## Phase 2c — drills, bloat, meta

| Script | Cadence | What it does |
| --- | --- | --- |
| `leadpeek_drill_schema.sh` | weekly (Sun 03:00 UTC) | Schema-only restore into ephemeral pgvector/pg16 docker; pre-installs `unaccent` + `f_unaccent` stub; passes if ≥ 95% of live tables restore |
| `leadpeek_drill_partial.sh` | monthly (1st Sun 04:00 UTC) | Schema + data restore for the 5 largest tables; exact row-count match required |
| `leadpeek_drill_full.sh` | quarterly (1st Sun Jan/Apr/Jul/Oct, 02:00 UTC) | Full restore best-effort; gated on free volume > 1.2× pg_database_size + 10 GB |
| `leadpeek_check_bloat.sh` | weekly (Sun 05:00 UTC) | `pgstattuple` on top 20 user tables > 100 MB; alerts if any > 30% dead-tuple |
| `leadpeek_watchdog_meta.sh` | every 30 min | Confirms each watchdog log was written within 2× its expected cadence |

Drills require the `pgvector/pgvector:pg16` docker image to be present on
the host (the root-disk action protects it from `docker system prune`).
Bloat check requires the `pgstattuple` extension to be installed in the
`leadpeek` database — it isn't auto-created (backup_user lacks superuser),
so the operator must run once:

```sql
-- as postgres superuser
\c leadpeek
CREATE EXTENSION pgstattuple;
```

## Why no continuous archiving / no replication

This is an operator-set hard constraint, accepted with full risk
documentation:

- Single Hetzner cloud server, 4 vCPU / 8 GB RAM, attached 200 GB volume
- Zero additional spend permitted for 6 months
- Off-site backup explicitly de-scoped
- Email-only alerting
- 4-day worst-case RPO accepted
- 3–5 hour restore time accepted

The plan was reviewed by 7 LLM jury models over 18 rounds; the converged
verdict in round 18 was APPROVE-WITH-CONCERNS from 6 of 7, including the
two strictest reviewers (Kimi K2.6 and DeepSeek V4 Pro) who had been
REJECTING through 17 prior rounds.
