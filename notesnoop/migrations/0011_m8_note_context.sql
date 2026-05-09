ALTER TABLE notes
  ADD COLUMN IF NOT EXISTS note_kind TEXT NOT NULL DEFAULT 'note'
    CHECK (note_kind IN ('note','meeting','call','email','task','report')),
  ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;

ALTER TABLE people
  ADD COLUMN IF NOT EXISTS email TEXT,
  ADD COLUMN IF NOT EXISTS role TEXT;

CREATE INDEX IF NOT EXISTS idx_notesnoop_notes_workspace_kind_time
  ON notes(workspace_id, note_kind, coalesce(occurred_at, created_at) DESC);

UPDATE notes
SET note_kind = 'email'
WHERE raw_email_metadata IS NOT NULL
  AND note_kind = 'note';
