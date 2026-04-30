-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/people.py.

CREATE TABLE IF NOT EXISTS people_enrichment (
    person_name  TEXT PRIMARY KEY,
    summary      TEXT,
    generated_at TIMESTAMP DEFAULT NOW()
);
