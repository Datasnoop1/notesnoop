# Runtime DDL Inventory - 2026-04-30

Phase: Week-1b runtime-DDL inventory + capture.

Scan command equivalent: tracked Python files under `backend/` and `scripts/`, matching `^\s*(CREATE TABLE|CREATE INDEX|ALTER TABLE)` and excluding `migrations/`. Untracked workspace probe/eval files are intentionally excluded because they are not part of the repository branch.

Total tracked files scanned: 129.
Total DDL grep matches: 65.
Total source files with matches: 19.

Count semantics: `Match count` is the number of grep-matched DDL statements. `Objects` is the de-duplicated object list for that source file.

## Spec Gap Callout

The literal Week-1b grep catches `scripts/migrate.py` because the runner owns the `schema_migrations` bootstrap table. That line is migration infrastructure, not app/runtime DDL. Before Week-1c turns this grep into a CI gate, the deep-dive should explicitly choose one of:

- exclude `scripts/migrate.py` from the no-runtime-DDL check; or
- require an explicit waiver marker on the `schema_migrations` DDL.

## Duplicate Object Callout

Several runtime DDL sites create or alter the same object from multiple files. Capture PRs must consolidate or order these carefully rather than blindly creating one independent migration per source file:

- `company_enrichment`: `backend/routers/companies/enrichment.py`, `backend/routers/companies/valuation.py`, `backend/semantic_bootstrap.py`, `scripts/migrate_phase_5_0.py`
- `vlerick_multiple`: `backend/routers/companies/valuation.py`, `scripts/seed_vlerick.py`
- `nace_vlerick_mapping`: `backend/routers/companies/valuation.py`, `scripts/seed_vlerick.py`
- `aggregator_skiplist`: `backend/main.py`, `backend/semantic_bootstrap.py`
- `api_keys`: `backend/routers/public_api.py`, `scripts/issue_api_key.py`
- `activity_log`: duplicate runtime blocks inside `backend/db.py`
- `platform_invoice`: duplicate runtime blocks inside `backend/db.py`

## Capture Hazards To Resolve

- Same-file duplicates: `backend/db.py` has two `activity_log` blocks (lines 324 and 578) and two `platform_invoice` blocks (lines 426 and 561). Capture as one canonical definition per object, then delete both runtime blocks.
- Constraint-in-DO block: `backend/db.py` line 627 is the inner `ALTER TABLE invoice_vendor_pattern ADD CONSTRAINT invoice_vendor_pattern_pattern_len CHECK (...)` inside a guarded `DO $$` block. Preserve the guard or rewrite as safe idempotent migration DDL.
- CTAS rebuild: `backend/nbb_batch_pipeline.py` line 398 is `CREATE TABLE financial_by_year AS` preceded by `DROP TABLE IF EXISTS financial_by_year`. That is a rebuild/materialization step, not an idempotent baseline create. Capture PR must decide whether `financial_by_year` belongs in schema baseline, a materialized table rebuild script, or a managed materialized view.
- Split canonical tables: `company_enrichment`, `vlerick_multiple`, `nace_vlerick_mapping`, `aggregator_skiplist`, and `api_keys` each have multiple runtime creators. The capture migration should choose one canonical table definition and treat the other callers as redundant compatibility shims to remove after migration apply.
- Alter-only dependency: `scripts/migrate_phase_5_0.py` alters `company_enrichment`; it depends on the canonical `company_enrichment` migration from the backend/runtime capture and should run after that migration, not independently first.

## Capture Plan

The table below assigns a provisional owner migration per source file so every grep match has a named capture destination. It is not an executable one-to-one apply plan for duplicate/spec-gap entries. Capture PRs must consolidate duplicate objects, reclassify CTAS/rebuild work, and update this inventory if final migration names differ before applying anything to staging or prod. After each migration has been applied on staging and prod, the paired source change removes the runtime caller.

| Source file | Intended migration | Match count | Objects |
| --- | --- | ---: | --- |
| `backend/ai_client.py` | `migrations/0001_runtime_ddl_baseline_ai_client.sql` | 2 | `translation_cache`, `llm_call_log` |
| `backend/db.py` | `migrations/0002_runtime_ddl_baseline_db.sql` | 28 | `idx_ci_name_trgm`, `idx_admin_name_trgm`, `idx_sh_name_trgm`, `activity_log`, `idx_activity_log_user_date`, `idx_activity_log_endpoint_date`, `idx_activity_log_date`, `valuation_commentary_cache`, `procurement_award`, `insolvency_case`, `staatsblad_event`, `platform_invoice`, `idx_platform_invoice_received`, `idx_platform_invoice_date`, `company_view_history`, `idx_company_view_history_user`, `sector_percentiles_pkey`, `idx_sector_percentiles_nace2`, `invoice_vendor_pattern`, `idx_invoice_vendor_pattern_priority`, `idx_platform_invoice_classified`, `invoice_misclassification_log`, `idx_invoice_misclass_invoice`, `idx_activity_log_session`, `idx_activity_log_ua_date` |
| `backend/embeddings.py` | `migrations/0003_runtime_ddl_baseline_embeddings.sql` | 3 | `company_embedding`, `idx_ce_embedding_hnsw`, `query_embedding_cache` |
| `backend/enrichment_queue.py` | `migrations/0004_runtime_ddl_baseline_enrichment_queue.sql` | 1 | `enrichment_job` |
| `backend/main.py` | `migrations/0005_runtime_ddl_baseline_main.sql` | 1 | `aggregator_skiplist` |
| `backend/nbb_batch_pipeline.py` | `migrations/0006_runtime_ddl_baseline_nbb_batch_pipeline.sql` | 1 | `financial_by_year` |
| `backend/routers/companies/enrichment.py` | `migrations/0007_runtime_ddl_baseline_routers_companies_enrichment.sql` | 4 | `company_enrichment`, `publication_summary`, `ai_insights_feedback` |
| `backend/routers/companies/valuation.py` | `migrations/0008_runtime_ddl_baseline_routers_companies_valuation.sql` | 6 | `vlerick_multiple`, `nace_vlerick_mapping`, `company_enrichment` |
| `backend/routers/favourites.py` | `migrations/0009_runtime_ddl_baseline_routers_favourites.sql` | 5 | `favourite_project`, `favourite_project_member`, `favourite_last_checked`, `people_favourite`, `customer_supplier_list` |
| `backend/routers/people.py` | `migrations/0010_runtime_ddl_baseline_routers_people.sql` | 1 | `people_enrichment` |
| `backend/routers/public_api.py` | `migrations/0011_runtime_ddl_baseline_routers_public_api.sql` | 2 | `api_keys`, `api_call_log` |
| `backend/routers/tier_config.py` | `migrations/0012_runtime_ddl_baseline_routers_tier_config.sql` | 1 | `tier_config` |
| `backend/semantic_bootstrap.py` | `migrations/0013_runtime_ddl_baseline_semantic_bootstrap.sql` | 3 | `company_enrichment`, `meta`, `aggregator_skiplist` |
| `backend/similar_cache.py` | `migrations/0014_runtime_ddl_baseline_similar_cache.sql` | 1 | `ai_similar_cache` |
| `scripts/alert_digest.py` | `migrations/0015_runtime_ddl_baseline_script_alert_digest.sql` | 1 | `user_digest_log` |
| `scripts/issue_api_key.py` | `migrations/0016_runtime_ddl_baseline_script_issue_api_key.sql` | 1 | `api_keys` |
| `scripts/migrate.py` | `migrations/0017_runtime_ddl_baseline_script_migrate.sql` | 1 | `schema_migrations` |
| `scripts/migrate_phase_5_0.py` | `migrations/0018_runtime_ddl_baseline_script_migrate_phase_5_0.sql` | 2 | `company_enrichment`, `idx_enrichment_quality_tier` |
| `scripts/seed_vlerick.py` | `migrations/0019_runtime_ddl_baseline_script_seed_vlerick.sql` | 2 | `vlerick_multiple`, `nace_vlerick_mapping` |

## Inventory By Source File

### `backend/ai_client.py`

Intended migration: `migrations/0001_runtime_ddl_baseline_ai_client.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 86 | `CREATE TABLE` | `translation_cache` | `CREATE TABLE IF NOT EXISTS translation_cache (` |
| 114 | `CREATE TABLE` | `llm_call_log` | `CREATE TABLE IF NOT EXISTS llm_call_log (` |

### `backend/db.py`

Intended migration: `migrations/0002_runtime_ddl_baseline_db.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 310 | `CREATE INDEX` | `idx_ci_name_trgm` | `CREATE INDEX IF NOT EXISTS idx_ci_name_trgm` |
| 315 | `CREATE INDEX` | `idx_admin_name_trgm` | `CREATE INDEX IF NOT EXISTS idx_admin_name_trgm` |
| 319 | `CREATE INDEX` | `idx_sh_name_trgm` | `CREATE INDEX IF NOT EXISTS idx_sh_name_trgm` |
| 324 | `CREATE TABLE` | `activity_log` | `CREATE TABLE IF NOT EXISTS activity_log (` |
| 342 | `CREATE INDEX` | `idx_activity_log_user_date` | `CREATE INDEX IF NOT EXISTS idx_activity_log_user_date` |
| 346 | `CREATE INDEX` | `idx_activity_log_endpoint_date` | `CREATE INDEX IF NOT EXISTS idx_activity_log_endpoint_date` |
| 350 | `CREATE INDEX` | `idx_activity_log_date` | `CREATE INDEX IF NOT EXISTS idx_activity_log_date` |
| 358 | `CREATE TABLE` | `valuation_commentary_cache` | `CREATE TABLE IF NOT EXISTS valuation_commentary_cache (` |
| 372 | `CREATE TABLE` | `procurement_award` | `CREATE TABLE IF NOT EXISTS procurement_award (` |
| 392 | `CREATE TABLE` | `insolvency_case` | `CREATE TABLE IF NOT EXISTS insolvency_case (` |
| 409 | `CREATE TABLE` | `staatsblad_event` | `CREATE TABLE IF NOT EXISTS staatsblad_event (` |
| 426 | `CREATE TABLE` | `platform_invoice` | `CREATE TABLE IF NOT EXISTS platform_invoice (` |
| 443 | `CREATE INDEX` | `idx_platform_invoice_received` | `CREATE INDEX IF NOT EXISTS idx_platform_invoice_received` |
| 447 | `CREATE INDEX` | `idx_platform_invoice_date` | `CREATE INDEX IF NOT EXISTS idx_platform_invoice_date` |
| 454 | `CREATE TABLE` | `company_view_history` | `CREATE TABLE IF NOT EXISTS company_view_history (` |
| 463 | `CREATE INDEX` | `idx_company_view_history_user` | `CREATE INDEX IF NOT EXISTS idx_company_view_history_user` |
| 508 | `CREATE UNIQUE INDEX` | `sector_percentiles_pkey` | `CREATE UNIQUE INDEX IF NOT EXISTS sector_percentiles_pkey` |
| 512 | `CREATE INDEX` | `idx_sector_percentiles_nace2` | `CREATE INDEX IF NOT EXISTS idx_sector_percentiles_nace2` |
| 561 | `CREATE TABLE` | `platform_invoice` | `CREATE TABLE IF NOT EXISTS platform_invoice (` |
| 578 | `CREATE TABLE` | `activity_log` | `CREATE TABLE IF NOT EXISTS activity_log (` |
| 606 | `CREATE TABLE` | `invoice_vendor_pattern` | `CREATE TABLE IF NOT EXISTS invoice_vendor_pattern (` |
| 627 | `ALTER TABLE` | `invoice_vendor_pattern` | `ALTER TABLE invoice_vendor_pattern` |
| 637 | `CREATE INDEX` | `idx_invoice_vendor_pattern_priority` | `CREATE INDEX IF NOT EXISTS idx_invoice_vendor_pattern_priority` |
| 641 | `CREATE INDEX` | `idx_platform_invoice_classified` | `CREATE INDEX IF NOT EXISTS idx_platform_invoice_classified` |
| 647 | `CREATE TABLE` | `invoice_misclassification_log` | `CREATE TABLE IF NOT EXISTS invoice_misclassification_log (` |
| 663 | `CREATE INDEX` | `idx_invoice_misclass_invoice` | `CREATE INDEX IF NOT EXISTS idx_invoice_misclass_invoice` |
| 676 | `CREATE INDEX` | `idx_activity_log_session` | `CREATE INDEX IF NOT EXISTS idx_activity_log_session` |
| 681 | `CREATE INDEX` | `idx_activity_log_ua_date` | `CREATE INDEX IF NOT EXISTS idx_activity_log_ua_date` |

### `backend/embeddings.py`

Intended migration: `migrations/0003_runtime_ddl_baseline_embeddings.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 73 | `CREATE TABLE` | `company_embedding` | `CREATE TABLE IF NOT EXISTS company_embedding (` |
| 82 | `CREATE INDEX` | `idx_ce_embedding_hnsw` | `CREATE INDEX IF NOT EXISTS idx_ce_embedding_hnsw` |
| 442 | `CREATE TABLE` | `query_embedding_cache` | `CREATE TABLE IF NOT EXISTS query_embedding_cache (` |

### `backend/enrichment_queue.py`

Intended migration: `migrations/0004_runtime_ddl_baseline_enrichment_queue.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 46 | `CREATE TABLE` | `enrichment_job` | `CREATE TABLE IF NOT EXISTS enrichment_job (` |

### `backend/main.py`

Intended migration: `migrations/0005_runtime_ddl_baseline_main.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 1116 | `CREATE TABLE` | `aggregator_skiplist` | `CREATE TABLE IF NOT EXISTS aggregator_skiplist (` |

### `backend/nbb_batch_pipeline.py`

Intended migration: `migrations/0006_runtime_ddl_baseline_nbb_batch_pipeline.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 398 | `CREATE TABLE` | `financial_by_year` | `CREATE TABLE financial_by_year AS` |

### `backend/routers/companies/enrichment.py`

Intended migration: `migrations/0007_runtime_ddl_baseline_routers_companies_enrichment.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 140 | `ALTER TABLE` | `company_enrichment` | `ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS publication_summary TEXT` |
| 332 | `CREATE TABLE` | `company_enrichment` | `CREATE TABLE IF NOT EXISTS company_enrichment (` |
| 342 | `ALTER TABLE` | `company_enrichment` | `ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS {col} TEXT` |
| 366 | `CREATE TABLE` | `ai_insights_feedback` | `CREATE TABLE IF NOT EXISTS ai_insights_feedback (` |

### `backend/routers/companies/valuation.py`

Intended migration: `migrations/0008_runtime_ddl_baseline_routers_companies_valuation.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 147 | `CREATE TABLE` | `vlerick_multiple` | `CREATE TABLE IF NOT EXISTS vlerick_multiple (` |
| 158 | `ALTER TABLE` | `vlerick_multiple` | `ALTER TABLE vlerick_multiple` |
| 171 | `ALTER TABLE` | `vlerick_multiple` | `ALTER TABLE vlerick_multiple DROP CONSTRAINT IF EXISTS vlerick_multiple_pkey;` |
| 172 | `ALTER TABLE` | `vlerick_multiple` | `ALTER TABLE vlerick_multiple ADD CONSTRAINT vlerick_multiple_multi_pkey` |
| 178 | `CREATE TABLE` | `nace_vlerick_mapping` | `CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (` |
| 253 | `CREATE TABLE` | `company_enrichment` | `CREATE TABLE IF NOT EXISTS company_enrichment (` |

### `backend/routers/favourites.py`

Intended migration: `migrations/0009_runtime_ddl_baseline_routers_favourites.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 118 | `CREATE TABLE` | `favourite_project` | `CREATE TABLE IF NOT EXISTS favourite_project (` |
| 126 | `CREATE TABLE` | `favourite_project_member` | `CREATE TABLE IF NOT EXISTS favourite_project_member (` |
| 281 | `CREATE TABLE` | `favourite_last_checked` | `CREATE TABLE IF NOT EXISTS favourite_last_checked (` |
| 352 | `CREATE TABLE` | `people_favourite` | `CREATE TABLE IF NOT EXISTS people_favourite (` |
| 442 | `CREATE TABLE` | `customer_supplier_list` | `CREATE TABLE IF NOT EXISTS customer_supplier_list (` |

### `backend/routers/people.py`

Intended migration: `migrations/0010_runtime_ddl_baseline_routers_people.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 705 | `CREATE TABLE` | `people_enrichment` | `CREATE TABLE IF NOT EXISTS people_enrichment (` |

### `backend/routers/public_api.py`

Intended migration: `migrations/0011_runtime_ddl_baseline_routers_public_api.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 68 | `CREATE TABLE` | `api_keys` | `CREATE TABLE IF NOT EXISTS api_keys (` |
| 83 | `CREATE TABLE` | `api_call_log` | `CREATE TABLE IF NOT EXISTS api_call_log (` |

### `backend/routers/tier_config.py`

Intended migration: `migrations/0012_runtime_ddl_baseline_routers_tier_config.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 38 | `CREATE TABLE` | `tier_config` | `CREATE TABLE IF NOT EXISTS tier_config (` |

### `backend/semantic_bootstrap.py`

Intended migration: `migrations/0013_runtime_ddl_baseline_semantic_bootstrap.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 127 | `CREATE TABLE` | `company_enrichment` | `CREATE TABLE IF NOT EXISTS company_enrichment (` |
| 144 | `CREATE TABLE` | `meta` | `CREATE TABLE IF NOT EXISTS meta (` |
| 159 | `CREATE TABLE` | `aggregator_skiplist` | `CREATE TABLE IF NOT EXISTS aggregator_skiplist (` |

### `backend/similar_cache.py`

Intended migration: `migrations/0014_runtime_ddl_baseline_similar_cache.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 43 | `CREATE TABLE` | `ai_similar_cache` | `CREATE TABLE IF NOT EXISTS ai_similar_cache (` |

### `scripts/alert_digest.py`

Intended migration: `migrations/0015_runtime_ddl_baseline_script_alert_digest.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 74 | `CREATE TABLE` | `user_digest_log` | `CREATE TABLE IF NOT EXISTS user_digest_log (` |

### `scripts/issue_api_key.py`

Intended migration: `migrations/0016_runtime_ddl_baseline_script_issue_api_key.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 64 | `CREATE TABLE` | `api_keys` | `CREATE TABLE IF NOT EXISTS api_keys (` |

### `scripts/migrate.py`

Intended migration: `migrations/0017_runtime_ddl_baseline_script_migrate.sql`

Note: this match is the migration runner bootstrap table itself. It is included because the literal Week-1b grep catches it, but it should be handled as migration infrastructure rather than app runtime DDL; this needs a Week-1c checker exclusion or explicit waiver.

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 31 | `CREATE TABLE` | `schema_migrations` | `CREATE TABLE IF NOT EXISTS schema_migrations (` |

### `scripts/migrate_phase_5_0.py`

Intended migration: `migrations/0018_runtime_ddl_baseline_script_migrate_phase_5_0.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 61 | `ALTER TABLE` | `company_enrichment` | `ALTER TABLE company_enrichment` |
| 68 | `CREATE INDEX` | `idx_enrichment_quality_tier` | `CREATE INDEX IF NOT EXISTS idx_enrichment_quality_tier` |

### `scripts/seed_vlerick.py`

Intended migration: `migrations/0019_runtime_ddl_baseline_script_seed_vlerick.sql`

| Line | Kind | Object | Matched text |
| ---: | --- | --- | --- |
| 121 | `CREATE TABLE` | `vlerick_multiple` | `CREATE TABLE IF NOT EXISTS vlerick_multiple (` |
| 131 | `CREATE TABLE` | `nace_vlerick_mapping` | `CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (` |
