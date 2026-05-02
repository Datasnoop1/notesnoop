-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures schema DDL formerly owned by scripts/migrate_phase_5_0.py.

CREATE TABLE IF NOT EXISTS company_enrichment (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    summary           TEXT,
    generated_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE company_enrichment
    ADD COLUMN IF NOT EXISTS unified_summary      JSONB,
    ADD COLUMN IF NOT EXISTS quality_tier         TEXT,
    ADD COLUMN IF NOT EXISTS quality_tier_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS model_chain          JSONB,
    ADD COLUMN IF NOT EXISTS bulk_website_text    TEXT,
    ADD COLUMN IF NOT EXISTS bulk_website_text_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'enrichment_quality_tier_check'
           AND conrelid = 'company_enrichment'::regclass
    ) THEN
        ALTER TABLE company_enrichment
            ADD CONSTRAINT enrichment_quality_tier_check
            CHECK (
                quality_tier IS NULL OR quality_tier IN (
                    'bulk_only',
                    'bulk_escalated',
                    'narrative_lite',
                    'narrative_full'
                )
            ) NOT VALID;
        ALTER TABLE company_enrichment
            VALIDATE CONSTRAINT enrichment_quality_tier_check;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_enrichment_quality_tier
    ON company_enrichment (quality_tier, quality_tier_at);

CREATE OR REPLACE FUNCTION try_parse_jsonb(t text) RETURNS jsonb AS $$
BEGIN
    RETURN t::jsonb;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
