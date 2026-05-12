-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Recurring tasks — simple cadence so the operator can model "weekly
-- check-in" / "monthly status report" without re-creating the task by hand.
-- When the task is marked done, the app spawns the next instance with the
-- due_at advanced. No RRULE complexity, no calendar exceptions yet.

ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS recurrence TEXT
    CHECK (recurrence IN ('none','daily','weekly','biweekly','monthly'))
    DEFAULT 'none';

CREATE INDEX IF NOT EXISTS idx_notesnoop_tasks_recurrence
  ON tasks(workspace_id, recurrence)
  WHERE recurrence <> 'none';

COMMENT ON COLUMN tasks.recurrence IS 'How often the task respawns after being marked done — none / daily / weekly / biweekly / monthly.';
