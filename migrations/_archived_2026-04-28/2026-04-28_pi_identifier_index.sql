-- Migration: index on participating_interest(identifier)
-- ----------------------------------------------------------------------------
-- Why: the spiderweb (network.py:718,795) and the new parent_companies
-- query in /api/companies/{cbe}/structure both filter
-- `participating_interest` with `WHERE identifier = %s` (or
-- `identifier IN (...)`). Only `idx_pi_ent` on `enterprise_number` exists,
-- so every reverse-direction lookup falls back to a sequential scan over
-- the whole table. That's been a latent cost for the spiderweb already;
-- the new structure-tab field puts the same scan on every profile view,
-- which is why the security review flagged it as a DoS multiplier.
--
-- Why partial: skip rows where `identifier` is NULL — natural-person
-- shareholders, foreign entities without a CBE, etc. Roughly halves the
-- index size at zero cost (the WHERE clause matches the query: we only
-- look up by identifier when we have one).
--
-- Why CONCURRENTLY: this runs on the shared prod DB (staging + prod
-- share Postgres). Without CONCURRENTLY the build would lock the table
-- for the duration of the build and block writes from the daily NBB
-- loader.
--
-- Estimated build time: 30-60 s (table is small relative to `address`).
-- Estimated storage: a few MB.
--
-- Run:
--   psql $DATABASE_URL -f migrations/2026-04-28_pi_identifier_index.sql
--
-- Verify after:
--   SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
--     FROM pg_indexes WHERE indexname = 'idx_pi_identifier';
--   EXPLAIN ANALYZE
--     SELECT * FROM participating_interest WHERE identifier = '0878290854';
--   -- Expected: Index Scan using idx_pi_identifier.
--
-- Rollback: see _rollback.sql sibling file.
-- ----------------------------------------------------------------------------

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pi_identifier
  ON participating_interest(identifier)
  WHERE identifier IS NOT NULL;
