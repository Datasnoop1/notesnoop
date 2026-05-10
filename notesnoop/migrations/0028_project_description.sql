-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Freeform description on projects: deal thesis, scope notes, anything the
-- project name can't carry. Optional; nothing breaks if NULL.

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS description TEXT;
