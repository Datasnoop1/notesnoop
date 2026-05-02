-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=30min

-- Ownership graph v1. Pure Postgres SQL; Apache AGE remains excluded.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ownership_edge (
    id                         BIGSERIAL PRIMARY KEY,
    parent_kind                TEXT NOT NULL,
    parent_id                  TEXT NOT NULL,
    parent_name_raw            TEXT,
    parent_identifier_scheme   TEXT,
    parent_identifier_value    TEXT,
    parent_country             CHAR(2),
    child_kind                 TEXT NOT NULL DEFAULT 'company',
    child_id                   TEXT NOT NULL,
    pct                        NUMERIC(5,2),
    edge_kind                  TEXT NOT NULL,
    source_table               TEXT NOT NULL,
    source_pk                  TEXT NOT NULL,
    source_action_seq          INT NOT NULL DEFAULT 0,
    source_filing              TEXT,
    source_rank                INT NOT NULL,
    fiscal_year                INT,
    deposit_date               DATE,
    valid_from                 DATE,
    valid_to                   DATE,
    confidence                 REAL DEFAULT 1.0,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ownership_edge_parent_kind_check
        CHECK (parent_kind IN ('company', 'person', 'external_org', 'unknown')),
    CONSTRAINT ownership_edge_child_kind_check
        CHECK (child_kind = 'company'),
    CONSTRAINT ownership_edge_child_id_check
        CHECK (child_id ~ '^[0-9]{10}$'),
    CONSTRAINT ownership_edge_pct_check
        CHECK (pct IS NULL OR (pct >= 0 AND pct <= 100)),
    CONSTRAINT ownership_edge_source_action_seq_check
        CHECK (source_action_seq >= 0),
    CONSTRAINT ownership_edge_source_rank_check
        CHECK (source_rank > 0),
    CONSTRAINT ownership_edge_confidence_check
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ownership_edge_valid_interval_check
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
    CONSTRAINT ownership_edge_kind_check
        CHECK (edge_kind IN (
            'shareholder',
            'participating',
            'gazette_capital',
            'gazette_transfer',
            'gazette_ownership',
            'gazette_ma'
        )),
    CONSTRAINT ownership_edge_parent_id_check
        CHECK (
            (
                parent_kind = 'company'
                AND parent_id ~ '^[0-9]{10}$'
                AND parent_identifier_scheme IS NOT DISTINCT FROM 'CBE'
                AND parent_identifier_value IS NOT DISTINCT FROM parent_id
            )
            OR (
                parent_kind = 'person'
                AND parent_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                AND parent_identifier_scheme IS NOT DISTINCT FROM 'UUID'
                AND parent_identifier_value IS NOT DISTINCT FROM parent_id
            )
            OR (
                parent_kind = 'external_org'
                AND parent_identifier_scheme IS NOT NULL
                AND parent_identifier_value IS NOT NULL
                AND parent_id = parent_identifier_scheme || ':' || parent_identifier_value
            )
            OR (
                parent_kind = 'unknown'
                AND parent_name_raw IS NOT NULL
                AND parent_identifier_scheme IS NULL
                AND parent_identifier_value IS NULL
                AND parent_id ~ '^unknown:[0-9a-f]{16}$'
            )
        ),
    CONSTRAINT ownership_edge_source_unique
        UNIQUE (source_table, source_pk, source_action_seq)
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oe_parent
    ON ownership_edge(parent_kind, parent_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oe_child
    ON ownership_edge(child_kind, child_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oe_active
    ON ownership_edge(child_id, valid_to)
    WHERE valid_to IS NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oe_rank
    ON ownership_edge(child_id, source_rank, deposit_date DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oe_source_table
    ON ownership_edge(source_table);

CREATE OR REPLACE VIEW ownership_edge_current AS
SELECT DISTINCT ON (parent_kind, parent_id, child_kind, child_id)
       id,
       parent_kind,
       parent_id,
       parent_name_raw,
       parent_identifier_scheme,
       parent_identifier_value,
       parent_country,
       child_kind,
       child_id,
       pct,
       edge_kind,
       source_table,
       source_pk,
       source_action_seq,
       source_filing,
       source_rank,
       fiscal_year,
       deposit_date,
       valid_from,
       valid_to,
       confidence,
       created_at,
       updated_at
FROM ownership_edge
WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)
  AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
ORDER BY parent_kind,
         parent_id,
         child_kind,
         child_id,
         source_rank ASC,
         deposit_date DESC NULLS LAST,
         fiscal_year DESC NULLS LAST,
         id DESC;

CREATE OR REPLACE FUNCTION ownership_edge_as_of(target_date DATE)
RETURNS SETOF ownership_edge
LANGUAGE sql
STABLE
AS $$
    SELECT DISTINCT ON (parent_kind, parent_id, child_kind, child_id)
           oe.*
    FROM ownership_edge oe
    WHERE (oe.valid_from IS NULL OR oe.valid_from <= target_date)
      AND (oe.valid_to IS NULL OR oe.valid_to > target_date)
    ORDER BY oe.parent_kind,
             oe.parent_id,
             oe.child_kind,
             oe.child_id,
             oe.source_rank ASC,
             oe.deposit_date DESC NULLS LAST,
             oe.fiscal_year DESC NULLS LAST,
             oe.id DESC
$$;

CREATE OR REPLACE FUNCTION ownership_ubo_walk(
    root_child_id TEXT,
    max_depth INT DEFAULT 6
)
RETURNS TABLE (
    depth INT,
    parent_kind TEXT,
    parent_id TEXT,
    parent_name_raw TEXT,
    child_id TEXT,
    pct NUMERIC(5,2),
    edge_kind TEXT,
    source_rank INT,
    path TEXT[],
    cycle BOOLEAN
)
LANGUAGE sql
STABLE
AS $$
    WITH RECURSIVE walk AS (
        SELECT
            1 AS depth,
            oe.parent_kind,
            oe.parent_id,
            oe.parent_name_raw,
            oe.child_id,
            oe.pct,
            oe.edge_kind,
            oe.source_rank,
            ARRAY['company:' || root_child_id, oe.parent_kind || ':' || oe.parent_id] AS path,
            false AS cycle
        FROM ownership_edge_current oe
        WHERE oe.child_kind = 'company'
          AND oe.child_id = root_child_id

        UNION ALL

        SELECT
            walk.depth + 1,
            oe.parent_kind,
            oe.parent_id,
            oe.parent_name_raw,
            oe.child_id,
            oe.pct,
            oe.edge_kind,
            oe.source_rank,
            walk.path || (oe.parent_kind || ':' || oe.parent_id),
            (oe.parent_kind || ':' || oe.parent_id) = ANY(walk.path)
        FROM walk
        JOIN ownership_edge_current oe
          ON walk.parent_kind = 'company'
         AND oe.child_kind = 'company'
         AND oe.child_id = walk.parent_id
        WHERE NOT walk.cycle
          AND walk.depth < GREATEST(1, LEAST(max_depth, 12))
    )
    SELECT depth,
           parent_kind,
           parent_id,
           parent_name_raw,
           child_id,
           pct,
           edge_kind,
           source_rank,
           path,
           cycle
    FROM walk
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ownership_edge TO leadpeek';
        EXECUTE 'GRANT SELECT ON ownership_edge_current TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION ownership_edge_as_of(DATE) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION ownership_ubo_walk(TEXT, INT) TO leadpeek';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE ownership_edge_id_seq TO leadpeek';
    END IF;
END $$;
