# Ownership graph evidence - 2026-05-02

Branch: `feat/ownership-graph`  
Base: `docs/architecture-r25`

## Local validation

- `python -m py_compile backend/ownership_id.py backend/nbb_governance.py backend/routers/companies/structure.py scripts/ownership_edge_etl.py`: passed.
- `pytest backend/tests/test_person_v1.py backend/tests/test_ownership_id.py backend/tests/test_ownership_graph_sql.py -q`: passed.
- `python scripts/check_migration_style.py migrations/2026-05-02_ownership_graph.sql`: passed.
- UTF-8/BOM scan for `src/schema.sql`, `migrations/2026-05-02_ownership_graph.sql`, and this phase-gates edit: no BOM, no `c3a2` mojibake bytes.
- Runtime-DDL shell wrapper could not run on this Windows host because `bash.exe` resolves to WSL and no WSL distro is installed. Equivalent `git grep` found only pre-existing runtime-DDL sites outside this phase; no new non-migration DDL was introduced by the ownership files.

## Staging migration and load

Target database verified with `SELECT current_database()`: `leadpeek_staging`.

Migration runner:

```text
database: leadpeek_staging
Applied 1 migration(s).

target: staging
database: leadpeek_staging
baseline_as_of: 2026-04-28
schema_migrations_exists: True
files: 22
applied: 22
pending: 0
checksum_mismatches: 0
```

Initial historical ETL:

```text
shareholder changed rows: 43980
participating_interest changed rows: 133949
staatsblad_event changed rows: 15589
total_edges: 193518
shareholder_edges: 43980
participating_edges: 133949
staatsblad_edges: 15589
person_edges: 12997
external_org_edges: 4675
unknown_edges: 20614
```

Idempotency rerun:

```text
shareholder changed rows: 0
participating_interest changed rows: 0
staatsblad_event changed rows: 0
total_edges: 193518
```

## Staging object checks

```text
objects: true,true,true,true
parent_kind company: 155232
parent_kind external_org: 4675
parent_kind person: 12997
parent_kind unknown: 20614
source_table participating_interest: 133949
source_table shareholder: 43980
source_table staatsblad_event: 15589
sample_child: 0219511295
sample_ubo_rows: 75
current_null_valid_from_rows: 6
```

The six current rows with `valid_from IS NULL` are intentionally retained by
the r25 convention: unknown start dates remain in-force until a later quality
pass can tighten the column.

## Staging app checks

- `backend-staging` and `frontend-staging` rebuilt from `feat/ownership-graph`.
- `/api/health` via staging nginx returned `{"status":"ok","service":"datasnoop-api"}`.
- `OWNERSHIP_GRAPH_READ_ENABLED` is unset in `backend-staging`; default OFF is active.
- Direct FastAPI handler call with the flag OFF returned `404` / `Ownership graph is not enabled`.
- Direct one-off handler call with `OWNERSHIP_GRAPH_READ_ENABLED=true` returned:

```text
direct_flag_on_shareholders: 75
direct_flag_on_participating: 10
direct_flag_on_parents: 75
direct_flag_on_ubo: 75
```

- HTTP request through staging nginx to `/api/companies/0403170701/ownership-graph`
  returned `401 staging_admin_only` before route dispatch, which is expected for
  the admin-gated staging surface.

## Prod migration and load

Target database verified with `SELECT current_database()`: `leadpeek`.

Migration runner:

```text
database: leadpeek
Applied 1 migration(s).

target: prod
database: leadpeek
baseline_as_of: 2026-04-28
schema_migrations_exists: True
files: 22
applied: 22
pending: 0
checksum_mismatches: 0
```

Initial historical ETL:

```text
shareholder changed rows: 44192
participating_interest changed rows: 135113
staatsblad_event changed rows: 15589
total_edges: 194894
shareholder_edges: 44192
participating_edges: 135113
staatsblad_edges: 15589
person_edges: 13121
external_org_edges: 4683
unknown_edges: 20625
```

Idempotency rerun:

```text
shareholder changed rows: 0
participating_interest changed rows: 0
staatsblad_event changed rows: 0
total_edges: 194894
```

## Prod object and app checks

```text
objects: true,true,true,true
parent_kind company: 156465
parent_kind external_org: 4683
parent_kind person: 13121
parent_kind unknown: 20625
source_table participating_interest: 135113
source_table shareholder: 44192
source_table staatsblad_event: 15589
sample_child: 0219511295
sample_ubo_rows: 75
current_null_valid_from_rows: 6
```

- `leadpeek-backend-1` rebuilt from `feat/ownership-graph` and is healthy.
- Internal backend `/api/health` returned `{"status":"ok","service":"datasnoop-api"}`.
- `OWNERSHIP_GRAPH_READ_ENABLED` is unset in prod; default OFF is active.
- Direct FastAPI handler call with the flag OFF returned `404`.
- Direct one-off handler call with `OWNERSHIP_GRAPH_READ_ENABLED=true` returned:

```text
direct_flag_on_shareholders: 75
direct_flag_on_participating: 10
direct_flag_on_parents: 75
direct_flag_on_ubo: 75
```

The public read path remains disabled until the separate soak/cutover
decision flips `OWNERSHIP_GRAPH_READ_ENABLED=true`.
