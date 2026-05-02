# Staging isolation evidence - 2026-05-02

Operator decision, 2026-05-02: skip the Stripe and Supabase hardening steps
for now. This preserves the Week-2a deferral after Bitemporal Phase A landed.

## Scope

This evidence records the live state at rollout close:

- Database isolation is GREEN.
- `STAGING_MODE=true` is GREEN.
- Stripe test-mode key isolation remains DEFERRED.
- Stripe webhook isolation remains DEFERRED.
- Supabase project isolation remains DEFERRED.

No secret values were printed during verification.

## Structural checks

```text
env_staging_present: True
database_url_targets_leadpeek_staging: True
staging_mode_true: True
stripe_test_key_green: False
stripe_webhook_secret_present: False
supabase_project_distinct: False
```

## Runtime database check

Inside `backend-staging`, the runtime database name is the staging database:

```text
backend_staging_database_segment: leadpeek_staging
backend_staging_current_database: leadpeek_staging
```

The `backend-staging` image does not include a `psql` binary, so the
`SELECT current_database()` check was run through the backend container's
Python/Postgres driver instead of `psql`.

## Deferred external checks

The following remain intentionally open:

- `STRIPE_SECRET_KEY` in staging does not start with `sk_test_`.
- `STRIPE_WEBHOOK_SECRET` is not present in `.env.staging`.
- `NEXT_PUBLIC_SUPABASE_URL` in staging still points at the production
  Supabase project.
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` in staging still matches production.

To close these later, add a Stripe test-mode secret key, a separate Stripe
test webhook for `https://staging.datasnoop.be/api/stripe/webhook`, and a
separate staging Supabase project, then rerun the full Stage R22-C four-check
matrix.
