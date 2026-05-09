-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

DROP POLICY IF EXISTS notes_creator_returning_select ON notes;
CREATE POLICY notes_creator_returning_select ON notes
  FOR SELECT
  USING (created_by = current_user_id() AND is_workspace_member(workspace_id));
