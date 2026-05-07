# Auth migration: Supabase to Clerk

Status: Draft recommendation outline, 2026-05-06.
Decision: Use Clerk as the single managed auth provider for DataSnoop.
Non-goal: Do not deploy, merge, or decommission Supabase until the operator approves.

## 1. Why Clerk

- Clerk was the unanimous 6/6 council pick because it gives managed auth without adding another critical service to the 8 GB Hetzner box.
- It covers the security basics DataSnoop needs: MFA, compromised-password checks, bot/attack protections, session controls, and user-management tooling.
- Its current public free tier is 50k monthly retained users plus 100 monthly retained organizations, with a one-month grace period after overage.
- It has first-class Next.js SDKs, which lowers migration risk in the current Next.js 16 frontend.
- FastAPI can keep sub-200 ms auth checks by verifying Clerk session JWTs locally against cached JWKS rather than calling Clerk on every API request.

## 2. Identity contract

Keep the backend auth interface stable:

- `get_current_user()` still returns `{id, email, role, payload}`.
- `optional_user()` still returns the same shape or `None`.
- Existing routers should not need broad rewrites.

Preserve DataSnoop's existing per-user data:

- Existing Supabase UUIDs remain the canonical DataSnoop user id.
- Imported Clerk users store the old Supabase UUID in `external_id`.
- Clerk session tokens include a custom `datasnoop_user_id` claim.
- Backend returns `id = datasnoop_user_id`.
- For an existing email in `user_roles`, a missing `datasnoop_user_id` is an auth failure, not a silent fallback to Clerk `sub`.
- New Clerk users get a DataSnoop UUID through a `user.created` webhook before they can write app-owned records.
- This protects tables such as `favourite`, `favourite_project`, `people_favourite`, `customer_supplier_list`, and Stripe metadata from breaking.

Keep roles local:

- `user_roles.email` remains the source of truth for `admin`, `pro`, `user`, and `blocked`.
- Clerk metadata may mirror role for dashboard visibility, but FastAPI should still check Postgres.
- Disable self-service primary email changes for the first cutover. Re-enable only after an explicit role-transfer flow updates `user_roles` safely.

## 3. Phase 1 - Clerk project setup

Goal: Create Clerk development, staging, and production instances without touching live traffic.

Steps:

1. Create Clerk application for DataSnoop.
2. Enable email/password and Google OAuth if the operator still wants Google login.
3. Enable MFA options, preferring TOTP/authenticator app plus backup codes over SMS-only.
4. Enable compromised-password protection, bot/attack protections, and user enumeration protection.
5. Configure allowed origins and redirect URLs:
   - `https://datasnoop.be`
   - `https://www.datasnoop.be`
   - `https://staging.datasnoop.be`
   - local dev URLs only for development keys
6. Create custom session token claim:
   - `datasnoop_user_id`: `{{user.external_id}}`
   - include email claim if not already present in the default token
7. Configure a Clerk `user.created` webhook that assigns a UUID to new users and stores it as `external_id`.
8. Record required environment variables in `.env.example`, `.env.staging`, and `.env.production` templates only. Do not commit real keys.

Acceptance:

- Clerk dashboard settings are documented.
- No DataSnoop code path uses Clerk in production yet.

## 4. Phase 2 - Frontend SDK swap

Goal: Replace Supabase browser auth with Clerk UI/session primitives.

Steps:

1. Add `@clerk/nextjs` to the frontend.
2. Wrap the App Router layout in `ClerkProvider`.
3. Replace `frontend/src/lib/supabase.ts` with a small Clerk auth helper.
4. Update login, reset-password, account, nav, admin page, and staging gate flows.
5. Update `frontend/src/lib/api.ts` so API calls attach the Clerk session token:
   - use `getToken()` from Clerk
   - send `Authorization: Bearer <token>` as today
6. Keep existing anonymous browsing behavior unchanged.
7. Remove Supabase OAuth callback pages only after their Clerk equivalents work on staging.

Acceptance:

- Anonymous search/profile pages still work.
- Signed-in pages can acquire a Clerk token and call `/api/me/is-admin`.
- Sign out clears the UI state without page refresh confusion.

## 5. Phase 3 - Backend token verification

Goal: Swap `backend/auth.py` from Supabase JWT verification to Clerk JWT verification.

Steps:

1. Add Clerk issuer, audience/authorized-party, and JWKS URL env vars.
2. Fetch and cache Clerk JWKS with a bounded TTL, matching the current Supabase pattern.
3. Verify:
   - expected algorithm
   - signature
   - `iss`
   - `exp` and `nbf`
   - authorized party/origin where present
4. Extract:
   - `email`
   - `sub` as `clerk_user_id`
   - `datasnoop_user_id` as canonical `id`
5. Keep `get_current_user` and `optional_user` signatures unchanged.
6. Keep `ensure_jwks_bootstrapped()` fail-closed at backend startup.
7. Fail closed when an existing email is known in `user_roles` but `datasnoop_user_id` is missing.
8. Add focused tests for valid token, expired token, wrong issuer, missing email, missing external id, and new-user pending setup.

Acceptance:

- Existing protected routers work against a mocked Clerk JWT with `datasnoop_user_id`.
- A token without trusted issuer/signature is rejected.
- A migrated user's token without `datasnoop_user_id` is rejected instead of orphaning their data.

## 6. Phase 4 - User migration

Goal: Move users to Clerk while preserving DataSnoop ids and Stripe/account continuity.

Preferred path if Supabase can be restored/exported:

1. Export Supabase users once, encrypted, following the existing secret-handling hygiene from the Kratos plan.
2. Build an import CSV/JSON for Clerk with:
   - email
   - old Supabase UUID as `external_id`
   - email verification status when available
3. Import users with Clerk's migration tooling or Backend API.
4. Default to forced password-reset invitations for all imported users.
5. Only preserve passwords if Clerk support/docs confirm the exact Supabase digest format before implementation.
6. Keep `user_roles` untouched, because roles are keyed by email.

Fallback if Supabase user export is unrecoverable:

1. Do not auto-cutover.
2. Build an email-to-UUID map from local tables only where it is unambiguous.
3. Create Clerk accounts with `external_id` set for those unambiguous users.
4. Hold ambiguous users for explicit operator approval before production cutover.
5. Tell the operator this path may not preserve every favourite/project.

Acceptance:

- Every staging-imported test user has a non-empty `datasnoop_user_id` claim.
- At least one imported admin can sign in on staging and keeps the old DataSnoop user id.
- Existing favourites/projects remain visible for that user.
- Stripe checkout/status still maps by email.

## 7. Phase 5 - Staging cutover

Goal: Prove the full app uses Clerk on staging only.

Steps:

1. Add Clerk env vars to staging.
2. Deploy to staging using `scripts/deploy_staging.sh`.
3. Smoke-test:
   - anonymous browsing
   - sign in
   - sign out
   - `/api/me/is-admin`
   - favourites/projects
   - Stripe checkout creation
   - admin route denial for non-admin
   - admin route access for admin
4. Fix critical auth, lockout, role, or data-continuity issues.
5. Stop after staging evidence and ask the operator for production approval.

Acceptance:

- Staging behaves normally with Clerk.
- No production traffic has changed.

## 8. Phase 6 - Production cutover and cleanup

Goal: Switch production after explicit operator approval.

Steps:

1. Announce a short login maintenance window.
2. Tag or record the exact pre-Clerk git commit and back up `.env.production`.
3. Verify whether Supabase auth is still restorable; do not describe rollback as guaranteed if Supabase remains paused.
4. Import users into the production Clerk instance with the same `external_id` mapping proven on staging.
5. Verify one production admin token contains the preserved `datasnoop_user_id` before ending maintenance.
6. Add production Clerk env vars.
7. Deploy production only with operator approval.
8. Verify:
   - anonymous routes
   - admin login
   - paid user login
   - favourites/projects
   - Stripe checkout and webhook role update
9. Keep Supabase auth env values available until the operator confirms the cutover is stable.
10. Remove Supabase packages, env vars, callback pages, and docs references in a later cleanup PR.

Rollback:

- If production login is broken, redeploy the exact pre-Clerk commit and matching env backup together.
- Clear Clerk browser session state via a logout/clear-session route or operator notice so users do not keep sending stale Clerk tokens to the rolled-back app.
- Do not delete Supabase configuration until Clerk has survived a real production soak.
