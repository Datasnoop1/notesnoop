# NBB governance durability evidence - 2026-05-02

Branch: `feat/bitemporal-governance-durability`  
Purpose: Bitemporal prerequisite.

## Local validation

- `pytest backend/tests/test_nbb_governance_durability.py -q`: passed.
- `pytest backend/tests/test_person_v1.py backend/tests/test_ownership_id.py backend/tests/test_ownership_graph_sql.py backend/tests/test_nbb_governance_durability.py -q`: 23 passed.
- `python -m py_compile backend/nbb_governance.py backend/nbb_batch_pipeline.py scripts/nbb_nightly_backload.py scripts/retry_failed_governance.py`: passed.
- `python scripts/check_migration_style.py migrations/2026-05-02_governance_load_log.sql`: passed.
- UTF-8/BOM/mojibake scan clean for `src/schema.sql`, `migrations/2026-05-02_governance_load_log.sql`, and phase-gates edit.

## Staging

Migration runner:

```text
database: leadpeek_staging
Applied 1 migration(s).

target: staging
database: leadpeek_staging
baseline_as_of: 2026-04-28
schema_migrations_exists: True
files: 23
applied: 23
pending: 0
checksum_mismatches: 0
```

App and object checks:

```text
backend health: {"status":"ok","service":"datasnoop-api"}
database: leadpeek_staging
governance_load_log_exists: true
indexes: governance_load_log_pkey,idx_governance_load_retry
smoke_row: ('ok', 1, True)
```

The staging smoke wrote a synthetic `governance_load_log` failure row,
then recorded success for the same `(enterprise_number, deposit_key)`.
The final row was `status='ok'`, `attempts=1`, and `last_error IS NULL`;
the synthetic row was deleted after verification.

## Prod gate

Production migration, backend/worker rebuild, managed-cron install, and
prod smoke remain the Gate Y tail step for this prerequisite branch.
