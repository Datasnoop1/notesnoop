-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE OR REPLACE FUNCTION home_accessible_note_project_links(
  target_workspace_id UUID,
  target_project_id UUID DEFAULT NULL
) RETURNS TABLE(note_id UUID, project_id UUID)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT np.note_id, np.project_id
  FROM note_projects np
  JOIN notes n ON n.id = np.note_id
  WHERE n.workspace_id = target_workspace_id
    AND is_workspace_member(n.workspace_id)
    AND (target_project_id IS NULL OR np.project_id = target_project_id)
    AND (
      n.created_by = current_user_id()
      OR (n.is_personal = FALSE AND is_workspace_admin(n.workspace_id))
      OR can_access_project(np.project_id)
      OR EXISTS (
        SELECT 1
        FROM note_projects access_np
        WHERE access_np.note_id = n.id
          AND can_access_project(access_np.project_id)
      )
    )
$$;

GRANT EXECUTE ON FUNCTION home_accessible_note_project_links(UUID, UUID) TO notesnoop_app, notesnoop_worker;
