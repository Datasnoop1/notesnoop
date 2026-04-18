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
Prod and staging run on the **same Hetzner VPS** (`62.238.14.150`)
in separate docker-compose projects (`leadpeek` vs `leadpeek-staging`).
Prod shares the DB with staging — **there is no staging DB**; staging
reads from the same Postgres that prod does. Implications: data loads
on staging write to the prod DB. Destructive DB migrations tested on
staging affect prod.

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
| `activity_log` | Every `/api/*` request | Endpoint + method + user_email (or `anon:<ip-hash>`) + timestamp. Drives tier limits and admin analytics. |
| `ai_company_enrichment`, `ai_people_enrichment`, `ai_insights` | OpenRouter outputs | Cached LLM responses. |
| `company_embedding` | Per-company text embeddings | Semantic search + similar-AI retrieval. |
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
| Zenrows | Proxied scraping of company websites + LinkedIn | `ZENROWS_API_KEY` |

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
See `docs/tech-debt.md` item 10 for the one current drift (`/api/polls`
uses `get_current_user` where it should use `_require_admin`).

---

## Deployment

### Commands

```
# Staging (port 8080, plain HTTP, same DB as prod)
./scripts/deploy_staging.sh 62.238.14.150 ~/.ssh/hetzner_leadpeek

# Prod (port 443, Let's Encrypt)
./scripts/deploy.sh 62.238.14.150 ~/.ssh/hetzner_leadpeek
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
  rebuild (`--build`).
- `/opt/leadpeek/.env.production` — **runtime env**. The backend +
  frontend containers read this via `env_file`. Changing values here
  requires **`docker compose up -d --force-recreate`**, not a plain
  `restart` — `restart` preserves the container's original env.
- **`deploy.sh` SCPs local `.env.production` over the server's.**
  If the server's version has drifted (e.g. you added a key on the
  server only), `deploy.sh` will overwrite it. Always `md5sum`
  both before running.

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
- **Layout wrapper** in `frontend/src/app/layout.tsx` sets
  `max-w-[1536px] mx-auto px-4 sm:px-6 lg:px-8`. Every page that needs
  a narrower container sets its own `mx-auto w-full max-w-[1200px]`
  inside. Exception: screener (split-pane full-viewport).
- **Mobile breakpoints**: Tailwind defaults. `sm:` = 640px,
  `md:` = 768px. Mobile-first: write `h-10 md:h-7` not the inverse.
  Apple HIG floor for tap targets is 44px; we accept 32–40px for
  secondary controls, 44px for primary.
- **iOS zoom-on-focus**: triggered when input text is < 16px. All
  form inputs should use `text-base` (16px) on mobile. Many admin
  inputs still fail this (tech-debt item 19).
- **Financials tables** use a **sticky first column** pattern: the
  row-label `<td>` / `<th>` gets `sticky left-0 z-[5/10] bg-[color]
  shadow-[1px_0_0_rgba(226,232,240,1)]` + `w-[110px] md:w-auto
  md:min-w-[240px]` + `whitespace-normal break-words`. Applied
  consistently across P&L / CF / BS / Credit / Valuation.

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
   data-centre IPs. Use `Datasnoop/1.0 (Belgian Company Intelligence)`.
3. **NBB politeness.** 1.5s between requests, 3-wide concurrency cap
   on `/api/companies/{cbe}/load`. Don't lower these.
4. **Supabase OAuth fallback cache is sticky.** When Site URL changes,
   the bogus-state redirect URL can stay cached at Supabase for hours.
   Dashboard save + toggle didn't clear it in one session — needed
   Management API or a support ticket.
5. **`docker compose restart` doesn't re-read env_file.** Only
   `up -d --force-recreate` does.
6. **Staging and prod share the same DB.** Any write via staging
   hits prod's data. No isolation.
7. **`STAGING_MODE` env** gates a "staging admin-only" middleware.
   Currently OFF (staging is open for anonymous browsing). Admin
   routes still gated at the router level via `_require_admin`.
8. **Nginx `scrollbar-none` class** (Tailwind utility) hides the
   native scrollbar — if a table has `overflow-x-auto scrollbar-none`,
   mobile users have no visual cue that they can scroll. Drop
   `scrollbar-none` on mobile-visible scroll containers.
9. **KBO licence prohibits using personal data for direct marketing.**
   Bulk director exports are a regulatory risk. See tech-debt Group A.
10. **EBITDA = rubric `9901` (operating profit) + rubric `630` (D&A).**
    Don't assume it's a standalone line item.

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
