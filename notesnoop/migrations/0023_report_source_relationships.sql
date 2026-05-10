-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS report_meetings (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, meeting_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_meetings_meeting
  ON report_meetings(meeting_id, report_id);

CREATE TABLE IF NOT EXISTS report_workflows (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, workflow_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_workflows_workflow
  ON report_workflows(workflow_id, report_id);

CREATE TABLE IF NOT EXISTS report_reports (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  source_report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, source_report_id),
  CHECK (report_id <> source_report_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_reports_source
  ON report_reports(source_report_id, report_id);

DROP TRIGGER IF EXISTS trg_report_meetings_workspace ON report_meetings;
CREATE TRIGGER trg_report_meetings_workspace
  BEFORE INSERT OR UPDATE ON report_meetings
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'meetings', 'meeting_id');

DROP TRIGGER IF EXISTS trg_report_workflows_workspace ON report_workflows;
CREATE TRIGGER trg_report_workflows_workspace
  BEFORE INSERT OR UPDATE ON report_workflows
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'workflows', 'workflow_id');

DROP TRIGGER IF EXISTS trg_report_reports_workspace ON report_reports;
CREATE TRIGGER trg_report_reports_workspace
  BEFORE INSERT OR UPDATE ON report_reports
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'reports', 'source_report_id');

ALTER TABLE report_meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS report_meetings_resource_access ON report_meetings;
CREATE POLICY report_meetings_resource_access ON report_meetings
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_meeting(meeting_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_meeting(meeting_id));

DROP POLICY IF EXISTS report_workflows_resource_access ON report_workflows;
CREATE POLICY report_workflows_resource_access ON report_workflows
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_workflow(workflow_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_workflow(workflow_id));

DROP POLICY IF EXISTS report_reports_resource_access ON report_reports;
CREATE POLICY report_reports_resource_access ON report_reports
  USING (
    is_workspace_member(workspace_id)
    AND can_access_report(report_id)
    AND EXISTS (
      SELECT 1 FROM reports source_report
      WHERE source_report.id = source_report_id
        AND source_report.workspace_id = report_reports.workspace_id
    )
  )
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND can_access_report(report_id)
    AND EXISTS (
      SELECT 1 FROM reports source_report
      WHERE source_report.id = source_report_id
        AND source_report.workspace_id = report_reports.workspace_id
    )
  );

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
        OR EXISTS (
          SELECT 1 FROM report_meetings rm
          WHERE rm.report_id = r.id
            AND can_access_meeting(rm.meeting_id)
        )
        OR EXISTS (
          SELECT 1 FROM report_workflows rw
          WHERE rw.report_id = r.id
            AND can_access_workflow(rw.workflow_id)
        )
      )
  )
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  report_meetings,
  report_workflows,
  report_reports
TO notesnoop_app, notesnoop_worker;

GRANT EXECUTE ON FUNCTION can_access_report(UUID) TO notesnoop_app, notesnoop_worker;
