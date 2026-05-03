# Week-2 FTS production ramp evidence - 2026-05-02

Branch: `feat/week-2-fts-prod-ramp`

Production code under test: `41e0559`

## Operator approval

- Production ramp approved by operator on 2026-05-02.
- Scope: apply the two Week-2 FTS migrations to prod, enable `SEARCH_FTS_ENABLED=true`, recreate the backend, smoke the five r19.5 categories, and begin the 24h click-through soak.
- This evidence PR does not close Week-2 FTS. It records the production
  ramp and leaves the 24h click-through soak gate open.

## Migration state

- Prod dry-run before apply showed exactly 2 pending migrations:
  - `2026-05-01_company_fts_index.sql` (`no-tx`)
  - `2026-05-01_denomination_fts_index.sql` (`no-tx`)
- `python3 scripts/migrate.py up --target=prod` applied 2 migrations to `leadpeek`.
- Both migrations use `CREATE INDEX CONCURRENTLY`; no table rewrite or schema downgrade is needed for rollback.
- `idx_ci_name_tsv` exists on `company_info`.
- `idx_denom_tsv` exists on `denomination`.
- `schema_migrations.applied_by_env` records both FTS migrations as `prod`.

## Runtime flag and deploy

- `/opt/leadpeek/.env.production` mode: `600`.
- `SEARCH_FTS_ENABLED=true` set in `/opt/leadpeek/.env.production`.
- Recreated production backend with `docker compose up -d --build --force-recreate backend`.
- Active production backend: `leadpeek-backend-1`, healthy.
- Active production backend has `SEARCH_FTS_ENABLED=true`.
- Active production backend points at `/leadpeek`.
- Backend image contains the split FTS code path (`_SEARCH_FTS_COMPANY_SQL` present).

## Smoke method

The smoke ran inside the live production backend container and called the same search route helper against `leadpeek`. This avoids browser/session noise while exercising the deployed code, feature flag, connection pool, and production database.

## FTS-on latency smoke

All timings below are milliseconds. Each query reported `fts_called=True`.

| Category | Queries | Category p95 |
| --- | --- | ---: |
| trailing legal forms | `Colruyt NV` 20.5, `Caritas ASBL` 13.0, `Proximus SA` 8.9 | 20.5 |
| leading legal forms | `NV Colruyt` 20.3, `ASBL Caritas` 26.8, `SA Proximus` 32.0 | 32.0 |
| accent variants | `Muller` 10.5, `Mueller` 7.7, `Francois` 24.4 | 24.4 |
| NL/FR variants | `Bruxelles` 13.0, `Brussel` 16.3, `Peter` 17.5 | 17.5 |
| common surnames | `Janssens` 13.3, `De Smet` 24.3, `Peeters` 32.7 | 32.7 |

Overall p95: `32.7 ms`.

## Rollback

Rollback is feature-flag only; no schema downgrade is required. The FTS
indexes can remain in place while the application returns to the trigram
path. The retained GIN indexes should be watched during the soak for size or
write-cost surprises, but no application reads use them while the flag is
off. This rollback path was executed on production during the ramp:

- `SEARCH_FTS_ENABLED=false` + backend recreate: backend healthy,
  container flag `false`, functional query returned 18 results, and the
  probe reported `flag=False` and `fts_called=False`.
- `SEARCH_FTS_ENABLED=true` + backend recreate: backend healthy,
  container flag `true`, functional query returned 18 results, and the
  probe reported `flag=True` and `fts_called=True`.
- Final full FTS-on smoke after restoring `true`: maximum category p95
  `32.7 ms`.

```bash
cd /opt/leadpeek
cp -p .env.production ".env.production.bak-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - <<'PY'
from pathlib import Path
path = Path('/opt/leadpeek/.env.production')
lines = path.read_text().splitlines()
out = []
seen = False
for line in lines:
    if line.startswith('SEARCH_FTS_ENABLED='):
        if not seen:
            out.append('SEARCH_FTS_ENABLED=false')
            seen = True
        continue
    out.append(line)
if not seen:
    out.append('SEARCH_FTS_ENABLED=false')
tmp = path.with_suffix(path.suffix + '.tmp')
tmp.write_text('\n'.join(out) + '\n')
tmp.chmod(0o600)
tmp.replace(path)
path.chmod(0o600)
PY
docker compose up -d --force-recreate --timeout 30 backend
```

Expected rollback verification:

```bash
docker exec leadpeek-backend-1 printenv SEARCH_FTS_ENABLED
# false
```

Functional rollback verification from the ramp: the false-flag probe returned
18 results for `colruyt nv` and reported `fts_called=False`; the restored
true-flag probe returned 18 results and reported `fts_called=True`.

## 24h soak

- 24h post-ramp click-through soak started on 2026-05-02.
- Automation/reminder id: `week-2-fts-click-through-soak-check`.
- Gate: activity-log click-through rate must not regress more than 5% before Week-2 FTS is marked fully closed.
- Final check ran after the full soak window completed:
  `2026-05-02 08:05:00` through `2026-05-03 08:05:00` UTC.
- Click-through signal source: `activity_log`, using company search API calls
  followed by company-detail API views in the same actor/session within
  30 minutes.
- Pre 24h window (`2026-05-01 08:05:00` to `2026-05-02 08:05:00` UTC):
  2 search sessions, 36 search calls, 0 click sessions, CTR `0.00%`.
- Post 24h window (`2026-05-02 08:05:00` to `2026-05-03 08:05:00` UTC):
  4 search sessions, 46 search calls, 0 click sessions, CTR `0.00%`.
- Regression: `0.00` percentage points. Gate result: PASS.
- Caveat: activity volume was low and neither window produced a positive
  click-through event, so this is a regression check rather than a strong
  relevance-quality proof. It verifies the required soak condition: no observed
  click-through regression greater than 5%.
- Privacy note: this evidence records aggregate `activity_log` counts only.
  It contains no raw user identifiers, session identifiers, IPs, secrets, or
  database connection strings.
