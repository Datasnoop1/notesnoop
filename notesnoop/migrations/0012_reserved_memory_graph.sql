-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  domain TEXT,
  description TEXT,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_companies_workspace_name
  ON companies(workspace_id, lower(name));
CREATE INDEX IF NOT EXISTS idx_notesnoop_companies_workspace_created
  ON companies(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  occurred_at TIMESTAMPTZ,
  location TEXT,
  summary TEXT,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_meetings_workspace_time
  ON meetings(workspace_id, coalesce(occurred_at, created_at) DESC);

CREATE TABLE IF NOT EXISTS tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK (status IN ('todo','doing','blocked','done','archived')) DEFAULT 'todo',
  priority SMALLINT NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  due_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_tasks_workspace_status_due
  ON tasks(workspace_id, status, due_at NULLS LAST, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notesnoop_tasks_workspace_created
  ON tasks(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workflows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK (status IN ('draft','active','paused','retired')) DEFAULT 'draft',
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_workflows_workspace_name
  ON workflows(workspace_id, lower(name));
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflows_workspace_status
  ON workflows(workspace_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  body TEXT,
  status TEXT NOT NULL CHECK (status IN ('draft','published','archived')) DEFAULT 'draft',
  period_start DATE,
  period_end DATE,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_reports_workspace_status_created
  ON reports(workspace_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS company_people (
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  role TEXT,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (company_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_company_people_person
  ON company_people(person_id, company_id);

CREATE TABLE IF NOT EXISTS company_projects (
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (company_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_company_projects_project
  ON company_projects(project_id, company_id);

CREATE TABLE IF NOT EXISTS company_notes (
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (company_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_company_notes_note
  ON company_notes(note_id, company_id);

CREATE TABLE IF NOT EXISTS meeting_people (
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  attendance_status TEXT NOT NULL CHECK (attendance_status IN ('invited','attended','absent')) DEFAULT 'attended',
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (meeting_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_meeting_people_person
  ON meeting_people(person_id, meeting_id);

CREATE TABLE IF NOT EXISTS meeting_projects (
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (meeting_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_meeting_projects_project
  ON meeting_projects(project_id, meeting_id);

CREATE TABLE IF NOT EXISTS meeting_notes (
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (meeting_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_meeting_notes_note
  ON meeting_notes(note_id, meeting_id);

CREATE TABLE IF NOT EXISTS task_people (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  relation TEXT NOT NULL CHECK (relation IN ('assignee','requester','watcher')) DEFAULT 'assignee',
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (task_id, person_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_task_people_person
  ON task_people(person_id, task_id);

CREATE TABLE IF NOT EXISTS task_projects (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (task_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_task_projects_project
  ON task_projects(project_id, task_id);

CREATE TABLE IF NOT EXISTS task_notes (
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (task_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_task_notes_note
  ON task_notes(note_id, task_id);

CREATE TABLE IF NOT EXISTS workflow_projects (
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (workflow_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflow_projects_project
  ON workflow_projects(project_id, workflow_id);

CREATE TABLE IF NOT EXISTS workflow_people (
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  relation TEXT NOT NULL CHECK (relation IN ('owner','participant','watcher')) DEFAULT 'participant',
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (workflow_id, person_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflow_people_person
  ON workflow_people(person_id, workflow_id);

CREATE TABLE IF NOT EXISTS workflow_notes (
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (workflow_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflow_notes_note
  ON workflow_notes(note_id, workflow_id);

CREATE TABLE IF NOT EXISTS workflow_tasks (
  workflow_id UUID REFERENCES workflows(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  position INT NOT NULL DEFAULT 0,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (workflow_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workflow_tasks_task
  ON workflow_tasks(task_id, workflow_id);

CREATE TABLE IF NOT EXISTS report_projects (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_projects_project
  ON report_projects(project_id, report_id);

CREATE TABLE IF NOT EXISTS report_people (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_people_person
  ON report_people(person_id, report_id);

CREATE TABLE IF NOT EXISTS report_notes (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_notes_note
  ON report_notes(note_id, report_id);

CREATE TABLE IF NOT EXISTS report_tasks (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_tasks_task
  ON report_tasks(task_id, report_id);

CREATE TABLE IF NOT EXISTS report_companies (
  report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
  company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (report_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_report_companies_company
  ON report_companies(company_id, report_id);

CREATE OR REPLACE FUNCTION enforce_memory_link_workspace() RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  idx INT;
  parent_id UUID;
  parent_workspace UUID;
BEGIN
  idx := 0;
  WHILE idx < TG_NARGS LOOP
    EXECUTE format('SELECT ($1).%I::uuid', TG_ARGV[idx + 1]) INTO parent_id USING NEW;
    IF parent_id IS NOT NULL THEN
      EXECUTE format('SELECT workspace_id FROM %I WHERE id = $1', TG_ARGV[idx])
        INTO parent_workspace
        USING parent_id;
      IF parent_workspace IS NULL OR parent_workspace <> NEW.workspace_id THEN
        RAISE EXCEPTION 'workspace mismatch on %.%', TG_TABLE_NAME, TG_ARGV[idx + 1]
          USING ERRCODE = '23514';
      END IF;
    END IF;
    idx := idx + 2;
  END LOOP;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_company_people_workspace ON company_people;
CREATE TRIGGER trg_company_people_workspace
  BEFORE INSERT OR UPDATE ON company_people
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('companies', 'company_id', 'people', 'person_id');

DROP TRIGGER IF EXISTS trg_company_projects_workspace ON company_projects;
CREATE TRIGGER trg_company_projects_workspace
  BEFORE INSERT OR UPDATE ON company_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('companies', 'company_id', 'projects', 'project_id');

DROP TRIGGER IF EXISTS trg_company_notes_workspace ON company_notes;
CREATE TRIGGER trg_company_notes_workspace
  BEFORE INSERT OR UPDATE ON company_notes
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('companies', 'company_id', 'notes', 'note_id');

DROP TRIGGER IF EXISTS trg_meeting_people_workspace ON meeting_people;
CREATE TRIGGER trg_meeting_people_workspace
  BEFORE INSERT OR UPDATE ON meeting_people
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('meetings', 'meeting_id', 'people', 'person_id');

DROP TRIGGER IF EXISTS trg_meeting_projects_workspace ON meeting_projects;
CREATE TRIGGER trg_meeting_projects_workspace
  BEFORE INSERT OR UPDATE ON meeting_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('meetings', 'meeting_id', 'projects', 'project_id');

DROP TRIGGER IF EXISTS trg_meeting_notes_workspace ON meeting_notes;
CREATE TRIGGER trg_meeting_notes_workspace
  BEFORE INSERT OR UPDATE ON meeting_notes
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('meetings', 'meeting_id', 'notes', 'note_id');

DROP TRIGGER IF EXISTS trg_task_people_workspace ON task_people;
CREATE TRIGGER trg_task_people_workspace
  BEFORE INSERT OR UPDATE ON task_people
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('tasks', 'task_id', 'people', 'person_id');

DROP TRIGGER IF EXISTS trg_task_projects_workspace ON task_projects;
CREATE TRIGGER trg_task_projects_workspace
  BEFORE INSERT OR UPDATE ON task_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('tasks', 'task_id', 'projects', 'project_id');

DROP TRIGGER IF EXISTS trg_task_notes_workspace ON task_notes;
CREATE TRIGGER trg_task_notes_workspace
  BEFORE INSERT OR UPDATE ON task_notes
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('tasks', 'task_id', 'notes', 'note_id');

DROP TRIGGER IF EXISTS trg_workflow_projects_workspace ON workflow_projects;
CREATE TRIGGER trg_workflow_projects_workspace
  BEFORE INSERT OR UPDATE ON workflow_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('workflows', 'workflow_id', 'projects', 'project_id');

DROP TRIGGER IF EXISTS trg_workflow_people_workspace ON workflow_people;
CREATE TRIGGER trg_workflow_people_workspace
  BEFORE INSERT OR UPDATE ON workflow_people
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('workflows', 'workflow_id', 'people', 'person_id');

DROP TRIGGER IF EXISTS trg_workflow_notes_workspace ON workflow_notes;
CREATE TRIGGER trg_workflow_notes_workspace
  BEFORE INSERT OR UPDATE ON workflow_notes
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('workflows', 'workflow_id', 'notes', 'note_id');

DROP TRIGGER IF EXISTS trg_workflow_tasks_workspace ON workflow_tasks;
CREATE TRIGGER trg_workflow_tasks_workspace
  BEFORE INSERT OR UPDATE ON workflow_tasks
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('workflows', 'workflow_id', 'tasks', 'task_id');

DROP TRIGGER IF EXISTS trg_report_projects_workspace ON report_projects;
CREATE TRIGGER trg_report_projects_workspace
  BEFORE INSERT OR UPDATE ON report_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'projects', 'project_id');

DROP TRIGGER IF EXISTS trg_report_people_workspace ON report_people;
CREATE TRIGGER trg_report_people_workspace
  BEFORE INSERT OR UPDATE ON report_people
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'people', 'person_id');

DROP TRIGGER IF EXISTS trg_report_notes_workspace ON report_notes;
CREATE TRIGGER trg_report_notes_workspace
  BEFORE INSERT OR UPDATE ON report_notes
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'notes', 'note_id');

DROP TRIGGER IF EXISTS trg_report_tasks_workspace ON report_tasks;
CREATE TRIGGER trg_report_tasks_workspace
  BEFORE INSERT OR UPDATE ON report_tasks
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'tasks', 'task_id');

DROP TRIGGER IF EXISTS trg_report_companies_workspace ON report_companies;
CREATE TRIGGER trg_report_companies_workspace
  BEFORE INSERT OR UPDATE ON report_companies
  FOR EACH ROW EXECUTE FUNCTION enforce_memory_link_workspace('reports', 'report_id', 'companies', 'company_id');

CREATE OR REPLACE FUNCTION can_access_company(target_company_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM companies c
    WHERE c.id = target_company_id
      AND is_workspace_member(c.workspace_id)
  )
$$;

CREATE OR REPLACE FUNCTION can_access_meeting(target_meeting_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM meetings m
    WHERE m.id = target_meeting_id
      AND is_workspace_member(m.workspace_id)
  )
$$;

CREATE OR REPLACE FUNCTION can_access_task(target_task_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM tasks t
    WHERE t.id = target_task_id
      AND is_workspace_member(t.workspace_id)
  )
$$;

CREATE OR REPLACE FUNCTION can_access_workflow(target_workflow_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workflows w
    WHERE w.id = target_workflow_id
      AND is_workspace_member(w.workspace_id)
  )
$$;

CREATE OR REPLACE FUNCTION can_access_report(target_report_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM reports r
    WHERE r.id = target_report_id
      AND is_workspace_member(r.workspace_id)
  )
$$;

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS companies_workspace_access ON companies;
CREATE POLICY companies_workspace_access ON companies
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = current_user_id()));

DROP POLICY IF EXISTS meetings_workspace_access ON meetings;
CREATE POLICY meetings_workspace_access ON meetings
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = current_user_id()));

DROP POLICY IF EXISTS tasks_workspace_access ON tasks;
CREATE POLICY tasks_workspace_access ON tasks
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = current_user_id()));

DROP POLICY IF EXISTS workflows_workspace_access ON workflows;
CREATE POLICY workflows_workspace_access ON workflows
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = current_user_id()));

DROP POLICY IF EXISTS reports_workspace_access ON reports;
CREATE POLICY reports_workspace_access ON reports
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id) AND (created_by IS NULL OR created_by = current_user_id()));

DROP POLICY IF EXISTS company_people_resource_access ON company_people;
CREATE POLICY company_people_resource_access ON company_people
  USING (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_person(person_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS company_projects_resource_access ON company_projects;
CREATE POLICY company_projects_resource_access ON company_projects
  USING (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_project(project_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS company_notes_resource_access ON company_notes;
CREATE POLICY company_notes_resource_access ON company_notes
  USING (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_company(company_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS meeting_people_resource_access ON meeting_people;
CREATE POLICY meeting_people_resource_access ON meeting_people
  USING (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_person(person_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS meeting_projects_resource_access ON meeting_projects;
CREATE POLICY meeting_projects_resource_access ON meeting_projects
  USING (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_project(project_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS meeting_notes_resource_access ON meeting_notes;
CREATE POLICY meeting_notes_resource_access ON meeting_notes
  USING (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_meeting(meeting_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS task_people_resource_access ON task_people;
CREATE POLICY task_people_resource_access ON task_people
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_person(person_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS task_projects_resource_access ON task_projects;
CREATE POLICY task_projects_resource_access ON task_projects
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_project(project_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS task_notes_resource_access ON task_notes;
CREATE POLICY task_notes_resource_access ON task_notes
  USING (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS workflow_projects_resource_access ON workflow_projects;
CREATE POLICY workflow_projects_resource_access ON workflow_projects
  USING (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_project(project_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS workflow_people_resource_access ON workflow_people;
CREATE POLICY workflow_people_resource_access ON workflow_people
  USING (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_person(person_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS workflow_notes_resource_access ON workflow_notes;
CREATE POLICY workflow_notes_resource_access ON workflow_notes
  USING (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS workflow_tasks_resource_access ON workflow_tasks;
CREATE POLICY workflow_tasks_resource_access ON workflow_tasks
  USING (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_task(task_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_workflow(workflow_id) AND can_access_task(task_id));

DROP POLICY IF EXISTS report_projects_resource_access ON report_projects;
CREATE POLICY report_projects_resource_access ON report_projects
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_project(project_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS report_people_resource_access ON report_people;
CREATE POLICY report_people_resource_access ON report_people
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_person(person_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS report_notes_resource_access ON report_notes;
CREATE POLICY report_notes_resource_access ON report_notes
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS report_tasks_resource_access ON report_tasks;
CREATE POLICY report_tasks_resource_access ON report_tasks
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_task(task_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_task(task_id));

DROP POLICY IF EXISTS report_companies_resource_access ON report_companies;
CREATE POLICY report_companies_resource_access ON report_companies
  USING (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_company(company_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_report(report_id) AND can_access_company(company_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON
  companies,
  meetings,
  tasks,
  workflows,
  reports,
  company_people,
  company_projects,
  company_notes,
  meeting_people,
  meeting_projects,
  meeting_notes,
  task_people,
  task_projects,
  task_notes,
  workflow_projects,
  workflow_people,
  workflow_notes,
  workflow_tasks,
  report_projects,
  report_people,
  report_notes,
  report_tasks,
  report_companies
TO notesnoop_app, notesnoop_worker;

GRANT EXECUTE ON FUNCTION can_access_company(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_meeting(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_task(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_workflow(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_report(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION enforce_memory_link_workspace() TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE companies IS 'Reserved NoteSnoop memory graph node for workspace companies.';
COMMENT ON TABLE meetings IS 'Reserved NoteSnoop memory graph node for workspace meetings.';
COMMENT ON TABLE tasks IS 'Reserved NoteSnoop memory graph node for workspace tasks.';
COMMENT ON TABLE workflows IS 'Reserved NoteSnoop memory graph node for workspace workflows.';
COMMENT ON TABLE reports IS 'Reserved NoteSnoop memory graph node for workspace reports.';
