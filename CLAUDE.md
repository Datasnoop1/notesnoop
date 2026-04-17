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

## Tech Stack

- **Database**: PostgreSQL (`DATABASE_URL` env var). SQLite era is over.
- **Backend**: FastAPI (Python 3.12+) in `backend/`
- **Frontend**: Next.js 16 + React 19 in `frontend/` (App Router, standalone build)
- **Auth**: Supabase (JWT verified server-side via JWKS)
- **Billing**: Stripe (subscriptions + webhooks)
- **AI enrichment**: OpenRouter
- **Web scraping**: Zenrows
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
│   └── test_nbb_loader.py          # Only test file currently
├── data/                           # KBO ZIPs / NBB downloads (gitignored)
├── docs/
│   ├── kbo-schema.md
│   ├── nbb-api.md
│   └── belgian-gaap.md
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
  `tier_config`, `graveyard`. Validates Supabase JWTs via JWKS. Enforces
  tier-based usage limits with in-memory rate limiting (Redis optional for
  multi-instance scaling). Filters bot traffic. Hashes anon IPs with
  `ACTIVITY_LOG_IP_SALT` before logging.

- **Next.js frontend** (`frontend/`):
  Screener, company deep-dive, sector benchmarking, account, billing.
  Supabase auth client-side; Stripe Checkout for upgrades. NOTE:
  Next.js 16 + React 19 — APIs differ from older docs. See
  `frontend/AGENTS.md` and `node_modules/next/dist/docs/` before coding.

- **AI enrichment** (OpenRouter): summarisation and entity enrichment from
  scraped pages.

- **Web scraping** (Zenrows): proxied scraping of public Belgian company
  websites and Staatsblad pages.

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

- All scripts runnable standalone with `python src/script.py`
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
2. If both pass, merge the PR into `master` automatically.
3. Trigger the staging deploy (`./scripts/deploy_staging.sh`) so the
   operator can test on port 8080.
4. NEVER deploy to production automatically. Production deploy requires
   the operator to explicitly approve after staging is green.
5. If either agent flags CRITICAL issues, fix them first and re-run both
   agents. Do NOT merge with known criticals.
6. If the deploy scripts require parameters the assistant doesn't have
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
