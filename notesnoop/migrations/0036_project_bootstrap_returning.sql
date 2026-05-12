-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

-- /api/bootstrap creates the default Personal and Inbox projects under
-- notesnoop_app before project_members rows exist. The INSERT uses RETURNING,
-- so the freshly-created row also needs a direct SELECT policy; can_access_project(id)
-- is not reliable during INSERT/RETURNING evaluation. Keep the predicate in
-- direct columns, but preserve the 0035 inbox-mode visibility model.
DROP POLICY IF EXISTS projects_creator_returning_select ON projects;
CREATE POLICY projects_creator_returning_select ON projects
  FOR SELECT
  USING (
    created_by = current_user_id()
    AND is_workspace_member(workspace_id)
    AND (
      kind <> 'inbox'
      OR (
        kind = 'inbox'
        AND shared = FALSE
        AND EXISTS (
          SELECT 1
          FROM workspaces w
          WHERE w.id = workspace_id
            AND coalesce(w.inbox_mode, 'per_user_private') <> 'shared'
        )
      )
      OR (
        kind = 'inbox'
        AND shared = TRUE
        AND EXISTS (
          SELECT 1
          FROM workspaces w
          WHERE w.id = workspace_id
            AND coalesce(w.inbox_mode, 'per_user_private') = 'shared'
        )
      )
    )
  );
