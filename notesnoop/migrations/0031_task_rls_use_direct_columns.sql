-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- 0030 split the FOR ALL policy into per-command policies, hoping to avoid
-- USING evaluation on INSERT. But the API issues INSERT ... RETURNING, and
-- RETURNING causes the SELECT policy's USING to fire against the freshly
-- inserted row. The id-based helpers (can_access_task_comment /
-- can_access_task_reminder) do a SELECT from their own table looking for
-- that id — which the policy evaluation can't yet observe, so USING
-- returns false and the row gets rejected on the way out.
--
-- For any row that lives in the table, evaluating USING via the
-- id-based helper is equivalent to evaluating it via the row's
-- workspace_id + task_id directly (the FKs guarantee they line up).
-- Using the direct column predicates avoids the in-flight visibility
-- problem and is identical in semantics for any existing row.

-- ----- task_comments -----
DROP POLICY IF EXISTS task_comments_select ON task_comments;
DROP POLICY IF EXISTS task_comments_insert ON task_comments;
DROP POLICY IF EXISTS task_comments_update ON task_comments;
DROP POLICY IF EXISTS task_comments_delete ON task_comments;

CREATE POLICY task_comments_select ON task_comments FOR SELECT
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_comments_insert ON task_comments FOR INSERT
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_comments_update ON task_comments FOR UPDATE
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_comments_delete ON task_comments FOR DELETE
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id));

-- ----- task_reminders -----
DROP POLICY IF EXISTS task_reminders_select ON task_reminders;
DROP POLICY IF EXISTS task_reminders_insert ON task_reminders;
DROP POLICY IF EXISTS task_reminders_update ON task_reminders;
DROP POLICY IF EXISTS task_reminders_delete ON task_reminders;

CREATE POLICY task_reminders_select ON task_reminders FOR SELECT
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_reminders_insert ON task_reminders FOR INSERT
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_reminders_update ON task_reminders FOR UPDATE
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

CREATE POLICY task_reminders_delete ON task_reminders FOR DELETE
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id));
