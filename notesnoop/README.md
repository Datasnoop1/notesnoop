# NoteSnoop

NoteSnoop is the Snoop suite's project/person memory layer. It shares the
Hetzner host, Postgres instance, and Clerk organization with Datasnoop, but it
uses its own `notesnoop` Postgres schema and its own services.

## v1 Defaults Chosen For Beta

- Email AI default: Manual. The Auto path is implemented behind config and can
  become the default by changing `NOTESNOOP_EMAIL_AI_DEFAULT=auto`.
- First v2 feature queued: Todos & reminders. Chat-with-notes is deferred to
  v2.2.
- Inbound provider: Postmark Inbound first, with the webhook adapter shaped so
  Mailgun can map into the same internal envelope.
- Beta cohort: operator follow-up item at beta-ready handoff.

## Migrations

Run NoteSnoop migrations independently from Datasnoop:

```bash
python notesnoop/migrate.py up --target=ci
python notesnoop/migrate.py status --target=ci
```

The migration runner reads `NOTESNOOP_TEST_DATABASE_URL`, `MIGRATE_DATABASE_URL`,
or `DATABASE_URL` for local/CI targets.
