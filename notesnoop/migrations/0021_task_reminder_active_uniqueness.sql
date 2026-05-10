-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY task_id, channel
      ORDER BY
        CASE state WHEN 'pending' THEN 0 ELSE 1 END,
        coalesce(snoozed_until, remind_at),
        updated_at DESC
    ) AS rn
  FROM task_reminders
  WHERE state IN ('pending','snoozed')
)
UPDATE task_reminders tr
SET state = 'dismissed',
    updated_at = now()
FROM ranked r
WHERE tr.id = r.id
  AND r.rn > 1;

DROP INDEX IF EXISTS idx_notesnoop_task_reminders_pending_task_channel;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_task_reminders_active_task_channel
  ON task_reminders(task_id, channel)
  WHERE state IN ('pending','snoozed');

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
    UPDATE task_reminders
    SET workspace_id = NEW.workspace_id,
        remind_at = NEW.due_at,
        state = 'pending',
        snoozed_until = NULL,
        created_by = COALESCE(created_by, NEW.created_by),
        updated_at = now()
    WHERE task_id = NEW.id
      AND channel = 'in_app'
      AND state IN ('pending','snoozed');

    IF NOT FOUND THEN
      INSERT INTO task_reminders (workspace_id, task_id, remind_at, channel, state, created_by)
      VALUES (NEW.workspace_id, NEW.id, NEW.due_at, 'in_app', 'pending', NEW.created_by)
      ON CONFLICT (task_id, channel) WHERE state IN ('pending','snoozed')
      DO UPDATE
        SET workspace_id = EXCLUDED.workspace_id,
            remind_at = EXCLUDED.remind_at,
            state = 'pending',
            snoozed_until = NULL,
            updated_at = now();
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

INSERT INTO task_reminders (workspace_id, task_id, remind_at, channel, state, created_by)
SELECT workspace_id, id, due_at, 'in_app', 'pending', created_by
FROM tasks
WHERE due_at IS NOT NULL
  AND status IN ('todo','doing','blocked')
ON CONFLICT (task_id, channel) WHERE state IN ('pending','snoozed')
DO UPDATE
  SET workspace_id = EXCLUDED.workspace_id,
      remind_at = EXCLUDED.remind_at,
      state = 'pending',
      snoozed_until = NULL,
      updated_at = now();

GRANT EXECUTE ON FUNCTION sync_task_due_reminder() TO notesnoop_app, notesnoop_worker;

COMMENT ON INDEX idx_notesnoop_task_reminders_active_task_channel IS 'At most one pending or snoozed reminder may be active per task/channel.';
