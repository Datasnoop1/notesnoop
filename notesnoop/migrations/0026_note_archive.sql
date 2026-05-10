-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Soft-archive for notes. Notes flagged with archived_at IS NOT NULL hide
-- from default queries but remain in the workspace for audit / undo.

ALTER TABLE notes
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_notesnoop_notes_workspace_active
  ON notes(workspace_id, created_at DESC)
  WHERE archived_at IS NULL;
