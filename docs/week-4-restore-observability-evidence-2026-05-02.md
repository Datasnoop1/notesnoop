# Week-4 restore drill + observability evidence - 2026-05-02

Branch: `feat/week-4-restore-observability`

## Scope

- Converted the Week-4 phase-gates placeholder into the required five-section
  format.
- Admin-gated the existing Prometheus `/metrics` endpoint.
- Added monthly restore-drill automation to the managed cron block.
- Added SLO recording/alert rules seeded from Week-1d phase timing.

## Restore drill design

`scripts/monthly_restore_drill.sh --run` is safe for root cron and never prints
connection strings or secrets.

The drill verifies:

- Latest base-backup directory exists via `DS_BACKUP_DIR/base-latest`.
- `backup_manifest` parses as JSON.
- Each compressed tar payload in the physical backup passes `gzip -t`.
- A schema-only logical dump restores into a scratch database, then verifies
  expected core relations exist:
  - `company_info`
  - `enterprise`
  - `financial_data`
  - `administrator`

The script records last status in:

- `/opt/leadpeek/scripts/_watchdog_state/restore_drill_last.json`

## Physical restore capacity callout

The Week-3 compressed base backup is valid and compact on disk, but the
manifest reports about 68 GiB of uncompressed payload. The attached volume had
about 45 GiB free after the first compressed backup. A full same-host physical
restore would therefore need more scratch capacity than the current volume has.

Week-4 ships the monthly automated drill as:

1. physical backup payload readability check, and
2. logical schema restore into a scratch DB.

This is a capacity-driven deviation from a full physical replay on the same
host. A future full-physical restore drill should run on a larger scratch
volume or a separate restore host.

## Observability

- `/metrics` now depends on `routers.admin._require_admin`.
- Non-admin callers no longer receive Prometheus metrics.
- Admin-authenticated callers receive Prometheus text with media type
  `text/plain; version=0.0.4`.
- `monitoring/prometheus/datasnoop-slo-rules.yml` defines p95/p99 recording
  rules and the first two warning alerts:
  - `DatasnoopApiTotalP95Slow`
  - `DatasnoopApiDbP95Slow`

## Validation

- `python -m pytest backend/tests/test_metrics_admin_gate.py -q`
  - Result: `2 passed`.
- `python -m py_compile backend/main.py`
  - Result: passed.
- Shell syntax checked on the production host's Bash by streaming scripts over
  SSH without writing them to disk:
  - `scripts/monthly_restore_drill.sh`: `bash -n` exit code 0.
  - `scripts/install_crons.sh`: `bash -n` exit code 0.
- `scripts/monthly_restore_drill.sh --check --skip-gzip-test` streamed on the
  production host:
  - Result: exit code 0.
  - Backup: `/mnt/volume-hel1-1/backups/base-20260502T095716Z`.
  - Compressed size: `20G`.
  - Manifest uncompressed size: `68G`.
  - Scratch free on default work dir: `12G`.
  - Physical same-host restore capacity: insufficient.
  - Manifest parse: ok.

## Staging validation

- Staging backend rebuilt and force-recreated from branch commit `f9f4948`.
- `backend-staging` health: `healthy`.
- `/api/health`: `{"status":"ok","service":"datasnoop-api"}`.
- Anonymous `/metrics`: `401`.
- Deployed app admin-dependency probe:
  - `/metrics` route depends on `routers.admin._require_admin`: `True`.
  - `prometheus_metrics()` returns media type
    `text/plain; version=0.0.4`.
  - Response body contains
    `datasnoop_request_phase_duration_ms_bucket`: `True`.

## Gate Y production tail

Complete under operator approval on 2026-05-02.

Production command shape:

```bash
cd /opt/leadpeek
git fetch origin feat/week-4-restore-observability
git switch --detach origin/feat/week-4-restore-observability
docker compose up -d --build --force-recreate backend
sudo bash scripts/monthly_restore_drill.sh --run
sudo bash scripts/install_crons.sh
```

Production output:

- Deployed production code ref for the first run: `f9f4948`.
- `leadpeek-backend-1` final health: `healthy`.
- Anonymous `/metrics`: `401`.
- Admin-dependency probe in the production container:
  - `/metrics` route depends on `routers.admin._require_admin`: `True`.
  - `prometheus_metrics()` returns media type
    `text/plain; version=0.0.4`.
  - Response body contains
    `datasnoop_request_phase_duration_ms_bucket`: `True`.
- Restore drill full run:
  - Backup: `/mnt/volume-hel1-1/backups/base-20260502T095716Z`.
  - `compressed_gb=20`.
  - `manifest_uncompressed_gb=68`.
  - `scratch_free_gb=12`.
  - `physical_restore_capacity=insufficient`.
  - `backup_manifest=parse_ok`.
  - `gzip_test_ok file=1183320.tar.gz`.
  - `gzip_test_ok file=base.tar.gz`.
  - `gzip_test_ok file=pg_wal.tar.gz`.
  - Scratch DB: `leadpeek_restore_drill_20260502T113442Z`.
  - `logical_schema_dump_start`.
  - `logical_schema_restore_start`.
  - `logical_restore_smoke=ok`.
  - `restore_drill_complete`.
- Managed cron installed:
  `20 2 1-7 * SUN bash /opt/leadpeek/scripts/monthly_restore_drill.sh --run >> /opt/leadpeek/scripts/_watchdog_state/restore_drill.log 2>&1`.

## Gate Y cleanup fix

The first successful full restore-drill run exposed a cleanup bug: the scratch
restore DB remained because the lock wrapper executed `main` in a subshell, so
the `EXIT` trap did not see `RESTORE_DB`. This branch fixes the wrapper to run
`main` in the current shell with a file-descriptor lock.

Production cleanup and verification:

- Dropped the leftover scratch DB.
- Reran the patched script streamed over SSH with
  `--run --skip-gzip-test` to avoid re-reading 20G immediately after the full
  gzip verification.
- Rerun result:
  - `backup_manifest=parse_ok`.
  - `gzip_test=skipped`.
  - Scratch DB: `leadpeek_restore_drill_20260502T113608Z`.
  - `logical_restore_smoke=ok`.
  - `restore_drill_complete`.
  - Remaining `leadpeek_restore_drill_%` databases: `0`.
- Synced the production checkout to fixed branch ref `d8e2e41`; backend
  remained healthy and remaining `leadpeek_restore_drill_%` databases stayed
  at `0`.
