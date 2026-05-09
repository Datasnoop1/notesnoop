-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

DROP POLICY IF EXISTS companies_project_access ON companies;
CREATE POLICY companies_project_access ON companies
  USING (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_company(id))
  )
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS meetings_project_access ON meetings;
CREATE POLICY meetings_project_access ON meetings
  USING (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_meeting(id))
  )
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS tasks_project_access ON tasks;
CREATE POLICY tasks_project_access ON tasks
  USING (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_task(id))
  )
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS workflows_project_access ON workflows;
CREATE POLICY workflows_project_access ON workflows
  USING (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_workflow(id))
  )
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS reports_project_access ON reports;
CREATE POLICY reports_project_access ON reports
  USING (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_report(id))
  )
  WITH CHECK (is_workspace_member(workspace_id));
