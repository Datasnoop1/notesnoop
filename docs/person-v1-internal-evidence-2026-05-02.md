# Person v1 Internal Evidence - 2026-05-02

## Scope

Person v1 shipped as an internal-only audit surface. `PERSON_PUBLIC_URL_ENABLED`
defaults off and is read per request. Public URL work remains blocked by the
separate legal, policy, and golden-set gates.

## Local Validation

- `python -m py_compile backend/feature_flags.py backend/routers/people.py scripts/person_resolver.py`
  passed.
- `pytest backend/tests/test_person_v1.py -q` passed: 6 tests.
- `python scripts/check_migration_style.py` passed.
- `bash scripts/check_no_runtime_ddl.sh` passed via Git Bash.
- `npx eslint src/app/person/[id]/page.tsx src/lib/api.ts` passed.
- `git diff --check` passed.
- UTF-8/BOM/mojibake scan passed for `src/schema.sql` and
  `migrations/2026-05-02_person_v1.sql`.
- Deviation: full `npm --prefix frontend run lint` still reports
  pre-existing unrelated source errors outside the Person v1 files; the
  touched frontend files pass targeted lint.

## Staging Evidence

- Branch deployed: `feat/person-v1-internal` at `b0bb2d2`.
- `python3 scripts/migrate.py dry-run --target staging` reported one
  pending migration: `2026-05-02_person_v1.sql`.
- `python3 scripts/migrate.py up --target staging` applied one migration.
- `python3 scripts/migrate.py status --target staging --json` reported
  21 files, 21 applied, 0 pending, 0 extra applied, 0 checksum mismatches.
- `backend-staging` and `frontend-staging` rebuilt and became healthy.
- `/api/health` returned HTTP 200.
- Resolver first successful staging run:
  - Tier A persons: 14,817
  - Tier A links: 15,671
  - Tier B links: 12,188
  - Tier C `staatsblad_event` links: 89,844
  - Tier C `administrator` links: 991,543
  - Tier C `shareholder` links: 12,902
  - Tier C `affiliation` links: 49,815
  - Role counts updated: 1,158,921
- Resolver idempotency rerun:
  - Tier A persons: 0
  - Tier A links: 0
  - Tier B links: 0
  - Tier C links across all sources: 0
  - Role counts updated: 0
- Staging DB counts after resolver:
  - `person`: 1,158,921
  - `person_link`: 1,171,963
  - `person_merge_log`: 0
  - Tier A links: 15,671
  - Tier B links: 12,188
  - Tier C links: 1,144,104
  - Affiliation links: 49,975
- Anonymous staging HTTP request returned 401 because staging admin-only
  middleware is active. The deployed app gate probe returned 404 from
  `_require_person_v1_access(None)` with `PERSON_PUBLIC_URL_ENABLED=false`.

## Production Gate Y Evidence

- Pending.

## Deferred Public URL Gates

- Policy record: `docs/person-v1-policy.md` is still a stub.
- Legal memo: pending external Belgian privacy-lawyer sign-off.
- Golden set: public-ramp precision threshold not measured yet.
