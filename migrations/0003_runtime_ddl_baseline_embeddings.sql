-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=5min

-- Captures runtime DDL formerly owned by backend/embeddings.py.
-- Current production embedding columns are vector(1024), matching the
-- NVIDIA embedding path.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS company_embedding (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    embedding         vector(1024),
    model             VARCHAR(100),
    generated_at      TIMESTAMP DEFAULT NOW()
);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = 'public'
          AND c.relname = 'company_embedding'
          AND a.attname = 'embedding'
          AND format_type(a.atttypid, a.atttypmod) <> 'vector(1024)'
    ) THEN
        -- Derived semantic vectors can be regenerated. Clear rows before
        -- normalizing the vector dimension to the current embedding model.
        DROP INDEX IF EXISTS idx_ce_embedding_hnsw;
        TRUNCATE TABLE company_embedding;
        ALTER TABLE company_embedding
            ALTER COLUMN embedding TYPE vector(1024)
            USING embedding::vector(1024);
    END IF;
END$$;
CREATE INDEX IF NOT EXISTS idx_ce_embedding_hnsw
    ON company_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS query_embedding_cache (
    query_hash   TEXT PRIMARY KEY,
    query_text   TEXT NOT NULL,
    embedding    vector(1024) NOT NULL,
    model        TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = 'public'
          AND c.relname = 'query_embedding_cache'
          AND a.attname = 'embedding'
          AND format_type(a.atttypid, a.atttypmod) <> 'vector(1024)'
    ) THEN
        -- This table is a disposable cache. Clear rows before normalizing
        -- the vector dimension so replay/fallback environments converge.
        TRUNCATE TABLE query_embedding_cache;
        ALTER TABLE query_embedding_cache
            ALTER COLUMN embedding TYPE vector(1024)
            USING embedding::vector(1024);
    END IF;
END$$;
CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_created
    ON query_embedding_cache(created_at);
