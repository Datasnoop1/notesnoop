CREATE OR REPLACE FUNCTION has_pending_workspace_invite(target_workspace_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM project_invites pi
    WHERE pi.workspace_id = target_workspace_id
      AND pi.status = 'pending'
      AND lower(pi.email) = lower(current_user_email())
  )
$$;

CREATE OR REPLACE FUNCTION can_bootstrap_workspace_member(
  target_workspace_id UUID,
  target_user_id TEXT,
  target_role TEXT
) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT target_user_id = current_user_id()
    AND target_role = 'admin'
    AND EXISTS (
      SELECT 1
      FROM workspaces w
      WHERE w.id = target_workspace_id
        AND w.clerk_org_id = 'personal:' || current_user_id()
        AND w.created_at >= transaction_timestamp() - interval '5 minutes'
        AND NOT EXISTS (
          SELECT 1
          FROM workspace_members wm
          WHERE wm.workspace_id = w.id
        )
    )
$$;

CREATE OR REPLACE FUNCTION update_own_workspace_member_settings(
  target_workspace_id UUID,
  next_email_ai_mode TEXT,
  next_morning_briefing_optin BOOLEAN
) RETURNS workspace_members
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  updated workspace_members;
BEGIN
  UPDATE workspace_members
  SET email_ai_mode = COALESCE(next_email_ai_mode, email_ai_mode),
      morning_briefing_optin = COALESCE(next_morning_briefing_optin, morning_briefing_optin)
  WHERE workspace_id = target_workspace_id
    AND clerk_user_id = current_user_id()
    AND is_workspace_member(target_workspace_id)
  RETURNING * INTO updated;

  RETURN updated;
END;
$$;

DROP POLICY IF EXISTS workspace_members_self_or_admin ON workspace_members;
DROP POLICY IF EXISTS workspace_members_self_bootstrap_insert ON workspace_members;
DROP POLICY IF EXISTS workspace_members_select_self_or_admin ON workspace_members;
CREATE POLICY workspace_members_select_self_or_admin ON workspace_members
  FOR SELECT
  USING (clerk_user_id = current_user_id() OR is_workspace_admin(workspace_id));

DROP POLICY IF EXISTS workspace_members_admin_insert ON workspace_members;
CREATE POLICY workspace_members_admin_insert ON workspace_members
  FOR INSERT
  WITH CHECK (is_workspace_admin(workspace_id));

DROP POLICY IF EXISTS workspace_members_invitee_insert ON workspace_members;
CREATE POLICY workspace_members_invitee_insert ON workspace_members
  FOR INSERT
  WITH CHECK (
    clerk_user_id = current_user_id()
    AND role = 'member'
    AND has_pending_workspace_invite(workspace_id)
  );

DROP POLICY IF EXISTS workspace_members_bootstrap_insert ON workspace_members;
CREATE POLICY workspace_members_bootstrap_insert ON workspace_members
  FOR INSERT
  WITH CHECK (can_bootstrap_workspace_member(workspace_id, clerk_user_id, role));

DROP POLICY IF EXISTS workspace_members_admin_update ON workspace_members;
CREATE POLICY workspace_members_admin_update ON workspace_members
  FOR UPDATE
  USING (is_workspace_admin(workspace_id))
  WITH CHECK (is_workspace_admin(workspace_id));

DROP POLICY IF EXISTS workspace_members_self_settings_update ON workspace_members;

DROP POLICY IF EXISTS workspace_members_admin_delete ON workspace_members;
CREATE POLICY workspace_members_admin_delete ON workspace_members
  FOR DELETE
  USING (is_workspace_admin(workspace_id));

DROP POLICY IF EXISTS projects_creator_bootstrap_select ON projects;

CREATE OR REPLACE FUNCTION can_access_project(target_project_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM projects p
    JOIN workspaces w ON w.id = p.workspace_id
    WHERE p.id = target_project_id
      AND is_workspace_member(p.workspace_id)
      AND (
        (
          p.kind <> 'inbox'
          AND p.kind <> 'personal'
          AND is_workspace_admin(p.workspace_id)
        )
        OR (
          p.kind <> 'personal'
          AND p.shared = TRUE
          AND coalesce(w.inbox_mode, 'per_user_private') = 'shared'
          AND p.kind = 'inbox'
        )
        OR (
          p.kind = 'inbox'
          AND p.shared = FALSE
          AND coalesce(w.inbox_mode, 'per_user_private') <> 'shared'
          AND p.created_by = current_user_id()
        )
        OR (
          p.kind <> 'inbox'
          AND p.created_by = current_user_id()
        )
        OR (
          p.kind NOT IN ('inbox', 'personal')
          AND EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id = p.id
              AND pm.clerk_user_id = current_user_id()
          )
        )
      )
  )
$$;

GRANT EXECUTE ON FUNCTION has_pending_workspace_invite(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_bootstrap_workspace_member(UUID, TEXT, TEXT) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION update_own_workspace_member_settings(UUID, TEXT, BOOLEAN) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_project(UUID) TO notesnoop_app, notesnoop_worker;
