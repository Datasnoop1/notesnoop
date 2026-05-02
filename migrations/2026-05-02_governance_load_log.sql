-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Durable retry log for NBB governance extraction.
CREATE TABLE IF NOT EXISTS governance_load_log (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,
    status              TEXT NOT NULL,
    attempts            INT NOT NULL DEFAULT 0,
    last_error          TEXT,
    counts_json         JSONB,
    last_attempt_at     TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (enterprise_number, deposit_key),
    CONSTRAINT governance_load_log_status_check
        CHECK (status IN ('ok', 'error')),
    CONSTRAINT governance_load_log_attempts_check
        CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_governance_load_retry
    ON governance_load_log(status, next_retry_at)
    WHERE status = 'error';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON governance_load_log TO leadpeek';
    END IF;
END $$;
