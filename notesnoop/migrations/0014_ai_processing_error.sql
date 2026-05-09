-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=30s

ALTER TABLE notes
  ADD COLUMN IF NOT EXISTS ai_processing_error TEXT;
