-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by scripts/issue_api_key.py. The
-- public-api router migration owns the same table too; this duplicate
-- idempotent create preserves the one-migration-per-inventory-entry shape.

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
