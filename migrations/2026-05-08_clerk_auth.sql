-- Three tables for Phase 3 of the Clerk migration.
--
-- clerk_user_map: maps Clerk session sub → DataSnoop UUID. Populated
-- during Phase 4/5.5 user import + by the user.created webhook +
-- self-heal in get_current_user(). Read on every Clerk-signed request.
CREATE TABLE IF NOT EXISTS clerk_user_map (
    clerk_sub TEXT PRIMARY KEY,
    datasnoop_user_id UUID NOT NULL,
    clerk_synced_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS clerk_user_map_dsuid_idx
    ON clerk_user_map(datasnoop_user_id);

-- webhook_log: idempotency. Each (svix_id, event_type) processed at most once.
CREATE TABLE IF NOT EXISTS webhook_log (
    svix_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (svix_id, event_type)
);

-- clerk_pending_sync: queue for failed Clerk PATCH calls when self-heal
-- can't update external_id remotely. A background worker retries.
CREATE TABLE IF NOT EXISTS clerk_pending_sync (
    clerk_sub TEXT PRIMARY KEY,
    datasnoop_user_id UUID NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ALLOW-RUNTIME-DDL: Phase 3 schema for Clerk auth migration; not runtime DDL on hot path.
