-- Migration: trigram indexes on address.street_* / municipality_* (REGO only)
-- ----------------------------------------------------------------------------
-- Why: company search's address-fallback arm (`backend/routers/companies/
-- search.py:348-360`) does ILIKE on a 3M-row address table without a
-- trigram index, which produces a sequential scan and a documented 1-2 s
-- floor on address-typed queries (e.g. "Rue Neuve"). GIN trigram indexes
-- on street_nl / street_fr / municipality_nl / municipality_fr drop that
-- floor to ~50-200 ms.
--
-- Why partial: the existing search arm filters on `type_of_address = 'REGO'`
-- (registered office), so the index only needs to cover REGO rows. That
-- shrinks the index from ~3M rows to ~1.7M and saves ~50% of the storage.
--
-- Why CONCURRENTLY: this runs on a live shared DB (staging + prod see the
-- same Postgres). Without CONCURRENTLY each `CREATE INDEX` would lock the
-- table for ~5-10 min, blocking writes and breaking the daily KBO loader.
--
-- Estimated build time: 3-6 min per index, run sequentially, ~20 min total.
-- Estimated storage: ~50 MB total.
--
-- Run order (psql, one at a time so a failure on a later index doesn't
-- stop the earlier ones being built):
--   psql $DATABASE_URL -f migrations/2026-04-26_address_trgm.sql
--
-- Verify after:
--   SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
--     FROM pg_indexes WHERE indexname LIKE 'idx_address_%_trgm';
--
-- Rollback: drop the four indexes (see _rollback.sql sibling file).
-- ----------------------------------------------------------------------------

-- pg_trgm extension should already be enabled (search V2 migration created
-- it), but IF NOT EXISTS keeps this idempotent for fresh environments.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Each index is in its own statement so a transient failure (e.g. lock
-- contention on a single column) only loses that one index, not the batch.
-- CONCURRENTLY cannot run inside a transaction block; psql's autocommit
-- mode handles each statement independently.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_street_nl_trgm
  ON address USING GIN (street_nl gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_street_fr_trgm
  ON address USING GIN (street_fr gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_municipality_nl_trgm
  ON address USING GIN (municipality_nl gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_municipality_fr_trgm
  ON address USING GIN (municipality_fr gin_trgm_ops)
  WHERE type_of_address = 'REGO';

-- Post-migration check (run manually):
--   EXPLAIN ANALYZE
--     SELECT * FROM address
--      WHERE type_of_address = 'REGO'
--        AND street_nl ILIKE '%rue neuve%';
-- Expected: Bitmap Index Scan on idx_address_street_nl_trgm.
