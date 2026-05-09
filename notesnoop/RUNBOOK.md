# NoteSnoop Runbook

NoteSnoop runs beside Datasnoop on the same Hetzner host, but with its own
Postgres container, port, volume, WAL archive, base-backup directory, app role,
worker role, backend, frontend, and worker. Do not run Datasnoop database
maintenance commands for NoteSnoop.

## Quick Triage

```bash
cd /opt/leadpeek
COMPOSE="docker compose --env-file .env.staging -f docker-compose.staging.yml -p leadpeek-staging"
$COMPOSE ps notesnoop-postgres-staging notesnoop-backend-staging notesnoop-worker-staging notesnoop-frontend-staging
docker logs --tail=120 leadpeek-staging-notesnoop-worker-staging-1
curl -fsS http://127.0.0.1:8091/api/health
```

If the preview is being checked through `note.datasnoop.be`, remember the
preview front door has basic auth and is not production.

## Backups And Restore

Backup targets:

- WAL archive: `/mnt/volume-hel1-1/notesnoop-wal-archive/`
- Base backups: `/mnt/volume-hel1-1/notesnoop-base-backup/`
- Cron installer: `scripts/install_notesnoop_postgres_crons.sh`
- Base backup command: `scripts/notesnoop_take_base_backup.sh`
- Restore drill command: `scripts/notesnoop_restore_drill.sh`

Install or refresh cron entries:

```bash
cd /opt/leadpeek
bash scripts/install_notesnoop_postgres_crons.sh --env-file /opt/leadpeek/.env.staging
```

Run a base backup:

```bash
cd /opt/leadpeek
bash scripts/notesnoop_take_base_backup.sh --env-file /opt/leadpeek/.env.staging
```

Run a restore drill into a disposable container:

```bash
cd /opt/leadpeek
bash scripts/notesnoop_restore_drill.sh --env-file /opt/leadpeek/.env.staging
```

The restore drill copies `base-latest` into a temporary Docker volume, starts a
fresh `pgvector/pgvector:pg16` container, checks `schema_migrations`,
`public.notes`, and `public.project_invites`, then deletes the disposable
container and volume. It does not print database passwords.

## RLS Troubleshooting

Every app request sets `notesnoop.current_user_id`; webhook ingestion sets
`notesnoop.current_user_id` to the inbound recipient before writing user-owned
rows. The API role is `notesnoop_app` with RLS enforced. The worker role is
`notesnoop_worker` with `BYPASSRLS`.

Useful checks:

```sql
SELECT current_setting('notesnoop.current_user_id', true);
SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename, policyname;
SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity = false;
```

If a user cannot see a note, check project membership first:

```sql
SELECT p.name, p.kind, p.shared, pm.clerk_user_id
FROM note_projects np
JOIN projects p ON p.id = np.project_id
LEFT JOIN project_members pm ON pm.project_id = p.id
WHERE np.note_id = '<note-id>';
```

Personal project notes must remain isolated. Do not disable the Personal
hard-block trigger to make a sharing bug disappear.

## AI Rate-Limit Alerts

Rate limiting is enforced when jobs are created. The backend returns `429` with
`Retry-After` when the per-user or per-workspace bucket is empty.

Triage:

```sql
SELECT key, tokens, last_refill FROM rate_limit_buckets ORDER BY last_refill DESC LIMIT 20;
SELECT state, count(*) FROM ai_jobs GROUP BY state ORDER BY state;
SELECT id, kind, attempts, last_error FROM ai_jobs WHERE state = 'failed' ORDER BY completed_at DESC LIMIT 20;
```

If failures rise, inspect the worker logs and confirm `OLLAMA_API_KEY`,
`OLLAMA_HOST`, `NOTESNOOP_EXTRACTION_MODEL`, and embedding settings are present
in the NoteSnoop containers. Product AI must use Ollama Cloud only.

## Postmark Provider Issues

Inbound webhook path:

```text
/webhooks/email/inbound
```

For staging previews, unsigned webhooks may be enabled with
`NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED=true`. For real staging/production, configure
Postmark Basic Auth or webhook signature validation. Mailgun is supported as a
fallback adapter by sending `X-NoteSnoop-Provider: mailgun` and mapping into the
same internal envelope.

Checks:

```sql
SELECT outcome, count(*) FROM inbound_email_log GROUP BY outcome ORDER BY outcome;
SELECT message_id, recipient_address, outcome, created_at
FROM inbound_email_log
ORDER BY created_at DESC
LIMIT 20;
```

Manual is the v1 default. A saved inbound email should have
`ai_processing_status = 'skipped'` until the user chooses Process with AI.

## Nightly Health

`scripts/nightly_health_report.py` includes a NoteSnoop section when
`NOTESNOOP_HEALTH_DATABASE_URL` or `NOTESNOOP_DATABASE_URL` is configured in the
container running the report. It reports signups, notes, queue depth, failures,
briefings, and calibration events.

Red conditions:

- AI queue depth above 250.
- AI job failure rate above 20% over the last 24 hours.
- Dedicated database query fails.

## On-Call Basics

1. Confirm the dedicated Postgres is healthy before touching app services.
2. Confirm migrations: `python3 notesnoop/migrate.py status --target=staging`.
3. Check worker logs for AI failures or stuck jobs.
4. Check `inbound_email_log` for Postmark delivery issues.
5. If RLS behavior looks wrong, reproduce with the app role and the exact
   `notesnoop.current_user_id`; do not use the worker role for user visibility
   debugging.
6. Never deploy NoteSnoop to production without operator approval.
