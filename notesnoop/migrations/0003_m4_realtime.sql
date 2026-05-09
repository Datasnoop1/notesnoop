-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE INDEX IF NOT EXISTS idx_notesnoop_npl_person_state_note
  ON note_people_links(person_id, state, note_id);

CREATE INDEX IF NOT EXISTS idx_notesnoop_note_viewers_note
  ON note_viewers(note_id, last_active DESC);

CREATE OR REPLACE FUNCTION notify_workspace_event() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  target_workspace_id UUID;
  event_kind TEXT;
BEGIN
  target_workspace_id := COALESCE(NEW.workspace_id, OLD.workspace_id);
  event_kind := CASE TG_TABLE_NAME
    WHEN 'review_queue' THEN 'review_queue'
    WHEN 'note_viewers' THEN 'collaborator_activity'
    ELSE TG_TABLE_NAME
  END;

  IF target_workspace_id IS NOT NULL THEN
    PERFORM pg_notify(
      'notesnoop_events',
      json_build_object(
        'workspace_id', target_workspace_id::text,
        'event', event_kind,
        'table', TG_TABLE_NAME,
        'operation', TG_OP,
        'sent_at', now()
      )::text
    );
  END IF;

  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_review_queue_notify ON review_queue;
CREATE TRIGGER trg_review_queue_notify
  AFTER INSERT OR UPDATE OR DELETE ON review_queue
  FOR EACH ROW EXECUTE FUNCTION notify_workspace_event();

DROP TRIGGER IF EXISTS trg_note_viewers_notify ON note_viewers;
CREATE TRIGGER trg_note_viewers_notify
  AFTER INSERT OR UPDATE OR DELETE ON note_viewers
  FOR EACH ROW EXECUTE FUNCTION notify_workspace_event();

GRANT EXECUTE ON FUNCTION notify_workspace_event() TO notesnoop_app, notesnoop_worker;

COMMENT ON FUNCTION notify_workspace_event() IS 'Publishes workspace-scoped NoteSnoop SSE invalidation events through Postgres LISTEN/NOTIFY.';
