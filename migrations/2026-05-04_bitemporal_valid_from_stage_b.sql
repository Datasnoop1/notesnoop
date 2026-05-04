-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=1800s

-- Bitemporal valid_from Stage B: Staatsblad supremacy.
--
-- Scope guardrails:
--   - Fill valid_from only for Staatsblad-sourced rows whose valid_from is NULL.
--   - Close valid_to only for older NBB-sourced rows whose valid_to is NULL.
--   - Do not add provenance, tighten valid_from nullability, or rewrite
--     existing non-NULL valid_from / valid_to values.

CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_b_try_date(raw TEXT)
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

CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_b_pub_reference(deposit_key TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN deposit_key LIKE 'sb\_%' ESCAPE '\'
            THEN NULLIF(substring(deposit_key FROM 4), '')
        ELSE NULL
    END
$$;

CREATE TEMP TABLE _bt_vf_stage_b_enterprise_start ON COMMIT DROP AS
SELECT enterprise_number,
       pg_temp._bt_vf_stage_b_try_date(start_date) AS start_date
FROM enterprise;

CREATE INDEX _bt_vf_stage_b_enterprise_start_key
    ON _bt_vf_stage_b_enterprise_start(enterprise_number);

CREATE TEMP TABLE _bt_vf_stage_b_events ON COMMIT DROP AS
WITH parsed AS (
    SELECT ev.id,
           ev.enterprise_number,
           ev.pub_reference,
           ev.event_type,
           lower(COALESCE(ev.sub_type, '')) AS sub_type,
           COALESCE(ev.event_date, ev.pub_date) AS effective_date,
           ev.person_name,
           ev.person_role,
           ev.entity_name,
           es.start_date AS enterprise_start
    FROM staatsblad_event ev
    LEFT JOIN _bt_vf_stage_b_enterprise_start es
      ON es.enterprise_number = ev.enterprise_number
)
SELECT id,
       enterprise_number,
       pub_reference,
       event_type,
       sub_type,
       effective_date,
       search_normalize(COALESCE(person_name, '')) AS person_name_key,
       search_normalize(COALESCE(entity_name, '')) AS entity_name_key,
       search_normalize(COALESCE(person_role, '')) AS person_role_key
FROM parsed
WHERE effective_date IS NOT NULL
  AND effective_date <= CURRENT_DATE
  AND (enterprise_start IS NULL OR effective_date >= enterprise_start);

CREATE INDEX _bt_vf_stage_b_events_ref_key
    ON _bt_vf_stage_b_events(enterprise_number, pub_reference);
CREATE INDEX _bt_vf_stage_b_events_type_key
    ON _bt_vf_stage_b_events(enterprise_number, event_type, sub_type, effective_date);

-- B1: fill Staatsblad-sourced valid_from rows from the matching event.

CREATE TEMP TABLE _bt_vf_stage_b_admin_valid_from ON COMMIT DROP AS
SELECT DISTINCT ON (a.ctid)
       a.ctid AS row_ctid,
       ev.effective_date
FROM administrator a
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = a.enterprise_number
 AND ev.pub_reference = pg_temp._bt_vf_stage_b_pub_reference(a.deposit_key)
WHERE a.valid_from IS NULL
  AND a.deposit_key LIKE 'sb\_%' ESCAPE '\'
  AND ev.event_type = 'admin_event'
  AND (ev.sub_type IN ('appointment', 'reappointment', 'renewal') OR ev.sub_type = '')
  AND search_normalize(COALESCE(a.name, '')) <> ''
  AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
  AND search_normalize(COALESCE(a.name, '')) IN (ev.person_name_key, ev.entity_name_key)
  AND (
      ev.person_role_key = ''
      OR search_normalize(COALESCE(a.role, '')) = ev.person_role_key
  )
ORDER BY a.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_admin_valid_from_ctid
    ON _bt_vf_stage_b_admin_valid_from(row_ctid);

UPDATE administrator a
SET valid_from = c.effective_date
FROM _bt_vf_stage_b_admin_valid_from c
WHERE a.valid_from IS NULL
  AND a.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_shareholder_valid_from ON COMMIT DROP AS
SELECT DISTINCT ON (sh.ctid)
       sh.ctid AS row_ctid,
       ev.effective_date
FROM shareholder sh
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = sh.enterprise_number
 AND ev.pub_reference = pg_temp._bt_vf_stage_b_pub_reference(sh.deposit_key)
WHERE sh.valid_from IS NULL
  AND sh.deposit_key LIKE 'sb\_%' ESCAPE '\'
  AND ev.event_type IN ('share_transfer', 'ownership_change')
  AND search_normalize(COALESCE(sh.name, '')) <> ''
  AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
  AND search_normalize(COALESCE(sh.name, '')) IN (ev.person_name_key, ev.entity_name_key)
ORDER BY sh.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_shareholder_valid_from_ctid
    ON _bt_vf_stage_b_shareholder_valid_from(row_ctid);

UPDATE shareholder sh
SET valid_from = c.effective_date
FROM _bt_vf_stage_b_shareholder_valid_from c
WHERE sh.valid_from IS NULL
  AND sh.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_pi_valid_from ON COMMIT DROP AS
SELECT DISTINCT ON (pi.ctid)
       pi.ctid AS row_ctid,
       ev.effective_date
FROM participating_interest pi
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = pi.enterprise_number
 AND ev.pub_reference = pg_temp._bt_vf_stage_b_pub_reference(pi.deposit_key)
WHERE pi.valid_from IS NULL
  AND pi.deposit_key LIKE 'sb\_%' ESCAPE '\'
  AND ev.event_type IN ('share_transfer', 'ownership_change', 'ma_event')
  AND search_normalize(COALESCE(pi.name, '')) <> ''
  AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
  AND search_normalize(COALESCE(pi.name, '')) IN (ev.person_name_key, ev.entity_name_key)
ORDER BY pi.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_pi_valid_from_ctid
    ON _bt_vf_stage_b_pi_valid_from(row_ctid);

UPDATE participating_interest pi
SET valid_from = c.effective_date
FROM _bt_vf_stage_b_pi_valid_from c
WHERE pi.valid_from IS NULL
  AND pi.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_affiliation_valid_from ON COMMIT DROP AS
SELECT DISTINCT ON (af.ctid)
       af.ctid AS row_ctid,
       ev.effective_date
FROM affiliation af
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = af.via_enterprise_number
 AND ev.pub_reference = pg_temp._bt_vf_stage_b_pub_reference(af.via_deposit_key)
WHERE af.valid_from IS NULL
  AND af.via_deposit_key LIKE 'sb\_%' ESCAPE '\'
  AND ev.event_type = 'admin_event'
  AND af.affiliation_type = 'represents_admin'
  AND search_normalize(COALESCE(af.person_name, '')) <> ''
  AND ev.person_name_key <> ''
  AND search_normalize(COALESCE(af.person_name, '')) = ev.person_name_key
ORDER BY af.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_affiliation_valid_from_ctid
    ON _bt_vf_stage_b_affiliation_valid_from(row_ctid);

UPDATE affiliation af
SET valid_from = c.effective_date
FROM _bt_vf_stage_b_affiliation_valid_from c
WHERE af.valid_from IS NULL
  AND af.ctid = c.row_ctid;

-- B2: close older NBB rows when a later Staatsblad event supersedes them.

CREATE TEMP TABLE _bt_vf_stage_b_admin_valid_to ON COMMIT DROP AS
SELECT DISTINCT ON (a.ctid)
       a.ctid AS row_ctid,
       ev.effective_date
FROM administrator a
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = a.enterprise_number
WHERE a.valid_to IS NULL
  AND a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND a.source_deposit_date IS NOT NULL
  AND ev.effective_date > a.source_deposit_date
  AND ev.event_type = 'admin_event'
  AND ev.sub_type IN ('resign', 'resignation', 'end', 'termination', 'dismissal', 'removal')
  AND search_normalize(COALESCE(a.name, '')) <> ''
  AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
  AND search_normalize(COALESCE(a.name, '')) IN (ev.person_name_key, ev.entity_name_key)
  AND (
      ev.person_role_key = ''
      OR search_normalize(COALESCE(a.role, '')) = ev.person_role_key
  )
ORDER BY a.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_admin_valid_to_ctid
    ON _bt_vf_stage_b_admin_valid_to(row_ctid);

UPDATE administrator a
SET valid_to = c.effective_date
FROM _bt_vf_stage_b_admin_valid_to c
WHERE a.valid_to IS NULL
  AND a.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_shareholder_valid_to ON COMMIT DROP AS
SELECT DISTINCT ON (sh.ctid)
       sh.ctid AS row_ctid,
       ev.effective_date
FROM shareholder sh
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = sh.enterprise_number
WHERE sh.valid_to IS NULL
  AND sh.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND sh.source_deposit_date IS NOT NULL
  AND ev.effective_date > sh.source_deposit_date
  AND ev.event_type = 'share_transfer'
  AND (ev.sub_type = '' OR ev.sub_type = 'transfer')
  AND ev.person_name_key <> ''
  AND search_normalize(COALESCE(sh.name, '')) <> ''
  AND search_normalize(COALESCE(sh.name, '')) = ev.person_name_key
ORDER BY sh.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_shareholder_valid_to_ctid
    ON _bt_vf_stage_b_shareholder_valid_to(row_ctid);

UPDATE shareholder sh
SET valid_to = c.effective_date
FROM _bt_vf_stage_b_shareholder_valid_to c
WHERE sh.valid_to IS NULL
  AND sh.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_pi_valid_to ON COMMIT DROP AS
SELECT DISTINCT ON (pi.ctid)
       pi.ctid AS row_ctid,
       ev.effective_date
FROM participating_interest pi
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = pi.enterprise_number
WHERE pi.valid_to IS NULL
  AND pi.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND pi.source_deposit_date IS NOT NULL
  AND ev.effective_date > pi.source_deposit_date
  AND (
      (
          ev.event_type = 'share_transfer'
          AND (ev.sub_type = '' OR ev.sub_type = 'transfer')
          AND ev.person_name_key <> ''
          AND search_normalize(COALESCE(pi.name, '')) <> ''
          AND search_normalize(COALESCE(pi.name, '')) = ev.person_name_key
      )
      OR (
          ev.event_type = 'ma_event'
          AND ev.entity_name_key <> ''
          AND search_normalize(COALESCE(pi.name, '')) <> ''
          AND search_normalize(COALESCE(pi.name, '')) = ev.entity_name_key
      )
  )
ORDER BY pi.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_pi_valid_to_ctid
    ON _bt_vf_stage_b_pi_valid_to(row_ctid);

UPDATE participating_interest pi
SET valid_to = c.effective_date
FROM _bt_vf_stage_b_pi_valid_to c
WHERE pi.valid_to IS NULL
  AND pi.ctid = c.row_ctid;

CREATE TEMP TABLE _bt_vf_stage_b_affiliation_valid_to ON COMMIT DROP AS
SELECT DISTINCT ON (af.ctid)
       af.ctid AS row_ctid,
       ev.effective_date
FROM affiliation af
JOIN _bt_vf_stage_b_events ev
  ON ev.enterprise_number = af.enterprise_number
WHERE af.valid_to IS NULL
  AND af.via_deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
  AND af.source_deposit_date IS NOT NULL
  AND ev.effective_date > af.source_deposit_date
  AND ev.event_type = 'admin_event'
  AND ev.sub_type IN ('resign', 'resignation', 'end', 'termination', 'dismissal', 'removal')
  AND af.affiliation_type = 'represents_admin'
  AND search_normalize(COALESCE(af.person_name, '')) <> ''
  AND ev.person_name_key <> ''
  AND search_normalize(COALESCE(af.person_name, '')) = ev.person_name_key
ORDER BY af.ctid, ev.effective_date ASC, ev.id ASC;

CREATE INDEX _bt_vf_stage_b_affiliation_valid_to_ctid
    ON _bt_vf_stage_b_affiliation_valid_to(row_ctid);

UPDATE affiliation af
SET valid_to = c.effective_date
FROM _bt_vf_stage_b_affiliation_valid_to c
WHERE af.valid_to IS NULL
  AND af.ctid = c.row_ctid;
