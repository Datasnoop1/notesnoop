-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS project_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT,
  status TEXT NOT NULL CHECK (status IN ('pending','accepted','revoked')) DEFAULT 'pending',
  invited_by TEXT NOT NULL REFERENCES user_profiles(clerk_user_id),
  accepted_by TEXT REFERENCES user_profiles(clerk_user_id),
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_project_invites_pending_email
  ON project_invites(project_id, lower(email))
  WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_notesnoop_project_invites_email
  ON project_invites(lower(email), status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notesnoop_project_invites_workspace
  ON project_invites(workspace_id, created_at DESC);

CREATE OR REPLACE FUNCTION current_user_email() RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT email
  FROM user_profiles
  WHERE clerk_user_id = current_user_id()
$$;

CREATE OR REPLACE FUNCTION has_pending_project_invite(target_project_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM project_invites pi
    WHERE pi.project_id = target_project_id
      AND pi.status = 'pending'
      AND lower(pi.email) = lower(current_user_email())
  )
$$;

CREATE OR REPLACE FUNCTION can_access_project(target_project_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM projects p
    WHERE p.id = target_project_id
      AND (
        p.created_by = current_user_id()
        OR EXISTS (
          SELECT 1 FROM project_members pm
          WHERE pm.project_id = p.id
            AND pm.clerk_user_id = current_user_id()
        )
        OR (
          p.kind <> 'personal'
          AND p.shared = TRUE
          AND is_workspace_member(p.workspace_id)
        )
        OR (
          p.kind <> 'personal'
          AND is_workspace_admin(p.workspace_id)
        )
      )
  )
$$;

ALTER TABLE project_invites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS project_invites_admin_or_invitee_select ON project_invites;
CREATE POLICY project_invites_admin_or_invitee_select ON project_invites
  FOR SELECT
  USING (
    is_workspace_admin(workspace_id)
    OR lower(email) = lower(current_user_email())
  );

DROP POLICY IF EXISTS project_invites_admin_insert ON project_invites;
CREATE POLICY project_invites_admin_insert ON project_invites
  FOR INSERT
  WITH CHECK (
    is_workspace_admin(workspace_id)
    AND invited_by = current_user_id()
  );

DROP POLICY IF EXISTS project_invites_admin_or_invitee_update ON project_invites;
CREATE POLICY project_invites_admin_or_invitee_update ON project_invites
  FOR UPDATE
  USING (
    is_workspace_admin(workspace_id)
    OR (status = 'pending' AND lower(email) = lower(current_user_email()))
  )
  WITH CHECK (
    is_workspace_admin(workspace_id)
    OR (
      status = 'accepted'
      AND accepted_by = current_user_id()
      AND lower(email) = lower(current_user_email())
    )
  );

DROP POLICY IF EXISTS project_members_invited_insert ON project_members;
CREATE POLICY project_members_invited_insert ON project_members
  FOR INSERT
  WITH CHECK (
    clerk_user_id = current_user_id()
    AND has_pending_project_invite(project_id)
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON project_invites TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION current_user_email() TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION has_pending_project_invite(UUID) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_project(UUID) TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE project_invites IS 'Email-based NoteSnoop project invitations. Pending invites auto-accept when a matching Clerk user signs in.';
