# NoteSnoop

Multi-user, AI-powered work-memory tool. Capture notes / forwarded emails, AI
extracts structured memory (projects, people, companies, tasks, meetings,
workflows, reports), user reviews uncertain suggestions, accepted memory has
source-backed relationship links.

This repo was split out from `Datasnoop1/platform` on 2026-05-11 — see
`notesnoop/RUNBOOK.md` and `notesnoop/migrations/` for product docs.

## Layout

```
notesnoop-backend/    FastAPI app + Dockerfile
notesnoop-frontend/   Next.js app + Dockerfile
notesnoop-worker/     Background worker (uses backend code)
notesnoop/            Product docs, migrations, integration tests
scripts/              Notesnoop-only ops scripts (Postgres crons, restore drills)
.github/workflows/    notesnoop-ci.yml
docker-compose.staging.yml   Service definitions for the Hetzner staging host
```

## Staging deploy (Hetzner)

The staging server keeps both this repo (at `/opt/notesnoop`) and the DataSnoop
repo (at `/opt/leadpeek`) side-by-side. `/opt/leadpeek/.env.staging` is the
canonical env file — `/opt/notesnoop/.env.staging` is a symlink pointing at it.

Standard deploy after pushing to `main`:

```bash
ssh -i ~/.ssh/hetzner_leadpeek root@62.238.14.150 "\
  cd /opt/notesnoop && git pull --ff-only origin main && \
  docker compose --env-file /opt/leadpeek/.env.staging \
    -f /opt/leadpeek/docker-compose.staging.yml \
    -f /opt/notesnoop/docker-compose.staging.yml \
    -p leadpeek-staging \
    build notesnoop-backend-staging notesnoop-frontend-staging && \
  docker compose --env-file /opt/leadpeek/.env.staging \
    -f /opt/leadpeek/docker-compose.staging.yml \
    -f /opt/notesnoop/docker-compose.staging.yml \
    -p leadpeek-staging \
    up -d notesnoop-backend-staging notesnoop-worker-staging notesnoop-frontend-staging && \
  docker compose --env-file /opt/leadpeek/.env.staging \
    -f /opt/leadpeek/docker-compose.staging.yml \
    -p leadpeek-staging \
    restart nginx-staging"
```

Both compose files are passed because nginx (in the DataSnoop compose) has
`depends_on` notesnoop services. Project name stays `leadpeek-staging` so
container names + the Docker network are unchanged — nginx config inside
`/opt/leadpeek/nginx/staging.conf` keeps working without edits.

The nginx restart is required because `compose up` may recreate notesnoop
containers with new IPs and nginx caches the old ones.

## Tests

```
# Frontend
cd notesnoop-frontend
npm run lint && npm run test -- --run && npm run build

# Backend integration tests (against a fresh CI db)
ssh root@... "cd /opt/notesnoop && \
  NOTESNOOP_TEST_DATABASE_URL='postgresql://notesnoop_admin:...@127.0.0.1:5434/notesnoop_ci_smoke' \
  /tmp/notesnoop_test_venv/bin/python -m pytest notesnoop/tests/"
```
