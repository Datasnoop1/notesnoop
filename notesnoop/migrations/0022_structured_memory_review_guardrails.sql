-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

ALTER TABLE review_queue
  DROP CONSTRAINT IF EXISTS review_queue_entity_kind_check;
ALTER TABLE review_queue
  ADD CONSTRAINT review_queue_entity_kind_check
  CHECK (entity_kind IN ('person','project','note','processing','task','meeting','report','workflow','company'));

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_kind TEXT,
  ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'
    CHECK (ai_review_state IN ('proposed','accepted','rejected','archived')),
  ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS source_payload JSONB;

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'
    CHECK (ai_review_state IN ('proposed','accepted','rejected','archived')),
  ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS source_payload JSONB;

ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'
    CHECK (ai_review_state IN ('proposed','accepted','rejected','archived')),
  ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS source_payload JSONB;

ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'
    CHECK (ai_review_state IN ('proposed','accepted','rejected','archived')),
  ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS source_payload JSONB;

ALTER TABLE workflows
  ADD COLUMN IF NOT EXISTS source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_kind TEXT,
  ADD COLUMN IF NOT EXISTS ai_review_state TEXT NOT NULL DEFAULT 'accepted'
    CHECK (ai_review_state IN ('proposed','accepted','rejected','archived')),
  ADD COLUMN IF NOT EXISTS ai_review_id UUID REFERENCES review_queue(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS source_payload JSONB;

CREATE INDEX IF NOT EXISTS idx_notesnoop_companies_source_review
  ON companies(source_note_id, ai_review_state)
  WHERE source_note_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notesnoop_tasks_source_review
  ON tasks(source_note_id, ai_review_state)
  WHERE source_note_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notesnoop_meetings_source_review
  ON meetings(source_note_id, ai_review_state)
  WHERE source_note_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notesnoop_reports_source_review
  ON reports(source_note_id, ai_review_state)
  WHERE source_note_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflows_source_review
  ON workflows(source_note_id, ai_review_state)
  WHERE source_note_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notesnoop_review_queue_candidate_key
  ON review_queue(workspace_id, target_user_id, entity_kind, entity_id, reason, (payload->>'candidate_key'))
  WHERE payload ? 'candidate_key';
