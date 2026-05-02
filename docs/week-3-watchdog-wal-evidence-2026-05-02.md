# Week-3 cancellation watchdog + WAL archiving evidence - 2026-05-02

Branch: `feat/week-3-watchdog-wal-archiving`

## Scope

- Converted the Week-3 phase-gates placeholder into the required five-section format.
- Added a search-only disconnect watchdog for the psycopg2 bridge period.
- Added pool-return safety so non-idle or aborted connections are discarded before reuse.
- Added WAL archive and base-backup host scripts for the production Gate Y tail step.

## Cancellation watchdog

- Watchdog is limited to read-only search GET endpoints:
  - `/api/companies/search`
  - `/api/companies/semantic-search`
  - `/api/people/search`
  - `/api/search/suggest`
- Each cancellable request gets a UUID request tag in `application_name`:
  `datasnoop:rid=<request-id>`.
- `pg_cancel_backend()` runs from a dedicated cancel pool and only cancels when both
  the captured PID and `application_name` still match the same request.
- `put_connection()` resets `application_name` to `datasnoop` before returning
  an idle connection to the pool.
- `put_connection()` discards any connection whose transaction status is not idle,
  covering the r25 poisoned-connection case after `QueryCanceled`.
- Main-pool and cancel-pool initialization are guarded by locks so concurrent
  first requests cannot create duplicate pool instances.

## WAL and base-backup scripts

- `scripts/configure_wal_archiving.sh` supports read-only `--check` and mutating
  `--apply` modes.
- The archive command copies rotated WAL files into `DS_WAL_ARCHIVE_DIR`.
- The script forces a WAL switch after apply and verifies that the switched file
  appears in the archive directory.
- `scripts/take_base_backup.sh` writes a local gzip-compressed tar-format
  base backup under
  `DS_BACKUP_DIR/base-<timestamp>`, keeps a `base-latest` symlink, and verifies
  `backup_manifest` presence.

## Local validation

- `python -m pytest backend/tests/test_cancel_watchdog.py backend/tests/test_db_pool_safety.py -q`
  - Result: `7 passed`.
  - Includes a Starlette `run_in_threadpool` regression proving the
    request cancel context reaches the sync threadpool used by FastAPI
    for sync route handlers.
- Shell syntax checked on the production host's Bash by streaming the new scripts
  over SSH without writing them to disk:
  - `scripts/configure_wal_archiving.sh`: `bash -n` exit code 0.
  - `scripts/take_base_backup.sh`: `bash -n` exit code 0.

## Read-only production audit

- Host: `ubuntu-4gb-hel1-1`.
- Server checkout at audit time: `docs/architecture-r25` commit `41e0559`
  (before this Week-3 branch lands).
- Volume paths present in `/opt/leadpeek/.env.production`:
  - `DS_VOLUME_ROOT=/mnt/volume-hel1-1`
  - `DS_STAGING_DATA_DIR=/mnt/volume-hel1-1/pgsql-staging`
  - `DS_WAL_ARCHIVE_DIR=/mnt/volume-hel1-1/wal-archive`
  - `DS_BACKUP_DIR=/mnt/volume-hel1-1/backups`
- Directory ownership/mode:
  - `/mnt/volume-hel1-1/pgsql-staging`: `postgres:postgres`, mode `700`.
  - `/mnt/volume-hel1-1/wal-archive`: `postgres:postgres`.
  - `/mnt/volume-hel1-1/backups`: currently `root:root`; the base-backup script
    fixes this to `postgres:postgres`, mode `700` during Gate Y.
- Disk:
  - root filesystem: 75G total, 9.6G free.
  - attached volume: 98G total, 66G free.
- PostgreSQL:
  - version: `16.13`.
  - config file: `/etc/postgresql/16/main/postgresql.conf`.
  - data directory: `/var/lib/postgresql/16/main`.
  - `wal_level=replica`.
  - `max_wal_senders=10`.
  - `archive_mode=off`.
  - `archive_command=(disabled)`.

## Spec gap callout

The Week-3 instruction says WAL archiving needs a Postgres reload. The live
audit shows `archive_mode=off`; PostgreSQL requires a restart to turn
`archive_mode` on from `off`. The script detects this and only restarts when
called with `--restart-if-required`. This needs a deep-dive revision callout;
the implementation does not silently treat reload as sufficient.

## Staging validation

- Server staging code checkout: commit `b6c246a`.
- Rebuilt and force-recreated `backend-staging` with
  `docker compose -f docker-compose.staging.yml -p leadpeek-staging up -d --build --force-recreate backend-staging`.
- `backend-staging` health: `healthy`.
- `/api/health`: `{"status":"ok","service":"datasnoop-api"}`.
- Controlled cancellation smoke inside `backend-staging`:
  - `watchdog_candidate=true` for `GET /api/companies/search`.
  - Search-tagged connection captured a Postgres PID.
  - Dedicated cancel pool returned `cancelled=true` using the PID +
    `application_name` guard.
  - Worker raised `QueryCanceled`, then rollback returned `ok`.
  - Follow-up pooled query returned `SELECT 1 AS ok`, proving pool reuse
    after cancellation.
- External unauthenticated `/api/companies/search` returned `401`, expected
  under `STAGING_MODE=true` admin gating; not treated as a watchdog failure.

## Gate Y production tail

Complete. The operator approved Codex to run the Gate Y production tail on
2026-05-02. The production backend was rebuilt and force-recreated from the
feature branch, WAL archiving was enabled with the required PostgreSQL restart,
and the first compressed base backup completed successfully.

The production command was:

```bash
cd /opt/leadpeek
git fetch origin feat/week-3-watchdog-wal-archiving
git switch --detach origin/feat/week-3-watchdog-wal-archiving
docker compose up -d --build --force-recreate backend
sudo bash scripts/configure_wal_archiving.sh --apply --restart-if-required
sudo bash scripts/take_base_backup.sh
docker compose ps backend
```

The first `git pull --ff-only` attempt stopped before any production mutation
because the server's local feature branch had diverged from the force-pushed
remote branch. The rerun used a detached checkout of
`origin/feat/week-3-watchdog-wal-archiving`, avoiding a local branch reset.

WAL archiving output:

- Deployed production code ref: `7b7c00c`.
- `settings_before`: `archive_mode=off`, `archive_command=(disabled)`,
  `wal_level=replica`.
- `writing_wal_archive_settings`.
- `reloading_postgres_config`.
- `postgres_restart_required=true`.
- `restarting_postgresql`.
- `forced_wal_switch=0000000100000045000000A0`.
- `archive_probe=ok file=0000000100000045000000A0`.
- `settings_after`: `archive_mode=on;pending_restart=false`,
  `wal_level=replica;pending_restart=false`.

Base backup output:

- The original plain-format backup attempt failed because `pg_basebackup`
  tried to write the existing live staging tablespace path,
  `/mnt/volume-hel1-1/pgsql-staging`, which is intentionally non-empty.
  The script was corrected to tar-format backup mode.
- The first raw tar-format run exhausted the 66G free on the attached volume
  at about 97%, because the full-cluster base backup includes both production
  and staging tablespaces. The failed in-progress backup was cleaned up by
  `pg_basebackup`; the script was corrected to gzip-compressed tar format.
- Final compressed backup preflight:
  `preflight data_gb=40 free_gb=66 required_gb=45`.
- Final compressed backup target:
  `/mnt/volume-hel1-1/backups/base-20260502T095716Z`.
- `base_backup_start target=/mnt/volume-hel1-1/backups/base-20260502T095716Z format=tar-gzip`.
- `base_backup_complete target=/mnt/volume-hel1-1/backups/base-20260502T095716Z`.
- `base_backup_size=20G`.
- `backup_manifest=present`.
- `base-latest -> base-20260502T095716Z`.

Final production postconditions:

- `leadpeek-backend-1` is `healthy`.
- WAL archive probe file
  `/mnt/volume-hel1-1/wal-archive/0000000100000045000000A0` exists.
- `archive_mode=on;pending_restart=false`.
- `wal_level=replica;pending_restart=false`.
- Attached volume after the compressed backup: 98G total, 45G available,
  52% used.
