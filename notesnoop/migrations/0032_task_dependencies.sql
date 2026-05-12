-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Task dependencies — "task A is blocked by task B" — so the operator can
-- model "draft the term sheet" depending on "get the legal review back".
-- The relationship is directional: blocked_task_id waits on blocking_task_id.
-- A single task can be blocked by many, and can also block many.

CREATE TABLE IF NOT EXISTS task_dependencies (
  blocked_task_id  UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  blocking_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  created_by       TEXT REFERENCES user_profiles(clerk_user_id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (blocked_task_id, blocking_task_id),
  CHECK (blocked_task_id <> blocking_task_id)
);

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_deps_blocking
  ON task_dependencies(blocking_task_id, blocked_task_id);

CREATE INDEX IF NOT EXISTS idx_notesnoop_task_deps_workspace
  ON task_dependencies(workspace_id, created_at DESC);

ALTER TABLE task_dependencies ENABLE ROW LEVEL SECURITY;

-- Direct-column predicates per the 0031 lesson (id-based helpers fail INSERT
-- under non-owner roles because the row isn't visible during evaluation).
DROP POLICY IF EXISTS task_dependencies_select ON task_dependencies;
CREATE POLICY task_dependencies_select ON task_dependencies FOR SELECT
  USING (
    is_workspace_member(workspace_id)
    AND can_access_task(blocked_task_id)
    AND can_access_task(blocking_task_id)
  );

DROP POLICY IF EXISTS task_dependencies_insert ON task_dependencies;
CREATE POLICY task_dependencies_insert ON task_dependencies FOR INSERT
  WITH CHECK (
    is_workspace_member(workspace_id)
    AND can_access_task(blocked_task_id)
    AND can_access_task(blocking_task_id)
  );

DROP POLICY IF EXISTS task_dependencies_delete ON task_dependencies;
CREATE POLICY task_dependencies_delete ON task_dependencies FOR DELETE
  USING (
    is_workspace_member(workspace_id)
    AND can_access_task(blocked_task_id)
    AND can_access_task(blocking_task_id)
  );

GRANT SELECT, INSERT, DELETE ON task_dependencies TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE task_dependencies IS 'Directional dependency: blocked_task_id is waiting on blocking_task_id to finish.';
