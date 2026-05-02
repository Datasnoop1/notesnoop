# Staging Isolation Evidence - 2026-05-01

Phase: Week-2a / Stage R22-C, abbreviated by operator decision.

Operator decision, 2026-05-01: Stripe webhook isolation and Supabase project
isolation are DEFERRED to the end-of-project hardening pass after Bitemporal
lands. During the rollout, staging continues to mirror the production Stripe and
Supabase surfaces. Do not loop back to those surfaces mid-stream.

Cross-reference: `docs/data-architecture-phase-gates.md` will carry the
canonical "Deferred isolation items" section in a separate doc-steward commit.

## Server Env Split

`/opt/leadpeek/.env.staging` was created from `/opt/leadpeek/.env.production`
with only these intended routing changes:

- `DATABASE_URL` database segment points at `leadpeek_staging`.
- `STAGING_MODE=true` is present.
- File mode is `600`.
- Key count is production plus one, matching the appended staging mode marker.

Structural verification output:

```text
env_staging=present
mode_octal=600
database_url_targets_leadpeek_staging=true
staging_mode_true=true
prod_key_count=42
staging_key_count=43
key_count_delta=1
```

## Compose Recreate

`backend-staging` and `frontend-staging` were recreated with
`docker-compose.staging.yml` using `.env.staging` for those two services.
Other staging services were left unchanged.

Service status after recreate:

```text
leadpeek-staging-backend-staging-1    Up (healthy)
leadpeek-staging-frontend-staging-1   Up (healthy)
```

## Abbreviated Smoke Test

Inside `backend-staging`, the runtime env points at the staging database name:

```text
backend_database_name=leadpeek_staging
backend_database_targets_leadpeek_staging=true
backend_staging_mode=true
```

The image does not include the `psql` CLI, so the equivalent Python Postgres
client probe was used for `SELECT current_database()`. The probe fails because
`leadpeek_staging` does not exist yet, which is expected until Week-2b creates
the staging clone.

```text
python_db_client=present
db_probe_status=missing_database_expected_week_2b
```

Week-2a result: green for the simplified DB-routing gate. Full Stage R22-C
parity remains deferred for Stripe/Supabase, and database connectivity awaits
Week-2b.
