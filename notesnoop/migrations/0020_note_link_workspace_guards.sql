-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM note_projects np
    JOIN notes n ON n.id = np.note_id
    JOIN projects p ON p.id = np.project_id
    WHERE n.workspace_id <> p.workspace_id
  ) THEN
    RAISE EXCEPTION 'note_projects contains cross-workspace links'
      USING ERRCODE = '23514';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM note_people_links npl
    JOIN notes n ON n.id = npl.note_id
    JOIN people p ON p.id = npl.person_id
    WHERE n.workspace_id <> p.workspace_id
  ) THEN
    RAISE EXCEPTION 'note_people_links contains cross-workspace links'
      USING ERRCODE = '23514';
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_note_project_workspace() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  note_workspace UUID;
  project_workspace UUID;
BEGIN
  SELECT workspace_id INTO note_workspace FROM notes WHERE id = NEW.note_id;
  SELECT workspace_id INTO project_workspace FROM projects WHERE id = NEW.project_id;
  IF note_workspace IS NULL OR project_workspace IS NULL OR note_workspace <> project_workspace THEN
    RAISE EXCEPTION 'workspace mismatch on note_projects'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_note_projects_workspace ON note_projects;
CREATE TRIGGER trg_note_projects_workspace
  BEFORE INSERT OR UPDATE ON note_projects
  FOR EACH ROW EXECUTE FUNCTION enforce_note_project_workspace();

CREATE OR REPLACE FUNCTION enforce_note_people_link_workspace() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  note_workspace UUID;
  person_workspace UUID;
BEGIN
  SELECT workspace_id INTO note_workspace FROM notes WHERE id = NEW.note_id;
  SELECT workspace_id INTO person_workspace FROM people WHERE id = NEW.person_id;
  IF note_workspace IS NULL OR person_workspace IS NULL OR note_workspace <> person_workspace THEN
    RAISE EXCEPTION 'workspace mismatch on note_people_links'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_note_people_links_workspace ON note_people_links;
CREATE TRIGGER trg_note_people_links_workspace
  BEFORE INSERT OR UPDATE ON note_people_links
  FOR EACH ROW EXECUTE FUNCTION enforce_note_people_link_workspace();
