-- =======================================================================
-- DataSnoop affiliation migration — 2026-04-25
--
-- Captures a softer relationship than `administrator`: when Company A's
-- annual filing names a corporate director (Company B), and Company B
-- is represented by a natural person X, we record that X is "affiliated"
-- with Company B. X may or may not be a direct admin of Company B
-- elsewhere — the affiliation is a clue, not a mandate.
--
-- Idempotent. Safe to re-run.
--
-- Phasing rationale:
--   Phase 0 — create the table with the generated search columns.
--             On a fresh DB this is instant; on prod the table is empty
--             until the new extractor and/or backfill writes to it, so
--             generated columns cost nothing on existing data.
--   Phase 1 — GIN indexes for trigram + reversed + phonetic search.
--             Empty table → instant. Future re-runs are no-ops.
--
-- Run with: psql -v ON_ERROR_STOP=1 -f migrations/2026-04-25_affiliation.sql
-- DO NOT pass through `psql -1` (single-tx wrapper kills the per-phase split).
-- =======================================================================

-- -----------------------------------------------------------------------
-- Phase 0 — table
-- -----------------------------------------------------------------------
BEGIN;

CREATE TABLE IF NOT EXISTS affiliation (
    person_name             TEXT NOT NULL,
    -- Company B: the company Person X is affiliated with via representing
    -- a corporate director of Company A. Stored as 10-digit canonical CBE.
    enterprise_number       TEXT NOT NULL,
    -- Company A: the filing company where the link was observed.
    via_enterprise_number   TEXT NOT NULL,
    -- Source filing for provenance + dedup. Combined with company_a CBE
    -- this lets us tell "5 distinct filings mention this rep" from
    -- "1 filing mentions them 5 times".
    via_deposit_key         TEXT NOT NULL,
    fiscal_year             TEXT,
    -- Reserved enum: 'represents_admin' for now. Future weak-links
    -- ('frequent_co_director', 'shared_address', 'shared_email_domain')
    -- can land here without schema churn.
    affiliation_type        TEXT NOT NULL DEFAULT 'represents_admin',
    -- Optional: NBB exposes this rarely for natural persons; usually NULL.
    person_identifier       TEXT,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Generated search columns — mirror the administrator/shareholder
    -- pattern from migrations/2026-04-24_search_v2.sql so the people
    -- search arm can reuse the same query shape.
    name_normalized TEXT
        GENERATED ALWAYS AS (search_normalize(person_name)) STORED,
    name_reversed   TEXT
        GENERATED ALWAYS AS (search_name_reversed(person_name)) STORED,
    name_phonetic   TEXT
        GENERATED ALWAYS AS (search_phonetic_key(person_name)) STORED,
    PRIMARY KEY (person_name, enterprise_number, via_enterprise_number, affiliation_type)
);

-- Lookup index for the connections endpoint (people → companies).
CREATE INDEX IF NOT EXISTS idx_affiliation_person_lower
    ON affiliation (LOWER(person_name));

-- Lookup index for the company-side query: who is affiliated with X?
CREATE INDEX IF NOT EXISTS idx_affiliation_ent
    ON affiliation (enterprise_number);

-- Reverse lookup: which filings introduced this affiliation?
CREATE INDEX IF NOT EXISTS idx_affiliation_via_ent
    ON affiliation (via_enterprise_number);

-- ----------------------------------------------------------------
-- Backfill attempt log. Tracks (filing) tuples that the
-- backfill_affiliation.py script has already re-fetched, so we don't
-- waste NBB quota perpetually re-fetching filings whose legal-person
-- admins have no representatives (zero affiliation rows produced).
-- The forward extractor doesn't write here — only the backfill does.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS affiliation_backfill_log (
    via_enterprise_number   TEXT NOT NULL,
    via_deposit_key         TEXT NOT NULL,
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows_inserted           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (via_enterprise_number, via_deposit_key)
);

COMMIT;

-- -----------------------------------------------------------------------
-- Phase 1 — search GIN indexes (instant on empty table)
-- -----------------------------------------------------------------------
BEGIN;

CREATE INDEX IF NOT EXISTS idx_affiliation_name_norm_trgm
    ON affiliation USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_affiliation_name_rev_trgm
    ON affiliation USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_affiliation_name_phon_trgm
    ON affiliation USING GIN (name_phonetic gin_trgm_ops);

COMMIT;

ANALYZE affiliation;

-- -----------------------------------------------------------------------
-- Permissions for the application role.
-- -----------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON affiliation TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON affiliation_backfill_log TO leadpeek';
    END IF;
END $$;
