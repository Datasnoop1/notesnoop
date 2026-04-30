-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/similar_cache.py and the
-- ad-hoc backend/migrations/001_similar_cache_upgrade.sql record.

CREATE TABLE IF NOT EXISTS ai_similar_cache (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    ranked_cbes       TEXT,
    reasons           TEXT,
    generated_at      TIMESTAMP DEFAULT NOW(),
    content_hash      TEXT,
    focus             TEXT NOT NULL DEFAULT 'activity',
    match_scores      TEXT,
    provenance        TEXT,
    signals           TEXT,
    model_used        TEXT
);
ALTER TABLE ai_similar_cache
    ADD COLUMN IF NOT EXISTS content_hash TEXT,
    ADD COLUMN IF NOT EXISTS focus TEXT NOT NULL DEFAULT 'activity',
    ADD COLUMN IF NOT EXISTS match_scores TEXT,
    ADD COLUMN IF NOT EXISTS provenance TEXT,
    ADD COLUMN IF NOT EXISTS signals TEXT,
    ADD COLUMN IF NOT EXISTS model_used TEXT;
CREATE INDEX IF NOT EXISTS ai_similar_cache_hash_idx
    ON ai_similar_cache (enterprise_number, focus, content_hash);
