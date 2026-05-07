-- Adds an `email` column to clerk_user_map.
--
-- Why: Clerk's default session JWT only carries
--   {azp, exp, iat, iss, nbf, sid, sub, sts, v}
-- — no email claim. The /api/me/is-admin endpoint (and several others)
-- looks up user_roles by email, so without an email we'd always return
-- is_admin=false even for legitimate admins.
--
-- Backend strategy (see backend/auth_clerk.py):
--   1. On every authenticated Clerk request, look up clerk_user_map
--      by clerk_sub and read the cached email.
--   2. If email is NULL (first request after this column lands, or a
--      new user via self-heal), call Clerk's /v1/users/{sub} once,
--      then UPSERT the email back into clerk_user_map. Future requests
--      hit the column cache and never touch Clerk's API.
--
-- The column is nullable on purpose — populated lazily so we don't
-- block the migration on a Clerk API enumeration of all 8 users.

ALTER TABLE clerk_user_map ADD COLUMN IF NOT EXISTS email TEXT;

CREATE INDEX IF NOT EXISTS clerk_user_map_email_idx
    ON clerk_user_map(email);

-- ALLOW-RUNTIME-DDL: Phase 5 schema extension for Clerk-driven
-- email→user_roles resolution; not runtime DDL on hot path.
