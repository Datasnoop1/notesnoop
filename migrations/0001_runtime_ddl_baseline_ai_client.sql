-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/ai_client.py.

CREATE TABLE IF NOT EXISTS translation_cache (
    cbe             TEXT NOT NULL,
    kind            TEXT NOT NULL,
    lang            TEXT NOT NULL,
    value           TEXT NOT NULL,
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cbe, kind, lang)
);
CREATE INDEX IF NOT EXISTS idx_translation_cache_gen
    ON translation_cache(generated_at);

CREATE TABLE IF NOT EXISTS llm_call_log (
    id                  SERIAL PRIMARY KEY,
    ts                  TIMESTAMP NOT NULL DEFAULT NOW(),
    endpoint            TEXT,
    model               TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    cost_usd            REAL
);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_ts
    ON llm_call_log(ts);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_endpoint
    ON llm_call_log(endpoint);
