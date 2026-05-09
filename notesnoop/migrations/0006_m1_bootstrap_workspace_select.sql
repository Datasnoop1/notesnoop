-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

DROP POLICY IF EXISTS workspaces_self_bootstrap_select ON workspaces;
CREATE POLICY workspaces_self_bootstrap_select ON workspaces
  FOR SELECT
  USING (clerk_org_id = 'personal:' || current_user_id());
