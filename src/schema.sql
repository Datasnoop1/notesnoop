-- BASELINE_AS_OF: 2026-04-28
-- Includes migrations through 2026-04-28_pi_identifier_index.sql
-- Belgian Company Database — KBO + NBB
-- Phase 1: KBO tables

CREATE EXTENSION IF NOT EXISTS pg_trgm;

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

CREATE TABLE IF NOT EXISTS governance_load_log (
    enterprise_number   TEXT NOT NULL,
    deposit_key         TEXT NOT NULL,
    status              TEXT NOT NULL,
    attempts            INT NOT NULL DEFAULT 0,
    last_error          TEXT,
    counts_json         JSONB,
    last_attempt_at     TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (enterprise_number, deposit_key),
    CONSTRAINT governance_load_log_status_check
        CHECK (status IN ('ok', 'error')),
    CONSTRAINT governance_load_log_attempts_check
        CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_governance_load_retry
    ON governance_load_log(status, next_retry_at)
    WHERE status = 'error';

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
    valid_from          DATE,               -- NULL = unknown start; treated as in-force by current/as-of views
    valid_to            DATE,               -- exclusive end; NBB inclusive mandate_end is stored as +1 day
    valid_from_provenance TEXT,
    valid_to_provenance   TEXT,
    source_deposit_date DATE,
    recorded_from       TIMESTAMPTZ DEFAULT NOW(),
    recorded_to         TIMESTAMPTZ,
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
    valid_from          DATE,               -- NULL = unknown start; treated as in-force by current/as-of views
    valid_to            DATE,               -- exclusive end
    valid_from_provenance TEXT,
    valid_to_provenance   TEXT,
    source_deposit_date DATE,
    recorded_from       TIMESTAMPTZ DEFAULT NOW(),
    recorded_to         TIMESTAMPTZ,
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
    valid_from              DATE,           -- NULL = unknown start; treated as in-force by current/as-of views
    valid_to                DATE,           -- exclusive end
    valid_from_provenance   TEXT,
    valid_to_provenance     TEXT,
    source_deposit_date     DATE,
    recorded_from           TIMESTAMPTZ DEFAULT NOW(),
    recorded_to             TIMESTAMPTZ,
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
    enterprise_number   TEXT,
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
    fte_total           REAL,
    personnel_costs     REAL
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
    source          TEXT NOT NULL DEFAULT 'vlerick',
    year            INTEGER NOT NULL,
    bucket_type     TEXT NOT NULL,
    bucket_key      TEXT NOT NULL,
    multiple        REAL NOT NULL,
    source_note     TEXT,
    CONSTRAINT vlerick_multiple_multi_pkey
        PRIMARY KEY (source, year, bucket_type, bucket_key)
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
-- Without these indexes, TierLimitMiddleware does a seq-scan on every
-- AI call and admin analytics pages take seconds. CREATE INDEX IF NOT
-- EXISTS is idempotent. CONCURRENTLY would be safer but can't run
-- inside a transaction block; the schema is only applied at boot with
-- the app quiesced, so plain CREATE is fine.
CREATE TABLE IF NOT EXISTS activity_log (
    id              SERIAL PRIMARY KEY,
    user_email      TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    method          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      TEXT,
    ua_family       TEXT,
    device_type     TEXT,
    country_code    VARCHAR(2),
    request_origin  TEXT,
    public_path     TEXT,
    bot_family      TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_log_user_date
    ON activity_log(user_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_endpoint_date
    ON activity_log(endpoint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_date
    ON activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_origin_date
    ON activity_log(request_origin, created_at DESC)
    WHERE request_origin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_activity_log_bot_date
    ON activity_log(bot_family, created_at DESC)
    WHERE bot_family IS NOT NULL;

-- Passive public traffic audit populated from nginx access logs. Raw IP
-- addresses, raw user agents, and URL query strings are not stored.
CREATE TABLE IF NOT EXISTS public_request_audit (
    id                  BIGSERIAL PRIMARY KEY,
    event_hash          TEXT NOT NULL UNIQUE,
    source              TEXT NOT NULL DEFAULT 'nginx',
    client_hash         TEXT NOT NULL,
    client_network      TEXT,
    client_type         TEXT NOT NULL DEFAULT 'unknown',
    method              TEXT NOT NULL,
    path                TEXT NOT NULL,
    route_kind          TEXT NOT NULL,
    cbe                 TEXT,
    status_code         INTEGER,
    response_bytes      INTEGER,
    referrer_path       TEXT,
    ua_family           TEXT,
    device_type         TEXT,
    bot_family          TEXT,
    is_verified_bot     BOOLEAN NOT NULL DEFAULT FALSE,
    is_ai_crawler       BOOLEAN NOT NULL DEFAULT FALSE,
    is_rsc_prefetch     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_public_request_audit_date
    ON public_request_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_request_audit_client_date
    ON public_request_audit(client_hash, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_request_audit_route_date
    ON public_request_audit(route_kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_request_audit_bot_date
    ON public_request_audit(bot_family, created_at DESC)
    WHERE bot_family IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_public_request_audit_cbe_date
    ON public_request_audit(cbe, created_at DESC)
    WHERE cbe IS NOT NULL;

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

CREATE TABLE IF NOT EXISTS company_enrichment (
    enterprise_number          VARCHAR(10) PRIMARY KEY,
    summary                    TEXT,
    generated_at               TIMESTAMP DEFAULT NOW(),
    website_summary            TEXT,
    linkedin_summary           TEXT,
    website_url                TEXT,
    ai_insights                TEXT,
    publication_summary        TEXT,
    vlerick_sector             TEXT,
    vlerick_sector_confidence  TEXT,
    vlerick_sector_reasoning   TEXT,
    vlerick_sector_generated_at TIMESTAMP,
    bulk_summary               JSONB,
    bulk_summary_at            TIMESTAMPTZ,
    bulk_website_hash          TEXT,
    bulk_website_url           TEXT,
    bulk_confidence            TEXT,
    unified_summary            JSONB,
    quality_tier               TEXT,
    quality_tier_at            TIMESTAMPTZ,
    model_chain                JSONB,
    bulk_website_text          TEXT,
    bulk_website_text_at       TIMESTAMPTZ,
    CONSTRAINT enrichment_quality_tier_check
        CHECK (
            quality_tier IS NULL OR quality_tier IN (
                'bulk_only',
                'bulk_escalated',
                'narrative_lite',
                'narrative_full'
            )
        )
);
CREATE INDEX IF NOT EXISTS idx_enrichment_quality_tier
    ON company_enrichment(quality_tier, quality_tier_at);

CREATE TABLE IF NOT EXISTS ai_insights_feedback (
    id                 SERIAL PRIMARY KEY,
    enterprise_number  VARCHAR(10) NOT NULL,
    user_email         TEXT,
    overall            TEXT NOT NULL,
    website_correct    BOOLEAN,
    linkedin_correct   BOOLEAN,
    insight_correct    BOOLEAN,
    comment            TEXT,
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION try_parse_jsonb(t text) RETURNS jsonb AS $$
BEGIN
    RETURN t::jsonb;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

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
-- Dimension is 1024 to match the current NVIDIA embedding path.
CREATE TABLE IF NOT EXISTS query_embedding_cache (
    query_hash          TEXT PRIMARY KEY,
    query_text          TEXT NOT NULL,
    embedding           vector(1024) NOT NULL,
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


-- ---------------------------------------------------------------------------
-- Folded from 2026-04-24_search_v2.sql (pre-baseline migration archived).
-- Transaction wrappers removed for src/schema.sql; CONCURRENTLY removed where present.
-- ---------------------------------------------------------------------------
-- =======================================================================
-- DataSnoop search V2 migration — 2026-04-24
--
-- Idempotent. Safe to re-run.
--
-- The migration is split into SIX transactions so any single table
-- rewrite can be retried without redoing the others, and the planner
-- picks up stats incrementally. On a prod-sized DB (3 M
-- `administrator` rows, 3.5 M `denomination` rows) expect:
--   - Phase 0 (extensions + functions + reference tables): <5 s
--   - Phase 1 (company_info rewrite + indexes):              10-30 s
--   - Phase 2 (administrator rewrite + 3 GIN indexes):       3-6 min
--   - Phase 3 (shareholder rewrite + 3 GIN indexes):         1-3 min
--   - Phase 4 (staatsblad_event rewrite + 3 GIN indexes):    30-90 s
--   - Phase 5 (denomination rewrite + 1 GIN index):          3-7 min
-- Total ~8-17 min. During each phase, writes to the affected table
-- BLOCK. Pause the semantic worker + KBO updater beforehand per the
-- operator runbook. ANALYZE runs per-phase, outside each transaction.
--
-- IMPORTANT: do NOT pass this file to `psql -1` — that wraps the
-- entire file in one transaction and the per-phase splits lose their
-- value. Use `psql -v ON_ERROR_STOP=1 -f migrations/2026-04-24_search_v2.sql`.
-- =======================================================================

-- -----------------------------------------------------------------------
-- Phase 0 — extensions + functions + reference tables (fast)
-- -----------------------------------------------------------------------

-- -----------------------------------------------------------------------
-- 1. Extensions
-- -----------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;   -- provides dmetaphone()
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------
-- 2. IMMUTABLE wrappers so functions can be used in generated columns
--    and expression indexes. `unaccent()` is STABLE by default which
--    blocks index-building; f_unaccent asserts immutability.
-- -----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;

-- Canonical normaliser — matches backend/search_normalization.py::normalize_name
-- exactly. Strips TRAILING Belgian + foreign legal suffixes. The '$'
-- anchor is critical: without it we would strip the leading "NV" from
-- names like "NVidia Belgium".
-- All inner function references are schema-qualified to public so that
-- autoanalyze workers and parallel workers (which run with restricted
-- search_paths) can inline this function without raising
-- "function ... does not exist" during query planning.
CREATE OR REPLACE FUNCTION public.search_normalize(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    TRIM(
      REGEXP_REPLACE(
        LOWER(public.f_unaccent(
          REGEXP_REPLACE(
            COALESCE(s, ''),
            '[[:space:][:punct:]]*(' ||
              'nv|sa|bvba|sprl|bv|srl|cvba|scrl|vof|snc|se|scs|gcv|' ||
              'comm\.?\s*v|scomm|asbl|vzw|aisbl|ivzw|' ||
              'gmbh|ag|ltd|inc|sas|sarl|llc|plc|corp|spa|kg|ohg|ug|eurl' ||
            ')[[:space:][:punct:]]*$',
            '', 'gi'
          )
        )),
        '\s+', ' ', 'g'
      )
    ),
    ''
  )
$$;

-- Sorted-tokens reversed key. "tim braet" and "braet tim" both → "braet tim".
CREATE OR REPLACE FUNCTION public.search_name_reversed(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(tok ORDER BY tok)
       FROM regexp_split_to_table(COALESCE(public.search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;

-- Double-Metaphone key per token, space-joined. Empty if input empty.
-- dmetaphone() from `fuzzystrmatch`.
CREATE OR REPLACE FUNCTION public.search_phonetic_key(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(public.dmetaphone(tok))
       FROM regexp_split_to_table(COALESCE(public.search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;


-- -----------------------------------------------------------------------
-- 5. KBO juridical-form category lookup. 146 codes. Upsert lets us
--    re-seed if the taxonomy is refreshed later.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS juridical_form_category (
  code      text PRIMARY KEY,
  label_nl  text NOT NULL,
  label_fr  text NOT NULL,
  category  text NOT NULL CHECK (category IN ('commercial','nonprofit','public','other'))
);

INSERT INTO juridical_form_category (code, label_nl, label_fr, category) VALUES
  ('001', 'Europese Coöperatieve Vennootschap',                         'Société coopérative européenne',                                   'commercial'),
  ('002', 'Organisme voor de Financiering van Pensioenen',              'Organisme de financement de pensions',                             'other'),
  ('003', 'BTW-eenheid',                                                 'Unité TVA',                                                        'other'),
  ('006', 'Coöperatieve vennootschap met onbeperkte aansprakelijkheid', 'Société coopérative à responsabilité illimitée',                   'commercial'),
  ('007', 'CVOA bij wijze van deelneming',                               'Coopérative à responsabilité illimitée, participation',            'commercial'),
  ('008', 'Coöperatieve vennootschap met beperkte aansprakelijkheid',   'Société coopérative à responsabilité limitée',                     'commercial'),
  ('009', 'CVBA bij wijze van deelneming',                               'SCRL, coopérative de participation',                               'commercial'),
  ('010', 'Eenpersoons BVBA',                                            'SPRL unipersonnelle',                                              'commercial'),
  ('011', 'Vennootschap onder firma',                                    'Société en nom collectif',                                         'commercial'),
  ('012', 'Gewone commanditaire vennootschap',                           'Société en commandite simple',                                     'commercial'),
  ('013', 'Commanditaire vennootschap op aandelen',                      'Société en commandite par actions',                                'commercial'),
  ('014', 'Naamloze vennootschap',                                       'Société anonyme',                                                  'commercial'),
  ('015', 'BVBA',                                                        'SPRL',                                                             'commercial'),
  ('016', 'Coöperatieve vennootschap (oud statuut)',                    'Société coopérative (ancien statut)',                              'commercial'),
  ('017', 'Vereniging zonder winstoogmerk',                              'Association sans but lucratif',                                    'nonprofit'),
  ('018', 'Instelling van openbaar nut',                                 'Etablissement d''utilité publique',                                'nonprofit'),
  ('019', 'Ziekenfonds / Mutualiteit',                                   'Mutualité',                                                        'nonprofit'),
  ('020', 'Beroepsvereniging',                                           'Union professionnelle',                                            'nonprofit'),
  ('021', 'Onderlinge verzekeringsvereniging (privaatrecht)',            'Association d''assurances mutuelles (droit privé)',                'nonprofit'),
  ('022', 'Internationale wetenschappelijke organisatie',                'Organisation scientifique internationale',                         'nonprofit'),
  ('023', 'Buitenlandse privaatrechtelijke vereniging',                  'Association étrangère privée',                                     'nonprofit'),
  ('025', 'Landbouwvennootschap',                                        'Société agricole',                                                 'commercial'),
  ('026', 'Private stichting',                                           'Fondation privée',                                                 'nonprofit'),
  ('027', 'Europese vennootschap (Societas Europaea)',                   'Société européenne',                                               'commercial'),
  ('028', 'Instelling zonder winstoogmerk',                              'Institution sans but lucratif',                                    'nonprofit'),
  ('029', 'Stichting van openbaar nut',                                  'Fondation d''utilité publique',                                    'nonprofit'),
  ('030', 'Buitenlandse entiteit',                                       'Entité étrangère',                                                 'other'),
  ('040', 'Kongolese vennootschap',                                      'Société congolaise',                                               'other'),
  ('051', 'Andere privaatrechtelijke vorm met rechtspersoonlijkheid',    'Autre forme de droit privé avec personnalité juridique',           'other'),
  ('060', 'Economisch samenwerkingsverband',                             'Groupement d''intérêt économique',                                 'commercial'),
  ('065', 'Europees economisch samenwerkingsverband',                    'Groupement européen d''intérêt économique',                        'commercial'),
  ('070', 'Vereniging van mede-eigenaars',                               'Association des copropriétaires',                                  'other'),
  ('106', 'CVOA van publiek recht',                                      'Coopérative à responsabilité illimitée de droit public',           'public'),
  ('107', 'CVOA van publiek recht, deelneming',                          'Coopérative à responsabilité illimitée, participation, public',    'public'),
  ('108', 'CVBA van publiek recht',                                      'Coopérative à responsabilité limitée de droit public',             'public'),
  ('109', 'CVBA van publiek recht, deelneming',                          'SCRL de droit public, coopérative de participation',               'public'),
  ('110', 'Rijk, Provincie, Gewest, Gemeenschap',                        'État, Province, Région, Communauté',                               'public'),
  ('114', 'Naamloze vennootschap van publiek recht',                     'Société anonyme de droit public',                                  'public'),
  ('116', 'Coöperatieve vennootschap van publiek recht (oud)',          'Société coopérative de droit public (ancien)',                     'public'),
  ('117', 'VZW van publiek recht',                                       'ASBL de droit public',                                             'public'),
  ('121', 'Onderlinge verzekeringsvereniging van publiek recht',         'Association d''assurances mutuelles de droit public',              'public'),
  ('123', 'Beroepsvereniging / Orde',                                    'Corporation professionnelle / Ordre',                              'public'),
  ('124', 'Openbare instelling',                                         'Etablissement public',                                             'public'),
  ('125', 'Internationale vereniging zonder winstoogmerk',               'Association internationale sans but lucratif',                     'nonprofit'),
  ('126', 'Openbaar centrum voor maatschappelijk welzijn',               'Centre public d''action sociale',                                  'public'),
  ('127', 'Berg van Barmhartigheid',                                     'Monts-de-Piété',                                                   'public'),
  ('128', 'Eredienst / Kerkfabriek',                                     'Temporel des cultes',                                              'public'),
  ('129', 'Polder / Watering',                                           'Polder / wateringue',                                              'public'),
  ('151', 'Andere rechtsvorm',                                           'Autre forme légale',                                               'other'),
  ('155', 'Lokale politiezone',                                          'Zone de police locale',                                            'public'),
  ('160', 'Buitenlandse of internationale publieke organisatie',         'Organisme public étranger ou international',                       'public'),
  ('200', 'Vennootschap in oprichting',                                  'Société en formation',                                             'commercial'),
  ('206', 'Burgerlijke vennootschap CVOA',                               'Société civile CVOA',                                              'commercial'),
  ('208', 'Burgerlijke vennootschap CVBA',                               'Société civile CVBA',                                              'commercial'),
  ('211', 'Burgerlijke vennootschap VOF',                                'Société civile SNC',                                               'commercial'),
  ('212', 'Burgerlijke vennootschap Comm.V',                             'Société civile SCS',                                               'commercial'),
  ('213', 'Burgerlijke vennootschap Comm.VA',                            'Société civile SCA',                                               'commercial'),
  ('214', 'Burgerlijke vennootschap NV',                                 'Société civile SA',                                                'commercial'),
  ('215', 'Burgerlijke vennootschap BVBA',                               'Société civile SPRL',                                              'commercial'),
  ('217', 'Europese politieke partij',                                   'Parti politique européen',                                         'nonprofit'),
  ('218', 'Europese politieke stichting',                                'Fondation politique européenne',                                   'nonprofit'),
  ('225', 'Burgerlijke Vennootschap Landbouw',                           'Société civile agricole',                                          'commercial'),
  ('230', 'Buitenlandse entiteit met BE-vastgoed',                       'Entité étrangère avec immobilier BE',                              'other'),
  ('235', 'Buitenlandse entiteit, BTW-rep',                              'Entité étrangère, rep. TVA',                                       'other'),
  ('260', 'ESV zonder zetel, BE-vestiging',                              'GIE sans siège, établissement BE',                                 'commercial'),
  ('265', 'EESV zonder zetel, BE-vestiging',                             'GEIE sans siège, établissement BE',                                'commercial'),
  ('301', 'Federale overheidsdienst',                                    'Service public fédéral',                                           'public'),
  ('302', 'POD',                                                         'SPP',                                                              'public'),
  ('303', 'Andere federale dienst',                                      'Autre service fédéral',                                            'public'),
  ('310', 'Vlaamse overheid',                                            'Autorité flamande',                                                'public'),
  ('320', 'Waalse overheid',                                             'Autorité wallonne',                                                'public'),
  ('325', 'IVZW van publiek recht',                                      'AISBL de droit public',                                            'public'),
  ('330', 'Brusselse overheid',                                          'Autorité bruxelloise',                                             'public'),
  ('340', 'Franse Gemeenschap',                                          'Communauté française',                                             'public'),
  ('350', 'Duitstalige Gemeenschap',                                     'Communauté germanophone',                                          'public'),
  ('370', 'Ministerie van Economische Zaken (legacy)',                   'Ministère Affaires économiques (legacy)',                          'public'),
  ('371', 'Ministerie Buitenlandse Zaken (legacy)',                      'Ministère Affaires étrangères (legacy)',                           'public'),
  ('372', 'Ministerie Landbouw (legacy)',                                'Ministère Agriculture (legacy)',                                   'public'),
  ('373', 'Ministerie Middenstand (legacy)',                             'Ministère Classes moyennes (legacy)',                              'public'),
  ('374', 'Ministerie Verkeerswerken (legacy)',                          'Ministère Communications (legacy)',                                'public'),
  ('375', 'Ministerie Defensie (legacy)',                                'Ministère Défense (legacy)',                                       'public'),
  ('376', 'Ministerie Onderwijs (legacy)',                               'Ministère Éducation (legacy)',                                     'public'),
  ('377', 'Ministerie Tewerkstelling (legacy)',                          'Ministère Emploi (legacy)',                                        'public'),
  ('378', 'Ministerie Financiën (legacy)',                               'Ministère Finances (legacy)',                                      'public'),
  ('379', 'Ministerie Binnenlandse Zaken (legacy)',                      'Ministère Intérieur (legacy)',                                     'public'),
  ('380', 'Ministerie Justitie (legacy)',                                'Ministère Justice (legacy)',                                       'public'),
  ('381', 'Ministerie Sociale Voorzorg (legacy)',                        'Ministère Prévoyance sociale (legacy)',                            'public'),
  ('382', 'Ministerie Volksgezondheid (legacy)',                         'Ministère Santé publique (legacy)',                                'public'),
  ('383', 'Diensten Eerste Minister (legacy)',                           'Services Premier Ministre (legacy)',                               'public'),
  ('384', 'Ministerie Infrastructuur (legacy)',                          'Ministère Infrastructure (legacy)',                                'public'),
  ('385', 'Ministerie Vlaamse Gemeenschap (legacy)',                     'Ministère Communauté flamande (legacy)',                           'public'),
  ('386', 'Ministerie Franse Gemeenschap (legacy)',                      'Ministère Communauté française (legacy)',                          'public'),
  ('387', 'Ministerie Brussel (legacy)',                                 'Ministère Bruxelles (legacy)',                                     'public'),
  ('388', 'Ministerie Waals Gewest (legacy)',                            'Ministère Région wallonne (legacy)',                               'public'),
  ('389', 'Ministerie Duitstalige Gemeenschap (legacy)',                 'Ministère Communauté germanophone (legacy)',                       'public'),
  ('390', 'Ministerie Ambtenarenzaken (legacy)',                         'Ministère Fonction publique (legacy)',                             'public'),
  ('391', 'Ministerie Middenstand & Landbouw (legacy)',                  'Ministère Classes moyennes & Agriculture (legacy)',                'public'),
  ('392', 'Ministerie Sociale Zaken & Milieu (legacy)',                  'Ministère Affaires sociales & Environnement (legacy)',             'public'),
  ('393', 'Andere (ministeries)',                                        'Divers (ministères)',                                              'public'),
  ('400', 'Provinciale overheid',                                        'Autorité provinciale',                                             'public'),
  ('401', 'RSZ PPO',                                                     'ONSS-APL',                                                         'public'),
  ('411', 'Stad / gemeente',                                             'Ville / commune',                                                  'public'),
  ('412', 'OCMW',                                                        'CPAS',                                                             'public'),
  ('413', 'Lokale politiezone',                                          'Zone de police locale',                                            'public'),
  ('414', 'Intercommunale',                                              'Intercommunale',                                                   'public'),
  ('415', 'Projectvereniging',                                           'Association de projet',                                            'public'),
  ('416', 'Dienstverlenende vereniging',                                 'Association prestataire de services',                              'public'),
  ('417', 'Opdrachthoudende vereniging',                                 'Association chargée de mission',                                   'public'),
  ('418', 'Autonoom gemeentebedrijf',                                    'Régie communale autonome',                                         'public'),
  ('419', 'Autonoom provinciebedrijf',                                   'Régie provinciale autonome',                                       'public'),
  ('420', 'Vereniging van OCMW''s',                                      'Association de CPAS',                                              'public'),
  ('421', 'Prezone',                                                     'Prézone',                                                          'public'),
  ('422', 'Hulpverleningszone',                                          'Zone de secours',                                                  'public'),
  ('451', 'RVP-organisme',                                               'Organisme ONP',                                                    'public'),
  ('452', 'Pensioen-organisme',                                          'Organisme Pensions',                                               'public'),
  ('453', 'Beursgenoteerde buitenlandse entiteit',                       'Société étrangère cotée',                                          'other'),
  ('454', 'Buitenlandse entiteit zonder RP met BE-vastgoed',             'Entité étrangère sans PJ avec immobilier BE',                      'other'),
  ('506', 'CVOA met sociaal oogmerk',                                    'CVOA à finalité sociale',                                          'nonprofit'),
  ('508', 'CVBA met sociaal oogmerk',                                    'CVBA à finalité sociale',                                          'nonprofit'),
  ('510', 'Eenpersoons BVBA sociaal oogmerk',                            'SPRL unipersonnelle finalité sociale',                             'nonprofit'),
  ('511', 'VOF sociaal oogmerk',                                         'SNC finalité sociale',                                             'nonprofit'),
  ('512', 'Comm.V sociaal oogmerk',                                      'SCS finalité sociale',                                             'nonprofit'),
  ('513', 'Comm.VA sociaal oogmerk',                                     'SCA finalité sociale',                                             'nonprofit'),
  ('514', 'NV sociaal oogmerk',                                          'SA finalité sociale',                                              'nonprofit'),
  ('515', 'BVBA sociaal oogmerk',                                        'SPRL finalité sociale',                                            'nonprofit'),
  ('560', 'ESV sociaal oogmerk',                                         'GIE finalité sociale',                                             'nonprofit'),
  ('606', 'CVOA sociaal oogmerk (WVV)',                                  'CVOA finalité sociale (CSA)',                                      'nonprofit'),
  ('608', 'CVBA sociaal oogmerk (WVV)',                                  'CVBA finalité sociale (CSA)',                                      'nonprofit'),
  ('610', 'Besloten Vennootschap (BV/SRL, WVV)',                         'Société à responsabilité limitée (CSA)',                           'commercial'),
  ('612', 'Commanditaire vennootschap (WVV)',                            'Société en commandite (CSA)',                                      'commercial'),
  ('614', 'NV sociaal oogmerk (WVV)',                                    'SA finalité sociale (CSA)',                                        'nonprofit'),
  ('616', 'BV van publiek recht',                                        'SRL de droit public',                                              'public'),
  ('617', 'Comm.V van publiek recht',                                    'SComm de droit public',                                            'public'),
  ('651', 'Andere vorm sociaal oogmerk, publiek recht',                  'Autre forme finalité sociale de droit public',                     'public'),
  ('701', 'Onrechtmatige handelsvennootschap',                           'Société commerciale irrégulière',                                  'commercial'),
  ('702', 'Maatschap',                                                   'Société de droit commun',                                          'commercial'),
  ('703', 'Tijdelijke handelsvennootschap',                              'Société momentanée',                                               'commercial'),
  ('704', 'Stille handelsvennootschap',                                  'Société interne',                                                  'commercial'),
  ('706', 'Coöperatieve vennootschap (WVV)',                            'Société coopérative (CSA)',                                        'commercial'),
  ('716', 'Coöperatieve vennootschap van publiek recht (WVV)',          'Société coopérative de droit public (CSA)',                        'public'),
  ('721', 'Vennootschap zonder rechtspersoonlijkheid',                   'Société sans personnalité juridique',                              'other'),
  ('722', 'Tijdelijke vereniging',                                       'Association momentanée',                                           'other'),
  ('723', 'Kostendelende vereniging',                                    'Association de frais',                                             'other'),
  ('724', 'Vakbond',                                                     'Syndicat',                                                         'nonprofit'),
  ('790', 'Diversen zonder rechtspersoonlijkheid',                       'Divers sans personnalité juridique',                               'other'),
  ('999', 'Ongekende rechtsvorm',                                        'Forme inconnue',                                                   'other')
ON CONFLICT (code) DO UPDATE
  SET label_nl = EXCLUDED.label_nl,
      label_fr = EXCLUDED.label_fr,
      category = EXCLUDED.category;

-- -----------------------------------------------------------------------
-- 6. Legal-form synonyms (bidirectional). Used only at query-expansion
--    time; indexing preserves original-form display fidelity.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS legal_form_synonyms (
  form       text PRIMARY KEY,    -- what the user types (lowercased)
  canonical  text NOT NULL        -- canonical bucket key
);

INSERT INTO legal_form_synonyms (form, canonical) VALUES
  ('nv',     'nv'),   ('sa',     'nv'),
  ('bv',     'bv'),   ('sprl',   'bv'),   ('srl',    'bv'),   ('bvba',   'bv'),
  ('cvba',   'cv'),   ('scrl',   'cv'),   ('cv',     'cv'),
  ('vof',    'vof'),  ('snc',    'vof'),
  ('comm.v', 'commv'),('comm v', 'commv'),('scs',    'commv'),('scomm',  'commv'),
  ('vzw',    'vzw'),  ('asbl',   'vzw'),
  ('ivzw',   'ivzw'), ('aisbl',  'ivzw'),
  ('se',     'se'),
  ('gmbh',   'gmbh'), ('ag',     'ag'),   ('kg',     'kg'),   ('ohg',    'ohg'),
  ('ug',     'ug'),
  ('ltd',    'ltd'),  ('plc',    'plc'),  ('llp',    'llp'),
  ('inc',    'inc'),  ('corp',   'corp'), ('llc',    'llc'),
  ('sas',    'sas'),  ('sarl',   'sarl'), ('eurl',   'sarl'),
  ('spa',    'spa')
ON CONFLICT (form) DO UPDATE SET canonical = EXCLUDED.canonical;

-- -----------------------------------------------------------------------
-- 7. Company popularity (ranking signal), refreshed nightly.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_popularity (
  enterprise_number  text PRIMARY KEY,
  click_count        integer NOT NULL DEFAULT 0,
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_popularity_count
  ON company_popularity (click_count DESC);


-- -----------------------------------------------------------------------
-- Phase 1 — company_info: drop old text column, recreate as GENERATED,
-- add trigram + prefix indexes.
-- -----------------------------------------------------------------------
-- Omitted from canonical baseline: no migration-era drop/rebuild of idx_ci_name_trgm.
-- Omitted from canonical baseline: never drop company_info.name_normalized during replay.
ALTER TABLE company_info
  ADD COLUMN IF NOT EXISTS name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_ci_name_norm_trgm
  ON company_info USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_ci_name_norm_prefix
  ON company_info (name_normalized text_pattern_ops);


-- -----------------------------------------------------------------------
-- Phase 2 — administrator: three generated columns + three GIN indexes.
-- Longest-running phase on prod (~3-6 min). If interrupted, re-running
-- is safe: `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.
-- -----------------------------------------------------------------------
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(name)) STORED;
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_admin_name_norm_trgm
  ON administrator USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_admin_name_rev_trgm
  ON administrator USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_admin_name_phon_trgm
  ON administrator USING GIN (name_phonetic gin_trgm_ops);


-- -----------------------------------------------------------------------
-- Phase 3 — shareholder (1-3 min).
-- -----------------------------------------------------------------------
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(name)) STORED;
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_sh_name_norm_trgm
  ON shareholder USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sh_name_rev_trgm
  ON shareholder USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sh_name_phon_trgm
  ON shareholder USING GIN (name_phonetic gin_trgm_ops);


-- -----------------------------------------------------------------------
-- Phase 4 — staatsblad_event (30-90 s).
-- -----------------------------------------------------------------------
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_normalized text
    GENERATED ALWAYS AS (search_normalize(person_name)) STORED;
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(person_name)) STORED;
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(person_name)) STORED;
CREATE INDEX IF NOT EXISTS idx_sb_person_norm_trgm
  ON staatsblad_event USING GIN (person_name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sb_person_rev_trgm
  ON staatsblad_event USING GIN (person_name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sb_person_phon_trgm
  ON staatsblad_event USING GIN (person_name_phonetic gin_trgm_ops);

-- Person v1 domicile anchors. Code already reads these fields; keeping them
-- in the canonical schema makes fresh installs match live databases.
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


-- -----------------------------------------------------------------------
-- Phase 5 — denomination (3-7 min — the widest rewrite).
-- -----------------------------------------------------------------------
ALTER TABLE denomination
  ADD COLUMN IF NOT EXISTS denomination_normalized text
    GENERATED ALWAYS AS (search_normalize(denomination)) STORED;
CREATE INDEX IF NOT EXISTS idx_denom_norm_trgm
  ON denomination USING GIN (denomination_normalized gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Folded from 2026-04-25_affiliation.sql (pre-baseline migration archived).
-- Transaction wrappers removed for src/schema.sql; CONCURRENTLY removed where present.
-- ---------------------------------------------------------------------------
-- =======================================================================
-- DataSnoop affiliation migration — 2026-04-25
--
-- Captures a softer relationship than `administrator`: when Company A's
-- annual filing names a corporate director (Company B), and Company B
-- is represented by a natural person X, we record that X is "affiliated"
-- with Company B. X may or may not be a direct admin of Company B
-- elsewhere — the affiliation is a clue, not a mandate.
--
-- Idempotent. Safe to re-run.
--
-- Phasing rationale:
--   Phase 0 — create the table with the generated search columns.
--             On a fresh DB this is instant; on prod the table is empty
--             until the new extractor and/or backfill writes to it, so
--             generated columns cost nothing on existing data.
--   Phase 1 — GIN indexes for trigram + reversed + phonetic search.
--             Empty table → instant. Future re-runs are no-ops.
--
-- Run with: psql -v ON_ERROR_STOP=1 -f migrations/2026-04-25_affiliation.sql
-- DO NOT pass through `psql -1` (single-tx wrapper kills the per-phase split).
-- =======================================================================

-- -----------------------------------------------------------------------
-- Phase 0 — table
-- -----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS affiliation (
    person_name             TEXT NOT NULL,
    -- Company B: the company Person X is affiliated with via representing
    -- a corporate director of Company A. Stored as 10-digit canonical CBE.
    enterprise_number       TEXT NOT NULL,
    -- Company A: the filing company where the link was observed.
    via_enterprise_number   TEXT NOT NULL,
    -- Source filing for provenance + dedup. Combined with company_a CBE
    -- this lets us tell "5 distinct filings mention this rep" from
    -- "1 filing mentions them 5 times".
    via_deposit_key         TEXT NOT NULL,
    fiscal_year             TEXT,
    -- Reserved enum: 'represents_admin' for now. Future weak-links
    -- ('frequent_co_director', 'shared_address', 'shared_email_domain')
    -- can land here without schema churn.
    affiliation_type        TEXT NOT NULL DEFAULT 'represents_admin',
    -- Optional: NBB exposes this rarely for natural persons; usually NULL.
    person_identifier       TEXT,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_from              DATE,           -- NULL = unknown start; treated as in-force by current/as-of views
    valid_to                DATE,           -- exclusive end
    valid_from_provenance   TEXT,
    valid_to_provenance     TEXT,
    source_deposit_date     DATE,
    recorded_from           TIMESTAMPTZ DEFAULT NOW(),
    recorded_to             TIMESTAMPTZ,
    -- Generated search columns — mirror the administrator/shareholder
    -- pattern from migrations/2026-04-24_search_v2.sql so the people
    -- search arm can reuse the same query shape.
    name_normalized TEXT
        GENERATED ALWAYS AS (search_normalize(person_name)) STORED,
    name_reversed   TEXT
        GENERATED ALWAYS AS (search_name_reversed(person_name)) STORED,
    name_phonetic   TEXT
        GENERATED ALWAYS AS (search_phonetic_key(person_name)) STORED,
    PRIMARY KEY (person_name, enterprise_number, via_enterprise_number, affiliation_type)
);

-- Lookup index for the connections endpoint (people → companies).
CREATE INDEX IF NOT EXISTS idx_affiliation_person_lower
    ON affiliation (LOWER(person_name));

-- Lookup index for the company-side query: who is affiliated with X?
CREATE INDEX IF NOT EXISTS idx_affiliation_ent
    ON affiliation (enterprise_number);

-- Reverse lookup: which filings introduced this affiliation?
CREATE INDEX IF NOT EXISTS idx_affiliation_via_ent
    ON affiliation (via_enterprise_number);

-- ----------------------------------------------------------------
-- Backfill attempt log. Tracks (filing) tuples that the
-- backfill_affiliation.py script has already re-fetched, so we don't
-- waste NBB quota perpetually re-fetching filings whose legal-person
-- admins have no representatives (zero affiliation rows produced).
-- The forward extractor doesn't write here — only the backfill does.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS affiliation_backfill_log (
    via_enterprise_number   TEXT NOT NULL,
    via_deposit_key         TEXT NOT NULL,
    attempted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows_inserted           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (via_enterprise_number, via_deposit_key)
);


-- -----------------------------------------------------------------------
-- Phase 1 — search GIN indexes (instant on empty table)
-- -----------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_affiliation_name_norm_trgm
    ON affiliation USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_affiliation_name_rev_trgm
    ON affiliation USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_affiliation_name_phon_trgm
    ON affiliation USING GIN (name_phonetic gin_trgm_ops);

-- -----------------------------------------------------------------------
-- Bitemporal Phase A: explicit current/fact views and as-of helpers for
-- NBB governance fact tables. NULL valid_from means unknown start and is
-- treated as in-force by current/as-of reads until per-table backfill quality
-- permits NOT NULL tightening.
-- -----------------------------------------------------------------------

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

-- -----------------------------------------------------------------------
-- Person v1 internal-only identity graph.
-- -----------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

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

CREATE INDEX IF NOT EXISTS idx_person_status
    ON person(status);
CREATE INDEX IF NOT EXISTS idx_person_name_tsv
    ON person USING GIN (to_tsvector('simple', name_normalized));
CREATE INDEX IF NOT EXISTS idx_person_name_norm_trgm
    ON person USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_person_link_person
    ON person_link(person_id);
CREATE INDEX IF NOT EXISTS idx_person_link_enterprise
    ON person_link(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_person_link_kind
    ON person_link(link_kind);
CREATE INDEX IF NOT EXISTS idx_person_link_source_table
    ON person_link(source_table);
CREATE INDEX IF NOT EXISTS idx_pml_primary
    ON person_merge_log(primary_id);
CREATE INDEX IF NOT EXISTS idx_pml_secondary
    ON person_merge_log(secondary_id);

-- -----------------------------------------------------------------------
-- Ownership graph v1 (pure SQL).
-- -----------------------------------------------------------------------

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

CREATE INDEX IF NOT EXISTS idx_oe_parent
    ON ownership_edge(parent_kind, parent_id);
CREATE INDEX IF NOT EXISTS idx_oe_child
    ON ownership_edge(child_kind, child_id);
CREATE INDEX IF NOT EXISTS idx_oe_active
    ON ownership_edge(child_id, valid_to)
    WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_oe_rank
    ON ownership_edge(child_id, source_rank, deposit_date DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_oe_source_table
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



-- -----------------------------------------------------------------------
-- Permissions for the application role.
-- -----------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'leadpeek') THEN
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON affiliation TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON affiliation_backfill_log TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON governance_load_log TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person_link TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON person_merge_log TO leadpeek';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ownership_edge TO leadpeek';
        EXECUTE 'GRANT SELECT ON ownership_edge_current TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION ownership_edge_as_of(DATE) TO leadpeek';
        EXECUTE 'GRANT EXECUTE ON FUNCTION ownership_ubo_walk(TEXT, INT) TO leadpeek';
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
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE person_link_id_seq TO leadpeek';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE person_merge_log_id_seq TO leadpeek';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE ownership_edge_id_seq TO leadpeek';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Folded from 2026-04-26_address_trgm.sql (pre-baseline migration archived).
-- Transaction wrappers removed for src/schema.sql; CONCURRENTLY removed where present.
-- ---------------------------------------------------------------------------
-- Migration: trigram indexes on address.street_* / municipality_* (REGO only)
-- ----------------------------------------------------------------------------
-- Why: company search's `addr_match` CTE (in `_SEARCH_SQL` inside
-- `backend/routers/companies/search.py`) does four ILIKE clauses on a
-- 3M-row `address` table without a trigram index, which produces a
-- sequential scan and a documented 1-2 s floor on address-typed queries
-- (e.g. "Rue Neuve"). The same scan also gates the optional location
-- filter (`loc_filter` CTE) used by the search UI's address fields.
-- GIN trigram indexes on street_nl / street_fr / municipality_nl /
-- municipality_fr drop that floor to ~50-200 ms.
--
-- Why partial: the existing search arm filters on `type_of_address = 'REGO'`
-- (registered office), so the index only needs to cover REGO rows. That
-- shrinks the index from ~3M rows to ~1.7M and saves ~50% of the storage.
--
-- Why CONCURRENTLY: this runs on a live shared DB (staging + prod see the
-- same Postgres). Without CONCURRENTLY each `CREATE INDEX` would lock the
-- table for ~5-10 min, blocking writes and breaking the daily KBO loader.
--
-- Estimated build time: 3-6 min per index, run sequentially, ~20 min total.
-- Estimated storage: ~50 MB total.
--
-- Run order (psql, one at a time so a failure on a later index doesn't
-- stop the earlier ones being built):
--   psql $DATABASE_URL -f migrations/2026-04-26_address_trgm.sql
--
-- Verify after:
--   SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
--     FROM pg_indexes WHERE indexname LIKE 'idx_address_%_trgm';
--
-- Rollback: drop the four indexes (see _rollback.sql sibling file).
-- ----------------------------------------------------------------------------

-- pg_trgm extension should already be enabled (search V2 migration created
-- it), but IF NOT EXISTS keeps this idempotent for fresh environments.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Each index is in its own statement so a transient failure (e.g. lock
-- contention on a single column) only loses that one index, not the batch.
-- CONCURRENTLY cannot run inside a transaction block; psql's autocommit
-- mode handles each statement independently.

CREATE INDEX IF NOT EXISTS idx_address_street_nl_trgm
  ON address USING GIN (street_nl gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX IF NOT EXISTS idx_address_street_fr_trgm
  ON address USING GIN (street_fr gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX IF NOT EXISTS idx_address_municipality_nl_trgm
  ON address USING GIN (municipality_nl gin_trgm_ops)
  WHERE type_of_address = 'REGO';

CREATE INDEX IF NOT EXISTS idx_address_municipality_fr_trgm
  ON address USING GIN (municipality_fr gin_trgm_ops)
  WHERE type_of_address = 'REGO';

-- Post-migration check (run manually):
--   EXPLAIN ANALYZE
--     SELECT * FROM address
--      WHERE type_of_address = 'REGO'
--        AND street_nl ILIKE '%rue neuve%';
-- Expected: Bitmap Index Scan on idx_address_street_nl_trgm.

-- ---------------------------------------------------------------------------
-- Folded from 2026-04-28_pi_identifier_index.sql (pre-baseline migration archived).
-- Transaction wrappers removed for src/schema.sql; CONCURRENTLY removed where present.
-- ---------------------------------------------------------------------------
-- Migration: index on participating_interest(identifier)
-- ----------------------------------------------------------------------------
-- Why: the spiderweb (network.py:718,795) and the new parent_companies
-- query in /api/companies/{cbe}/structure both filter
-- `participating_interest` with `WHERE identifier = %s` (or
-- `identifier IN (...)`). Only `idx_pi_ent` on `enterprise_number` exists,
-- so every reverse-direction lookup falls back to a sequential scan over
-- the whole table. That's been a latent cost for the spiderweb already;
-- the new structure-tab field puts the same scan on every profile view,
-- which is why the security review flagged it as a DoS multiplier.
--
-- Why partial: skip rows where `identifier` is NULL — natural-person
-- shareholders, foreign entities without a CBE, etc. Roughly halves the
-- index size at zero cost (the WHERE clause matches the query: we only
-- look up by identifier when we have one).
--
-- Why CONCURRENTLY: this runs on the shared prod DB (staging + prod
-- share Postgres). Without CONCURRENTLY the build would lock the table
-- for the duration of the build and block writes from the daily NBB
-- loader.
--
-- Estimated build time: 30-60 s (table is small relative to `address`).
-- Estimated storage: a few MB.
--
-- Run:
--   psql $DATABASE_URL -f migrations/2026-04-28_pi_identifier_index.sql
--
-- Verify after:
--   SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
--     FROM pg_indexes WHERE indexname = 'idx_pi_identifier';
--   EXPLAIN ANALYZE
--     SELECT * FROM participating_interest WHERE identifier = '0878290854';
--   -- Expected: Index Scan using idx_pi_identifier.
--
-- Rollback: see _rollback.sql sibling file.
-- ----------------------------------------------------------------------------

-- idx_pi_identifier is defined in the participating_interest baseline section above.
