# Belgian Company Database

A searchable database of Belgian companies combining KBO registry data with NBB
annual accounts — a self-hosted Belfirst alternative for PE deal sourcing and
screening. Now a multi-user web platform with tiered subscriptions.

## READ FIRST (new context window onboarding)

Before doing any substantive work in this repo, read these two
documents. They exist specifically to prevent drift between Claude
sessions on who the product is for, how it's put together, and what
the non-obvious operational rules are:

1. **[`docs/product.md`](docs/product.md)** — what DataSnoop is,
   who uses it, how the tiering works, current state, direction.
2. **[`docs/architecture.md`](docs/architecture.md)** — runtime
   topology, data flow, auth model, deployment mechanics, and the
   gotchas you'd otherwise rediscover the hard way (NBB keys, iOS
   zoom, `docker compose restart` not re-reading env, etc).

Then scan [`docs/tech-debt.md`](docs/tech-debt.md) for the current
triage state.

If your task touches the semantic pipeline, also read
[`docs/semantic-operations.md`](docs/semantic-operations.md). It is the
canonical runbook for semantic queue policy, fast-lane rules, excluded
legal forms, ETA interpretation, and staging/prod rollout procedure.

If your task touches any search surface — `/api/companies/search`,
`/api/people/search`, `/api/search/suggest`, the header autocomplete,
or the `/search` page — read [`docs/search.md`](docs/search.md)
first. Covers data sources (KBO + NBB + Staatsblad), the V2
normalisation contract, scoring arms, response shapes, known data
gaps, and the debug-a-missing-result runbook.

If your task touches NBB data loading, the backfill pipeline, or
`financial_data`, read [`docs/nbb-loader-operations.md`](docs/nbb-loader-operations.md).
It covers both pipelines (daily batch + historical backload), the
candidate-selection logic, the KBO juridical-form code mapping (with known
gotchas), coverage state, and the full change history.

If your task touches the public API (`/api/v1/*`, `api_keys`, the
`dsk_live_…` token format, `scripts/issue_api_key.py`), read
[`docs/public-api-orientation.txt`](docs/public-api-orientation.txt)
first. Internal orientation: auth/storage/limits, error envelope,
issuance + revocation, live key snapshot, and the refresh command.
The customer-facing spec is [`docs/api.md`](docs/api.md).

## Tech Stack

- **Database**: PostgreSQL (`DATABASE_URL` env var). SQLite era is over.
- **Backend**: FastAPI (Python 3.12+) in `backend/`
- **Frontend**: Next.js 16 + React 19 in `frontend/` (App Router, standalone build)
- **Auth**: Supabase (JWT verified server-side via JWKS)
- **Billing**: Stripe (subscriptions + webhooks)
- **AI enrichment**: Bulk and on-profile paths share `unified_summary` on
  `company_enrichment` (Phase 5, shipped 2026-04-29). Bulk pipeline runs
  `ollama:qwen3-coder-next` (Q2) → `ollama:deepseek-v4-flash:latest`
  escalation, writing `bulk_summary`, `bulk_website_text`,
  `unified_summary` at tier `bulk_only`/`bulk_escalated`, and the
  embedding. On-profile elaboration is `call_elaboration_narrative` in
  `ai_client.py`: `ollama:qwen3-coder-next` draft → `ollama:kimi-k2.6`
  critic-refine on top of the cached bulk row, plus multi-page scrape,
  group context, recent Staatsblad, and a press search. The embedding
  regenerates from the upgraded narrative so semantic search and
  find-similar improve with every viewed profile. The
  `/api/companies/{cbe}/ai-insights` endpoint returns sub-second via the
  ai_insights cache → bulk_summary fast path → KBO skeleton fallback;
  the qwen+kimi work runs in a pinned background asyncio task; the
  frontend polls every 30s (cap 3 attempts) and silently swaps in the
  rich version. Legacy `ai_insights_pipeline` remains in `ai_client.py`
  behind the `PHASE_5_ELABORATION_ENABLED` env flag (default `true`)
  as a single-flag rollback; Phase 5.4 (post-30-day soak) drops the
  legacy columns and code.
- **Web scraping**: raw `httpx + trafilatura` is the bulk default. **Zenrows
  was replaced by an in-network `playwright-scraper` service on 2026-04-25**
  — headless Chromium rotating through a Webshare datacenter proxy pool
  (~100 IPs). Lives at `playwright-scraper/`, reachable inside the docker
  network as `http://playwright-scraper:8000/scrape`. The legacy `zenrows*`
  function names in `backend/scraper.py` now delegate to this service;
  `ZENROWS_API_KEY` env var is no longer required. The Zenrows-Google SERP
  layer remains DROPPED from bulk discovery per Phase 0 (datacenter proxies
  are 0% viable against Google's anti-bot regardless of provider).
- **Deployment**: docker-compose + nginx + Let's Encrypt
- **Loaders**: `requests` for KBO/NBB ingestion, streaming CSV/JSON
- **Legacy UI**: Streamlit app under `app/` still works against Postgres but is secondary

## Project Structure

```
platform/
├── CLAUDE.md
├── requirements.txt
├── docker-compose.yml              # Production stack (ports 80/443)
├── docker-compose.staging.yml      # Staging stack (port 8080, plain HTTP)
├── nginx/
│   ├── default.conf                # Production nginx (TLS via Let's Encrypt)
│   └── staging.conf                # Staging nginx (HTTP only)
├── backend/                        # FastAPI app
│   ├── Dockerfile
│   ├── main.py
│   └── routers/                    # dashboard, screener, companies, stats,
│                                   # people, favourites, feedback, admin,
│                                   # polls, stripe_pay, staatsblad,
│                                   # tier_config, graveyard
├── frontend/                       # Next.js 16 + React 19
│   ├── Dockerfile                  # Standalone build, node:22-alpine
│   └── app/
├── src/                            # Data loaders (now write to Postgres)
│   ├── kbo_loader.py               # KBO full ZIP → Postgres
│   ├── kbo_updater.py              # KBO daily update ZIPs
│   ├── nbb_client.py               # NBB CBSO REST wrapper
│   ├── nbb_loader.py               # Parse NBB JSON filings → Postgres
│   ├── pipeline.py                 # Daily orchestrator
│   └── schema.sql                  # Postgres DDL
├── app/                            # Legacy Streamlit UI (secondary)
├── scripts/
│   ├── init_db.py
│   ├── screen.py
│   ├── semantic_status.py          # semantic health / ETA snapshot
│   ├── seed_enrichment_queue.py    # semantic queue seeding
│   ├── reclassify_enrichment_queue.py   # semantic reprioritisation
│   ├── apply_semantic_exclusions.py     # semantic corpus cleanup
│   └── test_nbb_loader.py          # Only test file currently
├── data/                           # KBO ZIPs / NBB downloads (gitignored)
├── docs/
│   ├── kbo-schema.md
│   ├── nbb-api.md
│   ├── belgian-gaap.md
│   ├── semantic-operations.md   # semantic worker runbook + handoff doc
│   └── search.md                # search V2 — data sources, scoring, runbook
├── .env.example
└── .gitignore
```

## Components

- **KBO loader / updater** (`src/kbo_loader.py`, `src/kbo_updater.py`):
  Stream-parse the ~300MB KBO ZIP into Postgres. Daily updates apply
  `*_delete.csv` then `*_insert.csv`, keyed on EnterpriseNumber. Track applied
  ExtractNumbers to avoid reprocessing.

- **NBB client + loader** (`src/nbb_client.py`, `src/nbb_loader.py`):
  REST client for the NBB CBSO API. Generates a UUID per request, sleeps
  1–2s between calls, base URL switches between `ws.uat2.cbso.nbb.be` and
  `ws.cbso.nbb.be`. Loader parses JSON filings (XBRL since April 2022) into
  the `financial_data` table per the rubric mapping in `docs/belgian-gaap.md`.

- **FastAPI backend** (`backend/`):
  Routers: `dashboard`, `screener`, `companies`, `stats`, `people`,
  `favourites`, `feedback`, `admin`, `polls`, `stripe_pay`, `staatsblad`,
  `tier_config`, `graveyard`, `search` (Phase 1 semantic),
  `admin_enrichment` (Phase 1 admin panel). Validates Supabase JWTs via
  JWKS. Enforces tier-based usage limits with in-memory rate limiting
  (Redis optional for multi-instance scaling). Filters bot traffic.
  Hashes anon IPs with `ACTIVITY_LOG_IP_SALT` before logging.

- **Bulk enrichment worker** (`backend/enrichment_worker.py`): long-running
  async process that drains a Postgres-backed queue (`enrichment_job`) to
  populate `company_enrichment.bulk_summary` + `company_embedding`.
  Postgres `FOR UPDATE SKIP LOCKED` makes multiple workers safe. Shipped as
  the `enrichment-worker` service in `docker-compose*.yml`. Admin controls
  at `/admin/enrichment` (pause/resume, daily USD budget, skip-list
  maintenance, dead-letter retry). See `docs/architecture.md` §Semantic
  enrichment and `docs/semantic-operations.md` for the live operator
  workflow.

- **Next.js frontend** (`frontend/`):
  Screener, company deep-dive, sector benchmarking, account, billing.
  Supabase auth client-side; Stripe Checkout for upgrades. NOTE:
  Next.js 16 + React 19 — APIs differ from older docs. See
  `frontend/AGENTS.md` and `node_modules/next/dist/docs/` before coding.

- **AI enrichment** (OpenRouter): summarisation and entity enrichment from
  scraped pages.

- **Web scraping** (`playwright-scraper`): proxied scraping of public Belgian
  company websites and LinkedIn pages, served by an internal Playwright +
  Chromium container rotating through Webshare datacenter proxies. Replaces
  the previous Zenrows integration as of 2026-04-25.

- **Deployment**: `docker compose up -d` builds and runs backend + frontend +
  nginx. Staging variant exposes port 8080 with no TLS. Healthchecks gate
  startup ordering.

## Key Facts (don't relearn these)

- EBITDA = rubric **9901** (operating profit) + rubric **630** (D&A).
- CBE numbers are stored as 10 digits without dots. KBO files render them as
  `0xxx.xxx.xxx`; NBB API requires `0xxxxxxxxx`. Strip dots on load, send
  bare digits to NBB.
- KBO data licence prohibits using personal data for direct marketing.
- NBB JSON only available for XBRL filings since April 2022.

## Conventions

- All scripts runnable standalone with `python path/to/script.py`
- Use argparse for CLI arguments
- Log to stdout with timestamps
- `.env` for secrets, never hardcode API keys
- Postgres connection via `DATABASE_URL`
- File naming: snake_case for Python, kebab-case for docs
- Error handling: log and continue (don't crash the pipeline on one bad filing)
- Don't load the KBO ZIP into memory; stream/iterate

## Environment Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # then fill in real values

# Local dev (without Docker)
uvicorn backend.main:app --reload   # backend on :8000
cd frontend && npm install && npm run dev   # frontend on :3000

# Production
docker compose up -d --build

# Staging (port 8080, HTTP)
docker compose -f docker-compose.staging.yml up -d --build
```

Server env nuance:
- `/opt/leadpeek/.env` feeds docker-compose build args
- `/opt/leadpeek/.env.production` is the runtime env file
- runtime env changes require `docker compose up -d --force-recreate`, not a
  plain `restart`

The OneDrive multi-device single-user model is **obsolete**. All data lives in
Postgres; multiple users hit the same DB through the FastAPI backend. Don't
sync `.venv/` or `node_modules/` between devices.

## Deploy protocol — STAGING FIRST, ALWAYS

Production changes must go through staging. The workflow is:

1. Push the feature branch to origin.
2. Deploy to staging: `./scripts/deploy_staging.sh` (runs against
   `docker-compose.staging.yml`, port 8080, plain HTTP).
3. Smoke-test the affected feature on staging. Include anything adjacent
   that might have regressed.
4. Only after staging is green, deploy to production:
   `./scripts/deploy.sh`.

Never deploy directly to production. If a hotfix feels too urgent for the
staging round-trip, it's still not too urgent — staging takes minutes, a
broken prod takes hours.

## Communication habits for AI assistants

The operator is non-technical. Keep them in the loop in plain English:

1. Before launching any subagent or long-running task, state in one short
   sentence what you asked it to do and roughly how long it takes.
2. While waiting for a subagent or a deploy, don't go silent. Either give
   a one-sentence update on what you're doing in the meantime, or say
   "waiting for X, nothing else to do until it reports".
3. When a subagent finishes, summarise the result in one or two sentences
   of plain English. Don't dump the raw technical output.
4. At decision points — merging, deploying, destructive actions, risky
   refactors — flag what you're about to do next. Pause before acting if
   the action is risky and isn't covered by a standing rule.
5. Avoid jargon. "PR", "master", "HEAD", "diff" etc. need a one-line
   translation the first time they appear in a conversation.

## Standing autonomy rules for AI assistants

The operator is non-technical, does not review code, and validates changes
by testing them on staging. AI assistants working on this repo follow this
policy by default, without asking:

1. Before any change is merged to `master`, run TWO independent review
   agents in parallel: (a) a correctness/regression audit and (b) a
   security review. Both must pass.
2. If both pass and the change is docs-only or otherwise read-only with
   no shared-DB side effects, merge into `master` automatically.
3. If the change touches a shared-production surface (semantic worker,
   loaders, queue scripts, schema, deploy scripts, billing, auth, or any
   code that can mutate the shared prod DB from staging), pause for
   operator approval before merging or deploying.
4. Only trigger staging deploy automatically for changes that cannot
   mutate the shared prod DB. For semantic and other shared-DB workflows,
   staging is code-validation only and must not be treated as a safe
   worker sandbox.
5. NEVER deploy to production automatically. Production deploy requires
   the operator to explicitly approve after staging is green.
6. If either agent flags CRITICAL issues, fix them first and re-run both
   agents. Do NOT merge with known criticals.
7. If the deploy scripts require parameters the assistant doesn't have
   (server IP, SSH key), hand the command off to the operator with a
   copy-paste-ready invocation.

## Important

- NEVER commit `.env*` or database dumps
- Don't ship Supabase or Stripe keys in build args; pass them through `.env`
  for `docker compose` variable substitution
- Bot filtering and tier limits are load-bearing — don't bypass them in new
  routers
- Only one test file exists (`scripts/test_nbb_loader.py`); add tests as you
  touch code
