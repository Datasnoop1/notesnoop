-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_kind TEXT;

ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_kind TEXT;

ALTER TABLE reports
  ADD COLUMN IF NOT EXISTS source_note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS source_kind TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_tasks_source_note_kind_title
  ON tasks(source_note_id, source_kind, lower(title))
  WHERE source_note_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_meetings_source_note_kind
  ON meetings(source_note_id, source_kind)
  WHERE source_note_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_reports_source_note_kind
  ON reports(source_note_id, source_kind)
  WHERE source_note_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notesnoop_tasks_source_note
  ON tasks(source_note_id)
  WHERE source_note_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notesnoop_meetings_source_note
  ON meetings(source_note_id)
  WHERE source_note_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notesnoop_reports_source_note
  ON reports(source_note_id)
  WHERE source_note_id IS NOT NULL;
