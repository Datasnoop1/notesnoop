-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/enrichment_queue.py.

CREATE TABLE IF NOT EXISTS enrichment_job (
    enterprise_number   VARCHAR(10) PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'queued',
    priority            INTEGER NOT NULL DEFAULT 0,
    attempts            INTEGER NOT NULL DEFAULT 0,
    claimed_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    last_error          TEXT,
    enqueued_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_enrichment_job_status
    ON enrichment_job(status, priority DESC, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_job_finished
    ON enrichment_job(finished_at DESC);
