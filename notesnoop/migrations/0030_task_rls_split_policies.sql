-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Both task_comments (0029) and task_reminders (0019) shipped with a single
-- FOR ALL policy that combined USING (can_access_..._by_id(id)) with WITH
-- CHECK (is_workspace_member AND can_access_task). PostgreSQL evaluates the
-- USING clause against the newly-inserted row's id for INSERT statements
-- run by a non-owner (e.g. notesnoop_app), and the helper function does a
-- SELECT from the same table looking for that id — which is not yet
-- visible to the policy's USING context, so USING returns false and INSERT
-- is rejected with "new row violates row-level security policy".
--
-- Fix: split the FOR ALL policy into per-command policies. INSERT only needs
-- WITH CHECK; SELECT / UPDATE / DELETE rely on USING.

-- ----- task_comments -----
DROP POLICY IF EXISTS task_comments_task_access ON task_comments;

CREATE POLICY task_comments_select ON task_comments FOR SELECT
  USING (can_access_task_comment(id));

CREATE POLICY task_comments_insert ON task_comments FOR INSERT
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_comments_update ON task_comments FOR UPDATE
  USING (can_access_task_comment(id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_comments_delete ON task_comments FOR DELETE
  USING (can_access_task_comment(id));

-- ----- task_reminders (same shape, same bug) -----
DROP POLICY IF EXISTS task_reminders_task_access ON task_reminders;

CREATE POLICY task_reminders_select ON task_reminders FOR SELECT
  USING (can_access_task_reminder(id));

CREATE POLICY task_reminders_insert ON task_reminders FOR INSERT
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_reminders_update ON task_reminders FOR UPDATE
  USING (can_access_task_reminder(id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_reminders_delete ON task_reminders FOR DELETE
  USING (can_access_task_reminder(id));
