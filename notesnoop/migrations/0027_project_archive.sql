-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Project archive: projects can be flagged closed when a deal/initiative
-- wraps. Closed projects hide from default sidebar / dashboard queries
-- but remain in the workspace for retrospective queries and memory.

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','closed'));

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_notesnoop_projects_workspace_active
  ON projects(workspace_id, created_at DESC)
  WHERE status = 'active';
