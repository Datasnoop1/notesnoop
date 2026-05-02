# Person v1 Public Ramp Evidence - 2026-05-02

Scope: final production flag flip for public `/person/<id>` URLs.

## Preconditions

- Policy record complete: `docs/person-v1-policy.md`.
- Mailbox and forwarding complete: `privacy@datasnoop.be`.
- Operational checklist items 3-5 complete:
  `docs/person-v1-public-checklist-evidence-2026-05-02.md`.
- Golden-set precision gate complete:
  `docs/person-v1-golden-set-metrics-2026-05-02.md`.
- Two Ollama review agents passed on PR #49.

## Production Change

`PERSON_PUBLIC_URL_ENABLED=true` was set in
`/opt/leadpeek/.env.production`. A timestamped `.env.production` backup was
created first. Backend and frontend were rebuilt and force-recreated so the
runtime code and env were live together.

Rollback remains a flag-only operation:

```bash
cd /opt/leadpeek
python3 - <<'PY'
from pathlib import Path
p = Path('.env.production')
lines = p.read_text(encoding='utf-8').splitlines()
out = [
    'PERSON_PUBLIC_URL_ENABLED=false' if line.startswith('PERSON_PUBLIC_URL_ENABLED=') else line
    for line in lines
]
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
PY
docker compose up -d --force-recreate backend frontend
```

## Smoke Evidence

Production containers after recreate:

```text
leadpeek-backend-1    backend    Up About a minute (healthy)
leadpeek-frontend-1   frontend   Up 40 seconds (healthy)
leadpeek-nginx-1      nginx      Up 41 minutes
```

Feature flag check inside backend:

```text
person_public_url_enabled True
```

Anonymous smoke used sample person id:

```text
23a821fc-aa82-0fae-330c-bc1a5546ddc8
```

Results:

```text
api_status=200
page_status=200
```

Rate-limit proof after bucket refill:

```text
     22 200
     98 429
```

## Result

Public `/person/<id>` URLs are live in production. The launch gate is green:
precision floor met, anonymous page/API smoke passed, and `/person/*` rate
limiting fires at the configured cap.
