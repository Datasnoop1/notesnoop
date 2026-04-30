-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/semantic_bootstrap.py.

CREATE TABLE IF NOT EXISTS meta (
    variable TEXT PRIMARY KEY,
    value    TEXT NOT NULL
);

INSERT INTO meta (variable, value) VALUES
    ('enrichment_enabled', 'true'),
    ('enrichment_daily_budget', '10.00')
ON CONFLICT (variable) DO NOTHING;

CREATE TABLE IF NOT EXISTS company_enrichment (
    enterprise_number VARCHAR(10) PRIMARY KEY,
    summary           TEXT,
    generated_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE company_enrichment
    ADD COLUMN IF NOT EXISTS website_summary   TEXT,
    ADD COLUMN IF NOT EXISTS linkedin_summary  TEXT,
    ADD COLUMN IF NOT EXISTS website_url       TEXT,
    ADD COLUMN IF NOT EXISTS ai_insights       TEXT,
    ADD COLUMN IF NOT EXISTS bulk_summary      JSONB,
    ADD COLUMN IF NOT EXISTS bulk_summary_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bulk_website_hash TEXT,
    ADD COLUMN IF NOT EXISTS bulk_website_url  TEXT,
    ADD COLUMN IF NOT EXISTS bulk_confidence   TEXT;

CREATE TABLE IF NOT EXISTS aggregator_skiplist (
    id          SERIAL PRIMARY KEY,
    pattern     TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'domain',
    reason      TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    added_by    TEXT,
    UNIQUE (pattern, kind)
);

INSERT INTO aggregator_skiplist (pattern, kind, reason, added_by) VALUES
    ('pappers.be',           'domain', 'seed: KBO aggregator',           'seed'),
    ('bsearch.be',           'domain', 'seed: business directory',       'seed'),
    ('handelsgids.be',       'domain', 'seed: business directory',       'seed'),
    ('infobel.be',           'domain', 'seed: directory',                'seed'),
    ('immoweb.be',           'domain', 'seed: real-estate listing',      'seed'),
    ('lemariagedelouise.be', 'domain', 'seed: wedding-vendor listing',   'seed'),
    ('economie.fgov.be',     'domain', 'seed: KBO portal',               'seed'),
    ('kompass.com',          'domain', 'seed: B2B directory',            'seed'),
    ('europages.com',        'domain', 'seed: B2B directory',            'seed'),
    ('dnb.com',              'domain', 'seed: credit directory',         'seed'),
    ('companyweb.be',        'domain', 'seed: directory',                'seed'),
    ('staatsbladmonitor.be', 'domain', 'seed: gazette mirror',           'seed'),
    ('trends.knack.be',      'domain', 'seed: press directory',          'seed'),
    ('/bedrijvengids/',      'path',   'seed: municipal business index', 'seed'),
    ('/annuaire/',           'path',   'seed: FR municipal directory',   'seed'),
    ('/infrastructuur-',     'path',   'seed: municipal infrastructure', 'seed')
ON CONFLICT (pattern, kind) DO NOTHING;
