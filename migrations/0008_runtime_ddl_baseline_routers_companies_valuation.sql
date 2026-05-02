-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/companies/valuation.py.

CREATE TABLE IF NOT EXISTS vlerick_multiple (
    source       TEXT NOT NULL DEFAULT 'vlerick',
    year         INTEGER NOT NULL,
    bucket_type  TEXT NOT NULL,
    bucket_key   TEXT NOT NULL,
    multiple     REAL NOT NULL,
    source_note  TEXT,
    CONSTRAINT vlerick_multiple_multi_pkey
        PRIMARY KEY (source, year, bucket_type, bucket_key)
);

ALTER TABLE vlerick_multiple
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'vlerick';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'vlerick_multiple_multi_pkey'
           AND conrelid = 'vlerick_multiple'::regclass
    ) THEN
        ALTER TABLE vlerick_multiple DROP CONSTRAINT IF EXISTS vlerick_multiple_pkey;
        ALTER TABLE vlerick_multiple ADD CONSTRAINT vlerick_multiple_multi_pkey
            PRIMARY KEY (source, year, bucket_type, bucket_key);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (
    nace_prefix     TEXT PRIMARY KEY,
    vlerick_sector  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_enrichment (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    summary           TEXT,
    generated_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE company_enrichment
    ADD COLUMN IF NOT EXISTS vlerick_sector              TEXT,
    ADD COLUMN IF NOT EXISTS vlerick_sector_confidence   TEXT,
    ADD COLUMN IF NOT EXISTS vlerick_sector_reasoning    TEXT,
    ADD COLUMN IF NOT EXISTS vlerick_sector_generated_at TIMESTAMP;
