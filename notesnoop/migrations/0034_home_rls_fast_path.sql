-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Keep the same visibility semantics, but put cheap row-column checks before
-- id-based helper calls. The helpers are still needed for shared project
-- visibility, but dashboard-scale scans should not re-select every note the
-- current user created before trying that simple path.

DROP POLICY IF EXISTS notes_project_access ON notes;
CREATE POLICY notes_project_access ON notes
  USING ((created_by = current_user_id() AND is_workspace_member(workspace_id)) OR can_access_note(id))
  WITH CHECK (created_by = current_user_id() AND is_workspace_member(workspace_id));

DROP POLICY IF EXISTS note_projects_note_access ON note_projects;
CREATE POLICY note_projects_note_access ON note_projects
  USING (can_access_project(project_id) OR can_access_note(note_id))
  WITH CHECK (can_access_note(note_id) AND can_access_project(project_id));
