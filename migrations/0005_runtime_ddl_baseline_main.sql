-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/main.py.

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
