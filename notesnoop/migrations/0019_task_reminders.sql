-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS task_reminders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  remind_at TIMESTAMPTZ NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('in_app','email')) DEFAULT 'in_app',
  state TEXT NOT NULL CHECK (state IN ('pending','sent','dismissed','snoozed')) DEFAULT 'pending',
  snoozed_until TIMESTAMPTZ,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_task_reminders_pending_task_channel
  ON task_reminders(task_id, channel)
  WHERE state = 'pending';

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_reminders_workspace_due
  ON task_reminders(workspace_id, state, (coalesce(snoozed_until, remind_at)), created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_reminders_task
  ON task_reminders(task_id, created_at DESC);

CREATE OR REPLACE FUNCTION can_access_task_reminder(target_reminder_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM task_reminders tr
    WHERE tr.id = target_reminder_id
      AND is_workspace_member(tr.workspace_id)
      AND can_access_task(tr.task_id)
  )
$$;

CREATE OR REPLACE FUNCTION sync_task_due_reminder() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NEW.due_at IS NULL OR NEW.status IN ('done','archived') THEN
    UPDATE task_reminders
    SET state = 'dismissed',
        updated_at = now()
    WHERE task_id = NEW.id
      AND state IN ('pending','snoozed');
  ELSE
    INSERT INTO task_reminders (workspace_id, task_id, remind_at, channel, state, created_by)
    VALUES (NEW.workspace_id, NEW.id, NEW.due_at, 'in_app', 'pending', NEW.created_by)
    ON CONFLICT (task_id, channel) WHERE state = 'pending'
    DO UPDATE
      SET workspace_id = EXCLUDED.workspace_id,
          remind_at = EXCLUDED.remind_at,
          snoozed_until = NULL,
          updated_at = now();
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_tasks_sync_due_reminder ON tasks;
CREATE TRIGGER trg_tasks_sync_due_reminder
  AFTER INSERT OR UPDATE OF due_at, status ON tasks
  FOR EACH ROW EXECUTE FUNCTION sync_task_due_reminder();

INSERT INTO task_reminders (workspace_id, task_id, remind_at, channel, state, created_by)
SELECT workspace_id, id, due_at, 'in_app', 'pending', created_by
FROM tasks
WHERE due_at IS NOT NULL
  AND status IN ('todo','doing','blocked')
ON CONFLICT (task_id, channel) WHERE state = 'pending'
DO UPDATE
  SET remind_at = EXCLUDED.remind_at,
      updated_at = now();

ALTER TABLE task_reminders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_reminders_task_access ON task_reminders;
CREATE POLICY task_reminders_task_access ON task_reminders
  USING (can_access_task_reminder(id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON task_reminders TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_task_reminder(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION sync_task_due_reminder() TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE task_reminders IS 'First-class NoteSnoop reminder records synchronized from task due dates.';
