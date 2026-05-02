-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=30min

-- Week-2 FTS track: trade-name expression GIN index for FTS primary path.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_denom_tsv
    ON denomination USING GIN (to_tsvector('simple', denomination_normalized));
