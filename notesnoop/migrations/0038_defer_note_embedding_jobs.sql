-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

ALTER TABLE ai_jobs DROP CONSTRAINT IF EXISTS ai_jobs_kind_check;

ALTER TABLE ai_jobs
  ADD CONSTRAINT ai_jobs_kind_check
  CHECK (kind IN ('extract','reprocess','embed','briefing','merge','prune'));
