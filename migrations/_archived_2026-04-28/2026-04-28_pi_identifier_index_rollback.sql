-- Rollback for 2026-04-28_pi_identifier_index.sql
-- ----------------------------------------------------------------------------
-- Drops the partial index on participating_interest(identifier). The reverse
-- PI lookup will revert to a sequential scan — see the forward migration
-- for context.
--
-- Run:
--   psql $DATABASE_URL -f migrations/2026-04-28_pi_identifier_index_rollback.sql
-- ----------------------------------------------------------------------------

DROP INDEX CONCURRENTLY IF EXISTS idx_pi_identifier;
