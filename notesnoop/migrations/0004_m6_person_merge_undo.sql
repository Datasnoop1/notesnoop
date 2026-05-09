-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

ALTER TABLE person_merge_undos
  ADD COLUMN IF NOT EXISTS target_links JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN person_merge_undos.target_links IS 'Pre-merge target-person links for source-note ids, used to make merge undo lossless.';
