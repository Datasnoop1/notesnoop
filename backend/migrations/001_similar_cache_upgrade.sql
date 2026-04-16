-- Upgrade ai_similar_cache to support content-hash invalidation, per-focus caching,
-- and the richer re-rank fields introduced by the rewrite of /api/companies/{cbe}/similar/ai.
--
-- Idempotent. Safe to run on every startup; the ensure_similar_cache_schema()
-- helper in backend/similar_cache.py runs an equivalent set of statements lazily
-- on the first call to the endpoint, so ops never has to remember to run this
-- file. It exists primarily as a written record of the schema change.

CREATE TABLE IF NOT EXISTS ai_similar_cache (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    ranked_cbes TEXT,
    reasons TEXT,
    generated_at TIMESTAMP DEFAULT NOW()
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
