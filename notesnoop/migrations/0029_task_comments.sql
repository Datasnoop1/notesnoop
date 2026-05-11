-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Threaded comments on a task. The "managing other people's to-dos" pillar
-- needs a place to record decisions, blockers, and updates against a single
-- task without polluting the task body itself.

CREATE TABLE IF NOT EXISTS task_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author_user_id TEXT NOT NULL REFERENCES user_profiles(clerk_user_id),
  author_name TEXT,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_comments_task
  ON task_comments(task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_comments_workspace_recent
  ON task_comments(workspace_id, created_at DESC);

CREATE OR REPLACE FUNCTION can_access_task_comment(target_comment_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM task_comments tc
    WHERE tc.id = target_comment_id
      AND is_workspace_member(tc.workspace_id)
      AND can_access_task(tc.task_id)
  )
$$;

ALTER TABLE task_comments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS task_comments_task_access ON task_comments;
CREATE POLICY task_comments_task_access ON task_comments
  USING (can_access_task_comment(id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_task(task_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON task_comments TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION can_access_task_comment(UUID) TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE task_comments IS 'Threaded comments on a task — used to record updates, decisions, and blockers against an individual to-do.';
