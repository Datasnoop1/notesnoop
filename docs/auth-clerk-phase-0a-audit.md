# Phase 0a — Pre-flight read-only audit

Date: 2026-05-07
Per `docs/auth-migration-clerk-final.md` Phase 0a.

## Headline

DataSnoop's user base is small (10 total users, 2 admin / 8 user) — well within Clerk's free-tier capacity. Migration is technically straightforward; the per-user mechanics matter more than the bulk-import scaling.

## DataSnoop-Postgres-side audit (completed)

### User count and roles

```
user_roles total : 10
  role:admin     : 2
  role:user      : 8
  role:pro       : 0
  role:anon      : 0 (anonymous traffic isn't tracked here)
```

Source: `SELECT count(*), role FROM user_roles GROUP BY role`. No PII pulled (counts only).

### Identity-keying audit per app-data table

Mixed model — some tables key user data by email, others by UUID:

| Table | Key column | Migration impact |
|---|---|---|
| `user_roles` | `email` | Untouched; backend lookup by email continues to work post-cutover |
| `ai_insights_feedback` | `user_email` | Untouched; email-stable across migration |
| `company_view_history` | `user_email` | Same |
| `feedback` | `user_email` | Same |
| `poll_response` | `user_email` | Same |
| `customer_supplier_list` | `user_id` (UUID) | Preserved via Clerk `external_id` = old Supabase UUID |
| `favourite` | `user_id` (UUID) | Same |
| `favourite_project` | `user_id` (UUID) | Same |
| `people_favourite` | `user_id` (UUID) | Same |

**Implication for the migration plan**: as long as both email-stability and UUID-stability are preserved, all app-data joins continue to work. v18's strategy (preserve email; preserve UUID via `external_id`) is valid.

### Stripe customer storage

```
columns matching '%stripe%' or '%customer_id%' in public schema: ZERO
```

DataSnoop does NOT store any local mapping to Stripe customer IDs. Stripe customers are referenced by email only, via the Stripe webhook → `user_roles.role` update flow. Email preservation through the Clerk migration → Stripe customer mapping continues to work without any schema change. v18 plan correct.

### `_bt_vf_stage_d_backup_*` notice

Four bitemporal Stage D backup tables exist in the public schema:
- `_bt_vf_stage_d_backup_administrator`
- `_bt_vf_stage_d_backup_affiliation`
- `_bt_vf_stage_d_backup_participating_interest`
- `_bt_vf_stage_d_backup_shareholder`

Per memory `project_bitemporal_stage_d_applied.md`, these are temporary and scheduled to be dropped (parallel to Stage A backups dropping on/after 2026-05-11). No impact on auth migration. Classified as `public_reference` in `scripts/staging_scrub.sql` (CI fix in same PR as this audit).

## Supabase-side audit (deferred to Phase 1b)

The following checks need direct access to Supabase's `auth` schema, which requires the Supabase Postgres connection string with project password. The operator provides this once via Option A (Codex prompt-and-paste) at Phase 1b's start. The same data inspection step inside Phase 1b will produce these audit numbers, so they are NOT separately requested from the operator now.

Items deferred to Phase 1b:
- Total users in `auth.users` (Supabase side)
- Split: email/password only vs Google OAuth only vs both vs neither
- Active users in last 30 days (Clerk MAU sizing — confirm < free-tier limit)
- Sample of `encrypted_password` format (length, prefix) — bcrypt MCF verification
- Bcrypt cost factor distribution (4-31 range; cost ≥ 12 triggers operator warning)
- Cross-check Supabase `auth.users.id` UUIDs vs DataSnoop `user_id` columns (orphans either way)
- Count of users with MFA enrolled
- Verify `encrypted_password` is `text`/`varchar` type (not `bytea` requiring `encode()` conversion)

## Clerk free-tier headroom

Public Clerk pricing (verified via Clerk's pricing page; if changed by the time the migration runs, Phase 1a's plan-tier verification gate catches it):
- Free tier: 10,000 monthly active users (MAU)
- 100 monthly active organizations
- One-month grace period after overage

DataSnoop's current scale (10 users) is **0.1%** of the free-tier MAU limit. Even at 100x growth, we'd remain on the free tier. No pricing risk for this migration.

## Supabase project status

Verified live: `https://fpsyraglybfazambxuqb.supabase.co/auth/v1/health` returns proper JSON 401 (auth required for actual data, but project IS responding — not paused). Memory `reference_supabase_projects.md` confirms 02:30 UTC keepalive cron prevents auto-pause; verified working.

## Auth schema permission verification

The Supabase `auth` schema is owned by `supabase_auth_admin`. Direct `SELECT` from `auth.users` requires the project's `postgres` superuser connection (default Supabase DB connection string). No additional `GRANT` step expected to be required. **Verified empirically in Phase 1b's first DB query.**

## Clerk dashboard config — pre-cutover items the operator must confirm

For Phase 1c. Codex's checklist will include each as a one-liner; the audit just records them so they're not forgotten:

1. Email/password authentication enabled
2. Google OAuth enabled with non-sensitive scopes (`openid`, `profile`, `email` only)
3. MFA enabled (TOTP + backup codes; SMS-only avoided)
4. Compromised-password protection ON
5. Bot/attack protection ON
6. User enumeration protection ON
7. Allowed origins: `https://datasnoop.be`, `https://www.datasnoop.be`, `https://staging.datasnoop.be`, `http://localhost:3000` (dev only)
8. JWT template named `datasnoop` with claim `datasnoop_user_id` mapped from `{{user.external_id}}`
9. `user.created` webhook configured (URL set to staging during Phase 1c, switched to prod via API in Phase 6 pre-flight)
10. Account Linking: "Sign-in with multiple identifiers" + "Allow account linking by email" — both ON
11. Email Verification: "Required for sign-up only" (NOT "Required for sign-in")
12. Webhook test endpoint accessible (verified in Phase 1a plan-tier gate)

## Audit gates: pass conditions for moving to Phase 1

- ✅ User count well below Clerk free tier (10 << 10,000)
- ✅ Stripe storage understood (email-keyed only; no schema change needed)
- ✅ Mixed email/UUID keying confirmed (v18 plan handles both)
- ✅ Supabase project alive and reachable
- ⏳ Bcrypt format and bcrypt cost — DEFERRED to Phase 1b empirical check (operator + DB URL)
- ⏳ MFA-enrolled user count — DEFERRED to Phase 1b
- ⏳ external_id collision audit — DEFERRED to Phase 1b

The deferred items do NOT block Phase 1a (Clerk sign-up) — they block Phase 1c (full dashboard config) and Phase 4 (staging import). Phase 1b's data inspection step is the gate.

## Decision

**Proceed to Phase 1a.** No blockers found. Migration is technically a small operation (10 users) with v18's plan giving comprehensive coverage.
