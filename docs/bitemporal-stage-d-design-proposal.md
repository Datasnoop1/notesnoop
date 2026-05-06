# Bitemporal Stage D Design Proposal

Status: design only. Do not implement until every Stage D precondition is true: Stage C has soaked for 30 days, the earliest implementation date has passed (2026-06-04), the operator explicitly says "go on Stage D", and the concurrent writer plan below has shipped and been verified.

This revision addresses PR #67 review findings. It stays design-only: no migrations, writer code, or schema changes are included in this branch.

Stage D tightens only `valid_from`. `valid_to` remains nullable because NULL still means open-ended / no known end date.

## Recommendation

Proceed with option D-a, but make it gated and auditable:

- Fill residual NULL `valid_from` values from a parsed `enterprise.start_date` fallback.
- Stamp `valid_from_provenance = 'fallback_enterprise_start'`.
- For affiliation rows only, if the target `enterprise.start_date` is unavailable,
  use the approved supplemental fallbacks in order: source filing
  `financial_data.deposit_date` with `fallback_filing_deposit`, then
  `recorded_from::date` with `fallback_unknown_start`.
- Keep all governance rows; do not drop known facts.
- Abort the Stage D migration if any row in the four target tables still has `valid_from IS NULL` after the fallback fill.
- Treat `fallback_enterprise_start`, `fallback_filing_deposit`, and
  `fallback_unknown_start` as migration-only provenance values. Live writers
  must not reuse these labels; if a future writer intentionally falls back at
  ingest, it must use a distinct value such as `live_writer_enterprise_start` or
  skip/log the row. This keeps Stage D backout predicates unambiguous.

The Stage D implementation PR must also update the `COMMENT ON COLUMN ... valid_from_provenance` text created in `migrations/2026-05-04_bitemporal_provenance_columns.sql` for all four tables to include the new `fallback_enterprise_start`, `fallback_filing_deposit`, and `fallback_unknown_start` values. Existing Stage C provenance values must not be dropped or renamed.

If `enterprise.start_date` is NULL, unparseable, before `1830-01-01`, or after `CURRENT_DATE`, Stage D blocks by default and publishes the row list for operator decision, except for the two affiliation-only supplemental fallbacks above. Do not stamp `fallback_enterprise_start` against a date that did not come from a valid enterprise-start fallback.

## D1 - Residual NULL Strategy

Current prod residuals as of 2026-05-05:

| Table | NULL `valid_from` |
|---|---:|
| `administrator` | 17,634 |
| `shareholder` | 2,645 |
| `participating_interest` | 4,720 |
| `affiliation` | 733 |

Use D-a as the mainline strategy. The product should keep these governance facts and mark the fallback as low-confidence provenance, not delete the rows.

D-b is rejected because dropping rows loses known governance facts. D-c is the fallback only if the preflight finds material `enterprise.start_date` gaps or the operator rejects the blocked-row policy.

### Fallback Date Rule

The Stage D fallback candidate is:

```sql
CASE
    WHEN enterprise_start_date IS NOT NULL
     AND source_deposit_date IS NOT NULL
        THEN LEAST(enterprise_start_date, source_deposit_date)
    ELSE enterprise_start_date
END
```

This handles temporal invalidity where KBO corrections or re-incorporation data make `enterprise.start_date > source_deposit_date`. In those cases we cap the fallback to the source deposit date so a governance fact does not start after the filing that evidenced it. The Stage D backup snapshot must record both `enterprise_start_date` and `source_deposit_date`, plus whether the source-date cap was used. Verification should report the count of capped rows per table.

For administrator, shareholder, and participating interest, rows without a valid `enterprise_start_date` still block Stage D. For affiliation, the supplemental fallback arms below are now the approved blocked-row policy.

### Affiliation Supplemental Fallbacks

The 2026-05-05 Step 3 dry-run found 47 affiliation rows whose target
`enterprise_number` has no matching `enterprise` row. The follow-up diagnostic
on tracker #68 comment `4381525029` showed that the target CBEs are valid and
public-KBO-findable, but absent from local canonical company tables. The
operator approved policy (2): unblock Stage D with explicit weaker provenance
rather than repairing the broader KBO-load gap in this rollout.

For `affiliation` only, apply fallback arms in this exact order:

1. `fallback_enterprise_start`: the mainline enterprise-start rule above.
2. `fallback_filing_deposit`: for rows still NULL, use
   `financial_data.deposit_date` joined by
   `(via_enterprise_number, via_deposit_key)`, bounded to
   `1830-01-01 <= deposit_date <= CURRENT_DATE`.
3. `fallback_unknown_start`: for rows still NULL, use
   `affiliation.recorded_from::date`, bounded to
   `1830-01-01 <= recorded_from::date <= CURRENT_DATE`.

Current expected split on the prod-shaped staging snapshot is 686 affiliation
rows from `fallback_enterprise_start`, 46 from `fallback_filing_deposit`, and 1
from `fallback_unknown_start`. Any rows still NULL after these three arms must
hit the existing `RAISE EXCEPTION` safety gate.

### Parser

Use the Stage A parser body as the base, including both `YYYY-MM-DD` and `DD/MM/YYYY`, then add date sanity guards. The stricter one-format parser from the first design draft is rejected because real `enterprise.start_date` data uses both formats.

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
```

### Writer Readiness

The missing-`deposit_date` writer bug exposes all four governance tables to NULL `valid_from`, not only affiliation:

- `backend/nbb_governance.py:730`: admin uses `mandate_start OR source_deposit_date`, so admin can still get NULL if both are missing.
- `backend/nbb_governance.py:765`, `:803`, `:846`: shareholder, participating interest, and affiliation use `source_deposit_date` directly.
- `scripts/backfill_affiliation.py:260` calls `store_governance_snapshot` without `deposit_date`.
- `scripts/backfill_nbb_governance.py:167` calls `store_governance_snapshot` without `deposit_date`.
- `backend/routers/companies/structure.py:744` bypasses `store_governance_snapshot` and directly inserts `administrator (..., valid_from, ...)`; `NULLIF(%s, '')::date` can still produce NULL. Its sibling update paths at `:773` and `:788` write `valid_to`, which remains nullable and is not a Stage D blocker, but the endpoint is a live governance writer.
- `backend/nbb_batch_pipeline.py:279` is safe only while the NBB batch pipeline is paused; it still writes via `store_governance_snapshot`.

Hard gate before Stage D implementation:

- Ship writer-fix PRs for `scripts/backfill_affiliation.py` and `scripts/backfill_nbb_governance.py`, or disable those scripts until they can pass a non-NULL date or skip/log undatable filings.
- Verify live backend paths that already pass `deposit_date`: `backend/routers/companies/financials.py:428`, `scripts/nbb_nightly_backload.py:426`, `scripts/retry_failed_governance.py:129`, and `backend/nbb_batch_pipeline.py:279`.
- Fix or route-block `POST /api/companies/{cbe}/extract-admins` before the migration window because it is user-triggered and bypasses the shared writer.
- The outside-repo `/opt/leadpeek/staatsblad_consumer_proc.py` must be inspected by the implementer, not delegated to the operator. The runbook must include `pgrep -af staatsblad_consumer` returning nothing or an explicit service stop before migration.

Post-pause gate: after writers are paused, confirm no fresh NULL `valid_from` inserts since the preflight timestamp:

```sql
-- Set :pause_started_at in psql to the timestamp captured immediately
-- after writer pause completed.
SELECT 'administrator' AS table_name, COUNT(*) AS fresh_nulls
FROM administrator
WHERE valid_from IS NULL AND recorded_from >= :'pause_started_at'::timestamptz
UNION ALL
SELECT 'shareholder', COUNT(*)
FROM shareholder
WHERE valid_from IS NULL AND recorded_from >= :'pause_started_at'::timestamptz
UNION ALL
SELECT 'participating_interest', COUNT(*)
FROM participating_interest
WHERE valid_from IS NULL AND recorded_from >= :'pause_started_at'::timestamptz
UNION ALL
SELECT 'affiliation', COUNT(*)
FROM affiliation
WHERE valid_from IS NULL AND recorded_from >= :'pause_started_at'::timestamptz;
```

Expected result: zero in all four tables.

### Consumer UX

The new `fallback_enterprise_start`, `fallback_filing_deposit`, and `fallback_unknown_start` values must be surfaced as low-confidence in the same rollout or explicitly handled by every consumer that displays provenance. Current `frontend/src` has no direct `valid_from` / `valid_to` references, but backend responses using `SELECT *` can expose the value. UI copy should not present them as exact mandate or ownership starts; `fallback_enterprise_start` should read as an incorporation-date bound, `fallback_filing_deposit` as a filing-date bound, and `fallback_unknown_start` as an observed-in-system upper bound.

## D2 - NOT NULL Transition Mechanics

Use the CHECK-then-validate pattern for each governance table:

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

The implementation must confirm the deployed Postgres major version is PG 12+ before relying on metadata-only `SET NOT NULL` after a validated CHECK:

```sql
SELECT current_setting('server_version_num')::int >= 120000 AS supports_fast_set_not_null;
```

If this returns false, do not proceed with the current plan.

### Required Migration Order

The maintenance window order is mandatory:

1. Pause all governance writers.
2. Confirm no active governance writer sessions remain.
3. Capture `:pause_started_at`.
4. Run the "fresh NULLs since pause" check.
5. Create Stage D backup snapshots inside the same transaction as the fallback fill.
6. Run fallback UPDATEs.
7. Re-confirm zero residual `valid_from IS NULL` rows.
8. Add CHECK constraints `NOT VALID`.
9. Run a tiny "any NULL?" assertion again.
10. Validate CHECK constraints.
11. Run `ALTER COLUMN valid_from SET NOT NULL`.
12. Recreate governance current/as-of views/functions without `valid_from IS NULL`.
13. Update provenance column comments to include `fallback_enterprise_start`, `fallback_filing_deposit`, and `fallback_unknown_start`.
14. Run verification SQL.
15. Restart backend/connection-pool users so plans pick up rewritten views/functions.
16. Resume writers only after verification passes.

Bake the zero-residual assertion into the migration:

```sql
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM administrator WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM shareholder WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM participating_interest WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM affiliation WHERE valid_from IS NULL
        LIMIT 1
    ) THEN
        RAISE EXCEPTION 'Stage D abort: residual NULL valid_from rows remain';
    END IF;
END
$$;
```

Use migration headers consistent with prior stages, including `lock_timeout=5s`. If any step aborts on `lock_timeout`, do not immediately retry blind. Inspect blockers in `pg_stat_activity`, confirm writers are still paused, then rerun the idempotent migration after blockers clear. This matches the Stage C lesson from `migrations/2026-05-04_bitemporal_provenance_columns_backfill.sql`.

Expected duration:

| Step | Expected duration | Notes |
|---|---:|---|
| Writer pause + drain | 5-15 min | Includes backend route block and process checks |
| Snapshot + 4 fallback UPDATEs | 5-15 min | Smaller than Stage C C2 but still row-locking |
| 4 ADD CONSTRAINT NOT VALID | <1 min | Catalog changes, lock-sensitive |
| 4 VALIDATE CONSTRAINT | 10-30 min | Full scans, administrator is the largest table |
| 4 SET NOT NULL | <1 min | Only after PG 12+ and validated CHECK |
| View/function recreation + comments | <5 min | Include backend restart after |

Reserve a 60-minute window with a 90-minute ceiling. The first design's 30-minute window is too optimistic given lock coordination and four full-table validations.

## D3 - Read-Path Cleanup Audit

Search method: PowerShell recursive `Select-String`, because `rg.exe` is blocked by local Windows permissions in this workspace.

Frontend:

- `frontend/src`: no `valid_from` or `valid_to` references found. No cleanup needed, apart from consumer handling of the Stage D fallback provenance values noted above.

Backend Python:

- `backend/routers/companies/financials.py:428`: live synchronous write path via `POST /api/companies/{cbe}/load`; must be paused.
- `backend/routers/companies/structure.py:744`: direct `INSERT INTO administrator (..., valid_from, ...)`; must be paused or fixed.
- `backend/routers/companies/structure.py:773` and `:788`: direct `valid_to` updates; must be understood, but `valid_to` stays nullable.
- `backend/nbb_batch_pipeline.py:279`: governance writer; pause by avoiding the daily batch window and confirming no active process.
- `backend/nbb_governance.py:450`: `_insert_bitemporal_unique` uses `valid_to IS NULL` to close prior open current rows. Must stay.
- `backend/nbb_governance.py:676`: ownership-edge closure uses `valid_to IS NULL`. Must stay; ownership_edge is not one of the four Stage D tables.
- `backend/tests/test_bitemporal_phase_a.py:30` and `backend/tests/test_ownership_graph_sql.py:37-38`: tests assert old NULL-aware view SQL. Stage D should update governance-table expectations after the view rewrite; ownership-edge expectations stay.
- `backend/tests/test_bitemporal_valid_from_stage_a.py` and `backend/tests/test_bitemporal_valid_from_stage_b.py`: historical migration guard tests assert Stage A/B NULL-only UPDATE scoping. Keep them.

`src/schema.sql` governance views and helpers:

- The four `*_current` views start at `src/schema.sql:1625`; their WHERE branches at `:1628-1650` semantically depend on "NULL valid_from means in force". Rewrite before or in the same Stage D migration:

```sql
WHERE valid_from <= CURRENT_DATE
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL
```

- The four `*_as_of` functions start at `src/schema.sql:1658`; their WHERE branches at `:1668-1717` also need the same cleanup:

```sql
WHERE valid_from <= valid_at
  AND (valid_to IS NULL OR valid_to > valid_at)
  AND recorded_from <= known_at
  AND (recorded_to IS NULL OR recorded_to > known_at)
```

- Function recreation detail: these functions return `SETOF administrator`, `SETOF shareholder`, etc. `CREATE OR REPLACE FUNCTION` should work because the signature and row type name do not change, but the implementation migration must test this. If PostgreSQL rejects replacement, use `DROP FUNCTION ...` followed by `CREATE FUNCTION ...`, then re-grant privileges in the same migration.
- Partial unique indexes around `src/schema.sql:1733-1757` use `valid_to IS NULL`; must stay.
- Ownership graph references around `src/schema.sql:1883`, `1931`, `1963-1983` are not Stage D governance-table references. Keep them unless a separate ownership-edge rollout is proposed.

Migrations:

- `migrations/2026-05-02_bitemporal_phase_a.sql` contains historical NULL-aware views/functions. Do not edit an already-applied migration. Stage D adds a new migration that recreates the views/functions with the non-null `valid_from` predicate.
- `migrations/2026-05-02_ownership_graph.sql` NULL-aware ownership-edge logic stays.
- `migrations/2026-05-04_bitemporal_valid_from_stage_a.sql`, `2026-05-04_bitemporal_valid_from_stage_b.sql`, and `2026-05-04_bitemporal_provenance_columns_backfill.sql` contain historical NULL-only backfill guards. Keep them.

## D4 - Concurrent Writer Pause Strategy

Backend-write pause is mandatory for the full fallback UPDATE -> ADD CONSTRAINT -> VALIDATE -> SET NOT NULL -> view rewrite window. A single in-flight `store_governance_snapshot` call can deadlock or insert a new NULL before validation, repeating the Stage C failure mode.

Required pauses:

- `nbb-backload-worker`: stop with `docker compose stop nbb-backload-worker`.
- `backend/routers/companies/financials.py:154` (`POST /api/companies/{cbe}/load`) because it calls `store_governance_snapshot` at `:428`.
- `backend/routers/companies/structure.py:680` (`POST /api/companies/{cbe}/extract-admins`) because it directly inserts admin `valid_from` at `:744`/`:759`.
- `backend/nbb_batch_pipeline.py:279`: avoid the 01:00 daily NBB batch pipeline and verify no process is running.
- `scripts/backfill_affiliation.py` cron at `04:00` in `scripts/install_crons.sh`; disable cron and confirm no current `backfill_affiliation.py` process.
- `scripts/backfill_nbb_governance.py` and `scripts/retry_failed_governance.py`: confirm no manual run is active.
- `scripts/staatsblad_batch_every_2d.py` cron at `04:00` every two days; pause/avoid the window because downstream event projection can touch governance via outside-repo consumers.
- Outside-repo `/opt/leadpeek/staatsblad_consumer_proc.py`: implementer must inspect and stop it if present.

Concrete pause mechanism:

- Recommended concrete mechanism: add a maintenance-mode switch before Stage D that returns 503 for governance-writing routes while leaving read-only traffic online. It must cover `POST /api/companies/{cbe}/load` and `POST /api/companies/{cbe}/extract-admins`.
- If no maintenance switch ships before Stage D, use nginx-level route blocking for those POST routes.
- If neither route-level block is available, stop the backend service for the entire migration window. This is heavier but safer than allowing profile-triggered writes.

The implementation runbook must not say "operator should identify" outside writers. It must include:

```bash
pgrep -af 'staatsblad_consumer|staatsblad_consumer_proc|backfill_affiliation|backfill_nbb_governance|retry_failed_governance|nbb_batch_pipeline|nbb_nightly_backload'
```

and an explicit check of `/opt/leadpeek/` for any long-running governance writer. `pgrep -af staatsblad_consumer` must return nothing, or the matched process must be stopped and documented.

Run the migration outside governance cron windows. Recommended window: `04:30 UTC < t < 23:30 UTC`, after verifying local/UTC schedule alignment, to avoid the 01:00 NBB batch, 04:00 affiliation cron, and every-two-days Staatsblad batch. KBO updater is not a governance-table writer.

Resume paused services only after all after-counts and spot checks pass.

## D5 - Backout

The CHECK/NOT NULL portion is reversible:

```sql
ALTER TABLE administrator ALTER COLUMN valid_from DROP NOT NULL;
ALTER TABLE administrator DROP CONSTRAINT IF EXISTS administrator_valid_from_not_null;
```

Repeat for the other three tables.

However, view/function rollback is coupled to any data rollback that reintroduces NULL `valid_from`. If rollback restores any `valid_from` to NULL, the rollback migration must also recreate the four `*_current` views and four `*_as_of` functions with their old `valid_from IS NULL OR ...` branches. Dropping the constraint without restoring those views would silently hide re-NULLed rows from current/as-of reads.

Alternative: if the operator only drops the NOT NULL metadata and does not restore fallback-filled rows to NULL, the non-null view predicates can remain. The rollback runbook must choose one path explicitly.

### Backup Snapshot Deliverable

The implementation PR must include a checked-in backup snapshot SQL helper. This is not optional. Stage C showed that ad hoc backup schemas are easy to under-specify.

Use one table per governance table, retain for 7 calendar days after apply, and schedule cleanup at creation time. If Stage D applies on the earliest possible date, 2026-06-04, the cleanup date is on or after 2026-06-11.

Each backup row must include:

- primary identity columns
- natural-key columns used by writers
- `source_deposit_date`
- `valid_from`
- `valid_to`
- `valid_from_provenance`
- `valid_to_provenance`
- raw `enterprise.start_date`
- parsed enterprise start date
- fallback date actually used
- fallback provenance actually used
- whether source-date capping was used

For `_bt_vf_stage_d_backup_affiliation`, also store
`via_enterprise_number`, `via_deposit_key`, the resolved
`financial_data.deposit_date` used by `fallback_filing_deposit`, and
`recorded_from::date` used by `fallback_unknown_start`.

Snapshot creation must occur in the same transaction as the fallback UPDATE while writers are paused. To eliminate the snapshot -> update race, either lock each target table before snapshotting and updating, or perform the snapshot and corresponding update in a single transaction with a documented lock primitive. The implementation should use a consistent table order to avoid deadlocks.

Example lock pattern:

```sql
LOCK TABLE administrator, shareholder, participating_interest, affiliation IN SHARE ROW EXCLUSIVE MODE;
```

The exact lock mode should be validated in the implementation PR; it must block concurrent writes for the snapshot/fill window without unnecessarily blocking reads.

### Explicit Backout SQL

The backout joins intentionally use raw primary-key columns, not `search_normalize(name)`. Stage A used `search_normalize` for fuzzy identity matching, but Stage D backup restore is row-image restoration against raw PK/natural keys captured before the fill.

Administrator:

```sql
UPDATE administrator a
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_administrator b
WHERE a.enterprise_number = b.enterprise_number
  AND a.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND a.name IS NOT DISTINCT FROM b.name
  AND a.role IS NOT DISTINCT FROM b.role
  AND a.valid_from = b.fallback_valid_from
  AND a.valid_from_provenance = 'fallback_enterprise_start';
```

Shareholder PK: `(enterprise_number, deposit_key, name)`.

```sql
UPDATE shareholder sh
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_shareholder b
WHERE sh.enterprise_number = b.enterprise_number
  AND sh.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND sh.name IS NOT DISTINCT FROM b.name
  AND sh.valid_from = b.fallback_valid_from
  AND sh.valid_from_provenance = 'fallback_enterprise_start';
```

Participating interest PK: `(enterprise_number, deposit_key, name)`.

```sql
UPDATE participating_interest pi
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_participating_interest b
WHERE pi.enterprise_number = b.enterprise_number
  AND pi.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND pi.name IS NOT DISTINCT FROM b.name
  AND pi.valid_from = b.fallback_valid_from
  AND pi.valid_from_provenance = 'fallback_enterprise_start';
```

Affiliation PK: `(person_name, enterprise_number, via_enterprise_number, affiliation_type)`. There is no `deposit_key` column on `affiliation`; the related filing column is `via_deposit_key`.

```sql
UPDATE affiliation af
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_affiliation b
WHERE af.person_name = b.person_name
  AND af.enterprise_number = b.enterprise_number
  AND af.via_enterprise_number = b.via_enterprise_number
  AND af.affiliation_type = b.affiliation_type
  AND af.valid_from = b.fallback_valid_from
  AND af.valid_from_provenance = b.fallback_provenance
  AND b.fallback_provenance IN (
      'fallback_enterprise_start',
      'fallback_filing_deposit',
      'fallback_unknown_start'
  );
```

After any of these updates restore NULL `valid_from`, immediately restore the NULL-aware current/as-of views/functions in the same rollback change.

## D6 - Verification SQL

Before counts:

```sql
SELECT 'administrator' AS table_name,
       COUNT(*) AS total_rows,
       COUNT(*) FILTER (WHERE valid_from IS NULL) AS null_valid_from,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start') AS enterprise_start_rows,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit') AS filing_deposit_rows,
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start') AS unknown_start_rows
FROM administrator
UNION ALL
SELECT 'shareholder', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM shareholder
UNION ALL
SELECT 'participating_interest', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM participating_interest
UNION ALL
SELECT 'affiliation', COUNT(*), COUNT(*) FILTER (WHERE valid_from IS NULL),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_enterprise_start'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_filing_deposit'),
       COUNT(*) FILTER (WHERE valid_from_provenance = 'fallback_unknown_start')
FROM affiliation;
```

Preflight for rows that would block D-a:

```sql
WITH residuals AS (
    SELECT 'administrator' AS table_name,
           a.enterprise_number,
           e.start_date,
           a.source_deposit_date
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

Affiliation supplemental fallback preview:

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

The post-apply fallback count per table should equal the backup-table row count for rows with non-NULL `fallback_valid_from`, minus any rows explicitly excluded by an operator-approved blocked-row policy. For the current affiliation blocker shape, expected affiliation counts are `enterprise_start_rows = 686`, `filing_deposit_rows = 46`, and `unknown_start_rows = 1`.

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

Row-level spot checks: sample 5-10 rows per table from the Stage D backup tables and confirm `valid_from = fallback_valid_from` plus the expected fallback provenance. For administrator, shareholder, and participating interest, this is always `fallback_enterprise_start`; for affiliation, it may be any of the three approved Stage D fallback values.

Administrator example:

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

Expected result for the administrator sample: every row has `a.valid_from = expected_valid_from` and `a.valid_from_provenance = 'fallback_enterprise_start'`. For affiliation samples, verify against the backup row's `fallback_valid_from` and `fallback_provenance`, which may be any of the three approved Stage D fallback values.

The verification SQL contains no secrets and is safe to paste into PR comments.

## Implementation Deliverables After Approval

When the operator eventually says "go on Stage D", the implementation PR must include:

1. Writer-fix PRs or documented disables for every call site listed under writer readiness.
2. Checked-in backup snapshot SQL with explicit columns for all four tables.
3. Stage D migration for fallback fill, zero-residual assertions, CHECK constraints, validation, `SET NOT NULL`, view/function rewrites, grants if needed, and provenance COMMENT updates.
4. Rollback migration or runbook covering constraints, data restore, and view/function rollback.
5. Static tests for no remaining governance-table `valid_from IS NULL OR` predicates.
6. A maintenance runbook with exact writer pause commands, process checks, expected durations, and lock-timeout retry steps.
7. Consumer/UI handling for `fallback_enterprise_start`, `fallback_filing_deposit`, and `fallback_unknown_start` as low-confidence provenance.

## Open Decisions Before Implementation

1. Confirm D-a plus the affiliation supplemental fallback arms as the approved residual strategy.
2. Decide whether source-date-capped fallback rows remain under `fallback_enterprise_start` or get a second explicit provenance value.
3. Decide the policy for any future rows whose `enterprise.start_date` is missing and whose table-specific supplemental fallbacks do not apply.
4. Choose the backend write-pause primitive: maintenance flag, nginx route block, or full backend stop.
5. Confirm backup retention: 7 days from apply, then scheduled cleanup.
