-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=900s

-- Bitemporal Phase A: additive valid-time + transaction-time columns for
-- NBB governance fact tables. Intervals are half-open:
-- valid_from <= D AND (valid_to IS NULL OR valid_to > D).

ALTER TABLE administrator
    ADD COLUMN IF NOT EXISTS valid_from DATE,
    ADD COLUMN IF NOT EXISTS valid_to DATE,
    ADD COLUMN IF NOT EXISTS source_deposit_date DATE,
    ADD COLUMN IF NOT EXISTS recorded_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recorded_to TIMESTAMPTZ;

ALTER TABLE shareholder
    ADD COLUMN IF NOT EXISTS valid_from DATE,
    ADD COLUMN IF NOT EXISTS valid_to DATE,
    ADD COLUMN IF NOT EXISTS source_deposit_date DATE,
    ADD COLUMN IF NOT EXISTS recorded_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recorded_to TIMESTAMPTZ;

ALTER TABLE participating_interest
    ADD COLUMN IF NOT EXISTS valid_from DATE,
    ADD COLUMN IF NOT EXISTS valid_to DATE,
    ADD COLUMN IF NOT EXISTS source_deposit_date DATE,
    ADD COLUMN IF NOT EXISTS recorded_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recorded_to TIMESTAMPTZ;

ALTER TABLE affiliation
    ADD COLUMN IF NOT EXISTS valid_from DATE,
    ADD COLUMN IF NOT EXISTS valid_to DATE,
    ADD COLUMN IF NOT EXISTS source_deposit_date DATE,
    ADD COLUMN IF NOT EXISTS recorded_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recorded_to TIMESTAMPTZ;

COMMENT ON COLUMN administrator.valid_from IS 'Valid-time start. NULL means unknown start; current/as-of views treat it as in force.';
COMMENT ON COLUMN shareholder.valid_from IS 'Valid-time start. NULL means unknown start; current/as-of views treat it as in force.';
COMMENT ON COLUMN participating_interest.valid_from IS 'Valid-time start. NULL means unknown start; current/as-of views treat it as in force.';
COMMENT ON COLUMN affiliation.valid_from IS 'Valid-time start. NULL means unknown start; current/as-of views treat it as in force.';
COMMENT ON COLUMN administrator.valid_to IS 'Valid-time exclusive end. Human-inclusive filing end dates are stored as end_date + 1 day.';
COMMENT ON COLUMN shareholder.valid_to IS 'Valid-time exclusive end. NULL means open-ended.';
COMMENT ON COLUMN participating_interest.valid_to IS 'Valid-time exclusive end. NULL means open-ended.';
COMMENT ON COLUMN affiliation.valid_to IS 'Valid-time exclusive end. NULL means open-ended.';
COMMENT ON COLUMN administrator.recorded_from IS 'Transaction-time start: when DataSnoop learned this fact.';
COMMENT ON COLUMN shareholder.recorded_from IS 'Transaction-time start: when DataSnoop learned this fact.';
COMMENT ON COLUMN participating_interest.recorded_from IS 'Transaction-time start: when DataSnoop learned this fact.';
COMMENT ON COLUMN affiliation.recorded_from IS 'Transaction-time start: when DataSnoop learned this fact.';
COMMENT ON COLUMN administrator.recorded_to IS 'Transaction-time exclusive end; NULL means this fact version is current knowledge.';
COMMENT ON COLUMN shareholder.recorded_to IS 'Transaction-time exclusive end; NULL means this fact version is current knowledge.';
COMMENT ON COLUMN participating_interest.recorded_to IS 'Transaction-time exclusive end; NULL means this fact version is current knowledge.';
COMMENT ON COLUMN affiliation.recorded_to IS 'Transaction-time exclusive end; NULL means this fact version is current knowledge.';

CREATE TEMP TABLE _bt_filing_dates ON COMMIT DROP AS
SELECT DISTINCT ON (enterprise_number, deposit_key)
       enterprise_number,
       deposit_key,
       CASE
           WHEN deposit_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
               THEN deposit_date::date
           ELSE NULL
       END AS deposit_date
FROM financial_data
WHERE deposit_date IS NOT NULL
ORDER BY enterprise_number, deposit_key;

CREATE INDEX _bt_filing_dates_key
    ON _bt_filing_dates(enterprise_number, deposit_key);

CREATE TEMP TABLE _bt_load_times ON COMMIT DROP AS
SELECT enterprise_number,
       deposit_key,
       CASE
           WHEN loaded_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
               THEN loaded_at::timestamptz
           ELSE NOW()
       END AS loaded_at_ts
FROM nbb_load_log;

CREATE INDEX _bt_load_times_key
    ON _bt_load_times(enterprise_number, deposit_key);

UPDATE administrator a
SET source_deposit_date = COALESCE(a.source_deposit_date, fd.deposit_date),
    valid_from = COALESCE(
        a.valid_from,
        CASE
            WHEN a.mandate_start ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN a.mandate_start::date
            WHEN a.mandate_start ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                THEN to_date(a.mandate_start, 'DD/MM/YYYY')
            ELSE fd.deposit_date
        END
    ),
    valid_to = COALESCE(
        a.valid_to,
        CASE
            WHEN a.mandate_end ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                THEN (a.mandate_end::date + INTERVAL '1 day')::date
            WHEN a.mandate_end ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                THEN (to_date(a.mandate_end, 'DD/MM/YYYY') + INTERVAL '1 day')::date
            ELSE NULL
        END
    ),
    recorded_from = COALESCE(a.recorded_from, lt.loaded_at_ts, NOW())
FROM _bt_filing_dates fd
LEFT JOIN _bt_load_times lt
  ON lt.enterprise_number = fd.enterprise_number
 AND lt.deposit_key = fd.deposit_key
WHERE a.enterprise_number = fd.enterprise_number
  AND a.deposit_key = fd.deposit_key
  AND (
      a.source_deposit_date IS NULL
      OR a.valid_from IS NULL
      OR a.recorded_from IS NULL
  );

UPDATE shareholder sh
SET source_deposit_date = COALESCE(sh.source_deposit_date, fd.deposit_date),
    valid_from = COALESCE(sh.valid_from, fd.deposit_date),
    recorded_from = COALESCE(sh.recorded_from, lt.loaded_at_ts, NOW())
FROM _bt_filing_dates fd
LEFT JOIN _bt_load_times lt
  ON lt.enterprise_number = fd.enterprise_number
 AND lt.deposit_key = fd.deposit_key
WHERE sh.enterprise_number = fd.enterprise_number
  AND sh.deposit_key = fd.deposit_key
  AND (
      sh.source_deposit_date IS NULL
      OR sh.valid_from IS NULL
      OR sh.recorded_from IS NULL
  );

UPDATE participating_interest pi
SET source_deposit_date = COALESCE(pi.source_deposit_date, fd.deposit_date),
    valid_from = COALESCE(pi.valid_from, fd.deposit_date),
    recorded_from = COALESCE(pi.recorded_from, lt.loaded_at_ts, NOW())
FROM _bt_filing_dates fd
LEFT JOIN _bt_load_times lt
  ON lt.enterprise_number = fd.enterprise_number
 AND lt.deposit_key = fd.deposit_key
WHERE pi.enterprise_number = fd.enterprise_number
  AND pi.deposit_key = fd.deposit_key
  AND (
      pi.source_deposit_date IS NULL
      OR pi.valid_from IS NULL
      OR pi.recorded_from IS NULL
  );

UPDATE affiliation af
SET source_deposit_date = COALESCE(af.source_deposit_date, fd.deposit_date),
    valid_from = COALESCE(af.valid_from, fd.deposit_date),
    recorded_from = COALESCE(af.recorded_from, lt.loaded_at_ts, NOW())
FROM _bt_filing_dates fd
LEFT JOIN _bt_load_times lt
  ON lt.enterprise_number = fd.enterprise_number
 AND lt.deposit_key = fd.deposit_key
WHERE af.via_enterprise_number = fd.enterprise_number
  AND af.via_deposit_key = fd.deposit_key
  AND (
      af.source_deposit_date IS NULL
      OR af.valid_from IS NULL
      OR af.recorded_from IS NULL
  );

UPDATE administrator SET recorded_from = NOW() WHERE recorded_from IS NULL;
UPDATE shareholder SET recorded_from = NOW() WHERE recorded_from IS NULL;
UPDATE participating_interest SET recorded_from = NOW() WHERE recorded_from IS NULL;
UPDATE affiliation SET recorded_from = NOW() WHERE recorded_from IS NULL;

ALTER TABLE administrator ALTER COLUMN recorded_from SET DEFAULT NOW();
ALTER TABLE shareholder ALTER COLUMN recorded_from SET DEFAULT NOW();
ALTER TABLE participating_interest ALTER COLUMN recorded_from SET DEFAULT NOW();
ALTER TABLE affiliation ALTER COLUMN recorded_from SET DEFAULT NOW();

WITH ranked AS (
    SELECT ctid,
           LEAD(recorded_from) OVER (
               PARTITION BY enterprise_number, search_normalize(name), role
               ORDER BY source_deposit_date NULLS FIRST, recorded_from NULLS FIRST, deposit_key
           ) AS next_recorded_from
    FROM administrator
    WHERE valid_to IS NULL
      AND recorded_to IS NULL
)
UPDATE administrator a
SET recorded_to = ranked.next_recorded_from
FROM ranked
WHERE a.ctid = ranked.ctid
  AND ranked.next_recorded_from IS NOT NULL;

-- shareholder has no country column in the live schema despite the r25
-- natural-key sketch. Use address as the available discriminator and
-- record the spec gap in the PR/audit evidence.
WITH ranked AS (
    SELECT ctid,
           LEAD(recorded_from) OVER (
               PARTITION BY enterprise_number,
                            search_normalize(name),
                            COALESCE(identifier, ''),
                            COALESCE(address, '')
               ORDER BY source_deposit_date NULLS FIRST, recorded_from NULLS FIRST, deposit_key
           ) AS next_recorded_from
    FROM shareholder
    WHERE valid_to IS NULL
      AND recorded_to IS NULL
)
UPDATE shareholder sh
SET recorded_to = ranked.next_recorded_from
FROM ranked
WHERE sh.ctid = ranked.ctid
  AND ranked.next_recorded_from IS NOT NULL;

WITH ranked AS (
    SELECT ctid,
           LEAD(recorded_from) OVER (
               PARTITION BY enterprise_number,
                            COALESCE(identifier, ''),
                            search_normalize(name),
                            COALESCE(country, '')
               ORDER BY source_deposit_date NULLS FIRST, recorded_from NULLS FIRST, deposit_key
           ) AS next_recorded_from
    FROM participating_interest
    WHERE valid_to IS NULL
      AND recorded_to IS NULL
)
UPDATE participating_interest pi
SET recorded_to = ranked.next_recorded_from
FROM ranked
WHERE pi.ctid = ranked.ctid
  AND ranked.next_recorded_from IS NOT NULL;

WITH ranked AS (
    SELECT ctid,
           LEAD(recorded_from) OVER (
               PARTITION BY enterprise_number,
                            search_normalize(person_name),
                            via_enterprise_number,
                            affiliation_type
               ORDER BY source_deposit_date NULLS FIRST,
                        recorded_from NULLS FIRST,
                        via_deposit_key
           ) AS next_recorded_from
    FROM affiliation
    WHERE valid_to IS NULL
      AND recorded_to IS NULL
)
UPDATE affiliation af
SET recorded_to = ranked.next_recorded_from
FROM ranked
WHERE af.ctid = ranked.ctid
  AND ranked.next_recorded_from IS NOT NULL;

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

CREATE OR REPLACE VIEW administrator_fact AS SELECT * FROM administrator;
CREATE OR REPLACE VIEW shareholder_fact AS SELECT * FROM shareholder;
CREATE OR REPLACE VIEW participating_interest_fact AS SELECT * FROM participating_interest;
CREATE OR REPLACE VIEW affiliation_fact AS SELECT * FROM affiliation;

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

CREATE INDEX IF NOT EXISTS idx_admin_bitemporal_window
    ON administrator(enterprise_number, valid_from, valid_to, recorded_from, recorded_to);
CREATE INDEX IF NOT EXISTS idx_shareholder_bitemporal_window
    ON shareholder(enterprise_number, valid_from, valid_to, recorded_from, recorded_to);
CREATE INDEX IF NOT EXISTS idx_pi_bitemporal_window
    ON participating_interest(enterprise_number, valid_from, valid_to, recorded_from, recorded_to);
CREATE INDEX IF NOT EXISTS idx_affiliation_bitemporal_window
    ON affiliation(enterprise_number, valid_from, valid_to, recorded_from, recorded_to);

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_current_natural
    ON administrator(enterprise_number, search_normalize(name), role)
    WHERE recorded_to IS NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_shareholder_current_natural
    ON shareholder(
        enterprise_number,
        search_normalize(name),
        COALESCE(identifier, ''),
        COALESCE(address, '')
    )
    WHERE recorded_to IS NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pi_current_natural
    ON participating_interest(
        enterprise_number,
        COALESCE(identifier, ''),
        search_normalize(name),
        COALESCE(country, '')
    )
    WHERE recorded_to IS NULL AND valid_to IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_affiliation_current_natural
    ON affiliation(
        enterprise_number,
        search_normalize(person_name),
        via_enterprise_number,
        affiliation_type
    )
    WHERE recorded_to IS NULL AND valid_to IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT ON administrator_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON shareholder_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON participating_interest_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON affiliation_current TO leadpeek';
        EXECUTE 'GRANT SELECT ON administrator_fact TO leadpeek';
        EXECUTE 'GRANT SELECT ON shareholder_fact TO leadpeek';
        EXECUTE 'GRANT SELECT ON participating_interest_fact TO leadpeek';
        EXECUTE 'GRANT SELECT ON affiliation_fact TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION admins_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION shareholders_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION participating_interests_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION affiliations_as_of(DATE, TIMESTAMPTZ) TO leadpeek';
    END IF;
END $$;
