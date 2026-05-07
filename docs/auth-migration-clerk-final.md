# Clerk migration — minimum-operator-action, invisible-cutover plan v18

## What changed from v17 (round 19 polish)

Round 19: gemma4 score 98% with 3 polish items. v18 implements them:

1. **Disable "Require email verification on sign-in" in Clerk Dashboard for all instances** (gemma4 R19). Even with imported users marked `verified`, Clerk's instance-level setting can override and block users at sign-in with a verify-email prompt. Phase 1c now includes: Clerk Dashboard → User & Authentication → Email, Phone, Username → Email Verification → "Required for sign-up only" (NOT "Required for sign-in"). All three instances (Dev/Staging/Prod).

2. **`clerk_pending_sync` row written WITHIN the atomic transaction** (gemma4 R19). v17 wrote the pending-sync row AFTER the Clerk PATCH failed. If the backend crashed between transaction commit and the PATCH attempt, no pending-sync record existed and the worker wouldn't know to retry. v18 writes the pending-sync row INSIDE the same atomic transaction as `clerk_user_map`; on PATCH success the row is deleted; on PATCH failure it stays for the worker. Crash-safe at every point.

3. **Connection verification script before each migration command** (gemma4 R19). After operator pastes `SUPABASE_DB_URL` + `CLERK_SECRET_KEY`, Codex's first 3-line check confirms:
   - `psql "$SUPABASE_DB_URL" -c "SELECT 1"` → ✅ DB Connection: OK
   - `curl -H "Authorization: Bearer $CLERK_SECRET_KEY" https://api.clerk.com/v1/users?limit=0` → ✅ Clerk Key: OK
   - Trailing whitespace / newline check on both vars
   Migration script does NOT run until all three are green.

## What changed from v16 (round 18 polish)

Round 18: gemma4 score 95% with 3 polish items. v17 implements them:

1. **"Ghost mapping" remediation: pending-sync queue** (gemma4 R18). v16's self-heal called Clerk's PATCH best-effort; if it failed (timeout, 500, rate limit), the DB had a clerk_user_map row but Clerk's external_id was unset. Subsequent user requests still worked (DB lookup hits the cache), but Clerk's view diverged from ours. v17 adds a `clerk_pending_sync` table + a tiny background worker that retries PATCH calls every 60 sec with backoff up to 24 h. The "ghost" is now self-healing on Clerk's side too, not just the DB side.

2. **Bcrypt encoding inspection** (gemma4 R18). v16's Phase 1b assumed `encrypted_password` is a string. Some Supabase / pgcrypto setups store it as `bytea`. v17 Phase 1b's data inspection now also runs `SELECT pg_typeof(encrypted_password) FROM auth.users LIMIT 1;` — if it returns `bytea` instead of `text` or `varchar`, the migration script applies `encode(encrypted_password, 'escape')` to convert. Empirical detection, no assumption.

3. **Cookie flags explicit verification** (gemma4 R18). v16 mentioned `SameSite=None + Secure` if Stripe needs it. v17 makes Phase 5 staging soak include an explicit `curl -I https://staging.datasnoop.be/api/_some_protected_route` step, parsing the `Set-Cookie` header to confirm BOTH `SameSite=None` AND `Secure` AND `HttpOnly` are present. Browsers ignore `SameSite=None` without `Secure`, so this catches the trap.

## What changed from v15 (round 17 polish)

Round 17's gemma4 score: 7/10 with 3 polish items. v16 implements them:

1. **Two-pass import: PATCH retry-with-backoff for Clerk's eventual consistency** (gemma4 R17). v15 did POST then PATCH back-to-back. Clerk's API can take a few hundred ms before a freshly POSTed user is visible to subsequent PATCH calls; the PATCH may 404 if it races. v16 retries the PATCH up to 5× with 500 ms backoff before giving up.

2. **Pre-build window UX warning** (gemma4 R17). After operator types `PROCEED`, `docker compose up -d --build` triggers a Next.js production build that can take 3-8 minutes during which the OLD containers continue serving traffic (zero downtime, but Codex's logs show "building" and the operator may panic if they don't know what's happening). v16 adds a Codex message immediately after `PROCEED` is received: "Build starting. Old containers continue serving live traffic for the next ~5 min while the new image builds. Site is NOT down. You'll see the cutover happen when Codex confirms 'rolled to new images'."

3. **`SameSite=None` requires `Secure` flag — explicit affirmation** (gemma4 R17). Already implicit (prod runs on TLS), but v16 makes it explicit: if Phase 5 staging soak forces a switch to SameSite=None, Codex also sets the Secure flag in the same Clerk config + verifies the staging cookie response includes both attributes via `curl -I` before promoting to prod.

## What changed from v14 (rounds 14-16 polish)

Across rounds 14-16, gemma4:31b consistently said "99% there, READY-TO-SHIP if you fix the top-3" with new top-3 each round. v15 sweeps in the round-16 top-3 + a few smaller items from round 15 / minimax:

1. **Profile completion: two-pass import** (gemma4 R16). Clerk's `POST /v1/users` may not accept `first_name`/`last_name` as top-level fields during `password_digest` flow; it varies by API version. v15 has the migration script do a TWO-PASS import for each user: pass 1 creates the user with email + `password_digest` + `password_hasher` + `external_id` + verification status; pass 2 immediately PATCHes `first_name` + `last_name` (extracted from Supabase `user_metadata.first_name`/`user_metadata.full_name`, or empty strings if absent). The `try/except` around pass 2 means partial success: if Clerk's API truly doesn't allow profile updates immediately after creation, the import still succeeds but the user may see "Complete profile" on first login. We test this empirically in Phase 1b on the operator's own account.

2. **Clerk account-linking explicitly configured** (gemma4 R16). Phase 1c adds a step where the operator sets Clerk's "Account Linking" settings to "Allow users to link accounts via email match" so an imported Google user whose Google email matches their Supabase email is auto-linked, not duplicated. Path: Clerk dashboard → User & Authentication → Account & Linking → enable "Sign-in with multiple identifiers" + "Allow account linking by email".

3. **Bcrypt cost-12+ warning** (gemma4 R16). Phase 1b's bcrypt cost check now adds an operator-facing message if cost ≥12: "Your existing passwords use bcrypt cost N. The first login per user post-cutover will take ~`2^(N-10)` seconds for Clerk to verify (subsequent logins are instant). At cost 12, that's ~4× the cost-10 baseline, typically still under 1 second. No action needed; this is informational." Avoids "wait, why is login slow?" support tickets.

4. **PROCEED keyword + GET-after-PATCH webhook verification + test-event detection** (round 15 inlines, already in v14, retained).

## What changed from v13 (round 13 final nits)

Round 13's gemma4:31b verdict was **READY-TO-SHIP** with three minor refinements. v14 implements them:

1. **Screenshot verification of Supabase-disable is augmented with a post-import sanity check** (gemma4:31b round 13). v13 relied on the operator + Codex visually confirming the dashboard screenshot. v14 adds a belt-and-suspenders verification: after the Phase 5.5 import completes, Codex queries Supabase auth.users for any rows with `created_at > <Phase 5.5 start time>`. If any are found, the disable was incomplete (one toggle was missed) and Codex aborts before Phase 6.

2. **Google OAuth Consent Screen "publishing status" gate added** (gemma4:31b round 13). For external apps, Google may put the Consent Screen in "Pending Verification" status if the app name + logo look "official" or the requested scopes look sensitive. v14 Phase 1c includes an explicit gate: operator confirms the Google Cloud Console shows "Publishing status: In production" (not "Testing" or "Pending Verification") for the OAuth Consent Screen. If Pending, the migration pauses until Google clears it (typically 4-6 weeks for sensitive scopes; near-instant for non-sensitive). DataSnoop's `openid + profile + email` scopes are non-sensitive and should auto-approve.

3. **SameSite=None third-party cookie testing expanded** (gemma4:31b round 13). v13 tested Stripe Checkout on Chrome + Safari + Firefox. v14 adds Brave (which blocks third-party cookies aggressively by default) and Chrome Incognito (which has stricter cookie policy than regular Chrome). If `SameSite=None` is needed and any of these browsers fails, the operator decides whether to require all users to disable third-party-cookie-blocking (workable for power users, terrible for general public) or to redesign the Stripe Checkout return URL to avoid the cross-site cookie dependency.

## What changed from v12 (round 12 refinements)

Round 12's 10-model jury (qwen STILL hallucinating bcrypt-base64 — 12 rounds, disregarded) surfaced 3 real refinements:

1. **No new operator credential required for Supabase verification** (gemma4:31b + deepseek-v4-flash). v12 implied Codex would need a Supabase Management API token to verify the operator had disabled all sign-up paths. This adds mental load. v13: Codex's verification falls back to a screenshot-based check — operator screenshots the Supabase Auth Providers page after disabling, pastes the screenshot into chat, Codex visually confirms all toggles are OFF before approving Phase 5.5 to proceed. No new API tokens.

2. **Google OAuth Consent Screen "verification status" check** (gemma4:31b). Google requires apps to either (a) be verified by Google, or (b) use only "non-sensitive" scopes (basic profile + email). DataSnoop's use case fits (b) — but if the operator accidentally requests sensitive scopes during Clerk's Google OAuth setup, users will see a "Google hasn't verified this app" warning. Phase 1c now includes an explicit step: confirm Clerk's Google OAuth scope list contains ONLY `openid`, `profile`, `email` (no Drive, Calendar, etc.). Codex provides the exact Clerk dashboard path to verify.

3. **Bcrypt sample size widened** (gemma4:31b). v12's Phase 1b data inspection used `LIMIT 1` which could pick a non-representative row (e.g., a test account, a row with NULL password, an old row from a different bcrypt cost). v13 samples the operator's own row + 5 random rows + 1 oldest row + 1 newest row, returning length distribution and prefix distribution. Codex confirms the distribution is uniform (all-MCF, same prefix family) before proceeding.

## What changed from v11 (round 11 refinements)

Round 11's 10-model jury (qwen continues bcrypt-base64 hallucination — 11 rounds, disregarded) surfaced 4 real refinements:

1. **Phase 1b adds an empirical "Data Inspection" sub-step** (gemma4:31b). Before the migration script is even written, operator runs `SELECT encrypted_password FROM auth.users LIMIT 1;` from the Hetzner web console and pastes the result back to Codex. Codex confirms it's a recognisable MCF string (`$2a$|$2b$|$2y$<cost>$<53-char-hex>`) before building the import script. Removes the "abort with cryptic error" failure mode where an unexpected Postgres-internal storage format slips past us.

2. **Phase 1c explicitly enumerates the exact Clerk-provided Redirect URIs to paste into Google Cloud Console** (gemma4:31b). Otherwise OAuth sign-in throws `redirect_uri_mismatch` 400 on first user. Codex's checklist now includes the 3 exact URIs (one per environment) and the precise Google Cloud Console field they go into.

3. **Phase 5.5 rollback sub-runbook added** (minimax-m2.7). If Phase 6 cutover fails within 30 min of completing, a fast "wipe Clerk Prod users created in Phase 5.5" reverse path is documented. Codex queries Clerk for `external_id IS NOT NULL` users (the imports), bulk-deletes them via Clerk Backend API, then operator re-enables Supabase sign-ups — leaving the system in a clean Supabase-only state. Past the 30-min window, rollback is no longer "safe-clean" and the runbook says so explicitly.

4. **Phase 1a verifies Clerk plan tier supports the test-webhook endpoint** (minimax-m2.7). Some Clerk endpoints (including `POST /v1/webhooks/{id}/test`) are gated by plan tier. Phase 1a now includes a single API call (`GET /v1/webhooks` with the Dev secret key) that returns either 200 (works) or 403 (need to upgrade). Operator does not proceed past Phase 1a if the test endpoint is unavailable on their tier.

## What changed from v9 (round 9 final fix)

Round 9's 10-model jury surfaced one real ordering issue (qwen3-next:80b): disabling Supabase sign-ups happens in Phase 6 pre-flight (post-import). During the ~15 min Phase 5.5 production import, new Supabase sign-ups could still happen and be missed. v10 fixes by moving the Supabase-sign-up-disable step into Phase 5.5 itself, as the FIRST action of that phase, BEFORE the import runs. Once the disable is in place, the import has no risk of racing new sign-ups.

The other two claims from qwen3-next were misreads (existing users already have `user_roles` rows; webhook endpoint is auth-exempt and reachable pre-cutover).

## What changed from v8 (round 8: 10-model jury final-approval fixes)

Round 8's 10-model jury surfaced no critical bugs, but flagged three real ordering/timing issues worth fixing:

1. **Phase 6 disables ALL Supabase sign-up paths in pre-flight, not after the smoke test** (kimi-k2.6). v8 had Supabase sign-ups disabled at step 5 (after the operator finishes smoke-testing), leaving a window where new Supabase sign-ups could happen between Phase 5.5's import and the disable. v9 moves the disable to pre-flight, before cutover. The operator now opens the Supabase dashboard tab BEFORE typing "go for prod cutover".

2. **Migration watchdog waits for main container to start before polling exit state** (deepseek-v4-pro:cloud). v8's watchdog could mistake "main container hasn't started yet" for "main container has exited", and prematurely re-enable the webhook before the migration script had paused it. v9 adds a startup-grace check: watchdog waits until main container is observed running at least once, then begins polling for exit.

3. **Rollback runbook now explicitly re-enables Supabase auth providers** (minimax-m2.7). v8's rollback re-enabled email/password sign-up in Supabase, but did NOT re-enable Google OAuth or magic-link. Existing Supabase Google users would have been locked out on rollback. v9 adds an explicit "re-enable all auth providers in Supabase dashboard" step, matching the Phase 0a screenshot's exact list.

## What changed from v7 (round 7: 10-model jury polish fixes)

The 10-model jury on v7 found no critical bugs (technical correctness 95%+). Only polish items remained, and v8 implements them:

1. **Webhook URL switch is now Codex-driven via Clerk Backend API, not operator clicking in dashboard** (kimi-k2.6). The operator no longer has to find the webhook in Clerk dashboard, click edit, paste the new URL, save. Codex calls `PATCH /v1/webhooks/{id}` programmatically as part of Phase 6 pre-flight. Operator approves the action; the URL change happens via API. Removes a manual paste-step that could fail silently.

2. **Phase 4 bcrypt pre-flight validator added** (gemma4:31b). Before the migration script makes any Clerk API calls, it runs a local sanity check on a sample of Supabase hashes: parses the MCF string, confirms it's well-formed bcrypt with a valid `$2[aby]$` prefix and 60-char total length, optionally invokes a local `bcrypt.checkpw` against a known throw-away test password to confirm structural integrity. Catches malformed/truncated hashes BEFORE we hit Clerk's API and blow through rate limits chasing 400s.

3. **Phase 6 webhook connectivity test added** (gemma4:31b). After Codex updates the prod webhook URL via API (item 1), Codex also triggers a synthetic Clerk test event via `POST /v1/webhooks/{id}/test` and verifies the prod backend received it with 200. If anything is broken (URL typo, signature mismatch, prod backend not reachable from Clerk's IPs, firewall change), it surfaces during pre-flight, not on first user signup.

4. **Phase 1c Google OAuth Consent Screen sub-step added** (gemma4:31b). Operator configures the Google Cloud Console OAuth Consent Screen (App name, User support email, Developer contact, Logo) BEFORE Phase 6, so the consent screen users see post-cutover looks legit instead of a scary unverified-app warning. Codex's checklist includes the exact Google Cloud Console URLs to navigate to.

## What changed from v6 (round 6: 10-model expanded jury fixes)

The 10-model jury caught five real bugs that the smaller 5-model jury missed in earlier rounds:

1. **Phase 6 webhook URL update moved to PRE-FLIGHT, not post-cutover** (gemma4:31b). In v6, the webhook URL was updated at Phase 6 step 6 — AFTER cutover at step 2. So new sign-ups during the gap would fire to the staging-pointed webhook, leaving the production backend reliant on the self-healing fallback as the primary path. Now the webhook URL switch is mandatory in pre-flight, before cutover.

2. **Phase 5 must use `--build`, not just `--force-recreate`** (minimax-m2.7). `NEXT_PUBLIC_USE_CLERK` is a Next.js client-bundle env var, baked at `next build` time. `--force-recreate` only re-schedules containers; it does NOT rebuild images. v6 would have staged a "Clerk cutover" that silently kept running Supabase auth in the browser bundle, giving the operator a false-positive smoke test. Phase 5 now uses `up -d --build`.

3. **Phase 6 disables ALL Supabase sign-up paths, not just email/password** (minimax-m2.7). Supabase has multiple sign-up mechanisms: email/password, magic link / email OTP, and OAuth providers (Google). v6 only mentioned disabling email/password. v7 adds: disable magic-link/email-OTP, disable each configured OAuth provider individually. Phase 0a screenshots the current Supabase Authentication providers page so the operator has a definitive list.

4. **Migration script auto-creates `/var/log/clerk-migration/` directory** (minimax-m2.7). v6 referenced this path for audit logs without ever creating it. v7 has the script's container entrypoint do `mkdir -p` first, with proper ownership, so audit logs always land somewhere findable.

5. **Migration script runs detached + uses lockfile-based webhook re-enable safety net** (kimi-k2.6). v6 ran the migration script in foreground via `docker compose run --rm`, which means a Hetzner web-console disconnect during the ~15 min import could SIGHUP the container before the `try/finally` re-enables the Clerk webhook — leaving the webhook paused permanently. v7 runs the script as detached `docker compose up` with logfile, plus a tiny separate "watchdog" sidecar that re-enables the webhook unconditionally if the migration container exits without the success-file marker. Operator sees logs in real time but is no longer the load-bearing piece for cleanup.

## What changed from v5 (deepseek-v4-pro final-review fix)

deepseek-v4-pro's solo final review verdict on v5 was **SHIP**, with one nice-to-have remaining. v6 implements the nice-to-have so v6 has zero remaining flagged items:

1. **Webhook silenced during Phase 5.5 production import.** In v5, when the migration script imported users to Clerk Production, the Clerk Prod webhook was still configured (per Phase 1c) to point at the **staging** backend URL. So Clerk would fire `user.created` events for every imported prod user at the staging backend — idempotent and harmless (webhook handler no-ops on already-set `external_id`, all writes use `ON CONFLICT DO NOTHING` against a separate staging DB), but noisy. v6 has the migration script automatically pause the Clerk webhook before importing and re-enable it after, via Clerk Backend API. Zero operator-clicks added; import runs silent.

## What changed from v4 (round 4 fixes)

1. **JWT race for new sign-ups now self-heals.** Round 4 flagged that v4's mitigation (lookup `clerk_user_map` row written by webhook) fails if the user's first request arrives BEFORE the webhook completes. v5 makes the backend self-healing: if `get_current_user()` sees a Clerk JWT with no `datasnoop_user_id` AND no row in `clerk_user_map`, it synchronously calls Clerk Backend API to PATCH `external_id` (assigns a fresh UUID), writes the mapping row, returns a normal response. Webhook may still fire later (idempotent ON CONFLICT DO NOTHING). New users never see an error from the race.
2. **Webhook URL prod-transition** is explicit non-skippable step in Phase 6 pre-flight checklist (Clerk Prod webhook still pointing at staging URL would mean prod webhooks never fire, breaking new sign-ups).
3. **Persistent qwen3-coder-next hallucination noted**: across rounds 1-4, qwen claimed Clerk's `password_digest` requires base64-encoded raw hash bytes, not the MCF string. Verified false against Clerk's official Backend API docs and via the other four jurors' agreement (kimi, glm, deepseek, minimax all confirm MCF). Phase 1b's live round-trip test is the empirical proof either way; if Phase 1b fails, that single test result resolves the dispute.

## What changed from v3 (round 3 fixes)

1. **Phase 0b ordering fixed.** Phase 0b needs Clerk Dev API keys to run the live bcrypt round-trip test. Phase 1 was originally where keys came from. Restructured: Phase 1a is "Clerk sign-up + Dev API key" (operator: 5 min). Phase 0b moves to AFTER Phase 1a (renamed Phase 1b). Phase 1c is the rest of the dashboard configuration. This removes the chicken-and-egg.
2. **Phase 4 validation step was meaningless.** Staging app still has `USE_CLERK=false` during Phase 4, so signing in to the staging app validates Supabase auth, not Clerk. Operator now validates the Clerk Staging import by signing in to **Clerk's hosted Account Portal for the Staging instance** with their email + original password — that proves Clerk + bcrypt work end-to-end without changing the staging app's auth flag.
3. **JWT claim race for new sign-ups handled.** Backend tolerates a missing `datasnoop_user_id` claim for the brief webhook race window: it falls back to using Clerk's `sub` claim until the JWT is refreshed (which happens automatically on next session token refresh). Documented expected behaviour.
4. **Migration script runs inside a Docker container** (`docker compose run --rm migrate-clerk python ...`), not on the host directly. No Python install on the server. Dependencies come from the existing backend image with a small additive layer.
5. **Phase 5.5 renamed to "Production import"** (it's the first time prod data lands in Clerk — calling it "delta sync" was confusing). The script's idempotency logic still handles any Supabase changes since Phase 4 staging import.
6. **Phase 5.5 must be back-to-back with Phase 6.** No multi-hour gap allowed; otherwise new Supabase sign-ups slip through. Codex pre-flight enforces "Phase 5.5 ran in last 60 min".
7. **Rollback gap for new Clerk-only sign-ups documented.** Users who sign up via Clerk during the 14-day soak are not in Supabase. If rollback occurs, they need to re-register. Realistic n is small (DataSnoop's daily sign-up rate × 14 days). Documented as accepted limitation.
8. **Cached frontend post-cutover.** Old frontend tabs may try Supabase auth endpoints after `USE_CLERK=true`. Backend returns 401 + `WWW-Authenticate` header, frontend reloads. Documented behaviour.
9. **Phase 0b also tests Google OAuth round-trip** (one Supabase Google user → Clerk Dev → sign-in via Google → confirm match by `sub`).
10. **Operator time bumped to 200-280 min total** per round 3 estimates (qwen's high-end was 450 but most operators won't hit edge-case debugging if the plan is solid).
11. **JWT template configuration** explicitly listed as a sub-step in Phase 1c.
12. **Cookie SameSite override**: if Phase 5's Stripe Checkout test fails, Codex configures Clerk to use `SameSite=None; Secure` instead of default `Lax`.

## Goals (in order, unchanged)

1. Existing users sign in with the SAME email + SAME password they used pre-migration. Zero forced password resets.
2. Operator hands-on time bounded.
3. No data loss — favourites, projects, Stripe subscription, role/tier all preserved.
4. Production cutover is reversible for at least 14 days post-cutover (with a small documented exception: Clerk-only sign-ups during the soak).

## Operator action budget v4

| Phase | Operator does | Approx time |
|---|---|---|
| 0a | Nothing | 0 |
| 1a | Sign up at clerk.com (free); create the DataSnoop application; copy the Development API publishable + secret keys to the operator's password manager | 5-10 min |
| 1b | Open Hetzner web console; paste Supabase DB URL + Clerk Dev secret key into one-shot shell vars; run Codex's bcrypt round-trip test on operator's own user; sign in to Clerk Dev's hosted Account Portal with the original password to confirm; same test for one Google OAuth user | 15-25 min |
| 1c | Walk through Codex's Clerk dashboard checklist (JWT template, allowed origins, MFA, security features, OAuth providers, webhook config); paste full set of API keys (Dev + Staging + Prod, plus webhook secret) into Hetzner web console env files | 90-120 min |
| 2 | Approve Codex PR | 1 min |
| 3 | Approve Codex PR | 1 min |
| 4 | Open Hetzner web console; paste Supabase DB URL inline; run Codex's STAGING-ONLY import command; close console; sign in to **Clerk Staging's Account Portal** with original password to confirm import worked | 15-20 min |
| 5 | Smoke-test login / favourites / Stripe Checkout / Google OAuth on staging app via Codex's explicit checklist | 25-35 min |
| 5.5 | (Immediately before Phase 6, same session) Open Hetzner web console; paste Supabase DB URL inline; run Codex's PROD import command; close console | 10-15 min |
| 6 | Yes/no for prod cutover; smoke-test prod login; disable Supabase email/password sign-up in Supabase dashboard | 15-20 min |
| 7 (day 15+) | Approve cleanup PR | 1 min |

Total: **~180-250 min** spread across 5-10 calendar days. The most concentrated session is the Phase 5.5 + Phase 6 back-to-back window (~30 min total in one sitting); the rest can be paused between phases.

## Technical strategy (unchanged from v3 except items below)

### JWT claim race for new sign-ups (self-healing backend)

For NEW users signing up via Clerk post-cutover, the user's first session JWT may lack `datasnoop_user_id` (Clerk minted it before the `user.created` webhook had a chance to set `external_id`). The backend does NOT block, retry, or loop. It self-heals once and caches:

**Request 1 (race window — happens at most once per new user):**
1. Backend gets Clerk JWT: has `sub`, no `datasnoop_user_id`.
2. Backend looks up `clerk_user_map(sub)`. Miss.
3. **Inside a single Postgres transaction (NEW v14)**: Backend assigns a fresh UUID, INSERTs `clerk_user_map(sub, uuid, clerk_synced_at NULL)` ON CONFLICT DO NOTHING, INSERTs `user_roles(email, 'user')` ON CONFLICT DO NOTHING, COMMITs. Both rows committed atomically. The `clerk_synced_at NULL` marker indicates "DB-side written, Clerk-side PATCH still pending".
4. Backend calls Clerk Backend API `PATCH /v1/users/{sub}` setting `external_id = uuid`.
   - On 200: backend updates `clerk_user_map.clerk_synced_at = now()`.
   - On error/timeout (NEW v17 — "Ghost Mapping" remediation): backend enqueues `(sub, uuid)` into a `clerk_pending_sync` table; a background worker retries the PATCH every 60s with exponential backoff up to 24h, then alerts the operator if still failing. Local DB is the source of truth in the meantime; subsequent user requests hit the `clerk_user_map` cache and proceed normally.
5. Backend uses the UUID as `datasnoop_user_id` and proceeds. ~1 extra round-trip to Clerk = ~150 ms latency spike on this single request.

**Requests 2..N (same JWT, before refresh):**
1. Backend gets same JWT: still no `datasnoop_user_id`.
2. Backend looks up `clerk_user_map(sub)`. **Hit** (row written in Request 1, step 3).
3. Backend uses the cached UUID. No Clerk API call. Normal latency.

**After JWT refresh (~60 sec, automatic via Clerk frontend SDK):**
1. New JWT carries `datasnoop_user_id` (because Clerk's `external_id` is now set).
2. Standard path used. `clerk_user_map` lookup no longer needed.
3. The race window is permanently closed for this user.

**Webhook handler runs idempotently:** when the webhook eventually fires, it sees Clerk's user already has `external_id` (set by us or by Clerk's own race), no-ops on the assignment, and `INSERT … ON CONFLICT DO NOTHING` on `user_roles` — so no row gets overwritten.

**For existing imported users**, the race is a non-issue: their `external_id` is set at migration-import time, every JWT carries `datasnoop_user_id` from session #1, none of the fallback code runs.

The user never sees an error or a loop. The only observable difference is ~150 ms latency on the very first request after sign-up.

### Migration script execution model

The migration script runs as a DETACHED Docker container with a webhook-cleanup watchdog sidecar — operator's web-console SSH disconnect cannot leave the Clerk webhook permanently paused.

Two services in `docker-compose.yml` (no profile, only run on demand):

1. `migrate-clerk` — main migration container.
   - Container entrypoint:
     - Creates `/var/log/clerk-migration/` if missing (`mkdir -p`).
     - Runs `python scripts/migrate_supabase_to_clerk.py --target=$TARGET`.
     - On clean success: writes `/var/log/clerk-migration/_success_${TARGET}_${DATE}.marker`.
   - Migration script flow:
     - Pauses Clerk webhook via Clerk API.
     - `try`: imports users, writes audit log.
     - `finally`: re-enables Clerk webhook (best-effort; if this fails, watchdog catches it).

2. `migrate-clerk-watchdog` — sidecar, started together with `migrate-clerk`.
   - **Startup grace with 5-minute timeout**: on launch, polls until `migrate-clerk` is observed in `running` state at least once OR 5 minutes have elapsed. If 5 min expire without `running` being observed, watchdog assumes the main container failed to start (e.g., bcrypt pre-flight aborted, env var missing), re-enables the webhook, logs the failure, and exits. Prevents both the premature-cleanup race AND the "stuck waiting forever" failure mode.
   - After grace: polls every 30 seconds:
     - If main container is still running: sleep.
     - If main container exited AND success marker is present: re-enable webhook (idempotent), exit.
     - If main container exited AND success marker is missing: re-enable webhook, log failure, exit. Operator sees "import failed; webhook restored" message.

Operator command (single one-shot):
```
docker compose up -d --build migrate-clerk migrate-clerk-watchdog && \
  docker logs -f leadpeek_migrate-clerk_1
```
The `-f` log tail is the operator's progress view. Closing the console (Ctrl-C the tail) does NOT kill the detached containers — they continue. The watchdog ensures cleanup either way.

Server doesn't need Python or any deps installed; everything is in the migrate-clerk image.

### Cookie SameSite

- Clerk's default cookie SameSite is `Lax`. Stripe Checkout's redirect-back flow can require `SameSite=None; Secure` in some browsers.
- Phase 5 staging soak runs the Stripe Checkout test on Chrome + Safari + Firefox (operator clicks through; Codex provides exact URLs).
- If any browser fails Stripe Checkout: Codex updates `ClerkProvider` config to `cookieSameSite: "none"` and `cookieDomain: ".datasnoop.be"`, redeploys staging, retest.

## Phase plan v4

### Phase 0a — Read-only audit (Codex; operator: 0 min)

Codex performs the v3 audit, **plus**:
- Codex (or operator) screenshots the Supabase dashboard's Authentication → Providers page so the operator has a definitive list of which sign-up paths must be disabled in Phase 6 step 5. Stored in `docs/auth-clerk-phase-0-audit.md` PR.

### Phase 1a — Clerk sign-up + Dev keys + plan-tier + API-shape verification (operator: 5-10 min)

1. Operator signs up at clerk.com (free tier).
2. Operator creates the "DataSnoop" application; Clerk auto-provisions a Development instance.
3. Operator copies from the Development instance:
   - Publishable key (`pk_test_...`)
   - Secret key (`sk_test_...`)
4. **Plan-tier verification gate (NEW v12)**: Codex runs ONE curl command (operator pastes secret key inline) hitting `GET https://api.clerk.com/v1/webhooks` to confirm webhook tooling is available on this Clerk plan. Pass = 200 with empty list (no webhooks yet). Fail = 403/404 → operator must upgrade Clerk plan before proceeding to Phase 1b. The `POST /v1/webhooks/{id}/test` endpoint that Phase 6 depends on is gated by the same tier; this gate catches it now instead of at cutover time.
5. **Webhook PATCH API-shape verification (NEW v14)**: Codex creates a temporary test webhook via `POST /v1/webhooks` with a placeholder URL, then PATCHes its URL via `PATCH /v1/webhooks/{id}` to a different placeholder, confirms the response shape, then deletes it. This proves the exact field name (typically `endpoint_url` or `url`; varies by Clerk API version) BEFORE Phase 6 depends on it. Codex records the confirmed field name in the migration runbook.
5. Saves keys into a password manager / safe location for the next phase.

No server changes yet. No code changes.

### Phase 1b — Live one-user round-trip test (Codex; operator: 15-25 min)

**Step 0 — Data Inspection (NEW v12)**: Before any script is written, confirm Supabase's actual storage format.
- Operator opens Hetzner Cloud Console; pastes `SUPABASE_DB_URL` as a one-shot shell var.
- **Column type inspection (NEW v17)**: Operator first runs `psql "$SUPABASE_DB_URL" -c "SELECT pg_typeof(encrypted_password) FROM auth.users LIMIT 1;"`. Expected: `text` or `varchar`. If it returns `bytea`, the migration script applies `encode(encrypted_password, 'escape')` to convert before sending to Clerk; otherwise pass-through.
- Operator runs Codex's command, which samples 8 rows (1 operator's own + 5 random + 1 oldest + 1 newest) and returns aggregate stats only: `psql "$SUPABASE_DB_URL" -c "SELECT length(encrypted_password) AS len, left(encrypted_password, 7) AS prefix, substring(encrypted_password from 5 for 2)::int AS bcrypt_cost, count(*) AS n FROM auth.users WHERE encrypted_password IS NOT NULL GROUP BY len, prefix, bcrypt_cost ORDER BY n DESC;"`. (Aggregate output only — no full hashes echoed to chat.)
- **Bcrypt cost factor check (NEW v14)**: Codex confirms `bcrypt_cost` is between 4 and 31 inclusive (Clerk's accepted range). Costs of 10 or 12 are common; cost 13+ may make Clerk's first-login verification slow (~1 sec) but still works.
- **Bcrypt-cost operator warning (NEW v15)**: If `bcrypt_cost ≥ 12`, Codex emits a single message to the operator: "Heads up — your existing passwords use bcrypt cost {N}. The first sign-in per user post-cutover takes about {2^(N-10)}× the cost-10 baseline (typically still under 1 second). Subsequent sign-ins are instant. This is informational, no action required, just so you don't think it's a bug."
- Codex confirms: every row has `len = 60` and `prefix` matches `^\$2[aby]\$\d{2}\$` (e.g., `$2a$10$`, `$2b$12$`). Distribution should be uniform — same prefix family across all sampled rows. Mixed prefixes are OK (Clerk handles all bcrypt variants); mixed lengths or non-MCF prefixes are NOT OK.
- If any row fails: STOP. Codex investigates, escalates to Claude. Phase 1b does not proceed until the format is confirmed compatible with Clerk's `password_digest` field.

1. Operator opens Hetzner Cloud Console (still open from Step 0 if continuing in same session).
2. Operator pastes `CLERK_SECRET_KEY` (Dev) as a second one-shot shell var alongside `SUPABASE_DB_URL`.
3. Codex provides the exact `docker compose run` command.
4. Script extracts ONE real Supabase user (operator's own test account), runs a TWO-PASS import:
   - **Pass 1**: `POST /v1/users` with email + `password_digest` (MCF) + `password_hasher: "bcrypt"` + `email_addresses[0].verification.status: "verified"` + `external_id` (Supabase UUID).
   - **Pass 2**: 250 ms after Pass 1 returns, `PATCH /v1/users/{id}` setting `first_name` + `last_name` from Supabase `user_metadata.first_name`/`full_name` (or empty strings if absent). **Eventual-consistency retry (NEW v16)**: if PATCH returns 404, sleep 500 ms and retry up to 5 times before giving up. Clerk's API can take a few hundred ms after POST before subsequent PATCH succeeds. If PATCH ultimately fails with 4xx (Clerk rejects the field) or all retries 404, import still succeeds; user may see "Complete profile" prompt on first login. Phase 1b's empirical test on operator's own account reveals this.
5. Operator opens Clerk Dev's hosted Account Portal (URL: `https://<dev-frontend-api>.accounts.dev/sign-in`); signs in with email + ORIGINAL password.
6. Same test for one Google-OAuth user: extract Google `sub` from Supabase, import with `external_accounts: [{strategy: "oauth_google", provider_user_id: <sub>}]`, then operator clicks "Sign in with Google" on Clerk Dev portal, expects ONE consent screen, confirms it logs in to the same imported user (not a duplicate).
7. Operator closes Hetzner console.

Acceptance:
- Email/password test user signs in to Clerk Dev with original password.
- Google OAuth test user signs in to Clerk Dev via Google, links to the imported user (Clerk dashboard shows ONE user, not two).
- This is the **gating test** for the entire migration.

### Phase 1c — Full Clerk dashboard configuration (operator: 90-120 min)

Operator walks through Codex's checklist for the Clerk Dev + Staging + Prod instances:
- Enable email/password authentication
- Enable Google OAuth (operator may need Google Cloud Console for OAuth client creation; Codex provides those steps too)
- Enable MFA (TOTP + backup codes)
- Enable security: compromised-password protection, bot/attack protection, user enumeration protection
- Configure allowed origins/redirect URLs (datasnoop.be, www.datasnoop.be, staging.datasnoop.be, dev localhost)
- **Google Cloud Console redirect URIs (NEW v12 — exact mapping)**: For each Clerk environment (Dev, Staging, Prod), Clerk surfaces a specific redirect URI under Configure → SSO connections → Google → "Authorized redirect URIs" — Codex extracts these via Backend API and provides the exact string the operator pastes into Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID → Authorized redirect URIs. There must be exactly 3 URIs in Google Console, one per environment. A `redirect_uri_mismatch` 400 on first OAuth sign-in means this step was skipped or the URIs were truncated.
- **Configure JWT template**: name `datasnoop`, claim `datasnoop_user_id` mapped from `{{user.external_id}}`, claim `email` already included
- Configure `user.created` webhook URL pointing to `https://staging.datasnoop.be/api/_auth/clerk-webhook` (testing first); Codex will switch to production URL via Clerk Backend API during Phase 6 pre-flight
- **Configure Google Cloud Console OAuth Consent Screen** (separate from Clerk's Google OAuth client config): App name = "DataSnoop", User support email, Developer contact email, Logo (DataSnoop's existing favicon-large), homepage URL = `https://datasnoop.be`. Without this, users see a "Google hasn't verified this app" warning on first OAuth sign-in post-cutover, which breaks the "invisible" UX. Codex provides exact Google Cloud Console navigation: APIs & Services → OAuth consent screen → Edit App.
- **Verify Clerk's Google OAuth scope list contains ONLY `openid`, `profile`, `email`** (NEW v13). Sensitive scopes (Drive, Calendar, etc.) require Google's app-verification process, which would block sign-in until verification completes. DataSnoop only needs basic profile info, so non-sensitive scopes are sufficient. Path: Clerk dashboard → User & Authentication → Social Connections → Google → Scopes — confirm only the three default scopes are checked.
- **Google OAuth Consent Screen "Publishing status" gate** (NEW v14). After configuring the OAuth Consent Screen, operator confirms in Google Cloud Console → APIs & Services → OAuth consent screen that "Publishing status" reads "**In production**" (not "Testing" or "Pending Verification"). For non-sensitive scopes (which we use), Google auto-approves and "In production" appears within minutes. If "Pending Verification" appears, the migration pauses until Google clears it (typically <24 h for non-sensitive; weeks if Google pulled the app for manual review of an "official-looking" name/logo). Operator should not proceed to Phase 6 until status is "In production".
- **Clerk Account Linking explicitly enabled** (NEW v15). Path: Clerk dashboard → User & Authentication → Account & Linking → enable "Sign-in with multiple identifiers" AND "Allow account linking by email". This lets imported Google users (whose Google email matches their Supabase email) get auto-linked to the existing Clerk user when they click "Sign in with Google" post-cutover, instead of creating a duplicate account.
- Capture all keys + secrets:
  - Dev pk_test, sk_test, JWKS URL, issuer, webhook secret
  - Staging pk_test, sk_test, JWKS URL, issuer, webhook secret
  - Prod pk_live, sk_live, JWKS URL, issuer, webhook secret
- Operator pastes them into `/opt/leadpeek/.env` (build args), `/opt/leadpeek/.env.staging`, `/opt/leadpeek/.env.production` via Hetzner web console nano commands
- Codex provides a self-test command (`curl Clerk JWKS URL with the secret key`) that confirms each key is valid before continuing.

### Phase 2 — Frontend SDK swap (Codex)

Same as v3.

### Phase 3 — Backend JWT verification (Codex)

Same as v3, plus:
- Backend tolerates missing `datasnoop_user_id` claim, falls back to `sub` via `clerk_user_map` lookup.
- New `clerk_user_map (clerk_sub, datasnoop_user_id)` table; webhook writes the row.

### Phase 4 — Staging-only user import (operator: 15-20 min)

1. Codex writes `scripts/migrate_supabase_to_clerk.py` and the `migrate-clerk` docker-compose service.
2. Operator opens Hetzner web console.
3. Operator pastes `SUPABASE_DB_URL` and confirms `CLERK_SECRET_KEY` (Staging) is in env.
4. Operator runs Codex's exact command (detached + watchdog model — see "Migration script execution model" above):
   ```
   SUPABASE_DB_URL=postgres://... TARGET=staging \
     docker compose up -d --build migrate-clerk migrate-clerk-watchdog && \
     docker logs -f leadpeek_migrate-clerk_1
   ```
5. Script runs the bcrypt pre-flight validator first (aborts on any malformed sample), then imports all Supabase users to Clerk Staging with bcrypt + email_verified + Google external_accounts. Watchdog sidecar guarantees Clerk webhook re-enable even if the operator closes the Hetzner console.
6. Audit log written to `/var/log/clerk-migration/staging-YYYY-MM-DD.json`. Success marker at `/var/log/clerk-migration/_success_staging_YYYY-MM-DD.marker`.
7. Operator closes Hetzner console once `migrate-clerk` container has exited (visible in the log tail, or check `docker ps -a | grep migrate`).
8. Operator opens **Clerk Staging's hosted Account Portal** (NOT the staging app, since `USE_CLERK=false` on staging app at this point) and signs in with email + ORIGINAL password to confirm a representative imported user works.

### Phase 5 — Staging cutover (operator: 25-35 min)

1. Codex sets `USE_CLERK=true` and `NEXT_PUBLIC_USE_CLERK=true` in `/opt/leadpeek/.env.staging`.
2. Codex **rebuilds and recreates** staging containers — `--build` is mandatory because `NEXT_PUBLIC_USE_CLERK` is baked into the Next.js client bundle at build time; `--force-recreate` alone would silently keep the old `false` value: `docker compose -f docker-compose.staging.yml -p leadpeek-staging up -d --build frontend-staging backend-staging`. After containers are up, Codex `curl`s a staging health endpoint to verify the build picked up the new env (look for a build-time-baked indicator in the response).
3. Operator runs Codex's smoke checklist on **the staging app** (`staging.datasnoop.be`):
   - Sign in with own email + same password as prod
   - Sign out
   - Sign in with Google (one consent screen, then through)
   - Open a specific known company page
   - Add a favourite (Codex provides one CBE)
   - Open the admin panel
   - Trigger Stripe Checkout in test mode (test on Chrome + Safari + Firefox + **Brave + Chrome Incognito** [v14: stricter third-party-cookie blocking; if the cookie path needs `SameSite=None`, these browsers are the canaries])
   - Trigger password reset flow (email arrives? reset completes?)
   - Sign out, then sign in as a non-admin user — confirm admin panel access denied
   - Try to access `/api/...` with old Supabase JWT (should 401, not 500)
4. Codex tails staging backend logs throughout for auth errors.
5. Auth-failure monitoring: alert if `/api/auth-error` rate > 10 per 5 minutes; alert routes to t.braet@gmail.com.
6. 48h staging soak before Phase 5.5/6.
7. Operator gives go/no-go after the soak.

### Phase 5.5 — Production import (operator: 15-20 min — IMMEDIATELY before Phase 6)

1. **Operator disables ALL Supabase sign-up paths in the Supabase dashboard FIRST** (before the import runs). Authentication → Providers, then disable each path Phase 0a's screenshot identified:
   - Email + password
   - Magic link / Email OTP / Passwordless
   - Google OAuth (and any other configured OAuth provider)
   This closes the window where a new Supabase sign-up could race the import. Existing user logins remain unaffected — only new account creation is blocked.
2. Codex IMMEDIATELY verifies Supabase sign-ups are disabled — operator screenshots the Supabase Auth Providers page after clicking toggles, pastes the screenshot into chat, Codex visually confirms ALL providers show "Disabled". If any provider is still enabled, Codex tells the operator to fix it before the import command can be issued. (Screenshot path is intentional — avoids requiring the operator to provide a Supabase Management API token.)
   - **Phase 5.5 start-timestamp recorded (NEW v14)**: Codex notes the wall-clock time when the operator confirms screenshot. This becomes the cutoff for the post-import sanity check.
3. Operator opens Hetzner web console.
4. Operator pastes `SUPABASE_DB_URL` inline; Clerk PROD secret key already in env.
4. Operator runs Codex's command (detached + watchdog):
   ```
   SUPABASE_DB_URL=postgres://... TARGET=prod \
     docker compose up -d --build migrate-clerk migrate-clerk-watchdog && \
     docker logs -f leadpeek_migrate-clerk_1
   ```
5. Migration script does, in order:
   - **Bcrypt pre-flight validator** (NEW in v8): samples 5-10 random Supabase rows, parses each `encrypted_password` MCF string, confirms `$2[aby]$<cost>$<53 chars>` regex match + 60-char total length, optionally runs `bcrypt.checkpw("known_test_password", hash)` on the operator's own test row to confirm hash parses + verifies as expected library behaviour. Aborts BEFORE any Clerk API call if any sample is malformed.
   - **Pauses the Clerk Prod webhook** via Clerk Backend API `PATCH /v1/webhooks/{id}` setting `enabled=false` (so the bulk import does not fire `user.created` events at the still-staging-pointed webhook URL — keeps staging backend silent).
   - Imports all Supabase users to Clerk PROD; idempotent on `external_id` and `email`; PATCHes password_digest if Supabase `updated_at` is newer than last import.
   - **Re-enables the Clerk Prod webhook** (`enabled=true`) after import completes, even on error (cleanup in a `try/finally`). The webhook URL is still the staging URL at this point — that's fine because the URL is updated to prod as part of Phase 6 pre-flight before any post-cutover sign-ups can happen.
   - On script failure: webhook is still re-enabled by the `finally` block; the operator sees the error and re-runs (idempotent).
6. Audit log to `/var/log/clerk-migration/prod-YYYY-MM-DD.json` records: pause-time, import counts, re-enable-time, any errors.
7. **Post-import sanity check (NEW v14)**: Codex queries Supabase for any rows in `auth.users` with `created_at > <Phase 5.5 start-timestamp from step 2>`. If `count > 0`, that means new users signed up to Supabase DURING the import (= screenshot verification missed a toggle). Codex aborts before Phase 6 and tells the operator which provider was still enabled. Operator disables it, re-runs Phase 5.5 (idempotent), sanity check should now return zero.
8. Operator closes Hetzner console.
9. Operator immediately proceeds to Phase 6 (no multi-hour pause).

### Phase 6 — Production cutover (operator: 15-20 min)

1. Codex pre-flight (ALL green required, NON-SKIPPABLE — order matters):
   - Phase 5 staging soak >= 48h, zero auth errors
   - Phase 5.5 production import within last 60 min, webhook re-enabled (audit log confirms)
   - **Codex updates Clerk Prod webhook URL via Backend API**: calls `PATCH /v1/webhooks/{id}` setting endpoint to `https://datasnoop.be/api/_auth/clerk-webhook`. Programmatic — not a manual operator click — to remove typo risk.
   - **Codex verifies the URL update via GET (NEW v14)**: immediately calls `GET /v1/webhooks/{id}` and confirms the response shows the production URL. If the field name was misidentified in Phase 1a or the PATCH didn't take effect, this catches it BEFORE cutover. Mismatch = abort.
   - **Codex sends a test webhook with a TEST FLAG**: calls `POST /v1/webhooks/{id}/test`. The webhook handler MUST check the event payload for the test marker (Clerk includes `"test": true` or similar in test events) and SKIP the `clerk_user_map` + `user_roles` inserts — otherwise the synthetic test user pollutes prod tables. The handler returns 200 to satisfy the connectivity check. (NEW v14: explicit test-event handling in webhook spec.)
   - **Confirm Supabase sign-ups are still disabled** (they were disabled at the start of Phase 5.5; Codex re-checks via Supabase Management API or operator re-confirms via dashboard).
   - Latest images rolled forward + tagged
   - Supabase env values still on server (env vars only — they are needed for the rollback path; only the dashboard sign-up toggles are off)
   - `.env.production` backup taken
2. **JWT template propagation soak**: if the JWT template was edited in Clerk dashboard within the last 5 minutes (e.g., during Phase 1c re-config), Codex waits until 5 minutes have elapsed since the last edit before issuing cutover. Clerk's JWT templates can take a few minutes to propagate across edge nodes; cutting over too soon means the first wave of users hit JWTs without `datasnoop_user_id` and trigger the self-heal path (still works, just adds 150 ms to their first request). The soak makes the cutover invisible to all users, not most.
3. **Hard PROCEED gate (NEW v14)**: Codex echoes the exact action it is about to take ("About to write `USE_CLERK=true` and `NEXT_PUBLIC_USE_CLERK=true` to /opt/leadpeek/.env.production, rebuild + recreate frontend and backend containers. THIS IS THE POINT OF NO RETURN until rollback. Type the single word `PROCEED` to confirm. Anything else is treated as 'wait, let me think'."). Operator pastes back the literal word `PROCEED` — Codex matches against `^PROCEED$` exactly. Any other input (questions, second thoughts, accidental paste) holds the cutover.
   - **Build-window UX message (NEW v16)**: immediately after `PROCEED` is received, Codex emits: "Build starting. Old containers continue serving live traffic for the next ~3-8 minutes while the new image builds — site is NOT down during this window. I'll confirm 'rolled to new images' when the cutover actually happens (~30 sec at the end). Don't panic if you check the site and it still looks like Supabase auth — that's the old container still serving."
   - Once `PROCEED` is received, Codex sets the env values and runs `docker compose up -d --build frontend backend` (`--build` mandatory for the same NEXT_PUBLIC reason as Phase 5).
3. ~30-60 sec deploy window.
4. Operator runs same smoke checklist on prod (`datasnoop.be`).
5. Auth-failure monitoring same as Phase 5, applied to prod.
6. 48h prod soak: Codex monitors logs daily.
7. 14 days post-cutover: Phase 7 unlocks.

### Rollback runbook (Phase 6)

**Two rollback modes — pick by elapsed time since Phase 6 cutover:**

**Mode A: Fast wipe-and-revert (within 30 min of cutover, NO new sign-ups since)**

Use this when Phase 6 cutover failed quickly and you want a clean slate back on Supabase:
1. Operator says "fast rollback Clerk" in chat.
2. Codex via Hetzner Cloud Console: sets `USE_CLERK=false` + `NEXT_PUBLIC_USE_CLERK=false` in `.env.production`, runs `docker compose up -d --build frontend backend`.
3. Codex queries Clerk Backend API for all users with `external_id IS NOT NULL` (= the Phase 5.5 imports), exports them to JSON for audit, then bulk-deletes them via `DELETE /v1/users/{id}` in batched calls. Clerk Prod ends up empty.
4. Operator re-enables ALL Supabase sign-up paths in dashboard.
5. Codex tails logs to confirm Supabase auth healthy.
6. No further communication needed — users sign in to Supabase with their original creds, no resets, no orphans.

**Mode B: Soft rollback (>30 min elapsed OR users have signed up via Clerk since cutover)**

Use this when Clerk has been live long enough that users may have changed passwords or new accounts have been created:
If Phase 6 cutover fails or auth errors spike:
1. Operator says "rollback Clerk" in chat.
2. Codex via Hetzner Cloud Console: sets `USE_CLERK=false` in `.env.production` and `NEXT_PUBLIC_USE_CLERK=false`.
3. Codex runs `docker compose up -d --build frontend backend` (frontend rebuild required because `NEXT_PUBLIC_*` is build-arg-baked).
4. **Operator re-enables ALL Supabase sign-up paths in the Supabase dashboard** — using the Phase 0a audit screenshot as the checklist (matches the providers disabled in Phase 6 pre-flight). Specifically: Email/password + Magic link/Email OTP + Google OAuth + any other provider that Phase 0a flagged. NOT just email/password — that would lock out existing Google users when they next try to sign in.
5. Codex tails logs to confirm Supabase auth is healthy on all relevant providers (test sign-in via each).
6. Communications:
   - Users who changed their Clerk password during the active window must use Supabase "Forgot password" once.
   - Users who signed up freshly via Clerk during the active window are NOT in Supabase. They have to re-register on the rolled-back Supabase auth. Operator can identify them by querying Clerk's user list for users with `external_id IS NULL` (those are post-cutover sign-ups; imported users all have `external_id` set).

### Phase 7 — Cleanup (day 15+; operator: 1 min)

Same as v3.

## Risks + mitigations (v4 additions to v3 table)

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| New Clerk-only sign-ups during 14-day soak orphaned by rollback | Possible | Low (small N over 14d) | Documented. Operator can re-create those few accounts from the Clerk export. |
| JWT missing `datasnoop_user_id` for first request after sign-up | Certain | Low | Backend fallback to `sub` via `clerk_user_map`. Subsequent JWT refresh has the claim. |
| Supabase auth-schema permission denied on direct DB | Medium | Medium | Phase 0a verifies. Default Supabase project DB connection uses `postgres` superuser which can read auth.users. If a custom role is in use, document the GRANT step. |
| Cookie SameSite=Lax breaks Stripe Checkout | Medium | Medium | Phase 5 explicit Stripe test on 3 browsers; if fails, Codex sets SameSite=None. |
| Migration script Python deps missing on server | Eliminated | n/a | Script runs inside Docker (uses backend image base). |
| Hetzner web console copy/paste flakiness | Medium | Low | Codex provides commands as single-line `bash -c "..."` strings to minimise paste errors; provides verification step (`echo $VAR | head -c 4` to confirm key prefix). |

## Standing safeguards (unchanged from v3)

## Definition of done (unchanged from v3)

## Known accepted limitations

- Users see one Google consent screen on first OAuth sign-in post-cutover.
- Users with MFA on Supabase re-enrol on Clerk.
- All active sessions invalidate at cutover (one extra login).
- Any Clerk password change during the 14-day soak is not back-portable to Supabase if rollback occurs.
- Clerk-only sign-ups during the 14-day soak are not in Supabase if rollback occurs (small N, manual re-creation).
- For ~few seconds after a NEW Clerk sign-up, the user's JWT lacks `datasnoop_user_id`. Backend handles via `sub` fallback. Effectively invisible to the user.
- Operator's clock time: ~180-250 min total spread across 5-10 calendar days.
