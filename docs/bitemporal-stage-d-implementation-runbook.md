# Bitemporal Stage D Implementation Runbook

PR status: implementation only. Do not run this migration on staging or prod until Step 3 / Step 5 approval gates are explicitly opened.

This PR implements the approved Stage D design in `docs/bitemporal-stage-d-design-proposal.md`:

- `migrations/2026-05-05_bitemporal_valid_from_stage_d.sql`
- `migrations/2026-05-05_bitemporal_valid_from_stage_d_rollback.sql`
- `ops/stage_d_cleanup_day7.sql`
- `ops/_apply_stage_d_cleanup.sh`

It does not touch writer code and it does not modify `src/schema.sql`.
Per the Step 2 operator scope, `src/schema.sql` remains a pre-Stage-D
baseline file in this PR; fresh installs must apply migrations through
`scripts/migrate.py` until a later baseline refresh is explicitly approved.

## Pre-Flight

Run from `/opt/leadpeek` on the server, after the eventual master merge has been cherry-picked onto `feat/industry-peers-browse`:

```bash
cd /opt/leadpeek
git branch --show-current
git status --short --branch
python3 scripts/migrate.py status --target=prod
python3 scripts/migrate.py dry-run --target=prod
```

Expected branch: `feat/industry-peers-browse`. Do not checkout `master` on the server.

Expected dry-run: exactly one pending migration, and it must be
`2026-05-05_bitemporal_valid_from_stage_d.sql`. If any other migration is
pending, stop and resolve that before opening the Stage D apply window.

Check the deployed Postgres version:

```sql
SELECT current_setting('server_version_num')::int >= 120000 AS supports_fast_set_not_null;
```

Expected result: `true`.

Preflight residual count and blocked-row check:

```sql
CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_d_try_date(raw TEXT)
RETURNS DATE
LANGUAGE plpgsql
AS $$
DECLARE
    text_value TEXT := btrim(raw);
    parsed DATE;
BEGIN
    IF text_value IS NULL OR text_value = '' THEN
        RETURN NULL;
    END IF;
    IF text_value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        BEGIN
            parsed := text_value::date;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        IF to_char(parsed, 'YYYY-MM-DD') = text_value THEN
            IF parsed < DATE '1830-01-01' OR parsed > CURRENT_DATE THEN
                RETURN NULL;
            END IF;
            RETURN parsed;
        END IF;
        RETURN NULL;
    END IF;
    IF text_value ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN
        BEGIN
            parsed := to_date(text_value, 'DD/MM/YYYY');
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        IF to_char(parsed, 'DD/MM/YYYY') = text_value THEN
            IF parsed < DATE '1830-01-01' OR parsed > CURRENT_DATE THEN
                RETURN NULL;
            END IF;
            RETURN parsed;
        END IF;
        RETURN NULL;
    END IF;
    RETURN NULL;
END
$$;

WITH residuals AS (
    SELECT 'administrator' AS table_name, a.enterprise_number, e.start_date, a.source_deposit_date
    FROM administrator a
    LEFT JOIN enterprise e ON e.enterprise_number = a.enterprise_number
    WHERE a.valid_from IS NULL
    UNION ALL
    SELECT 'shareholder', sh.enterprise_number, e.start_date, sh.source_deposit_date
    FROM shareholder sh
    LEFT JOIN enterprise e ON e.enterprise_number = sh.enterprise_number
    WHERE sh.valid_from IS NULL
    UNION ALL
    SELECT 'participating_interest', pi.enterprise_number, e.start_date, pi.source_deposit_date
    FROM participating_interest pi
    LEFT JOIN enterprise e ON e.enterprise_number = pi.enterprise_number
    WHERE pi.valid_from IS NULL
    UNION ALL
    SELECT 'affiliation', af.enterprise_number, e.start_date, af.source_deposit_date
    FROM affiliation af
    LEFT JOIN enterprise e ON e.enterprise_number = af.enterprise_number
    WHERE af.valid_from IS NULL
),
parsed AS (
    SELECT table_name,
           enterprise_number,
           pg_temp._bt_vf_stage_d_try_date(start_date) AS enterprise_start_date,
           source_deposit_date
    FROM residuals
)
SELECT table_name,
       COUNT(*) AS residual_rows,
       COUNT(*) FILTER (WHERE enterprise_start_date IS NULL) AS blocked_missing_or_bad_start,
       COUNT(*) FILTER (
           WHERE enterprise_start_date IS NOT NULL
             AND source_deposit_date IS NOT NULL
             AND enterprise_start_date > source_deposit_date
       ) AS source_date_capped_rows
FROM parsed
GROUP BY table_name
ORDER BY table_name;
```

Affiliation has two additional approved fallback arms after
`fallback_enterprise_start`: `fallback_filing_deposit` from
`financial_data.deposit_date` via `(via_enterprise_number, via_deposit_key)`,
then `fallback_unknown_start` from `recorded_from::date`. To preview those:

```sql
WITH affiliation_residuals AS (
    SELECT af.person_name,
           af.enterprise_number,
           af.via_enterprise_number,
           af.via_deposit_key,
           pg_temp._bt_vf_stage_d_try_date(e.start_date) AS enterprise_start_date,
           fd.deposit_date AS filing_deposit_date,
           af.recorded_from::date AS recorded_from_date
    FROM affiliation af
    LEFT JOIN enterprise e ON e.enterprise_number = af.enterprise_number
    LEFT JOIN LATERAL (
        SELECT MIN(pg_temp._bt_vf_stage_d_try_date(fd.deposit_date::text)) AS deposit_date
        FROM financial_data fd
        WHERE fd.enterprise_number = af.via_enterprise_number
          AND fd.deposit_key = af.via_deposit_key
          AND pg_temp._bt_vf_stage_d_try_date(fd.deposit_date::text) IS NOT NULL
    ) fd ON true
    WHERE af.valid_from IS NULL
)
SELECT COUNT(*) FILTER (WHERE enterprise_start_date IS NOT NULL) AS enterprise_start_rows,
       COUNT(*) FILTER (
           WHERE enterprise_start_date IS NULL
             AND filing_deposit_date IS NOT NULL
       ) AS filing_deposit_rows,
       COUNT(*) FILTER (
           WHERE enterprise_start_date IS NULL
             AND filing_deposit_date IS NULL
             AND recorded_from_date BETWEEN DATE '1830-01-01' AND CURRENT_DATE
       ) AS unknown_start_rows,
       COUNT(*) FILTER (
           WHERE enterprise_start_date IS NULL
             AND filing_deposit_date IS NULL
             AND NOT (recorded_from_date BETWEEN DATE '1830-01-01' AND CURRENT_DATE)
       ) AS blocked_rows
FROM affiliation_residuals;
```

Expected before applying on the current prod-shaped snapshot:
`blocked_missing_or_bad_start = 0` for administrator, shareholder, and
participating interest. For affiliation, expected approved fallback split is
`enterprise_start_rows = 686`, `filing_deposit_rows = 46`,
`unknown_start_rows = 1`, and `blocked_rows = 0`. If any blocked rows appear,
stop and bring the row list back to the operator.

## Pause Writers

Capture the pause start after the pause commands finish:

```bash
export STAGE_D_PAUSE_STARTED_AT="$(date -Iseconds)"
echo "$STAGE_D_PAUSE_STARTED_AT"
```

Pause list:

1. Stop the NBB backload worker:

```bash
docker compose stop nbb-backload-worker
```

2. Pause backend write routes. If no maintenance switch is deployed, stop backend during the migration window:

```bash
docker compose stop backend
```

This blocks both `POST /api/companies/{cbe}/load` and `POST /api/companies/{cbe}/extract-admins`.

3. Disable governance crons and keep a restore copy:

```bash
crontab -l > /tmp/stage_d_crontab.pre_stage_d
crontab -l | sed -E '/backfill_affiliation.py|backfill_nbb_governance.py|retry_failed_governance.py|staatsblad_batch_every_2d.py|nbb_nightly_backload.py|nbb_batch_pipeline.py/s/^/# STAGE_D_PAUSED /' | crontab -
crontab -l | grep STAGE_D_PAUSED || true
```

4. Confirm no long-running governance writer remains:

```bash
pgrep -af 'staatsblad_consumer|staatsblad_consumer_proc|backfill_affiliation|backfill_nbb_governance|retry_failed_governance|nbb_batch_pipeline|nbb_nightly_backload' || true
```

Expected result: no active writer process. If a process appears, stop it and document what was stopped.

5. Explicit outside-repo check:

```bash
test ! -f /opt/leadpeek/staatsblad_consumer_proc.py || pgrep -af staatsblad_consumer || true
```

Expected result: no running Staatsblad consumer process.

Post-pause gate:

```sql
-- Replace timestamp literal with $STAGE_D_PAUSE_STARTED_AT.
SELECT 'administrator' AS table_name, COUNT(*) AS fresh_nulls
FROM administrator
WHERE valid_from IS NULL AND recorded_from >= '<pause_started_at>'::timestamptz
UNION ALL
SELECT 'shareholder', COUNT(*)
FROM shareholder
WHERE valid_from IS NULL AND recorded_from >= '<pause_started_at>'::timestamptz
UNION ALL
SELECT 'participating_interest', COUNT(*)
FROM participating_interest
WHERE valid_from IS NULL AND recorded_from >= '<pause_started_at>'::timestamptz
UNION ALL
SELECT 'affiliation', COUNT(*)
FROM affiliation
WHERE valid_from IS NULL AND recorded_from >= '<pause_started_at>'::timestamptz;
```

Expected result: zero in all four rows.

## Apply

Apply only after the pause and post-pause gate pass:

```bash
cd /opt/leadpeek
bash /opt/leadpeek/_apply_stage_a.sh python3 scripts/migrate.py up --target=prod
```

If the migration aborts on `lock_timeout`, do not retry blind. Check blockers first:

```sql
SELECT pid, usename, application_name, state, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY state, pid;
```

Confirm writers are still paused, remove the blocker, then rerun the same apply command.

## Verify

After counts:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS null_valid_from,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start') AS enterprise_start_rows,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit') AS filing_deposit_rows,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start') AS unknown_start_rows
FROM administrator
UNION ALL
SELECT 'shareholder', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM affiliation;
```

On the current prod-shaped snapshot, the expected affiliation fallback split is
`enterprise_start_rows = 686`, `filing_deposit_rows = 46`, and
`unknown_start_rows = 1`.

Source-date capped rows from the backup snapshots:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) AS backup_rows,
       COUNT(*) FILTER (WHERE source_date_capped) AS source_date_capped_rows
FROM _bt_vf_stage_d_backup_administrator
UNION ALL
SELECT 'shareholder', COUNT(*), COUNT(*) FILTER (WHERE source_date_capped)
FROM _bt_vf_stage_d_backup_shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*), COUNT(*) FILTER (WHERE source_date_capped)
FROM _bt_vf_stage_d_backup_participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*), COUNT(*) FILTER (WHERE source_date_capped)
FROM _bt_vf_stage_d_backup_affiliation;
```

Constraint and column state:

```sql
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('administrator', 'shareholder', 'participating_interest', 'affiliation')
  AND column_name IN ('valid_from', 'valid_to')
ORDER BY table_name, column_name;

SELECT conrelid::regclass AS table_name, conname, convalidated
FROM pg_constraint
WHERE conname IN (
    'administrator_valid_from_not_null',
    'shareholder_valid_from_not_null',
    'participating_interest_valid_from_not_null',
    'affiliation_valid_from_not_null'
)
ORDER BY table_name::text;
```

Spot check fallback rows:

```sql
WITH picked AS (
    SELECT b.enterprise_number, b.deposit_key, b.name, b.role, b.fallback_valid_from
    FROM _bt_vf_stage_d_backup_administrator b
    WHERE b.fallback_valid_from IS NOT NULL
    ORDER BY random()
    LIMIT 10
)
SELECT a.enterprise_number,
       a.deposit_key,
       a.name,
       a.role,
       a.valid_from,
       p.fallback_valid_from AS expected_valid_from,
       a.valid_from_provenance
FROM picked p
JOIN administrator a
  ON a.enterprise_number = p.enterprise_number
 AND a.deposit_key IS NOT DISTINCT FROM p.deposit_key
 AND a.name IS NOT DISTINCT FROM p.name
 AND a.role IS NOT DISTINCT FROM p.role;
```

Expected result: every row has `valid_from = expected_valid_from` and
`valid_from_provenance = 'fallback_enterprise_start'`.

Affiliation fallback split spot check:

```sql
SELECT valid_from_provenance, COUNT(*) AS rows
FROM affiliation
WHERE valid_from_provenance IN (
    'fallback_enterprise_start',
    'fallback_filing_deposit',
    'fallback_unknown_start'
)
GROUP BY valid_from_provenance
ORDER BY valid_from_provenance;
```

## Resume Writers

Resume checklist mirrors the pause list exactly:

1. Restore governance crons:

```bash
crontab /tmp/stage_d_crontab.pre_stage_d
crontab -l | grep STAGE_D_PAUSED && echo "ERROR: paused cron lines remain" || true
```

2. Restart backend write routes:

```bash
docker compose up -d --build backend
docker ps --filter name=backend --format 'table {{.Names}}\t{{.Status}}'
```

3. Restart NBB backload worker:

```bash
docker compose up -d nbb-backload-worker
docker ps --filter name=nbb-backload-worker --format 'table {{.Names}}\t{{.Status}}'
```

4. Confirm no unintended manual governance writer remains:

```bash
pgrep -af 'staatsblad_consumer|staatsblad_consumer_proc|backfill_affiliation|backfill_nbb_governance|retry_failed_governance|nbb_batch_pipeline|nbb_nightly_backload' || true
```

5. Add a calendar entry for the Stage D backup cleanup date: apply day + 7 days.

Do not run cleanup before day +7.

## Day +7 Cleanup

Manual cleanup command, on or after apply day +7 only:

```bash
cd /opt/leadpeek
STAGE_D_APPLY_DATE=YYYY-MM-DD STAGE_D_CLEANUP_CONFIRM=DROP_STAGE_D_BACKUPS_AFTER_DAY7 bash ops/_apply_stage_d_cleanup.sh
```

Replace `YYYY-MM-DD` with the actual Stage D apply date. The helper refuses to
run before apply day +7 and refuses to run without the confirmation token. The
SQL file also requires a psql variable supplied by the helper, so direct
`psql -f ops/stage_d_cleanup_day7.sql` is intentionally blocked.

This drops:

- `_bt_vf_stage_d_backup_administrator`
- `_bt_vf_stage_d_backup_shareholder`
- `_bt_vf_stage_d_backup_participating_interest`
- `_bt_vf_stage_d_backup_affiliation`

The same cleanup window should also remove the doomsday rollback dump recorded
in `MEMORY.md`, for example:

```bash
rm -i /mnt/volume-hel1-1/pgsql-staging/stage_d_pre_apply_snapshot.2026-05-05.dump
```

Keep the file until Stage D apply day +7; it is intentionally not deleted by
the SQL cleanup helper because it is a filesystem artifact, not a database
object.

## Rollback

If verification fails, keep writers paused. Cherry-pick or deploy the commit that contains `migrations/2026-05-05_bitemporal_valid_from_stage_d_rollback.sql`, then apply the rollback file explicitly with the same prod wrapper:

```bash
cd /opt/leadpeek
ops/_psql_prod_file.sh -v ON_ERROR_STOP=1 -f migrations/2026-05-05_bitemporal_valid_from_stage_d_rollback.sql
```

Use `ops/_psql_prod_file.sh` for manual rollback SQL so the production DB URL
is not passed as a command-line argument. The helper reads the same server env
files, writes a temporary `PGPASSFILE`, and invokes `psql` with `PGHOST`,
`PGPORT`, `PGDATABASE`, and `PGUSER`.

The rollback file is self-transactional (`BEGIN` / `COMMIT`) and sets its own
5s lock timeout plus 600s statement timeout because `_rollback.sql` files are
not applied by `scripts/migrate.py`.

After rollback, rerun the after-counts and confirm the NULL-aware views/functions have been restored before resuming writers.

Do not remove the Stage D row from `schema_migrations` and rerun the forward
migration over the same backup tables. If Stage D needs to be applied again
after a rollback, use a new corrective migration or get explicit operator
approval to preserve/rename old backup snapshots first.
