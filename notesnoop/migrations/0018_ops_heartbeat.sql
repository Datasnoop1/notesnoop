-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE TABLE IF NOT EXISTS ops_heartbeats (
  key TEXT PRIMARY KEY,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE OR REPLACE FUNCTION ops_ai_job_health() RETURNS JSONB
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT jsonb_build_object(
    'queued', count(*) FILTER (WHERE state = 'queued'),
    'running', count(*) FILTER (WHERE state = 'running'),
    'stale_running', count(*) FILTER (
      WHERE state = 'running'
        AND consumed_at IS NOT NULL
        AND consumed_at < now() - (visibility_timeout_minutes * interval '1 minute')
    ),
    'failed_24h', count(*) FILTER (WHERE state = 'failed' AND completed_at > now() - interval '24 hours'),
    'last_done_at', max(completed_at) FILTER (WHERE state = 'done')
  )
  FROM ai_jobs
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ops_heartbeats TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION ops_ai_job_health() TO notesnoop_app, notesnoop_worker;
