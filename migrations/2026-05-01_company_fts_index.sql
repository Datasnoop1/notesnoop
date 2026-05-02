-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=30min

-- Week-2 FTS track: expression GIN index, no generated column/table rewrite.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ci_name_tsv
    ON company_info USING GIN (to_tsvector('simple', name_normalized));
