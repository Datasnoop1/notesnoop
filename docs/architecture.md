# DataSnoop — Architecture & Operational Reality

Read this **together with `docs/product.md` and `CLAUDE.md`** if you're a
new context window. This one covers the how: components, data flows,
decisions, and gotchas that would otherwise need to be relearned.

---

## Runtime topology

```
            Browser
               │
               ▼
    ┌────────────────────┐
    │  nginx (:80/:443)  │  TLS via Let's Encrypt on prod
    │  /etc/letsencrypt  │  HTTP-only on staging (port 8080)
    └─────┬──────────┬───┘
          │          │
   /api/* │          │ /, /_next/*, everything else
          ▼          ▼
   ┌─────────┐  ┌───────────┐
   │ FastAPI │  │ Next.js   │  standalone build, node:22-alpine
   │ uvicorn │  │ SSR + CSR │  Next.js 16 + React 19
   │ :8000   │  │ :3000     │
   └────┬────┘  └─────┬─────┘
        │             │ SSR calls backend via
        │             │ API_URL_INTERNAL=http://backend:8000
        │             ▼  (client calls use relative /api/*)
        │        (same FastAPI above)
        ▼
   ┌────────────────────────┐
   │ Postgres (host network)│  host.docker.internal:5432
   │ leadpeek DB            │
   └────────────────────────┘
```

Three containers per environment: `backend`, `frontend`, `nginx`.
Prod and staging run on the **same Hetzner VPS**
in separate docker-compose projects (`leadpeek` vs `leadpeek-staging`).
Staging uses an independent `leadpeek_staging` Postgres database restored
nightly from prod and scrubbed by `scripts/staging_scrub.sql` before the
rename swap. Worker variants are behind the `test-workers` compose profile
so they do not run during normal staging deploys.

---

## Data

### Postgres schema (the tables that matter)

| Table | Source | Notes |
|---|---|---|
| `enterprise` | KBO full + updates | Master list. `enterprise_number` = 10-digit CBE, no dots. |
| `denomination` | KBO | Names in NL / FR / EN. Use `type_of_denomination = '001'` for registered name. |
| `address` | KBO | Registered office = `type_of_address = 'REGO'`. |
| `activity` | KBO | NACE code per enterprise. Main activity = `classification = 'MAIN'`. |
| `administrator`, `shareholder`, `participating_interest` | KBO + staatsblad scrape + extract-admins AI | The PII-laden tables. |
| `company_info` | Derived | Materialised name + city + zipcode + nace_code per CBE. Normalised name for fast search. |
| `financial_data` | NBB CBSO | Raw filing data: `(enterprise_number, fiscal_year, rubric_code, value)`. Rubric codes like `70` (revenue), `9901` (operating profit), `630` (D&A). |
| `financial_summary`, `financial_latest`, `financial_by_year` | Views / materialised per-company | Pre-pivoted P&L / BS figures for fast reads. |
| `nace_lookup` | Static reference | NACE code → description, descriptions in 3 languages. |
| `user_roles` | Supabase-synced | `{email, role}` where role ∈ {anon, free, pro, admin}. |
| `meta` | Small operational key-value table | Stores runtime toggles such as `enrichment_enabled` and semantic daily budget. |
| `activity_log` | Every `/api/*` request | Endpoint + method + user_email (or `anon:<ip-hash>`) + timestamp. Drives tier limits and admin analytics. |
| `ai_company_enrichment`, `ai_people_enrichment`, `ai_insights` | OpenRouter outputs | Cached LLM responses. |
| `company_enrichment.bulk_*` | Phase 1 bulk pipeline | JSONB `bulk_summary` + confidence + hash of scraped text. Written by the worker; read by embedder + `/api/search/semantic`. Separate from narrative `ai_insights`. |
| `company_embedding` | Per-company text embeddings | Semantic search + similar-AI retrieval. Embedded text comes from `bulk_summary` (Phase 1) with fallback to NACE template for no-data rows. |
| `enrichment_job` | Phase 1 bulk-enrichment queue | Postgres-backed work queue. `status ∈ {queued, claimed, done, failed, dead, excluded}`, claimed via `FOR UPDATE SKIP LOCKED`. `excluded` means intentionally outside the semantic corpus, not "completed". |
| `query_embedding_cache` | Phase 1 /api/search/semantic | Keyed by `sha256(lower(q))`, 30-day TTL. Saves an embedding call per repeat query. |
| `aggregator_skiplist` | Phase 1 scrape skip-list | DB-backed replacement for the `_SKIP_DOMAINS` constant. Read from `backend/scraper.py::_load_skiplist` with 5-min cache; seeded from `src/schema.sql`. |
| `staatsblad_publications` | Scraped from publicatieblad | Legal notices, bankruptcy filings, etc. |

**Don't forget**: CBE numbers in KBO files render as `0xxx.xxx.xxx`
but are stored without dots. NBB API wants bare digits too. Strip
dots on load; never pad.

### External services

| Service | Used for | Auth |
|---|---|---|
| Supabase | User auth (Google OAuth + email/password), JWT issuance | JWKS public key (for backend JWT verification) + project anon key (for browser client) |
| Stripe | Subscriptions (€49/mo Pro), one-off donations, webhooks | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` |
| NBB CBSO | Per-company annual-accounts pulls | `NBB_AUTHENTIC_KEY` (and `NBB_EXTRACT_KEY` for daily batch) |
| NBB SDMX | Under evaluation as bulk-route alternative to CBSO | **No auth** (public API). See tech-debt + `docs/sdmx-migration-spike.md`. |
| OpenRouter | LLM pipeline for AI insights, extract-admins, company enrichment | `OPENROUTER_API_KEY` |
| `playwright-scraper` (in-network) | Headless Chromium + Webshare datacenter proxies. Replaces Zenrows as of 2026-04-25. | `WEBSHARE_PROXIES_FILE` (host path), `PLAYWRIGHT_SCRAPER_URL` (set in compose) |

---

## Auth + tier model

1. **Supabase** issues a JWT on sign-in (Google or password). Browser
   stores it in cookies (host-only, scoped to the specific host).
2. **Browser** sends `Authorization: Bearer <jwt>` on every `/api/*`
   call.
3. **Backend `auth.py`** verifies via JWKS cache (ES256/RS256, 1-hour
   TTL), falls back to HS256 with shared secret. Returns a user dict
   `{email, id}` or raises 401.
4. **`Depends(get_current_user)`** — hard-required auth. Routes using
   this 401 when anonymous.
5. **`Depends(optional_user)`** — soft. Returns `None` for anonymous,
   otherwise the user dict.
6. **`TierLimitMiddleware`** runs before any `/api/*` route, classifies
   the endpoint into a `limit_type` (see `_classify_endpoint` in
   `backend/main.py`), looks up the current daily count from
   `activity_log`, compares to `tier_config.<limit_type>_per_day`,
   blocks with 429 if over.
7. **`BotFilterMiddleware`, `RateLimitMiddleware`** — IP-hash-based
   global caps (200 req/min default). Runs regardless of auth.

**Role enforcement on admin routes** uses a router-level
`Depends(_require_admin)` dependency — independent of any middleware.
See `docs/tech-debt.md` for any currently known auth drift rather than
assuming every admin-labelled surface is already aligned.

---

## Deployment

### Commands

```
# Staging (port 8080, plain HTTP, independent scrubbed DB clone)
./scripts/deploy_staging.sh <SERVER_IP> <SSH_KEY_PATH>

# Prod (port 443, Let's Encrypt)
./scripts/deploy.sh <SERVER_IP> <SSH_KEY_PATH>
```

### What deploy scripts do

1. SSH to the VPS.
2. `cd /opt/leadpeek && git pull` (always pulls `master`).
3. `docker compose [-f docker-compose.staging.yml] up -d --build`.
4. 10-second wait, then `ps` to report container health.

### Env files on the server

- `/opt/leadpeek/.env` — **build-arg source**. `docker-compose.yml`
  references `${NEXT_PUBLIC_SUPABASE_URL}` etc. from this file during
  the frontend Docker build. Changing values here requires a
  rebuild (`--build`). Keep this file limited to non-sensitive build-time
  values such as `NEXT_PUBLIC_*`; runtime secrets belong in
  `.env.production`.
- `/opt/leadpeek/.env.staging` — staging runtime env. It currently mirrors
  production external-service values by operator decisions (2026-05-01 and
  2026-05-02) but points `DATABASE_URL` at `leadpeek_staging` and sets
  `STAGING_MODE=true`. Stripe/Supabase isolation remains deferred after
  Bitemporal Phase A; see `docs/staging-isolation-evidence-2026-05-02.md`.
- `/opt/leadpeek/.env.production` — **runtime env**. The backend +
  frontend containers read this via `env_file`. Changing values here
  requires **`docker compose up -d --force-recreate`**, not a plain
  `restart` — `restart` preserves the container's original env.
- **`deploy.sh` SCPs local `.env.production` over the server's.**
  If the server's version has drifted (e.g. you added a key on the
  server only), `deploy.sh` will overwrite it. Always `md5sum`
  both before running, and make a remote backup first:
  `cp /opt/leadpeek/.env.production /opt/leadpeek/.env.production.bak.$(date +%s)`.

### Standing deploy rules

- Staging first, always. Prod only after explicit operator approval.
- Two parallel review agents before merging to `master`: correctness
  + security. For UI changes, add a third mobile-review agent.
- Never run `docker compose` manually on the server — use the scripts.
- Backend env changes → always `--force-recreate`, never `restart`.
- Before a prod deploy: verify `/opt/leadpeek/.env` exists AND
  `grep API_URL_INTERNAL /opt/leadpeek/.env.production` returns a
  match. Missing `API_URL_INTERNAL` → frontend build fails → prod
  goes offline.

---

## Frontend specifics

- **Next.js 16 + React 19**. `frontend/AGENTS.md` flags that this is
  not the Next.js you know from training. Read `node_modules/next/dist/docs/`
  before writing any Next-specific code.
- **App Router** only. All pages are React Server Components by default;
  mark client-only with `"use client"` directive.
- **Supabase client** (`frontend/src/lib/supabase.ts`): uses
  `createBrowserClient` from `@supabase/ssr`. Session cookie is
  **host-only** — we tried apex-domain scoping and it broke session
  persistence. See `feedback_ssr_env.md` and this session's rollback
  commit on 2026-04-17.
- **UI conventions** — breakpoints, iOS zoom rules, tap targets,
  typography scale, sticky-first-column pattern, brand tokens, shared
  primitives, dark-mode policy — all live in
  [`docs/ui-conventions.md`](ui-conventions.md). Read that before
  styling anything new; update it when a convention changes.

---

## Known gotchas (learn these to avoid re-discovering)

1. **NBB keys rotate without notice — and rapidly.** Two rotations
   landed within ~24h on 2026-04-17 alone. If NBB calls start
   returning 401/403, check the subscription portal first — the key
   may have been rotated server-side. The current keys are the
   Primary from each subscription: AuthenticData + Extracts +
   AuthenticArchiveData. Env vars: `NBB_AUTHENTIC_KEY`,
   `NBB_EXTRACT_KEY`, `NBB_ARCHIVE_KEY` (the third is set in env but
   not yet read by code; reserved for the archive endpoints). Apply
   via `sed -i 's|^NBB_…_KEY=.*|NBB_…_KEY=<new>|' .env .env.production`,
   then `docker compose up -d --force-recreate backend frontend` for
   prod and the same `-f docker-compose.staging.yml -p
   leadpeek-staging` invocation for staging. A plain `restart` will
   silently keep the old key — see gotcha #5.
2. **NBB User-Agent matters.** NBB's Azure WAF rejects
   `Mozilla/5.0` and `python-urllib/*` headers with 403/500 from
   data-centre IPs. Use `Datasnoop/1.0 (Company Intelligence)`.
3. **NBB politeness.** 1.5s between requests, 3-wide concurrency cap
   on `/api/companies/{cbe}/load`. Don't lower these.
4. **Supabase OAuth fallback cache is sticky.** When Site URL changes,
   the bogus-state redirect URL can stay cached at Supabase for hours.
   Dashboard save + toggle didn't clear it in one session — needed
   Management API or a support ticket.
5. **`docker compose restart` doesn't re-read env_file.** Only
   `up -d --force-recreate` does.
6. **Staging has its own scrubbed DB clone.** The nightly snapshot restores
   prod into `leadpeek_staging_next`, applies `scripts/staging_scrub.sql`,
   then swaps it into `leadpeek_staging`. Stripe/Supabase isolation remains
   intentionally deferred per operator decisions on 2026-05-01 and
   2026-05-02.
7. **`STAGING_MODE` env** gates a "staging admin-only" middleware.
   It is true in `.env.staging`; admin routes are still gated at the
   router level via `_require_admin`.
8. **Nginx `scrollbar-none` class** (Tailwind utility) hides the
   native scrollbar — if a table has `overflow-x-auto scrollbar-none`,
   mobile users have no visual cue that they can scroll. Drop
   `scrollbar-none` on mobile-visible scroll containers.
9. **KBO licence prohibits using personal data for direct marketing.**
   Bulk director exports are a regulatory risk. See tech-debt Group A.
10. **EBITDA = rubric `9901` (operating profit) + rubric `630` (D&A).**
    Don't assume it's a standalone line item.

---

## Semantic enrichment (Phase 1 — bulk/narrative split)

Operational runbook: [`docs/semantic-operations.md`](semantic-operations.md).
Read that before changing queue policy, fast-lane thresholds, excluded legal
forms, or ETA assumptions.

DataSnoop runs **two** AI enrichment pipelines that share one canonical
output column on `company_enrichment` (Phase 5, shipped 2026-04-29).
The bulk pipeline processes the target corpus automatically; the
elaboration pipeline runs in the background when a user opens a
profile and upgrades the same row.

| Column | Who writes it | Tier set | Shape |
|---|---|---|---|
| `unified_summary` (JSONB) | bulk worker, then `call_elaboration_narrative` | `bulk_only` → `bulk_escalated` → `narrative_lite` → `narrative_full` | Single canonical narrative; tier only ever climbs up. Bulk fills the structured 4-field shape; elaboration adds `market_position`, `history`, `key_management[]`, `source_attribution`. |
| `bulk_website_text` (TEXT) | bulk worker | n/a | Cached cleaned scrape text. Read by elaboration to skip a redundant fetch when fresh (< 30 days). |
| `model_chain` (JSONB) | both | n/a | Ordered audit trail: `[{step, model, latency_ms, tokens, completed_at}]`. |
| `ai_insights` (TEXT) | elaboration (kept for backwards compat) | n/a | Same JSON as `unified_summary`. Read by the legacy cache short-circuit in the FastAPI endpoint. Removed in Phase 5.4 after 30-day soak. |
| `bulk_summary` (JSONB) | bulk worker (kept for backwards compat) | n/a | Mirror of the bulk-tier `unified_summary`. Removed in Phase 5.4. |

**Why two pipelines, one column:** the bulk path is cost-optimised
(`ollama:qwen3-coder-next` Q2 + `ollama:deepseek-v4-flash` escalation,
flat-rate Ollama subscription) and runs across the ~1.7M KBO universe.
The elaboration path tolerates two LLM calls per profile view because
it's only triggered by user attention, and produces a richer narrative
(`ollama:qwen3-coder-next` draft → `ollama:kimi-k2.6` critic-refine).
The elaboration **regenerates the embedding** from the upgraded text,
so semantic search and find-similar quality compounds with every viewed
profile. Both pipelines share the scraper, the KBO-context builder,
and the corporate-graph helper.

### Bulk pipeline (worker)

```
1. Unknown / branch-only CBE → no-op skip
2. Excluded-form check → out-of-scope legal forms → mark `excluded`, no corpus write
3. Dormant check       → `is_dormant(...)` short-circuit (`DISSOLVED_SITUATION_CODES`)
4. EBITDA fast lane    → known EBITDA below floor → template + embed, no discovery
5. Website resolve     → KBO contact WEB row → else DuckDuckGo (throttled)
6. Scrape              → raw httpx + trafilatura (≤8k); proxy fallback via in-network playwright-scraper (Chromium + Webshare DC proxies) for sites that block raw httpx
7. Template fallback   → scrape absent or untrustworthy → deterministic summary
8. KBO context block   → build_kbo_context_block({parent, admins, NACE, notes…})
9. Q2 call             → call_q2(kbo, scraped) — ollama:qwen3-coder-next, structured output
10. Collision check    → check_entity_collision — cheap 2nd Q2 call
                          that catches same-named wrong-entity matches
11. Escalation         → tier-1 big / KBO nace-flag / q2.confidence=low
                          → call_haiku_escalation — ollama:deepseek-v4-flash:latest
                          (fallbacks: glm-5.1, minimax-m2.7)
12. Persist            → company_enrichment.bulk_summary, bulk_website_text,
                          unified_summary @ tier bulk_only|bulk_escalated, model_chain
13. Embed              → text-embedding-3-small @ 256 dims → company_embedding
```

All LLM calls tag the OpenRouter request with a `/bulk-enrichment/<cbe>`
endpoint label (via `set_current_endpoint`) so the admin cost panel
attributes spend correctly. Daily spend guard reads back from
`llm_call_log.cost_usd` summed by date.

### Quality floor + search filtering

`/api/search/semantic` filters out `bulk_confidence IN ('low',
'insufficient_information')` by default. `?include_uncertain=1` flips
it. The same floor is applied by the on-profile elaboration step
(`call_elaboration_narrative`) when it decides whether to surface a
narrative or fall back to a NACE-template blurb.

### Worker operational controls

| Knob | Default | Where to change |
|---|---|---|
| `enrichment_enabled` | `true` | `meta` table / admin pause-resume endpoint |
| Daily USD budget | `$10` | `meta.enrichment_daily_budget` / admin endpoint |
| Concurrency | `3` | `WORKER_CONCURRENCY` env in compose |
| DDG throttle | env-tuned, intentionally conservative | `DDG_MIN_INTERVAL_S` env |
| EBITDA fast lane floor | `200000` EUR | `SEMANTIC_FASTLANE_EBITDA_FLOOR` env |
| Max attempts | `5` | `enrichment_queue.MAX_ATTEMPTS` |
| Stale-claim release | `30 min` | `release_stale()` call in worker loop |

Kill switch: `UPDATE meta SET value='false' WHERE variable='enrichment_enabled'`
causes the worker to drain in-flight and sleep on the next poll.

### Seeding the queue

Use `python scripts/seed_enrichment_queue.py --scope <pilot|tier1_2|tier3_web|
tier3_no_web|template>`. Priorities (`PRIORITY_TIER1..TEMPLATE`) live in
`backend/enrichment_routing.py`. The worker claims highest-priority first.

### Rollback

`meta.enrichment_enabled=false` pauses. The `bulk_*` columns and
`company_embedding` are additive — no destructive migration.

**Staging safety:** staging workers are behind the `test-workers` compose
profile, and queue/user/API/business-state tables are scrubbed from the
nightly `leadpeek_staging` clone before it becomes live.

If you need to restart the queue from zero, truncate it only from the
production backend context:
`TRUNCATE enrichment_job;` (still leaves bulk rows intact). See
`docs/semantic-operations.md` for the safe semantic rollout procedure.

---

## Pending decisions + active spikes

- **SDMX migration**: replace CBSO per-company key-gated API with the
  public SDMX REST API. Prompt for a second Claude window lives in the
  2026-04-17 session transcript. Outcome will land at
  `docs/sdmx-migration-spike.md`.
- **Staging OAuth**: Google login on `staging.datasnoop.be` is broken;
  Supabase fallback cache still returns `datapeak.invm.be`. Email/
  password login works as a bypass.
- **PII tier limits**: operator explicitly chose tier-rate-limiting
  over auth-gating for the PII-read endpoints. Implementation pending
  (tech-debt Group A).

---

## File-level pointers

| Need to change… | Start in… |
|---|---|
| Company search behaviour | `backend/routers/companies/search.py` |
| NBB loading | `backend/routers/companies/financials.py` (FastAPI route) + `src/nbb_client.py` (loader script) |
| Tier limits | `backend/main.py` — `TierLimitMiddleware` + `_classify_endpoint` |
| Admin analytics | `backend/routers/admin.py` (huge file — search for the specific route) |
| Company profile page | `frontend/src/app/company/[cbe]/company-page-client.tsx` + `_tabs/*.tsx` |
| Screener | `frontend/src/app/screener/page.tsx` (big, dense) |
| Auth behaviour | `backend/auth.py` + `frontend/src/lib/supabase.ts` |
| Deployment | `scripts/deploy.sh`, `scripts/deploy_staging.sh`, `docker-compose*.yml` |
| Tech debt | `docs/tech-debt.md` (triage + raw items) |
