-- Belgian Company Database — KBO + NBB
-- Phase 1: KBO tables

-- Metadata tracking
CREATE TABLE IF NOT EXISTS meta (
    variable    TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- KBO enterprise (1 row per entity)
CREATE TABLE IF NOT EXISTS enterprise (
    enterprise_number   TEXT PRIMARY KEY,   -- 10 digits, no dots
    status              TEXT NOT NULL,
    juridical_situation TEXT NOT NULL,
    type_of_enterprise  TEXT NOT NULL,      -- 1=legal person, 2=natural person
    juridical_form      TEXT,
    juridical_form_cac  TEXT,
    start_date          TEXT NOT NULL       -- ISO YYYY-MM-DD
);

-- KBO establishment units
CREATE TABLE IF NOT EXISTS establishment (
    establishment_number TEXT PRIMARY KEY,  -- 10 digits, no dots
    start_date           TEXT NOT NULL,
    enterprise_number    TEXT NOT NULL REFERENCES enterprise(enterprise_number)
);

-- KBO denominations (names)
CREATE TABLE IF NOT EXISTS denomination (
    entity_number        TEXT NOT NULL,
    language             TEXT NOT NULL,      -- 1=FR, 2=NL, 3=DE, 4=EN
    type_of_denomination TEXT NOT NULL,      -- 001=official, 002=commercial, 003=abbreviation
    denomination         TEXT NOT NULL,
    PRIMARY KEY (entity_number, language, type_of_denomination)
);

-- KBO addresses
CREATE TABLE IF NOT EXISTS address (
    entity_number       TEXT NOT NULL,
    type_of_address     TEXT NOT NULL,       -- REGO, BRAN
    country_nl          TEXT,
    country_fr          TEXT,
    zipcode             TEXT,
    municipality_nl     TEXT,
    municipality_fr     TEXT,
    street_nl           TEXT,
    street_fr           TEXT,
    house_number        TEXT,
    box                 TEXT,
    extra_address_info  TEXT,
    date_striking_off   TEXT,                -- ISO YYYY-MM-DD or NULL
    PRIMARY KEY (entity_number, type_of_address)
);

-- KBO activities (NACE codes)
CREATE TABLE IF NOT EXISTS activity (
    entity_number   TEXT NOT NULL,
    activity_group  TEXT NOT NULL,
    nace_version    TEXT NOT NULL,
    nace_code       TEXT NOT NULL,
    classification  TEXT NOT NULL,           -- MAIN, SECO, AUXI
    PRIMARY KEY (entity_number, activity_group, nace_version, nace_code, classification)
);

-- KBO contacts
CREATE TABLE IF NOT EXISTS contact (
    entity_number   TEXT NOT NULL,
    entity_contact  TEXT NOT NULL,
    contact_type    TEXT NOT NULL,           -- TEL, EMAIL, WEB
    value           TEXT NOT NULL,
    PRIMARY KEY (entity_number, entity_contact, contact_type, value)
);

-- KBO branches (foreign entities)
CREATE TABLE IF NOT EXISTS branch (
    id                TEXT PRIMARY KEY,
    start_date        TEXT NOT NULL,
    enterprise_number TEXT NOT NULL REFERENCES enterprise(enterprise_number)
);

-- KBO code lookup table
CREATE TABLE IF NOT EXISTS code (
    category    TEXT NOT NULL,
    code        TEXT NOT NULL,
    language    TEXT NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (category, code, language)
);

-- Track which KBO extracts have been applied
CREATE TABLE IF NOT EXISTS kbo_extract_log (
    extract_number  INTEGER PRIMARY KEY,
    extract_type    TEXT NOT NULL,           -- full / update
    applied_at      TEXT NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_enterprise_status ON enterprise(status);
CREATE INDEX IF NOT EXISTS idx_enterprise_juridical_form ON enterprise(juridical_form);
CREATE INDEX IF NOT EXISTS idx_enterprise_juridical_situation ON enterprise(juridical_situation);
CREATE INDEX IF NOT EXISTS idx_enterprise_type ON enterprise(type_of_enterprise);
CREATE INDEX IF NOT EXISTS idx_establishment_enterprise ON establishment(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_denomination_entity ON denomination(entity_number);
CREATE INDEX IF NOT EXISTS idx_denomination_type ON denomination(type_of_denomination);
CREATE INDEX IF NOT EXISTS idx_address_entity ON address(entity_number);
-- Trigram indexes on the address text columns. Without them, the
-- people-search address fallback ILIKEs on `address` (3M+ rows) seq-scan
-- the entire table even with a per-CTE LIMIT cap.
CREATE INDEX IF NOT EXISTS idx_addr_street_nl_trgm ON address USING GIN (street_nl gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_addr_street_fr_trgm ON address USING GIN (street_fr gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_addr_munic_nl_trgm  ON address USING GIN (municipality_nl gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_addr_munic_fr_trgm  ON address USING GIN (municipality_fr gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_address_zipcode ON address(zipcode);
CREATE INDEX IF NOT EXISTS idx_activity_entity ON activity(entity_number);
CREATE INDEX IF NOT EXISTS idx_activity_nace ON activity(nace_code);
CREATE INDEX IF NOT EXISTS idx_activity_classification ON activity(classification);
CREATE INDEX IF NOT EXISTS idx_contact_entity ON contact(entity_number);
CREATE INDEX IF NOT EXISTS idx_branch_enterprise ON branch(enterprise_number);

-- ============================================================
-- Phase 4: NBB financial data tables
-- ============================================================

-- One row per rubric per period per filing.
-- Period: 'N' = fiscal year being reported, 'NM1' = prior year comparison.
CREATE TABLE IF NOT EXISTS financial_data (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,      -- YYYY-NNNNNNNN
    fiscal_year         INTEGER,
    deposit_date        TEXT,               -- ISO YYYY-MM-DD
    filing_model        TEXT,               -- VOL, VKT, MIC, ...
    rubric_code         TEXT NOT NULL,      -- e.g. '70', '9901', '630'
    period              TEXT NOT NULL DEFAULT 'N',   -- 'N' or 'NM1'
    value               REAL,
    PRIMARY KEY (deposit_key, rubric_code, period)
);

CREATE INDEX IF NOT EXISTS idx_financial_enterprise ON financial_data(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_financial_year ON financial_data(enterprise_number, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_financial_rubric ON financial_data(rubric_code);

-- Track which companies have had financials loaded and when
CREATE TABLE IF NOT EXISTS nbb_load_log (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,
    loaded_at           TEXT NOT NULL DEFAULT NOW(),
    rubric_count        INTEGER,
    PRIMARY KEY (enterprise_number, deposit_key)
);

-- financial_summary view: pivot key rubrics into columns for PE screening.
-- One row per filing (current-period values only).
CREATE OR REPLACE VIEW financial_summary AS
SELECT
    f.enterprise_number,
    f.deposit_key,
    f.fiscal_year,
    f.deposit_date,
    f.filing_model,
    -- Income statement
    MAX(CASE WHEN f.rubric_code = '70'     THEN f.value END) AS revenue,
    MAX(CASE WHEN f.rubric_code = '9900'   THEN f.value END) AS gross_margin,
    MAX(CASE WHEN f.rubric_code = '9901'   THEN f.value END) AS ebit,
    MAX(CASE WHEN f.rubric_code = '630'    THEN f.value END) AS da,
    MAX(CASE WHEN f.rubric_code = '9901'   THEN f.value END)
        + COALESCE(MAX(CASE WHEN f.rubric_code = '630' THEN f.value END), 0) AS ebitda,
    MAX(CASE WHEN f.rubric_code = '9904'   THEN f.value END) AS net_profit,
    MAX(CASE WHEN f.rubric_code = '65'     THEN f.value END) AS financial_charges,
    -- Balance sheet
    -- Modern NBB filings use rubric ``21/28`` (intangible + tangible +
    -- financial fixed assets, excluding the deprecated establishment-costs
    -- rubric 20). Empirical: in our DB ``21/28`` has ~900k rows, ``20/28``
    -- has 0. Falling back to ``21/28`` here keeps the column populated.
    COALESCE(
        MAX(CASE WHEN f.rubric_code = '20/28'  THEN f.value END),
        MAX(CASE WHEN f.rubric_code = '21/28'  THEN f.value END)
    ) AS fixed_assets,
    MAX(CASE WHEN f.rubric_code = '20/58'  THEN f.value END) AS total_assets,
    MAX(CASE WHEN f.rubric_code = '10/15'  THEN f.value END) AS equity,
    MAX(CASE WHEN f.rubric_code = '17'     THEN f.value END) AS lt_debt,
    MAX(CASE WHEN f.rubric_code = '170/4'  THEN f.value END) AS lt_financial_debt,
    MAX(CASE WHEN f.rubric_code = '43'     THEN f.value END) AS st_financial_debt,
    MAX(CASE WHEN f.rubric_code = '54/58'  THEN f.value END) AS cash,
    MAX(CASE WHEN f.rubric_code = '50/53'  THEN f.value END) AS current_investments,
    -- Working capital
    MAX(CASE WHEN f.rubric_code = '3'      THEN f.value END) AS inventories,
    MAX(CASE WHEN f.rubric_code = '40/41'  THEN f.value END) AS trade_receivables,
    MAX(CASE WHEN f.rubric_code = '44'     THEN f.value END) AS trade_payables,
    -- Employment
    MAX(CASE WHEN f.rubric_code = '9087'   THEN f.value END) AS fte_total,
    MAX(CASE WHEN f.rubric_code = '9097'   THEN f.value END) AS fte_belgium,
    MAX(CASE WHEN f.rubric_code = '62'     THEN f.value END) AS personnel_costs
FROM financial_data f
WHERE f.period = 'N'
GROUP BY f.enterprise_number, f.deposit_key, f.fiscal_year, f.deposit_date, f.filing_model;

-- ============================================================
-- company_master view: enterprise + official name + registered address + main NACE
-- (must be defined before pe_screen which depends on it)
CREATE OR REPLACE VIEW company_master AS
SELECT
    e.enterprise_number,
    e.status,
    e.juridical_situation,
    e.type_of_enterprise,
    e.juridical_form,
    e.start_date,
    d.denomination AS name,
    d.language AS name_language,
    a.zipcode,
    a.municipality_nl,
    a.municipality_fr,
    a.street_nl,
    a.street_fr,
    a.house_number,
    a.box,
    act.nace_code,
    act.nace_version
FROM enterprise e
LEFT JOIN denomination d
    ON d.entity_number = e.enterprise_number
    AND d.type_of_denomination = '001'
    AND d.language = (
        CASE
            WHEN EXISTS (SELECT 1 FROM denomination d2
                         WHERE d2.entity_number = e.enterprise_number
                         AND d2.type_of_denomination = '001'
                         AND d2.language = '2') THEN '2'   -- prefer NL
            WHEN EXISTS (SELECT 1 FROM denomination d2
                         WHERE d2.entity_number = e.enterprise_number
                         AND d2.type_of_denomination = '001'
                         AND d2.language = '1') THEN '1'   -- then FR
            ELSE (SELECT MIN(d2.language) FROM denomination d2
                  WHERE d2.entity_number = e.enterprise_number
                  AND d2.type_of_denomination = '001')
        END
    )
LEFT JOIN address a
    ON a.entity_number = e.enterprise_number
    AND a.type_of_address = 'REGO'
LEFT JOIN activity act
    ON act.entity_number = e.enterprise_number
    AND act.classification = 'MAIN'
    AND act.nace_version = (
        SELECT MAX(act2.nace_version) FROM activity act2
        WHERE act2.entity_number = e.enterprise_number
        AND act2.classification = 'MAIN'
    );

-- ============================================================
-- Phase 5: PE screening view (KBO + NBB combined)
-- ============================================================

CREATE OR REPLACE VIEW pe_screen AS
SELECT
    c.enterprise_number,
    c.name,
    c.status,
    c.juridical_form,
    c.start_date        AS founding_date,
    c.zipcode,
    c.municipality_nl,
    c.nace_code,
    fs.deposit_key,
    fs.fiscal_year,
    fs.filing_model,
    fs.revenue,
    fs.ebit,
    fs.da,
    fs.ebitda,
    fs.net_profit,
    fs.equity,
    fs.lt_financial_debt,
    fs.st_financial_debt,
    fs.cash,
    fs.total_assets,
    fs.fte_total,
    fs.personnel_costs,
    -- Derived metrics
    CASE WHEN fs.revenue > 0 THEN ROUND((fs.ebitda / fs.revenue * 100)::numeric, 1) END AS ebitda_margin_pct,
    CASE WHEN fs.revenue > 0 THEN ROUND((fs.net_profit / fs.revenue * 100)::numeric, 1) END AS net_margin_pct,
    CASE WHEN fs.equity  > 0 THEN ROUND((fs.net_profit / fs.equity * 100)::numeric, 1) END AS roe_pct,
    (COALESCE(fs.lt_financial_debt, 0) + COALESCE(fs.st_financial_debt, 0))
        - (COALESCE(fs.cash, 0) + COALESCE(fs.current_investments, 0)) AS net_debt,
    CASE WHEN fs.fte_total > 0 THEN ROUND((fs.revenue / fs.fte_total)::numeric) END AS revenue_per_fte
FROM (
    SELECT enterprise_number, name, status, juridical_form, start_date,
           zipcode, municipality_nl, MIN(nace_code) AS nace_code
    FROM company_master
    GROUP BY enterprise_number, name, status, juridical_form, start_date,
             zipcode, municipality_nl
) c
JOIN financial_summary fs ON fs.enterprise_number = c.enterprise_number;

-- ============================================================
-- Staatsblad (Belgian Official Gazette) publications
-- ============================================================

CREATE TABLE IF NOT EXISTS staatsblad_publication (
    enterprise_number   TEXT NOT NULL,
    pub_date            TEXT NOT NULL,          -- YYYY-MM-DD
    pub_type            TEXT,                   -- e.g. ONTSLAGEN - BENOEMINGEN
    reference           TEXT,                   -- e.g. 0123639
    pdf_url             TEXT,                   -- relative path on ejustice
    entity_name         TEXT,                   -- name as published
    loaded_at           TEXT NOT NULL DEFAULT NOW(),
    PRIMARY KEY (enterprise_number, pub_date, reference)
);

CREATE INDEX IF NOT EXISTS idx_staatsblad_ent ON staatsblad_publication(enterprise_number);

-- ============================================================
-- Company structure: administrators, shareholders, subsidiaries
-- ============================================================

CREATE TABLE IF NOT EXISTS administrator (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,
    fiscal_year         TEXT,
    person_type         TEXT,               -- 'legal' or 'natural'
    name                TEXT,
    role                TEXT,               -- NBB function code (fct:m10, ...)
    identifier          TEXT,               -- CBE number of legal entity
    mandate_start       TEXT,
    mandate_end         TEXT,
    representative_name TEXT,               -- permanent rep for legal persons
    PRIMARY KEY (enterprise_number, deposit_key, name, role)
);

CREATE INDEX IF NOT EXISTS idx_admin_ent ON administrator(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_admin_name_type ON administrator(person_type, name);
CREATE INDEX IF NOT EXISTS idx_admin_name_trgm ON administrator USING GIN (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS participating_interest (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,
    fiscal_year         TEXT,
    name                TEXT,
    identifier          TEXT,               -- CBE / foreign reg. number
    address             TEXT,
    country             TEXT,
    ownership_pct       REAL,
    equity_value        REAL,
    net_result          REAL,
    PRIMARY KEY (enterprise_number, deposit_key, name)
);

CREATE INDEX IF NOT EXISTS idx_pi_ent ON participating_interest(enterprise_number);
-- Reverse lookup: "which parents declare this CBE as a PI?" — used by both
-- the spiderweb (network.py) and the parent_companies field on /structure.
-- Partial: identifier is NULL for natural persons / foreign entities without
-- a CBE; skipping those halves the index size for free.
CREATE INDEX IF NOT EXISTS idx_pi_identifier ON participating_interest(identifier)
  WHERE identifier IS NOT NULL;

CREATE TABLE IF NOT EXISTS shareholder (
    enterprise_number       TEXT NOT NULL,
    deposit_key             TEXT NOT NULL,
    fiscal_year             TEXT,
    shareholder_type        TEXT,           -- 'entity' or 'individual'
    name                    TEXT,
    identifier              TEXT,           -- CBE or foreign reg. number
    address                 TEXT,
    shares_held             REAL,
    ownership_pct           REAL,
    PRIMARY KEY (enterprise_number, deposit_key, name)
);

CREATE INDEX IF NOT EXISTS idx_sh_ent ON shareholder(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_sh_name_trgm ON shareholder USING GIN (name gin_trgm_ops);

-- ============================================================
-- Materialized/pre-computed tables (populated by pipeline.py)
-- ============================================================

-- Latest financial snapshot per company (one row per enterprise_number)
CREATE TABLE IF NOT EXISTS financial_latest (
    enterprise_number   TEXT PRIMARY KEY,
    fiscal_year         INTEGER,
    filing_model        TEXT,
    revenue             REAL,
    ebit                REAL,
    da                  REAL,
    ebitda              REAL,
    net_profit          REAL,
    equity              REAL,
    lt_financial_debt   REAL,
    st_financial_debt   REAL,
    cash                REAL,
    total_assets        REAL,
    fixed_assets        REAL,                 -- rubric 20/28
    fte_total           REAL,
    personnel_costs     REAL
);
-- Backfill column for live DBs that pre-date this addition.
ALTER TABLE financial_latest ADD COLUMN IF NOT EXISTS fixed_assets REAL;

-- All financial years per company (materialized from financial_summary view)
CREATE TABLE IF NOT EXISTS financial_by_year (
    enterprise_number   TEXT NOT NULL,
    fiscal_year         INTEGER NOT NULL,
    filing_model        TEXT,
    revenue             REAL,
    ebit                REAL,
    da                  REAL,
    ebitda              REAL,
    net_profit          REAL,
    equity              REAL,
    lt_financial_debt   REAL,
    st_financial_debt   REAL,
    cash                REAL,
    total_assets        REAL,
    fte_total           REAL,
    personnel_costs     REAL,
    PRIMARY KEY (enterprise_number, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_fby_ent  ON financial_by_year(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_fby_year ON financial_by_year(fiscal_year);

-- Denormalized company info for fast screener / stats joins
CREATE TABLE IF NOT EXISTS company_info (
    enterprise_number   TEXT PRIMARY KEY,
    name                TEXT,
    city                TEXT,
    zipcode             TEXT,
    nace_code           TEXT
);

CREATE INDEX IF NOT EXISTS idx_ci_nace    ON company_info(nace_code);
CREATE INDEX IF NOT EXISTS idx_ci_zipcode ON company_info(zipcode);

-- NACE 2-digit sector descriptions (for display in UI)
CREATE TABLE IF NOT EXISTS nace_lookup (
    nace_code       TEXT PRIMARY KEY,
    description     TEXT,
    company_count   INTEGER
);

-- ============================================================
-- User-facing tables (favourites, feedback)
-- ============================================================

CREATE TABLE IF NOT EXISTS favourite (
    enterprise_number   TEXT PRIMARY KEY,
    added_at            TEXT NOT NULL DEFAULT NOW(),
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id                  SERIAL PRIMARY KEY,
    type                TEXT NOT NULL,
    page                TEXT,
    description         TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Vlerick M&A Monitor reference multiples (for valuation tab)
-- ============================================================
-- bucket_type: 'size' (deal-size bracket) | 'sector' (industry bucket) | 'overall'
-- bucket_key:  'lt_5m' | '5_20m' | '20_50m' | '50_100m' | 'gt_100m' | 'overall'
--              | 'technology' | 'pharmaceutical' | 'healthcare' | ... (sectors)
CREATE TABLE IF NOT EXISTS vlerick_multiple (
    year            INTEGER NOT NULL,
    bucket_type     TEXT NOT NULL,
    bucket_key      TEXT NOT NULL,
    multiple        REAL NOT NULL,
    source_note     TEXT,
    PRIMARY KEY (year, bucket_type, bucket_key)
);

-- NACE 2-digit prefix → Vlerick sector bucket. Seeded from NACE Rev 2.
CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (
    nace_prefix     TEXT PRIMARY KEY,
    vlerick_sector  TEXT NOT NULL
);

-- ============================================================
-- AI / LLM observability
-- ============================================================
-- Translation cache: persists translate_cached / translate_cached_json
-- results so cached AI outputs (enrichments, valuation commentary,
-- person enrichments) don't re-pay OpenRouter after a container restart.
-- Read + written inline by backend/ai_client.py. 30-day TTL; rows older
-- than that are treated as stale and re-translated.
CREATE TABLE IF NOT EXISTS translation_cache (
    cbe             TEXT NOT NULL,
    kind            TEXT NOT NULL,
    lang            TEXT NOT NULL,
    value           TEXT NOT NULL,
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cbe, kind, lang)
);
CREATE INDEX IF NOT EXISTS idx_translation_cache_gen ON translation_cache(generated_at);

-- Per-call OpenRouter spend log. Captures real `usage.cost` returned
-- by OpenRouter when `usage: {include: true}` is passed, so the admin
-- LLM cost panel can sum true billed amounts instead of heuristic
-- per-call estimates. `endpoint` comes from a request-scoped contextvar
-- set by middleware; null for background / non-request calls.
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                  SERIAL PRIMARY KEY,
    ts                  TIMESTAMP NOT NULL DEFAULT NOW(),
    endpoint            TEXT,
    model               TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    cost_usd            REAL
);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_ts ON llm_call_log(ts);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_endpoint ON llm_call_log(endpoint);

-- ============================================================
-- Sector percentile rankings (for screener pills + radar chart)
-- ============================================================
-- Precomputed per-enterprise percentile within its NACE-2 sector.
-- Values are 0.0 (worst) to 1.0 (best). NULL metric rows get the
-- lowest rank (NULLS FIRST) — they're placed at the bottom rank so
-- companies with disclosed revenue outrank companies that didn't
-- disclose. Refresh via REFRESH MATERIALIZED VIEW CONCURRENTLY after
-- NBB batch loads (nbb_batch_pipeline.py triggers this).
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
           ORDER BY (CASE WHEN fl.revenue > 0
                          THEN fl.ebitda / fl.revenue END) NULLS FIRST
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

-- ============================================================
-- Company view history (for "what changed since last visit")
-- ============================================================
-- One row per (user, company). Each view shifts last → prev and
-- updates last. The prev timestamp is what "Since last visit" uses
-- as the diff baseline on the next visit. Anonymous users are
-- keyed by the hashed IP (same scheme as activity_log).
CREATE TABLE IF NOT EXISTS company_view_history (
    user_email         TEXT NOT NULL,
    enterprise_number  VARCHAR(10) NOT NULL,
    last_viewed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_viewed_at     TIMESTAMPTZ,
    PRIMARY KEY (user_email, enterprise_number)
);
CREATE INDEX IF NOT EXISTS idx_company_view_history_user
    ON company_view_history(user_email, last_viewed_at DESC);

-- ============================================================
-- activity_log indexes (critical — every /api/* hits this table)
-- ============================================================
-- The table is created elsewhere (backend bootstrap). Without these
-- indexes, TierLimitMiddleware does a seq-scan on every AI call and
-- admin analytics pages take seconds. CREATE INDEX IF NOT EXISTS is
-- idempotent. CONCURRENTLY would be safer but can't run inside a
-- transaction block; the schema is only applied at boot with the
-- app quiesced, so plain CREATE is fine.
CREATE INDEX IF NOT EXISTS idx_activity_log_user_date
    ON activity_log(user_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_endpoint_date
    ON activity_log(endpoint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_date
    ON activity_log(created_at DESC);

-- ============================================================
-- Platform invoices (from invoice@datasnoop.be inbox)
-- ============================================================
-- `scripts/invoice_ingest.py` reads the invoice@ IMAP mailbox nightly,
-- extracts amounts, and stores one row per email/invoice. Amounts are
-- best-effort from regex on body / PDF text; operator can override via
-- admin UI (not yet implemented). `message_id` de-dupes re-ingestion.
CREATE TABLE IF NOT EXISTS platform_invoice (
    id              SERIAL PRIMARY KEY,
    message_id      TEXT UNIQUE,            -- RFC822 Message-ID header
    sender          TEXT,
    subject         TEXT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invoice_date    DATE,
    amount_cents    BIGINT,                 -- NULL if parser couldn't extract
    currency        VARCHAR(3) DEFAULT 'EUR',
    vendor          TEXT,                   -- extracted best-effort
    category        TEXT,                   -- operator-assigned (hosting, llm, etc.)
    raw_body        TEXT,                   -- first N KB of body for audit
    attachment_path TEXT,                   -- relative path if we saved a PDF
    confirmed       BOOLEAN DEFAULT FALSE   -- operator reviewed + confirmed
);
CREATE INDEX IF NOT EXISTS idx_platform_invoice_received
    ON platform_invoice(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_platform_invoice_date
    ON platform_invoice(invoice_date DESC);

-- ============================================================
-- Open data: TED procurement (public-sector contracts won)
-- ============================================================
-- EU Tenders Electronic Daily — award notices with supplier VAT/name.
-- We only store Belgian awards. Joined to enterprise via VAT.
-- Source: data.europa.eu/data/datasets/ted-csv  (CSV monthly exports)
-- Ingested by scripts/open_data_ted.py
CREATE TABLE IF NOT EXISTS procurement_award (
    id              SERIAL PRIMARY KEY,
    ted_notice_id   TEXT UNIQUE,               -- TED ND-* identifier
    enterprise_number TEXT,                    -- 10-digit CBE (joined from VAT)
    supplier_name   TEXT,
    supplier_vat    TEXT,
    buyer_name      TEXT,                      -- public authority
    award_date      DATE,
    contract_value  NUMERIC(14,2),             -- in EUR (converted if needed)
    currency        VARCHAR(3) DEFAULT 'EUR',
    cpv_code        TEXT,                      -- main CPV classification
    title           TEXT,
    country         VARCHAR(2) DEFAULT 'BE'
);
CREATE INDEX IF NOT EXISTS idx_procurement_award_ent
    ON procurement_award(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_procurement_award_date
    ON procurement_award(award_date DESC);
CREATE INDEX IF NOT EXISTS idx_procurement_award_vat
    ON procurement_award(supplier_vat);

-- ============================================================
-- Open data: Regsol insolvency register
-- ============================================================
-- Belgian central solvency register (bankruptcies + judicial reorg since
-- 1 May 2018). Scraped from regsol.be nightly.
CREATE TABLE IF NOT EXISTS insolvency_case (
    id                SERIAL PRIMARY KEY,
    enterprise_number TEXT NOT NULL,
    docket_number     TEXT UNIQUE,        -- Regsol case ID
    case_type         TEXT,               -- 'bankruptcy' / 'reorganisation' / 'closure'
    court             TEXT,
    opened_at         DATE,
    closed_at         DATE,
    status            TEXT,               -- 'open' / 'closed' / 'ended'
    curator_name      TEXT,
    last_scraped_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_insolvency_case_ent
    ON insolvency_case(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_insolvency_case_opened
    ON insolvency_case(opened_at DESC);

-- ============================================================
-- Stage 3: Structured Staatsblad events (LLM-extracted)
-- ============================================================
-- Extracted via Claude Haiku 4.5 + Anthropic batch API from the
-- full OCR'd filing text. Eight event categories covering the
-- board-level changes a PE deal-sourcer cares about. Replaces the
-- earlier regex-classifier table of the same name.
--
-- The v1 table (pre-Stage 3) had columns (id, enterprise_number,
-- reference, pub_date, event_type, subject_name, raw_title,
-- extracted_at). If we find it, drop it — the regex classifier is
-- being retired in favour of the LLM extractor.
DO $staatsblad_event_migrate$
BEGIN
    -- Only drop when the old regex-classifier table is present: require
    -- both (a) no `pub_reference` column AND (b) the old `subject_name`
    -- column exists. Guards against accidentally dropping a partially-
    -- created new table, or a future variant that just happens to lack
    -- one column.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'staatsblad_event'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'staatsblad_event' AND column_name = 'pub_reference'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'staatsblad_event' AND column_name = 'subject_name'
    ) THEN
        DROP TABLE staatsblad_event CASCADE;
    END IF;
END
$staatsblad_event_migrate$;

CREATE TABLE IF NOT EXISTS staatsblad_event (
    id                SERIAL PRIMARY KEY,
    enterprise_number TEXT NOT NULL,
    pub_reference     TEXT NOT NULL,       -- staatsblad_publication.reference
    pub_date          DATE NOT NULL,
    event_type        TEXT NOT NULL,
    sub_type          TEXT,
    event_date        DATE,                -- effective date if stated in filing, else NULL
    person_name       TEXT,
    person_role       TEXT,
    entity_name       TEXT,
    amount_eur        NUMERIC,
    amount_shares     NUMERIC,
    summary           TEXT NOT NULL,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extraction_model  TEXT NOT NULL,
    CONSTRAINT staatsblad_event_type_check CHECK (event_type IN (
        'admin_event', 'capital_event', 'share_transfer', 'ownership_change',
        'ma_event', 'liquidation_event', 'corporate_change', 'other_notable'
    ))
);

CREATE INDEX IF NOT EXISTS idx_staatsblad_event_ent_date
    ON staatsblad_event(enterprise_number, pub_date DESC);
CREATE INDEX IF NOT EXISTS idx_staatsblad_event_type_date
    ON staatsblad_event(event_type, pub_date DESC);
CREATE INDEX IF NOT EXISTS idx_staatsblad_event_person_trgm
    ON staatsblad_event USING GIN (person_name gin_trgm_ops);
-- Dedup guard: same (cbe, pub_reference, event_type, person_name, entity_name)
-- tuple is the same event; extractor writes ON CONFLICT DO NOTHING.
-- NULLs NOT DISTINCT requires Postgres 15+; fall back to an IS-NOT-NULL
-- partial index + an IS-NULL partial index to cover all cases.
CREATE UNIQUE INDEX IF NOT EXISTS idx_staatsblad_event_dedup
    ON staatsblad_event (
        enterprise_number, pub_reference, event_type,
        COALESCE(person_name, ''), COALESCE(entity_name, '')
    );

-- Full-text search helper — GIN on a computed tsvector of
-- summary + person_name + entity_name. Used by /api/events/search as a
-- trigram/keyword fallback to blend with pgvector cosine results.
CREATE INDEX IF NOT EXISTS idx_staatsblad_event_fts
    ON staatsblad_event USING GIN (to_tsvector(
        'simple',
        coalesce(summary, '') || ' ' ||
        coalesce(person_name, '') || ' ' ||
        coalesce(entity_name, '')
    ));


-- Full body text per filing (fitz or OCR). Stored once and re-read by
-- AI-insights / excerpt-reconstruction instead of re-downloading the PDF.
CREATE TABLE IF NOT EXISTS staatsblad_publication_text (
    pub_reference      TEXT PRIMARY KEY,
    enterprise_number  TEXT NOT NULL,
    body_text          TEXT NOT NULL,
    extraction_source  TEXT,                -- 'fitz' | 'easyocr' | 'both_empty'
    extracted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_staatsblad_pubtext_ent
    ON staatsblad_publication_text(enterprise_number);


-- Backfill checkpoint. Every submitted filing writes one row so a resumed
-- run skips already-processed refs.
CREATE TABLE IF NOT EXISTS staatsblad_backfill_progress (
    run_id         TEXT NOT NULL,
    pub_reference  TEXT NOT NULL,
    status         TEXT NOT NULL,            -- 'queued' | 'ocr_done' | 'extracted' | 'failed'
    error          TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, pub_reference)
);
CREATE INDEX IF NOT EXISTS idx_staatsblad_backfill_status
    ON staatsblad_backfill_progress(run_id, status);


-- pgvector extension for semantic search on events (Phase 3e).
-- The extension is a no-op if already installed.
CREATE EXTENSION IF NOT EXISTS vector;

-- 256-dim embedding per event. 256 matches the existing
-- `text-embedding-3-small` convention used elsewhere in the codebase.
-- ON DELETE CASCADE so re-processing (e.g. re-running the extractor with a
-- newer prompt) cleans up old embeddings when events are replaced.
CREATE TABLE IF NOT EXISTS staatsblad_event_embedding (
    event_id   INTEGER PRIMARY KEY REFERENCES staatsblad_event(id) ON DELETE CASCADE,
    embedding  vector(256) NOT NULL,
    model      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- IVFFlat for cosine distance. `lists = 100` is fine for 10k-500k rows;
-- Phase 4a backfill will be under 100k.
CREATE INDEX IF NOT EXISTS idx_staatsblad_event_embedding_cos
    ON staatsblad_event_embedding USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);


-- ============================================================
-- Phase 1: Semantic enrichment orchestrator
-- ============================================================
-- The bulk enrichment pipeline writes a factual JSONB summary per
-- company into `company_enrichment.bulk_summary` (separate from the
-- narrative `ai_insights` column used on profile pages). The embedding
-- is derived from bulk_summary; the search endpoint filters by
-- bulk_confidence. See `docs/architecture.md` for the full flow and
-- `plans/i-want-to-explore-delightful-storm.md` for the rollout plan.

-- company_enrichment.bulk_summary columns.
-- `company_enrichment` is created at runtime by
-- `backend/routers/companies/enrichment.py::_ensure_enrichment_table`;
-- these ALTERs are idempotent and safe even if that runtime creator
-- hasn't fired yet. Wrapped in a DO block so a missing parent table
-- degrades to a notice instead of breaking the startup migration.
DO $bulk_enrichment_cols$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'company_enrichment'
    ) THEN
        ALTER TABLE company_enrichment
            ADD COLUMN IF NOT EXISTS bulk_summary       JSONB,
            ADD COLUMN IF NOT EXISTS bulk_summary_at    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS bulk_website_hash  TEXT,
            ADD COLUMN IF NOT EXISTS bulk_website_url   TEXT,
            ADD COLUMN IF NOT EXISTS bulk_confidence    TEXT;
    END IF;
END
$bulk_enrichment_cols$;

-- Postgres-backed work queue for the bulk enrichment worker.
-- Claimed with FOR UPDATE SKIP LOCKED so multiple workers (or
-- a single worker with WORKER_CONCURRENCY>1 using concurrent
-- asyncio tasks) don't grab the same job. Dead rows (attempts
-- exhausted) surface on the admin page.
CREATE TABLE IF NOT EXISTS enrichment_job (
    enterprise_number   VARCHAR(10) PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'queued',
        -- 'queued' | 'claimed' | 'done' | 'failed' | 'dead'
    priority            INTEGER NOT NULL DEFAULT 0,
        -- Higher = processed sooner. Tier-1 big = 100, tier-2 = 50,
        -- tier-3 with web = 20, tier-3 no-web = 10.
    attempts            INTEGER NOT NULL DEFAULT 0,
    claimed_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    last_error          TEXT,
    enqueued_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_enrichment_job_status
    ON enrichment_job(status, priority DESC, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_job_finished
    ON enrichment_job(finished_at DESC);

-- Query embedding cache — /api/search/semantic computes a query
-- embedding once per distinct (lowered, trimmed) query string and
-- reuses it for 30 days. `query_hash` = sha256(lower(q)).
CREATE TABLE IF NOT EXISTS query_embedding_cache (
    query_hash          TEXT PRIMARY KEY,
    query_text          TEXT NOT NULL,
    embedding           vector(256) NOT NULL,
    model               TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_created
    ON query_embedding_cache(created_at);

-- Externalised aggregator skip-list (was a hardcoded constant in
-- `backend/scraper.py::_SKIP_DOMAINS`). `kind` distinguishes domain
-- match from path-substring match so discovery can filter both.
-- Maintained via the admin enrichment page; read from DB at each
-- worker claim cycle (no in-memory caching — the table is small).
CREATE TABLE IF NOT EXISTS aggregator_skiplist (
    id                  SERIAL PRIMARY KEY,
    pattern             TEXT NOT NULL,
    kind                TEXT NOT NULL DEFAULT 'domain',
        -- 'domain' | 'path' — domain matches against parsed netloc,
        -- path matches as a substring on the full URL path.
    reason              TEXT,
    added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by            TEXT,
    UNIQUE (pattern, kind)
);

-- Seed the skip-list with the v3-validated aggregator patterns. ON
-- CONFLICT DO NOTHING so re-running the schema is a no-op for seeds.
INSERT INTO aggregator_skiplist (pattern, kind, reason, added_by) VALUES
    ('pappers.be',           'domain', 'seed: KBO aggregator',             'seed'),
    ('bsearch.be',           'domain', 'seed: business directory',         'seed'),
    ('handelsgids.be',       'domain', 'seed: business directory',         'seed'),
    ('infobel.be',           'domain', 'seed: directory',                  'seed'),
    ('immoweb.be',           'domain', 'seed: real-estate listing',        'seed'),
    ('lemariagedelouise.be', 'domain', 'seed: wedding-vendor listing',     'seed'),
    ('economie.fgov.be',     'domain', 'seed: KBO portal',                 'seed'),
    ('kompass.com',          'domain', 'seed: B2B directory',              'seed'),
    ('europages.com',        'domain', 'seed: B2B directory',              'seed'),
    ('dnb.com',              'domain', 'seed: credit directory',           'seed'),
    ('companyweb.be',        'domain', 'seed: directory',                  'seed'),
    ('staatsbladmonitor.be', 'domain', 'seed: gazette mirror',             'seed'),
    ('trends.knack.be',      'domain', 'seed: press directory',            'seed'),
    ('/bedrijvengids/',      'path',   'seed: municipal business index',   'seed'),
    ('/annuaire/',           'path',   'seed: FR municipal directory',     'seed'),
    ('/infrastructuur-',     'path',   'seed: municipal infrastructure',   'seed')
ON CONFLICT (pattern, kind) DO NOTHING;

-- Enrichment worker metadata (kill switch, daily spend, etc.).
-- The `meta` table already exists (top of this file). Keys used by
-- the worker:
--   enrichment_enabled       'true' | 'false' — master kill switch
--   enrichment_daily_budget  USD ceiling per UTC day, e.g. '10'
-- Spend tracking is derived on the fly from llm_call_log (endpoint
-- starts with '/bulk-enrichment/'), so there is no persistent
-- `enrichment_spend` table — it recomputes on admin-page load.


-- ============================================================================
-- Staatsblad bulk-scrape queue (Phase B backfill of ejustice metadata)
-- ============================================================================
-- One row per CBE we still need to scrape from ejustice.just.fgov.be.
-- The bulk scraper (`scripts/staatsblad_bulk_scrape.py`) dequeues with
-- `FOR UPDATE SKIP LOCKED` so multiple concurrent async workers can
-- claim disjoint CBEs safely. Mirrors the enrichment_job pattern.
--
-- Seeded from: SELECT enterprise_number FROM financial_latest
--              WHERE enterprise_number NOT IN staatsblad_publication
-- via `--seed` on the scraper, or by `scripts/staatsblad_bulk_seed.py`.
--
-- Status transitions:
--   pending     -> in_progress (on dequeue)
--   in_progress -> done         (on 200 + parseable HTML written)
--   in_progress -> pending      (on retryable error, attempts < 3)
--   in_progress -> failed       (on 3rd failure OR non-retryable)
--
-- Stale-claim recovery: rows stuck in 'in_progress' with
-- locked_at < NOW() - 10 min are reset to 'pending' by the worker's
-- periodic release step (mirrors enrichment_queue.release_stale).
CREATE TABLE IF NOT EXISTS staatsblad_bulk_queue (
    cbe           TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'done', 'failed')),
    attempts      INT NOT NULL DEFAULT 0,
    last_error    TEXT,
    locked_at     TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    pubs_found    INT,
    enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial index for fast dequeue (only pending rows matter).
CREATE INDEX IF NOT EXISTS idx_staatsblad_bulk_queue_pending
    ON staatsblad_bulk_queue (enqueued_at)
    WHERE status = 'pending';

-- Index for stale-claim sweeper.
CREATE INDEX IF NOT EXISTS idx_staatsblad_bulk_queue_inprogress
    ON staatsblad_bulk_queue (locked_at)
    WHERE status = 'in_progress';


-- ============================================================================
-- Public API v1 — customer-facing financials API
-- ============================================================================
-- Authenticated by API key (Bearer <token>). Stores SHA-256 hash only —
-- the raw token is shown once at issuance time by
-- `scripts/issue_api_key.py` and never reconstructable from the DB.
-- The `key_prefix` column stores the first 12 chars of the raw token in
-- plaintext for human identification (e.g. `dsk_live_K9p`) — those 12
-- chars are not enough to reconstruct the secret. `daily_cap` is a
-- circuit-breaker, not a paid quota: free during the test, but caps
-- runaway scripts. `disabled_at` lets us revoke without deleting (so
-- the audit trail in `api_call_log` keeps its FK).
CREATE TABLE IF NOT EXISTS api_keys (
    id              SERIAL PRIMARY KEY,
    key_hash        TEXT NOT NULL UNIQUE,    -- hex-encoded SHA-256 of the token
    key_prefix      TEXT NOT NULL,           -- first 12 chars of raw token, for ID
    label           TEXT NOT NULL,           -- e.g. "Customer X webshop"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at     TIMESTAMPTZ,
    daily_cap       INTEGER NOT NULL DEFAULT 10000,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);


-- One row per public-API call. Used for usage monitoring and audit. The
-- daily-cap check counts rows in this table for the calling key in the
-- last 24h, so the (api_key_id, created_at) index is load-bearing.
-- Logged status_code lets us separate successful lookups, 404s, and
-- 4xx/5xx for monitoring.
CREATE TABLE IF NOT EXISTS api_call_log (
    id              BIGSERIAL PRIMARY KEY,
    api_key_id      INTEGER NOT NULL REFERENCES api_keys(id),
    vat_queried     TEXT,                    -- normalized 10-digit CBE, NULL on auth failures
    endpoint        TEXT NOT NULL,
    status_code     INTEGER NOT NULL,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_call_log_key_date
    ON api_call_log(api_key_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_call_log_date
    ON api_call_log(created_at DESC);
