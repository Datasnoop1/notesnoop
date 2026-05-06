-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=600s

-- Manual rollback for Bitemporal valid_from Stage D.
-- scripts/migrate.py intentionally ignores files ending in _rollback.sql.
-- Apply only by explicit operator command after deciding whether to re-null
-- fallback rows and restore the NULL-aware read path together.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '600s';

ALTER TABLE administrator
    DROP CONSTRAINT IF EXISTS administrator_valid_from_not_null;
ALTER TABLE shareholder
    DROP CONSTRAINT IF EXISTS shareholder_valid_from_not_null;
ALTER TABLE participating_interest
    DROP CONSTRAINT IF EXISTS participating_interest_valid_from_not_null;
ALTER TABLE affiliation
    DROP CONSTRAINT IF EXISTS affiliation_valid_from_not_null;

ALTER TABLE administrator
    ALTER COLUMN valid_from DROP NOT NULL;
ALTER TABLE shareholder
    ALTER COLUMN valid_from DROP NOT NULL;
ALTER TABLE participating_interest
    ALTER COLUMN valid_from DROP NOT NULL;
ALTER TABLE affiliation
    ALTER COLUMN valid_from DROP NOT NULL;

CREATE OR REPLACE VIEW administrator_current AS
SELECT *
FROM administrator
WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW shareholder_current AS
SELECT *
FROM shareholder
WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW participating_interest_current AS
SELECT *
FROM participating_interest
WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW affiliation_current AS
SELECT *
FROM affiliation
WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE FUNCTION admins_as_of(
    valid_at DATE,
    known_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS SETOF administrator
LANGUAGE sql
STABLE
AS $$
    SELECT *
    FROM administrator
    WHERE (valid_from IS NULL OR valid_from <= valid_at)
      AND (valid_to IS NULL OR valid_to > valid_at)
      AND recorded_from <= known_at
      AND (recorded_to IS NULL OR recorded_to > known_at)
$$;

CREATE OR REPLACE FUNCTION shareholders_as_of(
    valid_at DATE,
    known_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS SETOF shareholder
LANGUAGE sql
STABLE
AS $$
    SELECT *
    FROM shareholder
    WHERE (valid_from IS NULL OR valid_from <= valid_at)
      AND (valid_to IS NULL OR valid_to > valid_at)
      AND recorded_from <= known_at
      AND (recorded_to IS NULL OR recorded_to > known_at)
$$;

CREATE OR REPLACE FUNCTION participating_interests_as_of(
    valid_at DATE,
    known_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS SETOF participating_interest
LANGUAGE sql
STABLE
AS $$
    SELECT *
    FROM participating_interest
    WHERE (valid_from IS NULL OR valid_from <= valid_at)
      AND (valid_to IS NULL OR valid_to > valid_at)
      AND recorded_from <= known_at
      AND (recorded_to IS NULL OR recorded_to > known_at)
$$;

CREATE OR REPLACE FUNCTION affiliations_as_of(
    valid_at DATE,
    known_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS SETOF affiliation
LANGUAGE sql
STABLE
AS $$
    SELECT *
    FROM affiliation
    WHERE (valid_from IS NULL OR valid_from <= valid_at)
      AND (valid_to IS NULL OR valid_to > valid_at)
      AND recorded_from <= known_at
      AND (recorded_to IS NULL OR recorded_to > known_at)
$$;

UPDATE administrator a
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_administrator b
WHERE a.enterprise_number = b.enterprise_number
  AND a.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND a.name IS NOT DISTINCT FROM b.name
  AND a.role IS NOT DISTINCT FROM b.role
  AND a.valid_from = b.fallback_valid_from
  AND a.valid_from_provenance = 'fallback_enterprise_start';

UPDATE shareholder sh
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_shareholder b
WHERE sh.enterprise_number = b.enterprise_number
  AND sh.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND sh.name IS NOT DISTINCT FROM b.name
  AND sh.valid_from = b.fallback_valid_from
  AND sh.valid_from_provenance = 'fallback_enterprise_start';

UPDATE participating_interest pi
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_participating_interest b
WHERE pi.enterprise_number = b.enterprise_number
  AND pi.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND pi.name IS NOT DISTINCT FROM b.name
  AND pi.valid_from = b.fallback_valid_from
  AND pi.valid_from_provenance = 'fallback_enterprise_start';

UPDATE affiliation af
SET valid_from = b.valid_from,
    valid_from_provenance = b.valid_from_provenance,
    valid_to = b.valid_to,
    valid_to_provenance = b.valid_to_provenance
FROM _bt_vf_stage_d_backup_affiliation b
WHERE af.person_name = b.person_name
  AND af.enterprise_number = b.enterprise_number
  AND af.via_enterprise_number = b.via_enterprise_number
  AND af.affiliation_type = b.affiliation_type
  AND af.valid_from = b.fallback_valid_from
  AND af.valid_from_provenance = b.fallback_provenance
  AND b.fallback_provenance IN (
      'fallback_enterprise_start',
      'fallback_filing_deposit',
      'fallback_unknown_start'
  );

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT ON administrator_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON shareholder_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON participating_interest_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON affiliation_current TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION admins_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION shareholders_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION participating_interests_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION affiliations_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
    END IF;
END
$$;

COMMENT ON COLUMN administrator.valid_from_provenance IS 'Origin of valid_from: nbb_mandate_start, nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN shareholder.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN participating_interest.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';
COMMENT ON COLUMN affiliation.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, or unknown.';

COMMIT;
