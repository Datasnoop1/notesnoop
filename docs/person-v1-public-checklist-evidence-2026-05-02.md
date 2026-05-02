# Person v1 public URL ramp checklist evidence — 2026-05-02

Scope: operational checklist items 3-5 from `docs/person-v1-policy.md`.
The public launch flag remains OFF until the golden-set precision/recall
gate passes.

## Changes

- `nginx/default.conf` adds a `person_profile` `limit_req_zone` and applies
  it to `/person/*` before proxying to the frontend.
- `frontend/src/app/person/[id]/page.tsx` adds a footer mail link to
  `privacy@datasnoop.be` for DSAR, rectification, and appeal requests.
- `frontend/public/robots.txt` allows `/person/` for the default crawler
  policy and GPTBot policy.
- `frontend/src/app/sitemap.xml/route.ts` includes person profile URLs from
  a backend sitemap feed.
- `backend/routers/screener.py` exposes `/api/sitemap/persons`, returning an
  empty list while `PERSON_PUBLIC_URL_ENABLED=false`.

## Local validation

- `npx eslint "src/app/person/[id]/page.tsx" "src/app/sitemap.xml/route.ts" --max-warnings=0`
  passed.
- `python -m py_compile backend/routers/screener.py` passed.
- `SUPABASE_HS256_FALLBACK=true SUPABASE_JWT_SECRET=test-secret pytest backend/tests/test_person_v1.py -q`
  passed: 6 tests.
- `npm run lint -- --max-warnings=0` was attempted for the full frontend and
  remained blocked by unrelated pre-existing lint findings outside this
  change set.

## Production nginx proof

PR-branch validation was performed on production with
`PERSON_PUBLIC_URL_ENABLED` still OFF.

Initial command:

- Checked out `feat/person-public-ramp-checklist` on `/opt/leadpeek`.
- `docker compose exec -T nginx nginx -t` passed: syntax OK and test
  successful.
- `docker compose exec -T nginx nginx -s reload` exited 0, but the running
  container still saw the old file-mounted config because `git reset --hard`
  replaced the host file inode behind the bind mount.

Corrected command:

- Re-ran the same branch checkout/reset.
- `docker compose up -d --force-recreate nginx` remounted
  `nginx/default.conf`; Compose also recreated `frontend` as an nginx
  dependency.
- `docker compose exec -T nginx nginx -t` passed: syntax OK and test
  successful.
- First rapid `/person/*` proof returned:

  ```text
       18 200
       98 429
        4 502
  ```

  The 502s were transient during the frontend dependency restart.

Clean post-start proof after the frontend reported healthy:

```text
NAME                  SERVICE    STATUS
leadpeek-frontend-1   frontend   Up About a minute (healthy)
leadpeek-nginx-1      nginx      Up About a minute

     22 200
     98 429
```

Result: nginx `/person/*` rate limiting fires at the configured cap.

## Launch state

`PERSON_PUBLIC_URL_ENABLED` remains OFF. Public anonymous 200 smoke and
frontend/backend recreate are intentionally deferred until the golden-set
metrics document shows the policy precision threshold is met.
