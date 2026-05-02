-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by scripts/alert_digest.py.

CREATE TABLE IF NOT EXISTS user_digest_log (
    user_email   TEXT PRIMARY KEY,
    last_sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
    event_count  INTEGER NOT NULL DEFAULT 0
);
