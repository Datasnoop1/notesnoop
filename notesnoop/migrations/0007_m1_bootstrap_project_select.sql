-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

DROP POLICY IF EXISTS projects_creator_bootstrap_select ON projects;
CREATE POLICY projects_creator_bootstrap_select ON projects
  FOR SELECT
  USING (created_by = current_user_id() AND is_workspace_member(workspace_id));
