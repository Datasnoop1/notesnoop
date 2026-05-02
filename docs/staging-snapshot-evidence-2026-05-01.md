# Staging Snapshot Evidence - 2026-05-01

## Operator Decision

- Date: 2026-05-01
- Scope: Week-2b staging DB clone, scrub, workers, and nightly snapshot cron.
- Stripe and Supabase isolation remain deferred to the end-of-project hardening pass after Bitemporal lands.

## Restore Findings

- Production database size: 37 GB.
- Host PostgreSQL server/client version: 16.13.
- Snapshot archive size during restore attempts: about 5.3 GB.
- The refresh script uses the host's default PostgreSQL client to avoid PG17 archive settings that PostgreSQL 16 rejects.
- Fresh staging restore prereqs must precreate prod extensions and generated-column search helper functions because `pg_restore` uses an empty search path while validating generated columns.

## Explicit Deviation

- `idx_ce_embedding_hnsw` on `company_embedding` is excluded from the staging snapshot restore list.
- Reason: repeated full-parity restore attempts reached this HNSW index and then slowed to multi-hour rebuild behavior even with restore-only `maintenance_work_mem` raised to 3 GB.
- Existing docs already flag this index as a suspicious zero-scan, 2.56 GB index pending investigation (`docs/db-maintenance-recommendations.md`, `docs/tech-debt.md`).
- Impact: staging gets the scrubbed data clone and regular indexes, but does not currently have this HNSW performance index after snapshot refresh.
- Revisit trigger: end-of-project hardening pass after Bitemporal lands, or earlier if semantic search parity becomes a required staging smoke test.

## Expected Week-2b Postconditions

- `leadpeek_staging` is created from a production snapshot and scrubbed with `scripts/staging_scrub.sql`.
- Staging workers use `.env.staging` and remain behind the `test-workers` profile.
- Nightly cron invokes `scripts/refresh_staging_snapshot.sh`.
- The snapshot script does not print database URLs or secrets.
