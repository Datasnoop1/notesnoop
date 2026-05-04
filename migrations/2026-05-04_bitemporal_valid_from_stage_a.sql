-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=1800s

-- Bitemporal valid_from Stage A: fill residual NULL starts from the
-- earliest NBB filing that mentions the same governance fact.
--
-- Scope guardrails:
--   - This migration only updates rows where valid_from IS NULL.
--   - It does not add provenance columns, apply Staatsblad overrides, or
--     tighten valid_from to NOT NULL; those are later rollout stages.
--   - Administrator rows prefer an exact mandate_start from any matching
--     NBB filing. The filing-date upper-bound fallback comes from the
--     grouped earliest NBB mention across all filings for the same admin
--     fact, not from a direct current-row deposit-date shortcut.

CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_a_try_date(raw TEXT)
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
            RETURN parsed;
        END IF;
        RETURN NULL;
    END IF;

    RETURN NULL;
END
$$;

CREATE TEMP TABLE _bt_vf_stage_a_filing_dates ON COMMIT DROP AS
WITH parsed AS (
    SELECT enterprise_number,
           deposit_key,
           pg_temp._bt_vf_stage_a_try_date(deposit_date) AS deposit_date
    FROM financial_data
    WHERE deposit_date IS NOT NULL
)
SELECT enterprise_number,
       deposit_key,
       MIN(deposit_date) AS deposit_date
FROM parsed
WHERE deposit_date IS NOT NULL
  AND deposit_date <= CURRENT_DATE
GROUP BY enterprise_number, deposit_key;

CREATE INDEX _bt_vf_stage_a_filing_dates_key
    ON _bt_vf_stage_a_filing_dates(enterprise_number, deposit_key);

CREATE TEMP TABLE _bt_vf_stage_a_enterprise_start ON COMMIT DROP AS
SELECT enterprise_number,
       pg_temp._bt_vf_stage_a_try_date(start_date) AS start_date
FROM enterprise;

CREATE INDEX _bt_vf_stage_a_enterprise_start_key
    ON _bt_vf_stage_a_enterprise_start(enterprise_number);

CREATE TEMP TABLE _bt_vf_stage_a_admin_mandate_refs ON COMMIT DROP AS
WITH parsed AS (
    SELECT a.enterprise_number,
           search_normalize(a.name) AS name_key,
           a.role,
           es.start_date AS enterprise_start,
           pg_temp._bt_vf_stage_a_try_date(a.mandate_start) AS mandate_start_date
    FROM administrator a
    LEFT JOIN _bt_vf_stage_a_enterprise_start es
      ON es.enterprise_number = a.enterprise_number
    WHERE a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
)
SELECT enterprise_number,
       name_key,
       role,
       MIN(mandate_start_date) AS earliest_mandate_start
FROM parsed
WHERE mandate_start_date IS NOT NULL
  AND mandate_start_date <= CURRENT_DATE
  AND (enterprise_start IS NULL OR mandate_start_date >= enterprise_start)
GROUP BY enterprise_number, name_key, role;

CREATE INDEX _bt_vf_stage_a_admin_mandate_refs_key
    ON _bt_vf_stage_a_admin_mandate_refs(enterprise_number, name_key, role);

CREATE TEMP TABLE _bt_vf_stage_a_admin_filing_refs ON COMMIT DROP AS
WITH parsed AS (
    SELECT a.enterprise_number,
           search_normalize(a.name) AS name_key,
           a.role,
           a.deposit_key,
           COALESCE(fd.deposit_date, a.source_deposit_date) AS filing_date,
           es.start_date AS enterprise_start
    FROM administrator a
    LEFT JOIN _bt_vf_stage_a_filing_dates fd
      ON fd.enterprise_number = a.enterprise_number
     AND fd.deposit_key = a.deposit_key
    LEFT JOIN _bt_vf_stage_a_enterprise_start es
      ON es.enterprise_number = a.enterprise_number
    WHERE a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
),
bounded AS (
    SELECT enterprise_number,
           name_key,
           role,
           deposit_key,
           CASE
               WHEN filing_date IS NOT NULL
                AND filing_date <= CURRENT_DATE
                AND (enterprise_start IS NULL OR filing_date >= enterprise_start)
                   THEN filing_date
               ELSE NULL
           END AS filing_ref_date
    FROM parsed
)
SELECT DISTINCT ON (enterprise_number, name_key, role)
       enterprise_number,
       name_key,
       role,
       deposit_key AS earliest_filing_key,
       filing_ref_date AS earliest_filing_ref
FROM bounded
WHERE filing_ref_date IS NOT NULL
ORDER BY enterprise_number, name_key, role, filing_ref_date ASC, deposit_key ASC;

CREATE INDEX _bt_vf_stage_a_admin_filing_refs_key
    ON _bt_vf_stage_a_admin_filing_refs(enterprise_number, name_key, role);

CREATE TEMP TABLE _bt_vf_stage_a_admin_candidates ON COMMIT DROP AS
SELECT COALESCE(m.enterprise_number, f.enterprise_number) AS enterprise_number,
       COALESCE(m.name_key, f.name_key) AS name_key,
       COALESCE(m.role, f.role) AS role,
       m.earliest_mandate_start,
       f.earliest_filing_key,
       f.earliest_filing_ref
FROM _bt_vf_stage_a_admin_mandate_refs m
FULL JOIN _bt_vf_stage_a_admin_filing_refs f
  ON f.enterprise_number = m.enterprise_number
 AND f.name_key = m.name_key
 AND f.role = m.role;

CREATE INDEX _bt_vf_stage_a_admin_candidates_key
    ON _bt_vf_stage_a_admin_candidates(enterprise_number, name_key, role);

UPDATE administrator a
SET valid_from = COALESCE(c.earliest_mandate_start, c.earliest_filing_ref)
FROM _bt_vf_stage_a_admin_candidates c
WHERE a.valid_from IS NULL
  AND a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND a.enterprise_number = c.enterprise_number
  AND search_normalize(a.name) = c.name_key
  AND a.role = c.role
  AND COALESCE(c.earliest_mandate_start, c.earliest_filing_ref) IS NOT NULL;

CREATE TEMP TABLE _bt_vf_stage_a_shareholder_candidates ON COMMIT DROP AS
WITH parsed AS (
    SELECT sh.enterprise_number,
           search_normalize(sh.name) AS name_key,
           COALESCE(sh.identifier, '') AS identifier_key,
           COALESCE(sh.address, '') AS address_key,
           COALESCE(fd.deposit_date, sh.source_deposit_date) AS filing_date,
           es.start_date AS enterprise_start
    FROM shareholder sh
    LEFT JOIN _bt_vf_stage_a_filing_dates fd
      ON fd.enterprise_number = sh.enterprise_number
     AND fd.deposit_key = sh.deposit_key
    LEFT JOIN _bt_vf_stage_a_enterprise_start es
      ON es.enterprise_number = sh.enterprise_number
    WHERE sh.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
),
bounded AS (
    SELECT enterprise_number,
           name_key,
           identifier_key,
           address_key,
           CASE
               WHEN filing_date IS NOT NULL
                AND filing_date <= CURRENT_DATE
                AND (enterprise_start IS NULL OR filing_date >= enterprise_start)
                   THEN filing_date
               ELSE NULL
           END AS filing_ref_date
    FROM parsed
)
SELECT enterprise_number,
       name_key,
       identifier_key,
       address_key,
       MIN(filing_ref_date) AS earliest_filing_ref
FROM bounded
WHERE filing_ref_date IS NOT NULL
GROUP BY enterprise_number, name_key, identifier_key, address_key;

CREATE INDEX _bt_vf_stage_a_shareholder_candidates_key
    ON _bt_vf_stage_a_shareholder_candidates(
        enterprise_number,
        name_key,
        identifier_key,
        address_key
    );

UPDATE shareholder sh
SET valid_from = c.earliest_filing_ref
FROM _bt_vf_stage_a_shareholder_candidates c
WHERE sh.valid_from IS NULL
  AND sh.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND sh.enterprise_number = c.enterprise_number
  AND search_normalize(sh.name) = c.name_key
  AND COALESCE(sh.identifier, '') = c.identifier_key
  AND COALESCE(sh.address, '') = c.address_key;

CREATE TEMP TABLE _bt_vf_stage_a_pi_candidates ON COMMIT DROP AS
WITH parsed AS (
    SELECT pi.enterprise_number,
           search_normalize(pi.name) AS name_key,
           COALESCE(pi.identifier, '') AS identifier_key,
           COALESCE(pi.country, '') AS country_key,
           COALESCE(fd.deposit_date, pi.source_deposit_date) AS filing_date,
           es.start_date AS enterprise_start
    FROM participating_interest pi
    LEFT JOIN _bt_vf_stage_a_filing_dates fd
      ON fd.enterprise_number = pi.enterprise_number
     AND fd.deposit_key = pi.deposit_key
    LEFT JOIN _bt_vf_stage_a_enterprise_start es
      ON es.enterprise_number = pi.enterprise_number
    WHERE pi.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
),
bounded AS (
    SELECT enterprise_number,
           name_key,
           identifier_key,
           country_key,
           CASE
               WHEN filing_date IS NOT NULL
                AND filing_date <= CURRENT_DATE
                AND (enterprise_start IS NULL OR filing_date >= enterprise_start)
                   THEN filing_date
               ELSE NULL
           END AS filing_ref_date
    FROM parsed
)
SELECT enterprise_number,
       name_key,
       identifier_key,
       country_key,
       MIN(filing_ref_date) AS earliest_filing_ref
FROM bounded
WHERE filing_ref_date IS NOT NULL
GROUP BY enterprise_number, name_key, identifier_key, country_key;

CREATE INDEX _bt_vf_stage_a_pi_candidates_key
    ON _bt_vf_stage_a_pi_candidates(
        enterprise_number,
        name_key,
        identifier_key,
        country_key
    );

UPDATE participating_interest pi
SET valid_from = c.earliest_filing_ref
FROM _bt_vf_stage_a_pi_candidates c
WHERE pi.valid_from IS NULL
  AND pi.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND pi.enterprise_number = c.enterprise_number
  AND search_normalize(pi.name) = c.name_key
  AND COALESCE(pi.identifier, '') = c.identifier_key
  AND COALESCE(pi.country, '') = c.country_key;

CREATE TEMP TABLE _bt_vf_stage_a_affiliation_candidates ON COMMIT DROP AS
WITH parsed AS (
    SELECT af.enterprise_number,
           search_normalize(af.person_name) AS person_name_key,
           af.via_enterprise_number,
           af.affiliation_type,
           COALESCE(fd.deposit_date, af.source_deposit_date) AS filing_date,
           es.start_date AS enterprise_start
    FROM affiliation af
    LEFT JOIN _bt_vf_stage_a_filing_dates fd
      ON fd.enterprise_number = af.via_enterprise_number
     AND fd.deposit_key = af.via_deposit_key
    LEFT JOIN _bt_vf_stage_a_enterprise_start es
      ON es.enterprise_number = af.enterprise_number
    WHERE af.via_deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
),
bounded AS (
    SELECT enterprise_number,
           person_name_key,
           via_enterprise_number,
           affiliation_type,
           CASE
               WHEN filing_date IS NOT NULL
                AND filing_date <= CURRENT_DATE
                AND (enterprise_start IS NULL OR filing_date >= enterprise_start)
                   THEN filing_date
               ELSE NULL
           END AS filing_ref_date
    FROM parsed
)
SELECT enterprise_number,
       person_name_key,
       via_enterprise_number,
       affiliation_type,
       MIN(filing_ref_date) AS earliest_filing_ref
FROM bounded
WHERE filing_ref_date IS NOT NULL
GROUP BY enterprise_number, person_name_key, via_enterprise_number, affiliation_type;

CREATE INDEX _bt_vf_stage_a_affiliation_candidates_key
    ON _bt_vf_stage_a_affiliation_candidates(
        enterprise_number,
        person_name_key,
        via_enterprise_number,
        affiliation_type
    );

UPDATE affiliation af
SET valid_from = c.earliest_filing_ref
FROM _bt_vf_stage_a_affiliation_candidates c
WHERE af.valid_from IS NULL
  AND af.via_deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND af.enterprise_number = c.enterprise_number
  AND search_normalize(af.person_name) = c.person_name_key
  AND af.via_enterprise_number = c.via_enterprise_number
  AND af.affiliation_type = c.affiliation_type;
