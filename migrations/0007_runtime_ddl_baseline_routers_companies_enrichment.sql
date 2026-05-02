-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/companies/enrichment.py.

CREATE TABLE IF NOT EXISTS company_enrichment (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    summary           TEXT,
    generated_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE company_enrichment
    ADD COLUMN IF NOT EXISTS website_summary     TEXT,
    ADD COLUMN IF NOT EXISTS linkedin_summary    TEXT,
    ADD COLUMN IF NOT EXISTS website_url         TEXT,
    ADD COLUMN IF NOT EXISTS ai_insights         TEXT,
    ADD COLUMN IF NOT EXISTS publication_summary TEXT,
    ADD COLUMN IF NOT EXISTS bulk_summary        JSONB,
    ADD COLUMN IF NOT EXISTS bulk_summary_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bulk_website_hash   TEXT,
    ADD COLUMN IF NOT EXISTS bulk_website_url    TEXT,
    ADD COLUMN IF NOT EXISTS bulk_confidence     TEXT;

CREATE TABLE IF NOT EXISTS ai_insights_feedback (
    id                 SERIAL PRIMARY KEY,
    enterprise_number  VARCHAR(10) NOT NULL,
    user_email         TEXT,
    overall            TEXT NOT NULL,
    website_correct    BOOLEAN,
    linkedin_correct   BOOLEAN,
    insight_correct    BOOLEAN,
    comment            TEXT,
    created_at         TIMESTAMP DEFAULT NOW()
);
