-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/public_api.py.

CREATE TABLE IF NOT EXISTS api_keys (
    id          SERIAL PRIMARY KEY,
    key_hash    TEXT NOT NULL UNIQUE,
    key_prefix  TEXT NOT NULL,
    label       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at TIMESTAMPTZ,
    daily_cap   INTEGER NOT NULL DEFAULT 10000,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash
    ON api_keys(key_hash);

CREATE TABLE IF NOT EXISTS api_call_log (
    id          BIGSERIAL PRIMARY KEY,
    api_key_id  INTEGER NOT NULL REFERENCES api_keys(id),
    vat_queried TEXT,
    endpoint    TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_call_log_key_date
    ON api_call_log(api_key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_call_log_date
    ON api_call_log(created_at DESC);
