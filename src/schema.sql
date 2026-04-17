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
