-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/tier_config.py.

CREATE TABLE IF NOT EXISTS tier_config (
    tier                   VARCHAR(20) PRIMARY KEY,
    page_views_per_day     INT DEFAULT -1,
    searches_per_day       INT DEFAULT -1,
    company_views_per_day  INT DEFAULT -1,
    ai_enrichments_per_day INT DEFAULT 0,
    export_per_day         INT DEFAULT 0,
    screener_results_limit INT DEFAULT 20,
    enabled                BOOLEAN DEFAULT FALSE,
    updated_at             TIMESTAMP DEFAULT NOW()
);

INSERT INTO tier_config (
    tier,
    page_views_per_day,
    searches_per_day,
    company_views_per_day,
    ai_enrichments_per_day,
    export_per_day,
    screener_results_limit,
    enabled
)
VALUES
    ('guest', 50, 10, 5, 0, 0, 20, FALSE),
    ('registered', -1, -1, -1, 5, 10, 100, FALSE),
    ('premium', -1, -1, -1, -1, -1, -1, FALSE)
ON CONFLICT (tier) DO NOTHING;
