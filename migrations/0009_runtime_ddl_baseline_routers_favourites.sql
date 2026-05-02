-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- Captures runtime DDL formerly owned by backend/routers/favourites.py.

CREATE TABLE IF NOT EXISTS favourite_project (
    id         SERIAL PRIMARY KEY,
    user_id    TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS favourite_project_member (
    project_id         INTEGER REFERENCES favourite_project(id) ON DELETE CASCADE,
    enterprise_number  TEXT NOT NULL,
    PRIMARY KEY (project_id, enterprise_number)
);

CREATE TABLE IF NOT EXISTS favourite_last_checked (
    user_id    TEXT PRIMARY KEY,
    checked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS people_favourite (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    person_name TEXT NOT NULL,
    notes       TEXT,
    added_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, person_name)
);

CREATE TABLE IF NOT EXISTS customer_supplier_list (
    id                SERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL,
    list_type         TEXT NOT NULL CHECK (list_type IN ('customer', 'supplier')),
    enterprise_number TEXT NOT NULL,
    custom_name       TEXT,
    notes             TEXT,
    added_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, list_type, enterprise_number)
);
