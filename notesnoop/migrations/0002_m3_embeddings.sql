-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embeddings (
  note_id UUID PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  embedding vector(1024) NOT NULL,
  model_version TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('ollama','lexical_hash')),
  embedding_dimension INT NOT NULL DEFAULT 1024 CHECK (embedding_dimension = 1024),
  embedding_text_sha256 TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notesnoop_embeddings_workspace
  ON embeddings(workspace_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_notesnoop_embeddings_model
  ON embeddings(model_version);
CREATE INDEX IF NOT EXISTS idx_notesnoop_embeddings_vector
  ON embeddings USING hnsw (embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION enforce_embedding_workspace() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  actual_workspace_id UUID;
BEGIN
  SELECT workspace_id INTO actual_workspace_id
  FROM notes
  WHERE id = NEW.note_id;

  IF actual_workspace_id IS NULL THEN
    RAISE EXCEPTION 'Embedding note % does not exist', NEW.note_id
      USING ERRCODE = '23503';
  END IF;

  IF NEW.workspace_id <> actual_workspace_id THEN
    RAISE EXCEPTION 'Embedding workspace % does not match note workspace %', NEW.workspace_id, actual_workspace_id
      USING ERRCODE = '23514';
  END IF;

  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_embeddings_workspace ON embeddings;
CREATE TRIGGER trg_embeddings_workspace
  BEFORE INSERT OR UPDATE ON embeddings
  FOR EACH ROW EXECUTE FUNCTION enforce_embedding_workspace();

ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS embeddings_note_access ON embeddings;
CREATE POLICY embeddings_note_access ON embeddings
  USING (is_workspace_member(workspace_id) AND can_access_note(note_id))
  WITH CHECK (is_workspace_member(workspace_id) AND can_access_note(note_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON embeddings TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION enforce_embedding_workspace() TO notesnoop_app, notesnoop_worker;

COMMENT ON TABLE embeddings IS 'Per-note semantic-search vectors. M3 locks NoteSnoop v1 embedding dimension at 1024.';
COMMENT ON COLUMN embeddings.provider IS 'ollama for Ollama Cloud embeddings; lexical_hash only for deterministic local fallback when the Cloud embedding endpoint is unavailable.';
