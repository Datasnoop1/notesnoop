-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=30min

-- Person v1 internal-only foundation.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Catalog-drift prerequisite: code already reads these fields from
-- staatsblad_event; Person v1 depends on the structured domicile anchor.
ALTER TABLE staatsblad_event
    ADD COLUMN IF NOT EXISTS person_domicile_city TEXT;
ALTER TABLE staatsblad_event
    ADD COLUMN IF NOT EXISTS person_domicile_postcode TEXT;
ALTER TABLE staatsblad_event
    ADD COLUMN IF NOT EXISTS person_domicile_country TEXT;
ALTER TABLE staatsblad_event
    ADD COLUMN IF NOT EXISTS person_domicile_confidence REAL;
ALTER TABLE staatsblad_event
    ADD COLUMN IF NOT EXISTS person_domicile_extracted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS person (
    person_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name      TEXT NOT NULL,
    name_normalized     TEXT GENERATED ALWAYS AS (search_normalize(canonical_name)) STORED,
    primary_city        TEXT,
    primary_postcode    TEXT,
    role_count          INT DEFAULT 0,
    first_seen_date     DATE,
    last_seen_date      DATE,
    cluster_version     TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    merged_into         UUID REFERENCES person(person_id),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT person_status_check
        CHECK (status IN ('active', 'merged', 'tombstone')),
    CONSTRAINT person_merged_into_check
        CHECK ((status = 'merged' AND merged_into IS NOT NULL) OR status <> 'merged')
);

CREATE TABLE IF NOT EXISTS person_link (
    id                  BIGSERIAL PRIMARY KEY,
    person_id           UUID NOT NULL REFERENCES person(person_id),
    source_table        TEXT NOT NULL,
    source_pk           TEXT NOT NULL,
    source_mention_seq  INTEGER NOT NULL DEFAULT 0,
    source_field        TEXT,
    enterprise_number   TEXT,
    name_as_written     TEXT,
    link_kind           TEXT NOT NULL,
    confidence          REAL NOT NULL,
    confirmed_by_human  BOOLEAN DEFAULT FALSE,
    cluster_version     TEXT,
    CONSTRAINT person_link_source_unique
        UNIQUE (source_table, source_pk, source_mention_seq),
    CONSTRAINT person_link_mention_seq_check
        CHECK (source_mention_seq >= 0),
    CONSTRAINT person_link_confidence_check
        CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT person_link_kind_check
        CHECK (link_kind IN ('deterministic', 'probabilistic', 'manual'))
);

CREATE TABLE IF NOT EXISTS person_merge_log (
    id              BIGSERIAL PRIMARY KEY,
    op_kind         TEXT NOT NULL,
    primary_id      UUID NOT NULL REFERENCES person(person_id),
    secondary_id    UUID REFERENCES person(person_id),
    moved_link_ids  BIGINT[],
    op_at           TIMESTAMPTZ DEFAULT NOW(),
    op_by           TEXT,
    reason          TEXT,
    CONSTRAINT person_merge_log_kind_check
        CHECK (op_kind IN ('merge', 'split', 'manual_correct', 'tombstone'))
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_status
    ON person(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_name_tsv
    ON person USING GIN (to_tsvector('simple', name_normalized));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_name_norm_trgm
    ON person USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_link_person
    ON person_link(person_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_link_enterprise
    ON person_link(enterprise_number);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_link_kind
    ON person_link(link_kind);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_person_link_source_table
    ON person_link(source_table);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pml_primary
    ON person_merge_log(primary_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pml_secondary
    ON person_merge_log(secondary_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person_link TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person_merge_log TO leadpeek';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE person_link_id_seq TO leadpeek';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE person_merge_log_id_seq TO leadpeek';
    END IF;
END $$;
