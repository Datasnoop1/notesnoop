-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=600s

-- Bitemporal valid_from Stage D: enterprise-start fallback and NOT NULL tightening.
--
-- Operator runbook requirements:
--   - The pg_temp parser below must run in the same psql session as every
--     statement that calls it. scripts/migrate.py executes this migration as
--     one transaction/session, so keep this as one file.
--   - ADD CONSTRAINT ... NOT VALID and ALTER COLUMN ... SET NOT NULL take brief
--     AccessExclusive locks. If lock_timeout aborts, do not retry blind:
--     inspect pg_stat_activity for the blocking session, confirm governance
--     writers are still paused, then rerun the migration.
--   - Stage C C2 took 5m07s for one broad update. Stage D uses four smaller
--     fallback updates plus four full-table validation scans; statement_timeout
--     is 600s to give roughly 2x margin for the largest administrator scan.

CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_d_try_date(raw TEXT)
RETURNS DATE
LANGUAGE plpgsql
AS $$
DECLARE
    text_value TEXT := btrim(raw);
    parsed DATE;
BEGIN
    IF text_value IS NULL OR text_value = '' THEN
        RETURN NULL;
    END IF;

    IF text_value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        BEGIN
            parsed := text_value::date;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        IF to_char(parsed, 'YYYY-MM-DD') = text_value THEN
            IF parsed < DATE '1830-01-01' OR parsed > CURRENT_DATE THEN
                RETURN NULL;
            END IF;
            RETURN parsed;
        END IF;
        RETURN NULL;
    END IF;

    IF text_value ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN
        BEGIN
            parsed := to_date(text_value, 'DD/MM/YYYY');
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END;
        IF to_char(parsed, 'DD/MM/YYYY') = text_value THEN
            IF parsed < DATE '1830-01-01' OR parsed > CURRENT_DATE THEN
                RETURN NULL;
            END IF;
            RETURN parsed;
        END IF;
        RETURN NULL;
    END IF;

    RETURN NULL;
END
$$;

DO $$
BEGIN
    IF current_setting('server_version_num')::int < 120000 THEN
        RAISE EXCEPTION 'Stage D abort: PostgreSQL 12+ required for metadata-only SET NOT NULL after validated CHECK';
    END IF;
END
$$;

DO $$
DECLARE
    existing_backup_tables TEXT;
BEGIN
    SELECT string_agg(table_name, ', ' ORDER BY table_name)
    INTO existing_backup_tables
    FROM (
        VALUES
            ('_bt_vf_stage_d_backup_administrator'),
            ('_bt_vf_stage_d_backup_shareholder'),
            ('_bt_vf_stage_d_backup_participating_interest'),
            ('_bt_vf_stage_d_backup_affiliation')
    ) AS backups(table_name)
    WHERE to_regclass('public.' || table_name) IS NOT NULL;

    IF existing_backup_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Stage D abort: backup tables already exist: %', existing_backup_tables
            USING HINT = 'Do not reapply Stage D over old rollback snapshots. Preserve/rename them or run the day+7 cleanup only after the retention window.';
    END IF;
END
$$;

-- Block concurrent governance writes during snapshot + fallback fill. The
-- operator runbook pauses writers first; this lock is the in-transaction guard
-- that keeps the backup row image aligned with the UPDATE.
LOCK TABLE administrator, shareholder, participating_interest, affiliation
    IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE _bt_vf_stage_d_backup_administrator AS
SELECT a.enterprise_number,
       a.deposit_key,
       a.name,
       a.role,
       a.fiscal_year,
       a.person_type,
       a.identifier,
       a.mandate_start,
       a.mandate_end,
       a.representative_name,
       a.source_deposit_date,
       a.valid_from,
       a.valid_to,
       a.valid_from_provenance,
       a.valid_to_provenance,
       a.recorded_from,
       a.recorded_to,
       e.start_date AS enterprise_start_date_raw,
       pg_temp._bt_vf_stage_d_try_date(e.start_date) AS enterprise_start_date,
       CASE
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
            AND a.source_deposit_date IS NOT NULL
               THEN LEAST(pg_temp._bt_vf_stage_d_try_date(e.start_date), a.source_deposit_date)
           ELSE pg_temp._bt_vf_stage_d_try_date(e.start_date)
       END AS fallback_valid_from,
       (
           pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
           AND a.source_deposit_date IS NOT NULL
           AND pg_temp._bt_vf_stage_d_try_date(e.start_date) > a.source_deposit_date
       ) AS source_date_capped,
       now() AS backed_up_at
FROM administrator a
LEFT JOIN enterprise e
  ON e.enterprise_number = a.enterprise_number
WHERE a.valid_from IS NULL
  AND pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL;

CREATE TABLE _bt_vf_stage_d_backup_shareholder AS
SELECT sh.enterprise_number,
       sh.deposit_key,
       sh.name,
       sh.fiscal_year,
       sh.shareholder_type,
       sh.identifier,
       sh.address,
       sh.shares_held,
       sh.ownership_pct,
       sh.source_deposit_date,
       sh.valid_from,
       sh.valid_to,
       sh.valid_from_provenance,
       sh.valid_to_provenance,
       sh.recorded_from,
       sh.recorded_to,
       e.start_date AS enterprise_start_date_raw,
       pg_temp._bt_vf_stage_d_try_date(e.start_date) AS enterprise_start_date,
       CASE
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
            AND sh.source_deposit_date IS NOT NULL
               THEN LEAST(pg_temp._bt_vf_stage_d_try_date(e.start_date), sh.source_deposit_date)
           ELSE pg_temp._bt_vf_stage_d_try_date(e.start_date)
       END AS fallback_valid_from,
       (
           pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
           AND sh.source_deposit_date IS NOT NULL
           AND pg_temp._bt_vf_stage_d_try_date(e.start_date) > sh.source_deposit_date
       ) AS source_date_capped,
       now() AS backed_up_at
FROM shareholder sh
LEFT JOIN enterprise e
  ON e.enterprise_number = sh.enterprise_number
WHERE sh.valid_from IS NULL
  AND pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL;

CREATE TABLE _bt_vf_stage_d_backup_participating_interest AS
SELECT pi.enterprise_number,
       pi.deposit_key,
       pi.name,
       pi.fiscal_year,
       pi.identifier,
       pi.address,
       pi.country,
       pi.ownership_pct,
       pi.equity_value,
       pi.net_result,
       pi.source_deposit_date,
       pi.valid_from,
       pi.valid_to,
       pi.valid_from_provenance,
       pi.valid_to_provenance,
       pi.recorded_from,
       pi.recorded_to,
       e.start_date AS enterprise_start_date_raw,
       pg_temp._bt_vf_stage_d_try_date(e.start_date) AS enterprise_start_date,
       CASE
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
            AND pi.source_deposit_date IS NOT NULL
               THEN LEAST(pg_temp._bt_vf_stage_d_try_date(e.start_date), pi.source_deposit_date)
           ELSE pg_temp._bt_vf_stage_d_try_date(e.start_date)
       END AS fallback_valid_from,
       (
           pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
           AND pi.source_deposit_date IS NOT NULL
           AND pg_temp._bt_vf_stage_d_try_date(e.start_date) > pi.source_deposit_date
       ) AS source_date_capped,
       now() AS backed_up_at
FROM participating_interest pi
LEFT JOIN enterprise e
  ON e.enterprise_number = pi.enterprise_number
WHERE pi.valid_from IS NULL
  AND pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL;

CREATE TABLE _bt_vf_stage_d_backup_affiliation AS
SELECT af.person_name,
       af.enterprise_number,
       af.via_enterprise_number,
       af.affiliation_type,
       af.via_deposit_key,
       af.fiscal_year,
       af.person_identifier,
       af.first_seen_at,
       af.last_seen_at,
       af.source_deposit_date,
       af.valid_from,
       af.valid_to,
       af.valid_from_provenance,
       af.valid_to_provenance,
       af.recorded_from,
       af.recorded_to,
       e.start_date AS enterprise_start_date_raw,
       pg_temp._bt_vf_stage_d_try_date(e.start_date) AS enterprise_start_date,
       fd.deposit_date AS fallback_filing_deposit_date,
       af.recorded_from::date AS fallback_recorded_from_date,
       CASE
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
            AND af.source_deposit_date IS NOT NULL
               THEN LEAST(pg_temp._bt_vf_stage_d_try_date(e.start_date), af.source_deposit_date)
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
               THEN pg_temp._bt_vf_stage_d_try_date(e.start_date)
           WHEN fd.deposit_date IS NOT NULL
               THEN fd.deposit_date
           ELSE af.recorded_from::date
       END AS fallback_valid_from,
       CASE
           WHEN pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
               THEN 'fallback_enterprise_start'
           WHEN fd.deposit_date IS NOT NULL
               THEN 'fallback_filing_deposit'
           ELSE 'fallback_unknown_start'
       END AS fallback_provenance,
       (
           pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
           AND af.source_deposit_date IS NOT NULL
           AND pg_temp._bt_vf_stage_d_try_date(e.start_date) > af.source_deposit_date
       ) AS source_date_capped,
       now() AS backed_up_at
FROM affiliation af
LEFT JOIN enterprise e
  ON e.enterprise_number = af.enterprise_number
LEFT JOIN LATERAL (
    SELECT MIN(pg_temp._bt_vf_stage_d_try_date(fd.deposit_date::text)) AS deposit_date
    FROM financial_data fd
    WHERE fd.enterprise_number = af.via_enterprise_number
      AND fd.deposit_key = af.via_deposit_key
      AND pg_temp._bt_vf_stage_d_try_date(fd.deposit_date::text) IS NOT NULL
) fd
  ON true
WHERE af.valid_from IS NULL
  AND (
      pg_temp._bt_vf_stage_d_try_date(e.start_date) IS NOT NULL
      OR fd.deposit_date IS NOT NULL
      OR af.recorded_from::date BETWEEN DATE '1830-01-01' AND CURRENT_DATE
  );

UPDATE administrator a
SET valid_from = CASE
        WHEN b.enterprise_start_date IS NOT NULL
         AND a.source_deposit_date IS NOT NULL
            THEN LEAST(b.enterprise_start_date, a.source_deposit_date)
        ELSE b.enterprise_start_date
    END,
    valid_from_provenance = 'fallback_enterprise_start'
FROM _bt_vf_stage_d_backup_administrator b
WHERE a.valid_from IS NULL
  AND a.enterprise_number = b.enterprise_number
  AND a.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND a.name IS NOT DISTINCT FROM b.name
  AND a.role IS NOT DISTINCT FROM b.role
  AND b.enterprise_start_date IS NOT NULL;

UPDATE shareholder sh
SET valid_from = CASE
        WHEN b.enterprise_start_date IS NOT NULL
         AND sh.source_deposit_date IS NOT NULL
            THEN LEAST(b.enterprise_start_date, sh.source_deposit_date)
        ELSE b.enterprise_start_date
    END,
    valid_from_provenance = 'fallback_enterprise_start'
FROM _bt_vf_stage_d_backup_shareholder b
WHERE sh.valid_from IS NULL
  AND sh.enterprise_number = b.enterprise_number
  AND sh.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND sh.name IS NOT DISTINCT FROM b.name
  AND b.enterprise_start_date IS NOT NULL;

UPDATE participating_interest pi
SET valid_from = CASE
        WHEN b.enterprise_start_date IS NOT NULL
         AND pi.source_deposit_date IS NOT NULL
            THEN LEAST(b.enterprise_start_date, pi.source_deposit_date)
        ELSE b.enterprise_start_date
    END,
    valid_from_provenance = 'fallback_enterprise_start'
FROM _bt_vf_stage_d_backup_participating_interest b
WHERE pi.valid_from IS NULL
  AND pi.enterprise_number = b.enterprise_number
  AND pi.deposit_key IS NOT DISTINCT FROM b.deposit_key
  AND pi.name IS NOT DISTINCT FROM b.name
  AND b.enterprise_start_date IS NOT NULL;

UPDATE affiliation af
SET valid_from = CASE
        WHEN b.enterprise_start_date IS NOT NULL
         AND af.source_deposit_date IS NOT NULL
            THEN LEAST(b.enterprise_start_date, af.source_deposit_date)
        ELSE b.enterprise_start_date
    END,
    valid_from_provenance = 'fallback_enterprise_start'
FROM _bt_vf_stage_d_backup_affiliation b
WHERE af.valid_from IS NULL
  AND af.person_name = b.person_name
  AND af.enterprise_number = b.enterprise_number
  AND af.via_enterprise_number = b.via_enterprise_number
  AND af.affiliation_type = b.affiliation_type
  AND b.enterprise_start_date IS NOT NULL
  AND b.fallback_provenance = 'fallback_enterprise_start';

UPDATE affiliation af
SET valid_from = b.fallback_valid_from,
    valid_from_provenance = 'fallback_filing_deposit'
FROM _bt_vf_stage_d_backup_affiliation b
WHERE af.valid_from IS NULL
  AND af.person_name = b.person_name
  AND af.enterprise_number = b.enterprise_number
  AND af.via_enterprise_number = b.via_enterprise_number
  AND af.affiliation_type = b.affiliation_type
  AND b.fallback_provenance = 'fallback_filing_deposit'
  AND b.fallback_valid_from = b.fallback_filing_deposit_date
  AND b.fallback_valid_from BETWEEN DATE '1830-01-01' AND CURRENT_DATE;

UPDATE affiliation af
SET valid_from = b.fallback_valid_from,
    valid_from_provenance = 'fallback_unknown_start'
FROM _bt_vf_stage_d_backup_affiliation b
WHERE af.valid_from IS NULL
  AND af.person_name = b.person_name
  AND af.enterprise_number = b.enterprise_number
  AND af.via_enterprise_number = b.via_enterprise_number
  AND af.affiliation_type = b.affiliation_type
  AND b.fallback_provenance = 'fallback_unknown_start'
  AND b.fallback_valid_from = b.fallback_recorded_from_date
  AND b.fallback_valid_from BETWEEN DATE '1830-01-01' AND CURRENT_DATE;

DO $$
DECLARE
    administrator_nulls BIGINT;
    shareholder_nulls BIGINT;
    participating_interest_nulls BIGINT;
    affiliation_nulls BIGINT;
BEGIN
    SELECT COUNT(*) INTO administrator_nulls FROM administrator WHERE valid_from IS NULL;
    SELECT COUNT(*) INTO shareholder_nulls FROM shareholder WHERE valid_from IS NULL;
    SELECT COUNT(*) INTO participating_interest_nulls FROM participating_interest WHERE valid_from IS NULL;
    SELECT COUNT(*) INTO affiliation_nulls FROM affiliation WHERE valid_from IS NULL;

    IF administrator_nulls > 0
        OR shareholder_nulls > 0
        OR participating_interest_nulls > 0
        OR affiliation_nulls > 0
    THEN
        RAISE EXCEPTION 'Stage D abort: residual NULL valid_from rows remain'
            USING DETAIL = format(
                'administrator=%s shareholder=%s participating_interest=%s affiliation=%s',
                administrator_nulls,
                shareholder_nulls,
                participating_interest_nulls,
                affiliation_nulls
            );
    END IF;
END
$$;

ALTER TABLE administrator
    ADD CONSTRAINT administrator_valid_from_not_null
    CHECK (valid_from IS NOT NULL) NOT VALID;

ALTER TABLE shareholder
    ADD CONSTRAINT shareholder_valid_from_not_null
    CHECK (valid_from IS NOT NULL) NOT VALID;

ALTER TABLE participating_interest
    ADD CONSTRAINT participating_interest_valid_from_not_null
    CHECK (valid_from IS NOT NULL) NOT VALID;

ALTER TABLE affiliation
    ADD CONSTRAINT affiliation_valid_from_not_null
    CHECK (valid_from IS NOT NULL) NOT VALID;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM administrator WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM shareholder WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM participating_interest WHERE valid_from IS NULL
        UNION ALL SELECT 1 FROM affiliation WHERE valid_from IS NULL
        LIMIT 1
    ) THEN
        RAISE EXCEPTION 'Stage D abort: residual NULL valid_from rows remain before constraint validation';
    END IF;
END
$$;

ALTER TABLE administrator
    VALIDATE CONSTRAINT administrator_valid_from_not_null;

ALTER TABLE shareholder
    VALIDATE CONSTRAINT shareholder_valid_from_not_null;

ALTER TABLE participating_interest
    VALIDATE CONSTRAINT participating_interest_valid_from_not_null;

ALTER TABLE affiliation
    VALIDATE CONSTRAINT affiliation_valid_from_not_null;

ALTER TABLE administrator
    ALTER COLUMN valid_from SET NOT NULL;

ALTER TABLE shareholder
    ALTER COLUMN valid_from SET NOT NULL;

ALTER TABLE participating_interest
    ALTER COLUMN valid_from SET NOT NULL;

ALTER TABLE affiliation
    ALTER COLUMN valid_from SET NOT NULL;

CREATE OR REPLACE VIEW administrator_current AS
SELECT *
FROM administrator
WHERE valid_from <= CURRENT_DATE
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW shareholder_current AS
SELECT *
FROM shareholder
WHERE valid_from <= CURRENT_DATE
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW participating_interest_current AS
SELECT *
FROM participating_interest
WHERE valid_from <= CURRENT_DATE
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
  AND recorded_to IS NULL;

CREATE OR REPLACE VIEW affiliation_current AS
SELECT *
FROM affiliation
WHERE valid_from <= CURRENT_DATE
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
    WHERE valid_from <= valid_at
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
    WHERE valid_from <= valid_at
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
    WHERE valid_from <= valid_at
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
    WHERE valid_from <= valid_at
      AND (valid_to IS NULL OR valid_to > valid_at)
      AND recorded_from <= known_at
      AND (recorded_to IS NULL OR recorded_to > known_at)
$$;

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

COMMENT ON COLUMN administrator.valid_from_provenance IS 'Origin of valid_from: nbb_mandate_start, nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, fallback_enterprise_start, fallback_filing_deposit, fallback_unknown_start, or unknown.';
COMMENT ON COLUMN shareholder.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, fallback_enterprise_start, fallback_filing_deposit, fallback_unknown_start, or unknown.';
COMMENT ON COLUMN participating_interest.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, fallback_enterprise_start, fallback_filing_deposit, fallback_unknown_start, or unknown.';
COMMENT ON COLUMN affiliation.valid_from_provenance IS 'Origin of valid_from: nbb_filing_earliest, staatsblad_event_date, staatsblad_pub_date, nbb_loader_direct, staatsblad_consumer_direct, fallback_enterprise_start, fallback_filing_deposit, fallback_unknown_start, or unknown.';
