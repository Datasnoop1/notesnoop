-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=5min

-- Captures runtime DDL formerly owned by backend/db.py.
-- Search V2 owns company_info.name_normalized and search indexes in
-- src/schema.sql; the legacy search-v1 startup fallback is intentionally not
-- recreated here. The old staatsblad_event regex table is also intentionally
-- omitted because the canonical baseline owns the Stage-3 staatsblad_event
-- shape and its indexes.

CREATE TABLE IF NOT EXISTS activity_log (
    id              SERIAL PRIMARY KEY,
    user_email      TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    method          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      TEXT,
    ua_family       TEXT,
    device_type     TEXT,
    country_code    VARCHAR(2)
);
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS ua_family TEXT;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS device_type TEXT;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS country_code VARCHAR(2);
CREATE INDEX IF NOT EXISTS idx_activity_log_user_date
    ON activity_log(user_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_endpoint_date
    ON activity_log(endpoint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_date
    ON activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_session
    ON activity_log(session_id, created_at DESC)
    WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_activity_log_ua_date
    ON activity_log(ua_family, created_at DESC)
    WHERE ua_family IS NOT NULL;

CREATE TABLE IF NOT EXISTS valuation_commentary_cache (
    enterprise_number TEXT PRIMARY KEY,
    commentary        TEXT NOT NULL,
    sector_used       TEXT,
    source_used       TEXT,
    lang              VARCHAR(2) DEFAULT 'en',
    generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_valuation_commentary_gen
    ON valuation_commentary_cache(generated_at DESC);

CREATE TABLE IF NOT EXISTS procurement_award (
    id                SERIAL PRIMARY KEY,
    ted_notice_id     TEXT UNIQUE,
    enterprise_number TEXT,
    supplier_name     TEXT,
    supplier_vat      TEXT,
    buyer_name        TEXT,
    award_date        DATE,
    contract_value    NUMERIC(14,2),
    currency          VARCHAR(3) DEFAULT 'EUR',
    cpv_code          TEXT,
    title             TEXT,
    country           VARCHAR(2) DEFAULT 'BE'
);
CREATE INDEX IF NOT EXISTS idx_procurement_award_ent
    ON procurement_award(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_procurement_award_date
    ON procurement_award(award_date DESC);
CREATE INDEX IF NOT EXISTS idx_procurement_award_vat
    ON procurement_award(supplier_vat);

CREATE TABLE IF NOT EXISTS insolvency_case (
    id                SERIAL PRIMARY KEY,
    enterprise_number TEXT NOT NULL,
    docket_number     TEXT UNIQUE,
    case_type         TEXT,
    court             TEXT,
    opened_at         DATE,
    closed_at         DATE,
    status            TEXT,
    curator_name      TEXT,
    last_scraped_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_insolvency_case_ent
    ON insolvency_case(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_insolvency_case_opened
    ON insolvency_case(opened_at DESC);

CREATE TABLE IF NOT EXISTS platform_invoice (
    id                  SERIAL PRIMARY KEY,
    message_id          TEXT UNIQUE,
    sender              TEXT,
    subject             TEXT,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invoice_date        DATE,
    amount_cents        BIGINT,
    currency            VARCHAR(3) DEFAULT 'EUR',
    vendor              TEXT,
    category            TEXT,
    raw_body            TEXT,
    attachment_path     TEXT,
    confirmed           BOOLEAN DEFAULT FALSE,
    parent_category     TEXT,
    child_category      TEXT,
    confidence          REAL,
    reason              TEXT,
    vendor_pattern_id   INTEGER,
    line_items          JSONB,
    classified_at       TIMESTAMPTZ,
    classifier_model    TEXT
);
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS parent_category TEXT;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS child_category TEXT;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS confidence REAL;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS vendor_pattern_id INTEGER;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS line_items JSONB;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ;
ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS classifier_model TEXT;
CREATE INDEX IF NOT EXISTS idx_platform_invoice_received
    ON platform_invoice(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_platform_invoice_date
    ON platform_invoice(invoice_date DESC);
CREATE INDEX IF NOT EXISTS idx_platform_invoice_classified
    ON platform_invoice(classified_at DESC);

CREATE TABLE IF NOT EXISTS company_view_history (
    user_email         TEXT NOT NULL,
    enterprise_number  VARCHAR(10) NOT NULL,
    last_viewed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_viewed_at     TIMESTAMPTZ,
    PRIMARY KEY (user_email, enterprise_number)
);
CREATE INDEX IF NOT EXISTS idx_company_view_history_user
    ON company_view_history(user_email, last_viewed_at DESC);

CREATE MATERIALIZED VIEW IF NOT EXISTS sector_percentiles AS
SELECT fl.enterprise_number,
       substr(ci.nace_code, 1, 2) AS nace2,
       percent_rank() OVER (
           PARTITION BY substr(ci.nace_code, 1, 2)
           ORDER BY fl.revenue NULLS FIRST
       )::real AS rev_rank,
       percent_rank() OVER (
           PARTITION BY substr(ci.nace_code, 1, 2)
           ORDER BY fl.ebitda NULLS FIRST
       )::real AS ebitda_rank,
       percent_rank() OVER (
           PARTITION BY substr(ci.nace_code, 1, 2)
           ORDER BY (CASE WHEN fl.revenue > 0 THEN fl.ebitda / fl.revenue END) NULLS FIRST
       )::real AS margin_rank,
       percent_rank() OVER (
           PARTITION BY substr(ci.nace_code, 1, 2)
           ORDER BY fl.fte_total NULLS FIRST
       )::real AS fte_rank,
       percent_rank() OVER (
           PARTITION BY substr(ci.nace_code, 1, 2)
           ORDER BY fl.fixed_assets NULLS FIRST
       )::real AS fixed_assets_rank,
       COUNT(*) OVER (PARTITION BY substr(ci.nace_code, 1, 2)) AS peer_count
FROM financial_latest fl
JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
WHERE ci.nace_code IS NOT NULL AND length(ci.nace_code) >= 2;
CREATE UNIQUE INDEX IF NOT EXISTS sector_percentiles_pkey
    ON sector_percentiles(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_sector_percentiles_nace2
    ON sector_percentiles(nace2);

CREATE TABLE IF NOT EXISTS invoice_vendor_pattern (
    id               SERIAL PRIMARY KEY,
    pattern          TEXT NOT NULL,
    vendor_canonical TEXT,
    parent_category  TEXT NOT NULL,
    child_category   TEXT,
    priority         INTEGER NOT NULL DEFAULT 0,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at     TIMESTAMPTZ,
    hit_count        INTEGER NOT NULL DEFAULT 0
);
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'invoice_vendor_pattern_pattern_len'
    ) THEN
        BEGIN
            ALTER TABLE invoice_vendor_pattern
                ADD CONSTRAINT invoice_vendor_pattern_pattern_len
                CHECK (length(pattern) BETWEEN 2 AND 200);
        EXCEPTION WHEN check_violation THEN
            NULL;
        END;
    END IF;
END$$;
CREATE INDEX IF NOT EXISTS idx_invoice_vendor_pattern_priority
    ON invoice_vendor_pattern(priority DESC);

CREATE TABLE IF NOT EXISTS invoice_misclassification_log (
    id               SERIAL PRIMARY KEY,
    invoice_id       INTEGER REFERENCES platform_invoice(id) ON DELETE CASCADE,
    old_parent       TEXT,
    old_child        TEXT,
    new_parent       TEXT,
    new_child        TEXT,
    old_vendor       TEXT,
    new_vendor       TEXT,
    old_amount_cents BIGINT,
    new_amount_cents BIGINT,
    corrected_by     TEXT,
    corrected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoice_misclass_invoice
    ON invoice_misclassification_log(invoice_id);
