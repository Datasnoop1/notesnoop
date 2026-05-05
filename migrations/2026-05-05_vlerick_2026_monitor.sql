-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Seed Vlerick M&A Monitor 2026 multiples (2025 Belgian transaction data) and
-- split telecommunications out of the technology sector.
--
-- Source: 2026 M&A Monitor, Vlerick Business School (published May 2026).
-- The 2024 row set is intentionally preserved — the valuation API selects
-- MAX(year) per source, so once these rows land the live multiples flip to
-- 2025 while the 2024 history stays for audit.

-- 2025 size multiples (overall + 5 size brackets)
INSERT INTO vlerick_multiple (source, year, bucket_type, bucket_key, multiple, source_note) VALUES
    ('vlerick', 2025, 'size', 'lt_5m',   5.1, '<5M EUR deal size'),
    ('vlerick', 2025, 'size', '5_20m',   6.1, '5M-20M EUR deal size'),
    ('vlerick', 2025, 'size', '20_50m',  7.9, '20M-50M EUR deal size'),
    ('vlerick', 2025, 'size', '50_100m', 8.3, '50M-100M EUR deal size'),
    ('vlerick', 2025, 'size', 'gt_100m', 8.0, '>100M EUR deal size'),
    ('vlerick', 2025, 'size', 'overall', 6.4, 'Belgian M&A market overall')
ON CONFLICT (source, year, bucket_type, bucket_key) DO UPDATE
    SET multiple    = EXCLUDED.multiple,
        source_note = EXCLUDED.source_note;

-- 2025 sector multiples. New for 2026 Monitor: telecommunications is split
-- out from technology (Vlerick reports them separately for the first time).
INSERT INTO vlerick_multiple (source, year, bucket_type, bucket_key, multiple) VALUES
    ('vlerick', 2025, 'sector', 'technology',          9.7),
    ('vlerick', 2025, 'sector', 'chemistry',           7.9),
    ('vlerick', 2025, 'sector', 'telecommunications',  7.6),
    ('vlerick', 2025, 'sector', 'healthcare',          7.5),
    ('vlerick', 2025, 'sector', 'energy_utilities',    7.4),
    ('vlerick', 2025, 'sector', 'pharmaceutical',      7.2),
    ('vlerick', 2025, 'sector', 'business_services',   6.7),
    ('vlerick', 2025, 'sector', 'real_estate',         6.6),
    ('vlerick', 2025, 'sector', 'entertainment_media', 6.5),
    ('vlerick', 2025, 'sector', 'industrial_products', 6.3),
    ('vlerick', 2025, 'sector', 'consumer_goods',      6.3),
    ('vlerick', 2025, 'sector', 'transport_logistics', 5.1),
    ('vlerick', 2025, 'sector', 'retail',              4.9),
    ('vlerick', 2025, 'sector', 'construction',        4.5)
ON CONFLICT (source, year, bucket_type, bucket_key) DO UPDATE
    SET multiple = EXCLUDED.multiple;

-- Re-route NACE prefix 61 (telecommunications) to the new dedicated sector.
-- The router's seeding logic only inserts the NACE map when the table is
-- empty, so this UPDATE is the only path for the migration to take effect.
INSERT INTO nace_vlerick_mapping (nace_prefix, vlerick_sector)
VALUES ('61', 'telecommunications')
ON CONFLICT (nace_prefix) DO UPDATE
    SET vlerick_sector = EXCLUDED.vlerick_sector;
