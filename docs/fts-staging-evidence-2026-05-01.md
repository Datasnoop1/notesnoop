# Week-2 FTS staging evidence - 2026-05-01

Branch: `feat/week-2-fts-smoke-fix`

Staging code under test: `5d2a499`

## Migration state

- `python3 scripts/migrate.py up --target=staging` applied 2 migrations to `leadpeek_staging`.
- `idx_ci_name_tsv` exists on `company_info`.
- `idx_denom_tsv` exists on `denomination`.
- `schema_migrations.applied_by_env` records both FTS migrations as `staging`.

## Runtime flag

- `/opt/leadpeek/.env.staging` mode: `600`.
- Active staging backend: `leadpeek-staging-backend-staging-1`, healthy.
- Active staging backend has `SEARCH_FTS_ENABLED=true`.
- False-toggle probe: after setting `SEARCH_FTS_ENABLED=false` and recreating the staging backend, `_search_fts_enabled()` returned `False` and the search probe reported `fts_called=False`.
- Staging was flipped back to `SEARCH_FTS_ENABLED=true` and recreated for soak.

## Smoke method

The public staging API is intentionally blocked by `StagingGateMiddleware` without an admin JWT. To avoid using or logging a user token, the smoke ran inside the live staging backend container and called the same search route helper against `leadpeek_staging`.

## FTS-on latency smoke

All timings below are milliseconds. Each query reported `fts_called=True`.

| Category | Queries | Category p95 |
| --- | --- | ---: |
| trailing legal forms | `Colruyt NV` 12.1, `Caritas ASBL` 71.6, `Proximus SA` 74.4 | 74.4 |
| leading legal forms | `NV Colruyt` 26.7, `ASBL Caritas` 27.1, `SA Proximus` 28.4 | 28.4 |
| accent variants | `Muller` 68.5, `Mueller` 23.2, `Francois` 71.2 | 71.2 |
| NL/FR variants | `Bruxelles` 22.3, `Brussel` 55.6, `Peter` 68.3 | 68.3 |
| common surnames | `Janssens` 23.4, `De Smet` 81.9, `Peeters` 69.3 | 81.9 |

Overall p95: `81.9 ms`.

## Notes

- The first staging smoke on PR #33 proved FTS was called but missed the 100 ms target on broad common-token queries because registered-name and trade-name FTS ran together.
- Follow-up fix: registered-name FTS now runs first; broad single-token queries skip trade-name FTS once registered-name FTS has enough hits. Multi-token partial pages still run trade-name FTS before falling back.
- The registered-name hydration path now skips the lateral trade-name lookup.
- Production deploy is still held for the Week-2-FTS approval gate. No production flag flip or production deploy was run.
- Activity-log click-through regression check remains a post-production-ramp soak item.
