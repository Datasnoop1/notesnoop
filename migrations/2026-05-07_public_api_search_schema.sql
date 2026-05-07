-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Public API search-endpoint schema. Adds:
--   - api_keys.scopes  TEXT[]   per-key permission set
--   - api_keys CHECKs            non-empty + known-vocabulary
--   - api_call_log.cost INTEGER  for weighted daily-cap accounting
--
-- See docs/public-api-search-plan.md.
--
-- The CONCURRENTLY index creates live in the sibling migration
--   2026-05-07_public_api_search_indexes.sql
-- which runs in no-tx mode. The two are ordered by filename so
-- migrate.py runs the schema first, indexes second.
--
-- Operator runbook:
--   - api_keys is tiny (~4 rows) so the ALTER takes microseconds.
--   - api_call_log can be large; the new column uses a non-volatile
--     DEFAULT (synthesised on read in PG ≥ 11) so the ALTER is
--     fast and lock-light. No table rewrite.

-- ---------------------------------------------------------------------------
-- 1. api_keys.scopes
-- ---------------------------------------------------------------------------

ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT ARRAY['lookup'];

-- Defensive backfill: existing rows get the DEFAULT during ADD COLUMN, but
-- be explicit so a future audit doesn't have to reason about which PG
-- version it ran on.
UPDATE api_keys
   SET scopes = ARRAY['lookup']
 WHERE scopes IS NULL OR cardinality(scopes) = 0;

-- Reject empty scope arrays. `cardinality()` returns 0 for empty arrays
-- (as opposed to `array_length()` which returns NULL — and NULL >= 1 is
-- UNKNOWN, which the planner treats as not-violated, defeating the CHECK).
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_not_empty;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_not_empty
  CHECK (cardinality(scopes) >= 1);

-- Reject typos / unknown scope names. The vocabulary lives in code AND
-- here; both must be updated together when adding a new scope.
ALTER TABLE api_keys
  DROP CONSTRAINT IF EXISTS api_keys_scopes_known;
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_known
  CHECK (scopes <@ ARRAY['lookup','search']::TEXT[]);

-- ---------------------------------------------------------------------------
-- 2. api_call_log.cost (weighted daily cap)
-- ---------------------------------------------------------------------------

-- PG ≥ 11 stores a non-volatile DEFAULT in pg_attrdef and synthesises
-- it on read for rows written before the column existed — no table
-- rewrite, no separate UPDATE needed. Existing rows logically read as
-- cost = 1 immediately after migration, so the cap math is consistent
-- from the moment this transaction commits.
ALTER TABLE api_call_log
  ADD COLUMN IF NOT EXISTS cost INTEGER NOT NULL DEFAULT 1;
