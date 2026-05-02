-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/nbb_batch_pipeline.py.
-- This table is derived from financial_summary and refreshed by the batch
-- pipeline; the migration owns only the stable heap/index shape.

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

CREATE INDEX IF NOT EXISTS idx_fby_ent
    ON financial_by_year(enterprise_number);
CREATE INDEX IF NOT EXISTS idx_fby_year
    ON financial_by_year(fiscal_year);
