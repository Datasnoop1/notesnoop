-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE OR REPLACE FUNCTION can_access_task(target_task_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM tasks t
    WHERE t.id = target_task_id
      AND is_workspace_member(t.workspace_id)
      AND (
        t.created_by = current_user_id()
        OR is_workspace_admin(t.workspace_id)
        OR EXISTS (
          SELECT 1 FROM task_projects tp
          WHERE tp.task_id = t.id
            AND can_access_project(tp.project_id)
        )
        OR EXISTS (
          SELECT 1 FROM task_notes tn
          WHERE tn.task_id = t.id
            AND can_access_note(tn.note_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_meeting(target_meeting_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM meetings m
    WHERE m.id = target_meeting_id
      AND is_workspace_member(m.workspace_id)
      AND (
        m.created_by = current_user_id()
        OR is_workspace_admin(m.workspace_id)
        OR EXISTS (
          SELECT 1 FROM meeting_projects mp
          WHERE mp.meeting_id = m.id
            AND can_access_project(mp.project_id)
        )
        OR EXISTS (
          SELECT 1 FROM meeting_notes mn
          WHERE mn.meeting_id = m.id
            AND can_access_note(mn.note_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_report(target_report_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM reports r
    WHERE r.id = target_report_id
      AND is_workspace_member(r.workspace_id)
      AND (
        r.created_by = current_user_id()
        OR is_workspace_admin(r.workspace_id)
        OR EXISTS (
          SELECT 1 FROM report_projects rp
          WHERE rp.report_id = r.id
            AND can_access_project(rp.project_id)
        )
        OR EXISTS (
          SELECT 1 FROM report_notes rn
          WHERE rn.report_id = r.id
            AND can_access_note(rn.note_id)
        )
        OR EXISTS (
          SELECT 1 FROM report_tasks rt
          WHERE rt.report_id = r.id
            AND can_access_task(rt.task_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_workflow(target_workflow_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM workflows w
    WHERE w.id = target_workflow_id
      AND is_workspace_member(w.workspace_id)
      AND (
        w.created_by = current_user_id()
        OR is_workspace_admin(w.workspace_id)
        OR EXISTS (
          SELECT 1 FROM workflow_projects wp
          WHERE wp.workflow_id = w.id
            AND can_access_project(wp.project_id)
        )
        OR EXISTS (
          SELECT 1 FROM workflow_notes wn
          WHERE wn.workflow_id = w.id
            AND can_access_note(wn.note_id)
        )
        OR EXISTS (
          SELECT 1 FROM workflow_tasks wt
          WHERE wt.workflow_id = w.id
            AND can_access_task(wt.task_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_company(target_company_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM companies c
    WHERE c.id = target_company_id
      AND is_workspace_member(c.workspace_id)
      AND (
        c.created_by = current_user_id()
        OR is_workspace_admin(c.workspace_id)
        OR EXISTS (
          SELECT 1 FROM company_projects cp
          WHERE cp.company_id = c.id
            AND can_access_project(cp.project_id)
        )
        OR EXISTS (
          SELECT 1 FROM company_notes cn
          WHERE cn.company_id = c.id
            AND can_access_note(cn.note_id)
        )
        OR EXISTS (
          SELECT 1 FROM report_companies rc
          WHERE rc.company_id = c.id
            AND can_access_report(rc.report_id)
        )
      )
  )
$$;

DROP POLICY IF EXISTS companies_workspace_access ON companies;
CREATE POLICY companies_project_access ON companies
  USING (can_access_company(id))
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_company(id))
  );

DROP POLICY IF EXISTS meetings_workspace_access ON meetings;
CREATE POLICY meetings_project_access ON meetings
  USING (can_access_meeting(id))
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_meeting(id))
  );

DROP POLICY IF EXISTS tasks_workspace_access ON tasks;
CREATE POLICY tasks_project_access ON tasks
  USING (can_access_task(id))
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_task(id))
  );

DROP POLICY IF EXISTS workflows_workspace_access ON workflows;
CREATE POLICY workflows_project_access ON workflows
  USING (can_access_workflow(id))
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_workflow(id))
  );

DROP POLICY IF EXISTS reports_workspace_access ON reports;
CREATE POLICY reports_project_access ON reports
  USING (can_access_report(id))
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND (created_by = current_user_id() OR is_workspace_admin(workspace_id) OR can_access_report(id))
  );
