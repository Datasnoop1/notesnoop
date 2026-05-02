# Bitemporal Phase A evidence - 2026-05-02

Branch: `feat/bitemporal-phase-a`

## Local validation

- `pytest backend/tests -q`: 77 passed.
- Focused scripts: `scripts/test_nbb_governance.py`,
  `scripts/test_nbb_nightly_backload.py`, `scripts/test_person_network_center.py`,
  `scripts/test_structure_merge.py`, and
  `scripts/test_financials_reference_normalization.py`: 9 passed with local
  Supabase HS256 fallback test env.
- `python -m py_compile` over touched backend routers and NBB scripts: passed.
- `python scripts/check_migration_style.py migrations/2026-05-02_bitemporal_phase_a.sql`: passed.
- Runtime-DDL grep equivalent: no unwaived runtime DDL outside
  `migrations/` and `src/schema.sql`.
- UTF-8/BOM/mojibake scan clean for `src/schema.sql`, the Phase A migration,
  read-path audit, and `backend/nbb_governance.py`.

## Read-path audit

Committed in `docs/bitemporal-readpath-audit.md`.

Production-code grep for bare fact-table reads:

```text
git grep ... -- backend scripts ':!scripts/test_*' ':!backend/tests'
```

Expected and observed: no output.

The only spec deviation is the documented shareholder natural-key gap:
the r25 sketch names `shareholder.country`, but the table has no such
column. Phase A uses `COALESCE(address, '')` as the available discriminator
and records this as a deep-dive revision callout candidate.

## Staging

Migration runner:

```text
database: leadpeek_staging
Applied 1 migration(s).

target: staging
database: leadpeek_staging
baseline_as_of: 2026-04-28
schema_migrations_exists: True
files: 24
applied: 24
pending: 0
checksum_mismatches: 0
```

Post-migration table checks:

```text
administrator: valid_from_null=228207 recorded_from_null=0 recorded_to_closed=502455
shareholder: valid_from_null=7808 recorded_from_null=0 recorded_to_closed=21933
participating_interest: valid_from_null=32900 recorded_from_null=0 recorded_to_closed=114424
affiliation: valid_from_null=7 recorded_from_null=0 recorded_to_closed=1300
administrator_current_exists: True
shareholder_current_exists: True
participating_interest_current_exists: True
affiliation_current_exists: True
admins_as_of_count: 573091
```

Backend smoke:

```text
backend-staging: healthy
backend health: {"status":"ok","service":"datasnoop-api"}
```

`/structure` and `/network` returned `401 Unauthorized` without an auth token,
which is expected for direct in-container unauthenticated probes; backend
startup and DB-backed health remained green.

## Prod gate

Gate Y comment: PR #42 comment
`https://github.com/Datasnoop1/platform/pull/42#issuecomment-4364033936`.

Migration runner:

```text
database: leadpeek
Applied 1 migration(s).

target: prod
database: leadpeek
baseline_as_of: 2026-04-28
schema_migrations_exists: True
files: 24
applied: 24
pending: 0
checksum_mismatches: 0
```

Post-migration table checks:

```text
administrator: valid_from_null=228207 recorded_from_null=0 recorded_to_closed=509864
shareholder: valid_from_null=7808 recorded_from_null=0 recorded_to_closed=22012
participating_interest: valid_from_null=32900 recorded_from_null=0 recorded_to_closed=115309
affiliation: valid_from_null=9 recorded_from_null=0 recorded_to_closed=1828
administrator_current_exists: True
shareholder_current_exists: True
participating_interest_current_exists: True
affiliation_current_exists: True
admins_as_of_count: 578310
```

Backend + worker smoke:

```text
leadpeek-backend-1: Up (healthy)
leadpeek-nbb-backload-worker-1: Up (healthy)
backend health: {"status":"ok","service":"datasnoop-api"}
```

The production tail rebuilt and recreated `backend` and
`nbb-backload-worker`. The only compose warnings were the existing unset
`NEXT_PUBLIC_API_URL` warning and an orphan staging scraper container notice;
neither affected the migrated production services.
