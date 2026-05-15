-- @migration: no-tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=300s

-- Distinguish direct browser/API activity from internal Next.js server fetches
-- in activity_log. These nullable columns keep existing rows untouched.
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS request_origin TEXT;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS public_path TEXT;
ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS bot_family TEXT;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_activity_log_origin_date
    ON activity_log(request_origin, created_at DESC)
    WHERE request_origin IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_activity_log_bot_date
    ON activity_log(bot_family, created_at DESC)
    WHERE bot_family IS NOT NULL;

-- Passive public traffic audit populated by scripts/ingest_public_request_audit.py.
-- Raw IP addresses and raw user agents are intentionally not stored.
CREATE TABLE IF NOT EXISTS public_request_audit (
    id                  BIGSERIAL PRIMARY KEY,
    event_hash          TEXT NOT NULL UNIQUE,
    source              TEXT NOT NULL DEFAULT 'nginx',
    client_hash         TEXT NOT NULL,
    client_network      TEXT,
    client_type         TEXT NOT NULL DEFAULT 'unknown',
    method              TEXT NOT NULL,
    path                TEXT NOT NULL,
    route_kind          TEXT NOT NULL,
    cbe                 TEXT,
    status_code         INTEGER,
    response_bytes      INTEGER,
    referrer_path       TEXT,
    ua_family           TEXT,
    device_type         TEXT,
    bot_family          TEXT,
    is_verified_bot     BOOLEAN NOT NULL DEFAULT FALSE,
    is_ai_crawler       BOOLEAN NOT NULL DEFAULT FALSE,
    is_rsc_prefetch     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_public_request_audit_date
    ON public_request_audit(created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_public_request_audit_client_date
    ON public_request_audit(client_hash, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_public_request_audit_route_date
    ON public_request_audit(route_kind, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_public_request_audit_bot_date
    ON public_request_audit(bot_family, created_at DESC)
    WHERE bot_family IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_public_request_audit_cbe_date
    ON public_request_audit(cbe, created_at DESC)
    WHERE cbe IS NOT NULL;
