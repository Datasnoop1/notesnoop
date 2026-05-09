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
- Morning briefing: default off, opt-in only, and count-only in v1. The worker
  sends via Postmark templates and includes one-click unsubscribe headers.
- Beta cohort: operator follow-up item at beta-ready handoff.
- M3 embedding model/dimension: `qwen3-embedding:0.6b` at 1024 dimensions.
  NoteSnoop calls Ollama Cloud's `/api/embed` endpoint when available. The
  deterministic `lexical_hash` provider is only a local/staging fallback for
  indexing and semantic-search tests when Cloud embeddings are unavailable;
  it can be disabled with `NOTESNOOP_EMBEDDING_ALLOW_LEXICAL_FALLBACK=false`.

## Migrations

Run NoteSnoop migrations independently from Datasnoop:

```bash
python notesnoop/migrate.py up --target=ci
python notesnoop/migrate.py status --target=ci
```

The migration runner reads `NOTESNOOP_TEST_DATABASE_URL`, `MIGRATE_DATABASE_URL`,
or `DATABASE_URL` for local/CI targets.

## Worker Commands

```bash
python -m app.worker
python -m app.worker enqueue-morning-briefings
```

The enqueue command is cron-safe and idempotent per workspace/member/local day.
It only queues opted-in members with at least one open Review Queue item at
their configured local morning hour.
