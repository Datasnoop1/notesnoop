# Data Architecture — Phase Gates (executor checklist)

**Companion to `docs/data-architecture-deep-dive.html`** — that doc is
the reference manual; this is the day-to-day checklist. If the two
disagree, the deep-dive wins; update this file to match.

Each phase below has the same five sections:

- **Preconditions** — what must be true before starting. Verify each.
- **Files** — files this phase touches. Anything else = scope creep.
- **Commands** — the actual shell / SQL the executor runs.
- **Postconditions** — verifiable assertions. Each is a query, a
  curl, a grep — not "should look right".
- **Approval gate** — Y/N. If Y, operator approves before merge.

Execution is now locked to must-have phases only. Codex should execute
Week 0 through Week 2 plus the parallel FTS track from this checklist.
Week 3, Week 4, Person v1, Ownership, and Bitemporal remain blocked
until the operator explicitly opens that phase; placeholder rows must
first be converted into the same five-section format. Do not reopen
architecture choices while executing these phases.

**Autonomy with `.env` access (assumed setup):** the Codex sandbox
carries `HETZNER_PASS`, `HETZNER_PG_URL`, `OPENROUTER_API_KEY`,
`ANTHROPIC_API_KEY`, and the NBB keys. With those, the gate semantics
become:

- **Gate N**: Codex proceeds autonomously. Standard correctness +
  security review applies before merge.
- **Gate Y**: Codex runs every step that doesn't itself mutate prod
  (build, commit, staging deploy, read-only psql verification, SSH
  audit reads, `pg_dump`) autonomously. Codex pauses at the single
  prod-mutating tail step of each phase, emits the exact command for
  the operator, the operator runs it, returns the output, Codex
  verifies the postcondition. **Policy ≠ capability**: prod deploys
  stay operator-approved per CLAUDE.md even when Codex *could* run
  them.

The redaction rule applies throughout: never echo `DATABASE_URL`,
`HETZNER_PASS`, or other secret values into transcripts; use
`SELECT current_database()` or `\conninfo` for verification, redact
before logging.

**Operator-runs-it summary** (the floor of intervention across must-have
phases — assumes the staging Stripe / Supabase / webhook accounts are
pre-staged before kickoff; if not, Week-2a grows by the time it takes
to create them):

| Phase | Operator command(s) |
|-------|--------------------|
| Week-0b | install updated `kbo_update.sh` into `/opt/leadpeek/scripts/` (scp + chmod) |
| Week-0c | `./scripts/deploy.sh` after Codex reports staging green |
| Week-0d | confirm maintenance window OR let Codex VACUUM ANALYZE off-hours autonomously (operator picks) |
| Week-1a | `python scripts/migrate.py baseline --target=prod` (one-shot baseline registration) |
| Week-1b | merge approval per inventory-capture PR; Codex emits the post-merge `migrate up --target=prod` batch |
| Week-2a | create `/opt/leadpeek/.env.staging` with staging Stripe/Supabase/webhook secrets (third-party-account-setup territory; operator-only); approve verification doc |
| Week-2b | add 02:30 UTC snapshot cron entry to `/etc/cron.d` on prod |
| Week-2-FTS | `./scripts/deploy.sh` after staging soak |

Roughly eight touch points across all must-have phases. Codex emits
exact commands; operator runs and returns output. Everything else is
autonomous.

---

## Phase Week-0a — Branch reality check

- **Preconditions**: working branch's HEAD is known. Codex starts from
  `origin/master` unless the operator explicitly asks to continue a
  named feature branch.
- **Files**: none.
- **Commands**:
  ```bash
  git fetch origin master
  git status
  git log --oneline origin/master ^HEAD | head -20
  ```
- **Postconditions**:
  - Executor records the branch name and HEAD SHA in the handoff.
  - If currently on `staatsblad-consumers-recovery` or another
    feature branch, stop before implementation unless the branch has
    been rebased onto `origin/master` and the operator explicitly chose
    that branch for this phase.
  - `backend/db.py` instantiates `ThreadedConnectionPool(2, 20, ...)`,
    no `SimpleConnectionPool` references in the live constructor path.
    Verify: `grep -n "ConnectionPool" backend/db.py` — the class on the
    `_pool = psycopg2.pool.…` line must be `ThreadedConnectionPool`.
  - `backend/routers/companies/search.py` defines `search_companies` as
    a sync `def`, not `async def`. Verify:
    `grep -nE "^(async )?def search_companies" backend/routers/companies/search.py`
    — the matched line must NOT start with `async`.
  - *(Line numbers drift as the surrounding code gets explanatory
    comments — the substance check is what matters, not the address.)*
  - If either is wrong, rebase / cherry-pick `105b303` + `79ed79c`
    from origin/master before any other phase.
- **Approval gate**: N — diagnostic, not a change.

## Phase Week-0b — KBO cron audit

- **Preconditions**: SSH access to prod.
- **Files**: `scripts/kbo_update.sh` (will be added to repo).
- **Commands**:
  ```bash
  ssh root@<prod> "crontab -l | grep kbo_update"
  ssh root@<prod> "cat /opt/leadpeek/scripts/kbo_update.sh"
  # copy to repo, add post-load ANALYZE, commit
  ```
- **Postconditions**:
  - `git ls-files scripts/kbo_update.sh` returns the path.
  - Diff between live `/opt/leadpeek/scripts/kbo_update.sh` and the
    repo copy is empty modulo the `ANALYZE` addition.
  - Last successful run timestamp pulled from the cron log.
- **Approval gate**: Y — touches the prod schedule.

## Phase Week-0c — De-async deploy

- **Preconditions**: Week-0a green; standing rules read; staging
  smoke-tested.
- **Files**: `backend/db.py`, `backend/routers/companies/search.py`,
  `backend/routers/_search_helpers.py` (if present).
- **Commands**:
  ```bash
  ./scripts/deploy_staging.sh
  # smoke-test /api/companies/search on staging
  # operator approves → ./scripts/deploy.sh
  ```
- **Postconditions**:
  - `/api/companies/search?q=Colruyt` p95 latency on staging < 500ms
    (was > 2s on the broken async path).
  - Connection-pool slots-in-use < 18 (cap is 20) under steady search load.
- **Approval gate**: Y — prod deploy.

## Phase Week-0d — Preflight

- **Preconditions**: prod psql access.
- **Files**: none — DB-side maintenance only.
- **Commands**: per `docs/db-maintenance-recommendations.md` Section 0:
  `VACUUM ANALYZE` the seven KBO tables; queue-table retention prune.
- **Postconditions**: `pg_stat_user_tables.last_analyze` within last hour
  for the seven tables.
- **Approval gate**: Y — operator confirms maintenance window.

---

## Phase Week-1a-precutover — Canonical baseline cut

This is the first Week-1 task. It used to be an assumed precondition of
the migrations runner; that made the first Codex pickup ambiguous.

- **Preconditions**: Week-0a green. No prod DB access required.
- **Files**: `src/schema.sql`; `migrations/_archived_2026-04-28/`;
  the eight existing pre-baseline migration files currently in
  `migrations/`.
- **Commands**:
  ```bash
  git status --short
  grep -n "BASELINE_AS_OF" src/schema.sql || true
  find migrations -maxdepth 1 -type f -name "*.sql" | sort
  # fold the four forward migrations into src/schema.sql if absent
  # NB — drop the CONCURRENTLY keyword from any folded-in CREATE INDEX
  # statements. src/schema.sql runs as a single transaction; CONCURRENTLY
  # cannot run inside one. Affects 2026-04-26_address_trgm.sql (4 indexes)
  # and 2026-04-28_pi_identifier_index.sql; search_v2.sql + affiliation.sql
  # already use plain CREATE INDEX IF NOT EXISTS so they fold in as-is.
  # move the four forward + four rollback files into migrations/_archived_2026-04-28/
  ```
- **Postconditions**:
  - `src/schema.sql` starts with
    `-- BASELINE_AS_OF: 2026-04-28`.
  - Schema objects from these forward migrations are present in
    `src/schema.sql`: `2026-04-24_search_v2.sql`,
    `2026-04-25_affiliation.sql`, `2026-04-26_address_trgm.sql`,
    `2026-04-28_pi_identifier_index.sql`.
  - `migrations/_archived_2026-04-28/` contains those four forward
    files plus their four rollback files.
  - `find migrations -maxdepth 1 -type f -name "*.sql"` returns no
    pre-baseline SQL files.
- **Approval gate**: N — repo-only baseline cut; normal review still
  applies before merge.

## Phase Week-1a — Minimal migrations runner (r25 split)

- **Preconditions**: Week 0 phases all green; Week-1a-precutover green.
- **Files**: `scripts/migrate.py` (new — minimal subset); `migrations/`
  tx/no-tx headers retrofitted on any post-baseline files added; nothing else.
- **Commands**:
  ```bash
  python scripts/migrate.py baseline --target=prod   # one-shot — registers BASELINE_AS_OF
  python scripts/migrate.py status --json
  python scripts/migrate.py up --target=prod         # noop on first run (post-baseline migrations folder is empty)
  ```
- **Postconditions**:
  - `psql -tAc "SELECT count(*) FROM schema_migrations"` matches the
    file count in `migrations/` (post-baseline; should start at 0).
  - `migrate up --target=prod` against fresh prod is a noop.
  - Advisory lock prevents two concurrent runs.
- **Approval gate**: Y — touches deploy hot path.
- **Out of scope for 1a**: dry-run, checksums, deploy-hook integration,
  CI gates, style-contract lint. All deferred to Week 1c.

## Phase Week-1b — Runtime-DDL inventory + capture (r25 split)

- **Preconditions**: Week-1a green; `scripts/migrate.py` works.
- **Files**: `docs/runtime-ddl-inventory-<date>.md` (new); 14+
  baseline migration files
  `migrations/0NNN_runtime_ddl_baseline_<file>.sql`;
  source-file deletions of the runtime-DDL callers across `backend/`
  + `scripts/`.
- **Commands**:
  ```bash
  grep -rnE '^\s*(CREATE TABLE|CREATE INDEX|ALTER TABLE)' backend/ scripts/ \
    --include='*.py' --exclude-dir=migrations
  # first commit the inventory grouped by source file and table/index name
  # then capture each group as a baseline migration and delete that runtime caller
  ```
- **Postconditions**:
  - `docs/runtime-ddl-inventory-<date>.md` is committed and includes
    every grep match grouped by source file, object name, and intended
    migration filename.
  - Grep above returns zero matches.
  - Each new migration applied via `migrate up` on staging then prod.
  - Startup logs no longer show "creating table X if not exists".
- **Approval gate**: Y — multi-PR pass touching shared startup code.

## Phase Week-1c — CI gates: syntactic + replay + style + runner extras (r25 split)

- **Preconditions**: Week-1b substantially complete (some lingering
  runtime DDL ok if a single in-flight migration captures it; all gates
  must pass against current master before merge).
- **Files**: `scripts/check_no_runtime_ddl.sh` (new);
  `scripts/check_migration_style.py` (new);
  `.github/workflows/schema-replay.yml` (new);
  `scripts/migrate.py` (extend with `dry-run` + checksum verification +
  deploy-hook integration).
- **Postconditions**:
  - CI fails on a deliberate `CREATE TABLE` outside `migrations/`.
  - CI fails on a migration without `SET lock_timeout` / `SET statement_timeout`.
  - CI fails on a tx-mode migration with explicit `BEGIN` / `COMMIT`.
  - Replay gate green against current master (Stage R22-B postconditions).
  - Deploy hook routes through `migrate up --target=prod` (Week-1
    short-circuit removed once Week 2a green; until then prod-only).
- **Approval gate**: N — CI workflow / lint files are repo-only and
  not shared-prod-DB-mutating. Standard correctness + security review
  still applies before merge. Any later production deploy that activates
  the updated deploy hook uses the normal prod-deploy approval gate.

## Phase Week-1d — Phase-timing middleware (r25 split, parallel)

- **Preconditions**: Week-0c de-async deployed. No dependency on 1a/1b/1c.
- **Files**: `backend/middleware/timing.py` (new); `backend/main.py`
  (wire the middleware).
- **Postconditions**:
  - Every `/api/*` response carries a `Server-Timing` header with
    `auth-ms`, `cache-ms`, `db-ms`, `serialize-ms` segments.
  - Prometheus `/metrics` exposes histograms for each segment.
- **Approval gate**: N — additive instrumentation, no behaviour change.
- **Why parallel**: zero migration-stack dependency. Different reviewer
  can ship this while 1a/1b/1c run on the runner track.

---

## Phase Week-2a — Staging external-service isolation (FIRST hard gate)

**Until this is green, no Week-2b work runs. No new staging workers,
no staging webhooks, no snapshot cron.**

- **Preconditions**: Week 1 green; `/opt/leadpeek/.env.production`
  inventory of secrets that need staging counterparts.
- **Files**: `/opt/leadpeek/.env.staging` (new, on prod server only —
  not in repo); `docker-compose.staging.yml` (modify);
  `scripts/verify_staging_isolation.sh` (new — Stage R22-C);
  `docs/staging-isolation-evidence-<date>.md` (new, one-shot).
- **Commands**:
  ```bash
  # operator: create /opt/leadpeek/.env.staging with staging-only Stripe test
  # keys, staging Supabase, staging webhook secret, DATABASE_URL=leadpeek_staging
  # NB: leadpeek_staging DB doesn't exist yet — Week 2b creates it
  vi docker-compose.staging.yml   # env_file: .env.staging on backend-staging + frontend-staging
                                  # STAGING_MODE: "true"
  docker compose -f docker-compose.staging.yml up -d --force-recreate \
    backend-staging frontend-staging
  bash scripts/verify_staging_isolation.sh
  ```
- **Postconditions** (each is a check the script runs; all four pass):
  - Inside `backend-staging`: `printenv STRIPE_SECRET_KEY` starts `sk_test_`.
  - Stripe CLI test webhook lands at staging backend, not prod.
  - `printenv NEXT_PUBLIC_SUPABASE_URL` = staging-allowlisted URL.
  - `psql $DATABASE_URL -tAc "SELECT current_database()"` from
    backend-staging = `leadpeek_staging` (NB: DB will be missing
    until Week 2b — script handles this case as "isolated, DB pending").
  - Evidence doc committed in `docs/`.
- **Approval gate**: Y (twice) — operator approves the env split BEFORE
  cutover (touches billing/auth surfaces); operator approves Stage R22-C
  results before declaring Week 2a done.
- **Detail**: deep-dive Stage R22-C + Week 2a row.

## Phase Week-2b — Staging DB clone + scrub + workers (gated on Week-2a green)

- **Preconditions**: Week-2a green; isolation-evidence doc committed;
  migrations runner live.
- **Files**: `scripts/staging_scrub.sql` (new — Stage R22-A);
  `scripts/check_scrub_inventory.py` (new); staging snapshot cron
  script (new); `docker-compose.staging.yml` (add `profiles:
  ["test-workers"]` to worker services); `docs/architecture.md`
  (update "shares the prod DB" → "fully independent").
- **Commands**:
  ```sql
  CREATE TABLESPACE staging_data LOCATION '/mnt/volume-hel1-1/pgsql-staging';
  CREATE DATABASE leadpeek_staging TABLESPACE staging_data;
  ```
  ```bash
  # first manual snapshot
  pg_dump -Fc leadpeek | pg_restore -d leadpeek_staging
  psql leadpeek_staging -f scripts/staging_scrub.sql
  # then add cron at 02:30 UTC
  ```
- **Postconditions**:
  - `psql leadpeek_staging -tAc "SELECT count(*) FROM api_keys"` = 0
    morning after first cron run.
  - `psql leadpeek_staging -tAc "SELECT count(*) FROM company_info"`
    matches prod (full clone, not exclusion variant).
  - CI scrub-inventory check green (every `pg_tables` entry classified).
  - Migration runner deploy hook now does `--target=staging` first,
    then `--target=prod` (Week-1 short-circuit removed).
  - `docs/architecture.md` no longer says "share the same DB".
- **Approval gate**: Y — touches scheduled-task surface + `docs/architecture.md`.
- **Detail**: deep-dive Stage R22-A + Week 2b row.

## Phase Week-2 (parallel) — §5c FTS — PROD RAMP SOAK IN PROGRESS (2026-05-02)

Not gated on Week-2a — FTS doesn't touch external surfaces. Shipped via
PRs #33 (initial FTS path) + #34 (smoke fix — split UNION ALL into two
app-level queries with single-token skip-condition).

- **Preconditions**: migrations runner live. ✓
- **Files shipped**: two FTS migrations (expression GIN on
  `company_info.name_normalized` + `denomination.denomination_normalized`);
  `backend/routers/companies/search.py` (FTS as separate app-level call,
  not UNION arm — matches deep-dive §5c decision).
- **Commands shipped**: migrations applied to staging via
  `python3 scripts/migrate.py up --target=staging`; both migrations
  registered in `schema_migrations.applied_by_env='staging'`.
- **Postconditions** (verified):
  - ✓ FTS query path p95 = **81.9 ms** worst-category, against the §5c
    100 ms target. All five r19.5 bench categories tested: trailing
    legal forms (74.4 ms), leading legal forms (28.4 ms), accent
    variants (71.2 ms), NL/FR variants (68.3 ms), common surnames
    (81.9 ms). Evidence: `docs/fts-staging-evidence-2026-05-01.md`.
  - ✓ `SEARCH_FTS_ENABLED` flag verified end-to-end. False-toggle
    probe returned `fts_called=False`; flipped back to `true` for soak.
  - ✓ Prod ramp approved by operator on 2026-05-02; prod migrations
    applied, `SEARCH_FTS_ENABLED=true`, backend recreated healthy, and
    prod smoke passed with maximum category p95 **32.7 ms** after the
    rollback-path validation restored the flag to true. Evidence:
    `docs/fts-prod-ramp-evidence-2026-05-02.md`.
  - ⏳ Activity-log click-through rate regression check — 24h
    post-prod-ramp soak in progress. Must not regress > 5% before this
    phase is marked fully closed.
- **Approval gate**: Y — prod deploy of search path change. ✓ operator
  approved and prod ramp executed on 2026-05-02. This phase is not yet
  closed; final closure waits for the 24h click-through soak.
- **Two-review-agent gate**: ✓ correctness PASS + security PASS via Ollama.

---

## Phase Week-3 — Cancellation watchdog + WAL archiving

- **Preconditions**: Week 1 and Week 2 foundation green; Week-2 FTS prod
  ramp executed, with the 24h click-through soak tracked separately.
  Production Postgres volume paths exist in `/opt/leadpeek/.env.production`
  as `DS_WAL_ARCHIVE_DIR` and `DS_BACKUP_DIR`.
- **Files**: `backend/db.py`, `backend/main.py`,
  `backend/middleware/cancel_watchdog.py`,
  `backend/tests/test_cancel_watchdog.py`,
  `backend/tests/test_db_pool_safety.py`,
  `scripts/configure_wal_archiving.sh`, `scripts/take_base_backup.sh`,
  `docs/week-3-watchdog-wal-evidence-2026-05-02.md`.
- **Commands**:
  ```bash
  pytest backend/tests/test_cancel_watchdog.py backend/tests/test_db_pool_safety.py
  ./scripts/deploy_staging.sh 62.238.14.150
  # staging smoke: cancelled search leaves backend healthy and pool reusable
  # read-only prod audit: SHOW archive_mode/archive_command/wal_level; df -h
  # Gate Y tail, operator-approved production run during quiet window:
  #   sudo bash /opt/leadpeek/scripts/configure_wal_archiving.sh --apply --restart-if-required
  #   sudo bash /opt/leadpeek/scripts/take_base_backup.sh
  ```
- **Postconditions**:
  - Search-only watchdog is enabled for read-only search endpoints and uses
    a dedicated cancel pool with `pg_cancel_backend()` guarded by both PID
    and `application_name=datasnoop:rid=<request-id>`.
  - `backend/db.py::put_connection()` resets `application_name` before pool
    return and discards any non-idle transaction state instead of handing a
    poisoned connection to the next request.
  - Staging deploy is healthy after the watchdog change; a cancelled search
    smoke leaves the next search request successful.
  - WAL archiving writes rotated WALs under `DS_WAL_ARCHIVE_DIR`; the first
    base backup lands under `DS_BACKUP_DIR`; `pg_reload_conf()` and any
    required Postgres restart output is captured in the evidence doc.
    Verified 2026-05-02: archive probe
    `0000000100000045000000A0`, compressed base backup
    `base-20260502T095716Z` size `20G`, manifest present, backend healthy.
- **Approval gate**: Y — production Postgres config edit + reload/restart
  if required by current `archive_mode`, plus first base backup. Prepare the
  branch, PR, staging deploy, read-only audit, and exact command
  autonomously; pause for the operator to approve the prod-mutating tail
  command. ✓ operator approved Codex-run and production postconditions were
  captured on 2026-05-02.
- **Detail**: deep-dive §5b cancellation watchdog + Week 3 row; r21
  `application_name` reset; r25 discard-or-rollback safety net.

## Phase Week-4 — Restore drill + observability stack

- **Preconditions**: Week-3 cancellation watchdog and WAL archiving green;
  first compressed base backup exists under `DS_BACKUP_DIR`; backend
  phase-timing middleware from Week-1d is live.
- **Files**: `backend/main.py`, `backend/tests/test_metrics_admin_gate.py`,
  `scripts/monthly_restore_drill.sh`, `scripts/install_crons.sh`,
  `monitoring/prometheus/datasnoop-slo-rules.yml`,
  `docs/observability-slo-dashboards-2026-05-02.md`,
  `docs/week-4-restore-observability-evidence-2026-05-02.md`.
- **Commands**:
  ```bash
  python -m pytest backend/tests/test_metrics_admin_gate.py -q
  python -m py_compile backend/main.py
  bash -n scripts/monthly_restore_drill.sh scripts/install_crons.sh
  ./scripts/deploy_staging.sh 62.238.14.150
  # staging smoke: /metrics rejects anonymous callers; admin-authenticated
  # /metrics returns Prometheus text with phase histograms
  # Gate Y tail, operator-approved production run:
  #   sudo bash /opt/leadpeek/scripts/monthly_restore_drill.sh --run
  #   sudo bash /opt/leadpeek/scripts/install_crons.sh
  ```
- **Postconditions**:
  - `/metrics` is no longer public; it uses the existing admin role
    dependency shared with `/api/admin/*`.
  - Admin-authenticated `/metrics` still returns
    `datasnoop_request_phase_duration_ms_*` Prometheus histograms.
  - Monthly restore-drill cron is installed in the managed cron block.
  - First restore drill writes a green
    `/opt/leadpeek/scripts/_watchdog_state/restore_drill_last.json`.
    Verified 2026-05-02: full run parsed the manifest, verified all three
    compressed tar payloads, restored schema into a scratch DB, passed core
    relation smoke, and cleanup left `0` scratch DBs behind after the fix.
  - SLO recording/alert rules for total and DB phase p95 are committed.
  - PgBouncer remains deferred unless live connection-budget evidence appears.
- **Approval gate**: Y — backend deploy changes an operational endpoint, and
  the restore-drill cron creates/drops a scratch DB on prod during the first
  run. Prepare branch, PR, staging deploy, and exact production commands
  autonomously; pause for operator approval before the prod-mutating tail.
  ✓ operator approved Codex-run and production postconditions were captured
  on 2026-05-02.
- **Detail**: deep-dive Week 4 row; Week-1d phase-timing middleware; Week-3
  base-backup evidence.

---

## Phase Weeks-5-10 — Person v1 (internal-only by default)

- **Status**: Green — closed 2026-05-02 as internal-only. Public URL
  work remains blocked by the separate Person public URL ramp gates.
- **Preconditions**:
  - Week 1 through Week 4 green.
  - `docs/person-v1-policy.md` exists, even if mostly stubbed.
  - Legal memo remains in flight; it gates public URL work only.
- **Files**:
  - `migrations/2026-05-02_person_v1.sql`
  - `src/schema.sql`
  - `scripts/person_resolver.py`
  - `scripts/install_crons.sh`
  - `backend/feature_flags.py`
  - `backend/routers/people.py`
  - `backend/tests/test_person_v1.py`
  - `frontend/src/lib/api.ts`
  - `frontend/src/app/person/[id]/page.tsx`
  - `docs/person-v1-metrics.md`
  - `docs/person-v1-internal-evidence-2026-05-02.md`
- **Commands**:
  - `python scripts/check_migration_style.py`
  - `bash scripts/check_no_runtime_ddl.sh`
  - `pytest backend/tests/test_person_v1.py -q`
  - `python -m py_compile backend/feature_flags.py backend/routers/people.py scripts/person_resolver.py`
  - `npm --prefix frontend run lint`
  - `python scripts/migrate.py dry-run --target staging`
  - `python scripts/migrate.py up --target staging`
  - `docker compose -f docker-compose.staging.yml up -d --force-recreate backend-staging frontend-staging`
  - `docker exec -e PYTHONPATH=/app leadpeek-backend-staging-1 python /app/scripts/person_resolver.py --incremental`
  - `python scripts/migrate.py dry-run --target prod`
  - `python scripts/migrate.py up --target prod` (Gate Y)
  - `docker compose up -d --force-recreate backend frontend`
  - `docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/person_resolver.py --incremental`
  - `bash /opt/leadpeek/scripts/install_crons.sh`
- **Postconditions**:
  - `PERSON_PUBLIC_URL_ENABLED=false` is the default; the env var
    is read on every request via the feature-flag wrapper.
  - Admin-authenticated access to `/person/<id>` returns the audit
    page; non-admin returns 404.
  - `person`, `person_link`, and `person_merge_log` exist in staging
    and prod; `person_link` includes `source_mention_seq` and
    `source_field`.
  - Tier-A/B/C deterministic resolver is idempotent and includes
    `affiliation`.
  - Internal smoke metrics are committed to `docs/person-v1-metrics.md`.
    Public-ramp metrics against the ~500-row stratified golden set remain
    blocked until the separate public URL gate opens.
- **Detail**: Deep-dive §1 Person v1 schema, deterministic resolver, and
  three public-URL prerequisites; r25 `source_mention_seq` correction.
- **Approval gate**: Y — schema changes + new PII surface.

## Phase Person — public URL ramp (SEPARATE stage)

- **Status**: Green — closed 2026-05-02. Operational checklist items 1-6
  are green; `PERSON_PUBLIC_URL_ENABLED=true` is live in production with
  evidence in `docs/person-v1-public-ramp-evidence-2026-05-02.md`.
- **Preconditions**:
  - Person v1 internal-only is green in production.
  - `docs/person-v1-policy.md` has a written answer (not a placeholder)
    in every section. **Status: ✅ green as of 2026-05-02.**
  - `privacy@datasnoop.be` mailbox and forwarding are provisioned.
  - External Belgian privacy-lawyer engagement remains recommended for
    incident response, but does NOT gate the public URL launch per r26.
  - Person v1 metrics must meet the policy precision/recall threshold
    before the final public flag flip.
- **Files**:
  - `nginx/default.conf` (`limit_req` zone for `/person/*` defence-in-depth).
  - `frontend/src/app/person/[id]/page.tsx` (DSAR/appeal footer link).
  - `frontend/public/robots.txt` and `frontend/src/app/sitemap.xml/route.ts`
    (public indexing and sitemap inclusion once the flag is on).
  - `backend/routers/screener.py` (flag-gated person sitemap feed).
  - `docs/person-v1-golden-set-metrics-<date>.md`.
  - `docs/person-v1-public-ramp-evidence-<date>.md`.
- **Commands**:
  ```bash
  npx eslint "src/app/person/[id]/page.tsx" "src/app/sitemap.xml/route.ts" --max-warnings=0
  pytest backend/tests/test_person_v1.py -q
  docker compose exec -T nginx nginx -t
  docker compose exec -T nginx nginx -s reload
  # Golden-set metric build/evaluation command, documented in the metric PR.
  echo PERSON_PUBLIC_URL_ENABLED=true >> /opt/leadpeek/.env.production
  docker compose up -d --force-recreate frontend backend
  ```
- **Postconditions**:
  - nginx config validates and `/person/*` rate limiting fires at the
    configured cap.
  - DSAR / erasure / merge channels are documented in the policy and the
    public page routes users to `privacy@datasnoop.be`.
  - `robots.txt` allows `/person/`; the sitemap includes person profiles
    only when `PERSON_PUBLIC_URL_ENABLED=true`.
  - Golden-set precision/recall meets the policy threshold before public
    launch. Precision is the safety-critical false-merge gate; recall gaps
    remain an accepted v1 operational completeness risk and must be documented
    in the evidence.
  - `curl https://datasnoop.be/person/<id>` (anon) returns 200 OR
    the policy-decided auth response (302/401).
- **Detail**: Deep-dive §1 Person v1 public URL ramp and
  `docs/person-v1-policy.md` pre-flag-flip checklist.
- **Approval gate**: Y — public PII surface; explicit operator
  approval after every above check.

---

## Phase Weeks-11-14 — Ownership graph (pure SQL)

- **Status**: Green — closed 2026-05-02; production read cutover flipped
  ON 2026-05-02 with evidence in
  `docs/ownership-graph-prod-flip-evidence-2026-05-02.md`.
- **Preconditions**:
  - Week-0 through Person v1 internal-only phases are green on
    `docs/architecture-r25`.
  - Apache AGE remains excluded; this phase is Postgres SQL plus thin
    application read gating only.
  - `OWNERSHIP_GRAPH_READ_ENABLED` defaults OFF in every environment
    until the graph has soaked.
- **Files**: `migrations/2026-05-02_ownership_graph.sql`;
  `src/schema.sql`; `backend/ownership_id.py`;
  `backend/nbb_governance.py`; `scripts/ownership_edge_etl.py`;
  `backend/feature_flags.py`; `backend/routers/companies/structure.py`;
  focused tests and evidence docs.
- **Commands**:
  ```bash
  python scripts/migrate.py up --target=staging
  python scripts/ownership_edge_etl.py --database-url "$STAGING_DATABASE_URL"
  pytest backend/tests/test_ownership_id.py backend/tests/test_ownership_graph_sql.py
  python scripts/migrate.py up --target=prod
  docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/ownership_edge_etl.py
  ```
- **Postconditions**:
  - `ownership_edge` exists with parent-kind CHECK enforcement for
    `company`, `person`, `external_org`, and `unknown`.
  - `ownership_edge_current`, `ownership_edge_as_of(date)`, and the
    recursive UBO SQL helper are present and handle NULL `valid_from`
    using the r25 convention.
  - Historical NBB shareholder, NBB participating-interest, and relevant
    Staatsblad ownership events have loaded idempotently.
  - New NBB governance writes dual-write ownership edges when the table
    exists.
  - Read cutover is gated by `OWNERSHIP_GRAPH_READ_ENABLED`; production
    is ON as of 2026-05-02, with rollback by env flip plus backend recreate.
- **Approval gate**: Y — production schema migration + historical graph
  load mutate prod; review must be green before the prod tail step.

## Phase Weeks-15-22 — Bitemporal append-only fact tables

- **Status**: Green — additive Bitemporal Phase A + Phase B live on
  production (2026-05-02). Evidence:
  `docs/bitemporal-phase-a-evidence-2026-05-02.md` and
  `docs/bitemporal-phase-b-evidence-2026-05-02.md`. `valid_from` NULL
  tightening was checked on 2026-05-02; no table qualifies yet, so nullable
  unknown-start handling remains active. Evidence:
  `docs/bitemporal-valid-from-tightening-2026-05-02.md`.
- **Preconditions**:
  - Week-0 through Ownership graph are green on `docs/architecture-r25`.
  - NBB governance durability is shipped before any bitemporal table work:
    either financial rows and `store_governance_snapshot()` are atomic in
    the same transaction, or a durable `governance_load_log` plus retry
    cron exists.
  - No silent semantic changes: every read site touching administrator,
    shareholder, participating-interest, or affiliation data must be
    classified current-state or history-aware before cutover.
- **Files**: prerequisite durability migration/code; then bitemporal
  migrations for `administrator`, `shareholder`, `participating_interest`,
  and `affiliation`; `src/schema.sql`; NBB caller plumbing; read-path audit
  evidence; focused tests.
- **Commands**:
  ```bash
  python scripts/migrate.py up --target=staging
  pytest backend/tests/test_nbb_governance_durability.py
  python scripts/migrate.py up --target=prod
  # Later bitemporal phases repeat staging/prod migration + targeted read tests.
  ```
- **Postconditions**:
  - Failed governance extraction after a successful financial parse is
    never lost silently; it is either rolled back with the filing or logged
    for retry.
  - Bitemporal columns/views/functions land additively with r22 interval
    semantics and r25 NULL `valid_from` handling.
  - `<table>_current`, `<table>_fact`, and `admins_as_of(valid_at, known_at)`
    helpers are verified before any read-path switch.
  - `shareholders_as_of`, `participating_interests_as_of`, and
    `affiliations_as_of` are verified on staging and production.
  - `SELECT count(*) FROM <table> WHERE valid_from IS NULL = 0` is recorded
    per table before tightening NULLability; all four tables remained
    nonzero on 2026-05-02, so no NOT NULL migration shipped.
- **Approval gate**: Y — production schema changes and loader durability
  changes touch shared prod ingestion; review must be green before prod
  tail steps.

---

## Phase End-of-project — Deferred isolation hardening

**Trigger:** after Bitemporal lands. Operator-decided revisit point
(2026-05-01) for the staging-isolation items punted from Week-2a to
keep the foundation rollout moving.

**Status:** Deferred by operator decision on 2026-05-02. Bitemporal Phase A
landed and database isolation remains green, but Stripe test-mode/webhook
isolation and Supabase project isolation are explicitly skipped for now.
Evidence: `docs/staging-isolation-evidence-2026-05-02.md`.

This phase closes out the full Stage R22-C four-check matrix that
Week-2a abbreviated. None of these are blockers for any earlier phase;
they're a final-pass hardening of the staging environment so future
work can rely on full prod-isolation guarantees.

### Items parked

- **Separate Stripe test-mode key for staging.** Today staging shares
  the same Stripe key as prod (in whichever mode prod uses). End-of-
  project: switch `/opt/leadpeek/.env.staging::STRIPE_SECRET_KEY` to a
  Stripe `sk_test_…` key from the same Stripe account's Test mode (no
  new account; just toggle the dashboard to Test and copy the key).
- **Separate Stripe webhook endpoint for staging.** Today: no separate
  webhook; staging shares prod's webhook URL. End-of-project: create a
  Stripe webhook endpoint pointing at the staging backend, copy the
  signing secret into `/opt/leadpeek/.env.staging::STRIPE_WEBHOOK_SECRET`.
- **Separate Supabase project for staging.** Today: staging uses prod's
  Supabase project (`fpsyraglybfazambxuqb`). End-of-project: create
  `datasnoop-staging` Supabase project, copy URL + anon key into
  `/opt/leadpeek/.env.staging::NEXT_PUBLIC_SUPABASE_URL` +
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Update
  `STAGING_SUPABASE_URL_ALLOWLIST` to match.
- **Re-expand the Stage R22-C verification script** from the Week-2a
  one-check abbreviation back to the full four-check matrix:
  Stripe key namespace, Stripe webhook routing, Supabase project,
  DATABASE_URL.

### Target postconditions when reopened

- Inside `backend-staging`: `printenv STRIPE_SECRET_KEY` starts `sk_test_`.
- A Stripe CLI test webhook lands at the staging backend log, NOT prod.
- `printenv NEXT_PUBLIC_SUPABASE_URL` = staging-allowlisted URL,
  distinct from `fpsyraglybfazambxuqb`.
- `psql $DATABASE_URL -tAc "SELECT current_database()"` from
  backend-staging = `leadpeek_staging` (already met since Week-2b; on
  2026-05-02 the same check used the backend Python/Postgres driver because
  `psql` is not installed in `backend-staging`).
- Updated `docs/staging-isolation-evidence-<date>.md` committed,
  showing all four checks GREEN. The original
  `docs/staging-isolation-evidence-2026-05-01.md` (one-check-only,
  three-DEFERRED) and `docs/staging-isolation-evidence-2026-05-02.md`
  remain in the audit trail.

### Approval gate

Y — touches billing surface (new Stripe webhook), auth surface (new
Supabase project), and `.env.staging` rewrites. Operator-approved
twice, same pattern as Week-2a.

### Cross-reference

Origin of the deferral: Week-2a evidence doc
`docs/staging-isolation-evidence-2026-05-01.md` and PR #21
("Week-2a: staging env split (Stripe/Supabase isolation deferred)").

---

## Conventions used here

- **Postcondition queries that need redaction**: never echo
  `DATABASE_URL` directly. Use `\conninfo` or `SELECT current_database()`
  instead.
- **Commands assume `cwd=/opt/leadpeek` on prod or repo root locally**.
- **All migrations declare `-- @migration: tx` or `no-tx`** per the
  Week 1 style contract — runner refuses files without the header.
- **Feature flags default OFF on first ship**. Each ramp-up has its
  own postcondition row above; no flag flips on without it.
- **"Approval gate: Y"** = operator must approve before merge AND
  before deploy (two distinct approvals if both apply).

---

*Generated alongside deep-dive r24; Codex-adapted for execution
alongside deep-dive r25 (Week 1 split into 1a-precutover / 1a / 1b /
1c / 1d, autonomy framing for non-approval-gated phases, branch-reality
hardening). When a phase ships, update its postconditions with the
actual measured numbers + the date the gate was crossed. This file is
the audit trail at the operational level; deep-dive r-history is the
audit trail at the spec level.*
