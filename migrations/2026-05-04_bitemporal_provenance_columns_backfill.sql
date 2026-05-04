-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=1800s

-- Bitemporal provenance Stage C: best-effort retroactive metadata backfill.
--
-- Scope guardrails:
--   - Only writes valid_from_provenance / valid_to_provenance where those
--     provenance fields are NULL.
--   - Does not change valid_from, valid_to, or any NOT NULL constraint.
--   - Uses Stage A / Stage B backup tables when present to distinguish
--     migration-filled rows from pre-existing loader / consumer values.

CREATE OR REPLACE FUNCTION pg_temp._bt_prov_stage_c_try_date(raw TEXT)
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

CREATE OR REPLACE FUNCTION pg_temp._bt_prov_stage_c_pub_reference(deposit_key TEXT)
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

CREATE TEMP TABLE _bt_prov_stage_c_enterprise_start ON COMMIT DROP AS
SELECT enterprise_number,
       pg_temp._bt_prov_stage_c_try_date(start_date) AS start_date
FROM enterprise;

CREATE INDEX _bt_prov_stage_c_enterprise_start_key
    ON _bt_prov_stage_c_enterprise_start(enterprise_number);

CREATE TEMP TABLE _bt_prov_stage_c_admin_mandate_refs ON COMMIT DROP AS
WITH parsed AS (
    SELECT a.enterprise_number,
           search_normalize(a.name) AS name_key,
           a.role,
           es.start_date AS enterprise_start,
           pg_temp._bt_prov_stage_c_try_date(a.mandate_start) AS mandate_start_date
    FROM administrator a
    LEFT JOIN _bt_prov_stage_c_enterprise_start es
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

CREATE INDEX _bt_prov_stage_c_admin_mandate_refs_key
    ON _bt_prov_stage_c_admin_mandate_refs(enterprise_number, name_key, role);

CREATE TEMP TABLE _bt_prov_stage_c_events ON COMMIT DROP AS
WITH parsed AS (
    SELECT ev.id,
           ev.enterprise_number,
           ev.pub_reference,
           ev.event_type,
           lower(COALESCE(ev.sub_type, '')) AS sub_type,
           COALESCE(ev.event_date, ev.pub_date) AS effective_date,
           CASE
               WHEN ev.event_date IS NOT NULL THEN 'staatsblad_event_date'
               ELSE 'staatsblad_pub_date'
           END AS effective_provenance,
           ev.person_name,
           ev.person_role,
           ev.entity_name,
           es.start_date AS enterprise_start
    FROM staatsblad_event ev
    LEFT JOIN _bt_prov_stage_c_enterprise_start es
      ON es.enterprise_number = ev.enterprise_number
)
SELECT id,
       enterprise_number,
       pub_reference,
       event_type,
       sub_type,
       effective_date,
       effective_provenance,
       search_normalize(COALESCE(person_name, '')) AS person_name_key,
       search_normalize(COALESCE(entity_name, '')) AS entity_name_key,
       search_normalize(COALESCE(person_role, '')) AS person_role_key
FROM parsed
WHERE effective_date IS NOT NULL
  AND effective_date <= CURRENT_DATE
  AND (enterprise_start IS NULL OR effective_date >= enterprise_start);

CREATE INDEX _bt_prov_stage_c_events_ref_key
    ON _bt_prov_stage_c_events(enterprise_number, pub_reference);
CREATE INDEX _bt_prov_stage_c_events_type_key
    ON _bt_prov_stage_c_events(enterprise_number, event_type, sub_type, effective_date);

-- Stage A valid_from attribution.

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_admin') IS NOT NULL THEN
        UPDATE administrator a
        SET valid_from_provenance = CASE
            WHEN EXISTS (
                SELECT 1
                FROM _bt_prov_stage_c_admin_mandate_refs c
                WHERE c.enterprise_number = a.enterprise_number
                  AND c.name_key = search_normalize(a.name)
                  AND c.role IS NOT DISTINCT FROM a.role
                  AND c.earliest_mandate_start = a.valid_from
            )
                THEN 'nbb_mandate_start'
            ELSE 'nbb_filing_earliest'
        END
        FROM _bt_vf_stage_a_backup_admin b
        WHERE a.valid_from_provenance IS NULL
          AND a.valid_from IS NOT NULL
          AND a.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
          AND b.valid_from IS NULL
          AND a.enterprise_number = b.enterprise_number
          AND a.deposit_key = b.deposit_key
          AND a.name IS NOT DISTINCT FROM b.name
          AND a.role IS NOT DISTINCT FROM b.role;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_shareholder') IS NOT NULL THEN
        UPDATE shareholder sh
        SET valid_from_provenance = 'nbb_filing_earliest'
        FROM _bt_vf_stage_a_backup_shareholder b
        WHERE sh.valid_from_provenance IS NULL
          AND sh.valid_from IS NOT NULL
          AND sh.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
          AND b.valid_from IS NULL
          AND sh.enterprise_number = b.enterprise_number
          AND sh.deposit_key = b.deposit_key
          AND sh.name IS NOT DISTINCT FROM b.name;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_participating_interest') IS NOT NULL THEN
        UPDATE participating_interest pi
        SET valid_from_provenance = 'nbb_filing_earliest'
        FROM _bt_vf_stage_a_backup_participating_interest b
        WHERE pi.valid_from_provenance IS NULL
          AND pi.valid_from IS NOT NULL
          AND pi.deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
          AND b.valid_from IS NULL
          AND pi.enterprise_number = b.enterprise_number
          AND pi.deposit_key = b.deposit_key
          AND pi.name IS NOT DISTINCT FROM b.name;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_affiliation') IS NOT NULL THEN
        UPDATE affiliation af
        SET valid_from_provenance = 'nbb_filing_earliest'
        FROM _bt_vf_stage_a_backup_affiliation b
        WHERE af.valid_from_provenance IS NULL
          AND af.valid_from IS NOT NULL
          AND af.via_deposit_key NOT LIKE 'sb\_%' ESCAPE '\'
          AND b.valid_from IS NULL
          AND af.person_name = b.person_name
          AND af.enterprise_number = b.enterprise_number
          AND af.via_enterprise_number = b.via_enterprise_number
          AND af.affiliation_type = b.affiliation_type;
    END IF;
END
$$;

-- Stage B B1 valid_from attribution from Staatsblad event effective dates.

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_administrator') IS NOT NULL THEN
        WITH candidates AS (
            SELECT DISTINCT ON (a.ctid)
                   a.ctid AS row_ctid,
                   ev.effective_provenance
            FROM administrator a
            JOIN _bt_vf_stage_b_backup_administrator b
              ON a.enterprise_number = b.enterprise_number
             AND a.deposit_key = b.deposit_key
             AND a.name IS NOT DISTINCT FROM b.name
             AND a.role IS NOT DISTINCT FROM b.role
            JOIN _bt_prov_stage_c_events ev
              ON ev.enterprise_number = a.enterprise_number
             AND ev.pub_reference = pg_temp._bt_prov_stage_c_pub_reference(a.deposit_key)
            WHERE a.valid_from_provenance IS NULL
              AND a.valid_from IS NOT NULL
              AND b.valid_from IS NULL
              AND a.deposit_key LIKE 'sb\_%' ESCAPE '\'
              AND a.valid_from = ev.effective_date
              AND ev.event_type = 'admin_event'
              AND (ev.sub_type IN ('appointment', 'reappointment', 'renewal') OR ev.sub_type = '')
              AND search_normalize(COALESCE(a.name, '')) <> ''
              AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
              AND search_normalize(COALESCE(a.name, '')) IN (ev.person_name_key, ev.entity_name_key)
              AND (
                  ev.person_role_key = ''
                  OR search_normalize(COALESCE(a.role, '')) = ev.person_role_key
              )
            ORDER BY a.ctid, ev.effective_date ASC, ev.id ASC
        )
        UPDATE administrator a
        SET valid_from_provenance = c.effective_provenance
        FROM candidates c
        WHERE a.valid_from_provenance IS NULL
          AND a.ctid = c.row_ctid;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_shareholder') IS NOT NULL THEN
        WITH candidates AS (
            SELECT DISTINCT ON (sh.ctid)
                   sh.ctid AS row_ctid,
                   ev.effective_provenance
            FROM shareholder sh
            JOIN _bt_vf_stage_b_backup_shareholder b
              ON sh.enterprise_number = b.enterprise_number
             AND sh.deposit_key = b.deposit_key
             AND sh.name IS NOT DISTINCT FROM b.name
            JOIN _bt_prov_stage_c_events ev
              ON ev.enterprise_number = sh.enterprise_number
             AND ev.pub_reference = pg_temp._bt_prov_stage_c_pub_reference(sh.deposit_key)
            WHERE sh.valid_from_provenance IS NULL
              AND sh.valid_from IS NOT NULL
              AND b.valid_from IS NULL
              AND sh.deposit_key LIKE 'sb\_%' ESCAPE '\'
              AND sh.valid_from = ev.effective_date
              AND ev.event_type IN ('share_transfer', 'ownership_change')
              AND search_normalize(COALESCE(sh.name, '')) <> ''
              AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
              AND search_normalize(COALESCE(sh.name, '')) IN (ev.person_name_key, ev.entity_name_key)
            ORDER BY sh.ctid, ev.effective_date ASC, ev.id ASC
        )
        UPDATE shareholder sh
        SET valid_from_provenance = c.effective_provenance
        FROM candidates c
        WHERE sh.valid_from_provenance IS NULL
          AND sh.ctid = c.row_ctid;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_participating_interest') IS NOT NULL THEN
        WITH candidates AS (
            SELECT DISTINCT ON (pi.ctid)
                   pi.ctid AS row_ctid,
                   ev.effective_provenance
            FROM participating_interest pi
            JOIN _bt_vf_stage_b_backup_participating_interest b
              ON pi.enterprise_number = b.enterprise_number
             AND pi.deposit_key = b.deposit_key
             AND pi.name IS NOT DISTINCT FROM b.name
            JOIN _bt_prov_stage_c_events ev
              ON ev.enterprise_number = pi.enterprise_number
             AND ev.pub_reference = pg_temp._bt_prov_stage_c_pub_reference(pi.deposit_key)
            WHERE pi.valid_from_provenance IS NULL
              AND pi.valid_from IS NOT NULL
              AND b.valid_from IS NULL
              AND pi.deposit_key LIKE 'sb\_%' ESCAPE '\'
              AND pi.valid_from = ev.effective_date
              AND ev.event_type IN ('share_transfer', 'ownership_change', 'ma_event')
              AND search_normalize(COALESCE(pi.name, '')) <> ''
              AND (ev.person_name_key <> '' OR ev.entity_name_key <> '')
              AND search_normalize(COALESCE(pi.name, '')) IN (ev.person_name_key, ev.entity_name_key)
            ORDER BY pi.ctid, ev.effective_date ASC, ev.id ASC
        )
        UPDATE participating_interest pi
        SET valid_from_provenance = c.effective_provenance
        FROM candidates c
        WHERE pi.valid_from_provenance IS NULL
          AND pi.ctid = c.row_ctid;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_affiliation') IS NOT NULL THEN
        WITH candidates AS (
            SELECT DISTINCT ON (af.ctid)
                   af.ctid AS row_ctid,
                   ev.effective_provenance
            FROM affiliation af
            JOIN _bt_vf_stage_b_backup_affiliation b
              ON af.person_name = b.person_name
             AND af.enterprise_number = b.enterprise_number
             AND af.via_enterprise_number = b.via_enterprise_number
             AND af.affiliation_type = b.affiliation_type
            JOIN _bt_prov_stage_c_events ev
              ON ev.enterprise_number = af.via_enterprise_number
             AND ev.pub_reference = pg_temp._bt_prov_stage_c_pub_reference(af.via_deposit_key)
            WHERE af.valid_from_provenance IS NULL
              AND af.valid_from IS NOT NULL
              AND b.valid_from IS NULL
              AND af.via_deposit_key LIKE 'sb\_%' ESCAPE '\'
              AND af.valid_from = ev.effective_date
              AND ev.event_type = 'admin_event'
              AND af.affiliation_type = 'represents_admin'
              AND search_normalize(COALESCE(af.person_name, '')) <> ''
              AND ev.person_name_key <> ''
              AND search_normalize(COALESCE(af.person_name, '')) = ev.person_name_key
            ORDER BY af.ctid, ev.effective_date ASC, ev.id ASC
        )
        UPDATE affiliation af
        SET valid_from_provenance = c.effective_provenance
        FROM candidates c
        WHERE af.valid_from_provenance IS NULL
          AND af.ctid = c.row_ctid;
    END IF;
END
$$;

-- Stage B B2 valid_to attribution.

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_administrator') IS NOT NULL THEN
        UPDATE administrator a
        SET valid_to_provenance = 'staatsblad_supersession'
        FROM _bt_vf_stage_b_backup_administrator b
        WHERE a.valid_to_provenance IS NULL
          AND a.valid_to IS NOT NULL
          AND b.valid_to IS NULL
          AND a.enterprise_number = b.enterprise_number
          AND a.deposit_key = b.deposit_key
          AND a.name IS NOT DISTINCT FROM b.name
          AND a.role IS NOT DISTINCT FROM b.role;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_shareholder') IS NOT NULL THEN
        UPDATE shareholder sh
        SET valid_to_provenance = 'staatsblad_supersession'
        FROM _bt_vf_stage_b_backup_shareholder b
        WHERE sh.valid_to_provenance IS NULL
          AND sh.valid_to IS NOT NULL
          AND b.valid_to IS NULL
          AND sh.enterprise_number = b.enterprise_number
          AND sh.deposit_key = b.deposit_key
          AND sh.name IS NOT DISTINCT FROM b.name;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_participating_interest') IS NOT NULL THEN
        UPDATE participating_interest pi
        SET valid_to_provenance = 'staatsblad_supersession'
        FROM _bt_vf_stage_b_backup_participating_interest b
        WHERE pi.valid_to_provenance IS NULL
          AND pi.valid_to IS NOT NULL
          AND b.valid_to IS NULL
          AND pi.enterprise_number = b.enterprise_number
          AND pi.deposit_key = b.deposit_key
          AND pi.name IS NOT DISTINCT FROM b.name;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_affiliation') IS NOT NULL THEN
        UPDATE affiliation af
        SET valid_to_provenance = 'staatsblad_supersession'
        FROM _bt_vf_stage_b_backup_affiliation b
        WHERE af.valid_to_provenance IS NULL
          AND af.valid_to IS NOT NULL
          AND b.valid_to IS NULL
          AND af.person_name = b.person_name
          AND af.enterprise_number = b.enterprise_number
          AND af.via_enterprise_number = b.via_enterprise_number
          AND af.affiliation_type = b.affiliation_type;
    END IF;
END
$$;

-- Pre-existing or newly ingested direct values.

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_admin') IS NOT NULL THEN
        UPDATE administrator a
        SET valid_from_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_a_backup_admin b
        WHERE a.valid_from_provenance IS NULL
          AND a.valid_from IS NOT NULL
          AND b.valid_from IS NOT NULL
          AND a.enterprise_number = b.enterprise_number
          AND a.deposit_key = b.deposit_key
          AND a.name IS NOT DISTINCT FROM b.name
          AND a.role IS NOT DISTINCT FROM b.role;

        UPDATE administrator a
        SET valid_from_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE a.valid_from_provenance IS NULL
          AND a.valid_from IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_a_backup_admin b
              WHERE a.enterprise_number = b.enterprise_number
                AND a.deposit_key = b.deposit_key
                AND a.name IS NOT DISTINCT FROM b.name
                AND a.role IS NOT DISTINCT FROM b.role
          );
    ELSE
        UPDATE administrator a
        SET valid_from_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE a.valid_from_provenance IS NULL
          AND a.valid_from IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_shareholder') IS NOT NULL THEN
        UPDATE shareholder sh
        SET valid_from_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_a_backup_shareholder b
        WHERE sh.valid_from_provenance IS NULL
          AND sh.valid_from IS NOT NULL
          AND b.valid_from IS NOT NULL
          AND sh.enterprise_number = b.enterprise_number
          AND sh.deposit_key = b.deposit_key
          AND sh.name IS NOT DISTINCT FROM b.name;

        UPDATE shareholder sh
        SET valid_from_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE sh.valid_from_provenance IS NULL
          AND sh.valid_from IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_a_backup_shareholder b
              WHERE sh.enterprise_number = b.enterprise_number
                AND sh.deposit_key = b.deposit_key
                AND sh.name IS NOT DISTINCT FROM b.name
          );
    ELSE
        UPDATE shareholder sh
        SET valid_from_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE sh.valid_from_provenance IS NULL
          AND sh.valid_from IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_participating_interest') IS NOT NULL THEN
        UPDATE participating_interest pi
        SET valid_from_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_a_backup_participating_interest b
        WHERE pi.valid_from_provenance IS NULL
          AND pi.valid_from IS NOT NULL
          AND b.valid_from IS NOT NULL
          AND pi.enterprise_number = b.enterprise_number
          AND pi.deposit_key = b.deposit_key
          AND pi.name IS NOT DISTINCT FROM b.name;

        UPDATE participating_interest pi
        SET valid_from_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE pi.valid_from_provenance IS NULL
          AND pi.valid_from IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_a_backup_participating_interest b
              WHERE pi.enterprise_number = b.enterprise_number
                AND pi.deposit_key = b.deposit_key
                AND pi.name IS NOT DISTINCT FROM b.name
          );
    ELSE
        UPDATE participating_interest pi
        SET valid_from_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE pi.valid_from_provenance IS NULL
          AND pi.valid_from IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_a_backup_affiliation') IS NOT NULL THEN
        UPDATE affiliation af
        SET valid_from_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_a_backup_affiliation b
        WHERE af.valid_from_provenance IS NULL
          AND af.valid_from IS NOT NULL
          AND b.valid_from IS NOT NULL
          AND af.person_name = b.person_name
          AND af.enterprise_number = b.enterprise_number
          AND af.via_enterprise_number = b.via_enterprise_number
          AND af.affiliation_type = b.affiliation_type;

        UPDATE affiliation af
        SET valid_from_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE af.valid_from_provenance IS NULL
          AND af.valid_from IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_a_backup_affiliation b
              WHERE af.person_name = b.person_name
                AND af.enterprise_number = b.enterprise_number
                AND af.via_enterprise_number = b.via_enterprise_number
                AND af.affiliation_type = b.affiliation_type
          );
    ELSE
        UPDATE affiliation af
        SET valid_from_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE af.valid_from_provenance IS NULL
          AND af.valid_from IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_administrator') IS NOT NULL THEN
        UPDATE administrator a
        SET valid_to_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_b_backup_administrator b
        WHERE a.valid_to_provenance IS NULL
          AND a.valid_to IS NOT NULL
          AND b.valid_to IS NOT NULL
          AND a.enterprise_number = b.enterprise_number
          AND a.deposit_key = b.deposit_key
          AND a.name IS NOT DISTINCT FROM b.name
          AND a.role IS NOT DISTINCT FROM b.role;

        UPDATE administrator a
        SET valid_to_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE a.valid_to_provenance IS NULL
          AND a.valid_to IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_b_backup_administrator b
              WHERE a.enterprise_number = b.enterprise_number
                AND a.deposit_key = b.deposit_key
                AND a.name IS NOT DISTINCT FROM b.name
                AND a.role IS NOT DISTINCT FROM b.role
          );
    ELSE
        UPDATE administrator a
        SET valid_to_provenance = CASE
            WHEN a.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE a.valid_to_provenance IS NULL
          AND a.valid_to IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_shareholder') IS NOT NULL THEN
        UPDATE shareholder sh
        SET valid_to_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_b_backup_shareholder b
        WHERE sh.valid_to_provenance IS NULL
          AND sh.valid_to IS NOT NULL
          AND b.valid_to IS NOT NULL
          AND sh.enterprise_number = b.enterprise_number
          AND sh.deposit_key = b.deposit_key
          AND sh.name IS NOT DISTINCT FROM b.name;

        UPDATE shareholder sh
        SET valid_to_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE sh.valid_to_provenance IS NULL
          AND sh.valid_to IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_b_backup_shareholder b
              WHERE sh.enterprise_number = b.enterprise_number
                AND sh.deposit_key = b.deposit_key
                AND sh.name IS NOT DISTINCT FROM b.name
          );
    ELSE
        UPDATE shareholder sh
        SET valid_to_provenance = CASE
            WHEN sh.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE sh.valid_to_provenance IS NULL
          AND sh.valid_to IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_participating_interest') IS NOT NULL THEN
        UPDATE participating_interest pi
        SET valid_to_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_b_backup_participating_interest b
        WHERE pi.valid_to_provenance IS NULL
          AND pi.valid_to IS NOT NULL
          AND b.valid_to IS NOT NULL
          AND pi.enterprise_number = b.enterprise_number
          AND pi.deposit_key = b.deposit_key
          AND pi.name IS NOT DISTINCT FROM b.name;

        UPDATE participating_interest pi
        SET valid_to_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE pi.valid_to_provenance IS NULL
          AND pi.valid_to IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_b_backup_participating_interest b
              WHERE pi.enterprise_number = b.enterprise_number
                AND pi.deposit_key = b.deposit_key
                AND pi.name IS NOT DISTINCT FROM b.name
          );
    ELSE
        UPDATE participating_interest pi
        SET valid_to_provenance = CASE
            WHEN pi.deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE pi.valid_to_provenance IS NULL
          AND pi.valid_to IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('public._bt_vf_stage_b_backup_affiliation') IS NOT NULL THEN
        UPDATE affiliation af
        SET valid_to_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        FROM _bt_vf_stage_b_backup_affiliation b
        WHERE af.valid_to_provenance IS NULL
          AND af.valid_to IS NOT NULL
          AND b.valid_to IS NOT NULL
          AND af.person_name = b.person_name
          AND af.enterprise_number = b.enterprise_number
          AND af.via_enterprise_number = b.via_enterprise_number
          AND af.affiliation_type = b.affiliation_type;

        UPDATE affiliation af
        SET valid_to_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE af.valid_to_provenance IS NULL
          AND af.valid_to IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM _bt_vf_stage_b_backup_affiliation b
              WHERE af.person_name = b.person_name
                AND af.enterprise_number = b.enterprise_number
                AND af.via_enterprise_number = b.via_enterprise_number
                AND af.affiliation_type = b.affiliation_type
          );
    ELSE
        UPDATE affiliation af
        SET valid_to_provenance = CASE
            WHEN af.via_deposit_key LIKE 'sb\_%' ESCAPE '\' THEN 'staatsblad_consumer_direct'
            ELSE 'nbb_loader_direct'
        END
        WHERE af.valid_to_provenance IS NULL
          AND af.valid_to IS NOT NULL;
    END IF;
END
$$;

-- Last-resort labels for values that could not be tied to a known path.

UPDATE administrator a
SET valid_from_provenance = 'unknown'
WHERE a.valid_from_provenance IS NULL
  AND a.valid_from IS NOT NULL;

UPDATE shareholder sh
SET valid_from_provenance = 'unknown'
WHERE sh.valid_from_provenance IS NULL
  AND sh.valid_from IS NOT NULL;

UPDATE participating_interest pi
SET valid_from_provenance = 'unknown'
WHERE pi.valid_from_provenance IS NULL
  AND pi.valid_from IS NOT NULL;

UPDATE affiliation af
SET valid_from_provenance = 'unknown'
WHERE af.valid_from_provenance IS NULL
  AND af.valid_from IS NOT NULL;

UPDATE administrator a
SET valid_to_provenance = 'unknown'
WHERE a.valid_to_provenance IS NULL
  AND a.valid_to IS NOT NULL;

UPDATE shareholder sh
SET valid_to_provenance = 'unknown'
WHERE sh.valid_to_provenance IS NULL
  AND sh.valid_to IS NOT NULL;

UPDATE participating_interest pi
SET valid_to_provenance = 'unknown'
WHERE pi.valid_to_provenance IS NULL
  AND pi.valid_to IS NOT NULL;

UPDATE affiliation af
SET valid_to_provenance = 'unknown'
WHERE af.valid_to_provenance IS NULL
  AND af.valid_to IS NOT NULL;
