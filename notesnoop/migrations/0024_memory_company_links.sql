-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS task_companies (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (task_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_task_companies_company
  ON task_companies(company_id, task_id);

CREATE TABLE IF NOT EXISTS meeting_companies (
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (meeting_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_meeting_companies_company
  ON meeting_companies(company_id, meeting_id);

CREATE TABLE IF NOT EXISTS workflow_companies (
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (workflow_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflow_companies_company
  ON workflow_companies(company_id, workflow_id);

DROP TRIGGER IF EXISTS trg_task_companies_workspace ON task_companies;
CREATE TRIGGER trg_task_companies_workspace
  BEFORE INSERT OR UPDATE ON task_companies
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('tasks', 'task_id', 'companies', 'company_id');

DROP TRIGGER IF EXISTS trg_meeting_companies_workspace ON meeting_companies;
CREATE TRIGGER trg_meeting_companies_workspace
  BEFORE INSERT OR UPDATE ON meeting_companies
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('meetings', 'meeting_id', 'companies', 'company_id');

DROP TRIGGER IF EXISTS trg_workflow_companies_workspace ON workflow_companies;
CREATE TRIGGER trg_workflow_companies_workspace
  BEFORE INSERT OR UPDATE ON workflow_companies
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('workflows', 'workflow_id', 'companies', 'company_id');

ALTER TABLE task_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_companies_resource_access ON task_companies;
CREATE POLICY task_companies_resource_access ON task_companies
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_company(company_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_company(company_id));

DROP POLICY IF EXISTS meeting_companies_resource_access ON meeting_companies;
CREATE POLICY meeting_companies_resource_access ON meeting_companies
  USING (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_company(company_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_company(company_id));

DROP POLICY IF EXISTS workflow_companies_resource_access ON workflow_companies;
CREATE POLICY workflow_companies_resource_access ON workflow_companies
  USING (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_company(company_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_company(company_id));

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
        OR EXISTS (
          SELECT 1 FROM task_companies tc
          WHERE tc.task_id = t.id
            AND can_access_company(tc.company_id)
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
        OR EXISTS (
          SELECT 1 FROM meeting_companies mc
          WHERE mc.meeting_id = m.id
            AND can_access_company(mc.company_id)
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
        OR EXISTS (
          SELECT 1 FROM workflow_companies wc
          WHERE wc.workflow_id = w.id
            AND can_access_company(wc.company_id)
        )
      )
  )
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  task_companies,
  meeting_companies,
  workflow_companies
TO notesnoop_app, notesnoop_worker;

GRANT EXECUTE ON FUNCTION can_access_task(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_meeting(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_workflow(UUID) TO notesnoop_app, notesnoop_worker;
