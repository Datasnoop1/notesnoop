-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notesnoop_app') THEN
    CREATE ROLE notesnoop_app NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notesnoop_worker') THEN
    CREATE ROLE notesnoop_worker BYPASSRLS NOINHERIT;
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO notesnoop_app, notesnoop_worker', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO notesnoop_app, notesnoop_worker;

CREATE TABLE IF NOT EXISTS user_profiles (
  clerk_user_id TEXT PRIMARY KEY,
  email TEXT,
  display_name TEXT,
  avatar_url TEXT,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_org_id TEXT NOT NULL,
  name TEXT NOT NULL,
  ai_mode TEXT NOT NULL CHECK (ai_mode IN ('on','manual')) DEFAULT 'on',
  inbox_mode TEXT NOT NULL CHECK (inbox_mode IN ('per_user_private','shared')) DEFAULT 'per_user_private',
  strict_personal_lockout BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workspaces_clerk_org ON workspaces(clerk_org_id);

CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('admin','member')) DEFAULT 'member',
  email_ai_mode TEXT NOT NULL CHECK (email_ai_mode IN ('auto','manual')) DEFAULT 'manual',
  morning_briefing_optin BOOLEAN NOT NULL DEFAULT FALSE,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, clerk_user_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_workspace_members_user ON workspace_members(clerk_user_id);

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color_hex TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('user','personal','inbox')) DEFAULT 'user',
  ai_mode TEXT NOT NULL CHECK (ai_mode IN ('on','manual')) DEFAULT 'on',
  shared BOOLEAN NOT NULL DEFAULT FALSE,
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_projects_workspace ON projects(workspace_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_project_owner_personal
  ON projects(workspace_id, created_by) WHERE kind = 'personal';
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_project_owner_inbox
  ON projects(workspace_id, created_by) WHERE kind = 'inbox' AND shared = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_project_shared_inbox
  ON projects(workspace_id) WHERE kind = 'inbox' AND shared = TRUE;

CREATE TABLE IF NOT EXISTS project_members (
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, clerk_user_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_project_members_user ON project_members(clerk_user_id);

CREATE TABLE IF NOT EXISTS notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT,
  title_is_derived BOOLEAN NOT NULL DEFAULT FALSE,
  body TEXT NOT NULL,
  raw_email_metadata JSONB,
  ai_processed_at TIMESTAMPTZ,
  ai_processing_status TEXT NOT NULL CHECK (ai_processing_status IN ('unprocessed','processing','processed','failed','skipped')) DEFAULT 'unprocessed',
  is_personal BOOLEAN NOT NULL DEFAULT FALSE,
  created_by TEXT NOT NULL REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_notes_workspace_created ON notes(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notesnoop_notes_workspace_status ON notes(workspace_id, ai_processing_status, created_at DESC);

ALTER TABLE notes
  ADD COLUMN IF NOT EXISTS search_vector tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(title,'') || ' ' || body)) STORED;
CREATE INDEX IF NOT EXISTS idx_notesnoop_notes_search ON notes USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS note_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  version INT NOT NULL,
  title TEXT,
  body TEXT NOT NULL,
  edited_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (note_id, version)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_note_versions_note ON note_versions(note_id, version DESC);

CREATE TABLE IF NOT EXISTS note_projects (
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  linked_by TEXT REFERENCES user_profiles(clerk_user_id),
  PRIMARY KEY (note_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_note_projects_project ON note_projects(project_id, note_id);

CREATE OR REPLACE FUNCTION refresh_note_is_personal() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  affected_note_id UUID;
BEGIN
  affected_note_id := COALESCE(NEW.note_id, OLD.note_id);
  UPDATE notes n
  SET is_personal = EXISTS (
    SELECT 1
    FROM note_projects np
    JOIN projects p ON p.id = np.project_id
    WHERE np.note_id = affected_note_id
      AND p.kind = 'personal'
  )
  WHERE n.id = affected_note_id;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_note_projects_personal ON note_projects;
CREATE TRIGGER trg_note_projects_personal
  AFTER INSERT OR UPDATE OR DELETE ON note_projects
  FOR EACH ROW EXECUTE FUNCTION refresh_note_is_personal();

CREATE OR REPLACE FUNCTION enforce_personal_exclusivity() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  has_personal BOOLEAN;
  has_other BOOLEAN;
BEGIN
  SELECT
    EXISTS (
      SELECT 1
      FROM note_projects np
      JOIN projects p ON p.id = np.project_id
      WHERE np.note_id = NEW.note_id
        AND p.kind = 'personal'
    ),
    EXISTS (
      SELECT 1
      FROM note_projects np
      JOIN projects p ON p.id = np.project_id
      WHERE np.note_id = NEW.note_id
        AND p.kind <> 'personal'
    )
  INTO has_personal, has_other;

  IF has_personal AND has_other THEN
    RAISE EXCEPTION 'Personal-project mutual exclusivity violated for note %', NEW.note_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_note_projects_personal_exclusive ON note_projects;
CREATE CONSTRAINT TRIGGER trg_note_projects_personal_exclusive
  AFTER INSERT OR UPDATE ON note_projects
  DEFERRABLE INITIALLY IMMEDIATE
  FOR EACH ROW EXECUTE FUNCTION enforce_personal_exclusivity();

CREATE TABLE IF NOT EXISTS people (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  company TEXT,
  details TEXT,
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id),
  created_by TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_people_workspace ON people(workspace_id);
CREATE INDEX IF NOT EXISTS idx_notesnoop_people_workspace_name ON people(workspace_id, lower(name));
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_people_unique_clerk_user
  ON people (workspace_id, clerk_user_id) WHERE clerk_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS note_people_links (
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('confirmed','auto_linked','pending')),
  confidence DOUBLE PRECISION,
  source TEXT NOT NULL CHECK (source IN ('user','ai','collaborator_suggestion')),
  source_user_id TEXT REFERENCES user_profiles(clerk_user_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (note_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_npl_person_note ON note_people_links(person_id, note_id);

CREATE TABLE IF NOT EXISTS flags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  flagged_user_id TEXT NOT NULL REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  person_id UUID REFERENCES people(id) ON DELETE CASCADE,
  flagged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  position INT NOT NULL DEFAULT 0,
  CHECK ((note_id IS NOT NULL)::int + (project_id IS NOT NULL)::int + (person_id IS NOT NULL)::int = 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_flags_unique_note ON flags(flagged_user_id, note_id) WHERE note_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_flags_unique_project ON flags(flagged_user_id, project_id) WHERE project_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notesnoop_flags_unique_person ON flags(flagged_user_id, person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notesnoop_flags_workspace ON flags(workspace_id);
CREATE INDEX IF NOT EXISTS idx_notesnoop_flags_user_recency ON flags(flagged_user_id, flagged_at DESC);

CREATE TABLE IF NOT EXISTS review_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  target_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('person','project','note','processing')),
  entity_id UUID NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN ('ai_suggestion','collaborator_suggestion','processing_pending')),
  payload JSONB,
  state TEXT NOT NULL CHECK (state IN ('open','accepted','rejected','archived')) DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_review_queue_user_state ON review_queue(target_user_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notesnoop_review_queue_workspace_state ON review_queue(workspace_id, state, created_at DESC);

CREATE TABLE IF NOT EXISTS email_blocks (
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  sender_pattern TEXT NOT NULL,
  blocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (clerk_user_id, sender_pattern)
);

CREATE TABLE IF NOT EXISTS inbound_email_addresses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  address TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_inbound_email_addresses_user ON inbound_email_addresses(clerk_user_id);

CREATE TABLE IF NOT EXISTS ai_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('extract','reprocess','briefing','merge','prune')),
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  target_user_id TEXT REFERENCES user_profiles(clerk_user_id),
  payload JSONB,
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed')) DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  idempotency_key TEXT UNIQUE,
  consumed_at TIMESTAMPTZ,
  priority SMALLINT NOT NULL DEFAULT 5,
  visibility_timeout_minutes INT NOT NULL DEFAULT 10,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_ai_jobs_queue ON ai_jobs(state, priority DESC, created_at) WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS idx_notesnoop_ai_jobs_workspace_kind ON ai_jobs(workspace_id, kind, created_at DESC);

CREATE TABLE IF NOT EXISTS recently_accessed (
  clerk_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (clerk_user_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_recently_accessed_user ON recently_accessed(clerk_user_id, accessed_at DESC);

CREATE TABLE IF NOT EXISTS calibration_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_job_id UUID REFERENCES ai_jobs(id) ON DELETE SET NULL,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  confidence DOUBLE PRECISION NOT NULL,
  user_decision TEXT NOT NULL CHECK (user_decision IN ('accepted','rejected','dropped')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_calibration_workspace ON calibration_events(workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS person_merge_undos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_person_id UUID NOT NULL,
  target_person_id UUID NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  source_person JSONB NOT NULL,
  source_links JSONB NOT NULL,
  created_by TEXT NOT NULL REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '30 seconds',
  undone_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_person_merge_undos_user
  ON person_merge_undos(created_by, created_at DESC);

CREATE TABLE IF NOT EXISTS rate_limit_buckets (
  key TEXT PRIMARY KEY,
  tokens DOUBLE PRECISION NOT NULL,
  last_refill TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS note_viewers (
  note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
  viewer_user_id TEXT REFERENCES user_profiles(clerk_user_id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (note_id, viewer_user_id)
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_note_viewers_recent ON note_viewers(workspace_id, last_active DESC);

CREATE TABLE IF NOT EXISTS inbound_email_log (
  message_id TEXT PRIMARY KEY,
  rfc_message_id TEXT,
  recipient_address TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('saved','blocked_sender','no_recipient_match','error'))
);
CREATE INDEX IF NOT EXISTS idx_notesnoop_inbound_email_log_received ON inbound_email_log(received_at DESC);

CREATE OR REPLACE FUNCTION current_user_id() RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('notesnoop.current_user_id', true), '')
$$;

CREATE OR REPLACE FUNCTION provider_webhook_enabled() RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(current_setting('notesnoop.provider_webhook', true), '') = 'true'
$$;

CREATE OR REPLACE FUNCTION is_workspace_member(target_workspace_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = target_workspace_id
      AND wm.clerk_user_id = current_user_id()
  )
$$;

CREATE OR REPLACE FUNCTION is_workspace_admin(target_workspace_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = target_workspace_id
      AND wm.clerk_user_id = current_user_id()
      AND wm.role = 'admin'
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
          AND is_workspace_admin(p.workspace_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_note(target_note_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM notes n
    WHERE n.id = target_note_id
      AND is_workspace_member(n.workspace_id)
      AND (
        n.created_by = current_user_id()
        OR (n.is_personal = FALSE AND is_workspace_admin(n.workspace_id))
        OR EXISTS (
          SELECT 1
          FROM note_projects np
          WHERE np.note_id = n.id
            AND can_access_project(np.project_id)
        )
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_person(target_person_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM people p
    WHERE p.id = target_person_id
      AND is_workspace_member(p.workspace_id)
  )
$$;

CREATE OR REPLACE FUNCTION can_access_review_item(target_review_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM review_queue rq
    WHERE rq.id = target_review_id
      AND is_workspace_member(rq.workspace_id)
      AND (
        rq.target_user_id = current_user_id()
        OR is_workspace_admin(rq.workspace_id)
      )
  )
$$;

CREATE OR REPLACE FUNCTION can_access_flag(target_flag_id UUID) RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM flags f
    WHERE f.id = target_flag_id
      AND f.flagged_user_id = current_user_id()
      AND is_workspace_member(f.workspace_id)
  )
$$;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO notesnoop_app, notesnoop_worker;

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE people ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_people_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_email_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE recently_accessed ENABLE ROW LEVEL SECURITY;
ALTER TABLE calibration_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE person_merge_undos ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_buckets ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_viewers ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_email_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_profiles_self_access ON user_profiles;
CREATE POLICY user_profiles_self_access ON user_profiles
  USING (clerk_user_id = current_user_id())
  WITH CHECK (clerk_user_id = current_user_id());

DROP POLICY IF EXISTS workspaces_member_access ON workspaces;
CREATE POLICY workspaces_member_access ON workspaces
  USING (is_workspace_member(id))
  WITH CHECK (is_workspace_member(id));

DROP POLICY IF EXISTS workspaces_self_bootstrap_insert ON workspaces;
CREATE POLICY workspaces_self_bootstrap_insert ON workspaces
  FOR INSERT
  WITH CHECK (current_user_id() IS NOT NULL);

DROP POLICY IF EXISTS workspace_members_self_or_admin ON workspace_members;
CREATE POLICY workspace_members_self_or_admin ON workspace_members
  USING (clerk_user_id = current_user_id() OR is_workspace_admin(workspace_id))
  WITH CHECK (clerk_user_id = current_user_id() OR is_workspace_admin(workspace_id));

DROP POLICY IF EXISTS workspace_members_self_bootstrap_insert ON workspace_members;
CREATE POLICY workspace_members_self_bootstrap_insert ON workspace_members
  FOR INSERT
  WITH CHECK (clerk_user_id = current_user_id());

DROP POLICY IF EXISTS projects_resource_access ON projects;
CREATE POLICY projects_resource_access ON projects
  USING (can_access_project(id))
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS project_members_project_access ON project_members;
CREATE POLICY project_members_project_access ON project_members
  USING (can_access_project(project_id))
  WITH CHECK (can_access_project(project_id));

DROP POLICY IF EXISTS notes_project_access ON notes;
CREATE POLICY notes_project_access ON notes
  USING (can_access_note(id))
  WITH CHECK (created_by = current_user_id() AND is_workspace_member(workspace_id));

DROP POLICY IF EXISTS note_versions_note_access ON note_versions;
CREATE POLICY note_versions_note_access ON note_versions
  USING (can_access_note(note_id))
  WITH CHECK (can_access_note(note_id));

DROP POLICY IF EXISTS note_projects_note_access ON note_projects;
CREATE POLICY note_projects_note_access ON note_projects
  USING (can_access_note(note_id) OR can_access_project(project_id))
  WITH CHECK (can_access_note(note_id) AND can_access_project(project_id));

DROP POLICY IF EXISTS people_workspace_access ON people;
CREATE POLICY people_workspace_access ON people
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS note_people_links_resource_access ON note_people_links;
CREATE POLICY note_people_links_resource_access ON note_people_links
  USING (can_access_note(note_id) AND can_access_person(person_id))
  WITH CHECK (can_access_note(note_id) AND can_access_person(person_id));

DROP POLICY IF EXISTS flags_owner_access ON flags;
CREATE POLICY flags_owner_access ON flags
  USING (can_access_flag(id))
  WITH CHECK (
    flagged_user_id = current_user_id()
    AND is_workspace_member(workspace_id)
    AND (note_id IS NULL OR can_access_note(note_id))
    AND (project_id IS NULL OR can_access_project(project_id))
    AND (person_id IS NULL OR can_access_person(person_id))
  );

DROP POLICY IF EXISTS review_queue_target_or_admin ON review_queue;
CREATE POLICY review_queue_target_or_admin ON review_queue
  USING (can_access_review_item(id))
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS email_blocks_owner_access ON email_blocks;
CREATE POLICY email_blocks_owner_access ON email_blocks
  USING (clerk_user_id = current_user_id())
  WITH CHECK (clerk_user_id = current_user_id());

DROP POLICY IF EXISTS inbound_email_addresses_owner_or_provider ON inbound_email_addresses;
CREATE POLICY inbound_email_addresses_owner_or_provider ON inbound_email_addresses
  USING (clerk_user_id = current_user_id() OR provider_webhook_enabled())
  WITH CHECK (clerk_user_id = current_user_id() OR provider_webhook_enabled());

DROP POLICY IF EXISTS ai_jobs_workspace_access ON ai_jobs;
CREATE POLICY ai_jobs_workspace_access ON ai_jobs
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS recently_accessed_owner_access ON recently_accessed;
CREATE POLICY recently_accessed_owner_access ON recently_accessed
  USING (clerk_user_id = current_user_id() AND can_access_note(note_id))
  WITH CHECK (clerk_user_id = current_user_id() AND can_access_note(note_id));

DROP POLICY IF EXISTS calibration_events_workspace_access ON calibration_events;
CREATE POLICY calibration_events_workspace_access ON calibration_events
  USING (is_workspace_member(workspace_id))
  WITH CHECK (is_workspace_member(workspace_id));

DROP POLICY IF EXISTS person_merge_undos_creator_or_admin ON person_merge_undos;
CREATE POLICY person_merge_undos_creator_or_admin ON person_merge_undos
  USING (created_by = current_user_id() OR is_workspace_admin(workspace_id))
  WITH CHECK (created_by = current_user_id() AND is_workspace_member(workspace_id));

DROP POLICY IF EXISTS rate_limit_buckets_backend_only ON rate_limit_buckets;
CREATE POLICY rate_limit_buckets_backend_only ON rate_limit_buckets
  USING (key LIKE 'user:' || current_user_id() || ':%' OR key LIKE 'workspace:%')
  WITH CHECK (key LIKE 'user:' || current_user_id() || ':%' OR key LIKE 'workspace:%');

DROP POLICY IF EXISTS note_viewers_workspace_access ON note_viewers;
CREATE POLICY note_viewers_workspace_access ON note_viewers
  USING (is_workspace_member(workspace_id) AND can_access_note(note_id))
  WITH CHECK (viewer_user_id = current_user_id() AND is_workspace_member(workspace_id) AND can_access_note(note_id));

DROP POLICY IF EXISTS inbound_email_log_provider_or_note_access ON inbound_email_log;
CREATE POLICY inbound_email_log_provider_or_note_access ON inbound_email_log
  USING (provider_webhook_enabled() OR (note_id IS NOT NULL AND can_access_note(note_id)))
  WITH CHECK (provider_webhook_enabled() OR (note_id IS NOT NULL AND can_access_note(note_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO notesnoop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO notesnoop_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO notesnoop_app, notesnoop_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO notesnoop_app, notesnoop_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO notesnoop_app, notesnoop_worker;

COMMENT ON SCHEMA public IS 'NoteSnoop v1 product schema inside its dedicated Postgres instance.';
