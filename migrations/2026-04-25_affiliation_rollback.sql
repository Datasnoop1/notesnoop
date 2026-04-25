-- Rollback for migrations/2026-04-25_affiliation.sql.
-- Drops the affiliation table and all its dependent indexes.
-- DESTRUCTIVE. Loses backfilled affiliation rows. Re-running the
-- forward migration recreates the structure but the rows themselves
-- have to be recovered by re-running scripts/backfill_affiliation.py.
BEGIN;
DROP TABLE IF EXISTS affiliation;
DROP TABLE IF EXISTS affiliation_backfill_log;
COMMIT;
