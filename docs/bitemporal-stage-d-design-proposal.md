# Bitemporal Stage D Design Proposal

Status: design only. Do not merge or implement until all Stage D preconditions are true: Stage C has soaked for 30 days, the earliest implementation date has passed (2026-06-04), the operator explicitly says "go on Stage D", and concurrent writer handling is approved.

## Recommendation

Proceed with option D-a, but only with a preflight gate: fill residual NULL `valid_from` values from parsed `enterprise.start_date` and stamp `valid_from_provenance = 'fallback_enterprise_start'`. Do not drop residual facts. Do not tighten only a subset unless the preflight shows missing or unparseable `enterprise.start_date` rows that the operator chooses to defer.

The migration should not proceed if any row in the four governance tables still has `valid_from IS NULL` after the fallback fill. That means Stage D needs a clear residual-of-residual policy before implementation:

- If `enterprise.start_date` parses to a valid date: set `valid_from = enterprise.start_date::date` and `valid_from_provenance = 'fallback_enterprise_start'`.
- If `enterprise.start_date` is NULL or unparseable: block Stage D by default and publish the row list for operator decision. Do not stamp `fallback_enterprise_start` against a date that did not come from `enterprise.start_date`.
- If the operator wants full four-table NOT NULL even for missing enterprise starts, add a second explicit provenance value in the implementation proposal, for example `fallback_unknown_start`, and choose an agreed sentinel date. That is a separate policy decision and should not be smuggled into `fallback_enterprise_start`.

This keeps the operator's "exhaustive list, let user sort" preference while preserving provenance honesty.

## D1 - Residual NULL Strategy

Current prod residuals as of 2026-05-05:

| Table | NULL `valid_from` |
|---|---:|
| `administrator` | 17,634 |
| `shareholder` | 2,645 |
| `participating_interest` | 4,720 |
| `affiliation` | 733 |

Use D-a as the mainline strategy. The data product should keep these governance facts and mark them as pessimistic lower-quality dates, not delete them. The resulting UI semantics are: "we know this fact exists; the start is no later than the enterprise start fallback and has low-confidence provenance."

D-b is rejected for this rollout because dropping rows loses known governance facts. D-c is the fallback only if the preflight finds material missing `enterprise.start_date` coverage or if the operator rejects a second fallback policy for those rows.

Affiliation needs a writer-side fix before Stage D. The residual affiliation count grew because `scripts/backfill_affiliation.py` calls `store_governance_snapshot(conn, cbe, deposit_key, fiscal_year, filing_json)` without a `deposit_date`; `backend/nbb_governance.py` uses that `deposit_date` as `source_deposit_date` and as the direct `valid_from` for affiliations, shareholders, and participating interests. With no date passed, new affiliation rows can still insert NULL `valid_from`. Stage D must not accept that brittleness. Before applying NOT NULL, ship a separate writer fix that makes every active governance writer provide a non-NULL `valid_from` or skip/log rows it cannot date:

- `scripts/backfill_affiliation.py`: include a best available filing date in `fetch_candidates` (from `financial_data` or `financial_summary`) and pass it to `store_governance_snapshot`; when no filing date exists, use parsed `enterprise.start_date` only with explicit fallback provenance support, or skip and record the attempt as blocked.
- Also review `scripts/backfill_nbb_governance.py`, which currently calls `store_governance_snapshot` without `deposit_date`.
- Keep existing live writer paths (`backend/routers/companies/financials.py`, `scripts/nbb_nightly_backload.py`, `scripts/retry_failed_governance.py`) on the "passes deposit_date" path.
- Patch or pause the outside-repo `/opt/leadpeek/staatsblad_consumer_proc.py` before Stage D if it still writes governance rows.

No live writer code is changed in this design PR.

## D2 - NOT NULL Transition Mechanics

Use the three-step CHECK-then-validate pattern for each of the four governance tables:

```sql
ALTER TABLE administrator
    ADD CONSTRAINT administrator_valid_from_not_null
    CHECK (valid_from IS NOT NULL) NOT VALID;

ALTER TABLE administrator
    VALIDATE CONSTRAINT administrator_valid_from_not_null;

ALTER TABLE administrator
    ALTER COLUMN valid_from SET NOT NULL;
```

Repeat for `shareholder`, `participating_interest`, and `affiliation`.

Rationale:

- The fallback UPDATE must happen first and must reduce NULL `valid_from` to zero.
- `ADD CONSTRAINT ... NOT VALID` takes a short DDL lock.
- `VALIDATE CONSTRAINT` scans the table but avoids holding an exclusive lock for the full scan.
- `ALTER COLUMN valid_from SET NOT NULL` is expected to be metadata-only once PostgreSQL can prove the column is non-null from a validated CHECK constraint.

Deviation to avoid: do not run a direct `ALTER TABLE ... ALTER COLUMN valid_from SET NOT NULL` before a validated CHECK constraint, especially on `administrator`.

## D3 - Read-Path Cleanup Audit

Search method: PowerShell recursive `Select-String`, because `rg.exe` is blocked by local Windows permissions in this workspace.

Frontend:

- `frontend/src`: no `valid_from` or `valid_to` references found. No cleanup needed.

Backend Python:

- `backend/nbb_governance.py:450`: `_insert_bitemporal_unique` uses `valid_to IS NULL` to close prior open current rows. Must stay. `valid_to` remains nullable by design.
- `backend/nbb_governance.py:676`: ownership-edge closure uses `valid_to IS NULL`. Must stay. `ownership_edge` is not one of the four Stage D tables.
- `backend/tests/test_bitemporal_phase_a.py:30` and `backend/tests/test_ownership_graph_sql.py:37-38`: tests assert old NULL-aware view SQL. Stage D implementation should update the governance-table expectations after the view rewrite. Ownership-edge expectations should stay.
- `backend/tests/test_bitemporal_valid_from_stage_a.py` and `backend/tests/test_bitemporal_valid_from_stage_b.py`: historical migration guard tests assert Stage A/B NULL-only UPDATE scoping. Keep them.

`src/schema.sql` governance views and helpers:

- `administrator_current`, `shareholder_current`, `participating_interest_current`, `affiliation_current` around `src/schema.sql:1628-1650` are dangerous because they semantically depend on "NULL valid_from means in force". Rewrite before or in the same Stage D migration:

```sql
WHERE valid_from <= CURRENT_DATE
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL
```

- `admins_as_of`, `shareholders_as_of`, `participating_interests_as_of`, `affiliations_as_of` around `src/schema.sql:1668-1717` are also dangerous. Rewrite:

```sql
WHERE valid_from <= valid_at
  AND (valid_to IS NULL OR valid_to > valid_at)
  AND recorded_from <= known_at
  AND (recorded_to IS NULL OR recorded_to > known_at)
```

- Partial unique indexes around `src/schema.sql:1733-1757` use `valid_to IS NULL`; must stay.
- Ownership graph references around `src/schema.sql:1883`, `1931`, `1963-1983` are not Stage D governance-table references. Keep them unless a separate ownership-edge NOT NULL rollout is proposed.

Migrations:

- `migrations/2026-05-02_bitemporal_phase_a.sql` contains historical NULL-aware views/functions. Do not edit an already-applied migration. Stage D should add a new migration that recreates the views/functions with the non-null `valid_from` predicate.
- `migrations/2026-05-02_ownership_graph.sql` NULL-aware ownership-edge logic stays.
- `migrations/2026-05-04_bitemporal_valid_from_stage_a.sql`, `2026-05-04_bitemporal_valid_from_stage_b.sql`, and `2026-05-04_bitemporal_provenance_columns_backfill.sql` contain historical NULL-only backfill guards. Keep them.

## D4 - Concurrent Writer Pause Strategy

Pause all writers that can touch `administrator`, `shareholder`, `participating_interest`, or `affiliation` during the fallback UPDATE and constraint validation window.

Required pauses:

- `nbb-backload-worker`, because Stage C deadlocked against it.
- `scripts/backfill_affiliation.py` cron (`0 4 * * * ...` in `scripts/install_crons.sh`) and any currently running `docker exec` process for it.
- Any manual `scripts/backfill_nbb_governance.py` or `scripts/retry_failed_governance.py` run.
- Backend write endpoints that call `store_governance_snapshot`, especially on-profile financial load routes. Preferred operational path: temporarily route admin/user traffic away from those write endpoints or pause backend writes if the operator expects profile-triggered loads during the window.
- Outside-repo Staatsblad consumer (`/opt/leadpeek/staatsblad_consumer_proc.py`) if it writes governance rows.

Recommended window: reserve 30 minutes, with a 60-minute rollback ceiling. The fallback UPDATE should be much smaller than Stage C C2, but constraint validation scans the full 1.25M-row administrator table and the other three tables. Stage C C2 completed in 5m07s only after `nbb-backload-worker` was stopped; Stage D should assume a similar or slightly longer maintenance window.

Operational mechanics:

- `docker compose stop nbb-backload-worker` is required; disabling cron is not enough for an already-running long-lived container.
- For cron-launched `backfill_affiliation.py`, disable the cron entry or run a one-off crontab filter before the window, and also confirm no existing process is running.
- Stop any known outside-repo consumer process or service explicitly. If its name is not managed by this repo, the operator should identify it before approving implementation.
- Restart paused services only after the after-counts and spot checks pass.

## D5 - Backout

The CHECK/NOT NULL portion is reversible:

```sql
ALTER TABLE administrator ALTER COLUMN valid_from DROP NOT NULL;
ALTER TABLE administrator DROP CONSTRAINT IF EXISTS administrator_valid_from_not_null;
```

Repeat for the other three tables.

The fallback UPDATE needs row-image snapshots before it runs. Create one backup table per governance table, using a retention name such as `_bt_vf_stage_d_backup_administrator`. Capture identity plus every value needed to reverse or later attribute the fallback:

- primary identity columns
- natural-key columns used by writers
- `source_deposit_date`
- `valid_from`
- `valid_to`
- `valid_from_provenance`
- `valid_to_provenance`
- raw `enterprise.start_date`
- parsed fallback date used by the migration

Example shape:

```sql
CREATE TABLE _bt_vf_stage_d_backup_administrator AS
SELECT a.enterprise_number,
       a.deposit_key,
       a.name,
       a.role,
       a.identifier,
       a.source_deposit_date,
       a.valid_from,
       a.valid_to,
       a.valid_from_provenance,
       a.valid_to_provenance,
       e.start_date AS enterprise_start_date_raw,
       pg_temp._bt_vf_stage_d_try_date(e.start_date) AS fallback_valid_from
FROM administrator a
LEFT JOIN enterprise e ON e.enterprise_number = a.enterprise_number
WHERE a.valid_from IS NULL;
```

Backout of the fallback should restore only rows that still match the fallback fill:

```sql
UPDATE administrator a
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance
FROM _bt_vf_stage_d_backup_administrator b
WHERE a.enterprise_number = b.enterprise_number
  AND a.deposit_key = b.deposit_key
  AND a.name IS NOT DISTINCT FROM b.name
  AND a.role IS NOT DISTINCT FROM b.role
  AND a.valid_from = b.fallback_valid_from
  AND a.valid_from_provenance = 'fallback_enterprise_start';
```

Repeat with table-specific identity for `shareholder`, `participating_interest`, and `affiliation`.

## D6 - Verification SQL

Before counts:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) AS total_rows,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS null_valid_from,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start') AS fallback_rows
FROM administrator
UNION ALL
SELECT 'shareholder', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM affiliation;
```

Preflight for rows that would block D-a:

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
            RETURN parsed;
        END IF;
    END IF;
    RETURN NULL;
END
$$;

WITH residuals AS (
    SELECT 'administrator' AS table_name, a.enterprise_number, e.start_date
    FROM administrator a LEFT JOIN enterprise e ON e.enterprise_number = a.enterprise_number
    WHERE a.valid_from IS NULL
    UNION ALL
    SELECT 'shareholder', sh.enterprise_number, e.start_date
    FROM shareholder sh LEFT JOIN enterprise e ON e.enterprise_number = sh.enterprise_number
    WHERE sh.valid_from IS NULL
    UNION ALL
    SELECT 'participating_interest', pi.enterprise_number, e.start_date
    FROM participating_interest pi LEFT JOIN enterprise e ON e.enterprise_number = pi.enterprise_number
    WHERE pi.valid_from IS NULL
    UNION ALL
    SELECT 'affiliation', af.enterprise_number, e.start_date
    FROM affiliation af LEFT JOIN enterprise e ON e.enterprise_number = af.enterprise_number
    WHERE af.valid_from IS NULL
)
SELECT table_name,
       COUNT(*) AS residual_rows,
       COUNT(*) FILTER (WHERE pg_temp._bt_vf_stage_d_try_date(start_date) IS NULL) AS missing_or_unparseable_start_date
FROM residuals
GROUP BY table_name
ORDER BY table_name;
```

After counts:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS null_valid_from,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start') AS fallback_rows
FROM administrator
UNION ALL
SELECT 'shareholder', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start')
FROM affiliation;
```

Constraint and column verification:

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

Row-level spot check using the backup snapshot as the known-residual source:

```sql
WITH picked AS (
    SELECT b.enterprise_number, b.deposit_key, b.name, b.role, b.fallback_valid_from
    FROM _bt_vf_stage_d_backup_administrator b
    WHERE b.fallback_valid_from IS NOT NULL
    ORDER BY b.enterprise_number, b.deposit_key, b.name
    LIMIT 1
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
 AND a.deposit_key = p.deposit_key
 AND a.name IS NOT DISTINCT FROM p.name
 AND a.role IS NOT DISTINCT FROM p.role;
```

Expected result: `a.valid_from = expected_valid_from` and `a.valid_from_provenance = 'fallback_enterprise_start'`.

## Open Decisions Before Implementation

1. Confirm D-a as the approved residual strategy.
2. Decide the policy for rows whose `enterprise.start_date` is missing or unparseable.
3. Ship or explicitly schedule writer fixes before the migration, especially `scripts/backfill_affiliation.py`, `scripts/backfill_nbb_governance.py`, and the outside-repo Staatsblad consumer.
4. Approve the writer pause window and exact service/cron commands.
5. Confirm backup snapshot names and retention period.
