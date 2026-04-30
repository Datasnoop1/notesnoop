-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by scripts/seed_vlerick.py. The
-- valuation router migration owns the same tables too; this duplicate
-- idempotent create preserves the one-migration-per-inventory-entry shape.

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
