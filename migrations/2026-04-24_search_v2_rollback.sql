-- =======================================================================
-- Rollback of DataSnoop search V2 migration.
-- Safe to run if the V2 code has been reverted. If the V2 code is live,
-- DO NOT run this — the new routers depend on these columns/functions.
-- =======================================================================

BEGIN;

DROP TABLE IF EXISTS company_popularity;
DROP TABLE IF EXISTS legal_form_synonyms;
DROP TABLE IF EXISTS juridical_form_category;

ALTER TABLE denomination DROP COLUMN IF EXISTS denomination_normalized;

ALTER TABLE staatsblad_event
  DROP COLUMN IF EXISTS person_name_normalized,
  DROP COLUMN IF EXISTS person_name_reversed,
  DROP COLUMN IF EXISTS person_name_phonetic;

ALTER TABLE shareholder
  DROP COLUMN IF EXISTS name_normalized,
  DROP COLUMN IF EXISTS name_reversed,
  DROP COLUMN IF EXISTS name_phonetic;

ALTER TABLE administrator
  DROP COLUMN IF EXISTS name_normalized,
  DROP COLUMN IF EXISTS name_reversed,
  DROP COLUMN IF EXISTS name_phonetic;

-- Restore the pre-V2 plain-text name_normalized on company_info so the
-- legacy `backend/db.py::ensure_trgm_setup` path still works.
DROP INDEX IF EXISTS idx_ci_name_norm_prefix;
DROP INDEX IF EXISTS idx_ci_name_norm_trgm;

ALTER TABLE company_info DROP COLUMN IF EXISTS name_normalized;
ALTER TABLE company_info ADD COLUMN name_normalized text;

CREATE INDEX IF NOT EXISTS idx_ci_name_trgm
  ON company_info USING GIN (name_normalized gin_trgm_ops);

UPDATE company_info
SET name_normalized = TRIM(REGEXP_REPLACE(
  LOWER(REGEXP_REPLACE(
    name,
    '\s*(NV|SA|BVBA|SRL|SPRL|BV|CVBA|SCRL|VOF|SNC|SE|COMM\.?\s*V|SCS|GCV|ASBL|VZW|AISBL|IVZW)\s*$',
    '', 'gi'
  )),
  '\s+', ' ', 'g'
))
WHERE name IS NOT NULL;

DROP FUNCTION IF EXISTS search_phonetic_key(text);
DROP FUNCTION IF EXISTS search_name_reversed(text);
DROP FUNCTION IF EXISTS search_normalize(text);
DROP FUNCTION IF EXISTS f_unaccent(text);

COMMIT;
